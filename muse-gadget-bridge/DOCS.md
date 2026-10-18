# Muse Gadget Bridge

Turns this Home Assistant into a Muse device, using the open-source Muse
Gadgets Linux Device SDK. Once paired, Muse can see every entity and call
every service in the house — full access, deliberately, no allowlist. Every
service call Muse makes is written to an audit log.

## Configuration

| Option | What it is |
| --- | --- |
| `sdk_token` | Your Muse Gadgets SDK token (`mgst_…`) from [gadgets.muse.ai](https://gadgets.muse.ai/settings/sdk-tokens) (Account → SDK tokens). Paste it here; it is stored only in this add-on's private data. Changing it later requires re-pairing (Muse records the token at pairing time). |
| `wifi_ssid` | Optional. The name of your home Wi-Fi network, exactly as it appears on your phone. This machine is wired and has no Wi-Fi radio to read the name from; if set, pairing offers this name as the bridge's current connection. If left empty, the pairing scan offers nothing and you enter your network name in the Muse app instead. The bridge ignores any Wi-Fi credentials the app sends back. |

## Pairing

1. Set `sdk_token` and `wifi_ssid` above and start the add-on.
2. Open the add-on **Log** tab. On first start it opens a 10-minute Bluetooth
   pairing window and prints the device name (`MuseGadgetXXXXXX`).
3. Stand near this machine with your phone. In the Muse app: **Settings →
   Devices → Developer mode** ON, then **Add Device**, and pick the
   `MuseGadget…` name. Muse will warn that this is a community device;
   continue. When asked for Wi-Fi, pick the network shown — the machine is
   already online, no password is needed.
4. The log will show the device registering with Muse. After that, pairing
   survives restarts and reboots.

To pair again (new token, new phone), restart the add-on while unpaired
state is cleared — or just restart: an unpaired bridge opens the window on
every start.

## What Muse can do

The standard Linux gadget commands (`system.run`, `file.read`, `file.write`,
`device.health` — these run inside this add-on's container as the
unprivileged `muse` account), plus:

| Command | Effect |
| --- | --- |
| `ha.get_states` | All entity states (paged), or one entity / one domain |
| `ha.call_service` | Any `domain.service` with any data — lights, locks, alarm, covers, Home Assistant itself |
| `ha.get_config` | Core configuration (version, location, components) |
| `ha.camera_snapshot` | A camera's current JPEG, in base64 chunks |
| `ha.automation_get` | One automation's full configuration (triggers, conditions, actions) by its config id |
| `ha.automation_save` | Create or update an automation from its full configuration |
| `ha.automation_delete` | Delete an automation by its config id |

## Audit log

Every `ha.call_service` call — and every `ha.automation_save` and
`ha.automation_delete` — appends one JSON line to `/data/audit.log`
inside the add-on's private data folder (timestamp, service, entity ids,
success or failure) and prints the same line, prefixed `audit`, to this
add-on's log. Review past calls in the Log tab or by reading the file from a
backup of the add-on data.

## Notes and limits

- Bluetooth is shared with Home Assistant through the host's BlueZ (this
  add-on uses `host_dbus`), so the Bluetooth integration keeps working. BLE
  pairing from inside a container is the one part of this build that can
  only be proven on the real machine — see `BUILD_NOTES.md` in the
  repository for the full risk list.
- Programs on the device can message Muse with
  `musegadget send-user-msg "…"` from inside the container.
