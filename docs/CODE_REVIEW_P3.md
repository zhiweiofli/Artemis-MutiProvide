# P3 独立审查：REWORK

本轮业务裁决 **REWORK**；Standards 与 Spec 均不通过，不能进入 P4 验收。必跑命令虽全部返回 0，但真实预设、视觉定位与验证工具仍存在当前范围内的材料性缺陷。生命周期审查已完成，业务通过与生命周期成功分开记录。

## 证据与审查边界

- FACT：先读取 CURRENT.json，再核对 round-0/TASK.md；原任务 SHA-256 为 `8285b5559289d897b6d925642d14a37600dcca633c5336be72b800be4c5d3744`。本轮 CANDIDATE.json 指定 P2 candidate-source.json 为候选、P2 round-0/TASK.md 为验收输入。
- 候选摘要 `4c5f09c997273ee4f4143ba27e1d0572de128c6ffa2dd2b673e873d4108dbb9f`；验收摘要 `3739f889646a3038d5d78ffe2d34332844666207a51518186ffffff90b1f5972`。18 个业务源文件均与冻结清单一致，结论针对该候选。
- 固定比较点为工作树 HEAD `351ca8422f7b5b54e80a9c1ce03a222e02415b6b`，P2 BUSINESS_BASELINE 中已有文件均与该 HEAD 相符。候选为未提交工作树，故使用冻结 candidate.diff 和 candidate-source.json，而非会漏掉未提交内容的三点分支 diff；没有 P2 提交列表。candidate.diff 摘要见 reviewer-integrity.json。
- 规范来源：AGENTS.md（含用户注入的 Decision Discipline 等规则）、CONTRIBUTING.md、规格 v1.1、ADR-001～007、P2/P3 冻结任务；未发现额外 CODING_STANDARDS.md。Fowler smell baseline 作为判断性启发；未将非材料性命名或抽象建议列为阻断项。
- 用户要求“自己完成、无子代理”，因此亲自分别执行两个轴，未采用 code-review 技能的并行子代理步骤；相对 P2 Worker 是独立会话、独立 Code Agent、独立模型。
- FACT：`uv run python scripts/gate.py --level L4 --phase P2-GREEN --json` 退出 **0**，37 passed；`uv run pytest tests/unit/test_third_party_boundary.py -q` 退出 **0**，321 passed。日志为`.fabric/runs/run-t0C4y7/p3-final-review/round-0/` 下的 reviewer-gate.json、reviewer-boundary.log。
- FACT：FROZEN_TESTS 的三个契约文件及 TEST_TREE_BASELINE 的 248 个测试/夹具摘要全部匹配，未发现 P2 篡改或弱化断言。核对结果见 reviewer-integrity.json。
- FACT：按 CONTRIBUTING.md 补跑 `make test` 返回 2（pytest：86 failed、2455 passed、7 skipped、8 deselected）；`make lint` 返回 2，停在格式检查（13 文件，含候选业务文件及冻结测试/既有文档，后续 ruff check/quality_ratchet 未执行）；`make typecheck` 返回 0（0 errors）。日志分别为 reviewer-make-test.log、reviewer-make-lint.log、reviewer-make-typecheck.log。工具已覆盖的格式问题不重复列为手工 finding。
- FACT：用 `git archive HEAD` 在一次性临时目录、同一 Python 解释器复跑四项代表测试：Explorer 原生引擎测试 HEAD 通过、候选失败（新增 provider 检查遇到未声明 provider 的 MagicMock）；摘要、Flash 初始化、视频三项 HEAD 也失败（缺 Key / mock provider），故不能把全部 86 失败归因于本候选。该样本没有改业务或测试，日志为 reviewer-head-sample.log/json；其余完整套件失败的基线归因未逐项穷尽。当前完整确定性套件不是绿色，需 controller 区分既有宿主/测试夹具问题和新行为，并按冻结契约处理，不能声称全套回归通过。
- 所有新增复现仅在 reviewer_repros.py / reviewer-repros.json 内产生负向审查证据；无真实 API、设备调用，也未写入 `.artemis/capabilities.json` 或 `.benchmark/`。命令：`uv run python .fabric/runs/run-t0C4y7/p3-final-review/round-0/reviewer_repros.py`，退出 0。

## Standards

