# Artemis 优化方案交接（供独立审查）

- 编写时间：2026-11-15
- 编写者：Alma（调度 + 观察者）
- 审查对象：**本文档提出的每一项优化方案**
- 证据来源：`docs/analysis/{COST,RELIABILITY,ACCURACY}.md`、`traces/qa_1114*/`、`traces/data_engine.db`
- 被测系统：Artemis Flash Profile（deepseek-flash 决策 + Qwen3-VL-30B-A3B-Instruct 视觉），Pixel 3 `89FX09M9U`

---

## 0. 给审查者的指令

请不要客气。你的任务是**推翻**，不是背书。对本文档每一条：

1. 对照代码/数据核实事实陈述，标记 `VERIFIED` / `UNVERIFIED` / `WRONG`；
2. 判断方案与 Artemis 现有约束（见 §2）是否冲突；
3. 指出方案本身的副作用、更简单的替代方案、或遗漏的更优解；
4. 给出你自己的优先级排序，允许与本文档不同。

输出写到 `docs/analysis/REVIEW_OF_HANDOFF.md`。若某条你没有证据，明确写「无法核实」，不要猜测。

---

## 0.5 修订记录（v2，2026-11-15，依独立审查）

独立审查见 `docs/analysis/REVIEW_OF_HANDOFF.md`。以下条目**已按审查修正，不要按旧版执行**：

| 条目 | 原方案 | 修正后 |
|---|---|---|
| **B2** Gemini fallback | 改 `validate_providers`/预热逻辑 | **否决原方案**。`ds-qwen-pure`（`config/artemis.jsonc:129`）已是零 Google 预设，空 key 实测可解析成功。问题是**队列选了 hybrid**（`qa_1114_queue.py:37`）→ 改为切预设 + 补 T-04 风格回归 |
| **D2** wakelock | 重写唤醒机制 | **否决原方案**。失败的 `set-wakelock` 是 `awake_service.py:100` 的 legacy 清理；主路径 `:105 svc power stayon usb` 已生效，仅验证谓词过严（要求 `mStayOn=true`）才降级 5s 心跳，而**心跳有效** |
| **B1** 错误分类 | 递归 `__cause__` 提取状态码 | **该修法无效**（异常链为空）。改为「status_code 优先 + 字符串数字 + `str(error)` 正则」 |
| **D4** 空树索引 | 增加可读错误 | **方案冗余**（现已在点击前抛错）。改为「抛错时刷新树 + 同索引连续失败 3 次封锁」 |
| **C2** 时间兜底 | 列为待改 P0 | **已生效**（v2 队列 2400s→TIMEOUT），改为「确认产品侧默认模板同步」 |
| **A1** 结构化断言 | 改提示词 | 落点改为 **tool schema + `_finalize_task_report` 硬门** |
| 录像体积 | 72 个 mp4 共 10.6 GB | **实为 ≈27.6 GiB**：mp4 10.61 + **mkv 17.0 GiB**（2 个超大文件） |
| 新增 | — | **L1 隐私/取证、L2 E阶段 UNKNOWN→PASS、L3 1×1 帧校验、L4 判据 golden set、L5 clean配置止血、L6 截图降采样**（见审查报告 §4） |

### 0.6 S0 实施记录（2026-11-15，六项全部完成）

