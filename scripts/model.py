#!/usr/bin/env python3
"""Download and validate the public Qwen3.8 Flash Next IQ3_S model files."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_DIR = REPO_ROOT / "models" / "iq3_s"
MODEL_REPO = "SC117/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-GGUF"
REVISION = "90a3350cd800ec1fe0d1660a38414ad9e985782f"
DEFAULT_ENDPOINT = "https://huggingface.co"
EXPECTED = {
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
}
NATIVE_EXPERT_RECORDS = 48
HASH_CHUNK_SIZE = 8 * 1024 * 1024


class ModelError(RuntimeError):
    pass


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(HASH_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def validate_file(path, expected_size, expected_sha256, verify_hash=True):
    if not path.is_file():
        raise ModelError(f"missing or not a regular file: {path}")
    actual_size = path.stat().st_size
    if actual_size != expected_size:
        raise ModelError(
            f"size mismatch for {path}: expected {expected_size}, got {actual_size}"
        )
    if verify_hash:
        actual_sha256 = sha256_file(path)
        if actual_sha256 != expected_sha256:
            raise ModelError(
                f"SHA256 mismatch for {path}: expected {expected_sha256}, "
                f"got {actual_sha256}"
            )


def check_model(model_dir, verify_hash=False):
    errors = []
    for relative_path, (size, sha256) in EXPECTED.items():
        path = model_dir / relative_path
        try:
            validate_file(path, size, sha256, verify_hash=verify_hash)
        except (ModelError, OSError) as exc:
            errors.append(str(exc))
        else:
            suffix = " (size and SHA256 OK)" if verify_hash else " (size OK)"
            print(f"{relative_path}{suffix}")
    if errors:
        raise ModelError("\n".join(errors))


def check_pack(model_dir):
    pack_dir = model_dir / "pack" / "iq3_s"
    errors = []
    for name in ("dense.bin", "experts.bin", "index.txt", "native_experts.txt"):
        if not (pack_dir / name).is_file():
            errors.append(f"missing or not a regular file: {pack_dir / name}")
    if not (pack_dir / "tokenizer").is_dir():
        errors.append(f"missing tokenizer directory: {pack_dir / 'tokenizer'}")

    native_experts = pack_dir / "native_experts.txt"
    if native_experts.is_file():
        try:
            layers = []
            with native_experts.open("r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, 1):
                    if not line.strip() or line.lstrip().startswith("#"):
                        continue
                    try:
                        layers.append(int(line.split()[0]))
                    except (ValueError, IndexError):
                        errors.append(f"{native_experts}:{line_number}: invalid layer record")
            if sorted(layers) != list(range(NATIVE_EXPERT_RECORDS)):
                errors.append(
                    f"{native_experts}: expected {NATIVE_EXPERT_RECORDS} layer records "
                    f"(0..{NATIVE_EXPERT_RECORDS - 1}), got {len(layers)}"
                )
        except (OSError, UnicodeError) as exc:
            errors.append(f"cannot read {native_experts}: {exc}")

    if errors:
        raise ModelError("\n".join(errors))
    print(f"pack OK: {pack_dir} ({NATIVE_EXPERT_RECORDS} native expert records)")


def hf_endpoint():
    endpoint = os.environ.get("HF_ENDPOINT", DEFAULT_ENDPOINT).rstrip("/")
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise ModelError("HF_ENDPOINT must be an HTTPS URL")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ModelError("HF_ENDPOINT must not contain credentials, query, or fragment")
    return endpoint


def authorized_request(url):
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "z100l-strata-model/1"}
    )
    token = os.environ.get("HF_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    return request


def fetch_remote_manifest():
    endpoint = hf_endpoint()
    revision = urllib.parse.quote(REVISION, safe="")
    query = urllib.parse.urlencode({"recursive": "true", "expand": "true"})
    url = f"{endpoint}/api/models/{MODEL_REPO}/tree/{revision}?{query}"
    try:
        with urllib.request.urlopen(authorized_request(url), timeout=60) as response:
            status = response.getcode()
            if status != 200:
                raise ModelError(f"Hugging Face API returned HTTP {status}")
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise ModelError(f"Hugging Face API returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ModelError(f"Hugging Face API request failed: {exc}") from exc

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ModelError("Hugging Face API returned invalid JSON") from exc
    if not isinstance(payload, list):
        raise ModelError("Hugging Face API returned an unexpected manifest")

    entries = {}
    for entry in payload:
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            entries[entry["path"]] = entry

    for relative_path, (expected_size, expected_sha256) in EXPECTED.items():
        entry = entries.get(relative_path)
        if entry is None or entry.get("type", "file") != "file":
            raise ModelError(f"Hugging Face API did not return expected path: {relative_path}")
        lfs = entry.get("lfs")
        if not isinstance(lfs, dict) or lfs.get("oid") != expected_sha256:
            raise ModelError(f"LFS SHA256 mismatch from Hugging Face API for {relative_path}")
        remote_size = lfs.get("size", entry.get("size"))
        if remote_size is not None and remote_size != expected_size:
            raise ModelError(f"LFS size mismatch from Hugging Face API for {relative_path}")
    return entries


def download_model(model_dir):
    fetch_remote_manifest()
    endpoint = hf_endpoint()
    token = os.environ.get("HF_TOKEN")

    for relative_path, (size, sha256) in EXPECTED.items():
        destination = model_dir / relative_path
        if destination.exists():
            try:
                validate_file(destination, size, sha256, verify_hash=True)
            except (ModelError, OSError) as exc:
                raise ModelError(
                    f"refusing to overwrite invalid existing file {destination}: {exc}"
                ) from exc
            print(f"already verified, skipping: {relative_path}")
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".part")
        quoted_path = urllib.parse.quote(relative_path, safe="/")
        revision = urllib.parse.quote(REVISION, safe="")
        url = f"{endpoint}/{MODEL_REPO}/resolve/{revision}/{quoted_path}"
        command = [
            "curl",
            "--fail",
            "--location",
            "--retry",
            "5",
            "--continue-at",
            "-",
            "--silent",
            "--show-error",
            "--output",
            str(partial),
        ]
        if token:
            command.extend(["--header", f"Authorization: Bearer {token}"])
        command.append(url)

        print(f"downloading: {relative_path}")
        try:
            result = subprocess.run(command, check=False)
        except OSError as exc:
            raise ModelError(f"could not execute curl for {relative_path}: {exc}") from exc
        if result.returncode != 0:
            raise ModelError(
                f"curl failed for {relative_path} with exit code {result.returncode}; "
                f"partial data retained at {partial}"
            )
        try:
            validate_file(partial, size, sha256, verify_hash=True)
        except (ModelError, OSError) as exc:
            raise ModelError(
                f"downloaded file failed validation; partial data retained at {partial}: {exc}"
            ) from exc
        partial.replace(destination)
        print(f"verified: {relative_path}")


def resolve_model_dir(argument):
    value = argument or os.environ.get("MODEL_DIR")
    return Path(value).expanduser() if value else DEFAULT_MODEL_DIR


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("check", "pack-info", "download"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--model-dir", help="model root (defaults to MODEL_DIR)")
        if command == "check":
            subparser.add_argument(
                "--hash", action="store_true", dest="verify_hash", help="verify SHA256"
            )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    model_dir = resolve_model_dir(args.model_dir)
    try:
        if args.command == "check":
            check_model(model_dir, verify_hash=args.verify_hash)
        elif args.command == "pack-info":
            check_pack(model_dir)
        else:
            download_model(model_dir)
    except (ModelError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
