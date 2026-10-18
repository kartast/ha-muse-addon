# BUILD_NOTES — Muse Gadget Bridge add-on

A Home Assistant add-on that runs the Muse Gadgets **Linux Device SDK**
inside Home Assistant OS, so the Home Assistant Green pairs with Muse as a
device and Muse can see and control the whole house.

Status: **prototype, mock-tested off-hardware.** Everything that can be
checked without a Green is checked (see “Verified by tests”). The one thing
that cannot be proven here — BLE pairing from inside a container over the
host's shared BlueZ — is called out first in “Open risks”, not papered over.

## Layout

```
repository.yaml                 add-on repository manifest (repo root)
muse-gadget-bridge/
  config.yaml                   add-on config: homeassistant_api, host_dbus,
                                sdk_token as a password field
  build.yaml                    per-arch base images (Debian bookworm)
  Dockerfile                    mirrors the upstream installer, minus systemd
  run.sh                        entrypoint logic (token sync, pairing, exec)
  rootfs/etc/s6-overlay/…       s6 longrun service that launches run.sh
  sdk/                          vendored Muse Linux Device SDK (see
                                sdk/VENDOR.md) with executor.py extended
  DOCS.md / README.md / CHANGELOG.md
tests/                          mock tests + fake Core server (run_tests.sh)
```

## Design decisions

**Vendored SDK, one file changed.** The SDK is copied in at upstream commit
`f60347ae` (2026-10-16) instead of being fetched during the image build, so
the build is reproducible and what pairs is exactly what can be reviewed
here. `diff` against upstream confirms the only changed file is
`src/musegadget/executor.py` (plus this repo's `VENDOR.md`; upstream's
`.gitignore` was dropped). The extension follows the SDK's own documented
pattern: specs in `COMMAND_SPECS`, branches in `Executor.run`.

**The four new commands** (full HA access — Karta's explicit decision; no
entity allowlist):

| Command | Implementation |
| --- | --- |
| `ha.get_states` | `GET /api/states`; optional `entity_id` (single fetch), `domain` filter, `offset`/`limit` paging |
| `ha.call_service` | `POST /api/services/<domain>/<service>` with the caller's `data` object; returns changed states |
| `ha.get_config` | `GET /api/config` |
| `ha.camera_snapshot` | `GET /api/camera_proxy/<entity_id>`, returned in base64 chunks (below) |

All four call `http://supervisor/core/api/...` (overridable via `HA_API_BASE`,
which the tests use) with `Authorization: Bearer $SUPERVISOR_TOKEN`, the
token the Supervisor injects into add-ons that set `homeassistant_api: true`.
They use only the standard library (`urllib`) — the SDK's dependency set has
no HTTP client, and none was added.

**Why the handlers run in the service process.** Upstream runs shell/file
commands in child processes with a scrubbed environment, as an unprivileged
account. The `ha.*` handlers deliberately do *not* do that: they need
`SUPERVISOR_TOKEN`, which lives in the service's environment. They are
read/write in-process, like upstream's own `device.health`. The upstream
split is otherwise preserved: the service runs as root (owns the state dir
and the token), and Muse's `system.run`/`file.*` commands still run as a
dedicated unprivileged in-image account named `muse`
(`MUSEGADGET_RUN_AS=muse`, created in the Dockerfile).

**Audit log.** Every `ha.call_service` — success *and* failure — appends one
JSON line to `/data/audit.log` (timestamp UTC, command, `domain.service`,
entity ids from `data.entity_id`, `ok`, and an error `detail` when it fails)
and prints the same line to stdout, where it lands in the add-on's Log tab.
Auditing never fails the call: a failed log write is itself only logged.

**get_states paging.** A big house's full state list can exceed the gadget
link's per-message budget (256 KiB per message; the SDK budgets 96 KiB for
command output). `ha.get_states` therefore pages: default is everything,
but if a page would exceed the budget it is shortened and `next_offset`
tells the caller where to continue — nothing is silently truncated.

**Camera snapshots.** `camera_proxy` returns a binary JPEG, and the gadget
link carries JSON only, so the snapshot crosses as base64 in ≤64 KiB chunks
— the same pattern as the SDK's `file.read`. Each reply carries
`content_type`, `size_bytes`, `sha256` of the whole image, `offset`,
`next_offset`, `eof`. Two honest caveats: each call re-fetches, and
`camera_proxy` always serves the camera's *latest* frame, so chunks from
separate calls can come from different frames; the per-call `sha256` is the
guard — if it changes between chunk calls, restart from offset 0. (Still
images are the design point; this is not a video channel.)

**Token plumbing, no secrets in the repo.** `sdk_token` is a `password`
schema field in `config.yaml`. The Supervisor writes it to
`/data/options.json`; on every start, `run.sh` copies it (stripped, file
mode 0600, state dir 0700 under `/data/musegadget/`) into exactly the file
the SDK's own `config.sdk_token()` reads. No real token exists anywhere in
this repository — a test scans for token-shaped strings and finds none.
Per upstream semantics, Muse records the token at pairing time, so
rotating the token later means re-pairing; DOCS.md says so.

