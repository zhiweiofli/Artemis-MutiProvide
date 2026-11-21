# Artemis 判断质量分析（准确性）

> 数据源：`traces/data_engine.db`（67 个 session，其中 64 个有步骤 / 2,167 steps / 30,569 traces / 2,067 张截图；累计 49,534,862 tokens；总墙钟 276.1 分钟）
> 日志：`traces/qa_1114/REPORT.md`、`traces/qa_1114_v2/SUMMARY.md`、`traces/qa_1114_v2/*/run_{BC,D,E}.log`
> 全部结论均由 SQL 聚合或截图目视得到；查不到的写「未知」。

---

## 一句话结论

**动作执行层是健康的（61.7% 的步骤真正改变了画面），失效集中在三处：判据层（第一轮 4 个 PASS 全部只靠「入口可见」——2 个从未尝试拉起面板、2 个尝试了但面板被锁/没弹）、模型层的「无 UI 树却用索引点击」（126 次瞬时失败，占全部索引点击的 53%）、以及缺少无进展熔断（最长连续 31 步画面不变，烧掉 1.01M tokens）——也就是说：模型看得没错，是「怎么算通过」和「卡住了怎么办」这两件事没被工程化。**

---

## 0. 口径与局限（先读这一节）

**动作有效性口径**：`extra_metadata.pre_image_dhash` 与 `post_image_dhash` 都是 64-bit dhash（16 hex），用汉明距离 `ham` 衡量画面变化。
- `ham > 8`：**有效**（主口径，判定"画面真的换了"）。
- `1 ≤ ham ≤ 8`：**灰区**（可能是跑马灯/计时器/特效/抗锯齿，也可能是"只变了一个小按钮"）。
- `ham = 0`：**无变化**（主口径下的失败）。

**必须记住的局限（dhash 相等 ≠ 画面完全相同）**：

1. dhash 是 8×8/9×8 的低频梯度指纹。**两次截图完全相同 ⇒ dhash 必相等；但 dhash 相等 ⇏ 画面完全相同**。一行提示文字、一个 toast、一颗小按钮的状态翻转、列表滚动后行内容相似，都可能保持同一 dhash。
2. 反过来也成立：**跑马灯公告、计时器、战斗动画**会让 dhash 变化（`ham` 常有 1–8），于是"wait 一步"看起来"很有效"。本数据集 `wait_for_delay` 的宽松有效率 88.2%，这几乎全是噪声，不是"等待让画面推进"。
3. 所以本文给两张表：**宽松口径（ham>0）** 与 **严格口径（ham>8）**。判断"点击到底有没有用"要看严格口径，且**单步结论必须用截图复核**（本文对 6 个关键步做了截图目视）。
4. 灰区规模：`ham=0` 308 步（14.2%）、`1–8` 559 步（25.8%）、`>8` 1,300 步（60.0%）。**约 26% 的步骤落在「dhash 和摘要都判不清」的地带**，这是当前可观测性的硬上限。

---

## 1. 动作有效性（问题 1）

### 1.1 总量与分布

| 指标 | 数值 |
|---|---|
| steps 总数 | 2,167 |
| 有 dhash 的 steps | 2,167（**100% 覆盖**，无缺失） |
| `ham=0` | 308（14.2%） |
| `ham 1–3` | 326（15.0%） |
| `ham 4–8` | 233（10.8%） |
| `ham 9–16` | 185（8.5%） |
| `ham >16` | 1,115（51.5%） |

### 1.2 动作有效性表（主表，排除 `report_task_status`：它天然不改画面，60/60 ham=0）

| 动作类型 | 次数 | 有效次数 (ham>8) | 有效率 | 参考：宽松口径 (ham>0) |
|---|---:|---:|---:|---:|
| click | 1,502 | 872 | **58.1%** | 87.7% |
| click_sequence | 50 | 36 | 72.0% | 94.0% |
| swipe | 18 | 6 | **33.3%**（样本小） | 94.4% |
| press_key | 102 | 83 | 81.4% | 92.2% |
| wait_for_delay | 380 | 255 | 67.1%（**多为噪声，见 §0**） | 88.2% |
| manage_app | 54 | 47 | 87.0% | 87.0% |
| input_text | 1 | 1 | 100% | 100% |
| **合计** | **2,107** | **1,300** | **61.7%** | 88.2% |

**解读**
- 真正"改画面"的点击只有 58.1%。但其中一部分不是模型的错：`swipe` 的 33.3% 是 dhash 对"列表滚动但行长得像"不敏感（例：`a4d2fb38` s5/s6 摘要明确写"list scrolled"，`ham` 只有 4/6）。**swipe 的 33.3% 应视为测量偏差，不是误判。**
- 唯一"看起来最无效"的确定缺陷是 **索引点击**：`click` 共 1,502 次，其中 237 次用整数索引（`args.target` 为 integer），**126 次当场返回 `Invalid target index N. The list is empty on this screen`（53.2%）**，这 126 步的 `ham` 几乎恒为 0。

