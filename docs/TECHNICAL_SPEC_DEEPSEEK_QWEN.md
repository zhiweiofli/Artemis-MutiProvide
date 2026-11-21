# ARTEMIS 解耦平替技术规格书 (Technical Specification: DeepSeek + 阿里云百炼 Qwen-VL)

> **版本**：1.1.0（根据 Opus 独立架构审查与用户 5 项决策全面修订）  
> **状态**：架构已冻结，可进入先验测试编写 (Frozen for TDD Red Phase)  
> **关联决策**：[`docs/ARCHITECTURE_DECISIONS.md`](file:///Users/zw-mini/orca/artemis/docs/ARCHITECTURE_DECISIONS.md) (ADR-001 ~ ADR-007)  

---

## 1. 系统分层、调用拓扑与授权修改范围

### 1.1 双预设冷启动与双阶段 Fallback 拓扑

```
[ CLI --preset / 环境变量 ARTEMIS_PRESET / config/artemis.jsonc: active_preset ]
                                      │
                                      ▼
        [ 配置解析与预设展开层: artemis.config.llm.resolve_preset_config ]
        (保留顶层 presets 供 Admin Console 使用；新增 presets_v2 承载多模型拓扑)
                                      │
       ┌──────────────────────────────┼──────────────────────────────┐
       ▼                              ▼                              ▼
[ gemini-baseline ]          [ ds-qwen-hybrid (阶段一) ]     [ ds-qwen-pure (阶段二) ]
- 全节点 Google Gemini        - 主: DeepSeek + 百炼 Qwen      - 主: DeepSeek + 百炼 Qwen
- 金标对照基线                - 备: 跨厂商回退 Google Gemini   - 备: 纯非 Google 多模态端点
                                      │                              │
                    ┌─────────────────┴──────────────────────────────┘
                    │
       ┌────────────┴────────────────────────────────────────────────┐
       ▼                                                             ▼
[ 主干多模态通道 (ModelProvider.DEEPSEEK) ]             [ 视觉空间定位通道 (ModelProvider.QWEN) ]
- DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL                - QWEN_API_KEY (或 DASHSCOPE_API_KEY)
- 默认: https://api.deepseek.com/v1                   - QWEN_BASE_URL: https://dashscope.aliyuncs.com/compatible-mode/v1
- Model: deepseek-flash-v4-1017                       - Model: qwen2.5-vl-72b-instruct / qwen3.8-27b-object-detection
- 强制注入: stream_usage=True, max_retries=0           - 强制注入: stream_usage=True, max_retries=0
- 结构化协议: method="function_calling"                - 坐标契约: coord_format="bbox_xyxy_px" | "bbox_xyxy_1000"
       │                                                             │
       ▼                                                             ▼
[ 业务与后台记忆节点全覆盖 ]                            [ 视觉定位与探索兜底 ]
- Operator / Planner / Checker / Diagnoser            - Object Detector (自适应像素/千分位归一化 + with_fallback)
- Outputter / Hopper / Lightweight Judges             - Explorer (Flash 模式直接委托 Object Detector)
- Video Analyzer (自动切换 Universal OpenCV 引擎)
- Step Summarizer / Memory Chunking (拔除硬编码 Google)
```

### 1.2 授权修改文件清单（用户已确认拓展范围）

| 层次 | 允许修改 / 新增的文件路径 | 职责说明 |
|---|---|---|
| **配置与常量层** | `artemis/config/constants.py`<br>`artemis/config/settings.py`<br>`artemis/config/llm.py`<br>`third_party/mobile_use/config/llm.py`<br>`config/artemis.jsonc` | 扩充 `LLMProvider` 与 `CoordFormat`；新增 DeepSeek/百炼 Qwen 环境变量；实现 `presets_v2` 纯函数加载器与模态校验；修复 `lightweight_judge_default` |
| **网关与路由层** | `artemis/llm/router.py`<br>`artemis/llm/reliability.py`<br>`artemis/llm/google/usage.py`<br>`artemis/services/llm.py` | 表驱动 OpenAI 兼容工厂（注入 `stream_usage=True, max_retries=0`）；`with_structured_output` 协议协商；HTTP 402 降级分类；`prompt_cache_hit_tokens` 计量；新增 `get_llm_for_model` |
| **记忆与后门清理** | `artemis/memory/chunking.py`<br>`artemis/agents/flash/summarizer.py`<br>`artemis/agents/flash/runner.py`<br>`artemis/agents/explorer/explorer.py` | 拔除 5 处硬编码 `get_google_llm` 后门；修复 `summarizer.py` 中 `is_utils=True` 的既有 Bug |
| **视觉检测层** | `artemis/agents/object_detector/object_detector.py`<br>`artemis/agents/object_detector/object_detector.json` | 声明式 `coord_format` 坐标解析与像素归一化；移除无条件 `[y,x]` 翻转 Bug；单次图像解码；接入 `with_fallback` 与端点级超时 |
| **探针、门禁与测试** | `scripts/probe_capabilities.py`<br>`scripts/gate.py`<br>`scripts/run_benchmark_comparison.py`<br>`tests/unit/test_deepseek_qwen_providers.py`<br>`tests/unit/test_object_detector_coords.py`<br>`tests/unit/test_preset_switching.py` | 端点能力先验探针、L1–L4 机器验收门禁、六维基准对比脚本及 TDD 先验单元测试 |

---

## 2. 配置、凭据与 `presets_v2` 加载器规范（解决阻断项 B1、B2）

### 2.1 常量与类型扩充（[`artemis/config/constants.py`](file:///Users/zw-mini/orca/artemis/artemis/config/constants.py)）

```python
LLMProvider = Literal[
    "openai",
    "google",
    "openrouter",
    "xai",
    "vertexai",
    "anthropic",
    "ollama",
    "vllm",
    "deepseek",  # 新增
    "qwen",      # 新增（阿里云百炼 DashScope 兼容模式）
    "custom",
]

CoordFormat = Literal[
    "point_yx_1000",  # Gemini ER 默认: {"point": [y, x]} in 0..1000
    "point_xy_1000",  # 归一化点: {"point": [x, y]} in 0..1000
    "bbox_yxyx_1000", # Gemini Box: {"box_2d": [ymin, xmin, ymax, xmax]} in 0..1000
    "bbox_xyxy_1000", # Qwen 归一化框: {"bbox_2d": [xmin, ymin, xmax, ymax]} in 0..1000
    "bbox_xyxy_px",   # 百炼 Qwen2.5-VL 原生像素框: {"bbox_2d": [xmin, ymin, xmax, ymax]} in pixels
]

StructuredOutputMethod = Literal["json_schema", "function_calling", "json_mode"]

# 要求主备端点 is_multimodal 必须为 True 的节点集合（强制执行 P-003）
MULTIMODAL_REQUIRED_NODES: frozenset[str] = frozenset({
    "operator",
    "planner",
    "checker",
    "diagnoser",
    "diagnoser_expert",
    "explorer",
    "summarizer",
    "operator_summarizer",
    "video_analyzer",
    "object_detector",
    "validator_pixel_safety_net",
})
```

### 2.2 环境变量与凭据配置（[`artemis/config/settings.py`](file:///Users/zw-mini/orca/artemis/artemis/config/settings.py)）

在 `Settings` 模型中新增 DeepSeek、阿里云百炼 Qwen 及冷启动预设环境变量：

```python
ENV_DEEPSEEK_API_KEY = "DEEPSEEK_API_KEY"
ENV_DEEPSEEK_BASE_URL = "DEEPSEEK_BASE_URL"
ENV_QWEN_API_KEY = "QWEN_API_KEY"
ENV_QWEN_BASE_URL = "QWEN_BASE_URL"
ENV_ARTEMIS_PRESET = "ARTEMIS_PRESET"

class Settings(BaseSettings):
    # ... 保持现有字段不变 ...
    DEEPSEEK_API_KEY: SecretStr | None = None
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"

    QWEN_API_KEY: SecretStr | None = None
    QWEN_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    ARTEMIS_PRESET: str | None = None
```

### 2.3 LLM 节点模型扩充与凭据校验（[`third_party/mobile_use/config/llm.py`](file:///Users/zw-mini/orca/artemis/third_party/mobile_use/config/llm.py)）

1. 在 `LLM` BaseModel 中新增可选能力声明字段：
   ```python
   is_multimodal: bool = True
   coord_format: CoordFormat | None = None
   structured_output_method: StructuredOutputMethod | None = None
   api_base: str | None = None
   ```
2. 在 `LLM.validate_provider(self, name: str)` 中补充 `deepseek` 与 `qwen` 校验（百炼同时兼容 `QWEN_API_KEY` 与阿里云标准环境变量 `DASHSCOPE_API_KEY`）：
   ```python
   elif self.provider == "deepseek":
       if not (settings.DEEPSEEK_API_KEY or os.environ.get("DEEPSEEK_API_KEY")):
           raise Exception(f"{name} requires DEEPSEEK_API_KEY in .env")
   elif self.provider == "qwen":
       if not (
           settings.QWEN_API_KEY
           or os.environ.get("QWEN_API_KEY")
           or os.environ.get("DASHSCOPE_API_KEY")
       ):
           raise Exception(f"{name} requires QWEN_API_KEY (or DASHSCOPE_API_KEY) in .env")
   ```
3. **P-003 模态匹配校验**：在 `validate_provider` 中，当 `name` 属于多模态节点（参见 `MULTIMODAL_REQUIRED_NODES`）且 `self.is_multimodal is False` 时，立即抛出 `ValueError(f"{name} requires a multimodal endpoint (is_multimodal=True), got {self.provider}/{self.model}")`。在 `LLMWithFallback.validate_provider` 中同时校验 `self.fallback.validate_provider(f"{name}.fallback")`，从而在启动阶段拦截“将纯文本模型配为多模态节点 fallback”的配置错误（解决 B3）。

### 2.4 向后兼容的 `presets_v2` 配置结构（[`config/artemis.jsonc`](file:///Users/zw-mini/orca/artemis/config/artemis.jsonc)）

保留顶层 `presets` 原有扁平格式（供 Admin Console 读取），新增 `active_preset` 与 `presets_v2`：

```jsonc
{
  // 激活的多模型架构预设；优先级：CLI --preset > 环境变量 ARTEMIS_PRESET > active_preset
  "active_preset": "gemini-baseline",

  // [保留兼容] 扁平预设：仅供 apps/admin_console 前端展示使用，请勿改为嵌套结构
  "presets": {
    "gemini-flagship": { /* 原样保留 */ }
  },

  // [新增] 完整多节点拓扑预设 (ADR-003)
  "presets_v2": {
    "gemini-baseline": {
      "default": {
        "provider": "google",
        "model": "gemini-3.8-flash",
        "thinking_level": "medium",
        "is_multimodal": true,
        "fallback": {
          "provider": "google",
          "model": "gemini-3.7-flash",
          "thinking_level": "medium",
          "is_multimodal": true
        }
      },
      "nodes": {
        "object_detector": {
          "provider": "google",
          "model": "gemini-robotics-er-2-preview",
          "coord_format": "point_yx_1000",
          "timeout": 10.0,
          "fallback": {
            "provider": "google",
            "model": "gemini-robotics-er-2-preview",
            "coord_format": "point_yx_1000"
          }
        },
        "hopper": {
          "provider": "google",
          "model": "gemini-3.5-flash-lite",
          "fallback": { "provider": "google", "model": "gemini-3.1-flash-lite" }
        }
      }
    },

    // 阶段一：DeepSeek + 阿里云百炼 Qwen 主力，跨厂商 Fallback 至 Gemini（高可用容灾）
    "ds-qwen-hybrid": {
      "default": {
        "provider": "deepseek",
        "model": "deepseek-flash-v4-1017",
        "is_multimodal": true,
        "structured_output_method": "function_calling",
        "fallback": {
          "provider": "google",
          "model": "gemini-3.8-flash",
          "thinking_level": "medium",
          "is_multimodal": true
        }
      },
      "nodes": {
        "object_detector": {
          "provider": "qwen",
          "model": "qwen2.5-vl-72b-instruct",
          "coord_format": "bbox_xyxy_px",
          "timeout": 25.0,
          "fallback": {
            "provider": "google",
            "model": "gemini-robotics-er-2-preview",
            "coord_format": "point_yx_1000"
          }
        },
        "hopper": {
          "provider": "deepseek",
          "model": "deepseek-flash-v4-1017",
          "fallback": {
            "provider": "google",
            "model": "gemini-3.5-flash-lite"
          }
        }
      }
    },

    // 阶段二：100% 零 Google 独立验收预设（无需 GOOGLE_API_KEY）
    "ds-qwen-pure": {
      "default": {
        "provider": "deepseek",
        "model": "deepseek-flash-v4-1017",
        "is_multimodal": true,
        "structured_output_method": "function_calling",
        "fallback": {
          "provider": "qwen",
          "model": "qwen-vl-max-latest",
          "is_multimodal": true,
          "structured_output_method": "function_calling"
        }
      },
      "nodes": {
        "object_detector": {
          "provider": "qwen",
          "model": "qwen2.5-vl-72b-instruct",
          "coord_format": "bbox_xyxy_px",
          "timeout": 25.0,
          "fallback": {
            "provider": "qwen",
            "model": "qwen-vl-max-latest",
            "coord_format": "bbox_xyxy_px"
          }
        },
        "hopper": {
          "provider": "deepseek",
          "model": "deepseek-flash-v4-1017",
          "fallback": {
            "provider": "qwen",
            "model": "qwen-vl-plus"
          }
        }
      }
    }
  }
}
```

### 2.5 预设解析与防泄漏展开逻辑（[`artemis/config/llm.py`](file:///Users/zw-mini/orca/artemis/artemis/config/llm.py)）

在 `artemis/config/llm.py` 中新增纯函数 `resolve_preset_config` 并改造 `_expand_default_into_nodes`：

1. **预设选择优先级**：
   ```python
   def get_active_preset_name(config_dict: dict, explicit_preset: str | None = None) -> str | None:
       return (
           explicit_preset
           or os.environ.get("ARTEMIS_PRESET")
           or (settings.ARTEMIS_PRESET if getattr(settings, "ARTEMIS_PRESET", None) else None)
           or config_dict.get("active_preset")
       )
   ```
2. **Fail-Fast 校验与节点合并规则**：
   - 若解析出的 `preset_name` 非空：在 `config_dict.get("presets_v2", {})` 中查找；若不存在，**立即抛出 `ValueError(f"Unknown preset {preset_name!r}. Available presets_v2: {sorted(presets_v2)}")`**。
   - **合并规则（阻断 Provider 继承泄漏）**：
     - 以 `preset["default"]` 替换顶层 `default`；
     - 顶层 `nodes` 中**仅保留与模型身份无关的行为参数**（如 `planner.thinking_level`、`operator.include_thoughts`、`log_analyzer.enable_grounding`、`checker.include_thoughts`）；
     - 顶层 `nodes` 中任何绑定了特定厂商模型的条目（如 `hopper.model = "gemini-3.5-flash-lite"`、`object_detector.model = "gemini-robotics-er-2-preview"`）**不得污染非 `gemini-baseline` 预设**——`preset["nodes"]` 对节点模型定义具有完全覆盖权。
     - 当某个节点覆盖了 `model` 时，若该 `model` 与 `default.provider` 明显跨厂商冲突（例如 `provider != "google"` 但 `model.startswith("gemini")`），加载器直接抛出 `ValueError` 拒绝启动。
3. **动态 `lightweight_judge_default`**：
   - `LLMConfig.get_agent` 在获取 `validator_pixel_safety_net` 或 `planner_validation` 为 `None` 时，若 `self.planner.provider == "google"`，返回 `lightweight_judge_default()`（`gemini-3.5-flash-lite`）；否则**直接返回 `self.operator.model_copy(update={"temperature": 0.0})`（或 `self.utils.hopper`）**，彻底消除非 Google 预设下的 Google 裁判后门。

---

## 3. 硬编码 Google 后门拔除与后台记忆路由统一（解决阻断项 B2）

### 3.1 统一辅助工厂 `get_llm_for_model`（[`artemis/services/llm.py`](file:///Users/zw-mini/orca/artemis/artemis/services/llm.py)）

为后台异步摘要（`VisualStepSummarizer`）与分段压缩（`ChunkSummarizer`）提供中立解析入口：

```python
def get_llm_for_model(
    model_spec: str | None = None,
    *,
    ctx: ArtemisContext | None = None,
    fallback_node: str = "summarizer",
    temperature: float = 0.0,
) -> BaseChatModel:
    """Resolve an LLM for background services without hardcoding Google.

    1. If ctx has an initialized llm_config whose fallback_node provider is NOT google,
       and model_spec is either None or a default 'gemini-*' string from agent config,
       delegate to get_llm(ctx, name=fallback_node, is_utils=False, temperature=temperature).
    2. If model_spec uses 'provider/model' syntax (e.g. 'deepseek/deepseek-flash-v4-1017'),
       parse provider and model_name and route via ModelFactory.get_model + RobustChatModelWrapper.
    3. Otherwise, infer provider from ctx.llm_config (if available) or fallback to Google.
    """
```

### 3.2 四处调用点改造细则

1. **[`artemis/agents/flash/summarizer.py#L162-L174`](file:///Users/zw-mini/orca/artemis/artemis/agents/flash/summarizer.py#L162-L174)**：
   - 修复既有 Bug：将 `get_llm(ctx, name="summarizer", is_utils=True)` 修正为 `is_utils=False`（`summarizer` 属于 `AgentNode` 而非 `LLMUtilsNode`）。
   - 将直接调用 `get_google_llm(model_name=target_model, temperature=0.0)` 替换为 `get_llm_for_model(model_name, ctx=ctx, fallback_node="summarizer", temperature=0.0)`。
2. **[`artemis/memory/chunking.py#L324-L338`](file:///Users/zw-mini/orca/artemis/artemis/memory/chunking.py#L324-L338)**：
   - `_get_llm` 与 `_get_fallback_llm` 改为调用 `get_llm_for_model(self._model_name, ctx=self._ctx, fallback_node="summarizer", temperature=0.0)`。
3. **[`artemis/agents/flash/runner.py#L281-L287`](file:///Users/zw-mini/orca/artemis/artemis/agents/flash/runner.py#L281-L287)**：
   - `_init_llm` 中当 `get_llm(self.ctx, name="operator")` 失败时，尝试 `get_llm(self.ctx, name="operator", use_fallback=True)`，不再硬编码退回 `get_google_llm(model_name="gemini-2.5-flash")`。
4. **[`artemis/agents/explorer/explorer.py#L118-L124`](file:///Users/zw-mini/orca/artemis/artemis/agents/explorer/explorer.py#L118-L124)**：
   - `_detect_native_engine()` 仅在 `llm_cfg.provider == "google"` 且 `is_gemini_model(self.model_name)` 时启用 Google GenAI 原生 SDK，其他 Provider 一律走 `universal_runner`。

---

## 4. 中立路由工厂、流式计量与结构化协议协商（解决阻断项 B3、B4、B5）

### 4.1 `ModelProvider` 与 `ModelEndpoint` 扩充（[`artemis/llm/router.py`](file:///Users/zw-mini/orca/artemis/artemis/llm/router.py)）

```python
class ModelProvider(StrEnum):
    GOOGLE = "google"
    GEMINI = "google"
    VERTEX_AI = "vertexai"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OPENROUTER = "openrouter"
    XAI = "xai"
    DEEPSEEK = "deepseek"   # 新增
    QWEN = "qwen"           # 新增（含别名 dashscope, bailian）
    OLLAMA = "ollama"
    VLLM = "vllm"
    CUSTOM = "custom"
```

在 `ModelProvider.from_string` 的 `mapping` 中增加：
```python
"deepseek": cls.DEEPSEEK,
"qwen": cls.QWEN,
"dashscope": cls.QWEN,
"bailian": cls.QWEN,
```

在 `ModelEndpoint` 中增加：
```python
coord_format: str | None = Field(
    default=None, description="Coordinate format for object detection endpoints"
)
structured_output_method: str | None = Field(
    default=None, description="Preferred with_structured_output method ('json_schema' | 'function_calling' | 'json_mode')"
)
```
并将 `coord_format` 与 `structured_output_method` 纳入 `ModelEndpoint.cache_key()` 元组。

### 4.2 表驱动 OpenAI 兼容实例化（强制 `stream_usage=True` 与 `max_retries=0`）

在 `ModelFactory.create_model` 中，用统一辅助方法消除 `DEEPSEEK`、`QWEN`、`OPENROUTER`、`XAI` 的重复代码：

```python
_OPENAI_COMPAT_PROVIDERS: dict[ModelProvider, tuple[str, str, str, tuple[str, ...]]] = {
    # provider: (settings_key_attr, settings_url_attr, default_base_url, env_key_fallbacks)
    ModelProvider.DEEPSEEK: (
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "https://api.deepseek.com/v1",
        ("DEEPSEEK_API_KEY",),
    ),
    ModelProvider.QWEN: (
        "QWEN_API_KEY",
        "QWEN_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ("QWEN_API_KEY", "DASHSCOPE_API_KEY"),
    ),
    ModelProvider.OPENROUTER: (
        "OPEN_ROUTER_API_KEY",
        "",
        "https://openrouter.ai/api/v1",
        ("OPEN_ROUTER_API_KEY",),
    ),
    ModelProvider.XAI: (
        "XAI_API_KEY",
        "",
        "https://api.x.ai/v1",
        ("XAI_API_KEY",),
    ),
}
```

实例化 `ChatOpenAI` 时强制注入以下关键参数（解决 B5）：
```python
kwargs: dict[str, Any] = {
    "model": endpoint.model_name,
    "temperature": endpoint.temperature,
    "max_tokens": endpoint.max_tokens,
    "api_key": api_key,
    "base_url": base_url,
    "timeout": endpoint.timeout_seconds,
    "stream_usage": True,  # 关键：自定义 base_url 下强制请求 stream_options.include_usage
    "max_retries": 0,      # 关键：禁用 openai SDK 内部隐式重试，统一交由 Artemis _run_with_recovery 管理
}
if endpoint.reasoning_effort:
    kwargs["reasoning_effort"] = endpoint.reasoning_effort
return ChatOpenAI(**{k: v for k, v in kwargs.items() if v is not None})
```

### 4.3 结构化输出协议自适应（[`artemis/services/llm.py`](file:///Users/zw-mini/orca/artemis/artemis/services/llm.py)，解决 B4）

在 `RobustChatModelWrapper.with_structured_output` 中：
```python
def with_structured_output(self, *args, **kwargs):
    if hasattr(self.base_model, "with_structured_output"):
        if "method" not in kwargs and self.endpoint is not None:
            if self.endpoint.structured_output_method:
                kwargs["method"] = self.endpoint.structured_output_method
            elif self.endpoint.provider in (ModelProvider.DEEPSEEK, ModelProvider.QWEN):
                # DeepSeek 与百炼兼容接口默认使用 function_calling，避免 json_schema 400 报错
                kwargs["method"] = "function_calling"
        return RobustChatModelWrapper(
            self.base_model.with_structured_output(*args, **kwargs),
            self.ctx,
            endpoint=self.endpoint,
        )
    raise AttributeError(f"{type(self.base_model)} does not support with_structured_output")
```

### 4.4 Token 缓存计量与 402 降级扩充

1. **[`artemis/llm/google/usage.py`](file:///Users/zw-mini/orca/artemis/artemis/llm/google/usage.py)**：
   - 在 `_CACHED_KEYS` 中加入 DeepSeek 专有字段 `"prompt_cache_hit_tokens"`；
   - 在 `normalize_usage` 中额外读取 `prompt_tokens_details` 下的 `"cached_tokens"`，确保 DeepSeek 与百炼的缓存命中 Token 被准确计入 `SessionTokenMeter`。
2. **[`artemis/llm/reliability.py`](file:///Users/zw-mini/orca/artemis/artemis/llm/reliability.py)**：
   - 在 `classify_failure` 中，将 `code == 402`（或错误消息包含 `"insufficient balance"` / `"insufficient_quota"` / `"arrearage"`）归类为 `Failure(FailureCategory.RATE_LIMIT, retryable=False, should_fallback=True)`，即：**不浪费时间原地重试，立即触发 `_ObservedFallback` 切换到备用厂商**。

---

## 5. Object Detector 声明式坐标契约与超时/Fallback 加固（解决阻断项 B6、B7）

### 5.1 声明式坐标归一化纯函数（[`artemis/agents/object_detector/object_detector.py`](file:///Users/zw-mini/orca/artemis/artemis/agents/object_detector/object_detector.py)）

新增纯函数 `normalize_detected_coordinate`，彻底取代原有的第 169–177 行无条件 `[y, x]` 翻转逻辑：

```python
def _clamp_1000(val: float) -> int:
    return max(0, min(1000, int(round(val))))


def normalize_detected_coordinate(
    item: dict,
    *,
    coord_format: str = "point_yx_1000",
    image_size: tuple[int, int] | None = None,
) -> list[int] | None:
    """Normalize raw model detection item into canonical [x, y] in 0..1000.

    Supported coord_format values:
      - 'point_yx_1000': {'point': [y, x]} in 0..1000 (Gemini ER default)
      - 'point_xy_1000': {'point': [x, y]} in 0..1000
      - 'bbox_yxyx_1000': {'box_2d': [ymin, xmin, ymax, xmax]} in 0..1000 (Gemini box)
      - 'bbox_xyxy_1000': {'bbox_2d' | 'box_2d': [xmin, ymin, xmax, ymax]} in 0..1000 (Qwen 0-1000)
      - 'bbox_xyxy_px':   {'bbox_2d' | 'box_2d': [xmin, ymin, xmax, ymax]} in pixel coords (Bailian Qwen2.5-VL)

    Returns [x_norm, y_norm] in [0, 1000], or None if malformed / degenerate.
    """
    if not isinstance(item, dict):
        return None

    # 1. Explicit 2D point
    pt = item.get("point") or item.get("point_2d")
    if isinstance(pt, (list, tuple)) and len(pt) == 2:
        try:
            a, b = float(pt[0]), float(pt[1])
        except (TypeError, ValueError):
            return None
        if coord_format == "point_yx_1000":
            raw_x, raw_y = b, a
        elif coord_format == "bbox_xyxy_px" and image_size and image_size[0] > 0 and image_size[1] > 0:
            raw_x = a / image_size[0] * 1000.0
            raw_y = b / image_size[1] * 1000.0
        else:
            raw_x, raw_y = a, b
        return [_clamp_1000(raw_x), _clamp_1000(raw_y)]

    # 2. 4-element Bounding Box
    box = item.get("bbox_2d") or item.get("box_2d") or item.get("bounding_box")
    if isinstance(box, (list, tuple)) and len(box) == 4:
        try:
            c0, c1, c2, c3 = float(box[0]), float(box[1]), float(box[2]), float(box[3])
        except (TypeError, ValueError):
            return None

        if coord_format == "bbox_yxyx_1000" or (
            coord_format == "point_yx_1000" and "box_2d" in item and "bbox_2d" not in item
        ):
            ymin, xmin, ymax, xmax = c0, c1, c2, c3
        else:
            xmin, ymin, xmax, ymax = c0, c1, c2, c3

        # Reject degenerate or inverted boxes
        if xmax <= xmin or ymax <= ymin:
            return None

        cx = (xmin + xmax) / 2.0
        cy = (ymin + ymax) / 2.0

        if coord_format == "bbox_xyxy_px":
            if not image_size or image_size[0] <= 0 or image_size[1] <= 0:
                return None
            cx = (cx / image_size[0]) * 1000.0
            cy = (cy / image_size[1]) * 1000.0

        return [_clamp_1000(cx), _clamp_1000(cy)]

    return None
```

### 5.2 按格式选择 Prompt 指令与单次图像预处理

1. **单次图像读取与编码**：在 `_run_object_detection` 入口只执行一次：
   ```python
   img_b64 = base64.b64encode(image_data).decode("utf-8")
   image_size = _extract_image_size(image_data)  # 使用 PIL.Image.open(io.BytesIO(image_data)).size
   ```
   避免每个 label 重复进行 Base64 编码与图像头解析。
2. **Prompt 按 `coord_format` 分派**（扩充 `object_detector.json`）：
   - 当 `coord_format == "point_yx_1000"`（Gemini ER）时，保持原有指令：`Each object must have a 'point' array [y, x] (normalized to 0-1000)`。
   - 当 `coord_format in ("bbox_xyxy_px", "bbox_xyxy_1000")`（百炼 Qwen-VL）时，使用 Qwen 原生 Grounding 指令：
     ```
     Locate "{labels_str}" in the image and return a JSON list of objects with "bbox_2d": [xmin, ymin, xmax, ymax] and "label": "{labels_str}". Return [] if not found.
     ```
3. **超时修复与 `with_fallback` 闭环（解决 B7）**：
   - 修复 `_run_object_detection` 中读取 `timeout` 的路径：`cfg = ctx.llm_config.get_utils("object_detector")`，优先读取 `cfg.timeout`（百炼 Qwen 设为 `25.0s`），其次读取 `OBJECT_DETECTOR_TIMEOUT` 环境变量。
   - `_detect_single_label` 通过 `with_fallback` 包装主模型（`get_llm(ctx, name="object_detector", is_utils=True)`）与备用模型（`get_llm(ctx, name="object_detector", is_utils=True, use_fallback=True)`），并在捕获终端异常时根据备用模型的 `endpoint.coord_format` 解析返回值。

---

## 6. 高自主闭环工具链（解决 Q3：降低 Human-in-the-Loop）

### 6.1 端点能力先验探针（`scripts/probe_capabilities.py`）

在接入真实 API Key 后，自动执行 5 项最小开销探测（总消耗 < 500 Tokens），将所有 `HYPOTHESIS` 转化为落盘的 `FACT`（`.artemis/capabilities.json`）：
1. **模型可达性探测**：请求 `/models` 或发一条 1-token ping，验证 `deepseek-flash-v4-1017` 与百炼 `qwen2.5-vl-72b-instruct` 模型 ID 有效。
2. **多模态探测**：发送一张内存生成的 `64x64` 纯红 PNG Base64，验证 `image_url` 不报 400 且能识别红色。
3. **结构化输出探测**：依次测试 `function_calling`、`json_mode`、`json_schema`，记录可用方法。
4. **流式 Usage 探测**：验证 `stream_usage=True` 下返回的 chunk 包含 `usage_metadata.input_tokens > 0`。
5. **合成图 Grounding 校准**：生成一张 `400x800` 白底画布并在已知位置 `(x=100..200, y=500..600)` 绘制黑色矩形，调用 `object_detector` 验证归一化后的中心点误差 $\le 25$（千分位），自动确认 `coord_format` 是 `bbox_xyxy_px` 还是 `bbox_xyxy_1000`！

### 6.2 机器裁决门禁与看板自动同步脚本（`scripts/gate.py`）

提供统一的 CLI 门禁 `uv run python scripts/gate.py --level L4 --phase P2-GREEN --json`，返回码 `0` 为唯一放行标准：
- **L1**：运行 `check.mjs doctor .`，断言 `"status": "healthy"`。
- **L2**：核对 `.agents/skills/` 下 6 个原子 Skill 目录存在。
- **L3**：检查 Python 环境、`langchain-openai` 版本，以及 `.agent/baseline.json` 中未授权文件未被篡改。
- **L4**：运行全套单元测试（现有 25 项 + 新增先验契约测试 `T-01`~`T-12`），全部通过才返回 `0`（注：在 `--phase P1-RED` 下，断言现有 25 项全部 `PASSED` 且新增 `T-01`~`T-12` 处于 Expected Fail 状态）。
- **自动看板与 HTML 重编译（零人工遗忘）**：
  - `gate.py` 在完成检查后，自动调用内部函数 `sync_task_board(phase, report)`：
    1. 根据实测结果原地更新 [`docs/TASK_BOARD.md`](file:///Users/zw-mini/orca/artemis/docs/TASK_BOARD.md) 中对应 Phase 的状态（`READY` → `DONE`）、`B1`~`B7` 状态及 L1~L5 验证表；
    2. 同步更新 `.archify/explainer-phase-task-board-20261109-141300/candidate.archify.md` 中 `#phase-status`、`#blocker-matrix` 与 `#action-checklist` 面板状态；
    3. 自动执行子进程：
       ```bash
       node .agents/skills/archify/bin/archify.mjs finalize explainer \
         .archify/explainer-phase-task-board-20261109-141300/candidate.archify.md \
         .archify/explainer-phase-task-board-20261109-141300/phase-task-board.html \
         --repo-root . --json
       ```
       确保每次门禁运行后，HTML 可视化看板 100% 反映最新真实状态。

### 6.3 统计严谨的六维基准对比脚本（`scripts/run_benchmark_comparison.py`）

支持 `--mode offline`（免真机 CI 模式：运行离线 Grounding 标注集 + 本地故障注入 Mock 集）与 `--mode e2e`（真机/模拟器配对跑批模式，$N \ge 5$ 次重复，内置 `--max-cost-usd` 预算熔断护栏），自动生成 Markdown 差分报告。

---

## 7. 五角色协作流水线与先验契约测试矩阵（解决 Q1）

### 7.1 角色边界与交接协议

| 阶段 | 角色与推荐模型 | 输入 | 产出物与权限边界 |
|---|---|---|---|
| **Phase 0** | **Spec Owner (Opus / Argon)** | 审查报告 + 用户决策 | 本 `Spec v1.1` + `ADR v1.1`；对后续 Test Dispute 拥有唯一裁决权 |
| **Phase 1 (Red)** | **Test Author (Claude Sonnet 5.5)** | `Spec v1.1` + 现有源码 | 仅允许写入 `tests/unit/test_*.py`；编写 `T-01`~`T-12` 先验测试并确认在未改业务代码前 Expected Fail |
| **Phase 2 (Green)** | **Implementer (Gemini 3.8 Flash)** | 冻结的先验测试 + `Spec v1.1` | 仅允许写入 §1.2 授权的业务文件与 `scripts/`；**严禁修改 `tests/` 下任何文件**；使 `gate.py --level L4` 返回 0 |
| **Phase 3 (Review)** | **Independent Reviewer (新会话 Sonnet/Opus)** | Git Diff + `Spec v1.1` | 运行 `matt-code-review` 双轴审查（Standards + Spec），输出审查报告 |
| **Phase 4 (Bench)** | **Bench Operator (脚本化执行)** | 通过审查的代码 | 运行 `probe_capabilities.py`、`gate.py` 与 `run_benchmark_comparison.py`，产出 L4/L5 验收证据 |

### 7.2 先验契约测试矩阵（Test Author 必写清单）

Test Author 必须在 `tests/unit/` 下实现以下 12 项确定性单元测试（全部使用 `monkeypatch` 隔离环境，每次测试自动清理 `ModelFactory._cache`）：

| 用例编号 | 测试文件 | 核心断言内容 | 对应阻断项 |
|---|---|---|---|
| **T-01** | `test_preset_switching.py` | 验证 `resolve_preset_config` 优先级：`explicit_preset > ARTEMIS_PRESET > active_preset`；传入未知预设名时立即抛出 `ValueError` | B1 |
| **T-02** | `test_preset_switching.py` | 验证顶层扁平 `presets` 保持原样可读（保障 Admin Console 兼容），同时 `presets_v2` 正确展开 `gemini-baseline`、`ds-qwen-hybrid`、`ds-qwen-pure` | B1 |
| **T-03** | `test_preset_switching.py` | **防 Provider 继承泄漏测试**：当 `default` 为 `deepseek` 且某节点仅写 `model: "gemini-3.5-flash-lite"` 未写 `provider` 时，加载器必须抛出 `ValueError` 拦截 | B2 |
| **T-04** | `test_preset_switching.py` | **阶段二零 Google 不变量测试**：清空 `GOOGLE_API_KEY`，设置 `ARTEMIS_PRESET=ds-qwen-pure`，遍历所有 `AgentNode`、`LLMUtilsNode`、`validator_pixel_safety_net`、`planner_validation` 及 `get_llm_for_model(None, ctx=ctx)`，断言解析出的 `endpoint.provider` 均不属于 `{google, vertexai}`，且 monkeypatch `get_google_llm` 抛异常时全程不触发 | B2 |
| **T-05** | `test_deepseek_qwen_providers.py` | 验证 `ModelProvider.from_string` 支持 `"deepseek"`、`"qwen"`、`"dashscope"`、`"bailian"`；`ModelFactory.create_model` 分别绑定各自专属的 `API_KEY` 与 `BASE_URL`（含 `DASHSCOPE_API_KEY` 回退） | ADR-002 |
| **T-06** | `test_deepseek_qwen_providers.py` | 验证 `DEEPSEEK` 与 `QWEN` 实例化的 `ChatOpenAI` 必然满足 `model.stream_usage is True` 且 `model.max_retries == 0` | B5 |
| **T-07** | `test_deepseek_qwen_providers.py` | **P-003 模态保护测试**：为 `operator` 的主模型或 `fallback` 配置 `is_multimodal=False` 时，`validate_providers()` 必须在启动期抛出异常 | B3 |
| **T-08** | `test_deepseek_qwen_providers.py` | 验证 `RobustChatModelWrapper.with_structured_output` 在 `DEEPSEEK` / `QWEN` 端点下默认向底层传入 `method="function_calling"`，且支持被 `endpoint.structured_output_method` 覆盖 | B4 |
| **T-09** | `test_deepseek_qwen_providers.py` | 验证 `classify_failure` 对 HTTP `402`（或 `"insufficient balance"`）返回 `retryable=False, should_fallback=True`，且 `_ObservedFallback` 立即切换至 `fallback` 而不原地重试；验证 `normalize_usage` 正确提取 `prompt_cache_hit_tokens` | B3, B5 |
| **T-10** | `test_object_detector_coords.py` | **Golden Fixtures 坐标归一化测试**：覆盖 `point_yx_1000`、`point_xy_1000`、`bbox_yxyx_1000`、`bbox_xyxy_1000`、`bbox_xyxy_px`（传入 `image_size=(1080, 2400)`）五种格式，断言输出均为 `[x, y] ∈ [0, 1000]`，且不会发生二次翻转 | B6 |
| **T-11** | `test_object_detector_coords.py` | **异常与退化框过滤测试**：对倒置框 `[500, 500, 200, 200]`、零面积框 `[100, 100, 100, 200]`、越界坐标 `[-50, 1200]`、缺少 `image_size` 的 `bbox_xyxy_px` 以及非数字字段进行断言 | B6 |
| **T-12** | `test_object_detector_coords.py` | **Detector 超时与 Fallback 闭环测试**：模拟主 Detector 抛出 503 / Timeout，断言 `_run_object_detection` 自动触发配置的 `fallback` 模型并按 `fallback` 的 `coord_format` 正确返回检测结果 | B7 |
