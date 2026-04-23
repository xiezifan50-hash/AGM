# codex-ma

`codex-ma` 是一个基于 Codex CLI 的多 Agent Sprint 协作系统原型，面向单仓库、CLI-first 的研发任务编排。它把用户需求拆成可协商的合同、可执行的 feature 队列、可审计的 review 任务和可恢复的 Sprint 状态。

## 当前状态

- 项目阶段：原型可运行。
- 主体能力：已具备任务创建、Sprint 状态持久化、合同协商、串行实现、L1 检查、并行 review、Holistic Review、失败结转和恢复入口。
- 最新业务交付：`snake.html` 单文件贪吃蛇网页小游戏已完成，`runs/task-003` 记录显示第 4 个 Sprint 已通过 review 与 Holistic Review，任务状态为 `done`。
- 测试覆盖：已有 CLI、状态计算、完整编排流程和人工介入恢复相关单元测试。

## 架构概览

```text
用户请求
  -> CLI
  -> Orchestrator 状态机
  -> Runner 调用 Codex CLI 或 fixture
  -> Agent JSON 输出
  -> JSON Schema 校验
  -> Storage 持久化 manifest / sprint / events / artifacts
```

核心模块职责：

- `src/codex_ma/cli.py`：命令行入口，负责解析命令并派发到编排器。
- `src/codex_ma/orchestrator.py`：核心状态机，串联协商、实现、检查、review、结转和恢复流程。
- `src/codex_ma/runner.py`：Agent 执行适配层，支持真实 `codex exec` 与测试用 `FixtureRunner`。
- `src/codex_ma/storage.py`：运行状态与事件日志的读写，写入前执行 schema 校验。
- `src/codex_ma/state.py`：manifest、sprint、合同共识、下一轮继承等状态构建逻辑。
- `src/codex_ma/config.py`：读取 `multiagent.toml`，解析角色 profile、并发、重试和安全配置。
- `src/codex_ma/prompts.py`：不同角色和动作的提示词模板。
- `schemas/`：持久化状态、事件日志和 Agent 输出的 JSON Schema。
- `runs/`：任务运行态目录，包含 `manifest.json`、`sprint-xxx.json`、`events.jsonl` 和 artifacts。
- `tests/`：单元测试与 fixture 工作区。

## Sprint 流程

1. `INIT`：创建任务与初始 Sprint。
2. `NEGOTIATE_GENERATOR_RESEARCH` / `NEGOTIATE_EVALUATOR_RESEARCH`：generator 与 evaluator 独立调研。
3. `NEGOTIATE_ROUND`：双方围绕 feature 级验收与 Holistic Review 标准协商合同。
4. `AWAITING_HUMAN`：协商超过轮次上限时暂停，等待人工裁决。
5. `CONTRACT_ACCEPTED`：合同达成一致，生成实现队列。
6. `IMPLEMENTING`：generator 按 feature 串行执行。
7. `L1_VERIFY`：执行合同中的 L1 检查，失败时按重试上限返回修复。
8. `REVIEW_PREP` / `PARALLEL_REVIEW`：生成 feature review 和 dimension review，并按配置并发执行。
9. `REVIEW_AGGREGATE`：聚合 review 结果，存在问题则进入下一轮 Sprint。
10. `HOLISTIC_REVIEW`：evaluator 按已协商的全局标准做最终审批。
11. `DONE` / `NEXT_SPRINT_PREP` / `blocked`：完成、结转下一轮或阻塞。

## 快速开始

```bash
python3 -m codex_ma init
python3 -m codex_ma task create "实现一个可恢复的多 agent orchestrator"
python3 -m codex_ma run task-001
python3 -m codex_ma status task-001
```

也可以使用仓库根目录的可执行包装脚本：

```bash
./codex-ma doctor
./codex-ma events task-001 --tail 20
```

## 主要命令

- `codex-ma init`：初始化目录与默认配置。
- `codex-ma doctor`：检查 Codex CLI、profile、schema 和已有任务状态。
- `codex-ma task create <用户需求>`：创建任务，可通过 `--task-id` 指定 ID。
- `codex-ma run <task-id>`：运行任务直到完成、阻塞或等待人工输入。
- `codex-ma resume <task-id>`：从人工暂停点或当前状态继续运行。
- `codex-ma status <task-id> [--json]`：查看任务状态。
- `codex-ma events <task-id> [--tail N]`：查看事件流。

