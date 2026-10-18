# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""The commands a Muse can invoke on this device.

Shell commands and file operations run in child processes as a separate,
unprivileged account (``run_as``), never as the service account, which owns
the device credentials. A command gets exactly the access that account has.

Home Assistant add-on extension (this vendored copy): the ``ha.*`` commands
run in the service process itself, because they need the add-on's
``SUPERVISOR_TOKEN`` from the service environment — the child-process
environment is deliberately stripped of it. They talk to Home Assistant Core
through the Supervisor proxy (``http://supervisor/core/api``).
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import json
import logging
import os
import pwd
import re
import select
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from musegadget import __version__

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 120
MAX_TIMEOUT_S = 600
# How long to wait for output after killing a timed-out command's process group.
KILL_GRACE_S = 2
# How long to keep reading queued output after the shell exits.
DRAIN_S = 0.5
# /link-control accepts at most 256 KiB per message from the device; leave
# room for the JSON envelope and escaping.
MAX_OUTPUT_BYTES = 96 * 1024
SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

COMMAND_SPECS = {
    "system.run": {
        "description": (
            "Run a shell command on this Linux device with bash and return its "
            "stdout, stderr and exit code. Output over 96 KiB per stream is "
            "truncated."
        ),
        "required": {
            "command": {"type": "string", "description": "Shell command line to run."},
        },
        "optional": {
            "cwd": {"type": "string", "description": "Working directory. Default: the account's home."},
            "timeout_ms": {"type": "integer", "description": "Kill the command after this long. Default 120000, max 600000."},
        },
        "timeout_ms": MAX_TIMEOUT_S * 1000 + 5000,
    },
    "file.read": {
        "description": "Read up to 64 KiB of a file, base64-encoded. Call again with next_offset until eof.",
        "required": {
            "path": {"type": "string", "description": "Absolute path."},
        },
        "optional": {
            "offset": {"type": "integer", "description": "Byte offset. Default 0."},
            "limit": {"type": "integer", "description": "Max bytes, up to 65536."},
        },
    },
    "file.write": {
        "description": (
            "Write a file in chunks of up to 64 KiB (base64). Start at offset 0, "
            "send chunks in order, and set final=true on the last one; the file "
            "is replaced atomically, and only if sha256 (when given) matches."
        ),
        "required": {
            "path": {"type": "string", "description": "Absolute destination path."},
            "data_b64": {"type": "string", "description": "This chunk's bytes, base64-encoded."},
        },
        "optional": {
            "offset": {"type": "integer", "description": "Byte offset of this chunk. Default 0."},
            "final": {"type": "boolean", "description": "True on the last chunk. Default false."},
            "sha256": {"type": "string", "description": "Hex SHA-256 of the whole file, checked on the final chunk."},
            "create_parents": {"type": "boolean", "description": "Create missing parent directories. Default false."},
            "overwrite": {"type": "boolean", "description": "Replace an existing file. Default true."},
        },
    },
    "device.health": {
        "description": "Device status: uptime, load, memory, disk, temperature, software version.",
        "required": {},
        "optional": {},
    },
    "ha.get_states": {
        "description": (
            "List Home Assistant entity states via the local Core API. Returns one page of "
            "states plus paging metadata (total, offset, next_offset): pass next_offset back "
            "as offset to page through a large house. Filter with domain (e.g. \"light\") or "
            "fetch one entity with entity_id."
        ),
        "required": {},
        "optional": {
            "entity_id": {"type": "string", "description": "Fetch only this entity, e.g. \"light.living_room\"."},
            "domain": {"type": "string", "description": "Only entities in this domain, e.g. \"light\", \"camera\"."},
            "offset": {"type": "integer", "description": "Page offset into the state list. Default 0."},
            "limit": {"type": "integer", "description": "Max entities per page. Default: all remaining."},
        },
    },
    "ha.call_service": {
        "description": (
            "Call any Home Assistant service, e.g. domain \"light\", service \"turn_on\", data "
            "{\"entity_id\": \"light.living_room\", \"brightness_pct\": 50}. Full access: locks, "
            "alarms and covers included. Every call is written to the audit log (/data/audit.log) "
            "and the device log. Returns the states the service changed."
        ),
        "required": {
            "domain": {"type": "string", "description": "Service domain, e.g. \"light\", \"lock\", \"homeassistant\"."},
            "service": {"type": "string", "description": "Service name, e.g. \"turn_on\", \"toggle\", \"restart\"."},
        },
        "optional": {
            "data": {"type": "object", "description": "Service data as a JSON object; put entity_id here to target entities."},
        },
        "timeout_ms": 70000,
    },
    "ha.get_config": {
        "description": "Home Assistant Core configuration: version, location name, time zone, unit system, loaded components.",
        "required": {},
        "optional": {},
    },
    "ha.camera_snapshot": {
        "description": (
            "Fetch a camera snapshot (JPEG) from Home Assistant, base64-encoded in chunks of up "
            "to 64 KiB, like file.read: call again with next_offset until eof is true, then "
            "concatenate the decoded chunks. size_bytes and sha256 describe the whole image."
        ),
        "required": {
            "entity_id": {"type": "string", "description": "Camera entity, e.g. \"camera.front_door\"."},
        },
        "optional": {
            "offset": {"type": "integer", "description": "Byte offset. Default 0."},
            "limit": {"type": "integer", "description": "Max bytes, up to 65536. Default 65536."},
        },
        "timeout_ms": 70000,
    },
}

# --- Home Assistant bridge (add-on only) ------------------------------------
# The Supervisor proxy base for the Core REST API. Tests and debugging can
# point HA_API_BASE at a stand-in server; SUPERVISOR_TOKEN is injected by the
# Supervisor into every add-on that sets homeassistant_api: true.
HA_API_BASE_DEFAULT = "http://supervisor/core/api"
HA_TIMEOUT_S = 30
HA_SNAPSHOT_TIMEOUT_S = 60
HA_MAX_PAYLOAD_BYTES = 96 * 1024  # same per-message budget as system.run output
SNAPSHOT_CHUNK_BYTES = 64 * 1024  # same chunk size as file.read
AUDIT_LOG_DEFAULT = "/data/audit.log"
_HA_NAME = re.compile(r"[a-z0-9_]+")


class HaError(Exception):
    """A Home Assistant bridge failure the caller should see verbatim."""


@dataclass(frozen=True)
class Account:
    name: str
    uid: int
    gid: int
    home: str

    @classmethod
    def lookup(cls, name: str) -> "Account":
        entry = pwd.getpwnam(name)
        return cls(entry.pw_name, entry.pw_uid, entry.pw_gid, entry.pw_dir)

    @classmethod
    def current(cls) -> "Account":
        entry = pwd.getpwuid(os.getuid())
        return cls(entry.pw_name, entry.pw_uid, entry.pw_gid, entry.pw_dir)


def ok(payload: dict) -> dict:
    return {"ok": True, "payload": payload}


def error(message: str) -> dict:
    return {"ok": False, "error": message}


class Executor:
    def __init__(self, account: Account) -> None:
        self.account = account

    def run(self, command: str, params: dict, timeout_ms: int | None = None) -> dict:
        try:
            if command == "system.run":
                return self.system_run(params, timeout_ms)
            if command in ("file.read", "file.write"):
                return self.file_op(command.split(".")[1], params)
            if command == "device.health":
                return ok(device_health())
            if command.startswith("ha."):
                return self.ha_command(command, params)
        except Exception as exc:
            log.exception("%s failed", command)
            return error(f"{type(exc).__name__}: {exc}")
        return error(f"unsupported command: {command}")

    # -- Child processes ------------------------------------------------------

    def _child_options(self) -> dict:
        env = {
            "HOME": self.account.home,
            "USER": self.account.name,
            "LOGNAME": self.account.name,
            "PATH": SAFE_PATH,
            "LANG": os.environ.get("LANG", "C.UTF-8"),
        }
        options: dict = {"env": env, "start_new_session": True}
        if os.geteuid() == 0 and self.account.uid != 0:
            options.update(user=self.account.uid, group=self.account.gid,
                           extra_groups=os.getgrouplist(self.account.name, self.account.gid))
        return options

    def system_run(self, params: dict, timeout_ms: int | None) -> dict:
        command = params.get("command")
        if not isinstance(command, str) or not command.strip():
            return error("command is required")
        requested = params.get("timeout_ms") or timeout_ms
        timeout_s = min(int(requested) / 1000 if requested else DEFAULT_TIMEOUT_S, MAX_TIMEOUT_S)
        cwd = params.get("cwd") or self.account.home
        log.info("system.run as %s (timeout %ss)", self.account.name, timeout_s)
        started = time.monotonic()
        try:
            proc = subprocess.Popen(
                ["/bin/bash", "-c", command], cwd=cwd,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                bufsize=0,
                **self._child_options(),
            )
        except OSError as exc:
            return error(f"could not start command: {exc}")
        timed_out, stdout, stderr = _wait_for_shell(proc, timeout_s)
        if timed_out:
            for pipe in (proc.stdout, proc.stderr):
                if pipe is not None and not pipe.closed:
                    os.set_blocking(pipe.fileno(), True)
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                more_out, more_err = proc.communicate(timeout=KILL_GRACE_S)
            except subprocess.TimeoutExpired as exc:
                # A process that left the group (setsid, a daemon) survived the kill and
                # still holds the pipes. Keep what was read instead of waiting on it.
                more_out, more_err = exc.stdout or b"", exc.stderr or b""
                for pipe in (proc.stdout, proc.stderr):
                    if pipe is not None:
                        pipe.close()
                proc.wait()
            stdout += more_out
            stderr += more_err
        out, out_cut = _clip(stdout)
        err, err_cut = _clip(stderr)
        return ok({
            "stdout": out,
            "stderr": err,
            "exit_code": proc.returncode,
            "timed_out": timed_out,
            "truncated": out_cut or err_cut,
            "duration_ms": int((time.monotonic() - started) * 1000),
        })

    def file_op(self, op: str, params: dict) -> dict:
        request = json.dumps({**params, "op": op})
        proc = subprocess.run(
            [sys.executable, "-m", "musegadget.fileops"], input=request.encode(),
            capture_output=True, timeout=60, cwd="/", **self._child_options(),
        )
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            return error(proc.stderr.decode(errors="replace")[-2000:] or "file operation failed")

    # -- Home Assistant bridge ------------------------------------------------
    # These run in the service process (see module docstring): they need
    # SUPERVISOR_TOKEN, which the child-process environment strips on purpose.

    def ha_command(self, command: str, params: dict) -> dict:
        if command == "ha.get_states":
            return self.ha_get_states(params)
        if command == "ha.call_service":
            return self.ha_call_service(params)
        if command == "ha.get_config":
            _, _, config = self._ha_request("GET", "/config")
            return ok(config if isinstance(config, dict) else {"config": config})
        if command == "ha.camera_snapshot":
            return self.ha_camera_snapshot(params)
        return error(f"unsupported command: {command}")

    def _ha_request(self, method: str, path: str, body: dict | None = None,
                    raw: bool = False, timeout: float = HA_TIMEOUT_S):
        """One Core REST API call through the Supervisor proxy.

        Returns (status, content_type, parsed JSON | bytes for raw=True).
        Raises HaError with a caller-readable message on any failure.
        """
        token = os.environ.get("SUPERVISOR_TOKEN")
        if not token:
            raise HaError("SUPERVISOR_TOKEN is not set; this command needs the add-on's "
                          "homeassistant_api permission")
        base = (os.environ.get("HA_API_BASE") or HA_API_BASE_DEFAULT).rstrip("/")
        headers = {"Authorization": f"Bearer {token}"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
                content_type = response.headers.get_content_type() if response.headers else ""
                status = response.status
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise HaError(f"Home Assistant returned HTTP {exc.code} for {method} {path}: "
                          f"{detail}") from exc
        except urllib.error.URLError as exc:
            raise HaError(f"could not reach Home Assistant at {base}: {exc.reason}") from exc
        if raw:
            return status, content_type, payload
        if not payload:
            return status, content_type, None
        try:
            return status, content_type, json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return status, content_type, payload.decode("utf-8", errors="replace")

    def ha_get_states(self, params: dict) -> dict:
        entity_id = params.get("entity_id")
        if entity_id is not None:
            if not isinstance(entity_id, str) or "." not in entity_id:
                return error("entity_id must look like \"domain.name\"")
            _, _, state = self._ha_request("GET", f"/states/{entity_id}")
            return ok({"states": [state], "count": 1, "total": 1, "offset": 0,
                       "next_offset": None})
        _, _, states = self._ha_request("GET", "/states")
        if not isinstance(states, list):
            return error(f"unexpected /states response: {type(states).__name__}")
        domain = params.get("domain")
        if domain:
            prefix = f"{domain}."
            states = [s for s in states
                      if isinstance(s, dict) and str(s.get("entity_id", "")).startswith(prefix)]
        total = len(states)
        try:
            offset = max(0, int(params.get("offset") or 0))
            limit = int(params.get("limit") or 0)
        except (TypeError, ValueError):
            return error("offset and limit must be integers")
        page = states[offset:offset + limit] if limit > 0 else states[offset:]
        # Keep the page inside the per-message budget: drop trailing states
        # and let the caller continue from next_offset instead of failing.
        while page and len(json.dumps(page)) > HA_MAX_PAYLOAD_BYTES:
            if len(page) == 1 and offset + 1 >= total:
                break  # a single oversized state, and it is the last one: send it
            page = page[:-1]
        next_offset = offset + len(page) if offset + len(page) < total else None
        return ok({"states": page, "count": len(page), "total": total,
                   "offset": offset, "next_offset": next_offset})

    def ha_call_service(self, params: dict) -> dict:
        domain = params.get("domain")
        service = params.get("service")
        data = params.get("data") or {}
        if not isinstance(domain, str) or not _HA_NAME.fullmatch(domain):
            return error("domain is required, e.g. \"light\"")
        if not isinstance(service, str) or not _HA_NAME.fullmatch(service):
            return error("service is required, e.g. \"turn_on\"")
        if not isinstance(data, dict):
            return error("data must be a JSON object")
        entity_ids = data.get("entity_id")
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]
        elif not isinstance(entity_ids, list):
            entity_ids = []
        try:
            _, _, changed = self._ha_request("POST", f"/services/{domain}/{service}", body=data)
        except HaError as exc:
            self._ha_audit(domain, service, entity_ids, ok_=False, detail=str(exc))
            raise
        self._ha_audit(domain, service, entity_ids, ok_=True)
        return ok({"service": f"{domain}.{service}", "changed_states": changed})

    def ha_camera_snapshot(self, params: dict) -> dict:
        entity_id = params.get("entity_id")
        if not isinstance(entity_id, str) or not entity_id.startswith("camera."):
            return error("entity_id of a camera is required, e.g. \"camera.front_door\"")
        try:
            offset = max(0, int(params.get("offset") or 0))
            limit = int(params.get("limit") or SNAPSHOT_CHUNK_BYTES)
        except (TypeError, ValueError):
            return error("offset and limit must be integers")
        limit = max(1, min(limit, SNAPSHOT_CHUNK_BYTES))
        _, content_type, image = self._ha_request(
            "GET", f"/camera_proxy/{entity_id}", raw=True, timeout=HA_SNAPSHOT_TIMEOUT_S)
        chunk = image[offset:offset + limit]
        next_offset = offset + len(chunk) if offset + len(chunk) < len(image) else None
        return ok({
            "entity_id": entity_id,
            "content_type": content_type or "image/jpeg",
            "size_bytes": len(image),
            "sha256": hashlib.sha256(image).hexdigest(),
            "offset": offset,
            "next_offset": next_offset,
            "eof": next_offset is None,
            "data_b64": base64.b64encode(chunk).decode("ascii"),
        })

    @staticmethod
    def _ha_audit(domain: str, service: str, entity_ids: list, ok_: bool,
                  detail: str = "") -> None:
        """One audit line per service call: /data/audit.log and stdout.

        Never fails the caller: a broken audit sink is logged, not raised.
        """
        line = json.dumps({
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "command": "ha.call_service",
            "service": f"{domain}.{service}",
            "entity_ids": entity_ids,
            "ok": ok_,
            **({"detail": detail} if detail else {}),
        })
        print(f"audit {line}", flush=True)
        log.info("audit %s", line)
        try:
            path = os.environ.get("AUDIT_LOG") or AUDIT_LOG_DEFAULT
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as exc:
            log.warning("could not write audit log: %s", exc)


def _read_available(pipe, deadline: float) -> tuple[bytes, bool]:
    # Stop at the deadline too: a writer that outpaces the reads would
    # otherwise keep this loop from ever seeing an empty pipe.
    chunks = []
    while time.monotonic() < deadline:
        try:
            chunk = pipe.read(65536)
        except BlockingIOError:
            return b"".join(chunks), True
        if chunk is None:
            return b"".join(chunks), True
        if chunk == b"":
            return b"".join(chunks), False
        chunks.append(chunk)
    return b"".join(chunks), True


def _wait_for_shell(proc, timeout_s: float) -> tuple[bool, bytes, bytes]:
    # Wait until the shell exits. Read only bytes already queued so a grandchild
    # that inherited the pipes cannot hold this open until EOF.
    streams: dict = {}
    for pipe in (proc.stdout, proc.stderr):
        if pipe is None:
            continue
        os.set_blocking(pipe.fileno(), False)
        streams[pipe] = []
    watching = list(streams)
    deadline = time.monotonic() + timeout_s
    while proc.poll() is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True, _joined(streams, proc.stdout), _joined(streams, proc.stderr)
        if not watching:
            time.sleep(min(remaining, 0.05))
            continue
        ready, _, _ = select.select(watching, [], [], min(remaining, 0.05))
        for pipe in ready:
            data, still_open = _read_available(pipe, deadline)
            if data:
                streams[pipe].append(data)
            if not still_open:
                watching.remove(pipe)
    drain_deadline = time.monotonic() + DRAIN_S
    for pipe in streams:
        if pipe.closed:
            continue
        data, _ = _read_available(pipe, drain_deadline)
        if data:
            streams[pipe].append(data)
    return False, _joined(streams, proc.stdout), _joined(streams, proc.stderr)


def _joined(streams: dict, pipe) -> bytes:
    return b"".join(streams.get(pipe, ()))


def _clip(data: bytes) -> tuple[str, bool]:
    cut = len(data) > MAX_OUTPUT_BYTES
    text = data[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
    # The budget is for the message, where json.dumps writes every non-ASCII
    # character as a 6- or 12-byte escape and each undecodable byte became
    # U+FFFD, so binary or non-Latin output can grow sixfold.
    while len(json.dumps(text)) - 2 > MAX_OUTPUT_BYTES:
        text = text[: len(text) * 3 // 4]
        cut = True
    return text, cut


def device_health() -> dict:
    health: dict = {"version": __version__, "hostname": socket.gethostname()}
    try:
        health["uptime_s"] = int(float(open("/proc/uptime").read().split()[0]))
    except OSError:
        pass
    try:
        health["load"] = [round(x, 2) for x in os.getloadavg()]
    except OSError:
        pass
    try:
        meminfo = dict(line.split(":", 1) for line in open("/proc/meminfo"))
        health["memory_mb"] = {
            "total": int(meminfo["MemTotal"].split()[0]) // 1024,
            "available": int(meminfo["MemAvailable"].split()[0]) // 1024,
        }
    except (OSError, KeyError, ValueError):
        pass
    disk = shutil.disk_usage("/")
    health["disk_gb"] = {"total": round(disk.total / 1e9, 1), "free": round(disk.free / 1e9, 1)}
    try:
        health["temperature_c"] = int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000
    except (OSError, ValueError):
        pass
    try:
        health["model"] = open("/proc/device-tree/model").read().strip("\x00\n")
    except OSError:
        pass
    return health
