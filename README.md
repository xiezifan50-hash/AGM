# codex-ma

`codex-ma` 是一个基于 Codex CLI 的多 Agent Sprint 协作系统原型，面向单仓库、CLI-first 的研发任务编排。

## 功能

- 四角色协作：`orchestrator` / `generator` / `evaluator` / `reviewer`
- Sprint 级状态持久化、恢复与审计
- 协商式 Contract：Holistic Review 审批标准在 `NEGOTIATE` 环节共同协商
- 串行实现、并行评审、下一轮 Sprint 继承
- 真实 `codex exec` 适配层与测试用 fixture runner

## 快速开始

```bash
python3 -m codex_ma init
python3 -m codex_ma task create "实现一个可恢复的多 agent orchestrator"
python3 -m codex_ma run task-001
python3 -m codex_ma status task-001
```

## 主要命令

- `codex-ma init`
- `codex-ma task create <用户需求>`
- `codex-ma run <task-id>`
- `codex-ma resume <task-id>`
- `codex-ma status <task-id>`
- `codex-ma events <task-id>`
- `codex-ma doctor`

## 配置

项目根目录使用 `multiagent.toml`。`init` 会自动写入默认配置。核心配置项：

- `negotiation.max_rounds = 2`
- `implementation.l1_retry_limit = 3`
- `review.max_concurrency = 4`
- `review.dimensions = ["correctness", "regression-risk", "api-ux-contract"]`

## 测试

```bash
python3 -m unittest discover -s tests -v
```