| 项 | commit | 实际改动位置 | 验收证据 |
|---|---|---|---|
| C3 前台包名 | `a6df5e4` | 新增 `artemis/agents/flash/preflight.py`；`artemis/agents/flash/runner.py` `run()` 首行；`scripts/qa_1114_queue.py` 传 `--locked-app` | 真机：Settings 在前台时 runner 拒绝开跑（`Refusing to start: Foreground package mismatch...`），0 张截图、0 次 LLM 调用、trace `foreground_check` 落库 |
| L1 录像 | `18a036c` | `config/artemis.jsonc`（两处 `video_analyzer.enabled=false`）；`artemis/sdk/builders/agent_config_builder.py`（未配置不再 auto-detect）；`build_scrcpy_record_command(time_limit_s=)`；`unified_controller` 每段 `--time-limit` + `MAX_RECORDING_SESSION_SECONDS`；新增 `artemis/runtime/orphan_recordings.py` | 一轮 BC+D 新增 27 张截图 7.6 MB、0 个 mkv；真实孤儿 scrcpy（ppid=1）被 `reap_orphan_recordings` 杀掉 |
| L3 帧校验 | `761fdd2` | `artemis/drivers/android/adb_driver.py`（去 1×1 占位图，重取一次后抛错）；`artemis/services/llm.py` `unusable_image_reason` + `_reject_degenerate_images` | 单测：1×1 帧被拦、模型 0 次调用、不产 fallback；≤31px 拒绝；1080×2160 放行；单色放行仅告警 |
| A1 报告硬门 | `4ba64ab` | `artemis/agents/validator/tool_declarations.py`（`report_task_status_tool(require_checks)`）；`artemis/agents/flash/runner.py` `_gate_report` + `_finalize_task_report`；`scripts/qa_1114_queue.py`（D 阶段开关、`[REPORT_GATE]` 优先、`completed≠PASS`） | 单测：只回 NO → FAIL；evidence 空 → INCONCLUSIVE；全 YES+证据 → PASS；开关关 → 原样透传。真机 D 阶段 `gate=PASS` 未误伤 |
| B1 状态码 | `34b29be` | `artemis/llm/reliability.py` `extract_status_code` | 真实 `openai.BadRequestError`（`.code='invalid_request_error'`）→ `BAD_REQUEST`；1 次尝试后抛 `LLMPermanentError`，无 pause |
| L2 UNKNOWN≠PASS | `50f5d9e` | `scripts/qa_1114_queue.py` `e_phase_verdict` | 无 `result=` 的 E 报告 → `INCONCLUSIVE` |

**与原方案的偏离**（均已在实现前确认）：

1. **A1 落点**：硬门做成按任务开关（`ARTEMIS_FLASH_REPORT_CHECKS=1`），不是全局生效 —— 三项检查是游戏 QA 专属，且全局生效会让 `test_flash_runner_ledger.py:443/626`、`test_flash_runner.py:554` 三个受保护测试变红。开关放环境变量而非配置项：`artemis/config/agent.py` 在 gate L3 的 baseline 保护名单内且不在授权修改列表。
2. **A1 顺带修队列**：`verdict_of` 不再把 `status: completed` 判 PASS（上一轮 4 个 PASS 中 3 个靠这条），改为优先读 `[REPORT_GATE] verdict=`。
3. **L3 落点**：1×1 帧源头是 `adb_driver.py` 的硬编码占位图，不是 `accessibility_client.py:324`；校验放在截图产出点 + LLM 网关（而非 `object_detector`：`test_object_detector_coords.py:460` 受保护且用 1×1 PNG mock 模型，消费侧拦截会撞冻结测试）。
4. **L3 单色**：只告警不拦截 —— 历史 2271 张截图里有 4 张全分辨率纯黑/纯白加载帧（30 步），硬拦会让 BC 误判失败。
5. **L1 落点**：`recorder.py` 是死代码（无 import）；真实录制是 scrcpy（`unified_controller.start_video_recording`），改的是配置与 scrcpy 命令。孤儿主体是主机侧 scrcpy（8.7 GiB mkv 在宿主死后仍写约 10 小时），清理逻辑据此实现。
6. **L1 抓开关**：未配置 `video_analyzer.enabled` 时原本 auto-detect（装了 scrcpy 就开），改为视为关闭，保证「默认不录」不因环境变化而漂移。
7. **C3 期望包**：runner 不知道目标包（启动是模型在循环内调 `launch_app`），复用 `--locked-app`；SDK 侧启动失败只 warning 的问题未修（改 `third_party`，约束 4），由 runner 的前台校验兜住。

**待办（未在 S0 内）**：截图保留期（L1 后置项）、`adb_driver` 的 `1080×2400` 默认值（归 D1）、存量 30 GB traces 的清理策略（含旧录像，需单独决策）。

---

## 1. 背景：两天的真实运行数据

2026-11-14 ~ 11-15 共 4 轮、55+ 个 session，跑 5 款手游（九游新游首发/内测）的质检流程：BC 启动登录 → D 新手引导 → E 主界面巡检。

| 指标 | 实测值 | 来源 |
|---|---|---|
| 总成本 | $4.29（prompt 61.25M / completion 2.48M） | COST.md |
| 未命中输入占比 | **70%**（$3.01） | COST.md |
| 缓存命中率 | 67.5% | COST.md |
| 单款完整流程 | $0.41~1.1 | SUMMARY.md |
| 动作有效率（ham>8 严格口径） | **61.7%** | ACCURACY.md |
| 重复动作占比 | 30.9%（670/2167） | ACCURACY.md |
| 最长连续无变化 | **31 步 / 1.01M tokens** | ACCURACY.md |
| 20 次失败中「非游戏原因」 | **11 次（55%）** | RELIABILITY.md |
| 空树仍传索引点击 | 126 次（占索引点击 53%） | ACCURACY.md |

