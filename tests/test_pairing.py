from __future__ import annotations

import sqlite3
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from hermes_link.pairing import PairingError, PairingStore
from hermes_link.pairing import store as pairing_store_module


class PairingStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "pairing.db"
        self.store = PairingStore(self.path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_ticket_contains_no_token_and_exchanges_once(self) -> None:
        ticket = self.store.create_ticket(
            "https://hermes.example.test",
            "test-mobile-token-123456",
            ttl_seconds=600,
            now=100,
        )
        self.assertIn("/api/mobile/pair?code=", ticket.pairing_url)
        self.assertNotIn("test-mobile-token-123456", ticket.pairing_url)
        code = ticket.pairing_url.split("code=", 1)[1].split("&", 1)[0]
        exchanged = self.store.exchange(code, now=101)
        self.assertEqual(exchanged["base_url"], "https://hermes.example.test")
        self.assertIn("device_token", exchanged)
        self.assertIn("device_id", exchanged)
        self.assertNotIn("api_token", exchanged)
        self.assertTrue(self.store.authenticate_device_token(str(exchanged["device_token"])))
        with self.assertRaises(PairingError) as context:
            self.store.exchange(code, now=102)
        self.assertEqual(context.exception.code, "pairing_used")

    def test_ticket_accepts_http_ip_endpoint(self) -> None:
        ticket = self.store.create_ticket(
            "http://203.0.113.42:18765",
            "test-mobile-token-123456",
            now=100,
        )
        self.assertTrue(ticket.pairing_url.startswith("http://203.0.113.42:18765/api/mobile/pair?"))

    def test_device_token_scope_and_revoke(self) -> None:
        ticket = self.store.create_ticket(
            "https://hermes.example.test",
            "test-mobile-token-123456",
            profile_ids=["mobiletest"],
            now=100,
        )
        code = ticket.pairing_url.split("code=", 1)[1].split("&", 1)[0]
        exchanged = self.store.exchange(code, now=101)
        device_token = str(exchanged["device_token"])
        self.assertTrue(self.store.authenticate_device_token(device_token, "mobiletest"))
        self.assertFalse(self.store.authenticate_device_token(device_token, "default"))
        self.assertTrue(self.store.revoke_device_token(device_token))
        self.assertFalse(self.store.authenticate_device_token(device_token, "mobiletest"))

    def test_expired_and_invalid_codes_are_rejected(self) -> None:
        ticket = self.store.create_ticket(
            "https://hermes.example.test",
            "test-mobile-token-123456",
            ttl_seconds=30,
            now=100,
        )
        code = ticket.pairing_url.split("code=", 1)[1].split("&", 1)[0]
        with self.assertRaises(PairingError) as context:
            self.store.exchange(code, now=130)
        self.assertEqual(context.exception.code, "pairing_expired")
        with self.assertRaises(PairingError) as context:
            self.store.exchange("too-short", now=101)
        self.assertEqual(context.exception.code, "pairing_invalid")

    def test_sqlite_file_is_restricted_when_supported(self) -> None:
        self.store.create_ticket(
            "https://hermes.example.test",
            "test-mobile-token-123456",
            now=100,
        )
        connection = sqlite3.connect(self.path)
        try:
            columns = [row[1] for row in connection.execute("PRAGMA table_info(pairing_tickets)")]
        finally:
            connection.close()
        self.assertEqual(
            columns,
            [
                "code_hash",
                "base_url",
                "api_token",
                "api_token_hash",
                "profiles_json",
                "created_at",
                "expires_at",
                "used_at",
            ],
        )

    def test_legacy_device_table_is_migrated_before_exchange(self) -> None:
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                """
                CREATE TABLE pairing_devices (
                    device_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    base_url TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    last_used_at INTEGER NOT NULL,
                    revoked_at INTEGER
                )
                """
            )
            connection.commit()
        finally:
            connection.close()

        ticket = self.store.create_ticket(
            "https://hermes.example.test",
            "test-mobile-token-123456",
            profile_ids=["default"],
        )
        code = ticket.pairing_url.split("code=", 1)[1].split("&", 1)[0]
        exchanged = self.store.exchange(code)
        self.assertTrue(str(exchanged["device_token"]).startswith("hmd_"))
        connection = sqlite3.connect(self.path)
        try:
            columns = [row[1] for row in connection.execute("PRAGMA table_info(pairing_devices)")]
        finally:
            connection.close()
        self.assertIn("profiles_json", columns)

    def test_qr_cli_uses_server_token_environment_without_printing_url(self) -> None:
        rendered: list[str] = []

        class FakeQrCode:
            def __init__(self, **_kwargs: object) -> None:
                pass

            def add_data(self, value: str) -> None:
                rendered.append(value)

            def make(self, **_kwargs: object) -> None:
                pass

            def print_ascii(self, **_kwargs: object) -> None:
                print("[QR]")

        fake_qrcode = type("FakeQrcode", (), {"QRCode": FakeQrCode})
        output = StringIO()
        with patch.dict(sys.modules, {"qrcode": fake_qrcode}), patch.dict(
            os.environ,
            {"HERMES_LINK_MOBILE_API_TOKEN": "test-mobile-token-123456"},
            clear=False,
        ), patch.object(
            sys,
            "argv",
            [
                "pairing.store",
                "--base-url",
                "https://hermes.example.test:8443",
                "--db",
                str(self.path),
                "--qr",
            ],
        ), redirect_stdout(output):
            pairing_store_module.main()

        self.assertEqual(len(rendered), 1)
        self.assertIn("/api/mobile/pair?code=", rendered[0])
        self.assertNotIn(rendered[0], output.getvalue())
        self.assertNotIn("test-mobile-token-123456", output.getvalue())


if __name__ == "__main__":
    unittest.main()
