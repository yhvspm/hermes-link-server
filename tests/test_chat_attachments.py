import base64
import json
import unittest

from hermes_link.api.attachments import ChatAttachmentError, normalize_chat_attachment_request


class ChatAttachmentTests(unittest.TestCase):
    def _normalize(self, attachment: dict, content: str = "请分析") -> dict:
        payload = {"messages": [{"role": "user", "content": content, "attachments": [attachment]}]}
        return json.loads(normalize_chat_attachment_request(json.dumps(payload).encode("utf-8")))

    def test_image_attachment_becomes_openai_image_url_part(self) -> None:
        result = self._normalize({
            "kind": "image",
            "name": "photo.png",
            "media_type": "image/png",
            "data_base64": base64.b64encode(b"png-bytes").decode("ascii"),
        })
        content = result["messages"][0]["content"]
        self.assertEqual(content[0], {"type": "text", "text": "请分析"})
        self.assertEqual(content[1]["type"], "image_url")
        self.assertEqual(content[1]["image_url"]["url"], "data:image/png;base64,cG5nLWJ5dGVz")
        self.assertNotIn("attachments", result["messages"][0])

    def test_utf8_text_file_is_inlined_without_exposing_a_path(self) -> None:
        result = self._normalize({
            "kind": "text",
            "name": "notes.md",
            "media_type": "text/markdown",
            "data_base64": base64.b64encode("# 标题".encode("utf-8")).decode("ascii"),
        })
        content = result["messages"][0]["content"]
        self.assertIn("[附件：notes.md]", content)
        self.assertIn("# 标题", content)
        self.assertNotIn("data_base64", content)

    def test_binary_or_path_like_file_is_rejected(self) -> None:
        with self.assertRaisesRegex(ChatAttachmentError, "Only UTF-8"):
            self._normalize({
                "kind": "text",
                "name": "document.pdf",
                "media_type": "application/pdf",
                "data_base64": base64.b64encode(b"not a pdf").decode("ascii"),
            })
        with self.assertRaisesRegex(ChatAttachmentError, "name is invalid"):
            self._normalize({
                "kind": "image",
                "name": "../photo.png",
                "media_type": "image/png",
                "data_base64": base64.b64encode(b"png").decode("ascii"),
            })
