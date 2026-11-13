# P3 round-4 独立审查：REWORK

**Standards：REWORK；Spec：REWORK。** 本轮是 P2 第5次业务审查；已按用户收敛策略逐项评估，保留的意见均影响验收正确性或当前必需预算/故障注入行为，不能降为非阻断。必跑确定性检查全部通过，原反例多数已修，但基准脚本仍有可复现的缺测 PASS 与预算放行漏洞。审查生命周期完成不等于业务 PASS。

## 证据与冻结边界

- FACT：先读 CURRENT.json，再读其指定 round-4/TASK.md；本轮 TASK SHA-256 `f22defc6dad63b80b6f810130c08f5677f86a64c111d745d5b9ee4643e1f25b9`，原任务 SHA-256 `8285b5559289d897b6d925642d14a37600dcca633c5336be72b800be4c5d3744`，均匹配。读取本轮完整累积目标、P2 round-4 TASK/DELIVERY、Spec v1.1、ADR、前轮审查及复现材料；旧轮结论仅作缺陷追踪。
- 当前 delivery.json 最新候选为 P2 round-4/candidate-source.json，SHA-256 **`a0252b897a525c69d2726e422977cbb3d58b272619d8701ff4cc0136f0c2f71f`**；验收输入 P2 round-4/TASK.md，SHA-256 **`44f210f10f7cdce23601ada2d65d82d34b10a8ed1f0bc2a240c84739eb700921`**。18个业务文件及只读快照在审查前后全部匹配；相对 round-3 只有 `scripts/run_benchmark_comparison.py` 变化。见 reviewer-integrity.json、reviewer-final-audit.json。
- FACT：248个测试/fixture的内容摘要与实际文件集合均匹配，无新增、删除或修改；三份 P1 冻结契约摘要匹配，未弱化断言。已核对 .agent/baseline.json 覆盖；真实 gate 验证未授权 baseline 文件。按18文件白名单保存 `git diff 95a5245 -- <paths>` 与 `git diff 351ca84 -- <paths>`，没有混入后续技能/文档提交，也没有漏掉未提交候选。
- Standards 来源：AGENTS.md P-001～P-008、宪法及验证门禁、CONTRIBUTING.md；Spec 来源：docs/TECHNICAL_SPEC_DEEPSEEK_QWEN.md v1.1、docs/ARCHITECTURE_DECISIONS.md ADR-001～007与本轮累积验收。Fowler smell仅作启发，未新增可选风格或结构阻断。
- 使用 fabric-reviewer、matt-code-review、Orca orchestration 技能；按明确任务约束亲自分别审查两轴，无子代理。仅写本轮报告/日志与 docs/CODE_REVIEW_P3.md，另运行授权 gate 自动刷新衍生看板/HTML；未改产品、测试、任务、Worker交付、controller决策、预算或配置，未 commit/amend/reset/push。
- 独立性 FACT：原生 worker_dispatches 的 launch.effective 为 **codex / gpt-6.1-sol / high**；唯一 Dispatch `ctx_bd12e41672bb` 对应 Codex session **`01a1c8c7-da7d-72a0-be8e-764e9f89e5df`**，原生 threads、session_meta与turn_context一致。P2 Worker为 antigravity / gemini-4-argon / 另一会话；本轮保存身份元数据，未保存会话正文。见 reviewer-native-launch.json、reviewer-identity.json。

## 实跑验证

测试环境显式设置 `GEMINI_API_KEY=dummy-test-key GOOGLE_API_KEY=dummy-test-key`。完整命令、退出码与日志保存在本轮 reviewer-*.exit.json / .log；未调用付费云API或设备。

