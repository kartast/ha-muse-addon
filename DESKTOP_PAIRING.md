# Fallback: pair on a desktop Linux box, import to the Green

Why: on the Home Assistant Green, pairing dies in the Muse app a
couple of seconds after the Wi-Fi scan on every attempt (9 attempts,
2 identities, 2 tokens, scan contents placeholder/empty/real-SSID,
and with HA's Bluetooth integration disabled to dedicate the radio).
The SDK's pairing code is unchanged since the version that paired
fine on 2026-10-05 — but that pairing ran on a desktop whose BlueZ
the SDK installer had configured (ExchangeMTU capped at 256, battery
plugin off) on a modern radio. HAOS does not let an add-on change
the host's bluetoothd configuration, so we replicate the proven
environment on the desktop, then import the pairing.

## On omarchy (or any Linux desktop with Bluetooth)

1. `git clone https://github.com/kartast/ha-muse-addon && cd ha-muse-addon/muse-gadget-bridge/sdk`
2. `sudo bash install.sh --from . --sdk-token <the "homeassistant" token from gadgets.muse.ai>`
   The installer configures BlueZ, installs the gadget service and
   opens pairing. (Omit --sdk-token to be prompted. Never paste the
   token anywhere else.)
3. Muse app, Developer mode on: Add Device -> the MuseGadgetXXXXXX
   shown in the installer output -> complete the flow.
4. Send Homer the two small files `/var/lib/musegadget/identity.json`
   and `/var/lib/musegadget/pairing.json`.
5. `sudo bash install.sh --uninstall` in the same folder, so only the
   Green runs the pairing afterwards (refresh tokens rotate; two
   live hosts would break it).

## On the Green (Homer)

An add-on build with identity/pairing import options seeds the two
files into the bridge's state dir at boot; the Green wakes up as the
device you paired, with the Home Assistant commands attached.