### 1.3 工具层失败（自伤，不是语义误判）

| 失败类型 | 步数 | 占全部 steps |
|---|---:|---:|
| `Invalid target index`（元素列表为空仍用索引） | 126 | 5.8% |
| `Tap failed at (...)`（坐标越界/注入层失效） | 5 | 0.2% |
| `Failed to launch app` | 3 | 0.1% |
| 其它 failed | 2 | 0.1% |
| **合计** | **136** | **6.3%** |

`Tap failed` 的根因在 `4600dc04` 的报告里被模型自己写清楚了：**「规范化坐标被按 2166 高度换算，实际屏幕为 1080×1080」** —— 分辨率切换（掉线后采集到 1080×1080 纯绿帧）时坐标空间没有重新校准。这是一条可复现的工具缺陷，非模型问题。

### 1.4 连续无变化的最长步数（停摆）

按严格口径（`ham ≤ 8` 视为"这一步什么都没发生"，跳过 `report_task_status`）：

| 排名 | session | 游戏/阶段 | 最长连续无变化 | 区间 | 该区间代价 |
|---:|---|---|---:|---|---|
| 1 | `4600dc04` | 斗破苍穹 / E | **31 步** | s126–s156 | 3.3 分钟 / **1,012,975 tokens** |
| 2 | `0d36c92b` | 一剑断念 / B+C | 19 步 | s4–s22 | 3.1 分钟 / 283,434 tokens |
| 3 | `b80f03a1` | 冲吧勇者 / D | 12 步 | s34–s45 | 2.4 分钟 / 261,505 tokens |
| 4 | `872aa6bc` | 冲吧勇者 / D | 12 步 | s10–s21 | 7.1 分钟 / 184,858 tokens |
| 5 | `170ed824` | 一剑断念 / E | 12 步 | s112–s123 | 0.9 分钟 / 399,080 tokens |
| 6 | `e6750112` | 一点三国 / D | 11 步 | s29–s39 | 2.8 分钟 / 249,916 tokens |
| 7 | `8d2e7675` | 一剑断念 / D | 11 步 | s33–s43 | 0.6 分钟 / 247,787 tokens |
| 8 | `a325bee8` | 一点三国 / D | 7 步 | s190–s196 | — |
| （旁证）| `684de6e0` | 非质检（九游 SDK Demo 登录） | 9 步 | s6–s14 | 193,483 tokens |

**关键发现：Artemis 违反了自己写在 goal 里的护栏。**
goal 原文（所有 session 一致）：「若连续 8 次操作画面无任何变化，判定为卡死」。实测**7 个手游 session 的连续无变化 ≥ 9 步**（另有 1 个非质检 session 9 步，共 8 个），没有一个在 8 步处判 FAIL。最极端的 `4600dc04` 是 31 步——报告里自己写了「已远超『连续 8 次操作无变化』的卡死阈值」，说明规则被读到但**没有被 runner 强制执行**（它只是提示词，不是代码）。

---

## 2. 重复与循环（问题 2）

### 2.1 精确重复（同 session 内 act + 坐标 + target 描述完全一致的重放）

| 动作类型 | 重复执行次数（扣掉首次） |
|---|---:|
| wait_for_delay | 334 |
| click | 217 |
| press_key | 78 |
| manage_app | 23 |
| click_sequence | 15 |
| swipe | 3 |
| **合计** | **670（占 2,167 步的 30.9%）** |

> 其中 wait 的 334 次有一部分是合理的"等加载"（如 `872aa6bc` 等资源下载 8%→98%），不算浪费；**click 的 217 次重复是纯浪费**。

### 2.2 「原地打转」段落（可复述的原文证据）

| session | 段落 | 现象 | 原文（截断） |
|---|---|---|---|
| `4600dc04` 斗破/E | s127–s156（30 步） | 21 次 `click` + 4 次 `press_key` + 5 次 `manage_app`，**全部失败/无效**（全 session 累计 32 次点"index 14"、18 次点"index 1"） | s127「Error during click: Invalid target index 14…」、s145「Failed to launch app 'com.rastar…'」 |
| `170ed824` 一剑/E | s113–s123 | 11 步里 9 步点"index 14"（该 session 累计 30 次） | s116「my aim was the '再玩一会' entry at index 14」→ 每步都「Invalid target index 14」 |
| `0d36c92b` 一剑/B+C | s11–s22 | 8 步点"index 3"（切换游戏号） | s12「my tap aimed at index 3 … was rejected with 'Invalid target index 3. The list is empty on this screen'」 |
| `a325bee8` 一点三国/D | s185–s196 | 反复点军师面板「升级/自动升级」，6 步里 5 步 ham≤1 | s190「点击后画面仍停留在『军师』面板」 |
| `e6750112` 一点三国/D | s31–s39 | 5 次点「商店」，全部 ham=0 | 报告自述「点击商店等页签时仅弹出『新手引导中』功能锁定提示」 |

