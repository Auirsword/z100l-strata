# 在海光 Z100L 上跑 125B MoE：Strata 移植、23.70% decode 调优与一键部署

## 0. 先给结果：同一张卡，默认配置与调优后差多少

| 固定 greedy CLI 指标 | Strata 官方默认运行方式 | 调优结果 | 变化 |
| --- | ---: | ---: | ---: |
| decode | 41.860 tok/s | 51.780 tok/s | +23.70% |
| prefill | 336.275 tok/s | 359.495 tok/s（pinned 单独 A/B） | +6.9% |

测试平台是单卡海光 DCU Z100L，gfx906、32GB 显存；CPU 为 EPYC 7F52 16 核 32 线程，配 256GB DDR4，软件栈为 DTK-26.10。模型是 SC117/Qwen3.8-Flash-Next-GSQ-RCO-abliterated 的 IQ3_S 版本，125B MoE，原生 48 层，不是 DeepSeek。

先澄清“官方默认”：它指上游 Strata 的默认运行参数，**不等于 Strata 原生支持 Z100L**。baseline 与调优组都包含同一套必要的 DTK 兼容补丁，否则连正确构建、运行都谈不上。两组使用同卡、同模型，不改变 IQ3_S 量化、KV int8 或采样默认值。固定 greedy 只是为了让输出 token IDs 可核对、测速可复现。

这张表还有一个容易忽略的口径：decode 的主要结果来自组合实验，最终两项设置为 `STRATA_ARENA_MMAP=0` 和 `STRATA_SH_STREAM=0`；**359.495 tok/s 的 prefill 来自 pinned 单独 A/B**，不是组合实验的同轮结果。组合实验主要报告 decode，因此不能把这两个百分比包装成一次实验里所有指标都同步提升。

真实服务路径也做了对照，但采用另外的统计边界：

| 服务侧指标 | 默认运行方式 | pinned + SH_STREAM=0 | 变化 |
| --- | ---: | ---: | ---: |
| hot_c4 真实完整请求墙钟 | 38.54 tok/s | 44.11 tok/s | +14.5% |
| batch 工作窗口输出 | 51.25 tok/s | 57.28 tok/s | +11.8% |

hot_c4 的 prompt 被立即复用，反映缓存命中后的上界，**不代表普通用户的 SLA**；batch 工作窗口只计算引擎 run/commit/emit/adapt 等工作区间，也不是完整请求吞吐。51.780 tok/s 则是固定 greedy CLI 的 decode 中位数，不是整机稳定聚合吞吐，更不能乘上并发数对外报价。

这轮优化没有更换模型，也没有靠放松采样或改量化“换速度”。本机带宽背景是：显存 Read 实测 777GB/s，pinned PCIe H2D/D2H 分别为 25.7/28.5GB/s，CPU triad 为 83.6GB/s。最终有效的不是一颗神秘 GPU kernel，而是减少主机内存注册、缺页与专家换入路径上的等待，再关闭 shared-expert cross-stream fork。下面从这张卡本身讲起。

实验方法也决定了这些数字能不能信。完整模型采用正向、反向交错的 A/B，尽量让温度、缓存和后台状态对两组产生相近影响，报告中位数而不是挑最快的一次。组合矩阵原计划 24 次，实际完成 16 次，四种配置各有 4 个有效样本；我不把它包装成完整 24 轮。候选优化先过组件正确性，再回到完整模型核对固定 greedy 的 token IDs，避免“速度变快其实是因为算错了”。

也不是每次尝试都有收益。QSA query swizzle 在组件级有提升，回到完整模型 decode 只有约 0.26%；某些 down 专家路径甚至明显变慢，因此没有进入最终配置。保留这些负结果很重要：微基准的赢家不一定是系统赢家，最终两项设置是靠完整模型和服务侧复核选出的，而不是靠堆叠所有看似先进的开关。

## 1. Z100L 是什么：与 MI50 同源，但不是“MI50 换皮”

Z100L 在海光产品体系里叫 DCU。对开发者最实用的识别信息不是营销代号，而是 `gfx906`：它决定了指令集目标、wave64 执行方式、可用的数学指令以及上游框架需要选择哪套 kernel。本次机器识别到 60 CU、32GB HBM2，PCI 设备 ID 为 `1d94:55b7`，设备类别显示为 Display controller。

这也解释了它与 AMD Instinct MI50 的渊源。AMD 官方资料把 MI50 32GB 标为 Vega20、60 CU、3840 个 stream processor、32GB HBM2，峰值显存带宽 1TB/s。Z100L 与 MI50 可以放在 gfx906/Vega20 这一代际和相近资源规模下理解，很多 MI50、MI60、Radeon VII 的移植经验因此有参考价值。

