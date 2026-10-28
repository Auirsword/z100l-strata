import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("configure", ROOT / "scripts/configure.py")
configure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(configure)


class ConfigureTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        configure.ROOT = self.root / "repo"
        configure.ROOT.mkdir()
        self.data = self.root / "data"
        self.model = self.root / "model"

    def tearDown(self):
        self.temp.cleanup()

    def run_config(self, *extra):
        argv = ["configure.py", "--data-dir", str(self.data), "--model-dir", str(self.model), *extra]
        with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
            configure.main()
        return json.loads((self.data / "config/serve.json").read_text())

    def test_conservative_defaults(self):
        with mock.patch.object(configure, "meminfo", return_value={"MemTotal": 64 * 2**30, "MemAvailable": 48 * 2**30}):
            cfg = self.run_config()
        self.assertEqual(cfg["parallel"], 1)
        self.assertEqual(cfg["conversation_cache_slots"], 4)
        self.assertEqual(cfg["conversation_cache_mib"], 8192)
        self.assertEqual(cfg["env"]["STRATA_ARENA_MMAP"], "1")
        self.assertNotIn("STRATA_SH_STREAM", cfg["env"])
        self.assertNotIn("vision", cfg)
        self.assertFalse(cfg["admit_affinity"])
        self.assertIn("32768", cfg["args"])
        self.assertIn("--conversation-disk-dir", cfg["args"])

    def test_tuned_preset(self):
        memory = {"MemTotal": 512 * 2**30, "MemAvailable": 400 * 2**30}
        with mock.patch.object(configure, "meminfo", return_value=memory), \
                mock.patch.object(configure.shutil, "disk_usage", return_value=shutil._ntuple_diskusage(1024**4, 0, 1024**4)):
            cfg = self.run_config("--preset", "z100l-32g-tuned")
        self.assertEqual(cfg["parallel"], 4)
        self.assertEqual(cfg["conversation_cache_mib"], 131072)
        self.assertEqual(cfg["env"]["STRATA_ARENA_MMAP"], "0")
        self.assertEqual(cfg["env"]["STRATA_SH_STREAM"], "0")
        self.assertIn("262144", cfg["args"])
        self.assertIn("--batch-mtp", cfg["args"])

    def test_tuned_refuses_small_host(self):
        with mock.patch.object(configure, "meminfo", return_value={"MemTotal": 64 * 2**30, "MemAvailable": 32 * 2**30}):
            with self.assertRaises(SystemExit):
                self.run_config("--preset", "z100l-32g-tuned")

    def test_context_can_be_smaller(self):
        cfg = self.run_config("--max-context", "65536")
        self.assertIn("65536", cfg["args"])
        self.assertIn("32768", cfg["args"])

    def test_rejects_invalid_context(self):
        with self.assertRaises(SystemExit):
            self.run_config("--max-context", "12345")


if __name__ == "__main__":
    unittest.main()
