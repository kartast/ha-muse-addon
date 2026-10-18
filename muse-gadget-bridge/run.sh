#!/usr/bin/env bash
# Muse Gadget Bridge add-on entrypoint.
#
# Runs as an s6 longrun service (rootfs/etc/s6-overlay/s6-rc.d/musegadget),
# which restarts it if it exits. Plain foreground bash: add-ons have no
# systemd, and the musegadget service is itself a foreground process.
#
# Jobs:
#   1. Copy the SDK token from the add-on options (/data/options.json) into
#      the musegadget state dir, where the SDK reads it (file mode 0600).
#   2. Point the SDK at the host D-Bus system bus (host_dbus: true).
#   3. If the device is not paired yet, open the 10-minute BLE pairing
#      window once per start. Restart the add-on to re-open it.
#   4. Run the musegadget service in the foreground.
#
# Paths can be overridden from the environment; the repo tests use that.

set -u

OPTIONS_JSON="${OPTIONS_JSON:-/data/options.json}"
STATE_DIR="${MUSEGADGET_STATE_DIR:-/data/musegadget}"
MUSEGADGET_BIN="${MUSEGADGET_BIN:-/opt/musegadget/venv/bin/musegadget}"
export MUSEGADGET_STATE_DIR="$STATE_DIR"
export MUSEGADGET_SOCKET="${MUSEGADGET_SOCKET:-/run/musegadget/musegadget.sock}"
export MUSEGADGET_RUN_AS="${MUSEGADGET_RUN_AS:-muse}"
export PYTHONUNBUFFERED=1

say() { printf '[muse-gadget-bridge] %s\n' "$*"; }

sync_sdk_token() {
    # Echoes "written" when a token was copied from the options, else "absent".
    python3 - "$OPTIONS_JSON" "$STATE_DIR/sdk_token" <<'PYEOF'
import json, os, sys
options_path, token_path = sys.argv[1], sys.argv[2]
try:
    with open(options_path, encoding="utf-8") as f:
        options = json.load(f)
except (OSError, ValueError):
    print("absent"); sys.exit(0)
token = str(options.get("sdk_token") or "").strip()
if not token:
    print("absent"); sys.exit(0)
os.makedirs(os.path.dirname(token_path), mode=0o700, exist_ok=True)
fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as f:
    f.write(token + "\n")
print("written")
PYEOF
}

configured_wifi_ssid() {
    # Echoes the wifi_ssid option — the household Wi-Fi name the pairing
    # scan should offer — or nothing when it is not set. This host is wired
    # and has no Wi-Fi radio to read an SSID from, and the Muse app stops
    # before provisioning when the scan offers only the placeholder label,
    # so the real name has to come from the configuration.
    python3 - "$OPTIONS_JSON" <<'PYEOF'
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as f:
        options = json.load(f)
except (OSError, ValueError):
    print(""); sys.exit(0)
ssid = options.get("wifi_ssid")
print(ssid.strip() if isinstance(ssid, str) else "")
PYEOF
}

import_state_files() {
    # Seeds identity.json / pairing.json from the identity_import /
    # pairing_import options: the desktop-pairing fallback, for pairing on
    # a machine whose Bluetooth environment works and running here. Prints
    # one line per file imported or rejected; empty options are skipped and
    # nothing is ever deleted, so clearing the options afterwards is safe.
    python3 - "$OPTIONS_JSON" "$STATE_DIR" <<'PYEOF'
import json, os, sys
options_path, state_dir = sys.argv[1], sys.argv[2]
try:
    with open(options_path, encoding="utf-8") as f:
        options = json.load(f)
except (OSError, ValueError):
    sys.exit(0)
for option_key, filename in (("identity_import", "identity.json"),
                             ("pairing_import", "pairing.json")):
    raw = options.get(option_key)
    if not isinstance(raw, str) or not raw.strip():
        continue
    try:
        data = json.loads(raw)
    except ValueError:
        print(f"rejected {filename}: the {option_key} option is not valid JSON")
        continue
    if not isinstance(data, dict):
        print(f"rejected {filename}: the {option_key} option must be a JSON object")
        continue
    payload = json.dumps(data, indent=2) + "\n"
    target = os.path.join(state_dir, filename)
    try:
        with open(target, encoding="utf-8") as f:
            if f.read() == payload:
                continue
    except OSError:
        pass
    os.makedirs(state_dir, mode=0o700, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(payload)
    print(f"imported {filename}")
PYEOF
}

main() {
    mkdir -p "$STATE_DIR" "$(dirname "$MUSEGADGET_SOCKET")"
    chmod 700 "$STATE_DIR" 2>/dev/null || true

    while IFS= read -r import_line; do
        [ -n "$import_line" ] && say "State import: $import_line"
    done <<EOF
$(import_state_files)
EOF

    case "$(sync_sdk_token)" in
        written) say "SDK token loaded from the add-on configuration." ;;
        *) say "WARNING: no SDK token in the add-on configuration. Set sdk_token, then restart the add-on." ;;
    esac

    wifi_ssid="$(configured_wifi_ssid)"
    if [ -n "$wifi_ssid" ]; then
        export MUSEGADGET_WIFI_SSID="$wifi_ssid"
        say "Pairing Wi-Fi scan will offer the configured network name."
    fi

    if [ -S /run/dbus/system_bus_socket ] && [ -z "${DBUS_SYSTEM_BUS_ADDRESS:-}" ]; then
        export DBUS_SYSTEM_BUS_ADDRESS="unix:path=/run/dbus/system_bus_socket"
        say "Using the host D-Bus system bus for Bluetooth."
    else
        say "WARNING: host D-Bus socket not found at /run/dbus/system_bus_socket; Bluetooth pairing needs host_dbus."
    fi

    if [ ! -f "$STATE_DIR/pairing.json" ]; then
        say "Not paired yet: opening the Bluetooth pairing window for 10 minutes."
        say "In the Muse app: Settings > Devices > Developer mode ON, then Add Device, standing near this machine."
        "$MUSEGADGET_BIN" pair || say "Pairing window closed without pairing; restart the add-on to try again."
    fi

    say "Starting the Muse gadget service (commands run as '$MUSEGADGET_RUN_AS')."
    exec "$MUSEGADGET_BIN" run
}

if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    main "$@"
fi
