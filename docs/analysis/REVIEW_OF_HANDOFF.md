# 对《Artemis 优化方案交接》的独立审查

- 审查时间：2026-11-15
- 审查对象：`docs/OPTIMIZATION_HANDOFF.md`
- 审查方式：逐条对照代码与 `traces/data_engine.db` 复核，并对 400 报文做了本地 mock 复现
- 结论口径：`VERIFIED` / `UNVERIFIED` / `WRONG`

---

## 1. 总评

方向大部分是对的（判据工程化、前置校验、错误分类、缓存前缀），但**事实基座有三处硬伤，不能照单执行**：

1. **B2「Gemini fallback 硬绑定」因果链错误**。零 Google 预设 `ds-qwen-pure` 已存在于 `config/artemis.jsonc:129`，在无 `GOOGLE_API_KEY` 下 `parse_llm_config()` 实测成功。所谓「清空 key 拒绝启动」，真实原因是**队列选了带 Google fallback 的 `ds-qwen-hybrid`**（`scripts/qa_1114_queue.py:37`）。B2 的改法是给配置选择问题做源码手术，且会撞冻结契约 T-02/T-04。
2. **D2「wakelock 32/32 全失败」是误读日志**。失败的 `set-wakelock` 来自 `awake_service.py:100` 的**遗留迁移清理**；真正的机制是 `awake_service.py:105` 的 `svc power stayon usb`，只是验证谓词过严（要求 `value==2` 且 `mStayOn=true`）才降级为 5 秒主机心跳——**而心跳是生效的**。
3. **B1 的第一条修法无效**。mock 复现显示 `openai.BadRequestError.code == 'invalid_request_error'`（字符串），`int()` 抛 `ValueError` → `None` → `UNKNOWN`；**异常链为空，递归 `__cause__` 修不了**。

最该改的三件事：把 B2 降级为「切预设 + 补回归」、把 D2 降级为「放宽验证谓词」、补上文档完全漏掉的**隐私与取证风险**（27.6 GiB 录像 + 562 MB 截图里有账号与支付面板）。另外 §5 的 `≤$0.25/款` 无法由 §3 各项收益推出（各项相加已 −75% 且互相重叠）。

---

## 2. 事实核查表

