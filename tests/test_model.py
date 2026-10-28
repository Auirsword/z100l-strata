import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import urllib.error

MODEL_PATH = Path(__file__).resolve().parents[1] / "scripts" / "model.py"
SPEC = importlib.util.spec_from_file_location("strata_model", MODEL_PATH)
model = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(model)

SMALL_FILES = {
    "shard/first.gguf": b"abc",
    "runtime/dense.bin": b"defgh",
}
SMALL_EXPECTED = {
    path: (len(content), hashlib.sha256(content).hexdigest())
    for path, content in SMALL_FILES.items()
}


class FakeResponse:
    def __init__(self, payload, status=200):
        self.body = json.dumps(payload).encode("utf-8")
        self.status = status

    def getcode(self):
        return self.status

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


def remote_entries(expected):
    return [
        {
            "type": "file",
            "path": path,
            "size": size,
            "lfs": {"oid": sha256, "size": size},
        }
        for path, (size, sha256) in expected.items()
    ]


def write_model_files(root, files=SMALL_FILES):
    for relative_path, content in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def make_pack(root, native_records=48, tokenizer=True):
    pack = root / "pack" / "iq3_s"
    pack.mkdir(parents=True)
    for name in ("dense.bin", "experts.bin", "index.txt"):
        (pack / name).write_bytes(b"fixture")
    (pack / "native_experts.txt").write_text(
        "# strata native experts v3: fixture\n"
        + "\n".join(f"{index} 18 20 0 2176000 0 0 0" for index in range(native_records)) + "\n\n",
        encoding="utf-8",
    )
    if tokenizer:
        (pack / "tokenizer").mkdir()


class ModelTestCase(unittest.TestCase):
    def run_main(self, argv):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = model.main(argv)
        return result, stdout.getvalue(), stderr.getvalue()

    def isolated_environment(self):
        return mock.patch.dict(
            os.environ, {"HF_ENDPOINT": "https://fixtures.invalid"}, clear=True
        )


class ManifestTests(ModelTestCase):
    def test_public_manifest_sizes_and_hashes(self):
        self.assertEqual(
            model.EXPECTED,
            {
                "IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-IQ3_S-00001-of-00002.gguf": (
                    55063448064,
                    "40f369eca301ec6ea318dbb671b3132c26a2f0b89aa5458a7051b33215ee296c",
                ),
                "IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-IQ3_S-00002-of-00002.gguf": (
                    28800138432,
                    "316b46f3a2dbd68c900f43136ab9449f9dcc3725dfd8c794847c204bc161e113",
                ),
                "strata/rt/experts.bin": (
                    707788800,
                    "09398406be61f1f54c93861f449e48b8df0bfccbc9ec9b2b7636775a6ea9244f",
                ),
                "strata/rt/dense.bin": (
                    116099072,
                    "c724dc0b0822ada5d2977bf5bde821605feabaa64ea2e0045b67ca656329070a",
                ),
                "strata/rt/draft_vocab.bin": (
                    425196,
                    "b1e1d3a7a9e4bf862dcd5923ce661fb59bbd07907e594df5cf86a62ac235cb91",
                ),
            },
        )
        self.assertEqual(sum(size for size, _ in model.EXPECTED.values()), 84687899564)
        self.assertEqual(
            sum(size for path, (size, _) in model.EXPECTED.items() if path.startswith("strata/")),
            824313068,
        )
        self.assertEqual(model.REVISION, "90a3350cd800ec1fe0d1660a38414ad9e985782f")


