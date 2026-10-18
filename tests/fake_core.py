"""A fake Supervisor/Core HTTP server for the mock tests.

Stands in for http://supervisor/core: serves the Core REST API paths the
bridge uses (/api/states, /api/config, /api/services/..., /api/camera_proxy/...)
and checks the Bearer token the way the real proxy does. No hardware, no
Home Assistant, no network beyond loopback.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = "test-supervisor-token"

STATES = [
    {"entity_id": "light.living_room", "state": "off",
     "attributes": {"friendly_name": "Living Room", "supported_features": 44},
     "last_changed": "2026-10-18T00:00:00+00:00", "last_updated": "2026-10-18T00:00:00+00:00"},
    {"entity_id": "light.kitchen", "state": "on",
     "attributes": {"friendly_name": "Kitchen", "brightness": 128},
     "last_changed": "2026-10-18T00:00:00+00:00", "last_updated": "2026-10-18T00:00:00+00:00"},
    {"entity_id": "switch.pump", "state": "off",
     "attributes": {"friendly_name": "Pump"},
     "last_changed": "2026-10-18T00:00:00+00:00", "last_updated": "2026-10-18T00:00:00+00:00"},
    {"entity_id": "camera.front_door", "state": "idle",
     "attributes": {"friendly_name": "Front Door", "entity_picture": "/api/camera_proxy/camera.front_door"},
     "last_changed": "2026-10-18T00:00:00+00:00", "last_updated": "2026-10-18T00:00:00+00:00"},
    {"entity_id": "sensor.temperature", "state": "31.5",
     "attributes": {"friendly_name": "Temperature", "unit_of_measurement": "°C"},
     "last_changed": "2026-10-18T00:00:00+00:00", "last_updated": "2026-10-18T00:00:00+00:00"},
]

CONFIG = {
    "version": "2026.10.1",
    "location_name": "The Trillium",
    "time_zone": "Asia/Singapore",
    "language": "en",
    "components": ["light", "switch", "camera", "sensor"],
    "state": "RUNNING",
}

# A deterministic stand-in JPEG, deliberately bigger than one 64 KiB chunk.
SNAPSHOT = b"\xff\xd8\xff\xe0" + bytes(range(256)) * 400 + b"\xff\xd9"


class _Handler(BaseHTTPRequestHandler):
    server_version = "FakeCore/1.0"

    def log_message(self, *args):  # keep test output readable
        pass

    def _reply(self, code, body, content_type="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        if self.headers.get("Authorization") == f"Bearer {TOKEN}":
            return True
        self._reply(401, {"message": "401: Unauthorized"})
        return False

    def do_GET(self):
        if not self._authorized():
            return
        if self.path == "/api/states":
            self._reply(200, STATES)
        elif self.path.startswith("/api/states/"):
            entity_id = self.path[len("/api/states/"):]
            for state in STATES:
                if state["entity_id"] == entity_id:
                    self._reply(200, state)
                    return
            self._reply(404, {"message": "Entity not found."})
        elif self.path == "/api/config":
            self._reply(200, CONFIG)
        elif self.path.startswith("/api/camera_proxy/"):
            entity_id = self.path[len("/api/camera_proxy/"):]
            if entity_id == "camera.front_door":
                self._reply(200, SNAPSHOT, "image/jpeg")
            else:
                self._reply(404, b"No camera entity found", "text/plain")
        else:
            self._reply(404, {"message": "not found"})

    def do_POST(self):
        if not self._authorized():
            return
        if self.path.startswith("/api/services/"):
            parts = self.path[len("/api/services/"):].split("/")
            if len(parts) != 2:
                self._reply(404, {"message": "not found"})
                return
            domain, service = parts
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            self.server.service_calls.append((domain, service, body))
            if service == "fail_me":
                self._reply(500, b"fake failure", "text/plain")
                return
            entity_id = body.get("entity_id")
            if isinstance(entity_id, str):
                entity_id = [entity_id]
            changed = [
                {**state, "state": "on"}
                for state in STATES
                if state["entity_id"] in (entity_id or [])
            ]
            self._reply(200, changed)
        else:
            self._reply(404, {"message": "not found"})


class FakeCore:
    """Context manager: a running fake Core on an ephemeral loopback port."""

    def __enter__(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.service_calls = []
        self.port = self.server.server_address[1]
        import threading
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    @property
    def api_base(self):
        return f"http://127.0.0.1:{self.port}/api"

    @property
    def service_calls(self):
        return self.server.service_calls