| 条目 | 结论 | 依据 | 备注 |
|---|---|---|---|
| 4 个 session `end_time` 相同 | VERIFIED | `group by end_time having count(*)>1` → `1794662524.044246 \| 4` | 67 个 session 均有 end_time |
| `traces/` 30 GB | VERIFIED | `du -sh` = 30G；db 单文件 1,746 MB | — |
| 录像 72 个共 10.6 GB | **WRONG（不完整）** | 10.61 GiB 仅 mp4；**另有 2 个 mkv 共 17.0 GiB** | 视频实际 ≈ **27.6 GiB** |
| 最大单文件 5.06 GB | **WRONG** | `qa1114_dasheng_BC/recording.mkv` = 8.7 GiB；`yidiansanguo_E/recording.mkv` = 8.2 GiB | D6 的「回收 10 GB」应为 ~27 GB |
| 400 已映射 BAD_REQUEST 非重试 | VERIFIED | `reliability.py:110` | — |
| `extract_status_code` 只读两属性 | VERIFIED | `reliability.py:68-74` | — |
| 400 实际走 UNKNOWN→retry→pause | VERIFIED | `traces` 中 `llm_retry` 13 条、`llm_pause` 3 条，payload `category=unknown, retryable=true` | 根因：`.code` 是字符串，遮蔽 `.status_code=400` |
| B1 修法①「递归 `__cause__`」 | **WRONG** | mock 400：`classify_failure()` → UNKNOWN，异常无 cause 链 | 只有「status_code 优先 + 正则」有效 |
| `wait_for_delay(240000)` 存在 | VERIFIED | `$.args.time_in_ms` 聚合：240000 出现 2 次 | 次高档 180000/150000/120000 |
| 「29 分钟里 24.5 分钟盲等」 | VERIFIED | session `872aa6bc`：21 次 wait 合计 1467.5s，session 跨 1769s | 全数据集最严重 |
| D2「32/32 wakelock 失败且被忽略」 | **WRONG** | 日志原文是 `Could not **inspect** … Unknown command: set-wakelock`（`chongba/run_D.log:52`），属 legacy 清理 | 主路径 `svc power stayon usb` 已执行 |
| D2「设备会自行睡眠」 | **WRONG（有兜底）** | `run_D.log:53` 降级 5 秒心跳；`awake_service.py:139-150` | 真机全程 `mWakefulness=Awake` |
| D2 改动点 `awake_lease.py:171,187` | 部分 WRONG | 属 legacy 租约，非主路径 | 已有单测 `test_awake_service.py` |
| `_dims()` 无设备静默 1080×2400 | VERIFIED | `mcp/actuators/adb.py:122-125`；真机 `wm size` = 1080x2160 | 多处同款默认值 |
| 「runner.py 无任何前置校验」 | 部分 WRONG | `FlashRunner.run`（`runner.py:1041`）无 preflight；但 `app_launch_utils.py:196-202` 已有前台包比对，`adb_driver.py:402-423` 是**返回值**实现 | 缺口是「从不调用」 |
| 空树索引 126 次 / 占 53% | VERIFIED | `last_execution_result like '%Invalid target index%'` = 126；整数 target click = 237 → 53.2% | — |
| D4「把错误喂回模型」需修 | **WRONG（方案冗余）** | `_resolve_index` 已在点击前抛可读 `_ArgError`（`action_executor.py:443-456`），从未真正 tap | 真问题是**树不刷新 + 模型重试 stale index** |
| D4 收益「2.64M tokens」 | 被高估 | 126 步关联 237 次调用：prompt 3.80M / cached 2.72M → **$0.2189** | 净省远小于 5% |
| 第一轮 4 个 PASS 的验收③不成立 | VERIFIED | `REPORT.md:130-140` | v2 已把 ③ 写进 goal |
| A1 改动位置「系统提示 + goal」 | 不完整 | `report_task_status` schema 只有两个自由文本字段（`tool_declarations.py:275-296`），`_finalize_task_report`（`runner.py:548-587`）原样透传 | 应改 **tool schema + 终局硬门** |
| C2 时间兜底三次踩门口 1678/1700/1743s | UNVERIFIED（自相矛盾） | `ACCURACY.md:213` 说三次；`REPORT.md:128-133` 只有 1731s/1781s 两项 | 数字不可采信 |
| C2 现网仍用时间兜底 | **WRONG（已修）** | `qa_1114_queue.py:6,284,295,305-306`：2400s → TIMEOUT | 属「已生效」 |
| C3 画面残留导致斗破判成大圣 | VERIFIED（一手） | session `019828f8`：22.0s 结束，report 写「大圣-西游咸鱼常规版-专服2」 | 「5 份」只核实到 1 份 |
| C3「adb_driver:416 只打印不比较」 | 部分 WRONG | `app_launch_utils.py:197` 就在比对 | 只有 `qa_1114_queue.py:88-93` 是只记录 |
| A3 中文名启动 → Hopper → 400 | VERIFIED | `hopper.py:59`、`services/llm.py:596-611`；3 次 `llm_pause` 均此报文 | 快路径是**全等匹配已装包**，无 `com.` 前缀判断 |
| A3「死等 392 分钟」 | UNVERIFIED | 三次 pause 的 `waited_seconds` 为 1.7/1.8/1.6s，之后受 `LLM_PAUSE_TIMEOUT_SECONDS=900` 约束 | 找不到 392 min 证据 |
| B2「清空 key 拒绝启动」 | **WRONG（对 ds-qwen-pure）** | 实测 `ds-qwen-pure` + 空 key → PARSE OK，全链路 deepseek/qwen | 异常文本来自 `third_party/mobile_use/config/llm.py:96-97` |
| B2「每节点 fallback 指向 google」 | VERIFIED（仅 hybrid/baseline） | `config/artemis.jsonc:92-128` vs `:129-160` | 队列显式选 hybrid |
| B2「预热是无条件真实 Gemini ping」 | VERIFIED | `sdk/agent.py:129-167`；无 key 时跳过（`:147`） | 非硬依赖 |
| 「本轮零 Gemini 推理」 | 对 QA 成立，对数据集 **WRONG** | `gemini-3.8-flash` 25 次/246,371 tok；`gemini-3.5-flash-lite` 18 次/62,129 tok；`llm_fallback` 2 次 | COST.md「13 次」与库不符 |
| 总成本 $4.29 / 61.25M / 2.48M / 67.5% | VERIFIED | 4,967 calls；cached 40,851,314（66.69%） | 逐节点复算合计 $4.291 |
| UI 树覆盖 98.2% | VERIFIED | 2,131 步中 2,092 非空 | 均值 3,739 字符 |
| B4 summarizer 每步 2 张图 | VERIFIED | 2,095 次调用均含 4 个 `image_url`；抽样 338KB + 151KB | planner 单轮 1 张 |
| B4「planner 图像 ~2.7M tok」 | UNVERIFIED | planner 走 `RobustChatModelWrapper`，prompt 未落库 | COST.md 自标「推断」 |
| P3「Qwen 后 63.7% < 基线 66.2%」 | VERIFIED | `ACCURACY.md:142-147`：226/273、174/273、915/1383 | 当前用法无增益 |
| D3 `compress_history` 最长 1677.8s | VERIFIED | `max(duration)`=1677.8，289 次，>300s 共 10 次 | — |
| D3 看门狗只看字节 | VERIFIED | `qa_1114_queue.py:133-148` | 240s vs 300s 仅 1.25 倍余量 |
| 一点三国结论漂移 | VERIFIED | `SUMMARY.md` 表格 | — |