### 2.3 坐标聚集（软信号，含合理重放）

- 同一 session 内"点击中心点相距 ≤40/1000 且成簇 ≥3 次"的点击共 **723 次 / 1,502 次（48.1%）**，集中于 D/E 阶段长 session：
  `a325bee8` 130 次、`3feafb5d` 79 次、`09b7af9a` 73 次、`4ace4c15` 70 次。
- 这条**不能**直接当缺陷：点"对话框"推进剧情本来就是同一点位重复。它的价值是定位候选段落（本文用它找到了 s113–s123 这类真循环）。

### 2.4 代价

- 7 个最长停摆窗口合计 **≈2.64M tokens（占总量 5.3%）**，墙钟 ≈20 分钟。
- 纯等待：`wait_for_delay` 380 次，累计 **4,824 秒 = 80.4 分钟 = 总墙钟 276.1 分钟的 29%**。最极端 `872aa6bc`（冲吧/D）：29.0 分钟里有 **24.5 分钟是 wait（84%）**，期间设备自动锁屏 3 次（s22/s26/s32 的"锁屏"描述，见 §5.1）。

---

## 3. 视觉调用质量（问题 3）

**调用计数**：`object_detector` 日志 `Calling Object Detector for '…'` 共 **273 次**（与 `Fused results from parallel inference` 128 次对应：一次 explorer 会话内并行提多问）；`tool/ask_explorer` 128 次、`agent/explorer` 128 次。
配置（`.env` + `config/artemis.jsonc` 的 `ds-qwen-hybrid` 预设）：节点 `object_detector` → provider `qwen` → `Qwen/Qwen3-VL-30B-A3B-Instruct`，`QWEN_BASE_URL=https://api.siliconflow.cn/v1`（代码里 `artemis/config/llm.py:289` 检测到 `siliconflow` 就切 `coord_format=bbox_xyxy_1000` 并把 timeout 抬到 35s，可证线上确实走 SiliconFlow）。

| 指标 | 数值 |
|---|---|
| Qwen 定位调用总数 | 273 |
| 调用时**前置截图根本没有可访问性文本**（按 `ui_tree` 里 `text`/`content-desc` 全为空判定，即 Unity/Cocos 画面）的比例 | **226 / 273 = 82.8%** |
| 可解析出目标文字（引号内）的调用 | 206 / 273 = 75.5% |
| 其中目标文字**已经出现在 UI 树里**（纯浪费）的次数 | **0 / 206** |
| 调用后紧接的那一步真正改变画面（ham>8） | **174 / 273 = 63.7%** |
| 对照：全部非 wait/report 动作的基线 | 68.6% |
| 对照：click/click_sequence 基线 | **66.2%**（915/1,383） |
| 调用后 3 步内的平均变化率 | 65.7% |

**结论（数据推翻了一个猜想、确认了另一个问题）**
1. **没有被浪费在"UI 树能解决"的地方**：0 次调用的目标文本已在树中；82.8% 的调用发生在没有任何 a11y 文本的画面上——Qwen 确实被用在了它该用的地方。
2. **但也没有带来可测量的增益**：调用后那一步 63.7% < 点击基线 66.2%（差 −2.5pp）。也就是说 **Qwen 定位的点击并没有比"平均一次点击"更容易生效**，约 36% 的 Qwen 定位点击当场无效（点位偏、或被引导层/浮层遮挡）。
3. **真正被浪费的是"该用视觉时没用"**：126 次 `Invalid target index` 全部发生在元素列表为空的画面上——模型本应走 `ask_explorer`/坐标，却坚持传索引，**一步都没省下来**（这 126 步是 6.3% 的纯损耗，且是 self-inflicted）。
4. 调用集中度：斗破 E 57 次、一点三国 D 55 次、斗破 D 40 次、冲吧 E 32 次——**D/E 阶段的视觉需求是 BC 的 3–10 倍**，成本应据此预算（斗破 D 单 session 6.37M tokens 即由此而来）。

---

## 4. 结论可信度核查（问题 4）

**判据的版本差异先要说清**（这决定了"PASS"到底在承诺什么）：

- **第一轮 `qa_1114`**（DB 里 2026-11-14 那批）goal 原文：
  「完成标记**任一**满足即 PASS：(a) 引导遮罩与引导手指消失，**且界面上可见**充值、首充、商城或钻石+入口；(b) 已累计游玩超过30分钟。」
  → **判据 (a) 只要求"入口可见"，根本不含"面板能拉起"**；判据 (b) 是纯时间兜底。
- **第二轮 `qa_1114_v2`**（SUMMARY.md 那批）：三项全满足才 PASS（引导消失 + 入口可见 + 面板真正拉起），D 阶段 40 分钟记 TIMEOUT。

### 4.1 核查表

