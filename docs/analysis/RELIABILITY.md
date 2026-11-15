# Artemis 可靠性分析（故障分类 / 静默卡死 / 重试自愈 / 前置校验 / 资源泄漏）

> 数据源：`traces/data_engine.db`（67 sessions / 2,167 steps / 30,569 traces / 2,067 images，1.7 GB）
> 日志：`traces/qa_1114/{queue,queue2..4}.log`、`traces/qa_1114/*/run_*.log`、`traces/qa_1114_v2/{queue,queue2}.log`、`traces/qa_1114_v2/*/run_*.log`、`traces/qa_1114_v2/queue_status*.json`
> 代码（只读）：`scripts/qa_1114_queue.py`、`artemis/services/llm.py`、`artemis/mcp/actuators/adb.py`、`artemis/drivers/android/adb_driver.py`、`artemis/config/settings.py`、`third_party/mobile_use/clients/ui_automator_client.py`
> 全部结论来自 SQL 聚合或日志原文引用；推算与观测严格分开标注；查不到的写「未知」。

---

## 一句话结论

**67 个 session 的墙钟里 91.3% 是废的：7 次进程级猝死（其中 4 次挂机 9.5–10.2 小时后才被外部批量补记闭环）吃掉 39.7 小时纯空转；20 次失败里有 11 次（55%）根本不是游戏的问题——5 次是上一款游戏的画面残留在前台被当成新产品判死，6 次是设备 WiFi 没通导致 5 款不同游戏集体报「链接已失效」。真正需要工程投入的只有三件事：**阶段级前置校验（前台包名 / 设备在线 / 帧有效性 / 网络 VALIDATED）**、**把 400 类错误从「可重试」改成「永久失败」并彻底删除无限停顿**、**让看门狗盯进程树与进度心跳，而不是盯日志字节数**。**

---

## 0. 口径与局限（先读）

1. **「净损失时长」定义**：`session.end_time − session.start_time`（墙钟）。对 4 个挂死 session，墙钟 **≥99%** 是空转（611.5/611.7、603.6/607.1、597.8/598.2、571.7/572.8 min），因此另列「实际活动时长 = 最后一条 trace 时间 − start_time」。
2. **`sessions.status` 只有两个取值**：`completed` / `failed`（无 `cancelled`/`running` 落库）。所以「失败」既包含「Agent 判定 FAIL/BLOCKED 的正常收尾」，也包含「进程猝死」，必须分开看（见 §1.2）。
3. **`traces.status` 四值**：`success` / `failed` / `running` / `retrying`。`running` 是**从未被关闭的 span**——进程被杀时 trace 来不及写终态，这类记录的规模本身就是猝死的代理指标。
4. **`failed_outputs` 表为空（0 行）**，模型原始输出/失败 prompt 没有落库，因此「模型侧失败原因」只能从 `traces.payload` 反推；这是可观测性缺口，不是「没有失败」。
5. **时钟**：`start_time/timestamp/end_time` 均为 epoch 秒，本文一律换算为本地时间（`+08:00`）。
6. **4 个挂死 session 的 `end_time` 是伪造的（观测事实，原因存疑）**：`715d27b7`、`5a79d7b3`、`6ec0dd97`、`4de4e676` 四条记录的 `end_time` **精确到同一秒 = 2026-11-14 21:22:04**（SQL 见附录 A6）。仓库内不存在任何批量 UPDATE sessions 的代码路径（`artemis/data_engine/storage.py:301` 的 `update_session` 是单条、且 `engine.py:644 end_session` 会先判断 `end_time is None`）。因此这是**仓库外的批量补写**（人工 SQL 或外部脚本）。后果：**`sessions` 表的时长字段被污染，任何基于 `end_time-start_time` 的可靠性统计都会虚高最多 10 小时**。本文对这四个样本同时给出「墙钟」与「实际活动」。

---

## 1. 失败分类学（问题 1）

### 1.1 总量

| 指标 | 数值 |
|---|---|
| sessions 总数 | 67 |
| `completed` | **47（70.1%）** |
| `failed` | **20（29.9%）** |
| 有 steps 的 session | 64（3 个 0 步：`af880a5d`/`6ec0dd97`/`fc025886`） |
| steps 总数 | 2,167 |
| traces 总数 | 30,569 |
| 时间跨度 | 2026-11-13 23:00 → 2026-11-15 14:36 |

**按天看，可靠性在恶化：**

| 日期 | completed | failed | 失败率 |
|---|---|---|---|
| 11-13 | 12 | 0 | **0.0%** |
| 11-14 | 18 | 5 | **21.7%** |
| 11-15 | 17 | 15 | **46.9%** |

> 11-13 全是「Open Settings and check Battery level」这类 12 个 0.3–1.2 分钟的单步冒烟用例，不能代表手游质检场景。11-14/15 才是真实负载。

### 1.2 关键拆分：猝死 vs 正常收尾

用「最后一步的 `last_execution_result` 是否含 `Task completed with final report`」判定 Agent 是否自己走完了收尾：

| 类型 | 数量 | 占失败 | 含义 |
|---|---|---|---|
| **正常收尾的 FAIL/BLOCKED** | 13 | 65.0% | Agent 主动 `report_task_status`，属「判据结论」 |
| **进程级猝死（无收尾）** | **7** | **35.0%** | 进程被杀/挂死，`end_session` 未执行 |

7 个猝死 session 明细：

| session | 墙钟 | 实际活动 | steps | 死在哪 |
|---|---|---|---|---|
| `715d27b7…` | 611.7 min | **0.2 min** | 1 | 摘要 LLM 调用（`ChatOpenAI` status=`running`）挂起 |
| `5a79d7b3…` | 607.1 min | 3.5 min | 20 | `compress_history` 执行中（末行 `Chunk capsule chunk:8-14 …`） |
| `6ec0dd97…` | 598.2 min | **0.4 min** | 0 | `llm_pause`（thinking-mode 400）后死等 |
| `4de4e676…` | 572.8 min | 1.1 min | 6 | 同上 |
| `fc025886…` | 5.5 min | 0.4 min | 0 | 同上（被看门狗 ~316s 杀掉） |
| `42980182…` | 0.3 min | 0.3 min | 1 | launch 后即死 |
| `af880a5d…` | 0.0 min | 0.0 min | 0 | `error: device '89FX09M9U' not found` |

### 1.3 故障分类表（主表：按 session 计）

> 占比分母 = 20 个 failed session。「必然失败」= 在故障原因不改变的前提下，重试/换模型/延长超时都不可能导致成功。

> 下表 8 个故障族**合计恰好 = 20 个 failed session**（F6 是 F5 内某个 session 的放大器，不单独计数；最后一行「闪退」是放大器，不单独计数）。