---

## 3. 逐条攻击（P0 项）

### A1 结构化断言 —— 方向对，落点错

- 改动放在「提示词」等于把可机读性寄托在模型自觉上，而这正是当前问题的成因；`report_task_status` 服务端**零校验**。
- **替代**：给 tool schema 增加 `check_guide_gone / check_entry_visible / check_panel_opened` + `evidence`，在 `_finalize_task_report` 做硬门：任一 `NO` 或 evidence 为空 → `INCONCLUSIVE`/`FAIL` 并落 trace。提示词只保留「必须调用该工具」。
- 落点不改，等于白做。

### A2 禁止超长盲等 —— 数据成立，但风险在别处

- 只盯「等待无上限」，没盯**看门狗余量**：最大合法等待 240s vs 阈值 300s，模型某次写 300000 就会杀掉健康任务。
- **替代**：`wait_for_delay` 上限压到 60s **与** D3 心跳看门狗**必须同批上线**，单做任一条都会放大误杀。
- A2b（`wait_until(predicate)` 走 CV 进度检测）成本高，降 P2。

### A3 一律用包名 —— 事实成立，最后一条判断错

- 「已有 `com.` 前缀快路径」不存在，快路径是**全等匹配已安装包**。真去加前缀判断会把错误包名误判为合法。
- **替代**：`find_package` 在 `app_name` 未命中包集合且含 CJK 时直接返回 None（不进 Hopper）；釜底抽薪是在 `services/llm.py:596-611` 对 DeepSeek 的 `with_structured_output` 改用 `bind_tools`（不传 `tool_choice`）。
- 建议 A3 降 P1，把「Hopper 结构化输出对 DeepSeek 走 bind_tools」提为新 P0。

### B1 错误分类 —— 结论对，修法②③对、①错

- 修法①（递归异常链）对本 bug **完全无效**，异常链为空。
- **替代**（只改一行语义）：
  ```python
  for attr in ("status_code", "code", "status"):
      v = getattr(error, attr, None)
      if isinstance(v, int): return v
      if isinstance(v, str) and v.isdigit(): return int(v)
  ```
  再补 `str(error)` 正则兜底；marker 白名单属多余风险。
- **被低估的成本**：会牵动 `test_llm_reliability.py` / `test_llm_pause.py` / `test_llm_gateway.py` 与 `run_benchmark_comparison.py:286-299`。
- **还有一条死等机制文档没看到**：`invoke_llm_with_timeout_message` 的 `hold=lambda: PAUSE_FILE.exists()`（`services/llm.py:873-878`）会在 pause 期间把 180s 硬超时按住 → 应限制 hold 时长。

### C1 `NO_TUTORIAL_END` —— 可接受，但缺拒绝条件

- 「面板可拉起 + 主界面可交互」在**崩坏场景下也会成立**（透明遮挡 + 可点按钮），一点三国 E 就是「点了没反应」。
- **补充**：若该 session 出现 ≥3 次「同坐标点击后 dhash 不变」，`NO_TUTORIAL_END` 直接降 `NEED_HUMAN`；结论类型必须进 schema。

### C3 阶段边界校验 —— 证据最硬，应最先做

- 必须明确**何时**比对：若在 `launch_app` 之后才比对，残留画面早已进上下文（`019828f8` 22 秒就结束）。
- **替代**：复用 `app_launch_utils.py:196-202`，前移到 `FlashRunner.run()` 第一行之前，并把 `reset_device()` 的 force-stop 列表下沉到产品侧。改动量远小于文档描述。

### D4 空树索引熔断 —— 机制已存在，收益被高估

- `_resolve_index` **已经**抛可读错误、从未真正 tap。落地原方案收益≈0。
- **替代**：抛错时**同步刷新树**并标 `retryable_with_refresh`；同一 session 同索引连续失败 ≥3 次 → 该 turn 禁用索引点击，只允许坐标点击/视觉提问。
- 收益修正：126 步实测 **$0.2189**，且下一步无论如何会发生。