| 游戏 | 阶段 / 轮次 | 判定 | 证据是否充分 | 问题描述（含原文/数字） |
|---|---|---|---|---|
| 斗破苍穹 | D / **r1** `3feafb5d` | PASS | **不足** | 报告只写「满足 PASS 条件 (a)」。SQL 核查：该 session **0 次**点击过 充值/商店/商城/钻石（按 target_description 与摘要双向过滤均为空）→ 验收③**从未尝试**。 |
| 一剑断念 | D / **r1** `8d2e7675` | PASS | **不足** | 同上，**0 次**充值/商城点击；唯一提到"商城"的 7 条记录全是 `tc='14'` 的 Invalid-index 失败步。 |
| 冲吧勇者 | D / **r1** `872aa6bc` | PASS | **不足** | 只尝试 1 次（s56 点底部「商店」，`ham=28` 但摘要写「the view then changed to a **hero detail page**… **No shop page is visible on this screen**」——被引导强拉走）。报告自认「**全程未触发任何支付/充值面板**」，却判 PASS——典型的「入口可见 ≠ 面板弹出」。 |
| 一点三国 | D / **r1** `e6750112` | PASS | **不足** | 6 次点「商店」，**5 次 ham=0、1 次 ham=1**；报告自己写「点击商店等页签时仅弹出**「新手引导中」功能锁定提示**」→ 面板没弹出，判 PASS。报告还保留旧判据痕迹：「另一完成标记 b『累计游玩超30分钟』未达…但标记 a 已满足即判 PASS」。 |
| 一点三国 | D / **r2 第 1 次** `a325bee8` | FAIL | 充分 | ①未满足（「最后画面（T+27:58）左下仍显示『通关黄天余烬1-5(0/1) 绑元x40』+ 金色圆环 + 指向手指」），②③均满足并给了具体商品与金额。判 FAIL 与判据自洽，但**结论不能读作"游戏问题"**：同账号另一次 774 s 判 PASS（见 §5.2），差别只是账号进度停在哪一格。 |
| 一点三国 | D / **r2 第 2 次** `4ace4c15` | PASS | 基本充分 | ③最好（s107 底部商店 `ham=36`、s108 元宝旁「+」`ham=28`，给出档位 1/300/5/10 元宝与「五倍首充」面板）。但 ①的证据是「任务条推进为『军师升级15次(11/15)』，引导手指不再出现」——**任务链仍在继续**，"手指此刻不在"≠"引导结束"。 |
| 斗破苍穹 | D / **v2** `7706ef66` | PASS | **充分** | 唯一有第三方支付面单证：s14 充值面板 `ham=29`，s20/s23 关闭「九游充值中心」`ham=13/20`，报告写明「¥30.00、微信（已选）/支付宝、橙色『确认充值 ￥30.00』」。 |
| 一剑断念 | D / **v2** `05fc0482` | PASS | 充分 | s13 点「商城」`ham=27`，报告给出「活动中心·每日必购」档位与 6 元金额。 |
| 冲吧勇者 | D / **v2** `b80f03a1` | PASS | 基本充分（**归因错位**） | 面板确实出现过：**s59** `ham=25`，摘要「the after screen showed a diamond purchase panel… 60钻石/6元 … 6480钻石/648元」。但报告写「点击钻石旁『+』后弹出」，而被指认的 **s58 摘要明确「no recharge or payment panel appeared」**（`ham=7`）。结论对、证据链错一步。 |
| 大圣 | B+C（5 次） | FAIL | 充分但**归因存疑** | 「链接已失效」+「WLAN 未连接到互联网」记录详实。但 13 个 FAIL 里有 **10 个是「链接已失效」**，其中 **7 个集中在两个多游戏并发窗口**（00:27–00:28 命中 2 款；11:07–11:11 命中 5 款：大圣/一点三国/一剑断念/斗破/冲吧）→ 这 7 个是**环境缺陷**，不能算单款游戏的结论。 |
| 一剑断念 | B+C `db3c84d2` | FAIL | 充分 | 「登录失败 — 网络状况不好，请点击『确定』重试」原文完整。同款游戏 2 小时后 `d23dbae1` PASS → **同一游戏结论翻转，归因是网络**。 |
| 一点三国 | B+C `9dd36d7e` | FAIL | **不足** | 只跑了 **1 步**就判 FAIL，且报告承认「设备状态栏同时显示『WLAN 未连接到互联网』，属网络不可用导致的启动失败」——已知是环境问题仍记为游戏 FAIL。 |
| 斗破苍穹 | E `4600dc04` | FAIL | 充分（且诚实） | 明确写出「纯绿空白帧」「坐标按 2166 高度换算，实际屏幕 1080×1080」「launch 连续 3 次失败」。唯一的瑕疵是**拖了 31 步**才判。 |

### 4.2 结论

