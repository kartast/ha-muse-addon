"""Format-check the real SDK token file with the SDK's own validator.

Reads ~/workspace/user/files/muse-gadget-sdk-token (Karta's smoke-test token)
and asserts the SDK accepts its format. The token value is never printed,
logged, or copied anywhere; only validity is asserted. Skips cleanly when
the file is absent.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "muse-gadget-bridge", "sdk", "src"))

TOKEN_FILE = Path.home() / "workspace" / "user" / "files" / "muse-gadget-sdk-token"


@unittest.skipUnless(TOKEN_FILE.exists(), "no local smoke-test token file")
class RealTokenFormatTest(unittest.TestCase):
    def test_token_format_accepted_by_sdk(self):
        from musegadget import config
        os.environ["MUSEGADGET_SDK_TOKEN"] = TOKEN_FILE.read_text(encoding="utf-8").strip()
        try:
            token = config.sdk_token()  # raises ValueError on a bad format
        finally:
            os.environ.pop("MUSEGADGET_SDK_TOKEN", None)
        self.assertIsNotNone(token)
        self.assertTrue(token.startswith("mgst_"))
        self.assertEqual(len(token), 48)


if __name__ == "__main__":
    unittest.main()