| 检查 | 退出码 | 实测证据 |
|---|---:|---|
| `uv run python scripts/gate.py --level L4 --phase P2-GREEN --json --frozen-tests .fabric/runs/run-t0C4y7/p1-red-tests/FROZEN_TESTS.json --test-tree-baseline .fabric/runs/run-t0C4y7/p2-green-impl/round-0/TEST_TREE_BASELINE.json` | 0 | L1～L4通过，37 passed；reviewer-gate-bound.log |
| `uv run pytest tests/unit/test_third_party_boundary.py -q` | 0 | 321 passed；reviewer-boundary.log |
| `node .agents/skills/workbench-project/scripts/check.mjs doctor .` | 0 | healthy；reviewer-doctor.log |
| 占位Key `make test`，未另加筛选 | 0 | **2541 passed、7 skipped、8 deselected**；reviewer-make-test.log |
| paired-head-results.json 原15项 Explorer selector | 0 | **15 passed**；reviewer-explorer-15.log |
| `make typecheck` | 0 | 0 errors/warnings/informations；reviewer-typecheck.log |
| `uv run python scripts/quality_ratchet.py` | 0 | silent_broad_exception_handlers=0；reviewer-quality-ratchet.log |
| `uv run ruff check <16个Python业务文件>` | 0 | All checks passed；reviewer-ruff-check.log |
| `uv run ruff format --check <同上>` | 0 | 16 files already formatted；reviewer-ruff-format.log |
| `uv run python .fabric/runs/run-t0C4y7/p3-final-review/round-4/reviewer_reused_controls.py` | 0 | 已检查的 Worker round-4控制脚本副本；round4-controls-results.json |
| `uv run python .fabric/runs/run-t0C4y7/p3-final-review/round-4/reviewer_extra_controls.py` | 0 | Reviewer独立反证及正向控制；reviewer-extra-controls.json |
| `uv run python .fabric/runs/run-t0C4y7/p3-final-review/round-4/reviewer_final_audit.py` | 0 | 18业务文件、248+3冻结文件及实际制品复核 |

最后两类控制的退出0只表示断言与观测相符，**包含成功复现剩余缺陷，不代表候选PASS**。extra控制首跑有一条对所有请求都不应stream的过宽断言失败；畸形JSON场景确实使用stream，修正为只核实“流中断”场景，首跑日志保留为 reviewer-extra-controls.first-attempt.log。未为此修改候选或冻结测试。

复用控制覆盖真实三个预设、22种截图节点主备模态拒绝、get_llm端点字段的真实HTTP序列化、非Google错误传播、Detector主备格式、probe用量16/16和606/606及预算停止、误差40拒绝、无Key/未知usage不伪verified、gate清单保护及各phase/低层级/成功失败/编译失败同步。正向使用实际项目函数、ChatOpenAI/OpenAI/httpx解析链和生产恢复函数，仅以隔离transport、runner、合成观测或临时根替换外部状态；未把它们标为真实云端、设备或生产基准FACT。

## Standards（1项P1，REWORK）

**STD-01：未观测或未执行的验收证据仍被标为 verified/PASS。** `scripts/run_benchmark_comparison.py:84-90,264-269,321-322,466-469`：未知usage变成0美元并报告100%降本；无时序真值与预测，仅两项标量准确率也可使六维整体PASS；名为流中断的场景实际是在非流式请求返回响应前抛超时。独立反例详见SPEC-07A。违反 AGENTS.md §1 第4项“可观察证据优先”与第6项禁止伪造通过结果的要求；这里评价输出证据的真实性，不推断作者意图。**blocking=true；impact：当前必需基准验收正确性。**

P-001：完整确定性套件、15项Explorer回归与定位主备控制通过，未发现新的移动闭环退化，未做真机验证。P-002：指定业务调用点经中立工厂；非Google构造错误不调用Google，Explorer显式非Google走通用引擎；ADR-001允许的Google原生基线未误报后门。P-003/P-004：11个截图节点主备22项拒绝、402/503/Timeout与备用格式契约通过。P-005/P-006：冻结先验契约和TDD红绿材料可追溯，测试未变；本轮无Test Dispute。P-007/P-008的生产质量/费用仍需后续实测，不能用当前基准PASS代证。

## Spec（2组P1，REWORK）

### SPEC-07A：缺测与未执行场景仍可被认证

规格§6.3要求六维离线标注/故障注入评估；ADR-004第3、5、6项要求按usage计价、真实流中断恢复、与人工时序真值对照。本轮P2验收明确“缺真值保持UNVERIFIED”“缺观测不得补绿”“真正注入流中断”。