- **「证据不足却判 PASS」：确认 4 例，全部在第一轮**（斗破 r1、一剑 r1、冲吧 r1、一点三国 r1）——**第一轮 4 个 PASS 的验收③ 全部没有成立**（2 个 0 次尝试，2 个尝试了但面板没弹/被锁）。这不是模型"编造"，而是**判据 (a) 本身不要求面板弹出**，模型严格照做了。
- **「证据充分却判 FAIL」：语义层 0 例**。所有 FAIL 报告的证据都对得上画面。真正的问题是**归因层**：13 个 FAIL 中 10 个是「链接已失效」，其中 7 个与其它游戏同分钟并发，属环境缺陷被记成游戏缺陷。
- **报告与步骤日志一致性**：逐帧抽查 6 个关键步，摘要的"变了/没变"方向与 dhash 全部一致（例：`872aa6bc` s56 点底部「商店」，`ham=28`，摘要如实写「the view then changed to a hero detail page… **No shop page is visible on this screen**」——被引导强拉去英雄详情，不是商店）。唯一的偏差是 `b80f03a1` 的验收③：面板在 **s59** 出现（`ham=25`），报告却记成"点 s58 的 + 号后弹出"（s58 摘要明确"no panel appeared"，`ham=7`），属**归因错位**，结论不受影响。
- 双侧一致性检查（关键词启发式）：`ham>16` 且摘要硬说"无变化"仅 4 例（`313c9400` s19、`a325bee8` s126、`addfad80` s11、`db3c84d2` s3）；`ham=0` 且摘要声称有变化 36 例（多为摘要里的 "appeared" 出现在 "no panel appeared" 这类否定句，属启发式噪声）。**真正的灰区是 §0 的 559 步，不是这些极值。**
- `report_task_status` 共 **60 次**（以 `steps` 表为准：47 次 `completed`、13 次 `failed`）；`qa_1114`/`qa_1114_v2` 归档日志里可见 37 次 `Executing Flash tool: report_task_status`，其余发生在未归档 log 的 session（如 2026-11-14 的探索性跑批）。

---

## 5. 判据设计缺陷（问题 5，每条带真实案例）

### 5.1 「锁屏画面」不是语义误判——但暴露了更贵的病

**用截图证伪**：`872aa6bc` 的"锁屏"共 3 段 —— s22 wait（发现锁屏，`ham=21`）、s23 click + s24 swipe（第一次解锁，`ham=0/23`）、s27 swipe（第二次，`ham=20`）、s32 wait + s33 click_sequence（第三次，`ham=21/16`）。对应截图 `9d4618fa…jpg`（21:47）、`7889a6dc…jpg`（22:00）经目视**确为真锁屏**（黑底 + 二次元剑士壁纸 + 「省电模式中…」「WIFI 80%」「抬起手机或点击屏幕解锁」）。
**所以"把资源下载页误述成锁屏并真的点击+上滑"这一疑点，用数据推翻了。**
真实病因在别处：**同一 session 29 分钟里 24.5 分钟在 wait**（s22 一次 wait 240,000ms，s26 150,000ms，s28 90,000ms，s32 60,000ms），设备因此三次自动锁屏、每次都要 1–2 步解锁。**"长时间盲等"才是这个案例的缺陷**，它同时解释了 33.3% 的低变化率和 29 分钟的超长 D 阶段。

### 5.2 「引导无终点」→ 同一账号两种结论（`一点三国` 实锤）

| 轮次 | session | 墙钟（步间跨度 / SUMMARY 记） | 步数 | 收尾任务条 | 判定 |
|---|---|---:|---:|---|---|
| 第 1 次 | `a325bee8` | **1,678 s / 1,710.7 s（27.97 min）** | 212 | 「通关黄天余烬1-5(0/1)」+ 金环 + 手指 | FAIL |
| 第 2 次 | `4ace4c15` | **774 s / 810.3 s（12.9 min）** | 110 | 「军师升级15次(11/15)」，手指不在 | PASS |

同一账号「黎阳关瑾瑜」（Lv.108 → Lv.112）。两次的差别**不是 Agent 判断水平，而是账号进度恰好停在"手指在/不在"的位置**。证据：PASS 那次的①依据本身就是"任务条推进到『军师升级15次』"，即**引导链并未结束，只是手指暂时不显示**。
→ 判据①（"引导遮罩与手指消失"）对这类游戏**不可判定**：它是瞬时状态，不是终态。

### 5.3 「30 分钟兜底」= 假 PASS 的现成通道（第一轮），且三次踩在门口

第一轮判据 (b)：「已累计游玩超过30分钟」即 PASS。本数据集**没有任何 PASS 是明确引用 (b) 通过的**（`e6750112` 明确写"标记 b 未达"），但 D 阶段墙钟分布显示这扇门只差一口气：

| session | 游戏 | D 墙钟 | 距 1,800 s | 当时判定 |
|---|---|---:|---:|---|
| `a325bee8` | 一点三国 | 1,678 s | **差 122 s** | FAIL（①未满足） |
| `3feafb5d` | 斗破 | 1,700 s | **差 100 s** | PASS（(a)，③未做） |
| `872aa6bc` | 冲吧 | 1,743 s | **差 57 s** | PASS（(a)，③未做） |

