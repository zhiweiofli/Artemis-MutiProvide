# Artemis 成本分析（2026-11-14 ~ 2026-11-15，4 轮 / 55 个 session）

> 数据源：`traces/data_engine.db`（只读 SQL 聚合）+ `traces/qa_1114*/` 运行日志。
> 计价（USD / 1M tokens）：deepseek 输入 0.14 / 缓存命中 0.014 / 输出 0.28；qwen 输入 0.40 / 缓存 0.10 / 输出 1.20。
> 所有数字均可由文末附录 SQL 复现。gemini 兜底模型的 13 次调用（103,215 prompt tok）**定价未知**，未计入金额（量级 <$0.001，不影响结论）。

---

## 一句话结论

两天 4 轮 55 个 session 共花 **$4.29**（prompt 61.25M / completion 2.48M），其中 **69.7% 花在 10 个 90-212 步的长程 session 上**，而钱的构成不是"prompt 变大"，而是 **70% 的成本来自未被缓存命中的输入 token（20.33M tok / $3.01）**——其中 planner 一家占 $1.85；因此第一优先级是**修缓存前缀稳定性（预计 −$1.2~1.5 / 两日，约 −30~35%）**，其次是**按需传图（−15%）**和**砍掉 27.4% 的无信息步（−15%）**。

---

## 1. 成本结构

### 1.1 总量与口径

| 指标 | 数值 | 数据查询方式 |
|---|---|---|
| session 数（11-14/11-15） | 55 | `sessions` where `date(start_time)` in 两天 |
| step 数 | 2,131 | `steps` join `sessions` |
| prompt tokens | 61,251,593 | `traces` where `type='llm_call' AND name='llm_usage'` → `json_extract(payload,'$.prompt_tokens')` 求和 |
| cached tokens | **40,851,314（66.7%）**；其中 deepseek 40,816,512 / 60,506,856 = **67.5%** | 同上，`$.cached_tokens`（gemini 另有 34,802） |
| completion tokens | 2,479,221 | 同上，`$.completion_tokens` |
| 总成本 | **$4.290** | deepseek $4.018 + qwen $0.273（gemini 未知） |
| 未命中 prompt tokens | 20,400,279（其中 deepseek 19,690,344 / qwen 641,522） | `prompt − min(cached, prompt)` 求和 |
| 单 session 均值 / 中位 | $0.078 / $0.023 | 逐 session 聚合 |
| 单 step 均值 | $0.0020 | $4.281 / 2,131（有 step 归因的调用） |

> 口径说明：金额 = `(prompt−cached)×输入价 + cached×缓存价 + completion×输出价`，逐条 `llm_usage` trace 计算后求和。`llm_usage` 共 4,967 条覆盖两天全部 LLM 调用（其中 4,959 条带 `step_id`，可归因到步）。

### 1.2 按模型 / 组件（node）拆解 —— 钱到底花在哪

| node | 模型 | 调用数 | cached tok | 未命中 tok | 输出 tok | 成本 | 占比 |
|---|---|---|---|---|---|---|---|
| `FlashRunner`（planner 决策） | deepseek | 2,276 | 38,271,488 | 13,233,418 | 918,802 | **$2.646** | **61.7%** |
| `lens:visualstepsummarizer`（每步看前后两张图写摘要） | deepseek | 2,082 | 1,942,016 | 5,575,934 | 663,194 | **$0.994** | 23.2% |
| `lens:step_capsule`（chunk 胶囊压缩） | deepseek | 297 | 547,072 | 632,847 | 821,064 | $0.326 | 7.6% |
| `explorer`（Qwen3-VL 视觉定位） | qwen | 269 | 0 | 641,522 | 13,324 | $0.273 | 6.4% |
| `spawn_sub_agent` / `video_analyzer` | deepseek | 43 | 55,936 | 248,145 | 59,752 | $0.052 | 1.2% |
| **合计** | | **4,967** | **40,816,512** | **20,331,866** | **2,476,136** | **$4.291** | 100% |

> 注：本表为 deepseek + qwen；另有 13 次 gemini 调用（prompt 103,215 / cached 34,802）定价未知，未计入。

**关键发现：成本 = 未命中 token（70%）。** 拆开看：
- 已命中缓存输入 40.82M tok → **$0.57**（13.4%）
- 未命中输入 20.33M tok → **$3.01**（70.2%）
- 输出 2.48M tok → **$0.69**（16.1%）

也就是说：**prompt 里"重复发 30k 历史"其实很便宜（缓存价 0.014，只有输入价的 1/10）；真正贵的是每次重算的那几 k 尾部 token。**

### 1.3 按轮次