1. **未知usage被当作免费观测。** 位置 `scripts/run_benchmark_comparison.py:84-90,1075-1082`，共享六维路径另见`:605-614`。在完整好样本上只删除 `target_cost_usd` 并提供 `target_usage={}`，总体验收仍 **PASS**，cost维度为 `verified`、目标成本 **0.0**、降本 **100%**。换成 `{'unrecognized_field':123}` 也PASS。FACT见 reviewer-extra-controls.json 的 empty_usage/unrecognized_usage。INFERENCE：接入缺usage的真实跑批会被错误认证为达成成本目标。应区分无usage与明确测得0，保留None/unverified；验证空、不认识/不完整usage拒绝，完整计量或明确成本仍正确比较。**blocking=true；impact：费用指标及总体验收正确性。**
2. **离线视频标量绕过真值。** 位置`:224-272`，尤其`:264-269`。从完整样本删除 temporal_ground_truth、baseline_video_pred、target_video_pred，仅给 baseline_video_accuracy=1.0 / video_accuracy=1.0，视频仍 `verified`、准确率1.0、整体 **PASS**。FACT见 video_scores_without_truth；正常带真值好样本PASS，错序预测FAIL。应要求离线路径具备可复核的时序真值与预测（或明确可核对的真值评估证据），缺失则UNVERIFIED，不能仅凭任意准确率字段跳过本轮明确的真值要求。**blocking=true；impact：视频维及总体验收正确性，当前必需验收。**
3. **“流中断”尚未实际注入。** 位置`:300,321-322,466-469`。新增控制观测10次实际transport请求；stream_interruption_timeout对应第7次请求的 `stream=false`，handler直接抛ReadTimeout，尚未返回任何响应或chunk；报告仍计该场景 recovered=true。另2次stream请求来自畸形JSON场景，不能代替中途断流。与生产with_fallback连接及429/402/503/坏JSON恢复已真实实现；剩余的是在接收有效chunk后抛错、运行生产流式恢复消费路径并验证终态，不能用调用前超时代表。**blocking=true；impact：当前明确要求的流中断恢复验收覆盖与证据正确性，不是可选网络加固。**

原来的“仅定位输入六维PASS”和“关闭恢复链仍100%”已修：当前仅定位UNVERIFIED；删除六维任意一维均UNVERIFIED；完整好样本PASS、坏样本FAIL；禁用with_fallback实际调用5次且恢复率0/整体FAIL。以上剩余问题可在原脚本内用本地控制修复，无需提前完成真实P4跑批。

### SPEC-07B：预算合同仍可因参数个数或估算属性而被错误授予

规格§6.3要求`--max-cost-usd`预算熔断；本轮P2明确只有显式单次最大成本或真正传入可执行剩余预算约束才能启动。

- **第四个普通参数误认预算护栏。** 位置 `scripts/run_benchmark_comparison.py:1224-1235,1269-1289`。独立runner签名 `device_runner(run_idx, baseline_preset, target_preset, device=None)`，未声明最大成本/预算约束；检查因 `len(pos_params)>=4` 得到 accepts_budget_constraint=true。实际 invoker 走已知关键字分支，只传前三项，device仍None，**没有传入预算**。0.10美元预算下该runner仍执行1次并报告成本 **1.00美元**，随后才熔断。FACT见 fourth_parameter_contract/fourth_parameter_calls/fourth_parameter_budget_bypass。这是正常额外设备参数即可触发的放行，无需runner谎报或违反已声明合同。
- **估算被当作最大成本。** 位置`:65-80`。无最大成本/预算参数的runner只设 `estimated_cost_usd=.01`，代码把estimate视作provable reserve；0.10预算下执行1次、实测成本1.00，invoker同样没有传入任何预算。FACT见 estimate_budget_bypass/estimate_calls。期望成本不是最大成本合同。
- **已修 FACT**：普通未声明`**kwargs`昂贵runner在0.01/0.03/0.10预算均执行0次；显式最大成本1.0在0.10下执行0次；显式remaining_budget_usd加`**kwargs`收到真实预算；RuntimeError/空或缺成本后停止且保留unknown；内部TypeError仅调用一次；正确五次配对观测仍PASS。
- **修复/验证**：只接受语义明确的最大成本或实际传入的预算参数/已明确的可执行协议，合同判定必须与最终invoker一致；不从一般参数个数或estimate推断安全。复验两个0.10反例均执行0次，并保留合法预算签名、未知成本停止和正确配对控制。
- **blocking=true；impact：费用护栏正确性，允许在调用者预算之外启动实际费用性工作；属于当前必需验收。** 未发现它直接改变移动端核心循环，但不能因此降为非阻断。