## 配置

项目根目录使用 `multiagent.toml`。`init` 会在缺失时写入默认配置。

关键配置项：

- `[profiles]`：为 `orchestrator`、`generator`、`evaluator`、`reviewer` 指定 Codex profile。
- `[codex].binary`：Codex CLI 路径，默认 `codex`。
- `[codex].search`：是否允许 Codex CLI 使用搜索。
- `[negotiation].max_rounds`：合同协商最大轮数。
- `[implementation].l1_retry_limit`：L1 检查失败后的最大重试次数。
- `[implementation].check_timeout_seconds`：L1 shell 检查超时时间。
- `[review].max_concurrency`：并行 review 最大并发数。
- `[review].dimensions`：默认 review 维度。
- `[safety]`：网络访问和危险操作审批策略。

## 数据与产物

每个任务会写入 `runs/<task-id>/`：

- `manifest.json`：任务级状态、当前阶段、恢复指针、agent session、review 队列摘要。
- `sprint-001.json` 等：Sprint 级合同、实现、review、Holistic Review 和下一轮继承信息。
- `events.jsonl`：按时间追加的事件日志。
- `artifacts/sprint-xxx/*.json`：每次 Agent 调用的结构化输出。

Agent 输出必须匹配 `schemas/agent-output/*.schema.json`。任务状态和事件分别受 `schemas/manifest.schema.json`、`schemas/sprint-state.schema.json`、`schemas/event-log.schema.json` 约束。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

测试默认使用 `FixtureRunner`，不依赖真实 Codex CLI 调用。真实运行任务时需要本机可用的 Codex CLI，并在 `multiagent.toml` 中配置好角色 profile 或使用内置 fallback flags。

## 贪吃蛇小游戏

仓库根目录包含纯前端单文件入口 `snake.html`。直接用浏览器打开即可运行，无需后端、登录或联网资源。

操作方式：

- `方向键` 或 `WASD` 控制移动。
- `空格` 暂停或继续。
- 失败或通关后点击“重新开始”或按 `Enter` 重开。

## 项目进展

- `task-001`：贪吃蛇网页小游戏任务创建后停留在 generator 调研阶段。
- `task-002`：贪吃蛇网页小游戏任务创建后停留在 generator 调研阶段。
- `task-003`：贪吃蛇网页小游戏完成 4 个 Sprint，最终通过 4 个 feature review、3 个 dimension review 和 Holistic Review，状态为 `done`。
- 当前代码侧已实现多 Agent Sprint 编排核心闭环，后续重点可放在真实场景稳定性、运行态清理策略、更多端到端示例和更细的失败恢复体验。

## 更新日志

### 2026-04-23

- 初始化 `codex-ma` Python CLI 原型，建立 `src/codex_ma`、`schemas`、`tests`、`runs` 等目录结构。
- 实现多角色协作状态机：generator / evaluator / reviewer 的合同协商、feature 实现、review 和 holistic 审批。
- 增加 `multiagent.toml` 配置、Codex CLI runner、fixture runner、schema 校验和事件日志。
- 增加单元测试，覆盖 CLI 初始化与任务创建、共识计算、完整运行、人工介入恢复。
- 新增 `snake.html` 单文件贪吃蛇小游戏，并通过 `task-003` 的最终 Sprint 验收。
- 扩展 README，补充项目架构、进展、更新日志和维护约束。

## 维护约束

每次进行功能变更时，必须同步更新本文件，至少检查并维护以下部分：

- `当前状态`：说明项目阶段、能力边界或最新交付状态是否变化。
- `架构概览`：涉及模块职责、目录结构、数据流或状态机变化时必须更新。
- `快速开始` / `主要命令` / `配置`：涉及运行方式、命令参数或配置项变化时必须更新。
- `项目进展`：新增任务、完成重要 Sprint、引入重大能力或发现明确限制时必须更新。
- `更新日志`：按日期追加本次变更摘要。
- `测试`：新增或调整测试命令、测试策略、依赖要求时必须更新。

提交功能代码前，请把 README 更新视为完成标准的一部分；如果某次变更不需要改 README，应在提交说明或评审说明中明确原因。
