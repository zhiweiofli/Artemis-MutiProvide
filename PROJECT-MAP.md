# PROJECT-MAP.md — Artemis 技术架构与项目导航地图

> **目标导向**：全面剖析 ARTEMIS 项目的技术体系、分层结构、运行原理与核心能力，梳理与 Google 供应商的现有耦合点，设计模型供应商拓展（以 DeepSeek 为核心候选）与 Google 解耦的技术路线，并建立 AWB 能力期望与导航契约。

---

## 1. 项目技术栈与核心模块索引

### 1.1 技术栈全貌

| 层次 | 核心技术 / 依赖 | 说明与作用 |
|---|---|---|
| **语言与运行时** | Python `>=3.12`, uv, Cython | 高性能异步并发，Cython 关键路径加速 |
| **智能体编排底座** | LangGraph `>=1.0.2`, LangChain `>=1.0.0` | 状态图管理、多智能体协同、检查点恢复 |
| **设备自动化驱动** | `adbutils`, `uiautomator2`, Accessibility Helper APK | Android 底层 ADB 通信、UI 层次结构提取、无障碍服务快速交互 |
| **屏幕录制与多模态感知** | `scrcpy`, OpenCV, Pillow, imageio-ffmpeg | 毫秒级低延迟屏幕流镜像、实时关键帧截取、动态录屏与视频时序分析 |
| **接口与 IDE 协议** | FastMCP (`mcp>=1.26.0`), FastAPI, Uvicorn, WebSockets | 遵循 Model Context Protocol，支持 Antigravity / Claude Code / Windsurf 无缝驱动真机 |
| **模型网关与调度** | `langchain-core`, `langchain-google-genai`, `langchain-openai`, `langchain-anthropic` | 多提供商动态路由、指数退避重试、Token 计量、思考流采集 |

### 1.2 目录与源码地图

```
artemis/
├── agents/                  # 智能体核心角色群
│   ├── flash/               # 【核心】Flash 响应式单智能体循环 (Observe-Think-Act, 3~5s/步)
│   ├── operator/            # 【核心】Pro 模式操作执行节点 (屏幕感知、元素匹配、动作下发)
│   ├── planner/             # 任务规划器 (目标拆解、里程碑管理、前置计划审查)
│   ├── checker/             # 质量验收器 (断言检查点验证、退出最终审查)
│   ├── validator/           # 执行前像素/XML安全网校验
│   ├── explorer/            # 深度元素探查器 (Flash/Pro/Ultra 三层视觉与感知检索)
│   ├── object_detector/     # 目标检测与空间坐标定位 (边界框解析)
│   ├── video_analyzer/      # 屏幕录屏视频流分析 (Gemini Files 原生与通用多模态双引擎)
│   ├── summarizer/          # 步骤与上下文压缩摘要器 (Transcript Ledger)
│   └── log_analyzer/        # Logcat 崩溃与错误日志分析器
├── config/                  # 运行时配置模型
│   ├── constants.py         # 环境变量与提供商枚举 (LLMProvider, AgentNode)
│   ├── settings.py          # Pydantic 强类型配置 (API Keys, ADB, 路径)
│   ├── llm.py               # 节点级主备模型映射模型 (LLMConfig, LLMWithFallback)
│   └── paths.py             # 规范路径与工作区解析
├── drivers/                 # Android 物理设备与模拟器驱动层
│   ├── adb/                 # ADB 会话管理、Socket 流、设备探测
│   └── uiautomator/         # UI 树抓取、无障碍助手 (Accessibility Helper) 桥接
├── graph/                   # Pro 模式 LangGraph 状态图定义
│   ├── graph.py             # 核心工作流图构建 (Planner -> Operator -> Validator -> Checker)
│   ├── state.py             # 状态总线 (任务状态、历史轨迹、检查点、反馈槽)
│   └── checkpoints.py       # 异步检查点队列、最终验收判定
├── llm/                     # 模型接入与路由基础设施
│   ├── router.py            # ModelRouter & ModelFactory (多厂商模型实例化与缓存)
│   ├── reliability.py       # 熔断器 (CircuitBreaker)、重试策略、异常分类
│   ├── structured.py        # 结构化输出提取与 JSON 容错解析
│   └── google/              # Google 专用适配器 (思考预算、Token 计量)
├── mcp/                     # MCP 协议服务端实现 (对外向 AI IDE 暴露移动控制工具)
├── memory/                  # 上下文管理与历史压缩策略 (Transcript Ledger, 3 级清洗)
├── services/                # 共享服务层 (llm.py 统一模型调度网关, token_meter.py)
└── tools/                   # 动作执行与辅助工具集 (点击、滑动、输入、按键、ADB Shell)
config/
└── artemis.jsonc            # 全局默认模型配置、节点级重载与执行预设 (Presets)
```