| # | 故障族 | 次数 | 占失败 | 平均损失时长 | 是否必然失败 | 判定依据（原文/聚合） |
|---|---|---|---|---|---|---|
| **F1** | **阶段切换画面残留 → 假 FAIL** | **5** | **25.0%** | 墙钟 0.22–0.77 min/次；但结论作废，等价重跑一款（D 阶段实测 340–810 s） | **是**（不校验前台包名就无法避免） | 见 §1.4 的 5 段原文，其中 3 段**明确写出屏幕上是《大圣》** |
| **F2** | **DeepSeek `Thinking mode does not support this tool_choice` 400 → `llm_pause` 无限等待** | **3** | **15.0%** | 平均 **392.2 min**（5.5 + 598.2 + 572.8） | **是**（同一 tool_choice 必然 400） | 3 条 `llm_pause` trace，payload 含 `…Thinking mode does not support this tool_choice…`；日志紧接 `Pausing execution to wait for resume signal...` 后停写 |
| **F3** | 摘要 LLM 调用静默挂起 | 1 | 5.0% | 611.7 min | 未知（n=1） | 末条 trace = `llm_call/ChatOpenAI status=running` @11:10:36，此后无任何写入 |
| **F4** | `compress_history` 长阻塞 / 被杀 | 1 | 5.0% | 607.1 min | **否**（同函数另 228 次成功，最长 1677.8 s 后正常返回） | 61 条 `compress_history` 永远停在 `running`；10 次耗时 >300 s |
| **F5** | 设备掉线（USB/ADB） | 2 | 10.0% | 平均 **7.85 min**（0.0 / 15.7） | **是**（设备不在 = 任何动作不可能成功） | `error: device '89FX09M9U' not found` ×4（`qa_1114_v2/queue.log:21,26,27,29`）；`Tap failed at (983, 358)` 等 5 次；`Failed to execute launch command` 9 次 |
| F6 | ↳ 空 UI 树索引点击空转（F5 的同源放大器） | *(含于 F5)* | — | 单 session 内 **50 步 / 12 分 51 秒**（`4600dc04`，12:25:16→12:38:27） | 否（换坐标/重新截图可恢复，模型没换） | 133 次点击失败里 **121 次（91.0%）** 是 `Invalid target index N. The list is empty on this screen`，跨 11 个 session |
| **F7** | 设备侧网络阻塞 → app 自报「链接已失效」 | **6** | **30.0%** | 平均 **1.7 min**（0.23 / 0.75 / 0.77 / 1.6 / 1.9 / 4.86） | **是**（不修网络不可能进游戏） | 见 §1.6：5 款不同游戏在 4 分钟内报同一「链接已失效」 |
| **F8** | launch 后进程即死，无收尾无报错 | 1 | 5.0% | 0.3 min | 未知（n=1） | `42980182`：1 step、41 traces、`Launched app 'com.qy.yjdn1.aligames'` 后 20 秒停写 |
| **F9** | 长流程耗尽预算仍 FAIL（无进展熔断） | 1 | 5.0% | **28.2 min** | 否（有熔断可提前止损） | `a325bee8`：212 steps、`result=FAIL（未达三项全满足）`，引导 28 分钟未消失 |
| — | 游戏自身闪退/掉后台（放大器，非独立失败） | — | — | 消耗步数 | 否（relaunch 可恢复） | 17 次 `relaunch` / `dropped to the launcher`，跨 11 个 session |

> **最危险的一点**：F1（5 次假 FAIL）与 F7（6 次真 FAIL）在 `sessions.status` 上完全一样，都是「正常收尾的 FAIL」，肉眼无法区分——**F1 会直接污染质检结论**。

### 1.4 F1 证据原文（最严重的发现）

`traces/qa_1114_v2/SUMMARY.md:50` 自己记了一笔：「**屏幕残留**：阶段切换时上一款游戏画面仍在前台，导致连续 5 款拍到同一画面。已加「清场 + 回桌面 + 校验前台」前置步骤。」

我在 trace 里逐条对上了这 5 款。**其中 3 款的报告里明确写出屏幕上是《大圣》**（★），另 2 款只报「链接已失效」但耗时只有 13/14 秒（☆，推断为同一残留）：

- ★ `9dd36d7e…` @ 2026-11-15 00:28（启动《一点三国》）
  > 「启动《一点三国》(com.gzhh.ydsg.aligames) 后，游戏卡在启动/资源加载页（底部标识：**大圣-西游咸鱼常规版-专服2** / 泊然SDK-成都百云时空科技有限公司 / Cocos Creator | Newtest），画面中央直接弹出确定性失败提示「链接已失效」…设备状态栏同时显示「WLAN 未连接到互联网」」
- ☆ `676369c3…` @ 11:09:23（启动《一点三国》）→ 同上「链接已失效」，**只跑了 14 秒**
- ★ `7f6da534…` @ 11:09:57（启动《一剑断念》）
  > 「启动《一剑断念》(com.qy.yjdn1.aligames) 后停留在 Cocos Creator 启动加载页（显示「**大圣-西游咸鱼常规版-专服2**」），下载进度条为空，画面中央弹出…「链接已失效」…等待约 6 秒后画面无任何变化」
- ★ `019828f8…` @ 11:10:40（启动《斗破苍穹》）
  > 「启动《斗破苍穹：异火降世》（com.rastar.dpcqyhjs.aligames）后，启动加载界面（**大圣-西游咸鱼常规版-专服2**…）中央立即显示确定性失败提示「链接已失效」」
- ☆ `22e1762d…` @ 11:11:13（启动《冲吧勇者》）→ 同上「链接已失效」，**只跑了 13 秒**

**交叉验证**：真正启动《大圣》一次要 1.9 分钟（`6d03498f` 墙钟 1.9 min）；这 4 个判决只花了 **14/27/14/13 秒**，物理上不可能完成一次冷启动 + 资源加载。**14 秒内得出「链接已失效」的结论一定是读的旧帧。**

代价：5 个 session / 20 个失败 = **25% 的失败率是假的**；而且这 5 条假 FAIL 直接进了质检报告（如果不过人工复核，就是 5 份错误的质检结论）。

### 1.5 F2 证据链（日志原文，`traces/qa_1114/yidiansanguo/run_E.log` 末 12 行）

```
ℹ Executing Flash tool: manage_app({'action': 'launch', 'app_name': '一点三国'})
[11/14/26 11:50:09] INFO  Processing request of type CallToolRequest
ℹ Starting Hopper Agent (use_fallback=False)
[11/14/26 11:50:09] INFO  POST https://api.deepseek.com/v1/chat/completions "HTTP/1.1 400 Bad Request"
ℹ LLM call failed (unknown), retrying in 1.50s...
[11/14/26 11:50:11] INFO  POST https://api.deepseek.com/v1/chat/completions "HTTP/1.1 400 Bad Request"
ℹ LLM Error: Error code: 400 - {'error': {'message': 'Thinking mode does not support this tool_choice
  (request_id: 1f6faaa3-…)', 'type': 'invalid_request_error'}}. Pausing execution to wait for resume signal...
ℹ VisualStepSummarizer: Generated summary for Step 6: …
ℹ Waiting for LLM call response...
<<< 此后再无任何输出，文件 mtime = 2026-11-14 11:50:19 >>>
```

链条：`manage_app` → Hopper 应用名解析 → 强制 `tool_choice` → deepseek-flash 的 thinking 模式拒绝该 tool_choice → **400** → 被分类为 `category=unknown` / **`retryable=true`**（错）→ 重试 1 次 → 再 400 → `llm_pause` → 写 `.artemis_paused` → `_wait_for_resume()` 死循环等待一个**在 headless/`--standalone` 模式下根本不存在的人**。

关键代码（`artemis/services/llm.py:356-368`）：

```python
async def _wait_for_resume(pause_file: Path) -> bool:
    deadline = float(getattr(settings, "LLM_PAUSE_TIMEOUT_SECONDS", 0.0) or 0.0)
    waited = 0.0
    while pause_file.exists():
        if deadline > 0 and waited >= deadline:
            return False
        await asyncio.sleep(1)      # ← deadline<=0 时永不返回
```