即：**只要再多等 1–2 分钟，`a325bee8` 这个"真 FAIL"就会变成"假 PASS"**。判据 (b) 是纯时间信号，与验收三项零耦合，本质是"跑满时长即合格"。

### 5.4 「40 分钟 TIMEOUT」：从未触发，有效性未知

v2 把时间兜底改成 TIMEOUT（超时不算 PASS），方向正确。但本数据集 **D 阶段最长 1,700 s（28.3 min），0 次 TIMEOUT**，所以"TIMEOUT 会不会把本该 PASS 的判成 TIMEOUT"**没有数据，属未知**。
可预见的一例：`872aa6bc` 在 v2 判据下（手指消失但面板始终不弹）会一直跑到 40 分钟 → 从 r1 的 **PASS 变成 TIMEOUT**，同一局、同一画面，结论相反。

### 5.5 「入口可见」被当成「面板弹出」（偷换概念的风险已实现，非理论风险）

- 第一轮判据 (a) 的字面要求就是"可见"，模型据此把 PASS 写得很自然：
  - `e6750112`：「验证②主界面可见商店/充值入口：满足」+「③…仅弹出『新手引导中』锁定提示」→ 仍 PASS。
  - `872aa6bc`：「满足条件 (a)…且界面可见钻石+入口与商城入口」+「全程未触发任何支付/充值面板」→ 仍 PASS。
- 第二轮修好了判据，但**报告文字仍会漂移**：`b80f03a1` 面板出现在 s59，报告归给 s58。逐字读报告会得到"点 + 号就弹面板"，逐帧读日志得到"点 + 号没反应，下一次点击才弹"——**报告是二次叙述，不是证据**。

### 5.6 环境缺陷被写成游戏缺陷（跨游戏并发相关）

- 2026-11-15 **00:27:09 / 00:28:13**：大圣、一点三国 两款先后「链接已失效」。
- 2026-11-15 **11:07:10 → 11:11:13**：大圣、一点三国、一剑断念、斗破、冲吧 **5 款在 4 分 3 秒内全部**「链接已失效」+「WLAN 未连接到互联网」。
- 之后（11:20/11:23/13:29）只有大圣继续失败，其它 4 款在 11:24–14:36 陆续 PASS。
→ 结论：**「链接已失效」在 burst 窗口内是环境信号；只有大圣后续 3 次孤立复现才构成游戏侧证据。** SUMMARY.md 的「已排除设备网络因素」只在 11:20 之后成立，00:27 与 11:07 那两批不能这么算。

### 5.7 规则写在提示词里，没有写进代码

§1.4 的 7 个 session（最长 31 步）证明「连续 8 步无变化 → FAIL」只是 goal 文本；`4600dc04` 的报告甚至自己引用了这条规则却仍继续跑了 31 步。**判据用自然语言表达时，模型会"引用"它而不会"执行"它。**

---

## 6. 五条优化建议

### 建议 1｜结论—证据绑定：给 `report_task_status` 加"证据令牌"，并让判定器核验

- **做的事**
  1. `report_task_status` 的 schema 增加必填 `evidence` 数组，每条验收至少一项：`{criterion: 1|2|3, step_number, screenshot_hash, expected_signal}`。
  2. 判定器（新，约 200 行的离线校验脚本/服务）对 criterion=3 校验：存在某一步 `pre_image_dhash→post_image_dhash` 的 `ham ≥ 20`（面板级阶跃）**且** 该步摘要/OCR 命中档位关键字（`元|钻石|灵玉|￥|首充|档`）。
  3. 缺失或不匹配 → 结论降级为 `NEEDS_RETEST`，而不是 PASS。
  4. 同时给每条 FAIL 打 `env_suspect` 标记：同批次（±10 分钟）≥2 款游戏出现同一失败原文 → 标记为环境。
- **提升指标**：PASS 证据充分率（第一轮 0/4 → 目标 4/4）；环境误归因 FAIL（13 中 7 → 0）。
- **实现成本**：M（1.5–2 人日；schema 改动小，校验器是纯 dhash+正则，无需模型）。
- **风险**：真的"面板被引导层遮住"时会降级成 NEEDS_RETEST，增加重跑成本；`ham` 阈值 20 需要在 5–10 局上标定，否则误杀（例如 `b80f03a1` s59=25 刚好过线，s108=28）。

### 建议 2｜把"无进展"从提示词搬进 runner：硬熔断 + 换策略

- **做的事**：runner 内建 `ProgressMonitor`：连续 N 步（建议 N=6，保守 8）满足「动作 ∈ {click, press_key} 且 ham ≤ 8 且工具结果非 failed」，则按序执行 `BACK → 回桌面+重启应用 → 直接 FAIL(reason=STUCK)`，并把该段落标记进报告。`wait_for_delay` / `manage_app` 不计入（避免把加载中误判为卡死）。
- **提升指标**：最长连续无变化 31 → ≤6；7 个违规 session → 0；停摆内耗 tokens（≈2.64M / 5.3%）→ ≤0.5M。
- **实现成本**：S（0.5–1 人日，纯 runner 层，不动模型提示词）。
- **风险**：对"逐句点对话推进剧情"这类**合法的同点重放**会误熔断（如 `a325bee8` D 阶段 4 次点同一「剧情对话框」`[600,795]`、3 次点同一「开始游戏按钮」`[500,786]`，都属于该点就得点）。缓解：仅当"画面无变化 **且** 摘要未出现新文本"时才计数（摘要出现新台词即豁免）。

