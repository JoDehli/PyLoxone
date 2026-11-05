# Intercom Gen 2 test record

Validated on 4 November 2026 against an isolated Home Assistant lab. This is an
experimental implementation for local native `IntercomV2` devices. The tested
2026.11 beta remains pinned; no production HA upgrade is needed for development.

## Compatibility and repository validation

The full suite passed locally in three separate environments:

| Home Assistant | Python | Result |
| --- | --- | --- |
| 2025.2.4 | 3.13 | 651 passed, 20 native-camera cases skipped |
| 2026.10.4 | 3.14 | 651 passed, 20 native-camera cases skipped |
| 2026.11.0b4 | 3.14 | 671 passed |

The matching test packages and commands are listed in the
[development instructions](../README.md#development-and-compatibility-tests).
CI is configured for the same full-suite matrix. These results are local runs;
they do not imply that remote GitHub jobs have run.

Home Assistant's official hassfest container also passed with zero invalid
integrations. Formatting and Ruff's `E,F` checks passed for the Intercom and
compatibility modules/test files, including shared test helpers.

The repository-wide formatter was also run in check mode, corresponding to
`scripts/lint` without rewriting the checkout. It reports 47 files needing
formatting, all also present in the unchanged upstream commit. Repository-wide
Ruff `E,F` reports 71 existing findings, compared with 75 on upstream commit
`026e8b9`. There are no introduced findings or new suppression rules. The
existing HACS validation workflow still needs to run on the PR.

## Automated coverage

All tests use synthetic configuration, tokens and signalling peers. They do not
connect to a home Miniserver or need hardware credentials.

[`test_intercom_signaling.py`](../tests/test_intercom_signaling.py) checks
authentication, SDP transport credentials, media/ICE mapping and hangup
ownership. Shared synthetic SDP and framed socket peers live in
[`intercom_helpers.py`](../tests/intercom_helpers.py); no `/config` imports or
captured device SDP are needed.

The camera tests also exercise the actual token manager, encrypted device
authentication, SDP translation and signalling reader together. They verify
replacement after device rejection, staged negotiation, early ICE mapping,
socket-loss cleanup and successful reopen with unchanged registry identity.
These cases use synthetic Miniserver responses and device sockets without
replacing the integration's camera or signalling classes.

[`test_intercom_controls.py`](../tests/test_intercom_controls.py) adds 24 cases
using the actual sensor, binary-sensor, switch and button platforms on all three
HA targets. They cover bell/mute feedback, non-optimistic mute commands,
distinct dismiss/output targets, dynamic voice-reply slots, diagnostic states,
locked and PIN-protected controls, malformed/bounded preset data, command
timeouts/redaction, reload cleanup and two Miniserver entries sharing control
UUIDs. These entities do not require the native camera APIs or an Intercom JWT.

| Area | Checks |
| --- | --- |
| Discovery and identity | Multiple entries/devices, native-device filtering, duplicate controls, stable IDs after address changes and reload, room/parent grouping, missing serial metadata |
| Availability and cleanup | Initial cached states, offline/address changes, Miniserver disconnect, entity removal and entry unload |
| Compatibility | Missing or unsupported camera APIs disable only cameras; setup/reload/unload preserve existing platforms and stored credentials on older HA |
| Dedicated authentication | Permission-0 issuance, persistence, renewal, expiry, rejection/replacement, shared requests, viewer cancellation, refresh races, unload and best-effort removal |
| Stored metadata | Corrupt UUIDs and invalid/nonfinite/oversized expiry values; refusing the main app token as an Intercom credential |
| WebRTC mapping | Video-first device negotiation, audio directions/codecs, transport-credential preservation, answer order/media IDs, early and MID-only ICE candidates |
| Transport failure | Connection/challenge/RPC/whole-offer timeouts, stalled writes, malformed messages/SDP, late responses, socket loss and device-ended calls |
| Call ownership | Busy audio is rejected without calling or hanging up; unowned/failed sessions do not send hangup; concurrent and cancelled closers share cleanup |
| Error handling | Safe frontend errors without raw device errors, tokens or SDP; established disconnects report failure; stale callbacks cannot close replacement sessions |
| Resource bounds | Candidate count/size, SDP/key/challenge size and bounded socket cleanup |

The public control mappings follow Loxone's
[Structure File v17 specification, pages 83–85](https://www.loxone.com/enen/wp-content/uploads/sites/3/2026/04/1700_Structure-File.pdf#page=83).
The device identity/registry adapter is shared with the camera, including support
for the legacy registry API on older HA versions. Preset discovery preserves
indexes, accepts at most 32 slots and rejects malformed state data. Output and
voice-reply commands are never issued on startup, during discovery or on reload.

Connection/authentication and each RPC have a 12-second deadline. The entire
offer has a 45-second deadline, followed by bounded cleanup. Owned hangup and
socket-close operations each have a three-second deadline. Temporary token
renewal failures retry after one minute; rejected credentials stop background
retries. These limits prevent a stalled peer from leaving the camera indefinitely
negotiating or blocking entry unload.

## Hardware results

Tested combination:

- Home Assistant Container `2026.11.0b4` in an isolated Docker lab on macOS.
- Miniserver firmware `17.3.10.27` and Intercom Gen 2 firmware `17.00.06.01`.
- Chrome over trusted localhost HTTPS, with HA's two-way camera Labs preview
  and microphone permission enabled.

Manual checks confirmed live video, listening and audible two-way audio in Chrome.
With a Loxone app call active, HA reports
"Intercom audio is in use; close other calls first", the app call continues
uninterrupted, and HA video/audio work after ending the app call and reopening
the HA camera.

A separate local harness exercised the real PyLoxone camera through HA's native
WebSocket API with early trickle ICE. It generated silence for outgoing audio
and counted incoming decoded audio frames; it recorded no media. All of these
checks passed:

1. A second audio call received a busy error while the first kept receiving audio.
2. Opening and closing a secondary video-only viewer left the audio owner active.
3. Closing the listening owner released the device's audio slot.
4. Three consecutive bidirectional audio calls connected and released the slot.
5. Reloading the PyLoxone entry during a call released the slot; a new call then
   connected successfully.

All harness clients were closed afterward. The harness refuses to start when
the Intercom is already occupied. It never forces another call off. A registry
check also verifies that the camera retains its entity ID and is grouped under
its Miniserver, including when serial metadata is absent.

The expanded controls also discovered the physical device's bell, mute, online
and status entities, dismissal button and two configured voice replies in the
lab. A live mute/unmute check confirmed feedback in both directions and restored
the original setting. This installation exposes no output subcontrols, so output
pulses and protected-output exclusion are covered by synthetic tests. The user
also confirmed physical ringing, dismissal and audible playback of the configured
voice replies. Recorder history independently shows the ringing state clearing
about 0.24 seconds after the dismissal action during this test.
After installing the expanded platforms, the native camera probe still connected,
received 236 decoded audio frames, sent 242 generated-silence audio packets and
closed its client. The existing camera entity ID was retained.

During the manual test, the Miniserver subsequently reported device state
`unknown → initializing → online` over about 9.7 seconds. The camera and voice
reply buttons became unavailable during that interval, then recovered
automatically; bell/mute/dismiss entities did not lose their Miniserver connection.
An earlier similar readiness transition is also present in the lab history.
This is an observed device-readiness interruption; its cause is not established,
and the test does not yet isolate ringing from voice-reply playback.
The ring-only follow-up is deferred; no result is claimed for that check.

Loxone's [Intercom changelog](https://www.loxone.com/enen/support/changelog-intercom/)
lists an offline-related entry, `BG-I46518`, under firmware `17.0.6.1` (the tested
`17.00.06.01`). That is relevant context, not confirmation that the same issue
caused this interruption. When Device status returns to Online, close and reopen
an errored camera dialog to start a fresh stream.

Earlier dedicated-token hardware checks confirmed permission `0`, separation
from the unchanged main app token, persistence across restart, scheduled renewal
and replacement after the Miniserver rejected renewal of a revoked token. The
renewal test simulated near-expiry metadata in the stopped lab, then restored
the actual expiry from the Miniserver response.

## Limits and further coverage

- The Python harness did not decode this device's video. Video and audible
  microphone speech are covered by the user's Chrome check, not RTP counts.
- Startup to first incoming audio took roughly 1.7–1.9 seconds across the final
  lifecycle run. This is not a measurement of ongoing playback delay. Previously
  reported lag has not been quantified or attributed to the device or browser.
- Microphone startup stalled in the ChatGPT embedded browser; Chrome worked.
  Safari, Firefox, mobile and HA companion-app clients have not been validated.
- Busy-call coexistence and recovery passed using concurrent lab clients and
  the actual Loxone app. Long calls, physical device reboots and network changes
  remain separate manual checks. Simulated disconnects are automated.
- The tested Intercom continued accepting an issued JWT immediately after
  Miniserver revocation. Revocation is best effort, with no immediate access
  cutoff or active-call termination guarantee.
- Trust/remote connections, custom Intercom controls, snapshots and other
  firmware combinations are outside the validated scope.

To repeat the manual check, use a camera more-info tile over HTTPS, confirm video
and listening, allow microphone access and check speech with someone at the door.
Close the dialog, reopen it and repeat. When testing a competing Loxone app call,
start that call first: HA should report busy while the app call continues. End
the app call and reopen the HA camera to verify recovery. Keep audio streams out
of background dashboard cards, which can occupy the single audio slot.

Keep home addresses, serial numbers, account details, JWTs, raw SDP and captured
signalling outside test fixtures and PR attachments. Only sanitized outcomes
belong in the public test record.
Native PyLoxone does not write raw offers or answers to disk.
