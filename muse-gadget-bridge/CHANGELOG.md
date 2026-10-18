# Changelog

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
