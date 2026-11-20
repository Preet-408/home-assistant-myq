# Tasks

## MYQ-001 — Maintain a validated household fork
- Owner: codex
- Reviewer: gpt-6.1-sol independent agent (Claude CLI unavailable: not signed in)
- Status: in-review
- Acceptance:
  - Preserve upstream MIT attribution and the existing `myq` integration domain.
  - Record sanitized APK findings, provenance, uncertainties and the exact upstream baseline.
  - Provide installation, observation and rollback steps without inventing entity IDs.
  - Preserve passive keypad previews; do not change wake, polling, authentication or door commands based on untested APK clues.
  - Pass `bash scripts/validate.sh`: lint, formatting, typing and offline upstream tests.
  - Independent review before a draft PR in this fork; Preet merges and deploys.
  - No APKs, credentials, callback URLs, account identifiers or device serials in Git.