### 1.1 已由我方复核的事实（审查者可直接采信，但仍建议抽查）

| 事实 | 复核方式 | 结果 |
|---|---|---|
| 4 个 session 的 `end_time` 精确相同 | SQL `group by end_time having count(*)>1` | 确认：`1794662524.044246` 对应 4 个 session → 时长字段被批量改写，**不可用于统计** |
| `traces/` 体积 | `du -sh` + 全部视频求和 | **30 GB / 视频 ≈27.6 GiB**（mp4 72 个 10.61 + **mkv 2 个 17.0**），最大单文件 `qa1114_dasheng_BC/recording.mkv` 8.7 GiB |
| 错误分类代码已存在 | 读 `artemis/llm/reliability.py:85-118` | 400 已映射 `BAD_REQUEST`（non-retryable），**但实测走了 UNKNOWN 重试分支** |
| `extract_status_code` 只读两个属性 | 读 `reliability.py:68-74` | 只查 `error.code` / `error.status_code`，未递归 `__cause__` |

> ⚠️ 已知内部矛盾：RELIABILITY.md 用 `end_time` 算出「91.3% 墙钟被浪费」，但同文档证明 `end_time` 不可信。**该 91.3% 不采信**，审查者可忽略。

### 1.2 需要审查者重点挑战的前提

以下判断是本文档方案的基础，如果它们站不住，方案要重写：

- **P1**：本轮质检的假 PASS / 假 FAIL 主要来自「判据与运行时护栏缺失」，而不是模型能力不足。
- **P2**：成本大头是「不可缓存的尾部 + 每步截图」，不是历史 prompt 累积（因为缓存价 1/10）。
- **P3**：Qwen 视觉并非浪费（82.8% 触发在无 a11y 文本画面），但**调用后动作有效率 63.7% < 点击基线 66.2%**，说明当前触发时机/用法无增益。

---

## 2. 硬约束（违反即方案作废）

1. **不动冻结契约**：`tests/` 里 frozen contract 必须字节不变；`scripts/gate.py` L4 门槛需通过。
2. **不越第三方边界**：`third_party/mobile_use/**` 的修改需最小化并说明理由；优先在 `artemis/` 侧包装。
3. **厂商中立**：不得新增对 Google/Gemini 的硬依赖；fallback 必须同厂或显式置空。
4. **真机验收**：任何声称修复，必须在 Pixel 3 上跑真实游戏复现。
5. **不真付款**：测试中禁止点击最终支付，只允许拉起面板后截图返回。
6. **失败必须显式**：禁止用兜底默认值掩盖错误（如无设备时静默 fallback 1080×2400）。

---

## 3. 优化项

优先级：P0 = 直接消除错误结论或死等；P1 = 显著降本或提质；P2 = 工程卫生。
每项格式：**问题 → 证据 → 改动位置 → 方案 → 收益 → 风险 → 验收**。

### A. Prompt 层

#### A1 `[P0]` 判据从散文改为结构化断言
- **问题**：模型用自然语言汇报「满足条件 (a)」，无法机器校验；出现「入口可见」被当成「面板已弹出」。
- **证据**：第一轮 4 个 PASS 的验收③（面板真弹出）全部不成立；冲吧的报告自认「全程未触发任何充值面板」却仍判 PASS（ACCURACY.md §4）。
- **改动（已修正落点）**：`artemis/agents/validator/tool_declarations.py:275-296` 扩展 `report_task_status` schema + `artemis/agents/flash/runner.py:548-587` 的 `_finalize_task_report` 做硬门。**只改提示词等于白做**（当前服务端零校验）。
- **方案**：要求逐步输出固定结构
  ```
  CHECK_GUIDE_GONE=YES|NO  evidence=<画面文字/坐标>
  CHECK_ENTRY_VISIBLE=YES|NO evidence=...
  CHECK_PANEL_OPENED=YES|NO evidence=<面板标题/价格档位>
  ```
  任一 `NO` → `result=FAIL`；任一 `evidence` 为空 → `result=INCONCLUSIVE`（新增状态）。
