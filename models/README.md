# Qwen3.8 Flash Next IQ3_S model files

This deployment uses the public
[`SC117/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-GGUF`](https://huggingface.co/SC117/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-GGUF)
model at immutable revision `90a3350cd800ec1fe0d1660a38414ad9e985782f`.
The model card declares Apache-2.0. Review the model card and license before use.

> **Safety notice:** this is an abliterated/refusal-removed variant. Safety refusals
> may be reduced or absent. Review its suitability for your application, evaluate
> outputs, apply appropriate content safeguards, and enforce authentication and
> access control. Do not expose an unauthenticated public endpoint.

Model weights and generated packs must not be committed to Git.

## Disk space

- Two GGUF shards: approximately **83.86 GB** (decimal).
- Strata runtime/MTP files: approximately **0.824 GB** additional.
- Generated native pack: approximately **49 GB** additional; actual size varies by
  pack version, so measure the generated output.
- Downloads use resumable `.part` files. Keep enough additional working space and
  do not delete a partial download while a downloader is using it.

The native pack is model- and revision-specific. Regenerate it from these exact
GGUF shards; do not reuse a pack produced for another model or revision.

## Download and verify

`scripts/lib.sh` loads the local deployment configuration and supplies
`MODEL_DIR` and `PACK_JOBS`. The default model location is `${DATA_DIR}/model`,
matching the profile in `models/iq3s.env`; local configuration can override it.

From the repository root:

```bash
source scripts/lib.sh
load_config
./scripts/download-model.sh
./scripts/model.py check --model-dir "${MODEL_DIR}" --hash
```

The downloader uses only Python's standard library and system `curl`. It first
checks paths and LFS object IDs through the Hugging Face API, resumes into
`.part` files, and renames a file only after its expected size and SHA256 match.
Existing verified files are skipped. Incomplete or invalid downloads are kept for
diagnosis/resume and cause a nonzero exit rather than being silently removed.
An invalid file already at a final destination is never overwritten automatically.

The official endpoint is `https://huggingface.co`. Set `HF_ENDPOINT` to select an
HTTPS mirror. TLS certificate verification remains enabled. `HF_TOKEN` is optional
and is used only for public or otherwise authorized downloads; never store it in
repository files, environment files, command logs, or build logs.

Expected public files:

| Relative path | Bytes | SHA256 |
| --- | ---: | --- |
| `IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-IQ3_S-00001-of-00002.gguf` | 55063448064 | `40f369eca301ec6ea318dbb671b3132c26a2f0b89aa5458a7051b33215ee296c` |
| `IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-IQ3_S-00002-of-00002.gguf` | 28800138432 | `316b46f3a2dbd68c900f43136ab9449f9dcc3725dfd8c794847c204bc161e113` |
| `strata/rt/experts.bin` | 707788800 | `09398406be61f1f54c93861f449e48b8df0bfccbc9ec9b2b7636775a6ea9244f` |
| `strata/rt/dense.bin` | 116099072 | `c724dc0b0822ada5d2977bf5bde821605feabaa64ea2e0045b67ca656329070a` |
| `strata/rt/draft_vocab.bin` | 425196 | `b1e1d3a7a9e4bf862dcd5923ce661fb59bbd07907e594df5cf86a62ac235cb91` |

## Generate and inspect the native pack

After the image is available and all five files have been downloaded:

```bash
./scripts/pack-model.sh
./scripts/model.py pack-info --model-dir "${MODEL_DIR}"
```

Packing runs `iq_pack.py` in Docker with no network, all capabilities dropped,
`no-new-privileges`, a read-only root filesystem, a temporary `/tmp`, and CPU
limits from `PACK_JOBS`. Only this packing container receives a writable bind
mount of the model directory; production serving must mount it read-only.

`pack-info` requires `pack/iq3_s/dense.bin`, `experts.bin`, `index.txt`,
`native_experts.txt` with exactly 48 non-empty records, and a `tokenizer`
directory.