---

## 4. 遗漏项（文档没写、杠杆更高）

### L1 `[P0]` 隐私/取证风险
27.6 GiB 录像 + 562 MB 截图（2,068 张，均值 272 KB），含真实角色名（黎阳关瑾瑜/阳夏彤/问道烛战野/见习冒险者）、九游账号回显（`大圣_x957，欢迎回来`）、¥168/¥198/¥328 充值面板。与仓库同盘、未加密、无保留期。D6 只把它当磁盘问题，**定性错了**。
→ 建议：录像默认关闭、截图区脱敏（状态栏/账号区遮罩）、保留 N 天、启动清理孤儿录制。

### L2 `[P0]` E 阶段把 `UNKNOWN` 当 `PASS`
`scripts/qa_1114_queue.py:324`：`"PASS" if verdict_of(e,1200) in ("PASS","UNKNOWN")`。**报告写得越含糊越容易 PASS**——比「时间兜底」更隐蔽的假 PASS 通道。

### L3 `[P0]` 1×1 帧零校验 → 触发跨厂 fallback 连环失败
11-15 12:37:29–32 连续 4 条 `llm_gave_up`：Qwen 400 `height(1) or width(1) must be larger than 28` → 回落 `gemini-robotics-er-2-preview` → `API_KEY_INVALID`。既是假 FAIL 源，也是厂商中立破口。
→ 截图入口加 `min_dim >= 32 且非单色` 校验，失败 fail-closed 并重取。

### L4 `[P1]` 缺判据回归集
A1/C1/C2 完全可以离线回归：库里有 2,167 条 step、2,067 张图、48 份 `report_task_status` 载荷，可做「历史证据 → 期望判决」golden set。没有它，改完无法证明「4 个假 PASS 会变成 4 个非 PASS」。

### L5 `[P1]` 一行配置止血前缀抖动
`lens:step_capsule` 花 $0.326 只换 31% 压缩；日志 `History compression swap: froze …` 出现 101 次；`transcript.py:456-461` 的 `start_ratio` 门控让 scrub 深度在 6↔3 来回。把 `config/artemis.jsonc:340` 的 `image_scrub_depth_relaxed` 设为与 `image_scrub_depth` 相同（或 `start_ratio=null`）即可零代码验证 B3 假设。

### L6 `[P1]` B4 真正大头是「图太大」不是「图太多」
实测两张图 338 KB / 151 KB（quality=85 的 1080×2160）。降到 720p 可省 ~55% 图像 token，对「描述画面变化」几乎无损；「按需删图」风险大得多。应拆开、先做降采样。

---

## 5. 优先级排序（与原文差异）

| 排序 | 项 | 原文 | 差异理由 |
|---|---|---|---|
| P0-1 | C3 前台校验 + 阶段重置（复用现成实现） | P0 | 唯一有一手证据的假 FAIL；改动最小 |
| P0-2 | **L1 隐私/保留策略 + 录像默认关闭** | 无 | 27.6 GiB 含账号与支付面板 |
| P0-3 | **L3 帧有效性校验** | 藏在 D1 注脚 | 同时消除假 FAIL、Qwen 400、Gemini 依赖 |
| P0-4 | A1（**改 schema + 硬门**） | P0（改提示词） | 落点错会白做 |
| P0-5 | B1（**只改 status_code 优先级**） | P0 | 修法①无效 |
| P0-6 | **L2 E 阶段 UNKNOWN→PASS** | 无 | 更隐蔽的假 PASS 通道 |
| P1-1 | D1 preflight（分级） | P0 | 依赖 C3 的前台查询 |
| P1-2 | A2 上限 60s **+ D3 心跳（同批）** | 分列 P0 | 单做会放大误杀 |
| P1-3 | **L5 一行配置止血** | 无 | 零代码先验 B3 假设 |
| P1-4 | B3 缓存前缀 | P1 | 先测净收益 |
| P1-5 | C1 `NO_TUTORIAL_END` + 硬否证 | P0 | schema 未定义前不该算 P0 |
| P2-1 | **L6 截图降采样 720p** | 与 B4 绑定 | 拆开后风险更低 |
| P2-2 | B4 按需传图 | P1 | planner 图像占比是推断值 |
| P2-3 | D4 索引熔断（改为刷新+封锁） | P0 | 原方案收益≈0 |
| P2-4 | **L4 判据 golden set** | 无 | 是 A1/C1/C2 的验收前提 |
| P2-5 | D5 进程回收进产品 | P1 | 同意 |
| P2-6 | D6 traces GC（**并入 L1**） | P2 | 隐私项子集 |
| 否决 | B2 按原方案 | P1 | 前提错 + 撞契约 + 越边界 |
| 否决 | D2 按原方案 | P0 | 误读日志，现行机制已生效 |