- **收益**：把「结论可信度」从人肉核查变成可回放校验；消除「入口≠面板」类偷换。
- **风险**：结构化输出可能降低长程引导的灵活性；需确认 deepseek 在长上下文下能稳定遵守（见 A1 验收）。
- **验收**：构造 3 个已知场景（面板能弹/不能弹/入口都不在），断言 3/3 正确；连续 2 款真实游戏无格式违规。

#### A2 `[P0]` 禁止超长盲等
- **问题**：模型可单次 `wait_for_delay(240000)`，无上限；实测某 session 29 分钟里 24.5 分钟在盲等，设备三次自动睡眠。
- **证据**：ACCURACY.md 对「锁屏」事件的重判（3 段截图 ham 21/23/20/16，确为真锁屏）；RELIABILITY.md 记录最长合法静默 239.2s。
- **改动**：`artemis/mcp/action_executor.py`（或 wait 工具实现处）。
- **方案**：`wait_for_delay` 单次上限 60s；超过需拆成多次，且每次必须重新取帧确认状态；连续 3 次等待仍无变化 → 强制 FAIL。
- **收益**：消除设备自动睡眠引发的连环故障；降低无信息 token。
- **风险**：真实长加载（资源包 5 分钟）会被打断。缓解：白名单场景用「进度条检测」替代固定等待（见 A2b）。
- **A2b 建议**：新增 `wait_until(predicate, timeout)`，由 CV/文本判断进度（百分比文本、进度条 ROI），而不是固定睡眠。
- **验收**：跑一款已知需长下载的游戏，验证不会睡眠、不误判卡死、总等待时间的有效占比 > 70%。

#### A3 `[P0]` 启动一律用包名（已部分生效，需固化）
- **问题**：用中文应用名启动会走 `find_package` → Hopper → `with_structured_output` → `tool_choice` 400 → 卡死。
- **证据**：`artemis/services/llm.py` 的 `with_structured_output`；`third_party/mobile_use/agents/hopper/hopper.py:59`。
- **改动**：系统提示 + 所有 goal 模板；可选在 `find_package` 入口做「看起来像包名就直接返回」的加固（已有快路径，需确认覆盖 `com.` 前缀判断）。
- **收益**：消除 3 次、392 分钟的死等。
- **风险**：低。
- **验收**：故意用中文名启动，验证 30s 内给出明确错误而不是挂起。

### B. Provider / 路由层

#### B1 `[P0]` 错误分类：修 `extract_status_code` 与 400 判定
- **问题**：代码里 400 已映射 non-retryable，但实测仍进 UNKNOWN → retryable → `llm_pause` 死等。
- **证据**：`reliability.py:68-74` 只读 `code/status_code`；日志出现 `LLM Error: Error code: 400` 后进入 `Waiting for LLM call response...`。
- **改动**：`artemis/llm/reliability.py`。
- **方案**（已按审查修正，原「递归 `__cause__`」无效）：
  1. `extract_status_code` 改为按 `status_code` → `code` → `status` 顺序取，**只接受 int 或纯数字字符串**（实测 `openai.BadRequestError.code='invalid_request_error'` 会遮蔽 `status_code=400`）；
  2. 再从 `str(error)` 正则兜底 `error code:\s*(\d{3})`；
  3. 不加 marker 白名单（减少误杀面）。
  - 附带：`services/llm.py:873-878` 的 `hold=lambda: PAUSE_FILE.exists()` 会在 pause 期间按住 180s 硬超时，需限制 hold 时长。
  - 注意测试返工：`test_llm_reliability.py` / `test_llm_pause.py` / `test_llm_gateway.py` / `run_benchmark_comparison.py:286-299`。
- **收益**：消除重试 0/3 成功的死循环类故障；fail-fast 让上层能换策略。
- **风险**：过度匹配可能把可恢复错误判死。缓解：marker 白名单 + 单测覆盖真错误样本。
- **验收**：用真实 400 报文回放，验证 1 次尝试后立即抛 `LLMPermanentError`，不进入 pause。

#### B2 `[已否决原方案，改为配置切换]` 厂商中立 / 去掉 Gemini 依赖

