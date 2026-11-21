# ARTEMIS 架构决策记录 (Architecture Decision Records, ADR)

> **项目**：ARTEMIS (Autonomous AI Assistant for Mobile Automation)  
> **版本**：1.1.0（经 Opus 独立架构审查修订并由用户确认）  
> **状态**：已批准，待按 Spec v1.1 实施 (Approved, Pending Spec v1.1 Implementation)  
> **记录人**：Antigravity Agent & 独立架构审查 Agent  

---

## ADR-001：多供应商中立架构、Gemini 基线 100% 保全与分阶段解耦

### 上下文与问题陈述
ARTEMIS 原生深度依赖 Google GenAI / Gemini 专有能力（包括 `ChatGoogleGenerativeAI` 工具调用 Patch、`gemini-robotics-er` 空间定位模型、GenAI Files API 视频上传，以及分布在 `chunking.py`、`summarizer.py`、`llm.py` 中的硬编码 `get_google_llm` 调用）。如果直接移除 Google 相关代码或在一阶段强行切断跨厂商备用链路，既会丧失 Golden Baseline 对照能力，也会在主模型（DeepSeek / Qwen）发生单厂商故障或配额耗尽时失去跨厂商逃生通道。

### 决策内容
1. **保留 Google 完整基线通路**：
   - 现有的 Google Provider 及其专有调用逻辑（`artemis/llm/google/provider.py`、`native_coordinator.py` 等）保持 100% 完整可用。
   - 保留 `gemini-baseline` 预设，作为任何评测与回归的权威金标（Golden Baseline）。
2. **分阶段解耦与 Fallback 策略（用户已确认）**：
   - **阶段一（跨厂商高可用平替）**：主模型全量切至 `DeepSeek Flash v4 1017` + 阿里云百炼 `Qwen-VL`，**允许 `fallback` 跨厂商指向 `google/gemini-3.8-flash`（及 `gemini-robotics-er-2-preview`）**，消除同厂商单点相关性故障（如主备共用同一 API Key / 同一账户余额 402 / 同区域 5xx）。
   - **阶段二（零 Google 独立验收）**：拔除所有硬编码 `get_google_llm` 后门（`chunking.py`、`summarizer.py`、`runner.py`、`lightweight_judge_default`），将 fallback 切换为纯非 Google 多模态端点，在清空 `GOOGLE_API_KEY` 的环境下通过“零 Google 运行不变量”独立验收。
3. **抽象中立接入层**：
   - 所有业务节点与后台记忆服务统一走 `ModelFactory`、`ModelEndpoint` 与 `artemis.services.llm.get_llm`（及新增的 `get_llm_for_model`），禁止业务层直接调用厂商 SDK 或硬编码 `get_google_llm`。

### 影响与后果
* **正面**：阶段一具备跨云容灾能力，阶段二可严格验证 100% 去 Google 化；随时可回滚、可对比。
* **负面**：需同时维护两套配置预设与双阶段验收测试。

---

## ADR-002：DeepSeek 与阿里云百炼 Qwen 双通道独立配置与表驱动接入

### 上下文与问题陈述
候选平替组合由两款模型构成：`DeepSeek Flash v4 1017`（多模态主脑）与阿里云百炼平台（DashScope）接入的 `Qwen-VL`（视觉目标检测定位）。二者对外均提供 OpenAI-compatible HTTP 接口（`/v1/chat/completions`），但属于不同云平台、不同认证密钥（`DEEPSEEK_API_KEY` vs `QWEN_API_KEY`）与不同网关地址。同时，`langchain_openai.ChatOpenAI` 在配置自定义 `base_url` 时存在默认关闭 `stream_usage`、默认开启 SDK 内部重试（`max_retries=2`）等隐式行为，会导致 ARTEMIS Token 计量失真与重试风暴。

### 决策内容
1. **双通道物理隔离配置**：
   - 在 `artemis.config.settings.Settings` 中设立独立命名空间：
     - `DEEPSEEK_API_KEY` 与 `DEEPSEEK_BASE_URL`（默认 `https://api.deepseek.com/v1`）
     - `QWEN_API_KEY` 与 `QWEN_BASE_URL`（默认阿里云百炼兼容端点 `https://dashscope.aliyuncs.com/compatible-mode/v1`）
2. **表驱动 OpenAI 兼容实例化**：
   - 在 `ModelProvider` 与 `LLMProvider` 中注册 `deepseek` 与 `qwen`。
   - `ModelFactory` 采用表驱动映射（`_OPENAI_COMPAT_PROVIDERS`），拒绝复制粘贴分支。
   - **强制网关级参数对齐**：对所有 OpenAI 兼容 Provider 显式注入 `stream_usage=True`（保障流式 Token 计量与 Transcript 压缩阈值准确）与 `max_retries=0`（禁用 openai SDK 内部静默重试，统一交由 `artemis.llm.reliability` 管理并上报遥测）。

### 影响与后果
* **正面**：消除代码重复，确保流式 Token 计量、成本核算与熔断重试行为在 Google 与非 Google 通道间完全一致。
* **负面**：部分老旧私有网关若不支持 `stream_options.include_usage` 需通过能力探针自动降级。