**No systemd.** HA base images bring s6-overlay, so the service is an s6
`longrun` (`rootfs/etc/s6-overlay/s6-rc.d/musegadget`). Its run file uses
the `#!/command/with-contenv bash` shebang the HA docs prescribe so the
service sees the container environment (`SUPERVISOR_TOKEN`), then execs
`run.sh`, a plain foreground script that syncs the token, opens pairing if
needed, and `exec`s `musegadget run`. `init: false` is set, as HA base
images require.

**Pairing UX.** An add-on gives the user no shell, so `run.sh` opens the
SDK's pairing window itself: on every start while no `pairing.json` exists,
it runs `musegadget pair` (10-minute window, BLE name printed to the log)
before starting the service. Restarting the add-on is how you re-open the
window. Pairing state lives in `/data`, so it survives restarts and updates.

**Debian base, upstream's install recipe.** The SDK needs the distribution's
`python3-dbus`, `python3-gi`, `python3-cryptography` (no wheels exist), so
`build.yaml` uses `ghcr.io/home-assistant/{arch}-base-debian:bookworm` —
not Alpine — and the Dockerfile replicates `install.sh`: pinned uv 0.9.9,
venv with `--system-site-packages` on `/usr/bin/python3`, package installed
`--no-deps`, then the hash-pinned `requirements.lock` (websockets) with
`--require-hashes`. aarch64 (the Green) and amd64 are declared.

**Bluetooth: `host_dbus: true`, and nothing else.** Chosen deliberately:
the HA add-on docs define `host_dbus` as mounting the host's D-Bus system
bus (`/run/dbus`) into the app — that is the supported way for an add-on to
talk to the host's bluetoothd. So the container installs **no** `bluez`
package and runs **no** bluetoothd of its own; the SDK's `ble_server`
registers its GATT application and advertisement with the *host's* BlueZ as
one more client, alongside Home Assistant's own Bluetooth integration on
the same CSR8510 adapter. The add-on process runs as root inside the
container (host uid 0), which is who bluetoothd's D-Bus policy admits. No
`privileged` capabilities, no `usb: true`, no `full_access` — none of them
are needed for D-Bus, and each would lower the add-on's security rating.
AppArmor is left at the Supervisor default (no custom profile in v1). The
entrypoint also exports `DBUS_SYSTEM_BUS_ADDRESS` pointing at the mounted
socket when present, and warns loudly in the log when it is not.

## Verified by tests

`tests/run_tests.sh` — **28 tests, all passing** (stdlib `unittest`; the
tracebacks visible in the output are the executor's own error logging for
the deliberate failure-path tests):

- `test_ha_commands.py` (19) — the real `Executor` handlers against a fake
  Supervisor/Core server (`tests/fake_core.py`, loopback only, Bearer-token
  checked): get_states all/domain/single/unknown/paging plus the
  payload-size guard; get_config; call_service happy path with the exact
  path/body asserted at the fake, entity-id list handling, missing/bad
  params rejected *before* any HTTP call, an HA 500 surfaced as an error;
  audit file lines on success **and** on failure (fields: ts, command,
  service, entity_ids, ok, detail) and the stdout copy; camera snapshot
  fetched in 64 KiB chunks and reassembled byte-identical, sha256 and
  content-type checked, unknown camera 404, non-camera rejected; missing
  `SUPERVISOR_TOKEN` and wrong-token (401) paths; all four commands present
  in `COMMAND_SPECS`.
- `test_run_sh.py` (3) — the entrypoint's token sync: token copied from a
  fake `options.json`, whitespace-stripped, file mode 0600; empty token and
  missing options both reported “absent” with no file written.
- `test_addon_files.py` (5) — packaging structure: `repository.yaml` exists;
  `config.yaml` carries `homeassistant_api`, `host_dbus`, `init: false`,
  the password schema and aarch64; the Dockerfile uses the Debian base and
  the distro Python packages and does **not** install bluetoothd; the s6
  files are shaped correctly (longrun, with-contenv shebang); **no
  token-shaped string anywhere in the add-on**.
- `test_sdk_token_format.py` (1) — Karta's real SDK token (from
  `~/workspace/user/files/muse-gadget-sdk-token`, read in place, never
  printed or copied) is accepted by the SDK's own token validator: the
  plumbing will recognise the real thing at install time.
- The whole vendored tree byte-compiles; `diff -rq` against the pristine
  upstream clone shows only `executor.py` changed.

Not verified, because it needs the real machine: the Docker image build
itself (reviewed line-by-line against the upstream installer and the HA
docs, but not built — no HAOS/Docker here), BLE pairing, registration with
Muse, and a live HA on the other end of the proxy.

## Open risks

