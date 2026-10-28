# Z100L × Strata

在海光 DCU **Z100L（gfx906、32GB）**上部署 **Strata + Qwen3.8-Flash-Next IQ3_S** 的独立开源包。包含 DTK 适配、容器构建、模型校验、native pack、MTP、L2/L3 会话缓存与性能复现工具。

这是社区移植，不是海光或 Strata 官方支持声明。当前只覆盖单卡文本推理；不包含 API 分发网关、公网转发、视觉、BMC 或生产侧私有资产。

## 一键部署

前置条件：x86_64 Linux、正常工作的 DCU 驱动与 DTK、Docker、Git、curl、Python 3。先确认宿主能够使用 GPU；本包不安装驱动、不执行 PCI/GPU reset。

```bash
git clone https://github.com/Auirsword/z100l-strata.git
cd z100l-strata
./install.sh --download-model
```

命令会依次生成保守配置、获取固定版本源码并应用补丁、构建容器、下载并校验模型、生成 native pack、启动本地服务。模型约 83.86GB，MTP 约 0.824GB，native pack 约 49GB；下载与构建需要时间和额外磁盘空间。

已有模型文件时：

```bash
./install.sh --model-dir /absolute/path/to/model
```

只验证源码与容器构建，不下载模型、不启动服务：

```bash
./install.sh --build-only
```

默认入口为 `http://127.0.0.1:18080`。`run.sh` 不会覆盖其他推理容器；`stop.sh` 仅停止本包的 `z100l-strata` 容器，先等待优雅退出，不强杀进程。

```bash
python3 scripts/smoke.py --wait 900
python3 scripts/smoke.py --generate   # 一个短的公开合成文本请求
./scripts/stop.sh
```

## 服务器适配

默认 DTK/HAL 路径为 `/opt/dtk`、`/opt/hyhal`。可通过 `.env` 修改：

```bash
DTK_DIR=/absolute/path/to/dtk
HYHAL_DIR=/absolute/path/to/hyhal
GPU_ID=0
PORT=18080
BUILD_JOBS=4
PACK_JOBS=4
```

`GPU_ID` 是 HIP 逻辑设备序号，不等同于 PCI BDF。需要指定渲染节点时可设置 `GPU_RENDER_DEVICE=/dev/dri/renderD...`，否则暴露本机 DRI 节点。PVE/AppArmor 环境若已确认需要，可显式设置 `DOCKER_APPARMOR=unconfined`；默认不关闭 AppArmor 或 seccomp，不使用 `--privileged`。

默认 `DOCKER_NETWORK=bridge`，只发布到宿主 `127.0.0.1`。若宿主 Docker 的端口映射不可用，可设置 `DOCKER_NETWORK=host` 并重新运行 `configure.sh`；此时服务仍只绑定 `PUBLISH_HOST=127.0.0.1`，不会监听局域网。只有在您明确需要暴露服务时才修改该地址。

**保守预设**：32K context、单会话、4 个 L2 槽位、32GiB L3。适合先验证安装，内存预算仍取决于模型、专家 cache、上下文和并发。

**Z100L 32GB 高配预设**：与已验证的高端工作点一致，启用 262K context、batch 4、pinned arena 与 shared-expert 调优：

```bash
./scripts/configure.sh --preset z100l-32g-tuned
./install.sh
```

该预设要求至少 224GiB 总内存、160GiB 当前可用内存和 340GiB 数据盘余量。低配服务器不要强行选择。建议先为模型、pack 和 L3 预留约 200GiB 磁盘；实际消耗以工具报告为准。生产调优后的 262K 已做单会话边界验证，不代表多个满 262K 会话已验证。

| 状态 | 范围 |
| --- | --- |
| 已实测 | Z100L 32GB、gfx906、DTK-26.10、EPYC AVX2、Linux 容器 |
| 同 ISA，未实测 | MI50 / MI60 / Radeon VII；不能自动视为同卡或同驱动 |
| 未在本包验证 | 其他 DTK 版本、NVIDIA、RDNA、ROCm、四卡或多实例 |

## 调用

本地服务使用上游 Strata 的 OpenAI/Anthropic 兼容接口，不额外提供 key 管理或公网转发。默认模型名为 `Qwen3.8-Flash-Next-IQ3_S`，API 不带鉴权，**不要直接暴露到不受信任网络**。

```bash
curl http://127.0.0.1:18080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "Qwen3.8-Flash-Next-IQ3_S",
    "stream": false,
    "max_tokens": 64,
    "messages": [{"role":"user","content":"用一句话介绍什么是 MoE。"}]
  }'
```

## 仓库结构

- `patches/strata/`：固定上游上的 DTK、L3 与可选准入适配。
- `scripts/prepare-source.sh`：固定 commit、检查并应用补丁。
- `scripts/download-model.sh`：下载公开模型并校验尺寸和 SHA-256。
- `scripts/pack-model.sh`：在容器中生成对应模型的 native pack。
- `scripts/configure.sh`：生成仅属于本机的 `.env` 和 `serve.json`，不会提交。
- `scripts/bench.py`：分别记录 prefill/decode，避免把墙钟或平均值误当整机吞吐。
- `docs/BENCHMARKS.md`：同卡对照与测量边界。
- `docs/HARDWARE.md`：Z100L 与 MI50、NVIDIA 各代硬件对照。
- `docs/zhihu/01-z100l-strata.md`：知乎系列首篇文章。

## 模型与安全

模型来自 [SC117/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-GGUF](https://huggingface.co/SC117/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-GGUF)，固定 revision，下载时校验 LFS OID 与已知 SHA-256。安装和 pack 默认也校验已有模型的完整哈希；已在上一轮完成校验时，可显式设置 `CHECK_MODEL_HASH=0` 跳过重复读盘，但不建议跳过首次验证。它是 **abliterated/refusal-removed** 模型，没有可靠的内置安全护栏。使用者需要自行提供内容审核、访问控制与法律评估；本包不代替这些措施。

模型权重、厂商 DTK、API 凭据和用户会话不进入 Git。DTK 在构建和运行时只读挂载，不会进入镜像层。模型目录在运行时只读，只有 `pack-model.sh` 临时开放写入。

上游为 [Niko1221/Strata](https://github.com/Niko1221/Strata)（MIT），其 ggml/llama.cpp 依赖也有独立许可。详见 [NOTICE.md](NOTICE.md)。

## 验证

```bash
python3 -m unittest discover -s tests -v
bash tests/shell.sh
```

测试不需要模型或 GPU。真实 GPU、完整模型、长上下文和持续负载会单独注明，不能由静态测试推断通过。已知限制和复测口径见 [性能文档](docs/BENCHMARKS.md)。
