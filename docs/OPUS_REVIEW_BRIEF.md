# ARTEMIS 解耦平替方案独立审查任务书 (Independent Review Brief for Opus 5.5)

## 1. 任务背景与目标
你作为由 Antigravity 移交的 **独立架构审查 Agent (基于 Claude Opus 5.5)**，正在接管并审查 ARTEMIS 移动自动化框架的“Google 解耦与多模型接入”技术方案。

工作区路径：`/Users/zw-mini/orca/artemis`

## 2. 需重点核查的输入材料
请优先精读以下核心规范与实施方案：
1. `docs/MODEL_SELECTION.md`（模型选型矩阵：DeepSeek Flash v4 1017 多模态主脑 + Qwen 27B 视觉空间定位兜底）
2. `docs/ARCHITECTURE_DECISIONS.md`（ADR-001 ~ ADR-004：基线保全、双通道独立配置、冷启动切换、6 维自动化对比体系）
3. `docs/TECHNICAL_SPEC_DEEPSEEK_QWEN.md`（技术规格书：代码扩展点、ModelFactory 拓扑、坐标自适应管道）
4. `AGENTS.md`（项目宪法、P-001~P-008 分级工程原则、四大工具策略与 AWB 验证门禁）
5. `PROJECT-MAP.md` 与 `HANDOFF.md`（项目地图与阶段交接事实）

## 3. 核心审查与评估要点 (Key Review Questions)

### Q1: 多模型组队分工评估
* **提议分工**：
  - **开发角色**：由 **Gemini 3.8 Flash** 独立负责代码实现（扩展 `settings.py`、`router.py`，配置模板编写，最小实现落地）。
  - **测试与审查角色**：由 **Claude Sonnet 5.5** 独立负责先验测试编写（TDD 单元测试）、边界用例补充及交付前 Code Review。
* **请评估**：
  - 此组队与模型搭配是否合理、高效？
  - 是否存在认知盲区或分工脱节风险？

### Q2: 方案审查与盲点补充
* 针对当前方案中拟定的：
  1. `ModelFactory` 双通道独立类 OpenAI 协议驱动；
  2. `ObjectDetector` 对 Qwen 27B Bounding Box 转 Center Point 坐标自适应；
  3. `scripts/run_benchmark_comparison.py` 六维自动化基线比对框架。
* 方案是否存在未考虑到的工程隐患（如多模态 Base64 传输性能、RateLimit 降级、无障碍树缺失时的回退时机、测试断言脆弱性）？

### Q3: 提高自主性与降低 Human in the Loop (HitL)
* 为实现 Agent 极高自主闭环交付，降低人类介入成本，在后续实施阶段需要进一步补充或细化哪些机制？
  - 例如：Mock 自动化自测模式、环境健康度先验探测（Toolchain Probe）、自动错误重试与自愈脚本、量化差分报告自动渲染等。

## 4. 交付要求
请完成全面审查，并在终端或以 `docs/OPUS_INDEPENDENT_REVIEW.md` 形式输出清晰、具体的审查结论与优化建议。