class CheckTests(ModelTestCase):
    def test_check_size_and_hash_accepts_complete_fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_model_files(root)
            with mock.patch.object(model, "EXPECTED", SMALL_EXPECTED):
                result, _, errors = self.run_main(
                    ["check", "--model-dir", str(root), "--hash"]
                )
            self.assertEqual(result, 0, errors)

    def test_check_rejects_missing_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_model_files(root)
            (root / "shard" / "first.gguf").unlink()
            with mock.patch.object(model, "EXPECTED", SMALL_EXPECTED):
                result, _, errors = self.run_main(["check", "--model-dir", str(root)])
            self.assertEqual(result, 1)
            self.assertIn("missing", errors)

    def test_check_rejects_truncated_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_model_files(root)
            (root / "shard" / "first.gguf").write_bytes(b"a")
            with mock.patch.object(model, "EXPECTED", SMALL_EXPECTED):
                result, _, errors = self.run_main(["check", "--model-dir", str(root)])
            self.assertEqual(result, 1)
            self.assertIn("size mismatch", errors)

    def test_check_hash_rejects_same_size_corruption(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_model_files(root)
            (root / "shard" / "first.gguf").write_bytes(b"abd")
            with mock.patch.object(model, "EXPECTED", SMALL_EXPECTED):
                result, _, errors = self.run_main(
                    ["check", "--model-dir", str(root), "--hash"]
                )
            self.assertEqual(result, 1)
            self.assertIn("SHA256 mismatch", errors)


class PackInfoTests(ModelTestCase):
    def test_pack_info_accepts_complete_fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_pack(root)
            result, _, errors = self.run_main(["pack-info", "--model-dir", str(root)])
            self.assertEqual(result, 0, errors)

    def test_pack_info_rejects_missing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_pack(root)
            (root / "pack" / "iq3_s" / "dense.bin").unlink()
            result, _, errors = self.run_main(["pack-info", "--model-dir", str(root)])
            self.assertEqual(result, 1)
            self.assertIn("dense.bin", errors)

    def test_pack_info_rejects_incomplete_native_expert_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_pack(root, native_records=47)
            result, _, errors = self.run_main(["pack-info", "--model-dir", str(root)])
            self.assertEqual(result, 1)
            self.assertIn("expected 48", errors)

    def test_pack_info_rejects_missing_tokenizer_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_pack(root, tokenizer=False)
            result, _, errors = self.run_main(["pack-info", "--model-dir", str(root)])
            self.assertEqual(result, 1)
            self.assertIn("tokenizer", errors)


class ApiTests(ModelTestCase):
    def test_api_manifest_validates_paths_and_lfs_oids(self):
        with self.isolated_environment(), mock.patch.object(
            model, "EXPECTED", SMALL_EXPECTED
        ), mock.patch.object(
            model.urllib.request,
            "urlopen",
            return_value=FakeResponse(remote_entries(SMALL_EXPECTED)),
        ) as urlopen:
            entries = model.fetch_remote_manifest()
        self.assertEqual(set(entries), set(SMALL_EXPECTED))
        request = urlopen.call_args.args[0]
        self.assertIn("/api/models/", request.full_url)
        self.assertIn(model.REVISION, request.full_url)
        self.assertNotIn("Authorization", request.headers)

    def test_api_network_error_is_fatal(self):
        with self.isolated_environment(), mock.patch.object(
            model.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError("offline fixture"),
        ):
            with self.assertRaisesRegex(model.ModelError, "request failed"):
                model.fetch_remote_manifest()

    def test_api_non_200_is_fatal(self):
        with self.isolated_environment(), mock.patch.object(
            model.urllib.request, "urlopen", return_value=FakeResponse([], status=503)
        ):
            with self.assertRaisesRegex(model.ModelError, "HTTP 503"):
                model.fetch_remote_manifest()

    def test_api_http_exception_is_fatal(self):
        error = urllib.error.HTTPError(
            "https://fixtures.invalid", 403, "fixture", {}, None
        )
        with self.isolated_environment(), mock.patch.object(
            model.urllib.request, "urlopen", side_effect=error
        ):
            with self.assertRaisesRegex(model.ModelError, "HTTP 403"):
                model.fetch_remote_manifest()

    def test_api_missing_expected_path_is_fatal(self):
        entries = remote_entries(SMALL_EXPECTED)[1:]
        with self.isolated_environment(), mock.patch.object(
            model, "EXPECTED", SMALL_EXPECTED
        ), mock.patch.object(
            model.urllib.request, "urlopen", return_value=FakeResponse(entries)
        ):
            with self.assertRaisesRegex(model.ModelError, "expected path"):
                model.fetch_remote_manifest()

    def test_api_hash_mismatch_is_fatal_and_does_not_replace_expected(self):
        entries = remote_entries(SMALL_EXPECTED)
        entries[0]["lfs"]["oid"] = "0" * 64
        expected_before = SMALL_EXPECTED.copy()
        with self.isolated_environment(), mock.patch.object(
            model, "EXPECTED", SMALL_EXPECTED
        ), mock.patch.object(
            model.urllib.request, "urlopen", return_value=FakeResponse(entries)
        ):
            with self.assertRaisesRegex(model.ModelError, "LFS SHA256 mismatch"):
                model.fetch_remote_manifest()
        self.assertEqual(SMALL_EXPECTED, expected_before)

    def test_insecure_endpoint_is_rejected(self):
        with mock.patch.dict(
            os.environ, {"HF_ENDPOINT": "http://fixtures.invalid"}, clear=True
        ):
            with self.assertRaisesRegex(model.ModelError, "HTTPS"):
                model.fetch_remote_manifest()


class DownloadTests(ModelTestCase):
    def test_download_resumes_part_file_verifies_and_renames_without_real_curl(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "shard" / "first.gguf"
            first.parent.mkdir(parents=True)
            first.with_name(first.name + ".part").write_bytes(b"a")
            commands = []

            def fake_curl(command, check):
                commands.append(command)
                self.assertFalse(check)
                output = Path(command[command.index("--output") + 1])
                existing = output.read_bytes() if output.exists() else b""
                content = SMALL_FILES[
                    "shard/first.gguf" if "first.gguf" in output.name else "runtime/dense.bin"
                ]
                output.write_bytes(existing + content[len(existing) :])
                return subprocess.CompletedProcess(command, 0)

            with self.isolated_environment(), mock.patch.object(
                model, "EXPECTED", SMALL_EXPECTED
            ), mock.patch.object(model, "fetch_remote_manifest") as api, mock.patch.object(
                model.subprocess, "run", side_effect=fake_curl
            ):
                result, _, errors = self.run_main(["download", "--model-dir", str(root)])

            self.assertEqual(result, 0, errors)
            api.assert_called_once_with()
            self.assertEqual(len(commands), 2)
            for command in commands:
                self.assertEqual(command[0], "curl")
                self.assertIn("--fail", command)
                self.assertIn("--location", command)
                self.assertEqual(command[command.index("--retry") + 1], "5")
                self.assertEqual(command[command.index("--continue-at") + 1], "-")
                self.assertNotIn("--insecure", command)
            for relative_path, content in SMALL_FILES.items():
                destination = root / relative_path
                self.assertEqual(destination.read_bytes(), content)
                self.assertFalse(destination.with_name(destination.name + ".part").exists())

    def test_existing_verified_files_skip_curl(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_model_files(root)
            with self.isolated_environment(), mock.patch.object(
                model, "EXPECTED", SMALL_EXPECTED
            ), mock.patch.object(model, "fetch_remote_manifest"), mock.patch.object(
                model.subprocess, "run"
            ) as curl:
                result, _, errors = self.run_main(["download", "--model-dir", str(root)])
            self.assertEqual(result, 0, errors)
            curl.assert_not_called()

    def test_curl_failure_is_nonzero_and_retains_partial_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def failed_curl(command, check):
                output = Path(command[command.index("--output") + 1])
                output.write_bytes(b"a")
                return subprocess.CompletedProcess(command, 7)

            with self.isolated_environment(), mock.patch.object(
                model, "EXPECTED", {"shard/first.gguf": SMALL_EXPECTED["shard/first.gguf"]}
            ), mock.patch.object(model, "fetch_remote_manifest"), mock.patch.object(
                model.subprocess, "run", side_effect=failed_curl
            ):
                result, _, errors = self.run_main(["download", "--model-dir", str(root)])
            self.assertEqual(result, 1)
            self.assertIn("curl failed", errors)
            self.assertFalse((root / "shard" / "first.gguf").exists())
            self.assertEqual((root / "shard" / "first.gguf.part").read_bytes(), b"a")

    def test_downloaded_hash_mismatch_is_nonzero_and_never_renamed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def corrupt_curl(command, check):
                output = Path(command[command.index("--output") + 1])
                output.write_bytes(b"abd")
                return subprocess.CompletedProcess(command, 0)

            with self.isolated_environment(), mock.patch.object(
                model, "EXPECTED", {"shard/first.gguf": SMALL_EXPECTED["shard/first.gguf"]}
            ), mock.patch.object(model, "fetch_remote_manifest"), mock.patch.object(
                model.subprocess, "run", side_effect=corrupt_curl
            ):
                result, _, errors = self.run_main(["download", "--model-dir", str(root)])
            self.assertEqual(result, 1)
            self.assertIn("SHA256 mismatch", errors)
            self.assertFalse((root / "shard" / "first.gguf").exists())
            self.assertEqual((root / "shard" / "first.gguf.part").read_bytes(), b"abd")

    def test_invalid_existing_destination_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "shard" / "first.gguf"
            destination.parent.mkdir(parents=True)
            destination.write_bytes(b"a")
            with self.isolated_environment(), mock.patch.object(
                model, "EXPECTED", {"shard/first.gguf": SMALL_EXPECTED["shard/first.gguf"]}
            ), mock.patch.object(model, "fetch_remote_manifest"), mock.patch.object(
                model.subprocess, "run"
            ) as curl:
                result, _, errors = self.run_main(["download", "--model-dir", str(root)])
            self.assertEqual(result, 1)
            self.assertIn("refusing to overwrite", errors)
            self.assertEqual(destination.read_bytes(), b"a")
            curl.assert_not_called()


if __name__ == "__main__":
    unittest.main()
