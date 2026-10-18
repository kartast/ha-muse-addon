# Vendored SDK

This is the **Linux Device SDK** from
[facebookincubator/muse-gadget-sdk](https://github.com/facebookincubator/muse-gadget-sdk),
`linux/` directory, at commit `f60347aeb851a1fe9438cfc388721776aa24f275`
(2026-10-16), Apache-2.0 (see the LICENSE at the repository root of the SDK
project; each source file also carries its license header).

Vendored rather than fetched at image-build time so the add-on build is
reproducible and reviewable: what pairs with Muse is exactly what is in
this folder.

Changes versus upstream:

- `src/musegadget/executor.py` — adds four commands
  (`ha.get_states`, `ha.call_service`, `ha.get_config`, `ha.camera_snapshot`)
  in `COMMAND_SPECS` plus handler branches in `Executor.run`, an audit log
  for service calls, and a module-docstring note. Everything upstream in the
  file is untouched; the additions are marked "Home Assistant bridge".
- `src/musegadget/ble_setup.py` — `SetupController.on_disconnect` no longer
  clears the pairing session. In the field the Muse app drops and re-opens
  the BLE connection between the pairing confirmation and the
  Wi-Fi/provisioning step; clearing the session on disconnect made setup
  impossible to complete (observed on the first install, 2026-10-18: the
  handshake reached "pairing confirmed", the app reconnected twice inside
  the confirmation window, and the window closed unpaired). The session
  now survives a disconnect, still bounded by the pairing deadlines in
  `pairing.py`; a fresh `pairing_client_hello` still restarts it. Marked
  "Muse-gadget-bridge change" in the code.
- `src/musegadget/ble_setup.py` (0.1.2, scan behaviour revised in
  0.1.4, device-info field added in 0.1.5) — `device_info` also
  carries `firmware_version` next to `version`, matching the field set
  of a known-working pairing. `_handle_wifi_scan` never offers the placeholder-labelled
  current-connection entry: when no real SSID is detected or configured
  it returns an empty network list so the user can enter their network
  in the app (the Muse app stops before provisioning on the placeholder
  label — documented in the SDK's network tests, observed live
  2026-10-18). The connectivity probe result is logged in
  `device_info`, `_handle_wifi_scan`, and `_run_provision`; the probe
  still gates provisioning itself.
- `src/musegadget/network.py` (0.1.3) — `active_wifi_ssid` first checks
  the `MUSEGADGET_WIFI_SSID` environment variable. The bridge host is
  wired and has no Wi-Fi radio, so neither nmcli nor wpa_cli can produce
  an SSID and the scan fell back to the placeholder label, on which the
  Muse app stops before provisioning (upstream's own network tests
  document that failure mode). `run.sh` sets the variable from the new
  `wifi_ssid` add-on option. One test added in `tests/test_network.py`.
- `tests/test_ble_setup.py` — the upstream disconnect test asserted the
  clearing behaviour and was rewritten for the resume behaviour; two tests
  were added (setup completing across a disconnect, and a fresh hello
  restarting the session after a disconnect). The offline test's scan
  assertion was updated for the always-offer change above.
- `.gitignore` was dropped. Nothing else was added, removed, or changed.

Upstream's `install.sh` is kept for reference; the add-on does not run it
(the Dockerfile performs the equivalent steps, minus systemd and the host
BlueZ reconfiguration, which an add-on cannot and should not do).
