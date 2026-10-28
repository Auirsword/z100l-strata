# Notices

This is an independent community deployment package for Hygon Z100L. It is not
an official Hygon, AMD, Qwen, or Strata release.

- [Strata](https://github.com/Niko1221/Strata): MIT License, Copyright (c) 2026
  Niko1221 and the Strata contributors. `patches/strata/` contains modifications
  to the pinned upstream source. The upstream license is included in the source
  checkout and runtime image.
- [llama.cpp / ggml](https://github.com/ggml-org/llama.cpp): MIT License.
  Strata uses ggml for quantization formats and CPU expert dot products; the
  main Strata engine is not a llama.cpp fork.
- Model weights and the Hygon DTK are **not bundled**. Users obtain them from
  their respective publishers and are responsible for their license terms.
- The selected model card declares Apache-2.0. Its abliterated/refusal-removed
  nature is a deployment-safety concern, not a claim of general model quality.
  Review the model card and provide your own moderation and access controls.

The container build downloads public source code at pinned revisions. No API
credentials, proprietary DTK files, user conversations, or model weights are
included in this repository.
