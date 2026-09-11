"""Runtime secret delivery regressions; all material below is invalid test data."""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "secret_files_under_test", ROOT / "src/larimia/secret_files.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SecretFileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "secret"
        self.path.write_text("invalid-local-fixture\n")
        self.path.chmod(0o400)

    def test_file_value_is_read_without_environment_materialization(self):
        with patch.dict(os.environ, {"EXAMPLE_FILE": str(self.path)}, clear=True):
            self.assertEqual(MODULE.environment_secret("EXAMPLE"), "invalid-local-fixture")
            self.assertNotIn("EXAMPLE", os.environ)

    def test_inline_and_file_conflict(self):
        with patch.dict(
            os.environ, {"EXAMPLE": "inline", "EXAMPLE_FILE": str(self.path)}, clear=True
        ):
            with self.assertRaisesRegex(ValueError, "only one"):
                MODULE.environment_secret("EXAMPLE")

    def test_missing_file_has_no_inline_fallback(self):
        self.path.unlink()
        with patch.dict(os.environ, {"EXAMPLE_FILE": str(self.path)}, clear=True):
            with self.assertRaises(ValueError):
                MODULE.environment_secret("EXAMPLE", "fallback")

    def test_unsafe_files_are_rejected(self):
        for mode in (0o644, 0o440, 0o700):
            with self.subTest(mode=mode):
                self.path.chmod(mode)
                with self.assertRaises(ValueError):
                    MODULE.read_secret_file(str(self.path), "EXAMPLE")
        self.path.unlink()
        self.path.mkdir()
        with self.assertRaises(ValueError):
            MODULE.read_secret_file(str(self.path), "EXAMPLE")

    def test_link_and_fifo_are_rejected(self):
        link = self.path.with_name("link")
        link.symlink_to(self.path)
        with self.assertRaises(ValueError):
            MODULE.read_secret_file(str(link), "EXAMPLE")
        pipe = self.path.with_name("pipe")
        os.mkfifo(pipe, 0o600)
        with self.assertRaises(ValueError):
            MODULE.read_secret_file(str(pipe), "EXAMPLE")

    def test_empty_binary_and_oversized_values_are_rejected_without_contents(self):
        for data in (b" ", b"\xffinvalid-local-fixture", b"a\x00b", b"x" * 65537):
            self.path.chmod(0o600)
            self.path.write_bytes(data)
            with self.assertRaises(ValueError) as caught:
                MODULE.read_secret_file(str(self.path), "EXAMPLE")
            self.assertNotIn("invalid-local-fixture", str(caught.exception))

    def test_rotated_file_is_read_on_next_load(self):
        replacement = self.path.with_name("replacement")
        replacement.write_text("rotated-fixture")
        replacement.chmod(0o400)
        replacement.replace(self.path)
        self.assertEqual(MODULE.read_secret_file(str(self.path), "EXAMPLE"), "rotated-fixture")

    def test_settings_resolve_declared_file_without_exposing_value_in_repr(self):
        from larimia.config import Settings

        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None, database_url_file=str(self.path))
            self.assertEqual(settings.database_url, "invalid-local-fixture")
            self.assertNotIn("invalid-local-fixture", repr(settings))
            with self.assertRaises(ValueError):
                Settings(_env_file=None, database_url="inline", database_url_file=str(self.path))

    def test_file_environment_uses_application_prefix(self):
        from larimia.config import Settings

        with patch.dict(os.environ, {"LARIMIA_DATABASE_URL_FILE": str(self.path)}, clear=True):
            settings = Settings(_env_file=None)
            self.assertEqual(settings.database_url, "invalid-local-fixture")


if __name__ == "__main__":
    unittest.main()
