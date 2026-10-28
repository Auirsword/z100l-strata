# Z100L 硬件与实验参考

本文记录 `Auirsword/z100l-strata` 所针对的硬件、模型拓扑、实测带宽和性能统计口径。除特别标注“官方标称”的项目外，数字只对应本次单卡测试机，不能外推为所有 Z100L 或其他显卡的实测结果。

## 1. 测试机与软件栈

| 项目 | 本次确认值 | 证据性质 |
| --- | --- | --- |
| GPU | 海光 DCU Z100L，gfx906，60 CU，32GB HBM2 | 本机识别与实验记录 |
| PCI 标识 | `1d94:55b7`，Display controller | 本机识别；设备 ID 可与海光社区资料交叉核对 |
| CPU | AMD EPYC 7F52，16C/32T，AVX2 | 本机识别；核心规格可由 [AMD EPYC 7002 官方页](https://www.amd.com/en/products/processors/server/epyc/7002-series.html) 核验 |
| 主机内存 | 8×32GB DDR4，合计 256GB，实际 2133 MT/s | DMI/实测；不是 3200 MT/s |
| 内存理论上限 | 约 136.5GB/s | 按八通道、2133 MT/s 估算，不是实测值 |
| GPU 软件栈 | DTK-26.10 | 本次移植与调优环境 |
| 上游引擎 | Niko1221/Strata，加 Z100L/DTK 必要兼容补丁 | 不代表上游原生认证 Z100L |

DTK 的 HIP 接口与 ROCm 有相似性，但运行时、编译默认值、厂商库、驱动/固件和虚拟化语义并不完全相同。不能把 DTK 简写成 ROCm 改名，也不能把 ROCm + MI50 的结果直接当成本机结果。

## 2. Z100L 与 MI50 的关系及硬件坐标

AMD 官方 MI50 32GB 规格为 Vega20、60 CU、3840 stream processors、32GB HBM2、4096-bit、1TB/s 峰值显存带宽。Z100L 与 MI50 可按 gfx906/Vega20 代际和相近资源规模理解，因此 MI50 的 wave64 移植经验有参考价值。

这不是“MI50 换皮”结论。Z100L 有不同的设备 ID、DTK、驱动与固件组合，并有不同的虚拟化和复位边界；相同 ISA 目标不证明板卡、固件或运行时行为相同。

### 2.1 官方标称规格对照

下表只比较架构与显存，不混排不同精度、稀疏与否或是否使用 Tensor Core 的 TFLOPS。Z100L 的 777GB/s 是本机 Read 微基准，其他数值是厂商标称峰值，两种口径不能直接相除。

| 显卡 | 架构/代际 | 显存容量与类型 | 官方标称峰值显存带宽 | 一手来源 |
| --- | --- | ---: | ---: | --- |
| 海光 Z100L | gfx906，Vega20 代际 | 32GB HBM2 | 未获得可核验的公开一手标称 | 本机识别；不以 MI50 标称代替 |
| AMD Instinct MI50 | Vega20 | 32GB HBM2 | 1TB/s | [AMD 官方规格](https://www.amd.com/en/support/downloads/drivers.html/accelerators/instinct/instinct-mi-series/instinct-mi50-32gb.html) |
| NVIDIA Tesla V100 | Volta | 32GB HBM2 | 900GB/s | [NVIDIA V100 PCIe Product Brief](https://images.nvidia.com/content/tesla/pdf/Tesla-V100-PCIe-Product-Brief.pdf)；[A100 架构文表 3](https://developer.nvidia.com/blog/nvidia-ampere-architecture-in-depth/) 亦列出 V100 32GB/900GB/s |
| NVIDIA A100（40GB SXM4） | Ampere | 40GB HBM2 | 1555GB/s | [NVIDIA Ampere Architecture In-Depth](https://developer.nvidia.com/blog/nvidia-ampere-architecture-in-depth/) |
| NVIDIA GeForce RTX 3090 | Ampere | 24GB GDDR6X | 936GB/s | [NVIDIA GA102 白皮书](https://www.nvidia.com/content/PDF/nvidia-ampere-ga-102-gpu-architecture-whitepaper-v2.1.pdf)；[Blackwell 白皮书对照表](https://images.nvidia.com/aem-dam/Solutions/geforce/blackwell/nvidia-rtx-blackwell-gpu-architecture.pdf) |
| NVIDIA GeForce RTX 4090 | Ada Lovelace | 24GB GDDR6X | 1008GB/s | [NVIDIA Ada 白皮书](https://images.nvidia.com/aem-dam/Solutions/geforce/ada/nvidia-ada-gpu-architecture.pdf)；[Blackwell 白皮书对照表](https://images.nvidia.com/aem-dam/Solutions/geforce/blackwell/nvidia-rtx-blackwell-gpu-architecture.pdf) |
| NVIDIA GeForce RTX 5090 | Blackwell | 32GB GDDR7 | 1792GB/s | [NVIDIA Blackwell 白皮书](https://images.nvidia.com/aem-dam/Solutions/geforce/blackwell/nvidia-rtx-blackwell-gpu-architecture.pdf)；[RTX 5090 官方页](https://www.nvidia.com/en-us/geforce/graphics-cards/50-series/rtx-5090/) |

没有在本机对 V100、A100、3090、4090 或 5090 做同模型、同量化、同负载测试。不得据此表或厂商展示结果推导确定的 LLM 加速倍率。

### 2.2 gfx906 对推理路径的影响

- gfx906 使用 wave64；不能直接照搬 NVIDIA warp32、sm_80 Tensor Core、MMA、`cp.async` 等路径。
- 本次 Strata 路径没有可用的 MFMA/WMMA Tensor Core 路线，QSA prompt attention 使用 FP32 fallback；这不表示 dense prefill 的所有 GEMM 都是 FP32。
- 硬件存在 `v_dot4_i32_i8` 等整型点积能力，但具体专家 kernel 是否获益必须按量化格式、形状和完整模型 A/B 验证。
- 显存容量只决定驻留预算的一部分。专家 cache、KV、MTP、激活和运行时缓冲需要共同记账。

## 3. 本机带宽实测

| 项目 | 实测结果 | 口径 |
| --- | ---: | --- |
| 显存 Read | 777GB/s | 本机显存读取微基准，不是厂商峰值，也不是完整模型吞吐 |
| pinned PCIe H2D | 25.7GB/s | 锁页主机内存到设备 |
| pinned PCIe D2H | 28.5GB/s | 设备到锁页主机内存 |
| CPU triad | 83.6GB/s | 主机内存 triad；约为当前 136.5GB/s 估算上限的 61% |

这些数字用于判断混合专家推理的瓶颈，不构成跨卡排名。H2D/D2H 是方向性拷贝带宽，不能与显存 Read 或 CPU triad 相加为“总带宽”。

## 4. 模型与单卡混合执行拓扑

本仓库针对的模型为 [SC117/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-GGUF](https://huggingface.co/SC117/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-GGUF) 的 IQ3_S 版本：

| 项目 | 值 |
| --- | --- |
| 模型族 | Qwen3.8-Flash-Next，125B MoE；不是 DeepSeek |
| 原生层数 | 48 层 |
| 专家拓扑 | 每层 512 experts，共 24576 个专家位置 |
| 专家权重 | 约 46.84GiB，仅是专家部分，不是整个 GGUF 大小 |
| KV | int8 |
| GPU/CPU 分工 | GPU 执行完整 48 层及驻留专家，GPU miss 的 decode 专家由 CPU expert pool 处理 |
| CPU 指令路径 | AVX2，不假定 AVX-512 |
| native pack | 必须从同一模型、同一量化格式的 GGUF 构建，并与运行时 GGUF 分片配套 |

Strata 使用 llama.cpp 项目的 ggml 静态 CPU 库执行相关 IQ 量化 CPU 专家点积；引擎本身不是 llama.cpp 的简单封装。模型文件、native pack 和 MTP 资产不包含在 Git 仓库中。

**模型治理提醒：** 所选权重是 abliterated / refusal-removed 版本，可能削弱原有拒答行为。使用者需要自行确认许可、内容审核、访问控制和适用场景；公开包默认仅用于本地文本推理，不提供面向公网的安全治理。

## 5. 性能结果与统计边界

### 5.1 固定 greedy CLI

| 指标 | 官方默认运行方式 + 必要 DTK 补丁 | 调优结果 | 变化 |
| --- | ---: | ---: | ---: |
| decode | 41.860 tok/s | 51.780 tok/s | +23.70% |
| prefill | 336.275 tok/s | 359.495 tok/s | +6.9% |

最终组合设置为：

```text
STRATA_ARENA_MMAP=0
STRATA_SH_STREAM=0
```

“官方默认运行方式”只指上游默认参数，两组都包含必要的 DTK 兼容补丁。模型量化、KV int8 和采样默认值均未改变；固定 greedy 用于可复现对照与 token IDs 核验。

decode 数字来自组合实验的有效样本中位数。组合矩阵计划 24 次，实际完成 16 次，四种配置各 4 个有效样本；不能称为完整 24 轮。359.495 tok/s 的 prefill 来自 pinned 单独 A/B，组合实验主要报告 decode，不能将 prefill 数字误写成组合开关的同轮测量。

51.780 tok/s 是该 CLI 场景的 decode 中位数，**不是整机稳定聚合吞吐**。

### 5.2 服务侧复核

| 指标 | 默认运行方式 | pinned + SH_STREAM=0 | 变化 |
| --- | ---: | ---: | ---: |
| hot_c4 完整请求墙钟 | 38.54 tok/s | 44.11 tok/s | +14.5% |
| batch 工作窗口输出 | 51.25 tok/s | 57.28 tok/s | +11.8% |

- hot_c4 立即复用 prompt，是缓存命中场景，不能代表普通用户的 TTFT、吞吐或 SLA。
- batch 工作窗口以引擎日志输出 token 和 run/commit/emit/adapt 等时间计算，不是完成请求 QPS，也不是端到端墙钟。
- 单请求上游速度、阶段区间并集、batch 工作窗口与完整请求墙钟必须分开，不能相互替换或简单相加。
- MTP 接受率不是加速倍率；草稿、验证、调度与共享 batch 成本仍需计入最终速度和墙钟。

### 5.3 调优机制与未采用项

匿名 pinned arena 在首次触页前注册，并请求透明大页，减少专家换入时的页注册、TLB 与复制等待。典型 adaptive tier 等待约从 2.565ms/round 降至 0.290ms/round，CPU expert pool 约从 35.6GB/s 提高到 41.4GB/s。关闭 shared-expert cross-stream fork 后形成最终组合。

`STRATA_ADAPT_OVERLAP` 没有上线：候选路径在自然负载中未形成稳定真实触发和可重复收益。CLI 结果不能单独证明 serve overlap 有效，也不能把 pinned 的收益记到 overlap 名下。长期满缓存、满上下文和长期锁页驻留仍需按实际部署继续观察。

## 6. 兼容性、虚拟化与公开包边界

必要 DTK 兼容处理包括：

- 对大于 256 线程的 launch，调整 gfx906 HIP 编译的默认线程上限；不能把所有共享内存 kernel 的历史故障简单概括为硬件只支持 256 线程。
- `SharedMemPerBlockOptin` 查询报错时回退到普通 `MaxSharedMemoryPerBlock`，同时处理错误码和非正值。
- 仅对已定位崩溃的 `hipGraphUpload` 做防护性 no-op，不据此宣称全部 HIP Graph 被关闭或全部可用。
- gfx906 使用 pinned staging 防护 pageable mmap 源的直接 H2D 路径；这与匿名 pinned arena 调优是不同层次的处理。
- native pack、GGUF 分片、量化格式和配套元数据必须一致，不能跨模型或跨量化复用。

**PCI Reset 禁忌：** 不把 PCI/VFIO reset 或 `hy-smi --dcureset` 当作常规恢复手段，已有经验表明其可能导致需要断电恢复的严重状态。公开仓库不包含 reset 或 PCI fixup 工具，不自动处理宿主驱动、固件、BMC 或虚拟化配置。

公开包不包含 API 网关、VPS、BMC 配置、密钥、真实会话、生产日志或模型权重。本文中的性能数字不包含任何真实用户提示词或会话内容。

## 7. 生态与上游资料

- [Strata 上游仓库](https://github.com/Niko1221/Strata)
- [Strata AMD HIP / gfx906 构建说明](https://github.com/Niko1221/Strata/blob/7ddc17a38fe7f31637e895ecfba58c2cd43d65ec/docs/AMD_HIP.md)：gfx906 为 opt-in 源码构建、社区测试路径，不等于 Z100L/DTK 原生认证。
- [海光社区：vLLM 0.11.0 与 Z100L 适配问答](https://forum.sourcefind.cn/thread/f18533d8-e3ae-11f0-b9e4-0242ac150003)：反映对应时间点和镜像的支持结论。
- [海光社区：Z100L vLLM Docker 镜像问答](https://forum.sourcefind.cn/thread/0ecaa292-8981-11f1-98ec-0242ac150003)：官方账号在该帖建议使用 Ollama；不能扩写成永久或全面不支持承诺。
- [海光开发者资源入口](https://developer.sourcefind.cn/document)：驱动、DTK 与部署资料应按具体版本复核。