`settings.LLM_PAUSE_TIMEOUT_SECONDS` 当前默认 **900.0 s**（`artemis/config/settings.py:153`），`.env` / `.env.example` **均未覆盖**。但观测到 3 次 `llm_pause` 里，`4de4e676` 与 `6ec0dd97` 都**没有任何 900 s 后放弃的日志**（不存在 `(900s) exceeded; giving up.` 字样，`llm.py:492` 会打这句）。→ **两次运行实际生效的是 `deadline <= 0`（无限等待），说明当时的进程读到的是旧版本/未加载新默认值。抓不到更直接证据，具体原因：未知。** 这条本身就是风险：**默认值来自代码常量而非显式配置，运行期无法自证。**

---

### 1.6 F7 证据：5 款不同游戏在 4 分钟内报同一个「链接已失效」

单看某一条「链接已失效」，无法区分「游戏 SDK 故障」和「设备没网」。但把时间轴排开后，归因就唯一了：

| 时间 | session | 游戏 | 报告结论 |
|---|---|---|---|
| 11-14 00:27 | `024fde65` | 大圣 | 链接已失效 + **WLAN「未连接到互联网」** |
| 11-15 11:07 | `6d03498f` | 大圣 | 链接已失效（真实跑完 1 分钟加载） |
| 11-15 11:09 | `676369c3` | 一点三国 | 链接已失效（14 s，见 §1.4） |
| 11-15 11:09 | `7f6da534` | 一剑断念 | 链接已失效（27 s，见 §1.4） |
| 11-15 11:10 | `019828f8` | 斗破苍穹 | 链接已失效（14 s，见 §1.4） |
| 11-15 11:11 | `22e1762d` | 冲吧勇者 | 链接已失效（13 s，见 §1.4） |
| 11-15 11:20 | `1504b472` | 大圣 | 链接已失效 |
| 11-15 11:23 | `2e60408c` | 大圣 | 链接已失效 |
| 11-15 13:29 | `a01e0125` | 大圣 | 链接已失效 |
| 11-14 12:07 | `db3c84d2` | 一剑断念 | 「网络错误阻塞在进入游戏场景阶段」 |

**推理**：5 个不同厂商、不同 SDK、不同引擎的游戏，在 4 分钟内集体报同一句「链接已失效」——**不可能同时出现 5 个独立的产品缺陷**，共同因子只能是设备侧网络。因此其中至少 6 条（`024fde65`/`6d03498f`/`1504b472`/`2e60408c`/`a01e0125`/`db3c84d2`）是**网络阻塞导致的假缺陷结论**，外加 §1.4 的 5 条残留假结论。**合计 11 条「链接已失效」，全部不是游戏的问题。**

> 补充观测：`traces/qa_1114_v2/dasheng/run_BC_pre_networkfix.log` 名字暗示「网络修复前」，但把它和修复后的 `run_BC.log` 逐行 diff，**唯一差异是 prompt 新增了规则 6（"启动应用时**必须**使用包名…"）——这是 Hopper 应用名解析的修复，不是网络修复**。修复后 `a01e0125` 依然报「链接已失效」。→ **网络问题到 11-15 13:29 仍未真正修复，只是被 prompt 掩盖。**

---

## 2. 静默卡死（问题 2）

### 2.1 「进程还活着但日志不再增长」的次数

| 判定方式 | 次数 |
|---|---|
| **进程级猝死（`end_session` 未执行）** | **7**（见 §1.2） |
| 其中日志**末行即断点**（无任何收尾行） | **6**（`42980182` 末行是 launch 结果，也属截断） |
| 只在 1 个日志里能抓到「末行 = `Waiting for LLM call response...`」（该句每轮都打，只有作为**末行**才是死锁标记） | 1（`yidiansanguo/run_E.log`） |
| 末行 = `Chunk capsule chunk:8-14 …(76%).`（压缩中途） | 1（`dasheng/run_BC.log`） |
| 末行 = `llm_call/ChatOpenAI status=running` | 1（`715d27b7`） |
| trace 侧：`compress_history` 永远 `running` | **61 条**（占该函数全部调用的 **21.1%**，289 次中 61 次未闭环） |
| trace 侧：`FlashRunner` 永远 `running` | 6 |
| trace 侧：`hopper` 永远 `running` | 3 |
| trace 侧：`ChatOpenAI` 永远 `running` | 2 |
| trace 侧：`manage_app` 永远 `running` | 3 |
| trace 侧：`wait_for_delay` 永远 `running` | 1 |
| **`running` 状态 trace 合计** | **76（占 30,569 traces 的 0.25%）** |

### 2.2 平均卡多久才被发现（分布）

必须区分两个不同的延迟：

**(a) 检测延迟 = 最后一条日志 → 进程被终止**

| session | 最后活动 | 发现方式 | 检测延迟 |
|---|---|---|---|
| `715d27b7` | 11:10:36 | **无** | **未发现**（611.5 min 空转） |
| `5a79d7b3` | 11:18:28 | **无** | **未发现**（603.6 min） |
| `6ec0dd97` | 11:24:15 | **无** | **未发现**（597.8 min） |
| `4de4e676` | 11:50:19 | 看门狗 240 s（`qa_1114/queue.log`）→ 下一款 11:54:27 启动 | **240 s** |
| `fc025886` | 11:14:28 | 看门狗（会话墙钟 5.5 min） | **~316 s** |
| `42980182` | 11:22:49 | **无**（队列继续下一款） | 未发现 |
| `af880a5d` | 12:41:57 | 无看门狗，`rc=1` 直接返回 | **~10 s**（唯一良性路径） |

分布：**未发现 5/7 = 71.4%**；≤300 s 2/7 = 28.6%；>300 s 0%。
（若把「未发现」按实际空转计，平均检测延迟 = (611.5+603.6+597.8+4+5.3+0.3+0.2)/7 ≈ **260 min/session**。）

**(b) 记录收尾延迟 = 最后一条日志 → `sessions.end_time` 落库**

4 个挂死 session **全部 = 9.53–10.19 小时**，且都精确落在 **21:22:04 同一秒**（见 §0.6）。→ **这 4 条记录从未被系统闭环，是被外部批量补写的。**

### 2.3 现有 300 s 看门狗够不够？——分三个层面回答

先看实现（`scripts/qa_1114_queue.py:115-152`）：

```python
while proc.poll() is None:                    # ← 只监视 uv 这一个 PID
    time.sleep(10)
    size = log.stat().st_size if log.exists() else 0
    if size != last_size:
        last_size, last_growth = size, time.time()
    elif time.time() - last_growth > stall_s:  # stall_s = 300（11-14 部署版本为 240，见 queue.log 原文）
        kill_tree(proc); break
    if time.time() > deadline:
        kill_tree(proc); break
```

**结论：阈值本身勉强够用，但覆盖率与判据都不够。**

**(1) 阈值：只有 20.3% 余量，已经贴近误杀线。**
实测「合法但不产日志」的最长间隔 = **239.2 s**（`872aa6bc` @ 21:43:23→21:47:22），原因找到了——**是模型自己要求的 `wait_for_delay({'time_in_ms': 240000})`**：

```
ℹ Executing Flash tool: wait_for_delay({'time_in_ms': 240000})
ℹ VisualStepSummarizer: Generated summary for Step 21: …
[11/14/26 21:47:22] …       ← 239 秒后才有下一行
```