但“同代际”不能偷换成“同一块卡”。Z100L 使用海光 DTK、自己的设备 ID、驱动与固件组合，虚拟化和复位语义也有差异。一个在 ROCm + MI50 上成立的运行时行为，不能未经验证就搬到 DTK + Z100L；同理，也不能把 Z100L 简单写成“MI50 换皮”。

### 和 V100、A100、3090、4090、5090 怎么比

先看不含算力单位混淆的硬件坐标。下表只列架构、显存容量、类型和厂商标称峰值带宽，不把 FP16、FP32、Tensor Core 或稀疏算力混在一列：

| 显卡 | 架构/代际 | 显存 | 官方标称峰值显存带宽 |
| --- | --- | ---: | ---: |
| 海光 Z100L | gfx906，Vega20 代际 | 32GB HBM2 | 未获得可核验的公开一手标称；本机 Read 实测 777GB/s |
| [AMD MI50 32GB](https://www.amd.com/en/support/downloads/drivers.html/accelerators/instinct/instinct-mi-series/instinct-mi50-32gb.html) | Vega20 | 32GB HBM2 | 1TB/s |
| [NVIDIA V100 32GB](https://images.nvidia.com/content/tesla/pdf/Tesla-V100-PCIe-Product-Brief.pdf) | Volta | 32GB HBM2 | 900GB/s |
| [NVIDIA A100 40GB](https://developer.nvidia.com/blog/nvidia-ampere-architecture-in-depth/) | Ampere，SXM4 | 40GB HBM2 | 1555GB/s |
| [NVIDIA RTX 3090](https://www.nvidia.com/content/PDF/nvidia-ampere-ga-102-gpu-architecture-whitepaper-v2.1.pdf) | Ampere | 24GB GDDR6X | 936GB/s |
| [NVIDIA RTX 4090](https://images.nvidia.com/aem-dam/Solutions/geforce/ada/nvidia-ada-gpu-architecture.pdf) | Ada Lovelace | 24GB GDDR6X | 1008GB/s |
| [NVIDIA RTX 5090](https://images.nvidia.com/aem-dam/Solutions/geforce/blackwell/nvidia-rtx-blackwell-gpu-architecture.pdf) | Blackwell | 32GB GDDR7 | 1792GB/s |

我只在 Z100L 上做了这组实验，没有把 V100、A100 或三代 GeForce 放在同一台机器上复测，所以这张表不是 LLM 速度排行榜。尤其不能用厂商展示的不同模型、不同量化速度，换算成“Z100L 相当于某卡的几分之几”。

即使只读这张表，也要区分三个问题。第一是容量：24GB 的 3090/4090 与 32GB 的 Z100L/5090 留给专家、KV 和运行时的预算不同，但同为 32GB 不代表 kernel 能力等价。第二是带宽：A100 40GB 的标称带宽很高，不代表任何 MoE offload 负载都会按比例提速。第三是主机路径：权重不能全部驻留时，CPU 核数、内存和 PCIe 可能盖过 GPU 账面差异。MI50 的 1TB/s 是官方峰值，本机 Z100L 的 777GB/s 是 Read 微基准，二者也不能直接相除得出效率。

架构差异也不只是带宽数字。gfx906 没有 V100 之后的 NVIDIA Tensor Core 路线，也没有可直接照搬的 MFMA/WMMA 路径；它有 wave64 和硬件 `v_dot4_i32_i8` 等自己的能力。V100、A100、3090、4090、5090 分属不同 NVIDIA 代际，矩阵加速单元、精度支持和软件路径都在变化。把 sm_80 的 kernel 参数直接复制给 gfx906，通常不是优化，而是制造新的 bug。

那为什么一张 32GB 卡能跑 125B MoE？答案不是把完整模型硬塞入显存，而是 Strata 的混合执行。所用 Qwen3.8-Flash-Next 是原生 48 层、每层 512 experts 的 MoE，GPU 保存 dense 部分、部分专家与 KV，未驻留的 decode 专家由 CPU expert pool 和主机内存承接，必要时再经 PCIe 换入。于是显存带宽之外，EPYC 的内存带宽、TLB、页注册和 PCIe 都进入关键路径。这也是后面两项设置能带来明显收益的原因。

## 2. 海光生态的独特性：相似 API 不等于相同运行时

海光软件栈里常见 DTK、DAS、DCU、HCU 等名字。可以粗略把 DTK 理解为编译器、HIP 运行时、数学库与管理工具组成的开发套件，把 DAS 理解为面向 AI 框架的适配发行集合。HIP 和 CUDA 风格的接口降低了移植门槛，上游项目也往往已有一些兼容层，但 **DTK 不是“ROCm 换个名字”**。

这次实际遇到的差异足够具体：`SharedMemPerBlockOptin` 查询会直接返回 invalid argument；未显式声明 launch bounds 的 kernel 默认被限制为 256 线程；`hipGraphUpload` 会在厂商运行库内部段错误。它们不是改一个 `ROCm` 字符串就会消失的问题，必须逐项探针、回退和正确性验证。驱动、VBIOS、DTK 与容器内库也要作为一套版本组合看待。

模型支持节奏同样具有生态特征。海光官方社区存在 Z100L 定制镜像与部署资料，但新框架、新模型的覆盖可能滞后。比如，在 [vLLM 0.11.0 适配咨询](https://forum.sourcefind.cn/thread/f18533d8-e3ae-11f0-b9e4-0242ac150003) 中，官方账号先指出发布文案有误，后续给出的结论是“目前不支持”；在另一个 [Z100L vLLM Docker 镜像咨询](https://forum.sourcefind.cn/thread/0ecaa292-8981-11f1-98ec-0242ac150003) 中，官方账号建议改用 Ollama。

这些帖子能证明相应时间点、对应镜像和模型路径的限制，不能被扩写成“海光完全不支持 Z100L”，更不是厂商对未来路线的永久承诺。社区教程、个人打包环境和官方账号答复也要分开引用：前两者可以提供可复现线索，不能替代正式支持矩阵。

有利的一面是，通用开源生态并非从零开始。[Strata 的 AMD HIP 文档](https://github.com/Niko1221/Strata/blob/7ddc17a38fe7f31637e895ecfba58c2cd43d65ec/docs/AMD_HIP.md) 已有 gfx906 的 opt-in 源码构建路径，并把它标为社区测试；相关实现通过 HIP 兼容层和 wave64 kernel 覆盖 MI50/MI60/Radeon VII。我们要做的是在这条路径上补 Z100L/DTK 的差异，而不是宣称上游已经原生认证了海光 Z100L。

这种环境尤其不适合每天追着上游 main 分支重新构建。公开仓库因此固定 Strata 与 ggml 的源码版本，并把补丁作为可审阅的独立资产；宿主驱动/DTK、上游引擎、Z100L 适配层是三件不同的事。复现问题时先记录这三层版本，再讨论模型和参数，能避免把上游变化、运行时差异与自己的修改混在一个“不能跑”的结论里。

所以，这个生态的真实体验是：硬件有可挖掘的能力，通用接口也能复用大量工作，但“能编译”只是起点。设备语义、数值正确性、模型格式和长期运行都要自己建立证据。对愿意读日志、写探针的人来说，这恰恰是国产老卡仍有可玩性的地方。

## 3. 踩坑记录：从“跑起来”到“数字可信”

### 3.1 大于 256 线程，不只是一个警告

Strata 的一些 sampler、归约 kernel 会以 512 或 1024 线程启动，DTK 则对没有 `__launch_bounds__` 的 kernel 使用 256 线程默认上限，直接拒绝更大的 launch。 gfx906 硬件本身支持更大的 block，因此在 gfx906 HIP 构建中加入 `--gpu-max-threads-per-block=1024`，而不是盲目把所有 kernel 改成 256。

这里必须保留一条反例纪律：早期 llama.cpp 探针曾在特定的共享内存归约写法上观察到 256 线程以上的 LDS 混叠；Strata 的独立探针用全块 LDS 树归约却没有复现。不能把某一 kernel 的故障概括成“整卡只能 256 线程”，也不能因新探针通过就跳过最终 parity 测试。

### 3.2 属性查询失败，不能当成属性值为零

上游回退原本只处理 `SharedMemPerBlockOptin` 查询成功但值不大于零的情况。DTK-26.10 是直接报错，若调用方忽略错误码，后续就会得到 `max_shared=0`，甚至把只需 160B shared memory 的 kernel 误判为超限。修复方式是在“查询失败或值非正”两种情况下，都回退到 `MaxSharedMemoryPerBlock`。这是运行时语义差异，不是显存不足。

### 3.3 HIP Graph 不能一刀切

本次崩溃定位在 `hipGraphUpload`，因此兼容层只把这个预上传优化改成返回成功的 no-op，让首次 launch 惰性处理。capture、instantiate、launch 并没有整体关闭。另一方面，llama.cpp 的 `hipGraphExecUpdate` 问题曾需要关闭其 graph 功能。两个项目、两个 API 的故障不能混成一句“DTK 不支持 HIP Graph”；正确做法是只屏蔽已证实危险的调用，并用输出验证其余路径。

### 3.4 pageable 源拷贝与 pinned staging

gfx906 构建曾落入直接从 pageable mmap GGUF 做 H2D 拷贝的分支，而上游其他 HIP 路径已经有 pinned staging。把 gfx906 纳入同一保护条件后，避免把页可换出的源缓冲直接交给这条拷贝路径。这里的 staging 是兼容与可靠性修复；后文的匿名 pinned arena 则是另一层内存模式调优，两者不能混为一谈。

### 3.5 Strata 不是 llama.cpp 套壳

Strata 是自研 C++/CUDA 引擎。它使用 llama.cpp 项目中的 ggml 静态 CPU 库，主要承担 IQ 量化格式的 CPU 专家 dot product；这并不意味着整个推理由 llama.cpp HIP 后端执行。区分这一点很重要：llama.cpp 的 graph 开关、kernel 故障和 benchmark 不能直接当作 Strata 的同名问题，CPU 基线与量化校验工具却可以复用。

### 3.6 native pack 必须和具体量化 GGUF 配套

native pack 不是与模型名字相同就能通用的缓存。它要从具体模型、具体量化格式的 GGUF 构建，并与运行时的 GGUF 分片、PLE 表、tokenizer、MTP 和 expert profile 对应。IQ3_S 的 pack 不能拿去配 Q2_0 权重，不同模型或重新打包的分片也不能凭文件名碰运气。更换任一权重来源后，应重新构建并做校验，而不是复用旧产物追一个启动速度。

### 3.7 MTP 接受率不是整机加速倍率

MTP 一次提出多个候选 token，接受率高通常有利，但生成草稿、验证、调度和未接受候选都有成本。batch 场景下，单流收益还可能被共享资源抵消。因此“接受率 80%”不等于“整机快五倍”，加深投机窗口也不一定更快。必须看最终 decode、完整请求墙钟和 batch 工作窗口，而不是只看接受率。

一次异常慢运行很能说明问题：当时 MTP tokens/round、接受率和 CPU pool 都正常，adaptive tier 却从相邻正常运行的约 2.635ms/round 变成 15.132ms/round。把每轮差值乘上 verify round，约 574.9ms，几乎覆盖实际 decode 增加的 566.8ms。若只看“这次开了哪个开关”，很容易误判；把等待、复制、专家池和 GPU 时间拆开，才发现主要慢在 adaptive tier，而不是 MTP 或 GPU kernel。

### 3.8 pinned 与 SH_STREAM 有效，overlap 却没有上线

文件映射 arena 在换入时涉及动态 pin/register、H2D 和提交；匿名 pinned arena 在首次触页前注册，并请求透明大页，减少约 3MB 专家在 4KB 页下的 TLB 与换入开销。典型 adaptive tier 等待从约 2.565ms/round 降到 0.290ms/round，CPU expert pool 从约 35.6GB/s 提高到 41.4GB/s。再关闭 shared-expert cross-stream fork，形成最终的 pinned + `STRATA_SH_STREAM=0` 组合。

相反，`STRATA_ADAPT_OVERLAP` 不能凭环境变量就宣称复制已经重叠。原实现的 solo 与 batch 路径不同，候选 batch 补丁在自然负载中真实 flip 很少，hot 与 batch 指标也没有稳定收益，所以 **overlap 没有上线**。固定 greedy CLI 的输出 token IDs 一致，也不等于所有 serve 采样、并发和长期内存场景都已得到同一保证。

### 3.9 吞吐口径与 Reset 禁忌，都是硬边界

单请求上游速度、阶段区间并集、batch 工作窗口、完整请求墙钟是四个不同指标。并发统计尤其不能把相对请求的 TTFT 与其他请求的绝对完成时间混用，否则会缩短分母，制造比单流还漂亮的假聚合。hot、cold、排队、prefill 和 decode 也必须分别报告。

最后是硬件安全：不要把 PCI Reset、VFIO reset 或 `hy-smi --dcureset` 当作普通排障按钮。已有 Z100L 经验表明，这类操作可能触发需要断电恢复的严重状态。公开仓库**不带 reset 或 PCI fixup 工具**，部署脚本也不会替用户尝试复位、刷固件或改虚拟化配置；相关宿主问题应按海光对应版本的官方流程单独处理。

### 3.10 容器里的“没有 GPU”，可能只是 Unix socket 被拒绝

公开包的独立验收还遇到过一个很有迷惑性的故障：宿主与 HIP 探针能识别显卡，Strata 却报 `no ROCm-capable device is detected`。对照容器启动参数后，关闭 seccomp 没有作用，单独关闭 AppArmor 才恢复设备枚举；内核审计最终指向 `socket(AF_UNIX, SOCK_STREAM, 0)` 被拒绝。

在这台 PVE 9 主机上，单纯给规则补 `network unix stream` 仍不够：系统固定的 AppArmor 策略特性集与新内核不匹配。最终办法不是 privileged，也不是关闭全局防护，而是给这个推理容器一个独立 profile，按 `/sys/kernel/security/apparmor/features` 的当前内核特性编译，并保留 seccomp、去掉 capabilities 和只读根文件系统。这个小坑再次说明，容器、运行时和驱动要作为一整条初始化链排查。

## 4. 一键部署：公开 Auirsword/z100l-strata

移植和调优结果整理在公开仓库：[https://github.com/Auirsword/z100l-strata](https://github.com/Auirsword/z100l-strata)。目标不是复制我的整台服务器，而是提供可审阅的 DTK 补丁、固定版本构建、模型准备和本地启动入口。前置条件是 x86_64 Linux、已经正常工作的 DCU 驱动与 DTK、Docker、Git、curl 和 Python 3。确认宿主能使用 GPU 后，部署入口如下：

```bash
git clone https://github.com/Auirsword/z100l-strata.git
cd z100l-strata
./install.sh --download-model
```

这条命令依次生成保守配置、获取固定版本源码并应用补丁、构建容器、下载并校验模型、生成 native pack，最后启动本地服务。默认先用 32K context、单会话的保守预设，避免一上来就按高配工作点锁占大量内存。已有完整模型时改用 `./install.sh --model-dir /absolute/path/to/model`；只想验证源码与容器构建时可用 `./install.sh --build-only`。

下载体量不能低估：两片 GGUF 约 83.86GB，MTP 文件约 0.824GB，生成的 native pack 约 49GB，还要给断点续传和构建留出工作空间。权重、pack 等产物不进入 Git。下载器核对固定 revision、文件尺寸和 SHA-256，已验证文件会跳过，损坏文件不会被静默当成成功。构建与运行版本以仓库锁定值为准，不要中途混用另一套 ROCm、另一份 llama.cpp 或别的量化 GGUF。

服务起来后，用公开合成请求做健康检查，而不是拿真实会话试机：

```bash
python3 scripts/smoke.py --wait 900
python3 scripts/smoke.py --generate
```

默认入口是 `http://127.0.0.1:18080`，API 本身不带鉴权，不要直接暴露到不受信任网络。若要复现文章的高配工作点，再按 README 选择 `z100l-32g-tuned`：它启用 262K context、batch 4、pinned arena 与 `STRATA_SH_STREAM=0`，要求至少 224GiB 总内存、160GiB 当前可用内存和 340GiB 数据盘余量。低配机器不要强选，高配预设也不代表多个满 262K 会话已经验证。硬件坐标与完整官方规格链接另见 [HARDWARE.md](https://github.com/Auirsword/z100l-strata/blob/main/docs/HARDWARE.md)。

模型来自 [SC117/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-GGUF](https://huggingface.co/SC117/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-GGUF)，采用 IQ3_S。请特别注意：**abliterated / refusal-removed 表示削弱或移除了部分拒答行为，不等于更安全，也不等于无需治理。** 使用者需要自行确认模型许可与适用法规，并补充内容审核、访问控制、日志策略和人工复核；不要把本地可运行误当成可直接对公众开放。

公开包默认只提供本地文本推理，不包含 API 网关、VPS、BMC 配置、密钥、真实会话、生产日志或模型权重，也不会发布这些私有资产。它不是多租户服务平台，更没有因为一次 hot_c4 测试就附带吞吐 SLA。

如果说这次移植最大的收获是什么，我会选“证据链”而不是 51.780 这一个数字：基线也打兼容补丁，优化前后保持模型与采样边界，固定输入核对 token IDs，组件收益必须回到完整模型验证，hot 与 cold 分开，未上线的 overlap 明确写成未上线。国产 GPU 的部署当然需要 kernel，但同样需要对驱动语义、主机内存和测量方法保持耐心。仓库已经公开，欢迎复现，也欢迎用同样严格的 A/B 来推翻或改进这组结果。