| 轮次（时间窗） | session | prompt | 缓存率 | completion | 成本 |
|---|---|---|---|---|---|
| 11-14 凌晨（SDKdemo） | 2 | 340,380 | 42.1% | 15,995 | $0.023 |
| **R1 11-14 上午**（11:08–12:46） | 14 | 14,090,133 | 64.7% | 580,679 | **$1.045** |
| **R2 11-14 下午+夜+11-15 凌晨** | 9 | 8,575,275 | 62.9% | 407,741 | **$0.658** |
| **R3 11-15 上午**（11:07–12:41） | 20 | 20,031,291 | 69.2% | 753,681 | **$1.321** |
| **R4 11-15 下午**（13:29–14:51） | 10 | 18,214,514 | 67.7% | 721,125 | **$1.244** |

（与 `traces/qa_1114_v2/SUMMARY.md` 自报的"17 个 session / 21,075,892 prompt / ≈$3.05"方向一致 —— 该数字对应的正是 R3+R4 共 30 个 session 的子集口径；本表按两天全部 55 个 session 计。）

### 1.4 按阶段

| 阶段 | session | prompt | 缓存率 | 成本 | $/session | 占比 |
|---|---|---|---|---|---|---|
| A 下载安装 | 5 | 963,376 | 49.5% | $0.088 | $0.018 | 2.1% |
| B+C 启动登录 | 27 | 4,862,147 | 53.7% | $0.432 | $0.016 | 10.1% |
| **D 新手引导** | 11 | 25,497,046 | 67.8% | **$1.745** | **$0.159** | 40.7% |
| **E 主界面巡检** | 9 | 29,416,540 | 68.8% | **$1.988** | **$0.221** | 46.3% |
| demo / 其他 | 3 | 512,484 | — | $0.038 | — | 0.8% |

> 与 `REPORT.md` 里"D 阶段占 70~85%"的说法不同：按 session 均值 **E（$0.221）比 D（$0.159）更贵**，因为 E 阶段是开放式逐按钮巡检（90-162 步），D 阶段部分 session 只跑了 22-43 步。D+E 合计 **$3.733 = 87.0%**。

### 1.5 Top 10 最贵 session

| # | session | 游戏 | 阶段 | step | LLM 调用 | prompt | 缓存率 | 成本 | $/step |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `3feafb5d` | 斗破苍穹 | D | 212 | 508 | 7,593,663 | 70.0% | **$0.496** | $0.0023 |
| 2 | `a325bee8` | 一点三国 | D | 212 | 506 | 7,964,043 | 73.3% | **$0.478** | $0.0023 |
| 3 | `4600dc04` | 斗破苍穹 | E | 157 | 373 | 5,077,441 | 71.1% | $0.323 | $0.0021 |
| 4 | `09b7af9a` | 冲吧勇者 | E | 162 | 371 | 5,057,142 | 71.8% | $0.308 | $0.0019 |
| 5 | `170ed824` | 一剑断念 | E | 139 | 314 | 4,299,372 | 68.8% | $0.283 | $0.0020 |
| 6 | `313c9400` | 一点三国 | E | 130 | 313 | 4,145,749 | 69.8% | $0.276 | $0.0021 |
| 7 | `4ace4c15` | 一点三国 | D | 110 | 244 | 3,259,532 | 67.8% | $0.219 | $0.0020 |
| 8 | `994c452e` | 斗破苍穹 | E | 99 | 234 | 2,951,995 | 66.6% | $0.210 | $0.0021 |
| 9 | `3bbb16aa` | 一剑断念 | E | 91 | 221 | 2,720,541 | 66.9% | $0.202 | $0.0022 |
| 10 | `65d6b790` | 斗破苍穹 | E | 92 | 222 | 2,672,889 | 66.4% | $0.195 | $0.0021 |

**Top 10 = $2.990 = 全额的 69.7%。** 全部是 90 步以上的 D/E 长程 session。贵在哪：
1. **步数**（第一驱动）：单步成本从 step 1-10 的 $0.0006 涨到 step 151+ 的 $0.0010（1.7x），但步数从 10 涨到 150+（15x）—— 成本≈线性于步数。
2. **图像**：summarizer 每步固定送 2 张 1080×2160 截图（~2.1k tok / 3.65k，约 **58% 输入**），全部不可能命中缓存。
3. **重复上下文**：planner 每次调用重算中位 3.2k token 尾部（scrub edge 原地改写历史消息导致的缓存断裂），p90 达 19k。
4. 缓存命中率并不是"长会话更好"—— Top 10 的命中率 66.4%~73.3%，低于 planner 单次稳态的 90%。

---

## 2. prompt 膨胀：涨了多少、拐点在哪、为什么

### 2.1 涨幅（planner 单次 prompt）

| session | planner 调用 | 首次 pt | 末次 pt | 倍数 | 稳态增长 |
|---|---|---|---|---|---|
| `a325bee8`（212 步 D） | 230 | 8,154 | 44,634 | **5.5x** | +100 tok/call |
| `3feafb5d`（212 步 D） | 224 | 7,250 | 41,771 | **5.8x** | +82 tok/call |
| `4600dc04`（157 步 E） | 167 | 8,190 | 32,938 | 4.0x | +62 tok/call |
| `09b7af9a`（162 步 E） | 169 | 8,076 | 32,818 | 4.1x | +57 tok/call |
| `170ed824`（139 步 E） | 144 | 8,127 | 33,580 | 4.1x | +87 tok/call |