- **原判断错误**：`ds-qwen-pure`（`config/artemis.jsonc:129-160`）已是零 Google 预设，空 `GOOGLE_API_KEY` 下 `parse_llm_config()` 实测成功（planner=deepseek、fallback=qwen）。「清空 key 拒绝启动」只发生在选中 `ds-qwen-hybrid` 时——而队列正是这么选的（`qa_1114_queue.py:37`）。
- **改源码会撞契约**：`test_preset_switching.py:287`（T-02）把 hybrid 的 google fallback 写成断言样本，`:449`（T-04）要求 pure 全链路非 Google；且异常真实抛点在 `third_party/mobile_use/config/llm.py:96-97`，改它越界。
- **正确做法**：队列与文档默认预设切 `ds-qwen-pure`；补一条与 T-04 同风格的回归（不改 T-04 本身）。
- **附带真相**：「本轮零 Gemini」只对 QA 任务成立；DB 里 `gemini-3.8-flash` 有 25 次/246,371 tok、`gemini-3.5-flash-lite` 18 次/62,129 tok，且 11-15 12:37 有一次真实 fallback（Qwen 400 1×1 帧 → gemini → `API_KEY_INVALID`）。
- **验收**：`GEMINI_API_KEY` 删除后跑通一款游戏；日志 `generativelanguage` 0 次。

#### B3 `[P1]` 稳定缓存前缀（降本主力）
- **问题**：历史段被 scrub edge 改写导致前缀失效，缓存命中率只有 67.5%。
- **证据**：COST.md「被 scrub 改写后重算的尾部，稳态中位 3.2k/call，p90 19k」。
- **改动**：`artemis/agents/flash/context_compressor.py`、`artemis/memory/chunking.py`、`artemis/memory/transcript.py`。
- **方案**：scrub 只做**尾部追加式**替换（append-only marker），不回写已发送的历史块；把「改写深度」限制在最近 N 轮。
- **收益**：命中率 67.5% → 85%，预计 **−31% 成本（−$1.35/两日）**。
- **风险**：上下文里旧信息更久不被压缩 → prompt 变长，可能抵消部分收益（需实测净收益）。
- **验收**：同一款游戏跑两次，对比 `cached_ratio` 与总成本；要求缓存命中 ≥ 80% 且总成本下降。

#### B4 `[P1]` 按需传图 + 降采样
- **问题**：每步默认带 2 张不可缓存截图，图像 token 约 7.0M（两日）。
- **证据**：COST.md「98.2% 的步已有 UI 树」。
- **改动**：`artemis/agents/flash/runner.py` 的图像注入路径 + `context_compressor` 的 screenshot edge。
- **方案**：UI 树可用时不传图（或只传缩略图）；仅在树缺失/视觉提问时传全图；分辨率按需降采样。
- **收益**：图像 token 7.0M → 2.0M，预计 **−15%**。
- **风险**：纯视觉游戏（Unity Canvas）树为空，降采样会影响定位精度 → 需按「树是否为空」动态决策。
- **验收**：在 1 款 UI 树可用 + 1 款纯视觉游戏上对比，前者成本降 ≥50% 且准确率不降，后者准确率不降。

### C. 策略 / 判据层

#### C1 `[P0]` 引入 `NO_TUTORIAL_END`，替代「引导消失」单一判据
- **问题**：主线引导连续无终点的游戏永远满足不了「引导消失」，同一账号两次跑出 FAIL / PASS 两个结论。
- **证据**：一点三国 黎阳关瑾瑜：D 1710.7s/230 轮 → FAIL（停在「黄天余烬1-5 + 手指」）；D 810.3s/114 轮 → PASS（停在「军师升级 11/15」，手指暂时不在）。
- **改动**：判据模板 + 报告 schema。
- **方案**：检测到「引导持续但入口可拉起面板」时，判 `NO_TUTORIAL_END`（可信但非 PASS），不再判 FAIL；报告附「已连续引导 28 分钟，任务链仍在继续」。
- **收益**：消除同一游戏结论漂移；这类游戏的结论从「假 FAIL」变成「有信息量的分类」。
- **风险**：可能被用来掩盖真正卡死。缓解：必须同时满足「面板可拉起 + 主界面按钮可交互」。
- **验收**：一点三国连跑两次，两次结论一致。

#### C2 `[已生效，转为确认项]` 删除「时间兜底 PASS」
- **问题**：旧判据 `(b) 游玩超 30 分钟即 PASS`，实测三次踩到门口（1678s/1700s/1743s，差 57~122s）。
- **证据**：ACCURACY.md §4。
- **现状**：v2 队列已实现（`qa_1114_queue.py:295,305-306`，2400s → TIMEOUT），不占 P0 名额。
- **剩余动作**：确认产品侧默认 goal 模板同步，并把该行为固化成回归测试（而不是再跑一遍游戏）。
- **方案**：超时只产出 `TIMEOUT`，永不产出 PASS。
- **收益**：消除假 PASS 的结构性来源。
- **风险**：长引导游戏会被判超时 → 需配合 C1。
- **验收**：构造超时场景，确认输出 `TIMEOUT` 而非 PASS。