1. **STD-01 / P1：未测量结果被写成成功证据。** `scripts/probe_capabilities.py:119` 的 live 分支直接写五项 verified；`scripts/run_benchmark_comparison.py:36,72` 直接返回固定指标/PASS。违反 AGENTS.md:22 的可观察证据原则及 :27 的禁止伪造验证要求。虚拟 Key、零网络即 verified；runs=0、预算=0 仍 PASS。对应 SPEC-06、07。
2. **STD-02 / P1：P-003 未落实到全部截图节点。** `third_party/mobile_use/config/llm.py:80` 仅 lower，调用方传 ObjectDetector 等名称，无法匹配 snake_case 集合；`artemis/services/llm.py:937` 又丢弃 is_multimodal。主备纯文本配置均可通过并继续接收截图。对应 SPEC-03、04。
3. **STD-03 / P1：坐标回退能力存在退化。** `artemis/agents/object_detector/object_detector.py:115` 令旧模板优先于声明式格式，实际 Qwen 请求仍为 Gemini `[y,x]` 指令，随后按像素 `[x,y]` 解释。违反 P-001/P-008 的核心视觉能力保全目标。对应 SPEC-02。
4. **STD-04 / P1：供应商中立与可靠降级不完整。** `artemis/services/llm.py:1001` 吞掉非 Google get_llm 构造错误，之后 :1031 强制选 Google；纯非 Google 上下文仍可能回到 Google，违反 P-002/P-004。对应 SPEC-05。
5. **STD-05 / P2：保护基线与看板证据门禁失真。** `scripts/gate.py:133` 跳过实际基线全部非测试条目；:337 仅 L1 通过也可标记 P2 DONE，且忽略编译失败。违反 AGENTS.md:86、:96。对应 SPEC-08、09。

P-005 的工具推荐、P-006 的先验 Red 及测试冻结、P-007 的文本节点路由方向均已检查；未发现需要另列的当前候选材料性违规。实际端点能力和成本仍未测量，不能据此断言满足 P-007/P-008。

## Spec

1. **SPEC-01 / P1 / B1、B2：真实非 Google 预设不能启动。** `artemis/config/llm.py:231-244` 在剔除顶层厂商模型、应用 preset.nodes 前先 `_check_leak`。实读 config/artemis.jsonc，hybrid/pure 都因旧顶层 object_detector 的 Gemini 模型抛 ValueError。§2.5 要求“preset.nodes 对节点模型定义具有完全覆盖权”。应先选择有效覆盖，再校验实际生效模型；复验真实文件的三预设均可加载，同时保留真正的跨厂商错配拒绝测试。
2. **SPEC-02 / P1 / B6：实际模板覆盖格式分派。** `object_detector.py:115-118` 与未改的 object_detector.json:8；Explorer/工具把旧 instructions 拼入 templates 后，Qwen 仍被要求输出 `[y,x]` 千分位。按该指令返回 [500,250] 时，在 1080×2400 图上被解释为 [463,104]，应为 [250,500]。§5.2 要求“Prompt 按 coord_format 分派”。应使真实模板加载路径与主备格式一致，复验 Explorer/工具路径发出的 Qwen bbox 指令及 Google fallback 指令。
3. **SPEC-03 / P1 / B3：多词节点漏过启动期模态保护。** `third_party/mobile_use/config/llm.py:80-81,168-170`，`artemis/config/llm.py:105,112,117`；ObjectDetector/VideoAnalyzer/OperatorSummarizer/DiagnoserExpert 等命名与集合不一致。§2.3 要求主备均在启动期拒绝纯文本。复现这四节点的主/备共八种 is_multimodal=False 全被接受。应使用统一节点标识，补验所有集合节点及 fallback。
4. **SPEC-04 / P1 / B3、B4：新增配置字段未传至统一端点。** `artemis/services/llm.py:937-947` 未传 api_base、is_multimodal、coord_format、structured_output_method。§2.3、§4.1、§4.3 要求这些声明生效；配置 json_mode/自定义 URL 实际变成 None，文本能力变 True，Detector endpoint 格式也为 None。Detector 从 cfg 再读格式仅局部掩盖问题。应补齐主备解析，复验通过 get_llm 的底层 URL 与结构化 method，而非仅手工构造 ModelEndpoint。
5. **SPEC-05 / P1 / B2：后台服务错误路径重新选 Google。** `artemis/services/llm.py:995-1012,1031-1036`；非 Google node 遇构造异常被吞掉，默认 gemini-* 字符串随后触发 GOOGLE 分支。§3.1 要求此类默认字符串委托当前非 Google 节点；复现捕获 provider=google。应传播原错误或使用已配置备用端点，验证默认模型的故障路径不构造 Google 客户端。
6. **SPEC-06 / P1：五项探针未实现。** `scripts/probe_capabilities.py:78-150` 只检测 Key 是否非空，未调用模型或图像生成器，便产出 live/verified。§6.1 要求真实可达性、视觉、三协议、流式 usage、合成图校准。应执行并记录可复核探测；缺依赖/无 Key/失败须明确未验证或失败。虚拟 Key 且禁止网络应绝不 verified。
7. **SPEC-07 / P1：基准脚本输出常量且无预算护栏。** `scripts/run_benchmark_comparison.py:36-96` 无标注集、故障注入、设备或采样，offline/e2e 直接 PASS；runs=0 与 budget=0 也接受且声称 cost=0.45。§6.3 要求六维实测、N≥5 与预算熔断。应从实际离线用例/配对跑批计算指标，缺条件不得输出成功；复验样本改变影响结果、不足五次拒绝、预算触发熔断。
8. **SPEC-08 / P2：L3 基线检查不工作。** `scripts/gate.py:125-140` 只查 tests/，但实际 baseline.json 的 files 是非测试路径到摘要字符串，故全部跳过；删除文件也不报错。§6.2 要求检查基线中未授权文件。临时基线 README 被改仍 passed=True。应按真实格式和授权范围核验，缺失/变更未授权条目须失败，并使用冻结测试清单保护契约。
9. **SPEC-09 / P2：门禁同步只会向绿、不能保证真实状态。** `scripts/gate.py:194,224,337-349` 仅 P2 成功时做字符串替换；失败/P3/P4 不刷新，L1 成功也会宣布 P2 DONE，编译失败不影响退出码。§6.2/AGENTS §4 要求“每次”根据实测报告刷新。实跑虽编译成功，board 的 L4 行和 HTML 引言仍写“37 项尚未转绿/准备实施”。应由完整报告驱动各层状态、限制完成所需层级，并将同步失败计入门禁；验证成功→失败、低层级、各 phase、编译失败路径。