全部 ≥8 次调用的 37 个 session：首→末 **中位 2.2x / 均值 2.8x**。

### 2.2 归一化增长曲线与拐点（按调用序号分桶，9 个 ≥100 调用的长会话）

| 调用序号 | 1-5 | 6-10 | 11-20 | 21-40 | **41-60** | 61-80 | 81-120 | 121+ |
|---|---|---|---|---|---|---|---|---|
| 中位倍数 | 1.28x | 1.63x | 1.91x | 2.43x | **3.15x** | 3.40x | 3.66x | 4.27x |
| 绝对 token 中位 | 9,779 | 13,124 | 15,186 | 19,302 | **24,919** | 27,224 | 28,948 | 33,571 |
| 平均增速 | — | +0.07x/call | +0.03x/call | +0.03x/call | **+0.04x/call** | +0.01x/call | +0.006x/call | +0.010x/call |

**拐点在第 41~60 轮**（增速峰值 +0.04x/call，绝对值 24.9k tok），**第 80 轮后进入平台期**（+0.006~0.01x/call）——对应 `agent.memory.transcript` 的 L2 块压缩起作用：`soft_ratio=0.7 × 80k budget` 在 ~25k 附近开始换块。

### 2.3 增长来源（实测拆解）

| 来源 | 量级 | 证据 |
|---|---|---|
| 固定前缀（system prompt + goal + 工具 schema） | ~9.8k tok（call 1-5 中位） | `flash_runner.md` 9,629 chars ≈ 2.4k tok + 工具 schema + goal |
| 8 个 chunk 块（L2 胶囊，`max_chunks=8`） | 每块 4.7-5.9k chars ≈ 1.2-1.5k tok，合计 ~10k tok | `history_chunks.rendered_text`：a325bee8 的 32 个 ready 块，avg 5.6k chars |
| eras / ledger（溢出块折叠） | 随步数线性累计 | `artemis.memory.chunking` 日志：`froze 7 turns (8 chunks, **3 eras** …)`，era 数逐段增长 |
| 活跃区 raw turns（含截图） | 每步新增 ~100 tok 文本 + 1 张截图（~1.0-1.6k tok，**不可缓存**） | 稳态 pt 增量 +100 tok/call，而 uncached 中位 3.2k/call |
| UI 树 | 98.2% 的步都带（avg 3,739 chars ≈ 935 tok） | `images.ui_tree`：2,092/2,131 步非空 |

**结论：prompt 膨胀是真实的（5.5x），但对账单的影响被缓存打了 10 折**——单次调用成本只从 $0.0006 涨到 $0.0010。真正的钱在"每步必须重算的尾部"（截图 + 新观察文本），不在"历史总量"。

---

## 3. 缓存效率

| 指标 | 数值 | 出处 |
|---|---|---|
| deepseek 整体缓存命中率 | **67.5%**（40.82M / 60.51M tok） | `llm_usage` 聚合 |
| planner（FlashRunner）命中率 | **74.3%**（38.27M / 51.50M） | 同上 |
| summarizer 命中率 | **25.8%**（1.94M / 7.52M） | 同上 |
| step_capsule 命中率 | 46.4%（0.55M / 1.18M） | 同上 |
| planner 单次命中率 中位 / 均值 | **0.90 / 0.78** | 长会话 `a325bee8` 230 次调用 |
| planner 单次命中率分布 | >90%: 22.5%，80-90%: 14.9%，60-80%: 35.6%，50-60%: 16.6%，<50%: 10.4% | 2,276 次调用分桶 |
| 稳态每次调用未命中量（call>60） | 中位 3,290 tok，均值 6,057 tok，p90 19,838 tok | 5 个最长 session |
| **cache 回退事件**（cached_tokens 较上一调用下降 >500） | **302 次**（占 planner 调用 13.3%），累计丢失前缀 **3,267,349 tok = $0.412** | 按 session 时序逐条 diff |

**什么在破坏前缀稳定性**（代码 + 日志佐证）：
1. **scrub edge 原地改写历史消息**：`agents/flash/context_compressor.py` 的 `_resolve/_rewrite` 把深度 ≥ `image_scrub_depth`(默认 3) 的截图**就地**换成摘要块；`xml_scrub_depth=1` 也会就地删除元素列表/plan 复述。任何**非尾部**改写都会让其后所有 token 失去缓存。
2. **`image_scrub_depth_relaxed=6` → 3 的动态切换**：上下文占用超过 `budget*start_ratio` 后深度收紧，一次性改写一批消息（典型尖峰：某 session 第 191 次调用命中率从 91% 掉到 **28%**）。
3. **L2 chunk swap / era 折叠**：`History compression swap: froze 49 turns (7 chunks, 0 eras …)` 是整段替换，命中率立即归零重算。
4. **capsule 压缩比只有 68.9%**（289 次配对日志：source 1,764,568 chars → capsule 1,215,985 chars，中位 72%）——花一次 4k tok 的调用，只省 31% 字符，却换来一次前缀重写。