---

## 6. 不能上线的项

### 6.1 B2「解除 Gemini fallback 硬绑定」—— 应否决原方案

1. **前提错**：`ds-qwen-pure`（`config/artemis.jsonc:129-160`）已是零 Google 预设，空 key 下解析成功。所谓拒绝启动只发生在选中 `ds-qwen-hybrid` 时（`qa_1114_queue.py:37`）。这是**配置选择问题**。
2. **撞冻结契约**：`tests/unit/test_preset_switching.py:287`（T-02）把 hybrid 的 google fallback 写成断言样本；`:449`（T-04）要求 pure 全链路非 Google。改语义要么改测试（违反字节不可变），要么红（违反 gate.py L4）。
3. **越 third_party 边界**：`requires GOOGLE_API_KEY` 的真实抛点在 `third_party/mobile_use/config/llm.py:96-97`。

**替代（成本≈0）**：队列与文档默认预设切 `ds-qwen-pure`；补一条与 T-04 同风格的回归（不改 T-04）。

### 6.2 D2「修复 wakelock」—— 应否决原方案

- 日志失败语句是 `Could not inspect the shared screen-bright wake lock: Unknown command: set-wakelock`，来自 `awake_service.py:100` 的**迁移清理**（注释明写 legacy）。
- 运行机制 `_configure_usb_stay_awake`（`awake_service.py:87-150`）执行的是 `svc power stayon usb`（:105）+ 读 `stay_on_while_plugged_in`（:115）；「失败」是因为验证谓词要求 `value==2 且 mStayOn=true`（:126-133），真机 `mStayOn=false` → 降级 5 秒心跳（:139-150），**心跳有效**。
- 因此「消除设备自动睡眠整条故障链」的收益是虚的。

**替代**：谓词放宽为「`stay_on_while_plugged_in != 0` 或 心跳线程存活」，并同步 `tests/unit/runtime/test_awake_service.py`。约半小时，不进 P0。

### 6.3 保留但必须改写

- **B1**：删 `__cause__` 递归。
- **A1**：落点改 `tool_declarations.py` + `runner._finalize_task_report`。
- **C2**：既成事实，改为「确认产品侧默认模板同步」+ 回归测试。

---

## 附录：可复现查询

```sql
-- 总量与命中率（4967 / 61,251,593 / 2,479,221 / 40,851,314 / 66.69%）
select count(*), sum(json_extract(payload,'$.prompt_tokens')),
       sum(json_extract(payload,'$.completion_tokens')),
       sum(json_extract(payload,'$.cached_tokens'))
from traces where type='llm_call' and name='llm_usage';

-- 按 source（暴露 gemini 实调用 25+18 次）
select json_extract(payload,'$.source') src, count(*),
       sum(json_extract(payload,'$.prompt_tokens')), sum(json_extract(payload,'$.cached_tokens'))
from traces where type='llm_call' and name='llm_usage' group by src;

-- 空树索引 126 = 索引点击 237 的 53.2%
select count(*) from steps where last_execution_result like '%Invalid target index%';
select count(*) from traces where type='action' and name='click'
  and json_type(payload,'$.args.target')='integer';

-- 等待上限
select cast(json_extract(payload,'$.args.time_in_ms') as integer) ms, count(*)
from traces where type='action' and name='wait_for_delay' group by ms order by ms desc limit 5;

-- 压缩阻塞
select max(duration), count(*), sum(case when duration>300 then 1 else 0 end)
from traces where name='compress_history';

-- 错误分类事件
select name, datetime(timestamp,'unixepoch','localtime'), substr(payload,1,200)
from traces where name in ('llm_pause','llm_gave_up') order by timestamp;
```

**mock 复现要点**：本地起 HTTP 服务返回真实 DeepSeek 400 体，用 `langchain_openai.ChatOpenAI(base_url=...)` 触发 → `type=openai.BadRequestError`、`.code='invalid_request_error'`、`.status_code=400`、`extract_status_code()` 返回 `None`、`classify_failure()` 返回 `UNKNOWN/retryable=True`。

---

## 未完成事项（如实记录）

1. 「11 次非游戏原因」中 6 次 WiFi 类未逐例复核；
2. 「5 份残留导致错误结论」只核实到 1 份（`019828f8`）；
3. A3 的「392 分钟」未找到证据。
