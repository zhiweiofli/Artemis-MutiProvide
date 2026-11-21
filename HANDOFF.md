# HANDOFF.md — Artemis 项目接入与模型解耦阶段交接报告

## 1. 任务背景与目标 (Goal & Scope)

- **目标**：对 ARTEMIS 项目进行架构与原理深度剖析，以“拓展模型供应商、与 Google 解耦且 100% 保全核心能力”为核心方向完成项目契约初始化、独立架构审查与 `Spec v1.1` 规格书修订。
- **候选供应商组合**：
  - **主干多模态主脑**：DeepSeek (`deepseek/deepseek-flash-v4-1017`)
  - **纯视觉空间定位兜底**：阿里云百炼平台（DashScope）接入的 Qwen-VL (`qwen/qwen2.5-vl-72b-instruct` 或百炼专属端点)
- **分阶段策略**：
  - **阶段一 (`ds-qwen-hybrid`)**：主走 DeepSeek + 百炼 Qwen，允许跨厂商 `fallback` 指向 Gemini 以保障生产级容灾。
  - **阶段二 (`ds-qwen-pure`)**：拔除全部 5 处硬编码 Google 后门，切换为纯非 Google 多模态备用链，通过“零 Google 运行不变量”独立验收。

---

## 2. 关键架构事实与解耦发现 (Architectural Facts)

1. **核心能力保全边界**：
   - ARTEMIS 依赖 Android Accessibility Helper 与 UIAutomator2 构建 `minimal_list` 结构化元素树。
   - 包含 Flash Profile（单智能体观察-思考-行动循环）与 Pro Profile（LangGraph 多智能体图谱）。
   - 核心感知闭环包含：UI 树元素点击 -> 坐标回退定位 -> 异步 Transcript 压缩 -> 检查点验证。
2. **Google 强依赖节点与隐式后门定位（FACT）**：
   - `config/artemis.jsonc` 默认全局指定 `google/gemini-3.8-flash`，`object_detector` 指定 `gemini-robotics-er-2-preview`，`hopper` 仅指定了 `model: "gemini-3.5-flash-lite"`（未声明 `provider`）。
   - 代码中存在 5 处绕过预设的 Google 硬编码调用点：`artemis/memory/chunking.py`、`artemis/agents/flash/summarizer.py`（同时存在 `is_utils=True` 传参 Bug）、`artemis/config/llm.py:lightweight_judge_default`、`artemis/agents/flash/runner.py`、`artemis/agents/explorer/constants.py`。
   - `video_analyzer` 与 `explorer` 均已内置双引擎（Native Google SDK vs Universal LangChain Engine）。
3. **DeepSeek 与百炼 Qwen 适配关键事实**：
   - `deepseek-flash-v4-1017` 原生支持多模态截图输入 (`image_url`)，可作为全局默认主模型对等替换 Gemini 3.8 Flash。
   - 阿里云百炼 Qwen2.5-VL 默认返回 `[xmin, ymin, xmax, ymax]` 绝对像素坐标（而 Gemini ER 返回 0–1000 的 `[y, x]`），需通过声明式 `coord_format` 与图像真实宽高 `(W, H)` 完成中心点提取与千分位归一化。

---

## 3. 本轮交付物清单 (Deliverables)