**反事实测算**（把每条调用的 cached 抬到目标命中率后重算金额）：

| 目标命中率 | 成本 | 节省 |
|---|---|---|
| 现状 67.5% | $4.290 | — |
| 80% | $2.851 | **−$1.44（−33.5%）** |
| 90% | $2.346 | **−$1.94（−45.3%）** |

---

## 4. 无效开销

| 浪费类型 | 步数 | 占比 | 成本 | 占比 |
|---|---|---|---|---|
| `wait_for_delay` 动作（全部） | 380 | 17.8% | $0.659 | 15.4% |
| ↳ 其中"连续第 2 次及以后"的等待（判据要求的双次确认之外） | 96 | 4.5% | $0.143 | 3.3% |
| 前后 `dhash` 完全相同（画面零变化，含终局汇报） | 296 | 13.9% | $0.495 | 11.6% |
| ↳ 减掉 `report_task_status`（48 步，终局汇报天然不改画面） | 248 | 11.6% | **$0.414** | **9.7%** |
| **真实无效并集（wait ∪ 点击无响应）** | **583** | **27.4%** | **$1.003** | **23.4%** |
| 相邻两步 `action_taken` 字符串完全相同 | 122 | 5.7% | $0.206 | 4.8% |
| 失败 session 的全部开销（20 个 failed） | — | — | **$0.927** | **21.6%** |

按动作类型的"点了没反应"率（真实零变化 / 该动作总步数）：

| 动作 | 步数 | 零变化 | 比例 |
|---|---|---|---|
| click | 1,478 | 184 | 12.4% |
| wait_for_delay | 380 | 45 | **11.8%** |
| press_key | 102 | 8 | 7.8% |
| manage_app | 54 | 7 | 13.0% |
| click_sequence | 50 | 3 | 6.0% |
| swipe | 18 | 1 | 5.6% |
| report_task_status | 48 | 48 | 100%（终局，正常） |

补充：
- 零变化最集中的 session：`4600dc04` 46/157（29%）、`170ed824` 29/139（21%）、`0d36c92b` 19/36（53%）、`e6750112` 13/43（30%）。
- **等待并不算浪费**：`wait_for_delay` 里只有 11.8% 出现零变化 —— 说明等待大多确实等到了加载/转场。真正的浪费在 **click 有 184 次点了没反应（12.4%）**，以及 380 次等待里"连续第 2 次及以后"的 96 步（$0.143，属于可以用模板推进的确定性步骤）。
- **Qwen 视觉定位没有浪费**：271 次 Attempt 1 对 269 次成功调用，`failed_outputs` 表 0 行，没有重试放大。
- **失败 session 的 $0.927 里，86% 来自两个长程 session**：
  - `a325bee8`（一点三国 D，212 步，$0.478，status=failed）：跑了 28 分钟主线引导仍未满足「引导遮罩消失」，属于「判据对无明确引导终点的游戏不适用」（见 `qa_1114_v2/SUMMARY.md`）——钱花完了却没有结论，是本轮最贵的单笔浪费。
  - `4600dc04`（斗破 E，157 步，$0.323，status=failed）：USB 掉线导致纯绿空帧，R4 整条重跑又花 $0.289 —— 纯环境故障浪费。
- `大圣` BC 阶段反复重试 7 个 session 共 $0.053（确定性「链接已失效」，按规则应一次即 FAIL）。

---

## 5. 图片成本

| 指标 | 数值 | 出处 |
|---|---|---|
| 每步是否带截图 | pre 图 **100%**（2,131/2,131），post 图 **94.8%**（2,020/2,131） | `steps.pre_image_name/post_image_name` 非空计数 |
| `images` 表行数 | 2,067 | `SELECT COUNT(*) FROM images` |
| 磁盘图片 | 2,068 个 jpg / **562 MB** / 均值 **272 KB** | `traces/images/` |
| UI 树覆盖率 | **98.2%**（2,092/2,131 步），avg 3,739 chars ≈ 935 tok | `images.ui_tree` 长度 |
| summarizer 每步送图数 | **2 张**（抽样 payload 均为 2 个 `image_url`；全量 2,369 条带图 trace 中双图占 2,054/2,106） | `ChatOpenAI` payload 中 `image_url` 块计数 |
| 单张图 token 成本 | **≈1,050 tok**（全量样本：双图调用均值 3,645，单图调用均值 2,030，差 1,615 为上限；按文本基线 1.55k 反推 ~1.05k） | summarizer prompt_tokens 分布 |
| 图像 token 总量（估） | **≈7.0M tok**（summarizer 4.4M 实测 + planner ~2.7M 推断） | summarizer = 2,082 × ~2,100 实测；planner = 2,276 × ~1.2k，按 `image_scrub_depth=3` + 稳态 uncached 3.2k/call 推断（**planner prompt 未落库，此处为推断值**） |
| 图像金额（估） | **≈$0.90，占 21%** | 全部为未命中 token（图像无法命中前缀缓存） |

