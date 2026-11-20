# Household myQ fork: Home Assistant setup

## What this delivers

A maintained copy of the existing community integration, with our APK research
and reproducible offline validation. This is a cloud-dependent integration, not
a local replacement for the myQ service. The upstream baseline is recorded in
STATE.md. APK findings support its approach but do not prove account or device
compatibility. No live HA installation has been performed by this task.

The upstream integration supports opener covers, lights, camera entities and
video-keypad diagnostics. Device-dependent entities appear only after discovery.
Our keypad is the TC family, firmware 2.58.272. Physical compatibility still needs
checking. Door low-battery and keypad battery must be displayed separately.

## Deployment gate

Preet merges the reviewed PR first. The fork keeps the `myq` domain: it cannot
coexist with a second integration installed at `custom_components/myq`.
Inspect the existing folder, installed integration and HACS repository before
copying anything. If already installed, back up its entire directory and record
its source revision; keep the existing config entry. Do not delete `.storage`.

Before any HA change, read the current `/Volumes/config/AGENTS.md`,
`docs/CONTEXT.md` and `STATE.md` (or their current ha-config checkout copies).
If the share is unavailable, do not treat a stale copy as deployment permission.
Take a current HA backup with an off-VM copy. Deployments, restarts, configuration
and all physical tests below are manual actions for Preet.

## Install the reviewed revision manually

The fork inherits `zip_release: true` in `hacs.json`, but GitHub does not copy
upstream release assets into a fork. Do not assume the upstream HACS install
button installs this fork. A fork release with a `myq.zip` asset is a future
packaging step; use a reviewed checkout for this first deployment. The inherited
release workflow runs on pushes to main when enabled and may publish assets after
merge; verify its result before switching this fork to HACS management.

1. In this repository after merge, record the reviewed commit with `git rev-parse HEAD`.
2. From that clean, reviewed checkout, copy only `custom_components/myq/` into
   HA's `/config/custom_components/myq/`. Preserve the prior folder off-box before
   replacing it. Do not copy tests, APKs or local environments to HA.
3. Preet restarts HA once to load the custom integration. If a config entry
   already exists, inspect its status before trying to add another one.
4. Otherwise open Settings → Devices & services → Add integration → MyQ.
   Prefer browser sign-in if automatic sign-in is rejected. Complete MFA privately;
   paste the callback only into HA. Never save credentials or the callback in Git.
5. Inspect discovered devices and entity IDs. Record the real IDs before writing
   dashboard YAML. Do not enable an automation that opens/closes the garage.
6. Log the installed fork URL, exact commit, version and date under
   "Live changes outside Git" in ha-config `docs/CONTEXT.md` through its own PR.
   HACS must not silently replace this manual fork with an upstream update.

Only the documentation/support metadata differs from upstream at this point.
No snapshot API change was made: `forceUseExisting=true` is an observation to
investigate, not a proven fix for this keypad.

## Observation first

- Check discovered opener state against the app without operating the door.
  Upstream background polling is normally two minutes; it is not an instant alert.
- Keep keypad battery separate from any opener/accessory low-battery warning.
- Do not repeatedly trigger refreshes if authentication or rate limits fail.
- Before the first explicit live session the keypad preview is empty. Afterwards
  it is a stored keyframe: show its capture time so it is not mistaken for live video.
- Use a passive still card for the keypad; tap to more-info for deliberate viewing.
  Disable stream preloading. Do not add a continuously live camera grid.
- An explicit live test may wake the battery device and requires Preet's approval.
  Observe that video stops after leaving; HA's stream worker can remain attached
  beyond the integration's 20-second idle grace period.
- LAN-only video is optional, off by default and still needs cloud signaling.
  Changing it reloads the integration: leave it alone during initial observation.

## Dashboard work, after entity discovery

Prepare a separate ha-config PR: read-only door status, keypad battery, opener
warning and snapshot age. Use the actual discovered entity IDs. No guessed YAML
is included here. Garage open/close controls or actuating automations require
Preet's own `# APPROVED-BY-PREET` approval under the HA project rules.

## Validation and rollback

Run `bash scripts/validate.sh` locally before publishing changes. These are offline
mocked tests, not proof of cloud login, physical compatibility or HA installation.

If a manual installation fails, Preet restores the backed-up integration folder
(or the HA backup if necessary) and restarts HA. Keep account entries and tokens
private. Record the rollback in ha-config CONTEXT through a PR. Do not use garage
commands to test rollback.
