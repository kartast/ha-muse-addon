# Changelog

## 0.1.7

- Desktop-pairing fallback: new `identity_import` and `pairing_import`
  options. Paste the identity.json / pairing.json contents from a
  machine where pairing succeeded and the bridge seeds them into its
  state directory at startup, adopting that identity and pairing.
  Invalid JSON is rejected without touching existing files; clearing
  the options afterwards is safe (nothing is ever deleted).

## 0.1.6

- Accept the SDK tokens gadgets.muse.ai issues now: they carry a
  45-character body (50 characters total), while the SDK's validator
  pinned the original 43-character shape and refused the token before
  pairing could start. Validation now accepts any plausible issued
  length; the Muse backend remains the real judge at pairing time.

## 0.1.5

- The pairing device-info response now also carries `firmware_version`
  (alongside `version`), matching the field set of a known-working
  pairing supplied by the user. Five pairing attempts died ~3 s after
  the app consented, before provisioning; this closes the one
  remaining protocol-field gap against that reference.

## 0.1.4

- The Wi-Fi scan no longer offers the placeholder "Use current
  connection" entry at all: the Muse app stops on that label, and on a
  wired host it was the only entry. With no real network name detected
  (or configured via `wifi_ssid`), the scan result is now empty so the
  user can enter their network name in the app during pairing.

## 0.1.3

- Fix pairing stopping at the Wi-Fi step: the Muse app only continues to
  provisioning when the scan offers a real network name (the SDK's own
  tests document the app stopping on the placeholder label). This host is
  wired and has no Wi-Fi radio to read an SSID from, so a new `wifi_ssid`
  option supplies the household network name for the scan to offer.

## 0.1.2

- Fix the app exiting at the Wi-Fi step: the Wi-Fi scan now always offers
  the current connection instead of an empty list when the connectivity
  probe fails (this bridge is wired into an always-online host), and the
  probe result is logged at device-info, scan, and provisioning time so a
  failing probe is visible in the add-on log.

## 0.1.1

- Fix pairing never completing: the Muse app drops and re-opens the BLE
  connection between the pairing confirmation and the provisioning step,
  and the vendored SDK cleared the pairing session on every disconnect.
  The session now survives a disconnect (still bounded by its own
  confirmation/provisioning deadlines) so setup can resume on the new
  connection. See `sdk/VENDOR.md`.

## 0.1.0

- First prototype: Muse Gadgets Linux Device SDK packaged as an add-on,
  with `ha.get_states`, `ha.call_service`, `ha.get_config`, and
  `ha.camera_snapshot` commands and an audit log of service calls.
