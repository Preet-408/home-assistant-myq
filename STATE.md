# State

## Baseline
- Fork: Preet-408/home-assistant-myq, upstream bvdcode/home-assistant-myq.
- Upstream commit: b5a022533cb06ba4ac1614b3338b57045098dc7a; manifest version 0.2.17.
- Runtime implementation is unchanged. Only ownership/support metadata and project documentation/tooling are being adapted.
- This repository is separate from Preet-408/ha-config; tracked HA YAML belongs in that repository.

## Needs Preet
- Merge the reviewed PR and apply the manual deployment steps in docs/HA-SETUP.md.
- Complete the account login privately in HA; then approve any live camera/garage tests separately.

## 2026-11-19 — MYQ-001
- Did: Fork created; sanitized research and installation plan prepared. Offline checks pass: 472 tests, Ruff lint/format and mypy (70 source files). Independent review by gpt-6.1-sol; Claude CLI was not signed in.
- PR: pending.
- Left: Physical discovery, cloud login, stream negotiation and battery interpretation unverified.
- Preet must: Merge/deploy; no live HA changes have been made by this task.
