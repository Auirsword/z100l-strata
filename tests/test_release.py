from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReleaseTest(unittest.TestCase):
    def test_no_unsafe_container_defaults(self):
        files = [ROOT / "docker/Dockerfile", ROOT / "scripts/run.sh", ROOT / "scripts/pack-model.sh"]
        for path in files:
            if not path.exists():
                continue
            text = path.read_text()
            self.assertNotIn("--privileged", text)
            self.assertNotIn("seccomp=unconfined", text)
            self.assertNotIn("--network=host", text)
            self.assertNotIn("--cap-add", text)

    def test_dtk_apparmor_profile_keeps_container_boundaries(self):
        profile = (ROOT / "security/z100l-strata.apparmor").read_text()
        self.assertIn("profile z100l-strata", profile)
        self.assertIn("network unix stream,", profile)
        self.assertIn("deny mount,", profile)
        self.assertNotIn("network,", profile)
        self.assertIn('DOCKER_APPARMOR=z100l-strata', (ROOT / "config/default.env").read_text())

    def test_no_local_deployment_artifacts(self):
        forbidden = re.compile(r"(?i)192\.168\.|100\.102\.|43\.155\.|sslip\.io|/data/build|pve\.local|core\.[0-9]+|BEGIN (?:RSA |OPENSSH )?PRIVATE KEY|(?:password|passwd|api[_-]?key|secret)[\w-]*\s*[:=]\s*[\"'][^\"'\n]+[\"']")
        for path in ROOT.rglob("*"):
            if path.resolve() == Path(__file__).resolve() or path.name == ".env":
                continue
            if not path.is_file() or any(part in {".git", ".work", "state", "__pycache__"} for part in path.parts):
                continue
            if path.suffix in {".gguf", ".bin", ".session", ".db", ".log"}:
                self.fail(f"local artifact should not be published: {path}")
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            self.assertIsNone(forbidden.search(text), f"local/private reference in {path}")

    def test_no_large_files(self):
        for path in ROOT.rglob("*"):
            if path.is_file() and ".git" not in path.parts and ".work" not in path.parts:
                self.assertLess(path.stat().st_size, 20 * 1024 * 1024, f"unexpected large artifact: {path}")

    def test_local_config_is_ignored(self):
        ignored = (ROOT / ".gitignore").read_text()
        for name in (".env", ".work/", "state/", "*.gguf", "*.session", "*.db", "core.*"):
            self.assertIn(name, ignored)

    def test_entrypoints_are_executable(self):
        paths = [ROOT / "install.sh", ROOT / "docker/entrypoint.sh", ROOT / "tests/shell.sh"]
        paths.extend((ROOT / "scripts").glob("*.sh"))
        for path in paths:
            self.assertTrue(path.stat().st_mode & 0o100, f"not executable: {path}")


if __name__ == "__main__":
    unittest.main()
