# Sprint 内 Session 复用与 Prompt 精简计划

更新时间：2026-04-24

## 1. 背景

`codex-ma` 当前已经在任务状态中记录各个 `logical_session` 的 `session_id`，但实际执行时仍然采用每个 phase 都重新发起一次 fresh `codex exec` 的方式。当前设计的优点是稳定、可控、便于保证结构化 JSON 输出；缺点是同一角色在同一职责链路中无法复用原生会话记忆，导致：

- `generator` 和 `evaluator` 在 negotiate 多轮循环中需要反复把历史协商上下文重新注入 prompt。
- `generator` 在同一 feature 的实现、L1 失败返工、review finding 修复中会重复加载同类背景。
- `reviewer` 在同一个 review job 的复审链路里无法持续沿用前一次审查语境。
- prompt 体积偏大，容易引入与当前动作无关的噪声。

本计划的目标是在不破坏现有 `schema-first` 约束的前提下，引入 Sprint 内按 `logical_session` 的 session 复用，并同步实施 prompt 精简。

## 2. 目标

- 在同一 `task` 的同一 `sprint` 内，按 `logical_session` 复用 session。
- 减少重复背景注入，提高同一职责链路中的推理连贯性。
- 将 prompt 从“全量状态注入”改为“冷启动全量 + 热启动增量”。
- 保持当前 JSON Schema 输出要求不变。
- 保留 fresh exec 兜底路径，确保系统可降级、可回退、可观测。

## 3. 范围

### 3.1 范围内

- `generator_contract`
- `evaluator_contract`
- `generator_feature_<feature_id>`
- `reviewer_feature_<feature_id>`
- `reviewer_dimension_<dimension>`
- `evaluator_holistic`
- prompt 上下文裁剪与最小注入
- session 元数据建模、事件记录、降级回退

### 3.2 范围外

- 跨 sprint 复用 session
- 重写现有 phase 状态机
- 修改 agent 输出 schema 的业务语义
- 引入新的角色、新的 workflow 或新的 review 模型

## 4. 会话复用策略

### 4.1 唯一标识

单个可复用会话由以下组合唯一标识：

`task_id + sprint_number + logical_session`

### 4.2 会话粒度

- `generator_contract`：覆盖整个 negotiate 链路。
- `evaluator_contract`：覆盖整个 negotiate 链路。
- `generator_feature_<feature_id>`：覆盖该 feature 的实现、L1 返工与 review finding 修复。
- `reviewer_feature_<feature_id>`：每个 feature review job 一条独立 session。
- `reviewer_dimension_<dimension>`：每个 dimension review job 一条独立 session。
- `evaluator_holistic`：默认独立一条 session；后续可评估是否并入 `evaluator_contract`。

### 4.3 生命周期

- sprint 创建时不预先创建 session，首次调用时懒创建。
- 同一 `logical_session` 在同一 sprint 内持续复用同一 `session_id`。
- 进入下一 sprint 后，旧 session 不再复用，只保留元数据用于审计。
- 某一 `logical_session` 出现 resume 失败、schema 输出不稳定或明显上下文污染时，只熔断该会话，不影响其它会话。

## 5. Prompt 精简原则

## 5.1 总体策略

采用“两段式上下文注入”：

- 冷启动：首次进入某个 `logical_session`，注入完整背景。
- 热启动：同一 session 后续调用只注入当前动作最小必需状态。

### 5.2 永远保留

- `workspace_policy`
- `role / action / phase / scope`
- 输出 schema 约束
- 当前任务边界与不可越界规则
- 当前动作必须解决的问题

### 5.3 优先裁掉

- 全量 `previous_rounds`
- 全量 `accepted_contract`
- 全量 `implementation`
- 与当前 scope 无关的 feature 执行结果
- 与当前 review job 无关的 review verdict
- 重复出现的背景介绍和历史正文

### 5.4 状态来源分层

- `manifest.json`：只提供任务级锚点，不作为全量 prompt 数据源。
- `sprint-xxx.json`：只提取当前 phase 相关切片。
- `artifacts/*.json`：只提取最近一次同 `logical_session` 的摘要或当前动作直接依赖的对手输出。
- 新增 `session brief`：作为热启动 prompt 的主输入。

