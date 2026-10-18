"""Mock tests for the ha.automation_* commands in the vendored SDK's executor.

Runs the real Executor handlers against the fake Supervisor/Core server
(tests/fake_core.py). Covers: save-create (generated id), save-update,
get (round trip + unknown id), delete (round trip + unknown id), parameter
validation, and the audit lines written for saves and deletes.

Run via tests/run_tests.sh.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "muse-gadget-bridge", "sdk", "src"))

from fake_core import TOKEN, FakeCore  # noqa: E402
from musegadget.executor import Executor, Account  # noqa: E402

CONFIG = {
    "alias": "Test automation",
    "description": "created by the mock tests",
    "triggers": [{"trigger": "time", "at": "03:00:00"}],
    "conditions": [],
    "actions": [{"action": "persistent_notification.create",
                 "data": {"message": "test"}}],
    "mode": "single",
}


class AutomationCommandsTest(unittest.TestCase):
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

    # -- save / get -----------------------------------------------------------

    def test_save_create_generates_id_and_round_trips(self):
        result = self.run_cmd("ha.automation_save", {"config": CONFIG})
        self.assertTrue(result["ok"], result)
        config_id = result["payload"]["config_id"]
        self.assertTrue(config_id.isdigit(), config_id)
        self.assertEqual(self.core.automation_configs[config_id], CONFIG)
        got = self.run_cmd("ha.automation_get", {"config_id": config_id})
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["payload"]["config"], CONFIG)

    def test_save_update_replaces_config(self):
        created = self.run_cmd("ha.automation_save", {"config": CONFIG})
        config_id = created["payload"]["config_id"]
        updated = {**CONFIG, "alias": "Renamed automation"}
        result = self.run_cmd("ha.automation_save",
                              {"config_id": config_id, "config": updated})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["payload"]["config_id"], config_id)
        got = self.run_cmd("ha.automation_get", {"config_id": config_id})
        self.assertEqual(got["payload"]["config"]["alias"], "Renamed automation")

    def test_save_audits_with_alias(self):
        self.run_cmd("ha.automation_save", {"config": CONFIG})
        lines = self.audit_lines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["command"], "ha.automation_save")
        self.assertTrue(lines[0]["ok"])
        self.assertEqual(lines[0]["detail"], "Test automation")

    def test_get_unknown_id_fails(self):
        result = self.run_cmd("ha.automation_get", {"config_id": "999999"})
        self.assertFalse(result["ok"])
        self.assertIn("404", result["error"])

    # -- delete ---------------------------------------------------------------

    def test_delete_round_trip_and_audit(self):
        created = self.run_cmd("ha.automation_save", {"config": CONFIG})
        config_id = created["payload"]["config_id"]
        result = self.run_cmd("ha.automation_delete", {"config_id": config_id})
        self.assertTrue(result["ok"], result)
        self.assertNotIn(config_id, self.core.automation_configs)
        got = self.run_cmd("ha.automation_get", {"config_id": config_id})
        self.assertFalse(got["ok"])
        deletes = [l for l in self.audit_lines()
                   if l["command"] == "ha.automation_delete"]
        self.assertEqual(len(deletes), 1)
        self.assertTrue(deletes[0]["ok"])
        self.assertEqual(deletes[0]["config_id"], config_id)

    def test_delete_unknown_id_fails_and_audits_failure(self):
        result = self.run_cmd("ha.automation_delete", {"config_id": "424242"})
        self.assertFalse(result["ok"])
        self.assertIn("404", result["error"])
        lines = self.audit_lines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["command"], "ha.automation_delete")
        self.assertFalse(lines[0]["ok"])

    # -- validation -------------------------------------------------------------

    def test_save_requires_config_object(self):
        for bad in (None, "nope", [], {}):
            result = self.run_cmd("ha.automation_save", {"config": bad})
            self.assertFalse(result["ok"], (bad, result))
        self.assertEqual(self.core.automation_configs, {})

    def test_config_id_validation(self):
        for bad in ("", "a/b", "..", "a b", 123):
            got = self.run_cmd("ha.automation_get", {"config_id": bad})
            self.assertFalse(got["ok"], (bad, got))
            deleted = self.run_cmd("ha.automation_delete", {"config_id": bad})
            self.assertFalse(deleted["ok"], (bad, deleted))
        saved = self.run_cmd("ha.automation_save",
                              {"config_id": "a/b", "config": CONFIG})
        self.assertFalse(saved["ok"])
        self.assertEqual(self.core.automation_configs, {})

    def test_missing_token_fails(self):
        os.environ.pop("SUPERVISOR_TOKEN")
        result = self.run_cmd("ha.automation_get", {"config_id": "123"})
        self.assertFalse(result["ok"])
        self.assertIn("SUPERVISOR_TOKEN", result["error"])


if __name__ == "__main__":
    unittest.main()
