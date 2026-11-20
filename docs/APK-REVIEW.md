# myQ APK review — November 19, 2026

## Scope and provenance

Static review of the installed Android package com.chamberlain.android.liftmaster.myq, version 5.324.0.1132442, version code 1132442, minSdk 31, targetSdk 36. Pulled base.apk and its ARM64 and xxhdpi splits through the already paired ADB connection. Used Androguard to inspect all nine DEX files, relevant method instructions, packaged setup assets, and native-library names.

Base APK SHA-256 is 20d6e5d35a819169867f1b7ebbe13769720ae0b78cb6e26ef95bc9f36dabefb2.

Compared selected source files from bvdcode/home-assistant-myq main. Repository HEAD at review completion was b5a022533cb06ba4ac1614b3338b57045098dc7a. Downloaded files were read directly from main, rather than from a pinned checkout.

Acceptance criteria were to identify device discovery, door-state representation, TC keypad camera transport and power management, and actionable differences from the community integration. This review establishes implementation evidence. Account authorization, server acceptance, and playback on the physical keypad remain untested.

## Findings

### 1. Hub and opener discovery are represented separately

Packaged API paths include gateways, account Devices, and door_openers. Device model methods in classes6.dex read door_state and default missing values to unknown. This supports the existing integration's distinction between account devices and garage-door state.

The community client enumerates /api/v6.2/Accounts/{account_id}/Devices and classifies garagedoor, camera, and lamp families. The APK also contains version-parameterized device endpoints. Static inspection did not establish which API version is selected for this account at runtime.

### 2. The camera has its own Tend/Seedonk stack

The APK contains SeedonkAuthManager, TendDevice, TendAuthHost, and the production Tend media host. Its ARM64 split includes libseedonkp2pWrapper.so and libjingle_peerconnection_so.so. Separate WebRTC/KVS signaling classes also exist.

These demonstrate multiple video components in the application. Their presence alone does not establish which transport the user's TC keypad negotiates. The community integration implements Tend signaling and an H.264 video bridge. Both sides use a Tend camera architecture, but packet-level equivalence was not established.

### 3. Battery-keypad wake-up is a real implementation requirement

The app contains a TendDeviceWakeupPoller, a /devices/{id}/do/wakeup path, and power-status models exposing sleep mode and battery level. DevicePowerStatus.getBatteryLevel reads battLv. Its sleep modes include FULL_POWER, FULL_POWER_BOOT, and LOW_POWER_DEEP_SLEEP.

The community integration already implements bounded on-demand wake-up and waits for full power, and reads battLv. Those mechanisms are supported by APK evidence. This favors an on-demand camera tile for the battery-powered keypad.

### 4. A concrete snapshot-request difference deserves investigation

In classes5.dex, com.chamberlain.myq.features.places.view.e constructs:

    /cxs/api/devices/{id}/cam/recentImage.jpg?size=FHD&forceUseExisting=true

The reviewed integration's generic snapshot method calls the same recentImage.jpg endpoint without those query parameters. A future targeted test could determine whether matching the app's cached-image request improves behavior. This is a candidate difference, not a demonstrated defect or measured battery improvement. The integration already documents passive local previews for video keypads, so its generic snapshot method must not be assumed to run for every keypad dashboard display.

### 5. Door and keypad battery readings must stay distinct

The phone UI showed a low-battery warning on the garage-door card, while keypad settings showed 100%. The APK includes multiple battery representations. The review did not establish whether the door warning refers to the hub's door-position sensor or another opener accessory.

## Practical result

The installed app supplies evidence supporting the community integration's existing Tend keypad approach. No new controller implementation is justified by this review alone.

The next useful work is a focused compatibility review of account discovery, TC keypad discovery, bounded wake-up, and an explicit live-video session. Implementation and deployment must follow Preet-408/ha-config project instructions and PR workflow. The config share was unavailable when previously checked, so its current CONTEXT.md and AGENTS.md must be read before proposing HA changes.

Full native-library decompilation, complete authentication analysis, dynamic traffic capture, and physical device validation were outside this static pass.

## References

- https://github.com/bvdcode/home-assistant-myq
- https://github.com/bvdcode/home-assistant-myq/blob/b5a022533cb06ba4ac1614b3338b57045098dc7a/custom_components/myq/client.py
- https://github.com/bvdcode/home-assistant-myq/blob/b5a022533cb06ba4ac1614b3338b57045098dc7a/custom_components/myq/keypad_wake.py
- https://github.com/bvdcode/home-assistant-myq/blob/b5a022533cb06ba4ac1614b3338b57045098dc7a/custom_components/myq/keypad_state.py