## 6. 各链路的上下文注入方案

### 6.1 Generator Contract

冷启动注入：

- `user_request`
- `inheritance`
- `generator_research`
- `workspace_policy`

热启动注入：

- 当前 `round_number`
- 最新 `evaluator_feedback` 摘要
- 当前 `unresolved_points`
- 最新 `human_intervention.decisions`
- 当前合同基线摘要

不再默认注入：

- 全量 `negotiation_rounds`
- 全量 `generator_research`
- 全量 `evaluator_research`

### 6.2 Evaluator Contract

冷启动注入：

- `user_request`
- `inheritance`
- `generator_research`

热启动注入：

- 最新 `generator_proposal` 或 `generator_resolution` 摘要
- 当前 `unresolved_points`
- 人工裁决摘要
- 当前协商基线摘要

不再默认注入：

- 全量历史提案
- 全量历史反馈
- 全量协商轮次正文

### 6.3 Generator Feature

冷启动注入：

- 当前 feature 的 `feature_id / title_zh / reason_zh`
- 该 feature 的 acceptance criteria
- 相关 L1 checks
- 必要的全局验收摘要
- workspace 边界约束

热启动注入：

- 当前 feature 最近一次 execution summary
- 该 feature 最新失败 `l1_checks`
- 与该 feature 相关的 review findings
- 该 feature 最近修改的 `changed_files`
- 当前 blocker / fix list

不再默认注入：

- 其它 feature 的执行结果
- 全量 `implementation.features`
- 整个 `accepted_contract`

### 6.4 Reviewer Job

冷启动注入：

- 当前 `review_job`
- 当前 scope 对应的 contract slice
- 当前 scope 对应的 implementation slice
- 当前 scope 的 `changed_files`

热启动注入：

- 上次 verdict 摘要
- 待复审 findings
- 本次新增修复摘要

不再默认注入：

- 其它 review job 的 verdict
- 无关 feature 的实现历史

### 6.5 Evaluator Holistic

注入：

- `aggregate_review` 摘要
- accepted contract 的全局验收摘要
- 实现总摘要
- 必要的人类裁决摘要

不再默认注入：

- 全量 negotiate 历史
- 全量 contract doc
- 全量 review verdict 正文

## 7. Session Brief 设计

为每个 `logical_session` 增加一个轻量摘要文件，作为热启动 prompt 的主输入。建议文件位置：

`project_workspace/.codex-ma/runs/<task-id>/artifacts/sprint-xxx/session-brief-<logical_session>.json`

建议字段：

- `logical_session`
- `current_goal`
- `decisions_so_far`
- `open_questions`
- `last_counterparty_summary`
- `must_not_forget`
- `last_action`
- `updated_at`

设计原则：

- brief 是显式、可审计的外部记忆，不依赖模型隐式记忆作为唯一真相源。
- prompt 热启动优先使用 brief，再补本轮新增状态。
- brief 内容必须短小、稳定、可回放。

## 8. 数据模型与配置改造

### 8.1 Manifest 扩展

细化 `agent_sessions` 结构，建议至少记录：

- `role`
- `profile`
- `session_id`
- `scope`
- `sprint_number`
- `status`
- `last_action`
- `last_used_at`
- `reuse_count`
- `degraded_to_fresh`
- `last_error`

### 8.2 配置项

建议在 `multiagent.toml` 中增加：

- `session_reuse_enabled`
- `prompt_compaction_enabled`
- `session_reuse_mode = "sprint"`
- `prompt_budget_chars` 或 `prompt_budget_tokens`
- `session_reuse_degrade_threshold`

## 9. 代码改造点

### 9.1 `src/codex_ma/runner.py`

- 抽象 `fresh exec` 与 `session reuse` 两条调用路径。
- 增加 Codex CLI capability probe。
- resume 失败时自动降级 fresh exec。
- 保留现有 `--output-schema`、超时、输出路径与 JSON 校验逻辑。

### 9.2 `src/codex_ma/orchestrator.py`

