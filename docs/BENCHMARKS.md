# 性能复现与口径

## 已测对照（Z100L 单卡）

环境：Z100L gfx906 32GB、EPYC 7F52、256GB DDR4、DTK-26.10，Qwen3.8-Flash-Next IQ3_S、KV int8、MTP。对照组包含必需的 DTK 兼容补丁，但不启用本轮内存与 shared-expert 调优；它不表示 Strata 官方原生支持 Z100L。

| 测量边界 | 默认运行方式 | 调优后 | 变化 |
| --- | ---: | ---: | ---: |
| 固定 greedy CLI decode | 41.860 tok/s | 51.780 tok/s | +23.70% |
| 固定 greedy CLI prefill（pinned 单独 A/B） | 336.275 tok/s | 359.495 tok/s | +6.9% |
| 真实 hot_c4 完整请求墙钟 | 38.54 tok/s | 44.11 tok/s | +14.5% |
| batch 工作窗口 | 51.25 tok/s | 57.28 tok/s | +11.8% |

CLI 的默认与组合调优各有 4 次有效样本；真实 serve 使用相同模型、采样与请求矩阵做正反向对照。组合实验主要报告 decode，不能把 pinned 单独 A/B 的 prefill 冒充完整组合的同轮结果。`hot_c4` 有高缓存复用，不是普通用户的 SLA，也不是独占 GPU 的 kernel benchmark。

调优项为 `STRATA_ARENA_MMAP=0` 与 `STRATA_SH_STREAM=0`。未更换模型量化、KV 精度或采样默认值；未将未证明稳定收益的 overlap 补丁纳入默认路径。

## 新部署复测

先停止其他推理负载，避免共享 GPU、CPU 和内存带宽。分别构建默认配置与 `z100l-32g-tuned` 配置；不能在同一容器里同时测两种配置。

```bash
# 合成输入每次有唯一 ID，减少整段缓存复用。
# 输出只保存 token 计数和上游耗时，不保存提示词/回答正文。
python3 scripts/bench.py --tag default --repetitions 4 --max-tokens 64
python3 scripts/bench.py --tag tuned --repetitions 4 --max-tokens 64
```

`bench.py` 的上游字段是 `prompt_per_second` 与 `predicted_per_second`，分别表示单个请求的 prefill 和 decode 速度。它输出的平均值明确标为 `mean_single_request_*`，不是整机聚合吞吐；`wall_s` 另存，不能拿来冒充 decode 时间。

需要比较缓存影响时，固定一份公开合成文本，通过 `--prompt-file` 分别测试首次与重复请求。不要把唯一 ID 的 cold 请求与完全复用的 hot 请求放在同一平均数中。

长上下文需单独测试输入长度、并发、会话切换与 L2/L3 恢复。这里的 262K 是容量工作点，不是“所有请求都以同一速度运行”的承诺。当前发布未声称多卡、其他型号 GPU 或其他 DTK 版本已经实测。