## 已修项与B1～B7复核

| 项 | 本轮结论 | 证据 |
|---|---|---|
| SPEC-01 / B1 | 保持已修 | 真实三个预设resolve/expand/LLMConfig通过，冻结优先级/未知预设/兼容契约绿 |
| SPEC-02 / B6 | 保持已修 | 真实templates+instructions、两方向主备格式均返回[375,688]；五格式/异常框契约绿 |
| SPEC-03 / B3 | 保持已修 | 全部11截图节点×主备22项纯文本启动拒绝 |
| SPEC-04 / B4 | 保持已修 | get_llm→实际工厂/HTTP请求保留URL/json_mode/coord_format/is_multimodal |
| SPEC-05 / B2 | 保持已修 | 非Google None/旧gemini字符串错误传播，Google factory调用0；15项Explorer绿 |
| B5 / B7 | 确定性路径通过 | 专属Key/URL、stream_usage、SDK零重试、缓存/402与Detector503/Timeout/备用格式契约绿 |
| SPEC-06 | 保持已修 | 16/16正向usage、606/606越预算及时停止，误差40拒绝；未知usage/无Key/阻断transport不伪verified |
| SPEC-08 | 保持已修 | gate不硬编码Run，未绑定清单/篡改删测试/缺清单/改README/缺baseline均拒绝；真实248+3保护通过 |
| SPEC-09 | 保持已修 | 实际L4行合法5列且37 passed；各phase、低层级、连续成功失败及编译失败同步控制通过；P3/P4不由单测授予DONE |

B1～B7业务确定性路径通过不替代SPEC-07测量逻辑或P4真实网络/设备证据。

## 第5次收敛、制品与后续边界

- 按 AGENTS.md §3.3，逐项核查以上剩余意见：未知费用/无真值PASS、未测试流中断却认证、无预算合同仍调用，均涉及**正确性或当前必需验收**，故保留阻断；没有把非核心风格意见作为REWORK理由，也没有为通过而减少验收。没有另加架构决定或Test Dispute；不负责擅自扩大返工/时间预算或切换模型，后续由controller裁决。
- 实际bound gate的finalize回执为 validate/deliver/check全部pass、quality=showcase；browser-check未运行。人工检查实际 docs/TASK_BOARD.md:78 的L4为合法5列、37项通过，Archify源和HTML包含37 passed；P4在两板均BLOCKED。最终HTML SHA-256 **`a70627315131c7cb26b260d2c617ae5c03ce10e94746cf0daedb204fd8fe682c`**；Archify源 **`685430d2e3f67ce6ad388a567aff186c7358d325c2930a5cc112197517cdff89`**；TASK_BOARD **`193274f0dd078c6c78fc2ba759041fed3e2be41871ca1833d32dec0e69e7319f`**。实际构建/检查回执及其摘要见 reviewer-gate-bound.log、reviewer-final-audit.json。
- **L1** doctor healthy；**L2**六份原子Skill入口存在（未逐文件审计全部技能包）；**L3**Python3.14.3/uv依赖可用，baseline与248+3冻结保护绿；**L4**37+321、完整2541及15项回归、类型/质量/格式全绿，但SPEC-07正确性仍阻止业务接受；**L5**本轮报告/JSON/控制与PROJECT-MAP/HANDOFF入口可被新会话复核，真实云端、真机闭环、生产六维数据和用户接受未验证。
- 当前gate衍生P2 DONE/P3 READY仅代表单测门禁通过，不能覆盖独立审查REWORK。按本轮写入权限，Reviewer不改HANDOFF或controller阶段终态；controller接收报告后负责记录最终P3裁决并同步HANDOFF/阶段看板。所有旧轮Task/Dispatch/候选/审查历史保留，未重置第5次计数。

**Standards：1组P1（证据真实性）；Spec：2组P1（基准缺测/流中断认证、预算合同）。两轴分别REWORK，审查生命周期成功完成。**