---

## 2. 核心架构与运行原理剖析

ARTEMIS 采用创新的**双引擎架构 (Dual-Engine Architecture)**，兼顾速度与复杂任务的自愈韧性：

```
                +---------------------------------------------------------+
                |                    Natural Language Request             |
                +---------------------------------------------------------+
                                             |
                   +-------------------------+-------------------------+
                   |                                                   |
       [ Flash Profile (快速响应式) ]                       [ Pro Profile (深度图谱闭环) ]
                   |                                                   |
     +---------------------------+                     +-------------------------------+
     |  Single-Agent React Loop  |                     |  LangGraph Multi-Agent Graph  |
     |                           |                     |                               |
     |   Observe (Screenshot+XML)|                     |   1. Planner (目标拆解与计划)   |
     |             ↓             |                     |               ↓               |
     |     Think (Fast VLM)      |                     |   2. Operator (动作构想)       |
     |             ↓             |                     |               ↓               |
     |     Act (Sync Click/Swipe)|                     |   3. Validator (执行前安全网)  |
     |             ↓             |                     |               ↓               |
     |   Async Background Memory |                     |   4. Execution & Incidents    |
     |   (Visual Step Summary)   |                     |               ↓               |
     +---------------------------+                     |   5. Checker (检查点与最终验收)|
                                                       +-------------------------------+
                                             |
                         +-----------------------------------+
                         |    Android Automation Driver      |
                         | (Accessibility Helper / ADB Shell)|
                         +-----------------------------------+
```

### 2.1 核心闭环能力

1. **混合多模态定位机制 (Hybrid Multimodal Targeting)**
   - 优先读取 Android Accessibility Helper 导出的结构化 UI 树 (`minimal_list`)，提取元素索引 `[n]` 与属性。
   - 当遇到 Flutter、React Native、Canvas 自绘组件或游戏界面（无结构化节点）时，无缝回退到基于空间坐标定位与视觉检测（Object Detector / Explorer）。
2. **异步上下文压缩 (Transcript Ledger & Step Summarization)**
   - 不依赖粗暴截断上下文或简单硬设步数上限。
   - 采用分层清洗策略：深度 1 清理旧屏幕的庞大 XML 树；深度 K 将高分辨率历史截图原地压缩为高信息密度的文字视觉摘要；多轮操作自动折叠为历史 Era，确保 Token 占用稳定在可控区间。
3. **IDE MCP 原生集成**
   - 自身作为 MCP Server，向 Antigravity、Claude Code 等 IDE 暴露 `mobile_run_task`、`mobile_get_device_state`、`mobile_inspect_trace` 等标准工具，将手机变成开发者的交互式设备。

---

## 3. Google / Gemini 依赖现状与解耦分析

### 3.1 现有耦合点全景盘点

通过对全仓库代码的只读审计，发现当前系统对 Google 体系的依赖分为两个层次：