## B1–B7 核对结论

| 项 | 当前结论 | 依据 |
|---|---|---|
| B1 | 未消解 | SPEC-01，真实预设失败 |
| B2 | 未消解 | SPEC-01、05；主流程调用点已改，但错误路径仍选 Google |
| B3 | 部分 | 402 立即 fallback 与拓扑存在；SPEC-03、04 漏模态保护 |
| B4 | 部分 | DeepSeek/Qwen 默认 function_calling 测试通过；SPEC-04 显式覆盖丢失 |
| B5 | 确定性测试通过，真实端点未验证 | 专属凭据/URL、stream_usage/max_retries、缓存计量通过；SPEC-06 禁止用假探针补证 |
| B6 | 未消解 | 五格式纯函数通过；SPEC-02 真实提示词仍冲突 |
| B7 | 确定性路径通过，真实时延未验证 | T-12 覆盖 503/Timeout、备用格式及 detected/failed 互斥；cfg.timeout 与 with_fallback 已接入 |

原有 Google 原生引擎依 ADR-001 保留；未将预先存在的 SDK 类型导入或可选原生分支误报为新增后门。新增错误路径 SPEC-05 仍需修复，故不能声称“无遗留 Google 后门”。

## 待修项与未验证后续

以上 SPEC-01～09 均为当前候选可修复问题，不是需要扩大产品范围的建议。Worker 应修业务与脚本，并通过协调器按冻结测试规则追加验证材料；Reviewer 未修改业务源码、冻结测试、任务或 Worker DELIVERY。

五层报告：**L1** doctor healthy；**L2** 六项 SKILL.md 就绪（未独立逐文件重验技能包完整性）；**L3** Python 3.14.3、相关依赖可导入，但基线检查缺陷见 SPEC-08；**L4** 必跑 37+321 测试全绿，完整确定性套件 86 失败，且负向复现证明目标行为仍不完整；**L5** 报告/摘要可接手，真实端点、真机闭环、六维基准与用户接受未完成。没有运行费用性 API 或设备任务。

本轮 gate 确实重新编译看板；文档、Archify 源和 HTML 内容摘要与 P2 交付记录相同，HTML 摘要也与 CANDIDATE.json 冻结值相同，build receipt 见 reviewer-gate.json，生成物及构建回执摘要见 reviewer-artifact-hashes.json。同步存在不实陈述，见 SPEC-09；当前 P3 REWORK 及 HANDOFF/看板终态应由 controller 在接收审查后按其权限同步，不应标记 P3 已通过或 P4 可启动。

独立性：Reviewer 会话 `01a1c3fe-fa2e-72f3-bf7e-6c48ba03bdbe`，codex-tui / openai / `gpt-6.1-sol` / high，来自当前 session_meta、turn_context；Worker 是 antigravity / gemini-3.8-flash / 不同 session。见 reviewer-identity.json。

Standards：5 项（最高 P1）；Spec：9 项（7 项 P1、2 项 P2，最严重涉及真实预设、定位与伪成功证据）；两轴分别失败，不互相抵消。