### 建议 3｜空树索引熔断：无 UI 元素时禁止索引点击，强制走视觉/坐标

- **做的事**：click 工具入口做前置校验——`isinstance(target, int)` 且当前元素列表为空 → **不执行**，直接返回可执行指令（`ask_explorer` 或坐标），并累加该 session 的 `index_attempt_on_empty_tree`。同一目标第 2 次仍传索引 → 直接转 `ask_explorer`。
- **提升指标**：`Invalid target index` 126 次（占索引点击 53.2%、占总步数 5.8%） → 0；顺带把「无变化步数」拉低约 5pp。
- **实现成本**：S（0.5 人日，工具层 20 行）。
- **风险**：视觉定位会真的多花钱（Qwen 一次调用 + 约 2–3 步），净效果取决于 §3 的 63.7% 命中率；建议同时上建议 4。

### 建议 4｜Qwen 调用前后各加一道校验（让 63.7% 提到 >80%）

- **做的事**
  1. **调用前**：只有当目标文字不在 UI 树、且画面无 a11y 文本时才调（现状已 82.8% 无树，可保留；0 次浪费这一点已达标，别退化）。
  2. **调用后**：点击落在 Qwen 返回 bbox 的中心；**若该步 `ham ≤ 8`（没反应），自动在该 bbox 内做一次 ±3% 屏宽的抖动重试点**（最多 2 次），再不行才换策略。数据依据：Qwen 定位后 36% 的点击当场无效，而无效点击里很大比例是"离线/被引导层挡"。
  3. 记录 `qwen_hit / qwen_retry / qwen_miss` 三元指标，按游戏出报表。
- **提升指标**：Qwen 后动作有效率 63.7% → 目标 80%+；重复点击（217 次）相应下降。
- **实现成本**：M（1 人日；需要 bbox 中心 + 抖动逻辑，`object_detector.py` 已经产出标准化坐标，改造面小）。
- **风险**：抖动重试可能与游戏内的"连点判定"冲突（如抽卡/购买）；必须限定只对 `click` 且目标非付费按钮生效。

### 建议 5｜判据分支化：`NO_TUTORIAL_END` + 用"进度"代替"墙钟"

- **做的事**
  1. 新增判定分支：D 阶段前 10 分钟内若检测到"任务条/主线进度持续前进但引导手指间歇出现"，则标记 `NO_TUTORIAL_END`，改用「连续 2 次 4 s 无手指 + 面板可拉起」为通过条件，并在报告首行声明。
  2. TIMEOUT 触发条件从"墙钟 40 分钟"改为「墙钟 40 分钟 **且** 进度信号（任务条文本/等级/关卡）在最近 10 分钟内无变化」；有进度则延长上限。
  3. 明确废弃"30 分钟兜底"（第一轮 (b)），并在校验器里拒绝任何引用 (b) 的 PASS（`e6750112` 那种"标记 a/b"话术直接判无效）。
- **提升指标**：同账号两次跑结论一致率（一点三国 0/1 → 目标 1/1）；`NO_TUTORIAL_END` 这类游戏的 PASS/FAIL 可复现性；避免"差 57–122 秒翻结论"的时间悬崖。
- **实现成本**：M（1–2 人日，需在 prompt 与校验器两处落地，并在 2–3 款无限引导游戏上回归）。
- **风险**：`NO_TUTORIAL_END` 天然放宽验收①，可能掩盖真实的"引导卡死"bug（`a325bee8` 那种 1-5 关永远打不完）；必须强制在报告里保留"最后任务条原文 + 停留时长"，供人工判定。

---

## 7. 附录：关键 SQL / grep

