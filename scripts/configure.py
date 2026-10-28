#!/usr/bin/env python3
"""Generate a local, non-secret deployment configuration."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
FIRST_SHARD = "IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-IQ3_S-00001-of-00002.gguf"
SECOND_SHARD = "IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-IQ3_S-00002-of-00002.gguf"


def meminfo():
    result = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            result[key] = int(value.split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return result


def absolute(value):
    return Path(value).expanduser().resolve()


def write(path, content, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.chmod(temporary, mode)
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", choices=("conservative", "z100l-32g-tuned"), default=os.environ.get("PRESET", "conservative"))
    parser.add_argument("--model-dir", default=os.environ.get("MODEL_DIR"))
    parser.add_argument("--data-dir", default=os.environ.get("DATA_DIR"))
    parser.add_argument("--max-context", type=int)
    args = parser.parse_args()
    data = absolute(args.data_dir or (Path.home() / ".local/share/z100l-strata"))
    model = absolute(args.model_dir or (data / "model"))
    tuned = args.preset == "z100l-32g-tuned"
    context = args.max_context or (262144 if tuned else 32768)
    if context < 4096 or context > 262144:
        parser.error("max-context must be between 4096 and 262144")
    if context % 1024:
        parser.error("max-context must be a multiple of 1024")
    memory = meminfo()
    total = memory.get("MemTotal", 0)
    available = memory.get("MemAvailable", total)
    if tuned and (total < 224 * 2**30 or available < 160 * 2**30):
        parser.error("tuned preset needs 224 GiB total RAM and 160 GiB currently available; use conservative")
    if tuned:
        free = shutil.disk_usage(data.parent if not data.exists() else data).free
        if free < 340 * 2**30:
            parser.error("tuned preset needs at least 340 GiB free on the data filesystem")
    l2_mib = 131072 if tuned else min(8192, max(2048, available // (4 * 2**20)))
    l3_gib = 200 if tuned else 32
    args_list = [
        "--pack", "/model/pack/iq3_s",
        "--native", "/model/" + FIRST_SHARD,
        "--ple-gguf", "/model/" + SECOND_SHARD,
        "--expert-profile", "/opt/strata/src/data/expert-profile.bin",
        "--mtp", "/model/strata/rt",
        "--max-context", str(context),
        "--kv", "int8",
        "--kv-resident", str(min(32768, context)),
        "--prefill", "4096",
        "--spec", "4", "--spec-min-p", "0.5", "--pcie-frac", "0",
        "--expert-cache", "auto",
        "--conversation-cache-mib", str(l2_mib),
        "--conversation-cache-slots", "16" if tuned else "4",
        "--conversation-disk-dir", "/state/conversations",
        "--conversation-disk-gib", str(l3_gib),
    ]
    if tuned:
        args_list.append("--batch-mtp")
    environment = {
        "STRATA_ARENA_MMAP": "0" if tuned else "1",
        "STRATA_EXP_MODE": "0",
        "STRATA_EXPDEC": "1",
    }
    if tuned:
        environment["STRATA_SH_STREAM"] = "0"
    serve = {
        "exe": "/opt/strata/bin/strata",
        "args": args_list,
        "parallel": 4 if tuned else 1,
        "tokenizer": "/model/pack/iq3_s/tokenizer",
        "model_name": "Qwen3.8-Flash-Next-IQ3_S",
        "cwd": "/opt/strata/src",
        "log": "/state/logs/engine.log",
        "host": "0.0.0.0" if os.environ.get("DOCKER_NETWORK", "bridge") == "bridge" else os.environ.get("PUBLISH_HOST", "127.0.0.1"),
        "port": 18080,
        "conversation_cache_mib": l2_mib,
        "conversation_cache_slots": 16 if tuned else 4,
        "env": environment,
        "admit_affinity": False,
    }
    write(data / "config/serve.json", json.dumps(serve, ensure_ascii=False, indent=2) + "\n")
    (data / "conversations").mkdir(parents=True, exist_ok=True)
    (data / "logs").mkdir(parents=True, exist_ok=True)
    env_path = ROOT / ".env"
    replacements = {"PRESET": args.preset, "DATA_DIR": str(data), "MODEL_DIR": str(model)}
    lines = []
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            key = line.split("=", 1)[0]
            if key not in replacements:
                lines.append(line)
    lines.extend(f"{key}={shlex.quote(value)}" for key, value in replacements.items())
    write(env_path, "\n".join(lines) + "\n", 0o600)
    print(f"configuration: {data / 'config/serve.json'}")
    print(f"preset={args.preset} context={context} L2={l2_mib}MiB L3={l3_gib}GiB")


if __name__ == "__main__":
    try:
        main()
    except OSError as error:
        sys.exit(f"configure: {error}")
