# Draft report: Muse app aborts Linux-gadget pairing ~2–3 s after pairing_confirmed, before provision_v2

Status: DRAFT, not posted. Prepared 2026-10-18 for kartast to file via
GitHub (facebookincubator/muse-gadget-sdk) and/or Muse feedback.

## Summary

Pairing a Linux SDK gadget (protocol v5, community mode) with the Muse
iOS app fails at the same point on every attempt: the handshake and app
consent complete, the gadget sends the encrypted `pairing_confirmed`
status (with the SDK token), and the app disconnects 1.7–3.4 s later
without sending `provision_v2` (in most attempts without `wifi_scan`
either; in two attempts `wifi_scan` was sent and answered, then the app
disconnected). Afterwards the app treats the device as already added:
subsequent Add Device attempts only connect, read `device_info`, and
disconnect; the device never becomes usable.

## Environment

- Gadget: Home Assistant Green (aarch64) running the Linux Device SDK
  at upstream HEAD f60347ae (2026-10-16), as a Home Assistant add-on;
  Bluetooth via the host's BlueZ over D-Bus, CSR8510 (BT 4.0) adapter,
  ATT MTU negotiated 185.
- Gadget commands exposed: Home Assistant entity/service access (the
  pairing failure occurs before any of this matters).
- App: Muse iOS app, Developer mode on; same account previously paired
  a Linux gadget (homelink relay) successfully from a desktop Linux
  host (BlueZ with ExchangeMTU=256).
- Two SDK tokens tried: an existing 48-char token and a freshly minted
  50-char token (gadgets.muse.ai now issues 45-char bodies; the SDK's
  config validator pins the old 48-char shape — separate minor issue,
  worked around locally by widening the pattern).

## Attempt timeline (gadget log, SGT)

All attempts show: connect → subscribed → ATT MTU 185 →
get_device_info → TX device_info (network_ready=true) →
pairing_client_hello → TX pairing_ready → pairing_client_finished
(encrypted) → "pairing confirmed (app consent)" → TX status
(encrypted #0) pairing_confirmed → disconnect.

- 7 full attempts, 2 different gadget identities (fresh state each),
  6 gadget builds, 2 SDK tokens.
- Disconnect delay after pairing_confirmed: 2.3 s, 3.4 s, 2.7 s, 3.4 s,
  2.5 s, 1.7 s.
- wifi_scan was sent in 2 of 7 attempts (answered with a scan result);
  the app still disconnected ~1.5–2 s after the result.
- After the first confirm for an identity, later connections are
  silent probes (~3 s, no GATT traffic) or device_info-only.

## What was verified gadget-side

- Implementation is byte-identical to upstream HEAD; SDK test suite
  passes (222 tests). Pairing also completes end-to-end against the
  SDK's app-side simulator.
- Protocol diffed against a known-working pairing's reference notes:
  service/RX/TX UUIDs, advertisement (ServiceUUIDs + ManufacturerData
  {0xFFFF: [0x00]}), pairing_ready field set, transcript/crypto (two-way
  encrypted traffic works), sdk_token placed top-level in the
  pairing_confirmed status, identity naming (node_id homelink-<suffix>,
  BLE name MuseGadget<SUFFIX>) — all match.
- device_info carries network_ready=true; the connectivity probe
  (TCP to api.muse.ai:443) succeeds from the gadget.
- Ruled out by experiment: stale app-side registration (fresh identity
  minted; app still aborted on first contact), Wi-Fi scan content
  (empty list, placeholder entry, and pre-scan aborts all fail
  identically), session loss on disconnect (session kept for resume),
  missing firmware_version in device_info (added; no change), SDK
  token validity/freshness (fresh token, presented as issued; no
  change).

## Hypothesis

At consent the app registers the device (later attempts see it as
added), then the step that produces the provision_v2 payload — minting
the device credentials server-side — fails or never completes, and the
app aborts setup without an error message. Nothing in the app UI
explains the failure; it just exits the flow.

## Ask

- Is there an app-side log or error surface for the provisioning step?
- Any known issue with community Linux gadgets on current iOS app
  builds, BT 4.0 adapters / MTU 185, or accounts outside the US?