`wait_for_delay` 的时长分布（成功调用，按 ms 降序前 8）：`240000 ×2`、`180000`、`150000`、`120000`、`90000`、`80000 ×3`、`60000 ×2`。**没有任何上限约束**。只要模型某次写成 `300000`，看门狗就会杀掉一个完全健康的任务。300 s / 239.2 s = **1.25 倍**，工程上不可接受。

**(2) 判据：只看「文件字节数」，抓不到「缓慢增长型」阻塞。**
`compress_history` 单次最长 **1677.8 s（27.9 分钟）**，全量 289 次里 **10 次 > 300 s**、平均 91.2 s。它运行时会零星打 `Chunk capsule …`，字节数在涨 → 看门狗永远不触发；而它恰恰是 `5a79d7b3` 猝死的地方。**这类「输出密集但无进展」的阻塞对字节看门狗完全不可见。**

**(3) 覆盖：71.4% 的猝死发生在看门狗射程之外。**
`while proc.poll() is None` 只盯 `uv` 这一个 PID。而 `uv run python -m artemis.main` 一旦 `uv` 退出/被 `SIGKILL`，`python` 子进程成为孤儿（`start_new_session=True` 让它自成会话，`kill_tree` 用 `os.killpg(os.getpgid(proc.pid), SIGKILL)` 只能命中 `uv` 自己的进程组），**孤儿继续握 ADB，看门狗却已经退出循环**。这正好解释：`715d27b7`/`6ec0dd97` 出现在 `queue.log` 首条记录（11:36:14）**之前**——它们是手工起的、根本不在任何看门狗下。

**量化孤儿成本**：`qa_1114/dasheng/run_BC.log`（`5a79d7b3`）的 `recording.mkv` 大小 **8.7 GB**，文件 mtime = **21:04**，而 session 在 **11:18:28** 就停写了——**孤儿把设备端 `screenrecord` 挂了 9.75 小时，录了 8.7 GB 空闲帧**。同批 `qa1114_yidiansanguo_E/recording.mkv` **8.2 GB**，mtime 同样 21:04。

---

## 3. 重试与自愈（问题 3）

### 3.1 重试总量

| 指标 | 数值 |
|---|---|
| `llm_call` traces 总数 | 10,044 |
| 其中 `FlashRunner`（真实决策轮） | **2,312** |
| `llm_retry`（Artemis 侧显式重试） | **13**，跨 **11 个 session**，`max_retries=2` |
| `llm_fallback`（切备用模型） | **2** |
| `llm_gave_up`（彻底放弃） | **4** |
| `llm_stream_reset` | **1** |
| `llm_pause`（升级为无限停顿） | **3** |
| `APIConnectionError`（瞬时网络） | **6 次调用 / 5 个 session** |

**重试后成功比例**：
- `llm_retry` 13 次 → 涉及 **11 个 session**：**6 个最终 `completed`、5 个 `failed`**。失败那 5 个里，3 个（`6ec0dd97`/`4de4e676`/`fc025886`）是重试后仍 400 并升级为 `llm_pause`，2 个（`db3c84d2`/`4600dc04`）是重试对象本身与最终死因无关（网络 / 设备）。→ **重试成功率 6/11 = 54.5%（按 session）；但凡是 400 类错误，重试 0/3 成功。**
- `APIConnectionError` 6 次 → 5 个 session 中 **4 个仍然 `completed`**（`4ace4c15`、`994c452e`、`8d2e7675`、`09b7af9a`），1 个（`db3c84d2`）因网络阻塞 FAIL。→ **瞬时连接错误的重试收益 4/5 = 80%。**
- `llm_gave_up` 4 次 = 100% 失败（没有一次从 gave_up 里恢复）。

### 3.2 「必然失败」与「瞬时可恢复」的分界

| 错误签名 | 次数 | 现有分类 | 应然分类 | 必然失败？ |
|---|---|---|---|---|
| `400 Thinking mode does not support this tool_choice` | 6 次 API 调用 / 3 session | `category=unknown`, **`retryable=true`** ❌ | `bad_request`, `retryable=false`，且**不得进 pause** | **是** |
| `400 height(1) or width(1) must be larger than 28 for Qwen 3 VL models` | 4 次 / 1 session | `category=unknown`, **`retryable=true`**, `handover=fallback` ❌ | 应识别为**输入帧无效** → 重新截图，**不是重试 LLM** | **是**（同一张 1×1 图重试必然再 400） |
| `400 API key not valid`（gemini-robotics-er-2-preview） | 2 次 / 1 session | `category=authentication`, `retryable=false` ✅ | 保持，但**必须在启动时体检** | **是** |
| `Failed to execute launch command for <pkg>` | **9**（3 轮 × 3 attempt） | 内置 3 次 attempt 后放弃 ✅ | 保持，但应先判「设备在线」而非盲试 3 次 | **是**（设备不在时） |
| `APIConnectionError: Connection error.` | 6 次 / 5 session | `retryable=true` ✅ | 保持 | **否（瞬时）** |
| `Invalid target index N. The list is empty on this screen` | **121** 次 / 11 session | 直接返回失败给模型 | **应是状态信号**：树为空 ⇒ 立即重新抓树/换视觉定位，且**同一错误 ≥3 次即熔断** | **否**（可恢复，但当前不恢复） |
| `error: device '89FX09M9U' not found` | 4 | 无分类，队列继续跑 | 必须 **hard stop + 等设备** | **是** |

**最严重的一条**：`llm_gave_up` 里那条 Qwen 400 的 payload 明确写着 `"retryable": true`——**一个 400 输入非法被判成可重试**。它触发的连锁是：Qwen 400→重试→`llm_gave_up`→`handover=fallback`→Gemini→`API_KEY_INVALID`→`llm_gave_up`（`retryable: false`）→整条视觉定位链路死掉。**兜底模型本身是坏的（key 无效），所以「fallback」在当前配置下等于没有兜底。**

### 3.3 自愈能力的真实边界

| 故障 | 能否自愈 | 实测证据 |
|---|---|---|
| 瞬时网络抖动 | ✅ 能 | 4/5 session 带 `APIConnectionError` 仍 completed |
| 游戏闪退/掉桌面 | ✅ 能（靠模型自己） | 17 次 `relaunch` / `dropped to the launcher`，11 个 session 继续跑完 |
| 空 UI 树 | ⚠️ 理论能，实际不能 | 121 次同一错误，最长在一个 session 里连撞 **50 步 / 12 分 51 秒**（`4600dc04`，12:25:16→12:38:27） |
| USB 掉线 | ❌ 不能 | 掉线后仍继续跑 3 次 launch + 55 次点击，全部失败 |
| 400 / 401 / 关键帧非法 | ❌ 不能 | 见上表 |
| LLM 停顿 | ❌ 不能 | `_wait_for_resume` 等不到人 |

---

## 4. 设备状态前置校验缺失（问题 4）

**现状**：`artemis/agents/flash/runner.py`（1,179 行）中**不存在任何 preflight / device health 校验**（对 `preflight|validate|check_device|is_ready|battery|wifi|foreground|currentFocus|health` 的 grep 只命中注释性 helper 名）。唯一的设备门禁在队列脚本 `run_phase()` 里，而且只有两步（`scripts/qa_1114_queue.py:118-121`）：