| 模块 / 路径 | 依赖内容 | 耦合程度 | 现有解耦可行性分析 |
|---|---|---|---|
| **默认配置 (`config/artemis.jsonc`)** | `default.provider = "google"`, `model = "gemini-3.8-flash"` | 易解耦 (配置层) | 修改配置默认值，替换为中立或指定厂商模型即可生效。 |
| **模型路由 (`artemis/llm/router.py`)** | `ModelProvider` 枚举未收录 `deepseek`；`ModelFactory` 仅支持标准 google/openai/anthropic/openrouter | 易解耦 (代码层) | 新增 `deepseek` 原生端点支持（基于 OpenAI 兼容协议），增加 `DEEPSEEK_API_KEY` 与默认 Base URL。 |
| **运行时配置 (`artemis/config/settings.py` & `constants.py`)** | `Settings` 类无 `DEEPSEEK_API_KEY`，`third_party/mobile_use/config/llm.py` 会做 provider 校验拦截 | 易解耦 (代码层) | 扩充配置项与白名单校验，允许通过 `.env` 直接注入 DeepSeek 凭据。 |
| **目标检测空间坐标 (`object_detector`)** | `gemini-robotics-er-2-preview` 专门用于连续空间子像素级 `[x, y]` 与 Bounding Box 预测 | 中等解耦 (能力层) | 普通 LLM 缺乏具身智能微调，但手机端 90% 以上场景有 UI 树的 `bounds` 坐标；无 UI 树时可用开源视觉定位模型（如 Qwen2.5-VL / Grounding DINO）或 OCR 坐标替代。 |
| **长视频录屏分析 (`video_analyzer`)** | `gemini_files.py` 原生调用 Google GenAI Files API 上传全视频流 | 已存在双引擎 (无需推倒) | 系统内部已有 `universal_engine.py` 与 `universal_tools.py`，支持基于 OpenCV 动态抽取关键帧 + 通用多模态工具调用的通用引擎。 |
| **搜索增强 (`enable_grounding: true`)** | `log_analyzer` 与 `diagnoser_expert` 开启了 Google Search Grounding | 易解耦 (功能层) | 纯本地测试可关闭 grounding，或通过 Tavily / Firecrawl / DuckDuckGo 等外部搜索工具替换。 |

### 3.2 候选供应商 DeepSeek 评估与适配矩阵

> [!IMPORTANT]
> **关键事实更新**：
> 1. 用户候选版本为具备**原生多模态推理能力**的 **DeepSeek Flash v4 (1017 版本)**。该版本直接支持多模态输入（包括屏幕截图 `image_url`）。
> 2. 在当前系统实现中，**Gemini 主模型从始至终均直接接收截图**进行视觉闭环；因此，具备多模态能力的 `deepseek flash v4 1017` 可作为**全模态对等替换（Drop-in Replacement）**，直接接管包括 Operator 在内的所有节点。
> 3. （兼容说明：若后续接入纯文本版本如 DeepSeek-V3/R1 官方 API，才需要通过端点能力校验，在有 UI 树时走文本化解析或混合多模型编排）。

| Artemis 智能体节点 | 节点核心特征 | DeepSeek Flash v4 (1017 多模态) 适配策略 | 推荐配置与回退保障 |
|---|---|---|---|
| **Operator (操作执行器)** | 需同时观察实时截图与 UI 树并生成交互动作 | **直接原生适配**：直接接收截图 (`image_url`) 与无障碍元素树 | 主: `deepseek/deepseek-flash-v4-1017`<br>备: `google/gemini-3.8-flash` / `openai/gpt-4o` |
| **Planner (规划器)** | 屏幕状态理解、多步骤任务拆解与子目标规划 | **完美适配** (多模态推理 + 深度思考能力) | 主: `deepseek/deepseek-flash-v4-1017`<br>备: `deepseek-reasoner` / `gemini-3.8-flash` |
| **Log Analyzer & Diagnoser** | 结合报错截图与 Logcat 日志排查诊断堆栈 | **完美适配** (同时具备视觉看图定位与代码级排障) | 主: `deepseek/deepseek-flash-v4-1017`<br>备: `deepseek-chat` |
| **Summarizer & Outputter** | 轨迹总结、Token 账单结算、格式化报告 | **完美适配** | 主: `deepseek/deepseek-flash-v4-1017` |
| **Checker (质量验证器)** | 断言判定、视觉最终状态与规则双重比对 | **完美适配** (原生支持视觉图文对齐判定) | 主: `deepseek/deepseek-flash-v4-1017` |
| **Video Analyzer** | 录屏时序分析与动态关键帧理解 | **完美适配** (走 `universal_engine` 动态抽帧直接传图) | 主: `deepseek/deepseek-flash-v4-1017` |

