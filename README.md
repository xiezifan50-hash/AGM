# codex-ma

`codex-ma` 是一个基于 Codex CLI 的多 Agent Sprint 协作系统原型，面向单仓库、CLI-first 的研发任务编排。它把用户需求拆成可协商的合同、可执行的 feature 队列、可审计的 review 任务和可恢复的 Sprint 状态。

## 当前状态

- 项目阶段：原型可运行。
- 主体能力：已具备任务创建、项目空间隔离、Sprint 状态持久化、合同协商、串行实现、L1 检查、并行 review、Holistic Review、失败结转、恢复入口、显式暂停/停止入口和命令行阶段成果输出。
- 最新业务交付：`snake.html` 单文件贪吃蛇网页小游戏已完成，`runs/task-003` 记录显示第 4 个 Sprint 已通过 review 与 Holistic Review，任务状态为 `done`。
- 测试覆盖：已有 CLI、状态计算、完整编排流程和人工介入恢复相关单元测试。

## 架构概览

```text
用户请求
  -> CLI
  -> 显式 project workspace
  -> Orchestrator 状态机
  -> Runner 在 project workspace 内调用 Codex CLI 或 fixture
  -> Agent JSON 输出
  -> JSON Schema 校验
  -> Storage 持久化 manifest / sprint / events / artifacts
```

核心模块职责：

- `src/codex_ma/cli.py`：命令行入口，负责解析命令并派发到编排器。
- `src/codex_ma/orchestrator.py`：核心状态机，串联协商、实现、检查、review、结转和恢复流程，并确保内部 agent 只在任务绑定的 project workspace 中运行。
- `src/codex_ma/runner.py`：Agent 执行适配层，支持真实 `codex exec` 与测试用 `FixtureRunner`。
- `src/codex_ma/storage.py`：运行状态与事件日志的读写，写入前执行 schema 校验。
- `src/codex_ma/state.py`：manifest、sprint、合同共识、下一轮继承等状态构建逻辑。
- `src/codex_ma/config.py`：读取 `multiagent.toml`，解析角色 profile、并发、重试和安全配置。
- `src/codex_ma/prompts.py`：不同角色和动作的提示词模板。
- `schemas/`：持久化状态、事件日志和 Agent 输出的 JSON Schema。
- `runs/`：任务编排状态目录，包含 `manifest.json`、`sprint-xxx.json` 和 `events.jsonl`；内部 agent 结构化 artifacts 写入 project workspace 的 `.codex-ma/runs/<task-id>/artifacts/`。
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
11. `DONE` / `NEXT_SPRINT_PREP` / `blocked` / `paused` / `aborted`：完成、结转下一轮、阻塞、用户软暂停或显式终止。

## 快速开始