**能否按需传图？可以，而且条件很好：98.2% 的步已经有 UI 树。**
- 当前：planner 每个 step 都带 3 张实时截图（`image_scrub_depth=3` 保留最近 3 张，**推断**），summarizer 每步消耗 2 张（**实测**，payload 中 2 个 `image_url`）。
- 建议：**"UI 树缺失 或 验收关键步（支付面板/引导终点判定）才传图"**；其余步仅传 UI 树 + 上一步摘要。
- 保守估算：图像 token 命中率不变的前提下，图像 token 从 7.0M 降到 ~1.8M（保留 1.8% 无树步 + 关键步，并把截图降到 720p 再省 4x）→ **节省 ~$0.55~0.75，占 13%~18%**。
- 若只做"降采样到 720p"（不改传图逻辑）：图像 token −60~75% → 省 **$0.54~0.68（13%~16%）**，风险最低。

---

## 6. 优化建议（按 ROI 排序）

> 基准：两日 **$4.29 / 55 session**；单款完整流程（BC+D+E）实测 **$0.29~0.51**（R4：一点三国 $0.508、冲吧勇者 $0.444、斗破 $0.289），含重跑的累计单款成本 $0.76~1.44。

### 建议 1：报告"只用于定位"的历史，不再每步重算 —— 稳定缓存前缀
- **做什么**：把 scrub edge 的"就地改写"改成"仅追加"——① 图片摘要/文本 strip 不原地替换，改为在**消息尾部**追加一条 `[已压缩]` 引用（原始消息冻结不再改写）；② `image_scrub_depth_relaxed` 动态收紧改为**只在硬阈值批量触发一次**，避免每步小改写；③ 每个 planner 调用只在真正的 milestone（子目标切换）重写历史。
- **预期节省**：命中率 67.5% → 80% = **−$1.44 / 两日（−33.5%）**；→ 90% = **−$1.94（−45.3%）**。折中按 85% 计：**≈ −$1.65 / 两日（−38%）**；考虑与建议 2/3/4 的重叠后，组合口径下按 **−$1.3** 计，≈ −$0.12/单款流程。
- **实现成本**：**中**（`context_compressor.py` 语义变更 + A/B，需回归 212 步长会话行为）。
- **风险**：prompt 变长（不压缩的历史留在上下文里）→ 但缓存价只有 1/10，净收益为正需 A/B 验证；冻结历史可能让 planner 引用过期坐标，需保留 `xml_scrub_depth=1` 的文本 strip。

### 建议 2：按需传图 + 截图降采样
- **做什么**：① 截图统一压到 720p（当前 1080×2160 / 272KB / 1,050 tok 一张）；② `image_scrub_depth` 3 → 1，planner 只保留最新 1 张；③ UI 树非空的步（98.2%）默认不传图，只对"无 UI 树 / 支付面板/引导终点判定"这类关键步传图；④ summarizer 的前后图合成一张对比图（上下拼接），省一半图 token。
- **预期节省**：图像 token ≈7.0M → ≈2.0M，**−$0.55~0.75 / 两日（13%~18%）**，≈ −$0.05~0.07/单款流程。仅做 ① 就有 −$0.54（13%）。
- **实现成本**：**小**（①③④ 都是配置/截图层改动；② 改一个 config 默认值）。
- **风险**：自绘 canvas 游戏（真·无 UI 树）定位退化 → 用"UI 树节点数 < N 或覆盖率低"作为兜底触发条件；已实测 Qwen 定位调用只有 269 次（12.6% 步），可作为"无树时"的廉价替代路径（单次 2,385 tok / $0.001）。

### 建议 3：砍掉"无信息步"（wait / 零变化 / 重复动作）
- **做什么**：① `wait_for_delay` 不调用 planner——等待本身是确定性动作，"等完之后画面一定会变"这件事不需要模型判断（实测等待步只有 11.8% 零变化，正是因为它确实等到了加载），可以先用廉价的画面变化检测，**变了才起一次决策**；② 落地已有的"连续 8 次无变化即 FAIL"规则（实测仍有 **248 步真实点了没反应**，占 11.6%，`click` 的无响应率 12.4%）；③ 相邻完全相同的 action 做去重/合并（122 步，$0.206）。
- **预期节省**：真实无效步并集 583 步（27.4%）对应 $1.003；按可消除 60~70% 计 **−$0.60~0.70 / 两日（14%~16%）**，≈ −$0.06/单款流程。
- **实现成本**：**中**（wait 旁路需要新的状态机分支；零变化早停要区分"该等"与"卡死"）。
- **风险**：早停过早判 FAIL（大圣这类"确定性失败"应早停，但加载慢的游戏会被误杀）→ 用"加载类动作豁免 + 累计无变化次数"而非单次判断。