---

## ADR-003：向后兼容的 `presets_v2` 冷启动预设切换

### 上下文与问题陈述
审查发现：现有 `config/artemis.jsonc` 中的 `presets` 采用扁平结构 `{provider, model, fallback}`，且已被 `apps/admin_console`（`system.py` / `tasks.py`）直接暴露给前端；而 Python 配置加载层（`artemis/config/llm.py`）此前从未实现预设读取逻辑。此外，`_expand_default_into_nodes` 采用浅层字典覆盖，若节点仅覆盖 `model`（如 `hopper`）而未显式声明 `provider`，在切换默认 Provider 时会发生 **Provider 继承泄漏**（变成 `deepseek/gemini-3.5-flash-lite` 引发 404 且不触发 fallback）。

### 决策内容
1. **新建 `presets_v2` 键，100% 保留旧 `presets` 兼容性（用户已确认）**：
   - 保持顶层 `presets` 原有扁平结构不变，确保 Admin Console 零破坏。
   - 新增顶层 `presets_v2` 与 `active_preset` 字段，承载包含 `{default, nodes, memory_overrides}` 的完整分层预设。
2. **仅支持冷启动切换（Cold-Start Preset Switching）**：
   - 解析优先级：`CLI --preset` > 环境变量 `ARTEMIS_PRESET` > `artemis.jsonc` 中的 `active_preset` > 顶层 `default`/`nodes`。
   - 传入未知的 preset 名称时**立即抛出 `ValueError`（Fail-Fast）**，严禁静默回退到 Gemini。
3. **阻断 Provider 继承泄漏**：
   - 在展开节点配置时，若某节点覆盖了 `model` 但未指定 `provider`，加载器必须通过模型前缀或已知模型归属表校验；而在 `presets_v2.<name>` 内部，所有异构节点（如 `object_detector`、`hopper`）必须显式同时声明 `provider` 与 `model`。

### 影响与后果
* **正面**：完全兼容现有管理后台，彻底根除 `deepseek/gemini-*` 跨厂商错配与静默回退。
* **负面**：配置文件同时存在 `presets`（旧 UI 用）与 `presets_v2`（多模型架构用），需在文档与注释中标明。

---

## ADR-004：统计严谨的 6 维度自动化评测与验收体系

### 上下文与问题陈述
移动端自动化任务受网络抖动、UI 渲染时机与模型采样影响，单次跑批的达成率波动较大；且若由候选预设自身的 Checker 判定任务成败，存在“自己给自己打分”的评测循环偏差。

### 决策内容
建立统计严谨的自动化对比验收体系（`scripts/run_benchmark_comparison.py`），对比 `gemini-baseline` 与 `ds-qwen-hybrid`：
1. **任务端到端达成率 (TSR)**：每个基准任务重复 $N \ge 5$ 次，采用**配对比较**并输出 95% 置信区间；成功判定优先依据**确定性设备断言**（ADB/UI 状态），需 LLM 终审时两边固定使用同一裁判模型。要求 $\text{TSR}_{\text{hybrid}} / \text{TSR}_{\text{gemini}} \ge 98\%$。
2. **交互时延 (Step Latency P50/P90)**：同时记录端到端步时延与 `request_bytes`（排查 Base64 体积影响），波动 $\le 15\%$。
3. **Token 开销与调用成本 (Cost & Consumption)**：修正 `normalize_usage` 采集 `prompt_cache_hit_tokens` 后，按带版本号的价格表核算，预期降本 $70\%\sim 90\%$。
4. **视觉空间定位精度 (Visual Grounding Accuracy)**：增设**离线标注回归集**（免真机 CI 可跑，判定预测点是否落入 GT Bounding Box 内）+ 真机点击命中率，并统计 `ask_explorer` 触发率。
5. **API 可靠性与故障注入恢复率 (Reliability)**：通过本地 OpenAI 兼容 Mock Server 注入 `429`、`402`、`503`、流中断与畸形 JSON，验证故障恢复率 100%。
6. **时序多模态解析一致性 (Video Grounding Consistency)**：对照人工标注真值集，瞬态 Toast/Loading 判定准确率 $\ge 95\%$。

---

## ADR-005：端点能力先验探测与结构化输出协议协商（新增）

### 上下文与问题陈述
`langchain_openai.ChatOpenAI.with_structured_output` 在 `1.5.2` 版本默认使用 `method="json_schema"`（OpenAI Structured Outputs 扩展），而 DeepSeek 与百炼 Qwen 的部分模型端点仅支持 `function_calling` 或 `json_mode`，直接调用会引发 HTTP 400（被归类为 `BAD_REQUEST` 不触发 fallback）。此外，`ModelEndpoint.is_multimodal` 字段此前在代码中从未被读取校验，P-003 原则缺乏运行时强制力。

### 决策内容
1. **配置期 + 探针期能力注册**：
   - 在 `ModelEndpoint` 中增加 `structured_output_method: Literal["json_schema", "function_calling", "json_mode"] | None = None`。
   - 提供 `scripts/probe_capabilities.py` 先验探针脚本，在接入新模型时实测验证：模型 ID 存在性、`image_url` 多模态支持、结构化输出协议、流式 `usage` 返回与坐标格式，结果落盘至 `.artemis/capabilities.json`。