#### C3 `[P0]` 阶段边界设备重置 + 前台校验
- **问题**：上一款游戏的画面残留，导致连续多款拍到同一画面，**产出 5 份错误结论**。
- **证据**：`019828f8` 启动斗破，报告写「启动加载界面（大圣-西游咸鱼常规版-专服2）」；这些判决只花 13~27s，而真实冷启动 1.9 分钟。
- **改动**：`artemis/agents/flash/runner.py`（`run()` 入口）+ `artemis/drivers/android/adb_driver.py:416`（已有前台查询能力，但只打印不比较）。
- **方案**：每次任务启动前：`force-stop` 目标外的测试包 → HOME → 查询 `mCurrentFocus` → **与期望包名比对，不匹配则重试/中止**；把比对结果写进 trace。
- **收益**：直接消掉 5 次假 FAIL。
- **风险**：低（前台查询有现成实现）。
- **验收**：故意让其他 app 在前台，验证 runner 拒绝开跑并给出明确原因。

#### C4 `[P1]` 步数预算 + 失败快速退出
- **问题**：单 session 跑 212 步仍失败；步数超 120 后开销 $0.697（16.2%）。
- **证据**：COST.md。
- **方案**：D/E 默认 120 步上限，超出转 `TIMEOUT/NEED_HUMAN`；`failed` 状态快速退出，不再重试整段。
- **收益**：**−16%**（步数）+ **−13%**（失败快速退出）。
- **风险**：复杂游戏可能被误截断 → 预算可按游戏配置。
- **验收**：同一游戏开/关预算各跑一次，对比成本与结论一致性。

### D. 模块 / 运行时

#### D1 `[P0]` Runner 入口加 Preflight（当前为零）
- **问题**：`runner.py` 无任何前置校验；`_dims()` 无设备时静默 fallback 1080×2400（实际 1080×2160）；`get_screenshot()` 对 1×1 帧零校验。
- **证据**：RELIABILITY.md §4。
- **方案**：启动前校验并 fail-closed：
  - 设备在线 / 屏幕尺寸与预期一致 / 前台包名匹配 / 网络 `VALIDATED` / helper 存活 / 电量 > 15% / wakelock 已生效
  - 任一失败 → 明确报错并停止，**不使用默认值继续**。
- **收益**：把「跑到一半发现设备是坏的」变成「开跑前就拒绝」；消除纯绿空帧类事故。
- **风险**：环境稍差就拒绝启动 → 需分级（阻断级 / 警告级）。
- **验收**：逐项制造故障（拔线、断网、helper 停止），验证 5/5 被前置拦截。

#### D2 `[已否决原方案，降级为谓词放宽]` 唤醒机制

- **原判断错误**：日志里的失败是 `Could not **inspect** the shared screen-bright wake lock: Unknown command: set-wakelock`，来自 `awake_service.py:100` 的**遗留迁移清理**（注释明写 legacy），不是运行机制。
- **现行机制有效**：`_configure_usb_stay_awake`（`awake_service.py:87-150`）已执行 `svc power stayon usb`（:105），只因验证谓词要求 `value==2 且 mStayOn=true`（:126-133）过严（真机 `mStayOn=false`）才降级为 5 秒主机心跳（:139-150），**心跳是生效的**；真机全程 `mWakefulness=Awake`。
- **正确做法**：谓词放宽为「`stay_on_while_plugged_in != 0` 或 心跳线程存活」，同步 `tests/unit/runtime/test_awake_service.py`。约半小时，不进 P0。
- **验收**：跑 30 分钟长任务，`mWakefulness` 始终 Awake，且日志不再出现误导性的「降级」告警。

#### D3 `[P0]` 看门狗改为心跳式
- **问题**：现有 300s 看门狗只看日志字节增长；`compress_history` 最长 1677.8s 且零星输出，永不触发；7 次猝死中 5 次未被发现。
- **证据**：RELIABILITY.md §2。
- **方案**：监控「step 序号 + LLM 调用计数 + 最后工具动作时间」三元组；任一 300s 不推进即判挂起；对 `compress_history` 单独设 600s 超时并允许降级（跳过压缩继续跑）。
- **收益**：把最长 27.9 分钟静默缩短到 <10 分钟。
- **风险**：正常长压缩被误杀 → 需保留「压缩进行中」心跳信号。
- **验收**：人为注入慢压缩，验证 600s 内被识别并按策略降级。

