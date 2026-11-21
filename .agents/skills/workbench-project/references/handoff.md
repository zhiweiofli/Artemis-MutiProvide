# Handoff v1

交接事实，不交接聊天或思维过程。一个 JSON 文件索引项目内的现有产物；运行状态继续由宿主管理。

## 必需字段

| 字段 | 内容 |
|---|---|
| `schema_version` | `1` |
| `goal` / `scope` / `acceptance_criteria` | 目标字符串、允许写入路径数组、可观察验收标准数组 |
| `workspace` | `path` 真实绝对项目路径、`head` 提交或 null、`dirty` 布尔值 |
| `baseline` | 项目内基线 JSON 的 `path` 与 `sha256`；改动前生成 |
| `changes` | 本轮每个新增/修改/删除文件的 `path`、`before_sha256`、`after_sha256`；不存在用 null |
| `context` | 本次需要读取的项目文件 `path`、`sha256` 数组 |
| `evidence` | 真实产物 `path`、`sha256`、`command`、`result` 数组；证据不存在不能填 passed |
| `decisions` / `open_questions` | 本轮继续有效的决定和未决项字符串数组，可以为空 |
| `acceptance` | `local_verification`、`production_deployment`、`real_client_acceptance`、`human_acceptance`，值为 `passed` / `failed` / `pending` / `N/A` |

`changes` 覆盖本轮契约与实现文件，不将仓库已有脏文件算作本轮修改。`context` 至少含 `.agent/contract.json` 与其必需角色路径。交接包、基线和最终验收总结是交付元数据，不形成递归摘要；在 `scope` 和交付说明中列出。元数据不属于 baseline.paths 的保护声明，需接手者实际读取核对。

## 基线与验证

```sh
node scripts/check.mjs snapshot /absolute/project /absolute/project/.local/baseline.json AGENTS.md README.md package.json catalog.json src scripts test
node scripts/check.mjs verify /absolute/project /absolute/project/reports/handoff.json
```

基线只覆盖 snapshot 明确声明的文件或目录。将本轮需要保持的现有资产以及会新增文件的目录列入覆盖范围；不要扫描私人历史或其他项目。验证器检查覆盖范围内的真实差异是否完整申报、原文件是否保持，以及上下文/证据摘要是否对应当前文件。报告必须说明未覆盖范围。

snapshot 输出包含 `root`、`paths` 和 `files` 路径到 SHA-256 的映射。无 Git 提交时 `head=null` 是合法基线，dirty 工作区可以交接。摘要一致不等于独立验收：接手者应读取产物、按原目标复核行为与限制。

## 接手

新会话只给项目路径与交接包路径。接手者先读取项目规则，运行 doctor/verify，然后核对实际 diff、命令结果和未决项，再生成审查报告。不要把文件中声称的 passed 直接当作自己的结论。

用户接受前 `human_acceptance=pending`；只读审查不代替安装后的业务调用。未部署的本地治理资产 `production_deployment=N/A`。无法观测自动发现时记录未验证，不能靠指定读取冒充通过。
