"""Structural checks on the add-on packaging (no Docker build needed)."""

from __future__ import annotations

import os
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ADDON = os.path.join(REPO, "muse-gadget-bridge")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class AddonFilesTest(unittest.TestCase):
    def test_repository_file(self):
        self.assertTrue(os.path.exists(os.path.join(REPO, "repository.yaml")))

    def test_config_yaml_key_settings(self):
        config = read(os.path.join(ADDON, "config.yaml"))
        for needle in (
            "slug: muse_gadget_bridge",
            "homeassistant_api: true",   # Core API via Supervisor proxy
            "host_dbus: true",           # host BlueZ for BLE pairing
            "init: false",               # HA base image brings its own s6 init
            "sdk_token: password",       # masked password field in the UI
            "- aarch64",                 # Home Assistant Green
        ):
            self.assertIn(needle, config)

    def test_no_real_token_anywhere_in_addon(self):
        import re
        token_shape = re.compile(r"mgst_[A-Za-z0-9_-]{20,}")
        for root, _dirs, files in os.walk(ADDON):
            for name in files:
                path = os.path.join(root, name)
                with open(path, "rb") as f:
                    data = f.read()
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                self.assertIsNone(token_shape.search(text),
                                  f"token-shaped string found in {path}")

    def test_dockerfile_shape(self):
        dockerfile = read(os.path.join(ADDON, "Dockerfile"))
        for needle in (
            "base-debian:bookworm",
            "python3-dbus",
            "python3-gi",
            "python3-cryptography",
            "--system-site-packages",
            "--require-hashes",
        ):
            self.assertIn(needle, dockerfile)
        # bluetoothd must NOT be installed: the host's BlueZ is used.
        self.assertNotIn("apt-get install -y --no-install-recommends \\\n      bluez", dockerfile)

    def test_s6_service_files(self):
        base = os.path.join(ADDON, "rootfs", "etc", "s6-overlay", "s6-rc.d")
        self.assertEqual(read(os.path.join(base, "musegadget", "type")).strip(), "longrun")
        run = read(os.path.join(base, "musegadget", "run"))
        self.assertIn("#!/command/with-contenv bash", run)  # sees SUPERVISOR_TOKEN
        self.assertIn("/opt/musegadget/run.sh", run)
        self.assertTrue(os.path.exists(os.path.join(base, "user", "contents.d", "musegadget")))


if __name__ == "__main__":
    unittest.main()