- [x] **基线快照**：`.agent/baseline.json`（固化 23 个核心代码与配置文件摘要）
- [x] **项目契约**：`.agent/contract.json`（定义必需文档角色与 doctor 校验命令）
- [x] **AI 宪法与工程原则**：[`AGENTS.md`](file:///Users/zw-mini/orca/artemis/AGENTS.md)（包含 6 大宪法内核、P-001~P-008 分级原则、四大工具策略与原子能力路由表）
- [x] **项目架构地图**：[`PROJECT-MAP.md`](file:///Users/zw-mini/orca/artemis/PROJECT-MAP.md)（包含双引擎原理、目录地图、Google 解耦矩阵与能力期望表）
- [x] **独立架构审查报告**：[`docs/OPUS_INDEPENDENT_REVIEW.md`](file:///Users/zw-mini/orca/artemis/docs/OPUS_INDEPENDENT_REVIEW.md)（识别 B1–B7 七项 P0 阻断项、评估五角色分工与高自主闭环机制）
- [x] **选型调研报告 (v1.1)**：[`docs/MODEL_SELECTION.md`](file:///Users/zw-mini/orca/artemis/docs/MODEL_SELECTION.md)（补全全仓库 Gemini 调用点、百炼 Qwen-VL 坐标差异与双阶段演进表）
- [x] **架构决策记录 (v1.1)**：[`docs/ARCHITECTURE_DECISIONS.md`](file:///Users/zw-mini/orca/artemis/docs/ARCHITECTURE_DECISIONS.md)（ADR-001~ADR-007，固化用户 5 项决策）
- [x] **解耦技术规格书 (v1.1)**：[`docs/TECHNICAL_SPEC_DEEPSEEK_QWEN.md`](file:///Users/zw-mini/orca/artemis/docs/TECHNICAL_SPEC_DEEPSEEK_QWEN.md)（涵盖 `presets_v2`、表驱动工厂、`stream_usage=True`、结构化输出协商、`coord_format` 坐标归一化、探针/门禁脚本与 12 项先验契约测试矩阵 `T-01`~`T-12`）
- [x] **契约自检**：通过 `check.mjs doctor` 验证通过（`status: healthy`）。

---

## 4. 关键决策记录 (Decisions, v1.1 已确认)

- **ADR-001（基线保全与分阶段 Fallback）**：保留 `gemini-baseline`；阶段一（`ds-qwen-hybrid`）允许跨厂商 fallback 指向 Gemini；阶段二（`ds-qwen-pure`）将“零 Google 运行”作为独立验收项。
- **ADR-002（DeepSeek + 阿里云百炼 Qwen 独立双通道）**：通过表驱动 `ChatOpenAI` 接入，默认 `QWEN_BASE_URL` 指向阿里云百炼 `https://dashscope.aliyuncs.com/compatible-mode/v1`（兼容 `QWEN_API_KEY` 与 `DASHSCOPE_API_KEY`），强制注入 `stream_usage=True` 与 `max_retries=0`。
- **ADR-003（`presets_v2` 向后兼容冷启动切换）**：保留顶层扁平 `presets` 兼容 Admin Console；新建 `presets_v2` 承载多节点拓扑，阻断 Provider 继承泄漏，未知预设名立即 Fail-Fast。
- **ADR-004（统计严谨的 6 维对比体系）**：配对跑批 $N \ge 5$、固定裁判模型、离线 Grounding 回归集与本地故障注入测试。
- **ADR-005（能力先验探测与结构化输出协商）**：通过 `probe_capabilities.py` 实测端点能力；DeepSeek / 百炼 Qwen 的 `with_structured_output` 默认协商为 `function_calling`；HTTP `402` 归为立即触发跨厂商 fallback；启动期强制执行 P-003 `is_multimodal` 校验。
- **ADR-006（声明式 `coord_format` 与 Detector 韧性加固）**：支持 `point_yx_1000`、`bbox_xyxy_px`、`bbox_xyxy_1000` 等 5 种坐标格式自动归一化，移除无条件 `[y, x]` 翻转 Bug，接入 `with_fallback` 并将百炼 Qwen 默认超时设为 `25.0s`。
- **ADR-007（五角色隔离流水线）**：Spec Owner → Test Author (Sonnet 5.5) → Implementer (Gemini Flash, 严禁改测试) → Independent Reviewer → Bench Operator。

---

## 5. 下一阶段实施分工与授权边界 (Execution Plan for Spec v1.1)

### 5.1 五角色执行顺序
1. **Phase 1 — Test Author (Claude Sonnet 5.5)**：按 [`docs/TECHNICAL_SPEC_DEEPSEEK_QWEN.md` §7.2](file:///Users/zw-mini/orca/artemis/docs/TECHNICAL_SPEC_DEEPSEEK_QWEN.md) 编写 `T-01`~`T-12` 先验单元测试（`test_preset_switching.py`、`test_deepseek_qwen_providers.py`、`test_object_detector_coords.py`），确认 Red 状态后冻结测试文件。
2. **Phase 2 — Implementer (Gemini 3.8 Flash)**：按 `Spec v1.1` §2~§6 实现配置层、路由层、后门清理、Detector 坐标归一化及 `probe_capabilities.py` / `gate.py`，使 `T-01`~`T-12` 及既有 25 项测试全部变绿（Green 状态）。
3. **Phase 3 — Independent Reviewer**：运行 `matt-code-review` 进行 Standards + Spec 双轴审查。
4. **Phase 4 — Bench Operator**：执行 `gate.py --level L4` 与 `probe_capabilities.py` 产出验收报告。

### 5.2 允许写入范围（已由用户确认扩充）

> 当前 P2 的精确边界与交付入口见 `.fabric/runs/run-t0C4y7/p2-green-impl/round-0/CONTEXT.json`：根冻结任务限定 18 个业务文件及看板/交接同步文件。下方目录概述不扩大该白名单。P1 已接受，三份契约测试与全部既有测试/fixture 均禁止修改；分别以 `p1-red-tests/FROZEN_TESTS.json` 和 P2 的 `TEST_TREE_BASELINE.json` 为准。具体测试冲突必须报告 Test Dispute，不改断言绕过。
- 配置层：`artemis/config/constants.py`、`artemis/config/settings.py`、`artemis/config/llm.py`、`third_party/mobile_use/config/llm.py`、`config/artemis.jsonc`
- 路由与网关层：`artemis/llm/router.py`、`artemis/llm/reliability.py`、`artemis/llm/google/usage.py`、`artemis/services/llm.py`
- 后台记忆与 Agent 去硬编码：`artemis/memory/chunking.py`、`artemis/agents/flash/summarizer.py`、`artemis/agents/flash/runner.py`、`artemis/agents/explorer/explorer.py`
- 视觉检测层：`artemis/agents/object_detector/object_detector.py`、`artemis/agents/object_detector/object_detector.json`
- 脚本与测试层：`scripts/probe_capabilities.py`、`scripts/gate.py`、`scripts/run_benchmark_comparison.py`、`tests/unit/`

## 6. Fabric 3.0 运行环境核查（2026-11-10；历史核查记录，最新执行状态见 §7）

- **FACT**：用户批准的 `run-rIQ5fl/plan.json` 字节 SHA-256 为 `5df38ed26b0df892a83d4ee273e41650cb0ebf3396e8feb2057e142a2ad77086`，其 `sources.profilesSha256` 对应当前 `fabric.agents.json` 的 `5dd49e9b0562a97409174dfedceb2d999ae3a96bf0734cef68b9a6bef6981df6`。`plan_approved` 已记录于 `.fabric/runs/run-rIQ5fl/EVENTS.jsonl`；`fabric report` 显示 1 次批准、0 次启动，未记录 Orca Run ID。Orca `orchestration run-list --json` 仅返回遗留只读 Run，`worker-list --json` 为空；没有目标 Run/Task/Dispatch。
- **FACT**：`agy models` 当前列出 `gemini-3.8-flash-high`、`gemini-3.8-flash-medium`、`gemini-3.8-flash-low`，未列出 `fabric.agents.json` 中的 `gemini-3.8-flash`。**更正（2026-11-10 实测）**：`agy -p --model gemini-3.8-flash --effort high` 与 `--model gemini-3.8-flash-high` 均返回 `OK`，无后缀 ID 被 CLI 接受；print 模式无法证明实际生效的模型，所以这只说明可启动。
- **FACT**：本机 Codex CLI v0.162.1 的模型缓存（`~/.codex/models_cache.json`，2026-11-09T16:21:38Z 更新）列出 `gpt-6-sol`、`gpt-6-luna`、`gpt-6.1-sol` 等，未列出配置中的 `gpt-5-codex`。`~/.codex/config.toml` 当前默认 `gpt-6-luna`、`model_reasoning_effort=high`；本次 Claude Code 会话由用户 `/model` 选定 `GPT-6-Sol · Codex`，与 Codex CLI 默认模型不同。
- **FACT**：Claude CLI v2.1.319 可以进入 `claude-sonnet-4-6` 会话；以 `--effort high` 启动的终端显示 `max effort`，因会话环境 `CLAUDE_CODE_EFFORT_LEVEL=max` 覆盖了参数。Orca 账号状态报告 Claude 用量遥测不可用（API key 计费），不能据此判定模型请求不可用。使用 `--surface chat --model claude-sonnet-4-6 --effort high` 启动过另一个协调会话，但它在创建 Run 前停止；没有有效的计划派工回执。
- **INFERENCE**：冻结计划复制了旧模型配置。若要把 AGY/Codex 调整为实际可选模型，须修改 profile 并重新 `fabric prepare --plan` 生成新 SHA 的计划，让用户审核新计划；旧批准只对原 SHA 有效。恢复前先复核 Orca 原生现场和时间/启动预算，不以本地摘要代替原生状态。既有 `HANDOFF.md` §5.1 和 `docs/TASK_BOARD.md` 将 P1 测试作者列为 Claude Sonnet 5.5，而冻结 DAG 列为 AGY，角色分工也需由用户确定。

## 7. Fabric 当前活动执行（2026-11-10）

- **FACT**：用户已批准新计划 SHA `d67313f43755b1bbbf6f0aae71f2aa8dc55cc9d22d6dee302c53c1f1144568ee`，并亲自执行 `fabric record` 写入 `plan-approved-user-run-t0C4y7`。入口为 `.fabric/runs/run-t0C4y7/REQUEST.md`。当前角色：Claude Manager `group/auto-claude-sonnet[1m]`、AGY Worker `gemini-3.8-flash`、Codex Reviewer `gpt-6.1-sol`，均配置 high。该批准计划指定 AGY 为 P1 测试作者，恢复时遵循冻结计划。
- **FACT**：唯一原生 Run 为 `run_5864774b88cc`，协调者为 `term_64593267-b8fd-4524-a970-1e88dfe57022`；四 Task ID 与创建回执保存在本 Run 的 `ORCA_RUN.json` 和各 Task 的 `task-create.receipt.json`。
- **FACT**：P1 Task `task_64f189a026e6` / Dispatch `ctx_596997c7e4e6` 已 completed，收到 `msg_ef0160cee014` worker_done；Worker 报告旧 25 项通过、新 12 项 Expected Red。三个测试文件已读取，23 项业务代码基线摘要仍匹配；尚未作接受裁决。真实启动 requested/effective 为 `antigravity / gemini-3.8-flash / high`；后来通过已启用 Orca 本地索引、按唯一Dispatch ID 查询得到 AGY session `bbfd03be-17f1-4f8a-b966-7cd9628a38d7`，Reviewer session `01a1c171-9e2c-7f31-97ab-0a4870858ef0`（仅提取元数据，见运行目录 `session-identities.json`，未复制会话正文）。候选及验收摘要见 `p1-red-tests/delivery.json`；candidate SHA 为 `cef95034a7470196a978e2717eef8012587da52ac161898ec733fde7b8083a87`。P1 Reviewer Task `task_98cd2aa80af0` / Dispatch `ctx_b93471cf162c` 已启动，`codex / gpt-6.1-sol / high`、turnStart observed；P2/P3 尚未派发。
- **FACT**：Fabric 原生调用未加 `--full`，与 Orca 1.4.251 的默认简略 JSON 不兼容，首次预检在保存启动 intent 前拒绝。Run 下 `fabric-full-json.mjs` 使用原 CLI `main()` 的客户端注入接口，对四个编排命令追加原生 `--full`；保留全部派工校验、锁与预算，使用同一 Orca 二进制，未修改 Runtime/冻结计划。后续实际派工复用此入口；原始 native 回执和启动 intent 已落盘，严禁重复启动同一轮。
- **FACT（审查裁决）**：Reviewer 已自行产出并核实 `p1-red-review/round-0/REVIEW.md` 和 `REVIEW.json`，结论 REWORK，7项finding：异步FallbackRunner测试API错误、环境/settings隔离缺失、fallback坐标断言漏检、预设优先级不可区分、legacy presets保留漏检、AgentNode遍历遗漏、专属BASE_URL绑定漏检。Reviewer独立实测旧25 passed、新12 failed，业务基线未变。身份字段已由Reviewer依据原生有效启动与索引元数据补齐。controller已记录首次业务REWORK，`delivery.json`判定 errors=[]、businessReworks=1、remainingReworks=1、downstreamReady=false；没有接受P1，P2禁止派发。
- **FACT（无全局改动的恢复）**：曾复现 `/usr/local/bin/orca` 为 root:wheel、模式 `lrwx------` 的符号链接导致读取目标失败；用户不批准修改全局权限，sudo尝试也未执行成功。确认原Reviewer终端身份且tui-idle后，仅一次投递使用 `/Applications/Orca.app/Contents/Resources/bin/orca` 读取原收件箱的传输恢复命令，原任务指引及worker_done仍走原生Dispatch。已观察turn_started，随后于 `2026-11-09T23:26:44Z` 收到 `msg_338537e2902d` worker_done；两个原Dispatch均completed且终端released。没有修改全局链接、权限或新增恢复Dispatch。
- **FACT（返工已准备）**：同一P1测试和审查Task均已追加round-1，保留round-0原始产物与审查；稳定TaskSpec和原计划SHA未变，两个dry-run均confirmed。P1 Task已ready，P1审查pending，P2 blocked；没有启动新轮次。原生CLI绝对路径已写进返工差异。测试与业务代码未被controller修改。`docs/TASK_BOARD.md`和Archify候选/HTML已同步为P1 REWORK/P2 BLOCKED，编译validate/deliver/check通过，未执行browser-check。入口doctor=healthy，6项业务Skill在位，uv/Python 3.14.3可用。
- **用户策略（已触发实施）**：同一Task第3次审查仍REWORK后改AGY/Argon High，新Task仍Flash先做；第5次仍失败时仅将非核心且不影响可用性的意见记录为非阻断项，核心与必需验收继续阻断。规则在AGENTS.md §3.3，传输重试不计数。当前P1已完成3次业务审查且REWORK，触发条件。`fabric.agents.json`已新增 `agy-argon`（antigravity / gemini-4-argon-high / gemini-4-argon / high），`fabric.json.delivery.workers`为[agy, agy-argon]，默认agents.worker仍agy/Flash；原profiles不变。当前任务由显式用户策略驱动的controller原生派工实现兜底，非旧Runtime自动路由。原包maxReworks<=2的硬校验与单Worker冻结机制未修改，旧fabric dispatch/append入口在新配置下不再适用，不伪造其通过。旧配置字节备份为Run下pre-escalation-fabric*.json；原冻结plan.json字节与原批准保留。
- **FACT（预算已续期并恢复派工）**：用户通过时间续期选项明确授权再120分钟，已记录 `budget-window-user-renewal-2`，绑定原批准及同一SHA；累计上限仍8次，原启动/返工/审查计数不重置。新截止为 `2026-11-10T03:07:59.479Z`（北京时间11:07:59）。P1 round-1已启动为同一Task的新Dispatch `ctx_73f263f8e175`，原生回执ready、turnStart observed、requested/effective均为 `antigravity / gemini-3.8-flash / high`；实际启动增至3次。原窗口过期暂停记录保留为历史，无全局权限改动。Worker已收到本轮预算与交付时更新旧预算提示的原生消息，controller不与Worker并发编辑其测试或看板。
- **FACT（round-1已交付并进入复核）**：收到 `msg_6da5c03895e0` worker_done，Flash Dispatch `ctx_73f263f8e175` 已completed。Worker逐项回应R1~R7，日志为旧25 passed、新12 failed；controller核验6项候选文件与23项业务基线摘要均匹配。原生索引按Dispatch查得新AGY session `bc07418f-8070-4625-8ba6-67dc1408556e`。候选SHA `cbed9f17396c166142f26fa0d8e912497e332009359f955718bda31f1ffaad7e`，验收SHA `0033ed9eed3356851589dd04ae872374b8c91e10090b28d5de5de77774346325`；只读源快照和最终HTML副本在 `p1-red-tests/round-1/frozen-source/`，对应索引已追加至delivery.json，原轮次/裁决保留。实际修复是否完整尚未接受，看板PENDING_REVIEW/P2 BLOCKED。
- **FACT（第二次审查与裁决）**：收到 `msg_d8bf82e6600f` worker_done，Reviewer `ctx_35752bda6479` 已completed并released；独立REWORK、真实session `01a1c30d-d4a5-78a0-9af4-27fa9697d07a`已按原生唯一Dispatch索引核实。R1/R4/R5/R6已通过复核，剩余R2（实际配置入口未隔离）、R3a（utils缺参与failed重叠漏检）、R3b（两label误要求全局只调用一次）、R7（完整URL路径漏检）具有可复现的实质影响；round-1自写mutation helper未调用真实交付测试，不能作为真实判别力证据。controller已记录第二次REWORK，delivery.json errors=[]、businessReworks=2、downstreamReady=false。P1/P2未接受，旧25 passed、新12 failed仍是Red阶段证据。
- **FACT（round-2交付核验）**：收到 `msg_dec26b8af6da` worker_done；Flash `ctx_bfdee232e9a7` completed且released，session `aff9c4e1-8278-4038-be10-c636793e6b00` 已用原生Dispatch索引独立核实。Worker报告四项已修复，日志旧25 passed、新12 failed，并提供调用真实fixture/test函数的控制组及错误实现日志。controller核对6项当前源与只读快照摘要、23项业务基线均匹配；复用Worker已准备的本轮snapshot/delivery索引，未覆盖旧轮或裁决。候选SHA `0100c3984c2a649bd710d6d89c1131d11f7cbbf31ab49b863ef9aca72d04f9f4`，验收SHA `40821e518d028c2b54b7491cb12152e5544c64702144fb6d0bae682786e45e9c`。本轮仍未接受，看板PENDING_REVIEW/P2 BLOCKED。
- **FACT（第三次审查）**：收到 `msg_e294635126f8` worker_done，Reviewer `ctx_bb4a906611df` completed且released，真实session `01a1c32c-f5af-7dc3-8f00-8c3f2110c509` 已用原生索引核实。结论REWORK，仅剩R3b：Mock对缺少label的首请求返回固定框，per-label断言跳过零次，导致字面量 `Locate {labels_str}` 的真实T12在Timeout/503均误过。R2/R3a/R7及早期其它修复已通过复核。controller已记录第三次REWORK；按用户后续策略，P1的有效有界返工上限为4（支持第5次审查评估），现有模块assessDelivery以该参数判定errors=[]/businessReworks=3；旧Runtime默认值2保留为兼容配置，不将其当新策略已自动支持。
- **执行补充与启动方式（恢复必读）**：Run内 `EXECUTION_SUPPLEMENT.json` 记录原计划SHA、原批准、真实用户策略事件、当前唯一配置增量摘要、原Run/Task ID、稳定TaskSpec和本轮材料摘要。`native-policy-dispatch.mjs TASK_KEY ROUND [--preflight-only]` 调用同一应用内Orca原生接口，复用现有预算/交付验证模块；核对原批准与策略、补充摘要、配置/Skill/材料、原Task ready/spec/deps、全分页已结算workers、全部旧intent回执、累计预算及独立审查/下游接受门禁。它保存同目录intent/receipt/error并使用同一派工锁，不重试未知启动，不创建新Run/Task，不改Runtime/原plan、不重置计数。旧CLI入口受新配置摘要与混合profile限制，后续不要继续调用fabric-full-json.mjs dispatch，也不要篡改旧plan.sources去伪造一致。追加新材料/策略时须保留旧版本并记录新的补充依据，不能静默改已记录补充。
- **FACT（Argon round-3交付）**：收到 `msg_c144267850b8` worker_done；Argon `ctx_c598e94a8139` completed且released。session `6cf75adf-b2f4-44aa-9eb8-d4f24cbc6e65` 已由唯一Dispatch原生索引独立核实。实际差分仅修改T12与看板，另两份测试与r2字节一致；移除无label固定框兜底、无条件逐query计数/label集合/未匹配调用断言。旧25 passed、新12 Expected Red，原Reviewer复现为正确实现PASS/未展开label具体AssertionError；均有原始日志。六个当前源与只读快照、23项业务基线匹配。候选SHA `9ce778e19b874e6cab0685e37997c44c80f4ec661615e4346fc526a75250e214`、验收SHA `5f1302950c2841909de0d64deadbd879aa817429c6c38d0405f0c52b0eb5f7b5`，已追加r3交付索引并保留三次REWORK；source控制组/最终Archify编译及其嵌入strict check证据也已登记（实际由Worker执行，browser-check未运行），尚无接受裁决。
- **FACT（P1最终审查并已接受）**：收到 `msg_bf3f3f865807` worker_done；第四次独立审查Dispatch `ctx_aeb52177849d` completed，Reviewer真实session `01a1c35d-88bc-7550-8ce7-6f23e50e9a87` 已原生索引核实。REVIEW.json为PASS且绑定候选SHA `9ce778e19b874e6cab0685e37997c44c80f4ec661615e4346fc526a75250e214`、验收SHA `5f1302950c2841909de0d64deadbd879aa817429c6c38d0405f0c52b0eb5f7b5`。Reviewer复验旧25 passed、新12 failed Expected Red、23项业务基线匹配及受保护路径clean，并用真实fixture/T12验证正确文本与多模态逐label实现通过，未展开/空/未知/漏label/零调用均被拒绝。controller核对候选、验收、制品、source/build/artifact证据，`assessDelivery(...,4)` 返回accepted=true、downstreamReady=true、errors=[]，已记录 `accept-p1-red-tests-r3`。三份冻结测试的字节摘要在Run内 `p1-red-tests/FROZEN_TESTS.json`；这只代表先验测试契约PASS/Expected Red，不是P2业务实现或用户验收。看板已将P1置DONE，Archify HTML已重编译；未执行browser-check，且未做人工视觉验收。
- **历史预算暂停（已被下方新授权取代）**：Run内8个Dispatch全部completed；最后Reviewer终端reclaimable，等待Orca自动释放，不要手工关闭。P2尚未启动。原生接续入口 `native-policy-dispatch.mjs p2-green-impl 0 --preflight-only` 在检查冻结测试后因累计启动8/8和明确预算窗口规则正确失败，说明不能启动P2。**P2仍使用默认AGY/Flash，不使用Argon**；至少还需2次累计启动（P2实现+P3最终审查），考虑可能返工应请求更高绝对上限；当前时间窗口截止北京时间11:07:59，也应在启动前核对是否足够。必须由用户明确追加 `budget_window`（相同plan SHA、绝对launchLimit、新expiresAt）后重新预检P2，不得自行扩大预算、改历史计数或新建Run/Task。验证应使用 `native-policy-dispatch.mjs p2-green-impl 0 --preflight-only`；P2写入白名单保持原计划，严禁改tests。
- **最新预算与 P2 准备（2026-11-10）**：用户明确要求把启动上限和时长翻倍，已记录 `budget-window-user-double-3`：绝对累计上限16次（已用8次不清零）、新窗口240分钟，截止 `2026-11-10T08:38:22.423Z`（北京时间16:38:22）。8个旧Dispatch均completed且released，没有活跃Worker。P1接受状态保留；P2继续默认Flash，精确18文件白名单、248个测试/fixture文件保护及已有接受依据已固定到 `p2-green-impl/round-0/CONTEXT.json` / `BUSINESS_BASELINE.json` / `TEST_TREE_BASELINE.json`，并记录摘要到 `intervention-p2-boundaries-prepared`。原生启动适配已新增冻结测试和完整测试树校验。下一步将P2 Task从blocked恢复ready，执行原生只读预检，再启动同一Task的P2 round-0。本段为启动前说明；实际派工ID和状态以 `ORCA_RUN.json`、`dispatch-intents/p2-green-impl-round-0.receipt.json` 及原生Orca对账为准，不能据本段推断未启动或重复派工。派工后controller仅更新运行记录，HANDOFF/两份看板交Worker维护至worker_done结算，避免并发编辑；不复用已结算Dispatch、不改全局权限。
- **FACT（P2-GREEN 落地与全绿验收，2026-11-10）**：
  - AGY Worker (`gemini-3.8-flash`) 严格遵循 18 个业务文件白名单完成实现，**严禁修改的 `tests/` 目录保持 100% 字节冻结未受修改**。
  - 实现内容：
    1. 常量与配置：`constants.py` 与 `settings.py` 扩充 `deepseek` / `qwen` / `dashscope` / `bailian` 提供商与环境变量、`CoordFormat`、`StructuredOutputMethod` 及 `MULTIMODAL_REQUIRED_NODES`。
    2. 模态校验与凭据：`third_party/mobile_use/config/llm.py` 扩充 `is_multimodal`（P-003 启动拦截）、`coord_format` 与凭据校验，`LLMWithFallback` 闭环校验 fallback 模态。
    3. 预设解析防泄漏：`config/artemis.jsonc` 新增 `active_preset` 与 `presets_v2`；`artemis/config/llm.py` 落地纯函数 `resolve_preset_config`，阻断跨厂商继承泄漏，`get_agent` 动态消除 Google 裁判后门。
    4. 表驱动模型工厂：`artemis/llm/router.py` 扩充 `ModelProvider` 与 `ModelEndpoint`，表驱动实例化 `ChatOpenAI` 强制注入 `stream_usage=True` 与 `max_retries=0`。
    5. 结构化协商与后门清理：`artemis/services/llm.py` 实现 `RobustChatModelWrapper.with_structured_output` 默认 `function_calling` 协商与 `get_llm_for_model` 中立工厂；`reliability.py` 映射 402/欠费为非重试立即 Fallback；`usage.py` 提取 `prompt_cache_hit_tokens` 与 `cached_tokens`；拔除 `summarizer.py`（修复 `is_utils=False`）、`chunking.py`、`runner.py`、`explorer.py` 的 5 处硬编码 Google 调用。
    6. 声明式坐标归一化与 Detector 加固：`object_detector.py` 导出纯函数 `normalize_detected_coordinate`（支持 5 格式归一化与倒置/退化过滤），单次图像解码，`_detect_single_label` 通过 `with_fallback` 闭环容灾。
    7. 门禁与闭环脚本：落地 `scripts/gate.py`、`scripts/probe_capabilities.py`、`scripts/run_benchmark_comparison.py`。
  - 机器门禁全部通过：
    1. `uv run python scripts/gate.py --level L4 --phase P2-GREEN --json` 返回码 `0`（L1~L4 全绿，既有 25 项 + 新增 12 项共 37 项单测全部 `PASSED`，自动同步 `docs/TASK_BOARD.md` 与重编译 `phase-task-board.html`，Archify quality: showcase，receipt pass）。
    2. `uv run pytest tests/unit/test_third_party_boundary.py -q` 返回码 `0`（321 passed）。
    3. `node .agents/skills/workbench-project/scripts/check.mjs doctor .` 输出 `status: healthy`。
  - P2 业务实现就绪，交付进入 P3 双轴独立审查阶段。


## P2 Controller 核验与最终审查入口（2026-11-10）

- **FACT**：收到P2 Worker `ctx_b90a6b7631c7` / Task `task_441a4b7e6761` 的 `msg_d9f10b02f027` worker_done，业务候选已交付但尚未接受。controller核验248个测试/fixture与三份已接受契约的摘要均未变，受保护基线本身也匹配启动前记录。17个业务文件发生变化，候选冻结18个允许范围业务文件（含1个未改文件）及只读副本；未发现白名单外tracked业务改动，.gitignore是任务前已存在差异。
- **FACT**：Worker只在DELIVERY里列测试结果，未留独立日志；controller已实际运行 `uv run python scripts/gate.py --level L4 --phase P2-GREEN --json` 与边界测试，退出均0，结果37 passed / 321 passed，原始stdout/stderr/退出码在 `p2-green-impl/round-0/controller-checks/`。Gate原始输出包含Archify构建/strict check通过，HTML摘要 `efe56c2700ec8284bd3a7349d7ee49898cf219e173ba6dd6703a790f5c667b33`。这些结果不代替Standards+Spec完整性审查；应用模型能力、设备闭环与测量基准仍未验收。
- **FACT（原生跟进对账）**：Orca为完成后送达的启动边界消息自动创建 `ctx_7a61eeb165e9` / `task_dfd7dbfa29fc`（New messages），followUpOf原P2 Dispatch；同终端/同进程复用、无新进程、仅确认收到 `msg_17b1fbf6183a`，filesModified=[]，已completed/released。早期turn-unobserved升级被真实 `msg_1766e8da7bdd` worker_done结算，不重发、不停止已结束进程。controller将此跟进保守计1次预算单位，真实worker-show原样收存于 `dispatch-intents/native-followup-ctx_7a61eeb165e9.receipt.json`，intent标明origin/native-mail-followup且args=null，不伪造worker-start回执；不计新的业务审查或返工。
- **固定候选**：`p2-green-impl/delivery.json` 初始round已登记、decisions=[]；候选 `round-0/candidate-source.json` SHA `4c5f09c997273ee4f4143ba27e1d0572de128c6ffa2dd2b673e873d4108dbb9f`，验收TASK SHA `3739f889646a3038d5d78ffe2d34332844666207a51518186ffffff90b1f5972`。源码快照位于同目录frozen-source，candidate.diff含完整源码变更。为允许强制gate复验，TASK_BOARD/HANDOFF/Archify衍生文件不纳入业务源码候选SHA；最终复验若改变衍生HTML，controller须将最后一次构建及其check对应制品重新固定，不能沿用旧制品PASS。
- **P3入口**：同一最终审查Task `task_37a69e1e27d0` 已ready；本轮 `p3-final-review/round-0/CANDIDATE.json` 给出独立Standards+Spec审查范围、候选/验收摘要、冻结测试、实际验证日志与输出边界。必须由Reviewer自行生成REVIEW.md / REVIEW.json及docs/CODE_REVIEW_P3.md，不改业务或测试；按原任务复跑L4/边界命令。所有原生编排均用 `/Applications/Orca.app/Contents/Resources/bin/orca` 绝对路径及需要的--full，不修改全局权限。实际Dispatch ID/状态以ORCA_RUN和原始receipt及原生查询为准，严禁重复派发。
- **预算**：启动前预算占用10/16（含上述保守计入的1次消息跟进，实际新进程启动9次）；P3正式启动将占第11个单位。新窗口仍截止 `2026-11-10T08:38:22.423Z`（北京时间16:38:22），不清零历史。P2当前完成实现候选且target tests绿色，最终接受等待真实独立Review及controller门禁；不要把看板DONE或Worker自报当最终接受。

- **当前实际审查**：P3已启动为 ctx_1d0ac9996bd6 / 原Task task_37a69e1e27d0，原生requested/effective为codex/gpt-6.1-sol/high、turnStart observed、liveness live。这是P2候选的第1次业务审查；P2 delivery.decisions仍为空，未接受。预算占用11/16（含1次原生消息跟进保守计入，非新的业务审查），截止仍北京时间16:38:22。原生跟进已对账且所有前序均结算/释放；原Run/Task及P1历史不变。等待此原Dispatch原生消息，勿重复派工。

- **P3原会话收件恢复**：收到msg_stop_b291565cff2bb2ca8b52f144：Reviewer在开始业务审查前被 /usr/local/bin/orca 链接解析故障挡住，Dispatch ctx_1d0ac9996bd6 仍dispatched、capability未撤销。核实同一终端term_2540a4bf-e7e2-4fca-96be-0e07becc8cbd空闲、无权限提示后，已在原生邮箱排入绝对路径指导msg_710430cc9933，并仅做一次原会话收件引导；请求56059116-1206-482e-8b9c-27fca9e06188观察到input_accepted/turn_started，进程身份ea30d86e-b79b-4683-98bd-fef0fe8000f6未变。不改全局权限、不新建Task/Dispatch、不增加业务审查或启动计数。一次45秒原生等待暂无新消息；等待Orca自动唤醒，勿盲重派。尚无最终审查报告/业务结论。

## P2 第 4 次业务审查（2026-11-11，run-t0C4y7）

- FACT：Argon round-3（dispatch ctx_bae5bf32fa67，session 9e46c5c3…）候选 candidate-source.json sha256 d97da205…；controller 复验 gate 37（显式绑定清单；未绑定 fail-closed）、321 边界、make test 2541/7/8、15 Explorer、typecheck、ratchet、ruff 全绿，248 受保护文件与 3 份冻结契约一致。
- FACT：Codex 第 4 次审查（ctx_a4fa2c057339，session 01a1c83c…）REWORK，绑定上述候选。确认 SPEC-01～06、SPEC-08、SPEC-09、B1～B7 已修；剩余 STD-01 / SPEC-07A（离线缺测用默认常量补成六维 PASS，故障恢复未真实注入）与 SPEC-07B（预算上限基于未施加的常量，未知成本不扣留，`**kwargs` runner 收不到剩余预算），均为验收正确性 P1。
- 状态：P2 round-4、P3 round-4 材料与执行补充 v6 已发布（v6.revision 内 controllerDecisionId/previousSupplement 字段沿用 v5 旧值，以 EVENTS 中 intervention-execution-supplement-v6-materials 的 references 与 previousSupplementSha256 为准）。用户已授权本 Run 剩余 Argon 返工与 Codex 审查（permission-approved-run-remaining-argon-codex），但时间窗口已于 2026-11-11T01:38Z 过期、启动 17/20，需用户给出新窗口后启动 P2 round-4。下一次审查为第 5 次，适用 §3.3 非核心意见收敛。

## P2 Round-4 实施与自检（2026-11-11，Dispatch `ctx_7afef9df019e`）

- **FACT**：AGY Argon Worker（`ctx_7afef9df019e` / Task `task_441a4b7e6761`）在白名单内仅修改 `scripts/run_benchmark_comparison.py`，消解 `STD-01`、`SPEC-07A` 与 `SPEC-07B`：
  1. **`SPEC-07A` / `STD-01`**：移除 `run_offline_benchmark` 中全部虚构默认观测值（`2000/300` token、`820/850ms` 时延、`18432` 请求字节、`1.0` 视频准确率及以定位结果充当任务成功）；缺少实测观测的维度统一标记为 `status: "unverified", passed: False`，仅定位输入及任一单维度缺失均返回 `UNVERIFIED`（绝不返回 `PASS`）；估算值单列于 `estimates`（`is_estimate: True, counted_in_acceptance: False`）；本地故障恢复通过隔离 `httpx.MockTransport` 与生产 `artemis.services.llm.with_fallback` + `acomplete_structured` + `parse_structured` 真实执行 429/402/503/流中断/坏 JSON 五类注入，禁用 `with_fallback` 时调用次数为 5、恢复率为 `0.0`、整体结论 `FAIL`；视频一致性与 `temporal_ground_truth` 对比，缺真值保持 `UNVERIFIED`。
  2. **`SPEC-07B`**：移除把固定假设常数当作任意 `runner` 可证明上界的逻辑；仅当 `runner` 显式声明单次最大成本（`max_cost_per_run_usd` / `estimated_cost_usd`）或在签名中显式接收预算约束参数（`remaining_budget_usd` / `max_cost_usd`）时才允许启动费用性任务，否则在执行前拒绝（0 次调用）；`_build_runner_invoker` 向同时含 `remaining_budget_usd` 与 `**kwargs` 的 `runner` 传入真实剩余预算（非 `None`）；发生 `RuntimeError`、空响应 `{}` 或缺失 `cost_usd` 等未知成本时立即终止后续轮次，保留 `known_cost_usd` 并设置 `cost_unknown: True, total_cost_usd: None`。
- **FACT**：L4 Gate（37 passed）、321 边界测试、完整 `make test`（2541 passed / 7 skipped）、15 项 Explorer 回归、`make typecheck`、`quality_ratchet.py` 与 16 个 Python 业务文件 `ruff check` / `ruff format --check` 全部通过（退出码均为 `0`），248 个测试/fixture 与 3 份冻结契约 100% 未改动。真实云端 API、真机闭环与生产六维跑批仍为未验证（待 `P4-BENCH`）。

## P2 第 5 次业务审查与待用户裁决（2026-11-11，run-t0C4y7）

- FACT：Argon round-4（ctx_7afef9df019e，session 6e079b5f…）交付候选、日志齐全，但 Argon 模型额度耗尽（约 105h 后重置），未发出 worker_done；controller 停止该 Dispatch 并直接核验产物，记入 delivery-p2-green-impl-r4（workerDoneSent=false）。controller 复验：gate 37、321 边界、make test 2541/7/8、15 Explorer、typecheck、ratchet、ruff 全绿；248+3 冻结文件一致。
- FACT：Codex 第 5 次审查（ctx_bd12e41672bb，session 01a1c8c7…）REWORK，绑定 round-4 候选。已按 §3.3 收敛策略逐项评估，三项均保留阻断，全部位于 scripts/run_benchmark_comparison.py：
  - SPEC-07A：空/未识别 usage 计为 0 成本并 PASS；离线视频准确率标量可绕过时序真值；“流中断”以响应前超时代替。
  - SPEC-07B：第 4 个普通位置参数被误认为预算护栏；estimated_cost 被当作最大成本。controller 独立复现：两种 runner 在 0.10 预算下各执行 1 次、花费 1.00（p3-final-review/round-4/controller-triage/）。
  - 未发现移动闭环核心退化；SPEC-01～06、08、09 及 B1～B7 保持已修。
- 状态：P2 未接受（decision-p2-green-impl-r4-needs-user）。返工上限 4 已用尽，Argon 额度耗尽，启动 19/20，窗口至 2026-11-11T05:03Z。需用户裁决下一步。

---

## 8. P2 终局修复与端机就绪（2026-11-12，接手闭环）

- **FACT（人工外科手术接管与缺陷消解）**：接管处理后直接在白名单文件 `scripts/run_benchmark_comparison.py` 实施精准修复，终结自动化死锁：
  1. **`SPEC-07A` / `STD-01` 修复**：
     - `_compute_cost_from_usage` 严格区分无 usage 与测得 0 成本。空字典、缺失有效 token 字段或未知结构直接返回 `None`；六维汇总路径将缺失 usage 标记为 `status: "unverified", passed: False`，整体结论拒绝误判为 PASS。
     - `_evaluate_temporal_video_sample` 强制要求时序真值 `temporal_ground_truth`，纯标量准确率缺失真值时拒绝返回虚拟得分，保持 `UNVERIFIED`。
     - 流中断注入场景真实开启 `stream: true` 并返回流式响应，在产出首个有效 chunk 后中途抛出 `httpx.ReadTimeout`，完整打通生产 `with_fallback` 流式容灾与恢复消费链路。
  2. **`SPEC-07B` 修复**：
     - 彻底移除 `len(pos_params) >= 4` 的误判，普通位置参数（如 `device=None`）绝不视作预算护栏；
     - 彻底移除把 `estimated_cost_usd` 视作可证明上限的逻辑；仅当显式声明 `max_cost_per_run_usd` 或形参声明可执行预算约束时才允许启动，0.10 美元预算下无约束 runner 严格执行 0 次。
- **FACT（门禁与大盘验证全绿）**：
  1. Reviewer 7 项反例控制 100% 修复并通过；
  2. `uv run python scripts/gate.py --level L4 --phase P2-GREEN --json --frozen-tests ... --test-tree-baseline ...` 退出码 `0`（L1~L4 全绿，37 项单测全部 PASSED）；
  3. `uv run pytest tests/unit/test_third_party_boundary.py -q` 退出码 `0`（321 passed）；
  4. `uv run python scripts/quality_ratchet.py` 退出码 `0`（质量卡尺通过）；
  5. `ruff check` 与 `ruff format --check` 全绿；
  6. 248 个受保护测试与 3 份冻结契约 100% 字节未篡改。
- **FACT（移动端真实设备与 MCP 联调成功）**：
  - 成功探测真实设备 Pixel 3（ID: `89FX09M9U`，Android 12，分辨率 1080x2160）；
  - 调通 `mobile-mcp` 工具集：屏幕截图取样、结构化 UI 树提取、元素坐标命中点击（成功打开系统“设置”）、系统全局按键导航（HOME 键恢复桌面）；
  - 真实设备链路与端侧闭环验证完全就绪，待配置真实端点 API Key 后即可启动生产 P4-BENCH 配对跑批。

---

## 9. P4 真实端点握手与 Pixel 3 五轮真机端到端验收通过（2026-11-13）

- **FACT（模型与动态环境适配）**：
  - 新增 `DEEPSEEK_BASE_MODEL`（默认 `deepseek-flash`）与 `QWEN_BASE_MODEL`（`Qwen/Qwen3.8-27B` on SiliconFlow）环境变量动态注入（`artemis/config/constants.py`, `artemis/config/settings.py`, `artemis/config/llm.py`）；
  - 当检测到 SiliconFlow 端点时，自动将 `object_detector` 的 `coord_format` 适配为 `bbox_xyxy_1000` 并放宽超时至 `35.0s`。
- **FACT（`probe_capabilities.py` 真实端点先验握手通过）**：
  - `deepseek-flash`：可达性（`verified`）、多模态图片输入（`verified`）、流式 Usage 提取（`verified`）。
  - `Qwen/Qwen3.8-27B` (SiliconFlow)：可达性（`verified`）、合成图 Grounding 校准（`calibrated_coord_format: "bbox_xyxy_1000"`, `error_1000: 0`, `verified`）。
- **FACT（P4-BENCH 5 轮真机配对端到端跑批通过）**：
  - 新增原生真机 Runner [`scripts/pixel3_e2e_runner.py`](file:///Users/zw-mini/orca/artemis/scripts/pixel3_e2e_runner.py)，通过 `artemis.main run --profile flash` 驱动 Pixel 3（`89FX09M9U`）执行真实任务 `"Open Settings and check Battery level"`，并直接从 `traces/data_engine.db` 提取真实指标；
  - 执行命令：`uv run python scripts/run_benchmark_comparison.py --mode e2e --runs 5 --max-cost-usd 2.0 --runner-spec scripts.pixel3_e2e_runner:run_pixel3_benchmark_iteration --json`
  - **六维对比报告全部 `PASS`**（详表落盘于 `.benchmark/diff_report_e2e_1794583213.md`）：
    1. **Task Success Rate (TSR)**：`1.0` vs `1.0`（5/5 成功，Ratio `1.0`）
    2. **Step Latency (P50 / P90)**：Baseline P50 `18.95s` / P90 `23.11s` vs Target P50 `6.43s` / P90 `6.66s`（**P90 提速 `-71.20%`**）
    3. **Cost Efficiency**：Baseline `$0.195197` vs Target `$0.010180`（**降本 `-94.78%`**，DeepSeek 缓存命中约 68%）
    4. **Visual Grounding / Action Hit**：`1.0` vs `1.0`（5/5 命中）
    5. **Fault Recovery**：`1.0` vs `1.0`（5/5 零异常）
    6. **Video Consistency**：`1.0` vs `1.0`（5/5 `recording.mp4` 与视觉摘要完整对齐）
- **覆盖边界披露**：本次真机任务（设置与电池）由 Accessibility UI 树直接定位命中，主要实测验证了 `deepseek-flash` 主脑规划与后台记忆摘要全链路（零 Google 调用）；`Qwen/Qwen3.8-27B` 视觉定位器已通过合成图 0 误差校准探针，如后续需补测无 UI 树覆盖的纯视觉界面（如 WebView/Canvas/游戏场景），可另行追加纯视觉回退专项跑批。