### 建议 4：给 D/E 长程阶段设"步数预算 + 脚本化巡检"
- **做什么**：① D 阶段设硬预算（如 120 步 / 20 分钟），超预算直接 `TIMEOUT` 并输出已有证据（当前最长 212 步）；② E 阶段从"开放式逐按钮探索"改为**固定巡检清单脚本**（包列表已知，按钮点击是确定性的），planner 只在异常分支介入；③ 对"无明确引导终点"的游戏（一点三国已证明）改用替代判据，避免反复推进主线。
- **预期节省**：D+E 合计 $3.733（87%）。以「该 session 第 N 步的时间戳」为截断点统计超出部分（口径覆盖全部 4,967 条调用）：

  | 预算上限 | 超出部分成本 | 占全量 |
  |---|---|---|
  | 80 步 | $1.361 | 31.7%（太激进） |
  | 100 步 | $0.960 | 22.4% |
  | **120 步** | **$0.697** | **16.2%** |
  | 150 步 | $0.354 | 8.3% |

  两个 212 步的 session 实测：`3feafb5d` 第 120 步后占其成本 46%（$0.230），`a325bee8` 占 48%（$0.229）。取 120 步预算：**−$0.70（−16.2%）**，≈ −$0.06/单款流程（其中已包含 `a325bee8` 那笔 $0.478 的无效长跑）。
- **实现成本**：**中**（E 脚本化是一次性工程；D 预算是一行配置 + 判据调整）。
- **风险**：判据覆盖不足导致漏检（一点三国"引导无限"就是反例）→ 必须同时输出 `NO_TUTORIAL_END` 标注，不能静默降级。

### 建议 5：失败快速退出 + capsule 输出瘦身
- **做什么**：① 确定性失败指纹（"链接已失效 / 版本过旧 / 维护"）一旦命中，写 FAIL 并落库"同游戏同指纹 24h 内不再重跑"（大圣被重试 7 次、斗破因设备掉线重跑）；② `lens:step_capsule` 当前输出 821k tok（$0.230，占 5.4%）换来的压缩比只有 68.9%——提高 `min_steps`（3→6）、给 capsule 输出加 token 上限、只在压缩比 >50% 时才落盘。
- **预期节省**：失败开销 $0.927 中**属于"重试/重跑"性质、可消除的部分约 $0.38~0.42**——`4600dc04` 设备掉线导致的失败 session $0.323（R4 又重跑一次 $0.289）+ `大圣` 7 次重复重试 $0.053 + 其余小失败重试约 $0.05；去重后可省 **−$0.38~0.42（9%~10%）**。capsule 优化再 **−$0.15~0.20（3.5%~4.7%）**。合计 **−$0.55 / 两日（≈13%）**。
  （注：`a325bee8` 那 $0.478 不算在这里——它起因是"跑到预算尽头仍无结论"，由建议 4 的步数预算 + 替代判据解决，避免重复计算。）
- **实现成本**：**小**（失败指纹是规则表；capsule 是配置 + 一行阈值）。
- **风险**：重跑去重会漏掉偶发失败 → 指纹必须包含"确定性"标志，网络类错误仍允许 1 次重试。

### 组合估算（去重叠后）

| 项 | 两日节省 | 占现成本 |
|---|---|---|
| 建议 1（缓存） | −$1.35 | −31% |
| 建议 2（图片） | −$0.65 | −15% |
| 建议 3（无信息步） | −$0.65 | −15% |
| 建议 4（步数预算 120 步） | −$0.70 | −16% |
| 建议 5（失败重跑/capsule） | −$0.55 | −13% |
| **合计（各项独立上限）** | −$3.90 | −91% |

⚠️ 直接相加会重复计算（建议 2/3/4 都在减少 token 与调用次数，而建议 1 的收益随 token 减少而变小）。按"图像 token 降 75%（−$0.74）→ 整体命中率提到 85%（→$2.54）→ 步数 −30%（→$1.78）→ 失败去重（→$1.5）"的顺序做保守模拟，**现实目标区间为 −55%~−65%，即两日 $4.29 → $1.5~1.9，单款完整流程 $0.41 → $0.15~0.19**。

---

## 附录：关键 SQL（可直接复现）

