"""Tests for the add-on entrypoint's SDK-token plumbing (run.sh).

Sources run.sh (its main guard keeps it from starting anything), then calls
sync_sdk_token with OPTIONS_JSON / MUSEGADGET_STATE_DIR pointed at temp dirs.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RUN_SH = os.path.join(REPO, "muse-gadget-bridge", "run.sh")


def sync(options, tmp):
    """Run sync_sdk_token; returns (printed result, token file path)."""
    env = dict(os.environ)
    options_path = os.path.join(tmp, "options.json")
    if options is not None:
        with open(options_path, "w", encoding="utf-8") as f:
            json.dump(options, f)
    env["OPTIONS_JSON"] = options_path
    env["MUSEGADGET_STATE_DIR"] = os.path.join(tmp, "state")
    proc = subprocess.run(
        ["bash", "-c", f'source "{RUN_SH}" >/dev/null 2>&1; sync_sdk_token'],
        env=env, capture_output=True, text=True, timeout=30,
    )
    return proc.stdout.strip(), os.path.join(tmp, "state", "sdk_token")


def read_ssid(options, tmp):
    """Run configured_wifi_ssid; returns what it echoes."""
    env = dict(os.environ)
    options_path = os.path.join(tmp, "options.json")
    if options is not None:
        with open(options_path, "w", encoding="utf-8") as f:
            json.dump(options, f)
    env["OPTIONS_JSON"] = options_path
    proc = subprocess.run(
        ["bash", "-c", f'source "{RUN_SH}" >/dev/null 2>&1; configured_wifi_ssid'],
        env=env, capture_output=True, text=True, timeout=30,
    )
    return proc.stdout.strip()


class RunShTest(unittest.TestCase):
    def test_token_written_stripped_with_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, token_file = sync({"sdk_token": "  mgst_dummy  "}, tmp)
            self.assertEqual(result, "written")
            with open(token_file, encoding="utf-8") as f:
                self.assertEqual(f.read(), "mgst_dummy\n")
            self.assertEqual(stat.S_IMODE(os.stat(token_file).st_mode), 0o600)

    def test_empty_token_is_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, token_file = sync({"sdk_token": ""}, tmp)
            self.assertEqual(result, "absent")
            self.assertFalse(os.path.exists(token_file))

    def test_missing_options_is_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, token_file = sync(None, tmp)
            self.assertEqual(result, "absent")
            self.assertFalse(os.path.exists(token_file))

    def test_wifi_ssid_read_stripped(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(read_ssid({"wifi_ssid": "  Home Net  "}, tmp), "Home Net")

    def test_wifi_ssid_unset_or_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(read_ssid({"wifi_ssid": ""}, tmp), "")
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(read_ssid(None, tmp), "")


def import_state(options, tmp):
    """Run import_state_files; returns (printed lines, state dir)."""
    env = dict(os.environ)
    options_path = os.path.join(tmp, "options.json")
    if options is not None:
        with open(options_path, "w", encoding="utf-8") as f:
            json.dump(options, f)
    env["OPTIONS_JSON"] = options_path
    state_dir = os.path.join(tmp, "state")
    env["MUSEGADGET_STATE_DIR"] = state_dir
    proc = subprocess.run(
        ["bash", "-c", f'source "{RUN_SH}" >/dev/null 2>&1; import_state_files'],
        env=env, capture_output=True, text=True, timeout=30,
    )
    return proc.stdout.strip(), state_dir


class ImportStateTest(unittest.TestCase):
    def test_imports_identity_and_pairing_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, state = import_state(
                {"identity_import": '{"mac": "aa:bb"}',
                 "pairing_import": '{"device_id": "dev-1"}'}, tmp)
            self.assertIn("imported identity.json", out)
            self.assertIn("imported pairing.json", out)
            for name, key in (("identity.json", "mac"), ("pairing.json", "device_id")):
                path = os.path.join(state, name)
                with open(path, encoding="utf-8") as f:
                    self.assertIn(key, json.load(f))
                self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_empty_options_import_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, state = import_state({"identity_import": "", "pairing_import": "  "}, tmp)
            self.assertEqual(out, "")
            self.assertFalse(os.path.exists(os.path.join(state, "identity.json")))

    def test_invalid_json_rejected_existing_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = os.path.join(tmp, "state")
            os.makedirs(state)
            target = os.path.join(state, "pairing.json")
            with open(target, "w", encoding="utf-8") as f:
                f.write('{"device_id": "keep-me"}\n')
            out, _ = import_state({"pairing_import": "not json"}, tmp)
            self.assertIn("rejected pairing.json", out)
            with open(target, encoding="utf-8") as f:
                self.assertIn("keep-me", f.read())

    def test_identical_import_is_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            options = {"identity_import": '{"mac": "aa:bb"}'}
            import_state(options, tmp)
            out, _ = import_state(options, tmp)
            self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