```python
fg = reset_device()                 # force-stop 其它游戏 + KEYCODE_HOME + dumpsys window
shot(gdir / "shots" / f"{phase}_start.png")   # 截完就丢，不校验
```

`reset_device()` **拿到了前台窗口名，但只打印不校验**；`shot()` 的异常被 `except: pass` 静默吞掉。所以「校验」实际上不存在。

### 应校验但未校验的项目 × 真实故障对应

| # | 应校验项 | 现状 | 缺校验导致的**具体**故障（真实案例） |
|---|---|---|---|
| **D1** | **前台包名 == 目标包名**（`dumpsys window \| grep mCurrentFocus`） | 取了值，**不比较** | **F1 的 5 次假 FAIL**（`019828f8` 启动斗破、屏幕是《大圣》；`7f6da534` 启动一剑断念、屏幕是《大圣》）。如果校验「前台 pkg != 目标 pkg ⇒ 不进入决策循环」，这 5 次会在 6 秒内以 INFRA_ERROR 中止而不是产出 5 份错误质检结论 |
| **D2** | **ADB 设备在线且 serial 匹配**（`adb devices`） | 只在 `reset_device()` 里间接发生，返回值不判空 | `af880a5d`：`[reset] BC 前前台: `（**空字符串**）+ `error: device '89FX09M9U' not found` ×4，队列仍继续启动 phase，10.0 s 后 `rc=1` |
| **D3** | **屏幕尺寸 + 方向**（`wm size` / `dumpsys input`） | `_dims()` 在 `ctx.device` 为空时**静默 fallback 到 1080×2400**（`adb.py:121-125`） | Pixel 3 实际 1080×2160。`一剑断念` 运行时旋转为 **2160×1080**（`run_D.log`/`run_E.log`：`Retrieved Android screen dimensions: 2160x1080`）。`_to_px()` 按当前 `device_width` 换算，**若旋转发生在会话中途而 `device_width` 未刷新，归一化坐标会整体错位**。观测到 `input tap 2084 710` 这类横向超界坐标 104 次（8.5%，全部在 `一剑断念`），虽在其横屏下合法，但**一旦回到竖屏就是必错的越界点击**，而系统没有任何 assertion 拦住它 |
| **D4** | **网络真 VALIDATED**（`dumpsys connectivity` / `NetworkCapabilities.NET_CAPABILITY_VALIDATED`） | **完全没有** | 设备 `captive_portal_http_url = null` → 走 `gstatic.com` 校验失败 → WiFi 长期 `partialConnectivity`。表现为**游戏内**报「链接已失效」：`9dd36d7e` 报告原文「设备状态栏同时显示『WLAN 未连接到互联网』」。代价：11-14 00:27 → 11-15 13:29 之间 **11 个 session** 报「链接已失效 / 网络错误」，其中 5 个是残留假 FAIL（§1.4）、6 个是真网络阻塞（§1.6）——**11 条都不是游戏缺陷** |
| **D5** | **screenshot 帧有效性**（尺寸 ≥ 28px、非纯色、与上一帧 dhash 不同） | `get_screenshot()` 无任何校验（`third_party/mobile_use/clients/ui_automator_client.py:376-393`）：adb 失败就 fallback 到 `device.screenshot()`，**返回值直接 `Image.open()` 用** | **1×1 像素帧**被送进 Qwen → `400 height(1) or width(1) must be larger than 28`。payload 里的 base64 已解码确认为 1×1 PNG。这就是「USB 掉线 → 纯绿/空帧」的可见后果。整个链路 5 次调用全废，还触发了错误的 fallback 链 |
| **D6** | **helper / 设备侧能力存活**（uiautomator2 server、`input`、`screenrecord`、wakelock） | 无 | **32/32 个 run 日志**都有 `⚠ Could not inspect the shared screen-bright wake lock on 89FX09M9U: Unknown command: set-wakelock` —— 100% 失败且被一直忽略。屏幕可能休眠，而 agent 无从判断「黑屏是游戏黑屏还是设备睡了」 |
| **D7** | **电量 / 温度 / 充电状态** | 无 | 未知（DB 与日志都没有电量记录；11-13 的 12 个冒烟用例只在 UI 上「看电池」，没有落库）。**不能编造，标未知。** 但可确认风险存在：单次任务最长 28.2 min（`a325bee8`），4 轮累计 44.8 h 连续跑机，掉电/降频会导致「游戏无响应」被误判为产品缺陷 |
| **D8** | **启动前 `am force-stop` 目标包之外的所有测试包 + 校验残留** | `reset_device(exclude)` 只 force-stop `GAMES` 里 5 个包 | 若残留的是**非清单内**app（如九游商店 `cn.ninegame.gamemanager`、`com.google.android.apps.maps`），就漏网。logcat 抓到 `11-15 14:29:21 ANR in com.google.android.apps.maps` |

---

## 5. 资源泄漏（问题 5）

### 5.1 磁盘（当前实测）

| 项 | 规模 |
|---|---|
| `traces/` 总占用 | **30 GB** |
| `recording.*` 文件 | **124 个 / 27.2 GB** |
| **其中 2 个孤儿录制** | **23.4 GB（86.0%）**：`qa1114_dasheng_BC/recording.mkv` **8.7 GB** + `recording.mp4` 5.1 GB；`qa1114_yidiansanguo_E/recording.mkv` **8.2 GB** + `recording.mp4` 1.4 GB |
| `data_engine.db` | 1.7 GB |
| `traces/images/` | 562 MB / 2,067 张 |
| 单 trace 目录数 | 288 |
| 0 字节截图 | 4（`qa_1114_v2/_round1/chongba/shots/{BC_start,BC_end,D_start}.png`、`.../doupo/shots/E_end.png`） |

**孤儿的直接证据**：`qa1114_dasheng_BC/recording.mkv` 的 mtime = **21:04**，而 `5a79d7b3` 的最后一条 trace 是 **11:18:28**。→ **宿主进程在 11:18 就死了，设备端 `screenrecord` 继续录了约 9.75 小时**，产出 8.7 GB 空闲帧；随后（21:21）还被 ffmpeg 转成 5.1 GB 的 mp4。**一个 5.5 分钟的 session 产出 14 GB 垃圾，占全部 traces 空间的 46.7%。**

### 5.2 孤儿进程

| 项 | 状态 |
|---|---|
| 当前残留（`ps` 快照） | `artemis.main ui --no-open` 1 个（PID 50596，已运行 **29 h 29 min**，属预期常驻服务）；**无遗留 `uv run`、无遗留 `artemis.main run`、无遗留 `screenrecord`** |
| 历史孤儿证据 | ① `5a79d7b3`/`4de4e676` 的 8.7 GB / 8.2 GB 录制跑满 9.75 h（宿主已死，设备端任务未死）② `traces` 里 76 条 `running` trace 未闭环 ③ 4 条 session 行靠外部批量补写才闭环 |
| ADB 争用 | 未观测到显式等待锁的日志（`DeviceExecutionLock` 是 **PID + process_created_time 感知**的，`device_lock.py:71-90`，能识别陈旧持有者），所以「孤儿持锁卡死下一位」在当前版本**未复现**；风险来自孤儿进程**直接对设备发命令**（争用 ADB server socket），表现是 `Tap failed at / Failed to execute launch command`，共 14 次 |

### 5.3 残留 app

