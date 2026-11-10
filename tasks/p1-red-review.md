# P1-RED-REVIEW：先验契约测试独立审查

## 目标与交付
作为独立 Reviewer (`codex`)，审查 `p1-red-tests` 产出的 3 个先验测试文件是否完整、准确地覆盖了 `docs/TECHNICAL_SPEC_DEEPSEEK_QWEN.md` §7.2 中的 `T-01` ~ `T-12`，并确认没有任何业务代码被提前修改。在本轮目录生成 `REVIEW.md` 与结构化 `REVIEW.json`。

## 审查核对清单
1. `git status --short` 确认未修改 `artemis/`、`third_party/`、`config/artemis.jsonc`；
2. 核对 `T-01`~`T-12` 是否包含：未知预设 Fail-Fast (`T-01`)、扁平 `presets` 兼容 (`T-02`)、跨厂商 Provider 继承泄漏拦截 (`T-03`)、阶段二零 Google 不变量 (`T-04`)、百炼 `DASHSCOPE_API_KEY` 兼容 (`T-05`)、`stream_usage=True` & `max_retries=0` (`T-06`)、`is_multimodal=False` 启动拦截 (`T-07`)、`with_structured_output` 默认 `function_calling` (`T-08`)、HTTP 402 立即降级与 `prompt_cache_hit_tokens` (`T-09`)、五种 `coord_format` 归一化 (`T-10`)、退化框过滤 (`T-11`)、Detector `with_fallback` 闭环 (`T-12`)；
3. 核对所有测试是否清理了 `ModelFactory._cache` 并通过 `monkeypatch` 隔离了真实 `.env`。
