# 九游每日新游质检 · 运行手册

固定在**每天 19:00** 执行（cron「九游每日新游质检」）。目标：从九游「即将上线 → 今天」里挑
**≥5 款当日首发**，装好并跑完 B+C / D / E 三阶段质检，最后给出与历史基线的对比。

## 硬约束

1. **绝不点击任何付款 / 确认支付按钮**。充值面板只允许拉起、截图、立即返回。
2. 遇到手机号验证码、实名认证、人脸识别 → 该游戏记 `BLOCKED`，不尝试绕过。
3. 判定必须来自结构化信号：`result=` 或 `[REPORT_GATE] verdict=`，不读模型自述。
4. 跑完必须把当天记录写进 `docs/qa_daily/ledger.json`（`run_games.py` 会自动做）。
5. 设备是 Pixel 3 `89FX09M9U`，仓库 `/Users/zw-mini/orca/artemis`，预设 `ARTEMIS_PRESET=ds-qwen-hybrid`。

## 首选：一条命令跑完（纯脚本）

```bash
python3 scripts/qa_daily/run_daily.py --budget-min 180
```

它按顺序做完：前置检查 → 清场（force-stop 往期游戏）→ 取当日可跑首发 → 装前空间核算（3× 包体积，
不够就按最近任务倒序卸载**我们自己装过的包**）→ 安装 → BC/D/E（交 Artemis）→ 收尾 force-stop → 写台账。

退出码：`0` 跑完 / `2` 前置条件不满足 / `3` 另一轮在跑 / `4` 当日无可跑首发 / `5` 安装全失败 / `6` 反复崩溃中止。

**只有非 0 时**才需要按下面的分步流程人工判断；0 就只写报告，不用再动设备。

## 分步流程（脚本失败或需要人工判断时）



### 1. 前置检查

```bash
cd /Users/zw-mini/orca/artemis
python3 scripts/qa_daily/preflight.py --json; echo "exit=$?"
```

- `exit=0` 且 `allowed=true` 才继续。
- `exit=2` → 立刻停止，把 `reasons` 发给用户，当天不跑、不写台账。

判定规则：设备在线 / 网络 0% 丢包 / `/data` 剩余 ≥10 GB / 连续执行天数 <4。
另外 preflight 会返回 `busy`：为 true 说明**另一轮正在跑**（单实例锁 `/tmp/artemis_qa_daily.lock` 或
`run_games.py` / `install_game.py` 进程还在）。此时必须停手——不要安装、不要跑测、不要 force-stop 任何游戏，
只输出一句「另一轮在跑，本轮跳过」。2026-11-18 就是补跑守卫和 19:00 那轮撞了，误杀了正在跑的 E 阶段。

### 2. 取当日首发清单

```bash
python3 scripts/qa_daily/today_launches.py --json --require-download > /tmp/launches.json
```

> 2026-11-17 修：旧版本读首页横向卡片会把「明天」的首发算进「今天」。现在固定走
> 「首页 · 即将上线 · 更多 → 新游首发 tab → 竖向日期分组列表」，每屏只 dump 一次。

- 只保留 `date` 为「今天」且 `kind` 为「首发」的条目；`action` 必须是「下载」才算可跑。
- **数量规则（2026-11-17 定）**：目标 ≥5 款；若当日可下载首发不足 5 款，**跑完全部可下载的（≥1 款即跑）**，
  并在报告与台账里标注「当日首发仅 N 款」。只有 0 款时才停止并告知用户。
- 绝不用「更新 / 新活动 / 删档测试」凑数——那类不属于首发。

### 3. 下载安装（逐款）

```bash
python3 scripts/qa_daily/install_game.py --name "<游戏名>" --timeout-min 15
```

- 成功输出 `{"ok": true, "name": …, "package": …}`；失败 `exit=2` + 原因。
- 安装失败或超时的游戏跳过，继续下一款；最终凑够 ≥5 款开始跑测，不足 5 款就如实汇报。

### 4. 跑测

```bash
cat > /tmp/games.json <<'JSON'
[{"name": "…", "package": "com.…", "schedule": "10:00 首发"}]
JSON
python3 scripts/qa_daily/run_games.py --games /tmp/games.json --budget-min 180
```

- 每款：B+C（900s）→ D（1500s，带 A1 硬门 + `--locked-app`）→ E（1200s）。
- 结果写 `traces/qa_daily_<stamp>/SUMMARY.md` 与 `summary.csv`。

### 5. 对比与汇报

报告写到 `docs/qa_daily/reports/YYYY-MM-DD.md`，必须回答三个问题：

| 指标 | 对比对象 | 判据 |
|---|---|---|
| 每局成本 / 耗时 | `docs/qa_daily/ledger.json` 与 `docs/baseline/S0_BASELINE_2026-11-16.md` | 是否下降 |
| 成功率 | 上轮 PASS 率 | **注意 A1 之后 PASS 数可能下降是正确行为**：要看「PASS 但三项验收不成立」是否为 0 |
| 假绿信号 | 空树索引失败、1×1 入模帧、`llm_pause` 次数 | 应为 0 或显著下降 |

汇报给用户：几款、各自判决、总耗时、成本估算、与上轮差异、以及「变更是否有效」的结论（一句话，有证据）。

## 已知坑

- 九游首页首屏有开屏广告，`today_launches.py` 会点「跳过」；若点不掉，等 3 秒再 dump。
- 首页「今天」日期标签必须点中，否则读到的可能是别的日期场次。
- `scripts/jiuyou_list_scan.py` 是旧脚本，导航到「新游首发」子页会跑偏，**不要用**；用 `today_launches.py`。
- 安装大包（>1.5 GB）可能超过 15 分钟，`--timeout-min` 可上调，但整轮预算 180 分钟要留够跑测时间。