- 队列的 `reset_device()` 只处理 `GAMES` 字典里 5 个包。**九游商店、地图、系统 UI 等不在清单内的 app 会残留**（观测到 `ANR in com.google.android.apps.maps`）。
- 游戏自身掉后台 **17 次 / 11 个 session**（`relaunch`、`dropped to the launcher`），最多 `a325bee8` 4 次。这类「残留/闪退」在 `status` 上不可见，只能靠 step 摘要文本统计 → **当前没有结构化字段记录 app 存活状态**。

### 5.4 日志 / 图片堆积

- 单次 phase 的 `logcat_*.txt` 可达 **2.8 MB**（`qa_1114_v2/dasheng/logcat_BC.txt` 2,829,506 B），累计 13 个 phase 均有 `logcat_{phase}.txt` + `crash_{phase}.txt`，无轮转、无保留策略。
- `run_*.log` 单文件最大 **321 KB**（`qa_1114/doupo/run_D.log`）；`body_len` 最大 310,794 字符（`queue_status_round1.json` 里一点三国 D 阶段）。
- 无 TTL / 无配额 / 无清理任务（`scripts/` 下无任何清理脚本；`traces/` 从 11-13 到 11-15 两天涨到 30 GB，即 **~15 GB/天**）。

---

## 6. 五条优化建议

> 排序原则：先消除「会产出错误结论」的（P0），再消除「烧时间」的（P1），最后做资源卫生（P2）。

### 建议 1（P0）· 阶段级前置门禁 `preflight_gate()`：不过门禁绝不开跑

**做的事**：在 `run_phase()` 真正启动 `uv run python -m artemis.main run` **之前**，按顺序硬校验，任一失败即 `verdict=INFRA_ERROR` 并记录原因码、**不消耗游戏配额**：
1. `adb -s <serial> get-state` == `device`（D2）
2. `wm size` 读到的 (w,h) 与期望一致、且方向与会话一致，否则刷新 `ctx.device.device_width/height`（D3）
3. `dumpsys window | grep mCurrentFocus` **必须**等于目标包名；不等则 `force-stop` + `HOME` + 重试 2 次，仍不等 → 中止（D1）
4. `adb shell am force-stop <其它所有测试包>`，并校验 `mCurrentFocus` 为 launcher（D8）
5. `dumpsys connectivity` 中当前网络的 `NetworkCapabilities` 含 `NET_CAPABILITY_VALIDATED`（D4）
6. `adb shell uptime` + `dumpsys battery` 记录电量/温度基线，低于阈值告警（D7）
7. `screencap` 一次，校验 `≥ 28×28` 且非纯色、且与上一帧 dhash 不同（D5）
8. helper 探测：`uiautomator2` ping + `input --help` 可用（D6；`set-wakelock` 若不可用则降级为 `svc power stayon true`）

**能消除**：F1（5 次假 FAIL，25% 失败率）、F5 的一半（设备不在线时 10 秒内拒绝而非盲跑 15.7 min）、F7（网络不 VALIDATED 时直接标 ENV_BLOCKED，而不是产出「游戏链接已失效」的错误结论）、F6 的诱因（空 UI 树 / 无效帧时先重新抓帧再决策，而不是拿 1×1 图去点）。

**实现成本**：低。~250 行纯 Python，无新依赖；`reset_device()` 已经把 `dumpsys window` 打通，只是把「打印」改成「比较」。1–2 人日（含 8 个 case 的回归测试）。

**风险**：① `mCurrentFocus` 在部分机型/游戏有 1–2 s 抖动，需给 3 次重试避免误拦（当前 `time.sleep(2.5)` 已接近临界）。② 网络 VALIDATED 校验在 `captive_portal_http_url=null` 的设备上**会一直失败**——这正是我们要的，但必须提供「显式豁免 + 记入报告」的开关，否则会挡住所有离线场景（如纯 UI 巡检）。③ 增加了 phase 启动延迟约 3–5 s（可接受）。

---

### 建议 2（P0）· 修正 LLM 错误分类学：400 永不重试、永不 pause；帧非法不重试 LLM

**做的事**：
1. 在 `artemis/services/llm.py` 的错误分类器里，把 **HTTP 400 / 422 一律归为 `bad_request` + `retryable=false`**（当前 `Thinking mode does not support this tool_choice` 与 `height(1) or width(1) must be larger than 28` 都被打成 `category=unknown, retryable=true`）。
2. **`bad_request` 永不进入 `_handle_llm_pause_and_resume()`**——直接 `raise LLMPermanentError`。`llm.py:396-400` 的 docstring 已经写了这条原则（"Non-retryable categories (auth, bad request) raise LLMPermanentError immediately"），**是实现没跟上注释**。
3. `LLM_PAUSE_TIMEOUT_SECONDS`：**默认改为有限值且必须可自证**。headless / `--standalone` / 有 `ARTEMIS_TEST_NAME` 时强制 `=0 → 立即失败`（不允许 pause）；交互模式保留 900 s。启动时把生效值打一行日志（当前 3 次 pause 里 2 次「等 10 小时」而代码默认 900 s，运行期无法自证到底读了什么）。
4. 视觉定位把「图片尺寸 < 28px」识别为 **`invalid_frame` 而非 `bad_request`**：立即重新 `screencap`（最多 3 次，间隔 500 ms），3 次仍无效 → 上报「设备帧异常」并中止阶段，**不再向任何 VL 模型发请求**。
5. 兜底链路加启动体检：`llm_fallback` 之前先做一次 cheap ping（如 1×1 文本调用），失败则标记该 provider `unavailable` 并把 `handover` 改为 `abort`，避免 `API_KEY_INVALID` 之后还把 4 秒浪费在死模型上。

**能消除**：F2（3 次 / 15% 失败，平均 392 min）、F5 中的视觉侧级联（4 次 Qwen 400 + 2 次 Gemini 401 = 6 次无效 API 调用）、以及全部 `llm_gave_up → fallback → 也失败` 的空转。

**实现成本**：低。分类器是集中式的，改动约 80–120 行 + 单测；已有 `tests/unit/test_llm_gateway.py` 可扩展（它已经会 monkeypatch `LLM_PAUSE_TIMEOUT_SECONDS`）。0.5–1 人日。

**风险**：① 把 400 一律判永久，可能把「provider 偶发 400 但重试能过」的极少数情况也判死 → 用「同类 400 连续 2 次才升级为永久」折中。② standalone 下禁 pause 会让某些原本「等人点继续」的调试流程失效 → 用 profile 开关隔离。③ 重新截图会改变「同一帧多次询问」的缓存假设，可能让 `ask_explorer` 的截图 hash 缓存失效率上升（性能小退，可接受）。

---

### 建议 3（P0）· 无进展熔断 + 空 UI 树降级

**做的事**：
1. **同错熔断**：在 `FlashRunner` 每轮记录 `(action_name, error_signature)`，**同一 `error_signature` 连续出现 3 次**即注入一条系统消息强制换策略（"索引点不了，改用坐标或重新截图"），**连续 8 次直接 `report_task_status(result=FAIL)` 并标 `cause=action_stuck`**。当前 `4600dc04` 连撞 **50 步 / 12 分 51 秒**、`a325bee8` 烧 28.2 分钟才收尾。
2. **空树降级**：捕获到 `The list is empty on this screen` 时，**不是返回错误给模型**，而是立刻 `dump_hierarchy` 重试一次 → 仍空则**跳过索引路径、强制走视觉定位**（`ask_explorer`），并把「本步 UI 树不可用」写进 step metadata（供事后统计「无树率」）。
3. **画面无变化熔断已有雏形**（prompt 规则 5「连续 8 次操作画面无任何变化，判定为卡死」），但**只在 prompt 里、不在代码里**。把它下移到 runner：用 `extra_metadata.pre_image_dhash` 与 `post_image_dhash` 的汉明距离，**连续 8 步 ham=0 即熔断**（`ACCURACY.md` 已证明 `ham=0` 有 308 步/14.2%，是可靠信号）。

