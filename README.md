# ha-muse-addon

A Home Assistant add-on repository containing one add-on,
**Muse Gadget Bridge** (`muse-gadget-bridge/`), which runs the Muse Gadgets
Linux Device SDK inside Home Assistant OS so a Home Assistant Green appears
in Muse as a device and Muse can see and control the whole house.

- Install and design notes: [BUILD_NOTES.md](BUILD_NOTES.md)
- Add-on documentation: [muse-gadget-bridge/DOCS.md](muse-gadget-bridge/DOCS.md)
- Mock tests (no hardware needed): `tests/` — run `./tests/run_tests.sh`.

The SDK is vendored under `muse-gadget-bridge/sdk/` (Apache-2.0; see
`muse-gadget-bridge/sdk/VENDOR.md`). No real SDK token exists anywhere in
this repository: the token is entered in the add-on configuration at install
time and never leaves the add-on's private data folder.