#### D4 `[P0]` 空树索引点击熔断
- **问题**：元素列表为空仍传索引点击，126 次（占索引点击 53%）。
- **证据**：`artemis/mcp/action_executor.py:451`；日志 `Invalid target index 14. The list is empty on this screen`。
- **方案（已修正）**：现状**已经**在点击前抛可读错误（`action_executor.py:443-456`），所以「加错误提示」收益≈0。真正要做的是：抛错时**同步刷新一次 UI 树**并标记 `retryable_with_refresh`；同一 session 对同一索引连续失败 ≥3 次 → 该 turn 禁用索引点击，只允许坐标点击 / 视觉提问。
- **收益（修正）**：126 步实测关联成本 **$0.2189**（237 次调用 / 3.80M prompt / 2.72M cached），净省远小于 5%——原「2.64M tokens」高估了影响。
- **风险**：低。
- **验收**：注入空树场景，验证不产生 LLM 往返。

#### D5 `[P1]` 进程树回收进产品代码
- **问题**：`uv run` 被杀后 python 子进程成孤儿，占 ADB 导致后续任务卡死。
- **现状**：已在队列脚本用 `start_new_session + killpg` 修复（`scripts/qa_1114_queue.py`），**但产品侧未修**。
- **方案**：迁移到 `artemis` 的任务生命周期管理里。
- **验收**：强杀父进程后，子进程在 5s 内消失。

#### D6 `[P2]` `traces` 保留策略与 GC
- **现状**：30 GB；录像 72 个共 10.6 GB；最大单文件 5.06 GB；存在「宿主已死、设备端继续录 9 小时」的孤儿录制。
- **方案**：默认不录像（或仅录最近一次）；录制加硬上限（时长/大小）；按天保留 N 天；启动时清理孤儿。
- **收益**：立即回收 ~10 GB，长期增长可控。
- **验收**：连续跑 3 款游戏，新增磁盘 < 1 GB。

---

### E. 审查新增项（原方案遗漏，杠杆高于多数 P1）

#### L1 `[P0]` 隐私与取证风险（原方案把它误判为「磁盘问题」）
- **事实**：视频 ≈27.6 GiB + 截图 2,068 张 / 562 MB，含真实角色名、九游账号回显（`大圣_x957，欢迎回来`）、¥168/¥198/¥328 充值面板；与仓库同盘、未加密、无保留期。
- **方案**：录像默认关闭（需要时显式开启）；截图区脱敏（状态栏/账号区遮罩）；保留期 N 天；启动清理孤儿录制。
- **收益**：隐私合规 + 立刻回收 ~27 GB。
- **验收**：新跑一轮后新增磁盘 < 1 GB，回放截图不含账号明文。

#### L2 `[P0]` E 阶段把 `UNKNOWN` 当 `PASS`
- **事实**：`scripts/qa_1114_queue.py:324` `"PASS" if verdict_of(e,1200) in ("PASS","UNKNOWN")`。**报告写得越含糊越容易 PASS**，比「时间兜底」更隐蔽。
- **方案**：`UNKNOWN` 一律记 `INCONCLUSIVE`，不并入 PASS。
- **验收**：构造一份无 `result=` 的 E 报告，验证不被判 PASS。

#### L3 `[P0]` 1×1 帧零校验 → 跨厂 fallback 连环失败
- **事实**：11-15 12:37:29–32 连续 4 条 `llm_gave_up`：Qwen 400 `height(1) or width(1) must be larger than 28` → 回落 `gemini-robotics-er-2-preview` → `API_KEY_INVALID`。
- **方案**：截图入口校验 `min_dim >= 32` 且非单色，失败 fail-closed 并重取。
- **收益**：同时消除假 FAIL、Qwen 400、以及对 Google 的意外依赖。

#### L4 `[P1]` 判据 golden set（离线回归）
- 库里有 2,167 条 step、2,067 张图、48 份 `report_task_status` 载荷，可做「历史证据 → 期望判决」回归集。
- **没有它，A1/C1/C2 改完无法证明「4 个假 PASS 会变成 4 个非 PASS」**。