**能消除**：F6（`4600dc04` 连撞 50 步 / 12 分 51 秒）+ F9（`a325bee8` 烧满 28.2 min 才收尾）、121 次 `list is empty` 空转、以及「画面无变化却继续烧 token」的隐性浪费。

**实现成本**：中低。dhash 已在 `steps.extra_metadata` 里现成；熔断器约 150 行。1–2 人日。

**风险**：① 熔断过早会把「需要多步铺垫的长流程」（如连续 5 次点剧情对话推进）误判为卡死 → 阈值必须按 action 类型分档（`click` 严、`wait_for_delay` 宽）。② 空树强制走视觉定位会显著提高 `ask_explorer` 调用量 → Qwen 成本上升（`ACCURACY.md` 已指出 126 次「无 UI 树却用索引点击」占索引点击 53%，一旦全部转视觉，成本增幅需与 `COST.md` 对齐评估）。

---

### 建议 4（P1）· 看门狗升级为「三合一」：进程树 + 进度心跳 + 活动感知阈值

**做的事**：
1. **盯进程树而不是盯 uv**：`proc.poll()` 改为 `psutil.Process(proc.pid).children(recursive=True)` 递归存活判断；`kill_tree()` 在 `killpg` 之外补一次「按 `ARTEMIS_SESSION_ID` 反查残留 PID」的兜底收割；并在**启动前**先扫一遍 `pgrep -f "artemis.main run"`，发现残留**先杀再加锁**（对应「孤儿占 ADB」）。
2. **进度心跳替代字节数**：让 runner 每轮 `record_trace(heartbeat)`（或复用已有 `Flash Turn N` 行），看门狗读**最后一条 `Flash Turn` 的语义时间戳**而不是文件 mtime，从而识别「`compress_history` 输出密集但无进展」。
3. **阈值改为活动感知**：基准 `stall_s = 300` → 改为 `max(180, 1.6 × 本次会话已见最长合法静默)`；并把模型请求的 `wait_for_delay` **上限硬限幅为 120 s**（当前实测已用到 240 s，直接顶穿 300 s 阈值），超过则拆成多次等待，每 30 s 打一行心跳。
4. **SIGKILL 后必须补写收尾**：在 `kill_tree()` 之后**由看门狗进程自己**执行 `UPDATE sessions SET status='failed', end_time=<kill时刻> WHERE session_id=? AND end_time IS NULL`（或调用一个 `artemis session reap` 子命令），把「记录收尾延迟 9.5–10.2 h」降到 0。

**能消除**：§2.2 里 5/7「未发现」的猝死（覆盖率 28.6% → ~100%）、F3/F4 的 10 小时量级空转、以及 `sessions` 表 `end_time` 被外部批量污染的问题。

**实现成本**：中。`compress_history` 的耗时分布（avg 91.2 s / max 1677.8 s）需要先做初步统计（本文已提供 SQL）；`psutil` 已在 `device_lock.py` 里用作可选依赖。2–3 人日。

**风险**：① 递归 children 遍历在 macOS 上对大量短命子进程有开销 → 采样间隔保持 10 s 即可。② `wait_for_delay` 限幅 120 s 会改变模型行为（可能让模型改点更多次「等待」而不是一次长等），需观察 1 轮 TURN 数是否上升。③ 看门狗自己写 DB 会引入第二个写入者 → SQLite 并发写风险，应走单条短事务 + `busy_timeout`，或改为写一个 `.reap.json` 由下次启动读取。

---

### 建议 5（P2）· 资源生命周期与会话绑定 + TTL 回收

**做的事**：
1. **录制跟随 session 生命周期**：`screenrecord` 的启动/停止改为「会话结束时由 orchestrator 用 `adb shell pkill -f screenrecord` 兜底」；并给录制**硬上限**（如 30 min 或 2 GB，先到先停），避免孤儿录 9.75 h。
2. **退出路径全覆盖**：`try/finally` + `atexit` + `SIGTERM`/`SIGINT` handler 里统一 `stop_recording()` / `end_session()`；对 `SIGKILL`（不可捕获）由建议 4 的看门狗补写。
3. **TTL 回收**：`traces/` 加一个 `artemis traces gc --max-age 7d --max-size 20GB --keep-failed`；**优先删「孤儿录制」**（判定：`recording.*` mtime 比该目录内最后一条 trace 晚 >1 h，或 size > 1 GB 且所在 session 墙钟 < 10 min）。按当前数据，这一条能立刻回收 **23.4 GB**。
4. **日志限额**：`logcat_{phase}.txt` 单文件上限 2 MB（`logcat -d | head -c 2000000`），`crash_*.txt` 上限 256 KB；`shot()` 的 `except: pass` 改为记录失败原因并把 0 字节帧计数上报。

**能消除**：§5 的 86% 磁盘浪费、0 字节截图静默、`except: pass` 掩盖的采集失败。

**实现成本**：低。~150 行脚本 + 一个 gc 子命令。0.5 人日。**投入产出比最高**（一条命令回收 23.4 GB）。

**风险**：① 录制硬上限可能截断「确实需要长录像取证」的崩溃复现 → 保留 `--keep-failed` 白名单。② TTL 误删证据影响质检可追溯性 → gc 默认 `--dry-run`，且只删 `recording.*` 与 `logcat_*`，**永不删 `crash_*`、`*.db`、失败 session 的截图**。③ `pkill -f screenrecord` 在多设备并发时会误杀其他设备 → 必须带 `-s <serial>`。

---

## 附录

### A. 关键 SQL