```sql
-- A. dhash 覆盖率与变化分布（含灰区）
SELECT count(*) total,
       sum(json_extract(extra_metadata,'$.pre_image_dhash')  IS NOT NULL) has_pre,
       sum(json_extract(extra_metadata,'$.post_image_dhash') IS NOT NULL) has_post
FROM steps;

-- B. 每步汉明距离（SQLite 无 bit_count，故用 Python 跑；此处给导出口径）
SELECT session_id, step_number,
       json_extract(action_taken,'$.action')        AS act,
       json_extract(extra_metadata,'$.pre_image_dhash')  AS pre,
       json_extract(extra_metadata,'$.post_image_dhash') AS post,
       json_extract(extra_metadata,'$.token_usage.total_tokens') AS tok,
       last_execution_result, summary
FROM steps ORDER BY session_id, step_number;
-- 然后在 Python 里： ham = bin(int(pre,16)^int(post,16)).count("1")；ham>8 记为有效

-- C. 动作类型分布 / 索引点击 / 工具失败
SELECT json_extract(action_taken,'$.action') act, count(*) FROM steps GROUP BY act ORDER BY 2 DESC;
SELECT sum(json_type(action_taken,'$.args.target')='integer') idx_clicks, count(*)
FROM steps WHERE json_extract(action_taken,'$.action')='click';
SELECT count(*) FROM steps WHERE last_execution_result LIKE '%Invalid target index%';   -- 126
SELECT count(*) FROM steps WHERE last_execution_result LIKE '%Tap failed%';            -- 5
SELECT count(*) FROM steps WHERE last_execution_result LIKE '%Failed to launch app%';  -- 3

-- D. 游戏 / 阶段 / 墙钟（session 名从 initial_goal 解析《》与“阶段X”）
SELECT s.session_id, s.initial_goal, s.status,
       min(st.timestamp) t0, max(st.timestamp) t1, (max(st.timestamp)-min(st.timestamp))/60.0 minutes,
       count(*) n
FROM sessions s JOIN steps st ON st.session_id=s.session_id
GROUP BY s.session_id ORDER BY t1 DESC;

-- E. 每个 session 是否点过“充值/商店/商城/钻石”（验收③ 是否被尝试）
SELECT session_id, step_number,
       json_extract(action_taken,'$.args.target_description') tc,
       json_extract(extra_metadata,'$.pre_image_dhash')||'->'||json_extract(extra_metadata,'$.post_image_dhash') d
FROM steps
WHERE (json_extract(action_taken,'$.args.target_description') LIKE '%充值%'
    OR json_extract(action_taken,'$.args.target_description') LIKE '%商店%'
    OR json_extract(action_taken,'$.args.target_description') LIKE '%商城%'
    OR json_extract(action_taken,'$.args.target_description') LIKE '%钻石%')
ORDER BY session_id, step_number;

-- F. Qwen(object_detector) 调用次数与去向
SELECT session_id, count(*) FROM traces
WHERE json_extract(payload,'$.message') LIKE 'Calling Object Detector%'
GROUP BY session_id ORDER BY 2 DESC;                                                   -- 273 total
SELECT count(*) FROM traces WHERE json_extract(payload,'$.message')='Fused results from parallel inference.';  -- 128

-- G. 报告原文（判据核查）
SELECT s.session_id, s.step_number, s.action_taken FROM steps s
WHERE s.action_taken LIKE '%report_task_status%' ORDER BY s.timestamp;                 -- 60 条
```

```bash
# 日志侧（注意：goal 文本里也含 report_task_status，必须过滤；真正执行行用下面这条）
grep -rn "Executing Flash tool: report_task_status" traces/qa_1114/ traces/qa_1114_v2/ --include="*.log" | wc -l   # 37
grep -rn "report_task_status" traces/qa_1114_v2/ --include="*.log" | wc -l                                          # 64（含 goal/提示词命中）

# 第一轮 goal 原文（证明“入口可见 + 30 分钟兜底”）
sqlite3 traces/data_engine.db "SELECT initial_goal FROM sessions WHERE session_id LIKE 'e6750112%';"

# 锁屏疑点的截图取证（截图为 sha256 命名，落在 traces/images/）
sqlite3 traces/data_engine.db "SELECT step_number, pre_image_name, post_image_name FROM steps \
  WHERE session_id LIKE '872aa6bc%' AND step_number IN (22,23,24,26,27,32,33);"
sips -Z 700 traces/images/<hash>.jpg --out /tmp/check.jpg    # 目视：真锁屏（21:47 / 22:00）

# 模型配置取证
grep -n "QWEN_BASE_MODEL\|QWEN_BASE_URL" .env        # SiliconFlow + Qwen/Qwen3-VL-30B-A3B-Instruct
grep -n -A12 '"ds-qwen-hybrid"' config/artemis.jsonc # object_detector → provider qwen
sed -n 280,300p artemis/config/llm.py                # siliconflow ⇒ coord_format=bbox_xyxy_1000, timeout≥35s

# 视觉提问记录
grep -c "ask_explorer" traces/qa_1114_v2/*/run_*.log
```

---

## 8. 明确「未知」的部分

1. **40 分钟 TIMEOUT 的误判率**：本数据集 0 次触发（D 阶段最长 1,700 s），无样本。
2. **"面板真弹了但被判无"**：灰区 559 步（25.8%）里可能藏有此类，dhash 与摘要都不足以定性，需逐帧人审，未做。
3. **Qwen 定位误差的像素级分布**：`object_detector` 日志未落库 bbox 与点击点，只有 `Calling/Received/Fused` 三类消息，无法算 IoU；只能以"下一步是否变画面"作为弱代理。
4. **PASS/FAIL 与游戏真实付费能力的相关性**：无游戏侧对照数据（后台订单/真实用户日志），本文只评估"证据是否支撑结论"，不评估"游戏是否真的可充值"。