2. **Wrapper 协议自适应**：
   - `RobustChatModelWrapper.with_structured_output` 对非 Google 端点自动读取 `endpoint.structured_output_method`（DeepSeek / Qwen 默认采用兼容性最广的 `function_calling`），业务层（`checker.py`、`planner.py`）无需修改。
3. **强制执行 P-003 模态保护**：
   - 启动校验阶段，凡绑定到多模态节点（`operator`、`planner`、`checker`、`object_detector`、`explorer`、`video_analyzer`、`summarizer`）的主备模型，其 `is_multimodal` 必须为 `True`，否则在冷启动配置校验时直接拒绝启动。
   - `artemis/llm/reliability.py` 将 HTTP `402 Payment Required` 归类为 `QUOTA_OR_BILLING`（`retryable=False, should_fallback=True`），确保单厂商欠费时立即切向跨厂商备用模型。

---

## ADR-006：Object Detector 声明式坐标契约与超时/降级加固（新增）

### 上下文与问题陈述
审查发现现有 `object_detector.py` 存在两处致命缺陷：
1. **坐标格式歧义**：现有代码假设模型必返回 `[y, x]` 并在第 176 行无条件翻转 `x, y`；而 Gemini `box_2d` 为 `[ymin, xmin, ymax, xmax]`（0–1000），百炼 Qwen2.5-VL 默认返回 `[xmin, ymin, xmax, ymax]` **绝对像素坐标**（基于输入图像尺寸或 smart-resize 尺寸），Qwen3-VL / 部分 grounding 模式返回 0–1000 的 `[xmin, ymin, xmax, ymax]`。用无状态启发式猜测会导致 x/y 颠倒或像素未归一化。
2. **超时与 Fallback 失效**：单 label 默认超时 `10.0s` 与 RateLimit 首次退避基准 `10.0s` 相等，导致 429 重试必被外层 `wait_for` 杀死；且内部吞掉所有异常、未包裹 `with_fallback`，导致配置的备用模型永远无法触发。

### 决策内容
1. **声明式 `coord_format` 契约**：
   - 在节点配置与 `ModelEndpoint` 中引入显式字段 `coord_format: Literal["point_yx_1000", "point_xy_1000", "bbox_yxyx_1000", "bbox_xyxy_1000", "bbox_xyxy_px"]`。
   - 移除 `object_detector.py` 第 169–177 行的无条件翻转逻辑，改为在纯函数 `normalize_detected_coordinate(item, *, coord_format, image_size)` 中按声明格式一次性完成中心点提取、`[x, y]` 顺序对齐、像素到 `0~1000` 归一化与 `[0, 1000]` 边界裁剪。
2. **Prompt 按格式分派**：
   - `gemini-robotics-er` 使用原生 `point_yx_1000` 指令；
   - 阿里云百炼 `Qwen-VL` 使用与其预训练对齐的 `bbox_2d`（`[xmin, ymin, xmax, ymax]`）指令，并在 `_run_object_detection` 入口只读取一次图像 `(width, height)` 与 Base64 编码。
3. **超时解耦与 Fallback 闭环**：
   - 将 Detector 单次调用超时提升至端点级可配置（百炼 Qwen 默认 `25.0s`，大于单次重试窗口），并通过 `with_fallback` 包装主备 Detector 调用，当主模型超时或不可用时自动切换至 `fallback`。

---

## ADR-007：五角色隔离的 Agent 协作流水线（新增，用户已确认）

### 上下文与问题陈述
原 `HANDOFF.md` §5 设定为“单 Agent 工作流”，而后提议改为“Gemini Flash 开发 + Claude Sonnet 测试与审查”。独立审查指出：若规格书存在偏差，双 Agent 会把错误固化进测试；且测试作者兼任代码审查存在自审盲区，同时缺少负责基准跑批的独立角色。

### 决策内容
采用**五角色隔离流水线**推进后续代码实施与验收：
1. **Spec Owner / Architect（Opus / Pro 级）**：维护 `Spec v1.1` 与契约测试清单，对实现阶段的“测试争议（Test Dispute）”做唯一仲裁。
2. **Test Author（Claude Sonnet 5.5）**：依据 `Spec v1.1` 与仓库代码事实编写先验失败测试（Red Commit），测试文件提交后对 Implementer 只读冻结。
3. **Implementer（Gemini 3.8 Flash / Argon）**：在授权目录内编写最小实现使测试变绿（Green Commit），**严禁修改测试断言**；若认为测试有误，必须附证据向 Spec Owner 发起 Test Dispute。
4. **Independent Reviewer（独立会话的 Sonnet / Opus）**：使用 `matt-code-review` 进行 Standards + Spec 双轴审查（同时审查业务代码与测试质量）。
5. **Bench Operator（脚本化执行角色）**：运行 `scripts/probe_capabilities.py`、`scripts/gate.py` 与 `scripts/run_benchmark_comparison.py`，完全以脚本返回码和客观产物作为 L4/L5 门禁依据。