```sql
-- A1 session 状态分布（成功率）
SELECT status, count(*) n,
       round(100.0*count(*)/(SELECT count(*) FROM sessions),1) pct
FROM sessions GROUP BY status ORDER BY n DESC;

-- A2 按天失败率
SELECT date(start_time,'unixepoch','localtime') d, status, count(*) n
FROM sessions GROUP BY d, status ORDER BY d;

-- A3 trace 状态分布（running = 未闭环 span，猝死代理指标）
SELECT status, count(*) n, round(100.0*count(*)/(SELECT count(*) FROM traces),2) pct
FROM traces GROUP BY status ORDER BY n DESC;

-- A4 失败 trace 按 type/name
SELECT type, name, count(*) n, round(100.0*count(*)/164,1) pct
FROM traces WHERE status='failed' GROUP BY type,name ORDER BY n DESC;

-- A5 猝死 vs 正常收尾
SELECT
  sum(CASE WHEN EXISTS(SELECT 1 FROM steps st WHERE st.session_id=s.session_id
        AND st.last_execution_result LIKE '%Task completed with final report%') THEN 1 ELSE 0 END) clean_report,
  sum(CASE WHEN NOT EXISTS(SELECT 1 FROM steps st WHERE st.session_id=s.session_id
        AND st.last_execution_result LIKE '%Task completed with final report%') THEN 1 ELSE 0 END) abrupt_death
FROM sessions s WHERE s.status='failed';

-- A6 ★检测外部批量补写 end_time（同一秒关闭多条）
SELECT datetime(end_time,'unixepoch','localtime') closed_at, count(*) n,
       group_concat(substr(session_id,1,8)) sids
FROM sessions WHERE end_time IS NOT NULL
GROUP BY round(end_time) HAVING n>1 ORDER BY n DESC;

-- A7 挂死 session：墙钟 vs 实际活动 vs 静默尾长
WITH t AS (SELECT session_id, max(timestamp) last_ts, count(*) n FROM traces GROUP BY session_id)
SELECT s.session_id, s.status, s.pid,
  round((t.last_ts - s.start_time)/60.0,1)  work_min,
  round((s.end_time - t.last_ts)/60.0,1)    idle_min,
  round((s.end_time - s.start_time)/60.0,1) wall_min, t.n traces
FROM sessions s LEFT JOIN t USING(session_id) ORDER BY s.start_time;

-- A8 页内最大静默间隔（看门狗阈值依据）
WITH g AS (SELECT session_id, timestamp,
       lag(timestamp) OVER (PARTITION BY session_id ORDER BY timestamp) prev FROM traces),
d AS (SELECT session_id, prev, timestamp, timestamp-prev gap FROM g WHERE prev IS NOT NULL)
SELECT session_id, round(gap,1) gap_s,
       datetime(prev,'unixepoch','localtime') from_ts, datetime(timestamp,'unixepoch','localtime') to_ts
FROM d WHERE gap > 60 ORDER BY gap DESC LIMIT 40;

-- A9 点击失败分类
SELECT CASE
    WHEN payload LIKE '%The list is empty on this screen%' THEN 'list_empty(UI树为空)'
    WHEN payload LIKE '%Active index range%'                THEN 'active_index_range'
    WHEN payload LIKE '%Tap failed at%'                     THEN 'tap_failed(ADB)'
    WHEN payload LIKE '%Invalid target format%'             THEN 'invalid_format_none'
    ELSE 'other' END cat,
  count(*) n, round(100.0*count(*)/133,1) pct
FROM traces WHERE status='failed' AND type='action' AND name='click'
GROUP BY cat ORDER BY n DESC;

-- A10 compress_history 阻塞规模（看门狗盲区）
SELECT status, count(*) n, round(min(duration),1) min_s, round(avg(duration),1) avg_s,
       round(max(duration),1) max_s, sum(CASE WHEN duration>300 THEN 1 ELSE 0 END) over300
FROM traces WHERE name='compress_history' GROUP BY status;

-- A11 错误签名 → session 映射（把 payload LIKE 换成具体错误串）
SELECT session_id, name, status, count(*) n,
       datetime(min(timestamp),'unixepoch','localtime') t
FROM traces WHERE payload LIKE '%Thinking mode does not support%'
GROUP BY session_id,name,status ORDER BY t;

-- A12 重试 / 放弃 / 暂停 / 兜底总量
SELECT name, status, count(*) n FROM traces
WHERE name IN ('llm_retry','llm_fallback','llm_gave_up','llm_pause','llm_stream_reset')
GROUP BY name,status ORDER BY n DESC;

-- A13 wait_for_delay 时长分布（看门狗误杀风险）
SELECT json_extract(payload,'$.args.time_in_ms') ms, count(*) n
FROM traces WHERE name='wait_for_delay' AND status='success'
GROUP BY ms ORDER BY CAST(ms AS INTEGER) DESC LIMIT 15;

-- A14 最慢 trace（定位长阻塞点）
SELECT type, name, round(duration,1) d, datetime(timestamp,'unixepoch','localtime') t
FROM traces WHERE duration > 60 ORDER BY duration DESC LIMIT 20;
```

### B. 关键 grep / shell

```bash
# B1 看门狗实际触发次数与阈值（11-14 部署版是 240s，非当前代码的 300s）
grep -h "watchdog\]" traces/qa_1114/queue*.log traces/qa_1114_v2/queue*.log | sort | uniq -c

# B2 设备掉线
grep -n "not found" traces/qa_1114_v2/queue.log
#   → error: device '89FX09M9U' not found   (4 行：L21,26,27,29)

# B3 找「日志末行 = 死锁标记」的日志（每轮都会打 Waiting，只有作为末行才是卡死）
for f in traces/qa_1114_v2/*/run_*.log traces/qa_1114/*/run_*.log; do
  last=$(tail -c 2000 "$f" | grep -v '^\s*$' | tail -1)
  case "$last" in
    *"Waiting for LLM call response"*|*"Chunk capsule"*) echo "HANG  $f :: $last";;
  esac
done

# B4 thinking-mode 400 与 pause 的完整上下文
grep -n -B8 -A4 "Thinking mode does not support" traces/qa_1114/yidiansanguo/run_E.log

# B5 1×1 帧导致 Qwen 400（base64 里 iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB = 1×1 PNG）
sqlite3 traces/data_engine.db \
 "SELECT session_id, substr(payload,1,200) FROM traces
  WHERE payload LIKE '%larger than 28 for Qwen%';"

# B6 helper 能力 100% 失败
grep -rh "set-wakelock" traces/*/run_*.log traces/*/*/run_*.log | wc -l   # → 32，覆盖 32/32 个 run 日志

# B7 残留画面：Agent 启动 A、屏幕是 B
sqlite3 traces/data_engine.db \
 "SELECT session_id, substr(payload,1,400) FROM traces
  WHERE payload LIKE '%report_task_status({%' AND payload LIKE '%大圣-西游咸鱼常规版%';"

# B8 资源泄漏：孤儿录制（mtime 远晚于 session 结束）
find traces -name "recording.*" -size +1G -exec ls -lh {} \; | awk '{print $5, $6, $7, $8, $9}'
du -sh traces/*/ | sort -rh | head -5

# B9 当前是否有孤儿
ps -eo pid,ppid,etime,command | grep -E "artemis.main run|uv run|screenrecord" | grep -v grep
adb devices
```

### C. 未取到 / 未知项（不编造）

| 项 | 状态 |
|---|---|
| 电量 / 温度 / 充电历史 | **未知**——DB 与日志均无落库。11-13 的 12 个冒烟用例只在 UI 上看电池数值，未采集 |
| `captive_portal_http_url = null` 的原始 `dumpsys` 输出 | **未知**——只有 app 侧旁证（「WLAN 未连接到互联网」），没有设备侧 dump 存档 |
| 4 个挂死 session 的 `end_time` 由谁在 21:22:04 批量写入 | **未知**——仓库内无对应代码路径（已排除 `storage.update_session` / `end_session`），判断为仓库外操作 |
| `LLM_PAUSE_TIMEOUT_SECONDS` 在 11-14 运行时实际生效值 | **未知**——代码默认 900 s，但两次 pause 无 `(900s) exceeded; giving up.` 日志，说明当时是 `<=0`（无限）。具体原因未取到 |
| 孤儿 `uv run` 被杀的确切时刻与信号 | **未知**——`dmesg`/崩溃报告无留存；只能由 `recording.mkv` mtime（21:04）反推宿主在 11:18–21:04 之间已死 |
| 每次 400 的 `request_id` 与 DeepSeek 侧账单对账 | **未知**——`failed_outputs` 表为空（0 行），失败 prompt / 原始输出未落库 |
| `partialConnectivity` 期间的具体丢包率 / 时延 | **未知** |