```sql
-- 0) 计价函数（Python 侧，逐条 llm_usage 计算后求和）
-- cost = ((pt - min(ct,pt)) * in_price + min(ct,pt) * cache_price + cpt * out_price) / 1e6

-- 1) 总 token / 缓存
SELECT json_extract(payload,'$.source') AS src,
       COUNT(*) AS calls,
       SUM(json_extract(payload,'$.prompt_tokens'))     AS prompt_tok,
       SUM(json_extract(payload,'$.cached_tokens'))     AS cached_tok,
       SUM(json_extract(payload,'$.completion_tokens')) AS compl_tok
FROM traces t
JOIN sessions s ON s.session_id = t.session_id
WHERE t.type = 'llm_call' AND t.name = 'llm_usage'
  AND date(s.start_time,'unixepoch','localtime') IN ('2026-11-14','2026-11-15')
GROUP BY src;

-- 2) 按组件（node）拆 token
SELECT json_extract(payload,'$.node') AS node, COUNT(*) n,
       SUM(json_extract(payload,'$.prompt_tokens')) pt,
       SUM(json_extract(payload,'$.cached_tokens')) ct,
       SUM(json_extract(payload,'$.completion_tokens')) cpt
FROM traces t JOIN sessions s ON s.session_id = t.session_id
WHERE t.type='llm_call' AND t.name='llm_usage'
  AND date(s.start_time,'unixepoch','localtime') IN ('2026-11-14','2026-11-15')
GROUP BY node ORDER BY pt DESC;

-- 3) 阶段推导（goal 里的「阶段B+C / 阶段D / 阶段E / 阶段A」）
SELECT session_id, start_time, status,
       CASE WHEN initial_goal LIKE '%阶段E%'   THEN 'E'
            WHEN initial_goal LIKE '%阶段D%'   THEN 'D'
            WHEN initial_goal LIKE '%阶段B+C%' THEN 'BC'
            WHEN initial_goal LIKE '%阶段A%'   THEN 'A' ELSE 'other' END AS phase
FROM sessions
WHERE date(start_time,'unixepoch','localtime') IN ('2026-11-14','2026-11-15');

-- 4) Top 最贵 session
SELECT t.session_id, COUNT(*) calls,
       SUM(json_extract(t.payload,'$.prompt_tokens')) pt,
       SUM(json_extract(t.payload,'$.cached_tokens')) ct
FROM traces t JOIN sessions s ON s.session_id=t.session_id
WHERE t.type='llm_call' AND t.name='llm_usage'
  AND date(s.start_time,'unixepoch','localtime') IN ('2026-11-14','2026-11-15')
GROUP BY t.session_id ORDER BY pt DESC LIMIT 10;

-- 5) planner prompt 增长（首/末/中位）
SELECT t.session_id, COUNT(*) n,
       MIN(json_extract(t.payload,'$.prompt_tokens')) first_pt,
       MAX(json_extract(t.payload,'$.prompt_tokens')) last_pt
FROM traces t JOIN sessions s ON s.session_id=t.session_id
WHERE t.type='llm_call' AND t.name='llm_usage'
  AND json_extract(t.payload,'$.node')='FlashRunner'
  AND date(s.start_time,'unixepoch','localtime') IN ('2026-11-14','2026-11-15')
GROUP BY t.session_id HAVING n >= 8 ORDER BY last_pt DESC;

-- 6) 缓存断裂：逐 session 按时间排序，比较相邻调用的 cached_tokens
SELECT session_id, timestamp, step_id,
       json_extract(payload,'$.prompt_tokens') pt,
       json_extract(payload,'$.cached_tokens') ct
FROM traces
WHERE type='llm_call' AND name='llm_usage'
  AND json_extract(payload,'$.node')='FlashRunner'
  AND session_id = 'a325bee8-a8bb-4755-acc6-fd3bfa1e9fcc'
ORDER BY timestamp;
-- 在应用层 diff：ct < 上一次 ct - 500 记为一次回退，累加损失量

-- 7) 动作分布（action_taken 有字符串/JSON 两种历史格式，用 CASE+LIKE 统一）
SELECT CASE
         WHEN action_taken LIKE '%wait_for_delay%'   THEN 'wait_for_delay'
         WHEN action_taken LIKE '%click_sequence%'   THEN 'click_sequence'
         WHEN action_taken LIKE '%click%'            THEN 'click'
         WHEN action_taken LIKE '%press_key%'        THEN 'press_key'
         WHEN action_taken LIKE '%swipe%'            THEN 'swipe'
         WHEN action_taken LIKE '%input_text%'       THEN 'input_text'
         WHEN action_taken LIKE '%manage_app%'       THEN 'manage_app'
         WHEN action_taken LIKE '%report_task_status%' THEN 'report_task_status'
         ELSE 'other' END AS a,
       COUNT(*) n
FROM steps s JOIN sessions ss ON ss.session_id=s.session_id
WHERE date(ss.start_time,'unixepoch','localtime') IN ('2026-11-14','2026-11-15')
GROUP BY a ORDER BY n DESC;

SELECT COUNT(*) AS no_change_steps FROM steps s JOIN sessions ss ON ss.session_id=s.session_id
WHERE date(ss.start_time,'unixepoch','localtime') IN ('2026-11-14','2026-11-15')
  AND json_extract(s.extra_metadata,'$.pre_image_dhash') IS NOT NULL
  AND json_extract(s.extra_metadata,'$.pre_image_dhash')
    = json_extract(s.extra_metadata,'$.post_image_dhash');

-- 8) 图片 / UI 树覆盖率
SELECT COUNT(*) steps,
       SUM(CASE WHEN i.ui_tree IS NOT NULL AND length(i.ui_tree)>50 THEN 1 ELSE 0 END) with_uitree,
       ROUND(AVG(length(i.ui_tree)),0) avg_tree_chars
FROM steps s JOIN sessions ss ON ss.session_id=s.session_id
LEFT JOIN images i ON i.image_name = s.pre_image_name
WHERE date(ss.start_time,'unixepoch','localtime') IN ('2026-11-14','2026-11-15');

-- 9) capsule 压缩效果（实测 68.9%）：把 log 的 message 拉出来用 Python 正则统计
--    正则：source (\d+) chars -> capsule (\d+) chars \((\d+)%\)
SELECT t.timestamp, t.payload FROM traces t
JOIN sessions s ON s.session_id=t.session_id
WHERE t.type='log' AND t.name='artemis.memory.chunking'
  AND t.payload LIKE '%chars -> capsule%'
  AND date(s.start_time,'unixepoch','localtime') IN ('2026-11-14','2026-11-15');

-- 10) 失败 session 成本占比
SELECT s.status, COUNT(*) n
FROM sessions s
WHERE date(s.start_time,'unixepoch','localtime') IN ('2026-11-14','2026-11-15')
GROUP BY s.status;

-- 11) 步数预算的节省上限（以"该 session 第 N 步的 timestamp"为截断点）
--     先取每个 session 第 120 步的时间点，再把该时间点之后的 llm_usage 成本加起来
SELECT s.session_id, s.timestamp AS cut_at
FROM steps s JOIN sessions ss ON ss.session_id = s.session_id
WHERE s.step_number = 120
  AND date(ss.start_time,'unixepoch','localtime') IN ('2026-11-14','2026-11-15');

-- 12) 无效步并集（wait ∪ 真实无响应，排除 report_task_status）—— 在 Python 侧求并集后按 step_id 汇总成本
SELECT step_id, action_taken,
       json_extract(extra_metadata,'$.pre_image_dhash')  AS pre,
       json_extract(extra_metadata,'$.post_image_dhash') AS post
FROM steps s JOIN sessions ss ON ss.session_id = s.session_id
WHERE date(ss.start_time,'unixepoch','localtime') IN ('2026-11-14','2026-11-15')
  AND (action_taken LIKE '%wait_for_delay%'
       OR (json_extract(extra_metadata,'$.pre_image_dhash')
           = json_extract(extra_metadata,'$.post_image_dhash')
           AND action_taken NOT LIKE '%report_task_status%'));

-- 13) 缓存断裂检测（逐 session 按时间排序，在应用层 diff）
--     ct < 上一次 ct - 500 记为一次回退，累加 (上一次 ct - 本次 ct) 得到丢失的前缀 token
SELECT session_id, timestamp,
       json_extract(payload,'$.prompt_tokens') pt,
       json_extract(payload,'$.cached_tokens') ct
FROM traces
WHERE type='llm_call' AND name='llm_usage'
  AND json_extract(payload,'$.node') = 'FlashRunner'
  AND date(timestamp,'unixepoch','localtime') IN ('2026-11-14','2026-11-15')
ORDER BY session_id, timestamp;
```

