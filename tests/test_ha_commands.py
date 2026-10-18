"""Mock tests for the ha.* commands in the vendored SDK's executor.

Runs the real Executor handlers against a fake Supervisor/Core server
(tests/fake_core.py) with HA_API_BASE / SUPERVISOR_TOKEN / AUDIT_LOG pointed
at the fakes. Covers: get_states (all, domain filter, single entity, paging,
payload-size guard), call_service (happy path, bad params, HA error,
audit-on-success and audit-on-failure), get_config, camera_snapshot
(chunking and reassembly), and the missing/ wrong-token paths.

Run via tests/run_tests.sh.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "muse-gadget-bridge", "sdk", "src"))

from fake_core import CONFIG, SNAPSHOT, STATES, TOKEN, FakeCore  # noqa: E402
from musegadget.executor import Executor, Account  # noqa: E402


class HaCommandsTest(unittest.TestCase):
    def setUp(self):
        self.core = FakeCore().__enter__()
        self.tmp = tempfile.TemporaryDirectory()
        self.audit_path = os.path.join(self.tmp.name, "audit.log")
        self.env = {
            "HA_API_BASE": self.core.api_base,
            "SUPERVISOR_TOKEN": TOKEN,
            "AUDIT_LOG": self.audit_path,
        }
        self.saved = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        self.executor = Executor(Account.current())

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.core.__exit__()
        self.tmp.cleanup()

    def run_cmd(self, command, params=None):
        return self.executor.run(command, params or {})

    def audit_lines(self):
        if not os.path.exists(self.audit_path):
            return []
        with open(self.audit_path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    # -- ha.get_states ---------------------------------------------------------

    def test_get_states_all(self):
        result = self.run_cmd("ha.get_states")
        self.assertTrue(result["ok"], result)
        payload = result["payload"]
        self.assertEqual(payload["total"], len(STATES))
        self.assertEqual(payload["count"], len(STATES))
        self.assertIsNone(payload["next_offset"])
        self.assertEqual({s["entity_id"] for s in payload["states"]},
                         {s["entity_id"] for s in STATES})

    def test_get_states_domain_filter(self):
        result = self.run_cmd("ha.get_states", {"domain": "light"})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["payload"]["total"], 2)
        self.assertTrue(all(s["entity_id"].startswith("light.")
                            for s in result["payload"]["states"]))

    def test_get_states_single_entity(self):
        result = self.run_cmd("ha.get_states", {"entity_id": "switch.pump"})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["payload"]["states"][0]["entity_id"], "switch.pump")

    def test_get_states_unknown_entity(self):
        result = self.run_cmd("ha.get_states", {"entity_id": "light.nope"})
        self.assertFalse(result["ok"])
        self.assertIn("404", result["error"])

    def test_get_states_paging(self):
        first = self.run_cmd("ha.get_states", {"limit": 2})
        self.assertTrue(first["ok"], first)
        self.assertEqual(first["payload"]["count"], 2)
        self.assertEqual(first["payload"]["next_offset"], 2)
        rest = self.run_cmd("ha.get_states", {"offset": first["payload"]["next_offset"]})
        self.assertTrue(rest["ok"], rest)
        self.assertEqual(rest["payload"]["count"], len(STATES) - 2)
        self.assertIsNone(rest["payload"]["next_offset"])

    def test_get_states_size_guard_pages_instead_of_overflowing(self):
        big = [{
            "entity_id": f"sensor.s{i}", "state": "1",
            "attributes": {"blob": "x" * 4000},
        } for i in range(100)]
        self.executor._ha_request = lambda *a, **k: (200, "", big)
        result = self.run_cmd("ha.get_states")
        self.assertTrue(result["ok"], result)
        payload = result["payload"]
        self.assertLess(payload["count"], 100)
        self.assertIsNotNone(payload["next_offset"])
        self.assertLessEqual(len(json.dumps(payload["states"])), 96 * 1024 + 4096)

    # -- ha.get_config -----------------------------------------------------------

    def test_get_config(self):
        result = self.run_cmd("ha.get_config")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["payload"]["version"], CONFIG["version"])
        self.assertEqual(result["payload"]["location_name"], CONFIG["location_name"])

    # -- ha.call_service -----------------------------------------------------------

    def test_call_service_ok_and_audited(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = self.run_cmd("ha.call_service", {
                "domain": "light", "service": "turn_on",
                "data": {"entity_id": "light.living_room", "brightness_pct": 50},
            })
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["payload"]["service"], "light.turn_on")
        self.assertEqual(len(result["payload"]["changed_states"]), 1)
        self.assertEqual(result["payload"]["changed_states"][0]["state"], "on")
        # The fake saw exactly the path and body HA would receive.
        self.assertEqual(self.core.service_calls, [
            ("light", "turn_on", {"entity_id": "light.living_room", "brightness_pct": 50}),
        ])
        # Audit: one JSON line in the file, and the same line on stdout.
        lines = self.audit_lines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["command"], "ha.call_service")
        self.assertEqual(lines[0]["service"], "light.turn_on")
        self.assertEqual(lines[0]["entity_ids"], ["light.living_room"])
        self.assertTrue(lines[0]["ok"])
        self.assertIn("ts", lines[0])
        self.assertIn("audit ", out.getvalue())
        self.assertIn("light.turn_on", out.getvalue())

    def test_call_service_entity_list(self):
        result = self.run_cmd("ha.call_service", {
            "domain": "switch", "service": "turn_off",
            "data": {"entity_id": ["switch.pump"]},
        })
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.audit_lines()[0]["entity_ids"], ["switch.pump"])

    def test_call_service_missing_service(self):
        result = self.run_cmd("ha.call_service", {"domain": "light"})
        self.assertFalse(result["ok"])
        self.assertEqual(self.core.service_calls, [])

    def test_call_service_bad_domain_rejected_before_http(self):
        result = self.run_cmd("ha.call_service", {"domain": "../core", "service": "x"})
        self.assertFalse(result["ok"])
        self.assertEqual(self.core.service_calls, [])

    def test_call_service_non_object_data(self):
        result = self.run_cmd("ha.call_service", {
            "domain": "light", "service": "turn_on", "data": ["not", "an", "object"],
        })
        self.assertFalse(result["ok"])
        self.assertEqual(self.core.service_calls, [])

    def test_call_service_ha_error_is_returned_and_audited(self):
        result = self.run_cmd("ha.call_service", {
            "domain": "light", "service": "fail_me", "data": {"entity_id": "light.kitchen"},
        })
        self.assertFalse(result["ok"])
        self.assertIn("500", result["error"])
        lines = self.audit_lines()
        self.assertEqual(len(lines), 1)
        self.assertFalse(lines[0]["ok"])
        self.assertEqual(lines[0]["service"], "light.fail_me")
        self.assertIn("detail", lines[0])

    # -- ha.camera_snapshot ---------------------------------------------------------

    def test_camera_snapshot_chunked_reassembly(self):
        chunks = []
        offset = 0
        seen = {}
        while True:
            result = self.run_cmd("ha.camera_snapshot",
                                  {"entity_id": "camera.front_door", "offset": offset})
            self.assertTrue(result["ok"], result)
            payload = result["payload"]
            seen.update({k: payload[k] for k in ("content_type", "size_bytes", "sha256")})
            chunks.append(base64.b64decode(payload["data_b64"]))
            if payload["eof"]:
                self.assertIsNone(payload["next_offset"])
                break
            offset = payload["next_offset"]
        image = b"".join(chunks)
        self.assertEqual(image, SNAPSHOT)
        self.assertEqual(seen["size_bytes"], len(SNAPSHOT))
        self.assertEqual(seen["content_type"], "image/jpeg")
        self.assertEqual(seen["sha256"], hashlib.sha256(SNAPSHOT).hexdigest())
        self.assertGreater(len(SNAPSHOT), 65536)  # the fixture really needs 2+ chunks

    def test_camera_snapshot_unknown_camera(self):
        result = self.run_cmd("ha.camera_snapshot", {"entity_id": "camera.nope"})
        self.assertFalse(result["ok"])
        self.assertIn("404", result["error"])

    def test_camera_snapshot_rejects_non_camera(self):
        result = self.run_cmd("ha.camera_snapshot", {"entity_id": "light.kitchen"})
        self.assertFalse(result["ok"])
        self.assertEqual(self.core.service_calls, [])

    # -- token handling -----------------------------------------------------------

    def test_missing_supervisor_token(self):
        os.environ.pop("SUPERVISOR_TOKEN")
        result = self.run_cmd("ha.get_config")
        self.assertFalse(result["ok"])
        self.assertIn("SUPERVISOR_TOKEN", result["error"])

    def test_wrong_supervisor_token(self):
        os.environ["SUPERVISOR_TOKEN"] = "not-the-token"
        result = self.run_cmd("ha.get_states")
        self.assertFalse(result["ok"])
        self.assertIn("401", result["error"])

    # -- spec registration -----------------------------------------------------------

    def test_commands_are_registered(self):
        from musegadget.executor import COMMAND_SPECS
        for name in ("ha.get_states", "ha.call_service", "ha.get_config", "ha.camera_snapshot"):
            self.assertIn(name, COMMAND_SPECS)
            self.assertIn("description", COMMAND_SPECS[name])


if __name__ == "__main__":
    unittest.main()
