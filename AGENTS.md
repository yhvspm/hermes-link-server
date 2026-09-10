# Hermes Link Server

## Boundaries

Self-hosted is the baseline; Cloud is optional. This independently versioned public repository owns stable client APIs, pairing/device tokens, identity/signing, isolation, DIRECT notifications, Cloud protocol sending, Sessions/Chat/Models/Jobs adapters and Server deployment.

- Agent internal endpoints/version branching belong only in `integrations/hermes_agent/`; temporary patches belong in `compat/`. No Cloud Admin/Worker/providers/database access, `hermes_link_cloud` imports or HarmonyOS implementation.
- Preserve Hermes Link Protocol v1, Cloud Protocol v2 and Event Protocol v1 compatibility; negotiate extensions through capabilities and versioned schemas. Never require App/Server/Cloud version equality.
- Define cross-repository HTTP/schema changes first, then implement in each owning repository within authorized scope. Report boundary conflicts with a concrete alternative and continue independent work.
- Keep keys/tokens in restricted server-side files, never Git/logs. Do not expose arbitrary internal URLs, commands, files, raw logs or Hermes credentials.
- Validate Profile/Server/Installation/Session/Job/Run/Event ownership. Cloud events allow only `chat.completed`, `job.completed`, `job.failed`; exclude full content, prompts, replies and secrets.
- Standard deployment uses a selected direct HTTP port; external TLS/proxies remain optional.

## Working method

- Inspect branch, HEAD, status, relevant diff and untracked paths; preserve existing work.
- Complete authorized work and appropriate checks. Resolve routine choices from context; ask about material ambiguity while continuing independent work. Keep edits focused.
- Commit/push/publication/deployment, credential changes and destructive Git actions require explicit authorization. Honor existing authorization; prepare reviewable results before asking.
- Load relevant skills only. User instructions outrank skill guidance within system/developer constraints; cite any rule blocking progress.
- Delegate independent work when authorized and useful; define ownership and review integration.
- Report results, checks and gaps concisely. Repeat passing checks only for changed inputs, failures or unresolved risk.

Verification: [Server skill](.agents/skills/hermes-server-verify/SKILL.md). CI is the full integration baseline; local checks are not deployment or release acceptance.