> 复现提示 1：`sessions.start_time` / `traces.timestamp` / `steps.timestamp` 都是 Unix 秒（REAL），过滤器统一用
> `date(x,'unixepoch','localtime')`。
> 复现提示 2：`steps.action_taken` 早期行为纯字符串（如 `wait_for_delay(...)`），后期行为 JSON（`{"action": "click", ...}`），
> 因此统计动作类型用 `LIKE '%click%'` 这类模糊匹配，或 `json_extract(action_taken,'$.action')` 二者混用会漏数。
> 复现提示 3：少量 `llm_usage.step_id` 是悬空值（`steps` 表里没有对应行，本窗口内 64 条 / 该 session $0.065），
> 做"按步归因"时要用 `t.step_id IS NOT NULL`（非 JOIN `steps`），否则会低估 1~13%。

> 性能提示：`traces` 表 30,569 行、payload 大（单条最大 ~1.1MB）。**永远不要 `SELECT *` 或 `SELECT payload`**，只用 `json_extract` 聚合；本报告所有查询都在秒级完成。

---

## 未知项（不猜）

1. **gemini 兜底调用定价**：13 次调用（`google:gemini-3.8-flash` 7 次 / `gemini-3.5-flash-lite` 6 次，103,215 prompt tok）未给价，金额未知（量级 <$0.001）。
2. **planner 每次调用实际带的截图张数**：planner 的完整 prompt 未落库（只有 summarizer 的 `ChatOpenAI` trace 带 `image_url`），"3 张 / 每次 ~1.2k 图 token"是由 `image_scrub_depth=3` 配置 + 稳态 uncached 3.2k/step 推断，非直接测量。
3. **`wait_for_delay` 中"必要性"的精确划分**：只有 96 步能确定是"连续第 2 次及以后"（判据要求），其余单次等待是否必要需人工抽样判定。
4. **R2 轮次的官方定义**：`qa_1114_v2/queue_status*.json` 只覆盖 11-15 的两轮；11-14 下午/夜间的重跑没有独立 queue 文件，本报告按时间窗切分为"R2"，可能与执行者口径不同。
