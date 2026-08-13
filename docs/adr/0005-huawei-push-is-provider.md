# ADR 0005: Huawei Push is a provider

Status: Accepted

## Decision

Hermes Link Cloud owns a `NotificationProvider` interface. Huawei Push is the current `HuaweiProvider`, not the definition of Cloud and not a core Hermes Link dependency.

## Consequences

Provider credentials stay in Cloud Worker configuration. Adding APNs, FCM or another provider requires its own implementation and tests but no App-to-Hermes dependency change.