1. **BLE pairing from inside the container over host BlueZ — the
   prototype's open question.** The `host_dbus` route is the documented
   one, but nothing here proves the Green's bluetoothd will accept a GATT
   application + LE advertisement from the add-on while HA's Bluetooth
   integration is actively scanning the same Bluetooth 4.0 CSR8510 dongle.
   BlueZ supports multiple clients in principle; a BT 4.0 dongle juggling
   scanning, an advertisement, and a GATT connection is the flakiest part
   of the stack. If registration is refused, the add-on log will show the
   D-Bus error at pairing time — first fixes to try: a custom
   `apparmor.txt` if the denial is AppArmor, and pairing while HA's
   Bluetooth integration is momentarily disabled. If the dongle itself is
   the limit, the fallback is the same bridge on a Pi, or a better adapter.
2. **Host BlueZ settings the add-on cannot change.** Upstream's installer
   edits the *host's* `/etc/bluetooth/main.conf` (`ExchangeMTU = 256` —
   without it, Android pairing can fail at the Wi-Fi step because the app
   writes oversized packets) and disables BlueZ's battery plugin (without
   it, iOS can be asked to bond mid-pairing and drop). An add-on cannot
   edit host config, so if pairing misbehaves in exactly those ways, the
   fix is on the host (HAOS developer SSH on port 22222), not in this repo.
3. **The token in the add-on config.** It sits in the Supervisor's option
   storage and the add-on's `/data` — normal for add-ons, and the reason
   the kill switch stays simple: clearing the option and restarting, or
   revoking the token at gadgets.muse.ai, ends the bridge. A rotated token
   needs a re-pair (upstream semantics).
4. **First install builds the image on the Green.** The Supervisor builds
   locally (apt + PyPI + the uv download), so install takes minutes and
   needs the Green online; a failure shows in the Supervisor's build log,
   not the add-on log. Nothing is pre-published, per the local-repo plan.
5. **Full access is the design.** With `homeassistant_api`, the Supervisor
   token can call every service, including locks and the alarm, and the
   bridge adds no allowlist (Karta's decision). The mitigations are the
   audit log, the token custody above, and that stopping the add-on or
   disabling the path severs it completely.

## Install steps (Karta)

1. Publish this folder as a GitHub repository (or copy it to the Green as a
   local add-on repository). In Home Assistant: **Settings → Add-ons →
   Add-on store → ⋮ (top right) → Repositories**, paste the repository URL,
   **Add**, then close and refresh the store. “Muse Gadget Bridge” appears
   under its own repository heading.
2. Open **Muse Gadget Bridge → Install**. The Supervisor builds the image
   on the Green; give it several minutes.
3. Go to the **Configuration** tab, paste the SDK token (`mgst_…`, from
   gadgets.muse.ai → Account → SDK tokens) into **sdk_token**, and **Save**.
4. **Info tab → Start.** Open the **Log** tab: it should confirm the SDK
   token was loaded, announce the pairing window, and print the device
   name, `MuseGadgetXXXXXX`.
5. Stand near the Green with your phone. In the Muse app: **Settings →
   Devices → Developer mode** ON → **Add Device** (+) → choose
   `MuseGadgetXXXXXX` → accept the community-device warning → at the Wi-Fi
   step pick the network it shows (the Green is already online; no
   password). The window stays open for 10 minutes from add-on start.
6. Watch the log: pairing is saved, the service starts, and it registers
   with Muse. First test: ask Muse what's on in the house
   (`ha.get_states`), then have it toggle one light (`ha.call_service`) and
   look for the `audit …` line in the log.
7. Not paired in time, or pairing again later: **restart the add-on** —
   while unpaired, every start re-opens the 10-minute window.

## Addendum, 2026-10-18: 0.1.1 pairing-resume fix

First live install reached "pairing confirmed" but never completed: the
Muse app dropped the BLE connection ~2 s after the confirmation and
reconnected twice inside the confirmation window, while the vendored
`SetupController.on_disconnect` cleared the pairing session on every
disconnect, so the continuation (wifi_scan / provision_v2) had no session
to land on and the window closed unpaired. `ble_setup.py` now keeps the
session across disconnects (still bounded by the `pairing.py` deadlines;
a fresh hello still restarts it). Divergence list is therefore now two
source files (`executor.py`, `ble_setup.py`) plus the rewritten/added
tests in `tests/test_ble_setup.py`; see `sdk/VENDOR.md`. Verified: SDK
suite 219 passed / 1 skipped, add-on suite 28/28.

## Addendum, 2026-10-18: 0.1.3 configurable scan SSID

Second and third attempts (0.1.1/0.1.2) completed the handshake and the
wifi_scan exchange, then the app disconnected at the Wi-Fi step without
sending provision_v2. Probe logging in 0.1.2 showed the container's
connectivity probe is fine (online=True); the scan offered the
placeholder label "Use current connection" because the Green is wired and
has no Wi-Fi SSID source (no nmcli/wpa_cli data). Upstream's own
test_network.py documents that the app stops before provision_v2 when the
entry falls back to that label. 0.1.3 adds a `wifi_ssid` add-on option:
run.sh exports it as MUSEGADGET_WIFI_SSID and network.active_wifi_ssid
prefers it, so the scan offers the household network by its real name.