```bash
python3 -m codex_ma init
python3 -m codex_ma task create --workspace ./project-space "实现一个可恢复的多 agent orchestrator"
python3 -m codex_ma run task-001
python3 -m codex_ma pause task-001
python3 -m codex_ma resume task-001
python3 -m codex_ma stop task-001
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
- `codex-ma task create --workspace <path> <用户需求>`：创建任务，可通过 `--task-id` 指定 ID。`--workspace` 必填，内部 agent 只能在该目录内工作。
- `codex-ma run <task-id>`：运行任务直到完成、阻塞或等待人工输入；运行中会主动输出调研、协商、实现、L1、review、holistic review 和返工决策摘要。
- `codex-ma pause <task-id>`：将任务标记为 `paused`，保留当前 phase，后续可通过 `resume` 从原进度继续。
- `codex-ma resume <task-id>`：从用户暂停点、人工暂停点或当前可恢复状态继续运行，并继续输出阶段成果摘要。
- `codex-ma stop <task-id>`：将任务标记为 `aborted`，让后续 `run` / `resume` 不再推进；如果已有 runner 正在执行，当前 agent 调用返回后会停止，不会用旧内存状态覆盖停止结果。
- `codex-ma status <task-id> [--json]`：查看任务状态。
- `codex-ma events <task-id> [--tail N]`：查看事件流。

## 运行输出

`run` / `resume` 会在关键阶段完成后打印易读摘要，减少反复手动查询状态：

- 调研阶段：输出 generator / evaluator 的摘要、feature 计划、主要风险与关注点。
- Negotiate：每个 agent 子步骤开始和完成时输出进度，包含 proposal、feedback、argue back、resolution；每轮结束后输出 pass 状态、generator 修订摘要、evaluator 结论、未决点；合同达成后输出 feature 队列和全局验收摘要。
- 实现阶段：每个 feature 完成后输出执行摘要、变更文件、阻塞信息；L1 检查输出通过/失败详情和是否返工。
- Review：输出 review 队列、每个 review verdict、findings 摘要、聚合结果和建议。
- Holistic Review：输出最终通过/未通过、满意度缺口、需结转 feature 和下一步。

## 配置

项目根目录使用 `multiagent.toml`。`init` 会在缺失时写入默认配置。

关键配置项：

- `[profiles]`：为 `orchestrator`、`generator`、`evaluator`、`reviewer` 指定 Codex profile。
- `[codex].binary`：Codex CLI 路径，默认 `codex`。
- `[codex].search`：是否允许 Codex CLI 使用搜索。
- `[codex].agent_timeout_seconds`：单次 `codex exec` agent 调用超时时间，默认 900 秒。
- `[negotiation].max_rounds`：合同协商最大轮数。
- `[implementation].l1_retry_limit`：L1 检查失败后的最大重试次数。
- `[implementation].check_timeout_seconds`：L1 shell 检查超时时间。
- `[review].max_concurrency`：并行 review 最大并发数。
- `[review].dimensions`：默认 review 维度。
- `[safety]`：网络访问和危险操作审批策略。

## 数据与产物

每个任务必须绑定一个 project workspace。编排器在 `runs/<task-id>/` 保存任务状态：

- `manifest.json`：任务级状态、当前阶段、恢复指针、agent session、review 队列摘要；`status` 可为 `in_progress`、`paused`、`blocked`、`done`、`aborted` 等。
- `sprint-001.json` 等：Sprint 级合同、实现、review、Holistic Review 和下一轮继承信息。
- `events.jsonl`：按时间追加的事件日志。

内部 agent 只能在绑定的 project workspace 内运行和写入文件：

- Codex CLI 的工作目录为 project workspace。
- Agent JSON artifacts 写入 `project_workspace/.codex-ma/runs/<task-id>/artifacts/sprint-xxx/*.json`。
- L1 shell 检查也在 project workspace 中执行。
- project workspace 不能是 `codex-ma` 工具仓库本身或其父目录，防止内部 agent 观察或修改工具层文件。
- project workspace 内的 `README.md` / `README.markdown` 属于项目文件，内部 agent 可以按任务需要修改；project workspace 外的 README 或其它文件不属于内部 agent 工作范围。
- generator 输出的 `changed_files` 会做边界校验，任何指向 project workspace 外的路径都会让本次 agent 调用失败。

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

### 2026-04-24

- 新增 `codex-ma pause <task-id>`，支持将任务软暂停为 `paused` 并在后续通过 `resume` 从原 phase 继续。
- 新增 `[codex].agent_timeout_seconds`，默认 900 秒，避免单次 `codex exec` agent 调用无限阻塞。
- 增强 Negotiate 进度输出：proposal、feedback、argue back、resolution 每个子步骤开始和完成时都会打印阶段日志，便于定位卡住的 agent 调用。

### 2026-04-23

- 初始化 `codex-ma` Python CLI 原型，建立 `src/codex_ma`、`schemas`、`tests`、`runs` 等目录结构。
- 实现多角色协作状态机：generator / evaluator / reviewer 的合同协商、feature 实现、review 和 holistic 审批。
- 增加 `multiagent.toml` 配置、Codex CLI runner、fixture runner、schema 校验和事件日志。
- 增加单元测试，覆盖 CLI 初始化与任务创建、共识计算、完整运行、人工介入恢复。
- 新增 `snake.html` 单文件贪吃蛇小游戏，并通过 `task-003` 的最终 Sprint 验收。
- 扩展 README，补充项目架构、进展、更新日志和维护约束。
- 新增 `codex-ma stop <task-id>`，支持把任务显式标记为 `aborted`，并防止运行中的旧状态在 agent 调用返回后覆盖停止结果。
- 新增强制 project workspace：`task create` 必须指定 `--workspace`，内部 agent 的 cwd、artifacts 和 L1 检查都限制在该目录；项目空间内 README 可按项目任务修改，工具仓库 README 不暴露给内部 agent。
- 增强 `run` / `resume` 的交互输出：阶段完成后主动打印合同协商、feature 执行、L1 检查、review verdict、返工与最终审批摘要。

## 维护约束

每次进行功能变更时，必须同步更新本文件，至少检查并维护以下部分：

- `当前状态`：说明项目阶段、能力边界或最新交付状态是否变化。
- `架构概览`：涉及模块职责、目录结构、数据流或状态机变化时必须更新。
- `快速开始` / `主要命令` / `配置`：涉及运行方式、命令参数或配置项变化时必须更新。
- `项目进展`：新增任务、完成重要 Sprint、引入重大能力或发现明确限制时必须更新。
- `更新日志`：按日期追加本次变更摘要。
- `测试`：新增或调整测试命令、测试策略、依赖要求时必须更新。

提交功能代码前，请把 README 更新视为完成标准的一部分；如果某次变更不需要改 README，应在提交说明或评审说明中明确原因。