---

## 4. 能力期望表 (Skill Desired State)

按 AWB 规范，在本项目统一维护项目所依托的原子 Skill 期望状态：

| Skill ID | 期望版本 | 准入状态 | 宿主位置 | 验证层级 | 用途与触发条件 |
|---|---|---|---|---|---|
| **`workbench-project`** | `v1.0.0` | `verified` | `.agents/skills/workbench-project` | 入口与 Doctor 可通过 | 项目契约检查、环境探测、基线快照与交接管理。 |
| **`matt-tdd`** | `b0618bc436ad` | `verified` | `.agents/skills/matt-tdd` | 文件已就绪 | 测试驱动开发：新增 DeepSeek 端点时编写先验单元测试。 |
| **`matt-codebase-design`** | `b0618bc436ad` | `verified` | `.agents/skills/matt-codebase-design` | 文件已就绪 | 架构设计：设计 Multi-Provider 与异构视觉路由抽象层。 |
| **`matt-diagnosing-bugs`** | `b0618bc436ad` | `verified` | `.agents/skills/matt-diagnosing-bugs` | 文件已就绪 | 排障诊断：分析模型重试、4xx/5xx 或格式解析异常。 |
| **`matt-code-review`** | `b0618bc436ad` | `verified` | `.agents/skills/matt-code-review` | 文件已就绪 | 代码审查：在代码提交与阶段交接前进行边界合规审查。 |
| **`archify`** | `latest` | `verified` | `.agents/skills/archify` | 宿主已就绪 (`ready`) | 架构可视化：主动生成解耦前后数据流与状态机可视化图解。 |
| **`fabric-onboarding`** | `3.0.0-dev.4.local.a9589aceae64` | `trial (user-selected)` | `.agents/skills/fabric-onboarding` & `.claude/skills/fabric-onboarding` | `fabric doctor .` 在线 9 项全绿 | Harness Fabric 3.0 项目接入、便携运行时安装与 `init/doctor` 检查。 |
| **`fabric-main` / `fabric-manager` / `fabric-worker` / `fabric-reviewer`** | `3.0.0-dev.4` | `trial (user-selected)` | `.agents/skills/fabric-*` & `.claude/skills/fabric-*` | `fabric prepare --plan` 已冻结 (`run-rIQ5fl`) | Fabric 3.0 分层多角色执行控制（Claude Code 任 Manager，AGY 任 Worker，Codex 任 Reviewer）。 |

---

## 5. 项目导航与常用验证命令

- **契约健康度检查 (Doctor)**:
  ```bash
  node .agents/skills/workbench-project/scripts/check.mjs doctor .
  ```
- **环境与推荐工具感应 (Env)**:
  ```bash
  node .agents/skills/workbench-project/scripts/check.mjs env .
  ```
- **模型服务与网关单元测试**:
  ```bash
  uv run pytest tests/unit/test_llm_gateway.py tests/unit/test_llm_reliability.py
  ```
- **结构化输出与容错测试**:
  ```bash
  uv run pytest tests/unit/test_llm_structured.py
  ```
- **启动 Artemis 本地 CLI 任务 (验证端到端)**:
  ```bash
  uv run artemis run "查看电量" --profile flash
  ```