#### L5 `[P1]` 一行配置止血前缀抖动
- `lens:step_capsule` 花 $0.326 只换 31% 压缩；`History compression swap: froze …` 出现 101 次；`transcript.py:456-461` 的 `start_ratio` 让 scrub 深度在 6↔3 来回。
- **做法**：把 `config/artemis.jsonc:340` 的 `image_scrub_depth_relaxed` 设成与 `image_scrub_depth` 相同（或 `start_ratio=null`），零代码先验证 B3 假设。

#### L6 `[P1]` 截图降采样（从 B4 拆出）
- 实测两张图 338 KB / 151 KB（quality=85 的 1080×2160）。降到 720p 约省 55% 图像 token，对「描述画面变化」几乎无损。
- 风险远低于「按需删图」，应**先做降采样，再做按需传图**。

## 4. 实施顺序（v2，按审查重排）

| 阶段 | 内容 | 预估 | 依赖 |
|---|---|---|---|
| S0 | **C3 前台校验（复用现成实现）**、**L1 录像默认关+脱敏**、**L3 帧有效性校验**、**A1 schema+硬门**、**B1 status_code 优先级**、**L2 UNKNOWN≠PASS** | 1.5~2 天 | 无 |
| S1 | D1 preflight（分级）、A2 等待上限 60s **+** D3 心跳看门狗（同批）、L5 一行配置止血 | 1~2 天 | S0 |
| S2 | B3 缓存前缀（append-only）、L6 截图降采样、C4 步数预算 | 2~3 天 | S1 有干净基线后 |
| S3 | C1 NO_TUTORIAL_END（含硬否证）、L4 golden set、D4 索引熔断（刷新+封锁） | 2 天 | S1 |
| S4 | D5 进程回收进产品、B2 切预设+回归、D2 谓词放宽 | 1 天 | 无 |

> 与 v1 的差异：C3/L1/L3/L2 提前到 S0；B2/D2 从 P0 降级；A2 与 D3 强制同批上线（240s vs 300s 只有 1.25 倍余量，单做任一条会放大误杀）。

## 5. 验收指标（当前 → 目标）

| 指标 | 当前 | 目标 | 测量方式 |
|---|---|---|---|
| 假 PASS（面板未拉起却 PASS） | 4/4 第一轮 PASS 不成立 | **0** | 结构化断言 + 回放核查 |
| 假 FAIL（画面残留/设备故障导致） | 11 次非游戏原因 | **0** | 报告必须含前台包名与设备快照 |
| 动作有效率 | 61.7% | ≥ 75% | dhash 对比（注明局限） |
| 静默挂起检出率 | 2/7 | **7/7 且 < 10 分钟** | 心跳看门狗日志 |
| 单款完整流程成本 | $0.41~1.1 | ≤ $0.25（需实测验证，各项收益有重叠，勿直接相加） | DataEngine 聚合 |
| 视频/截图存量 | ≈27.6 GiB / 562 MB | 默认不录像；保留 N 天 | `du -sh` + 隐私抽检 |
| 结论一致性（同游戏连跑） | 一点三国 FAIL/PASS 漂移 | 两次一致 | 重复实验 |

---

## 6. 开放问题（需人决策，审查者可提意见）

1. 是否允许对 deepseek 关闭 thinking mode？关了能彻底绕开 `tool_choice` 冲突，但长程规划质量可能下降。
2. 是否引入本地 CV 快通道（高亮遮罩/引导手指模板匹配）？能显著提速降本，但增加维护面与平台差异风险。
3. 录像是否默认关闭？影响事后举证能力，但占 10.6 GB。
4. `NO_TUTORIAL_END` 是否可接受为正式结论类型？业务侧是否认可？
5. 结构化断言会让 prompt 变长，与降本目标冲突，是否接受用少量成本换可信度？

---

## 7. 审查者检查清单

- [ ] §1.1 四条事实是否复现成功？
- [ ] 每条「改动位置」是否真的存在且是正确入口？
- [ ] 有没有哪条方案的收益被我高估（尤其是 B3 缓存前缀的净收益）？
- [ ] 有没有方案会破坏 frozen contract 或 gate.py L4？
- [ ] 有没有漏掉的高杠杆项（我认为已覆盖问题，但可能漏解）？
- [ ] 优先级排序是否合理？S0/S1 是否依赖了尚未验证的假设？
- [ ] 验收指标是否可测？有没有「测不出来」的指标？
- [ ] 是否存在隐私/安全风险（截图含账号信息、录像含支付面板）？