- 在 `_invoke_agent()` 前增加 session 解析、复用判定、降级逻辑。
- 将 `logical_session` 从“记录 session_id”升级为“真实会话单元”。
- 增加以下事件：
  - `AGENT_SESSION_REUSED`
  - `AGENT_SESSION_RESET`
  - `PROMPT_COMPACTED`

### 9.3 `src/codex_ma/prompts.py`

- 将 `build_prompt()` 拆分为“静态模板 + action 级 context builder”。
- 给每个 action 定义最小字段白名单。
- 引入 prompt compactor，按链路裁剪上下文。

### 9.4 `src/codex_ma/state.py`

- 增加 canonical summary 构造函数。
- 增加 session brief 构造函数。
- 为不同 action 输出最小上下文切片。

### 9.5 `schemas/manifest.schema.json`

- 将 `agent_sessions` 从松散对象升级为受约束结构。
- 保证是字段新增，不做破坏性替换。

### 9.6 测试

需要补充或调整：

- `tests/test_runner.py`
- `tests/test_orchestrator.py`
- 必要时补充 `tests/test_state.py`

## 10. 回退机制

### 10.1 开关回退

- 关闭 `session_reuse_enabled`，系统退回现有 fresh exec 模式。
- 关闭 `prompt_compaction_enabled`，系统恢复全量 context 注入。

### 10.2 运行时回退

- 单次 session resume 失败时，自动切 fresh exec，不阻断任务。
- 单个 `logical_session` 连续失败达到阈值后，标记本 sprint 内不再复用。
- 降级信息写入 `agent_sessions` 与 `events.jsonl`。

### 10.3 数据兼容

- `manifest` 采用向后兼容的新增字段方式。
- 不删除现有 fresh exec 路径。
- 不依赖一次性迁移历史任务数据。

## 11. 实施顺序

### 阶段 1：能力探测与数据建模

- 明确 resume 能力边界
- 定义 `agent_sessions` 完整模型
- 定义 session brief 结构
- 定义 action 级最小上下文字段白名单

### 阶段 2：主链路打通

- 改造 runner
- 改造 orchestrator
- 打通 `logical_session -> session_id -> reuse/degrade`

### 阶段 3：Prompt 精简落地

- 实现 prompt compactor
- 接入 brief 驱动的热启动上下文
- 按 negotiate / feature / review / holistic 分链路调优

### 阶段 4：测试与观测

- 增加单元测试与集成测试
- 增加 session 与 prompt 压缩事件
- 补充统计指标

### 阶段 5：灰度启用

- 先开 `generator_contract`
- 再开 `evaluator_contract`
- 再开 `generator_feature_<id>`
- 最后评估 `reviewer` 与 `evaluator_holistic`

## 12. 验证标准

### 12.1 功能正确性

- 同 sprint 同 `logical_session` 多次调用时复用同一 `session_id`
- 新 sprint 不复用上一 sprint 的 `session_id`
- resume 失败可自动降级
- pause / resume / stop / timeout 语义不被破坏

### 12.2 Prompt 质量

- 平均 prompt 长度明显下降
- 必需字段无丢失
- 结构化 JSON 输出通过率不下降

### 12.3 运行稳定性

- 平均耗时不明显劣化
- timeout / blocked / aborted 占比不明显上升
- review 与 holistic 结论稳定性不下降

## 13. 建议的首轮灰度范围

首轮只打开以下链路：

- `generator_contract`
- `evaluator_contract`
- `generator_feature_<feature_id>`

原因：

- 这三段最能体现“连续思考”的收益。
- 链路相对串行，便于定位 session 复用问题。
- 相比 reviewer 并行链路，风险更低、收益更直接。

## 14. 最终结论

这项改造的本质不是单纯“让 agent 复用一个 `session_id`”，而是把当前编排系统从“每次重新装载全量状态”升级为“围绕 `logical_session` 的连续会话 + 增量上下文注入”。

正式实施时必须坚持三条底线：

- `schema-first` 不退化
- fresh exec 始终可回退
- 显式落盘状态仍然是真相源，session 记忆只是增强层
