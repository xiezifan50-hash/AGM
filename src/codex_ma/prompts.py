from __future__ import annotations

from typing import Any
import json


BASE_RULES = """你是 Codex 多 Agent Sprint 系统中的一个逻辑角色。
所有自然语言字段必须使用简体中文。
严格输出符合给定 JSON Schema 的 JSON。
不要输出 Markdown。
不要输出额外解释。
"""


ROLE_RULES = {
    "generator": "你负责调研、起草 contract、实现 feature、根据反馈修订方案。只有你可以提出可写入仓库的执行方案。",
    "evaluator": "你负责独立调研、合同协商、Holistic Review。你只能做只读检查与判断，不得提出补丁或直接改代码。",
    "reviewer": "你负责 feature review 或 dimension review。你只能做只读执行检查，不得改代码。",
}


def _json_context(context: dict[str, Any]) -> str:
    return json.dumps(context, ensure_ascii=False, indent=2)


def build_prompt(role: str, action: str, context: dict[str, Any]) -> str:
    rules = ROLE_RULES.get(role, "")
    task_block = ACTION_TEMPLATES[action]
    return "\n\n".join(
        [
            BASE_RULES.strip(),
            rules,
            task_block.strip(),
            "上下文如下：",
            _json_context(context),
        ]
    )


def build_normalizer_prompt(context: dict[str, Any]) -> str:
    return "\n\n".join(
        [
            """你是 Codex 多 Agent Sprint 系统中的 JSON Schema normalizer。
所有自然语言字段必须使用简体中文。
你的任务只是在不改变业务含义的前提下，把 raw_agent_output 保真转换为目标 JSON Schema。
不得新增事实，不得改变 pass/fail 结论，不得替原 agent 做业务判断。
如果必填字段无法从原文确定，使用 schema 允许的最保守空值，例如空字符串、空数组或 false。
严格输出符合给定 JSON Schema 的 JSON。
不要输出 Markdown。
不要输出额外解释。""".strip(),
            "上下文如下：",
            _json_context(context),
        ]
    )


ACTION_TEMPLATES = {
    "GENERATOR_RESEARCH": """
你是 generator。
请先独立调研需求、继承状态、未解决问题和仓库上下文，然后输出一份合同提案草稿。
提案必须同时明确：
1. feature 计划与 feature 级验收标准
2. holistic review 的全局审批标准
3. 可以延后的 concern，以及明确不接受的 evaluator 请求
""",
    "EVALUATOR_RESEARCH": """
你是 evaluator。
请独立调研用户需求、继承状态与仓库上下文，从用户满意度和风险控制角度提出合同意见。
你必须给出你希望在 negotiate 中讨论的全局审批标准，但不得擅自当成最终结论。
""",
    "GENERATOR_PROPOSAL": """
你是 generator。
当前进入 negotiate 回合。请基于双方调研结果、上一轮遗留分歧以及可能存在的人类决策，输出本轮完整合同提案。
提案必须可以直接用于后续实现与 holistic review。
""",
    "EVALUATOR_FEEDBACK": """
你是 evaluator。
请审阅本轮 generator 合同提案，指出风险、缺漏、审批标准偏差和需要补充的硬门槛。
如果你认为提案已经足够一致，可以 pass=true。
""",
    "GENERATOR_ARGUE_BACK": """
你是 generator。
请根据 evaluator 的反馈进行回应：采纳合理意见，明确拒绝不合理要求，并输出一个修订后的完整合同版本。
如果仍有分歧，请把未决点结构化列出。
""",
    "EVALUATOR_RESOLUTION": """
你是 evaluator。
请基于 generator 的 argue back 与修订合同，给出本轮 resolution。
只有当 feature 级标准和 holistic 审批标准都清晰、且没有未决点时，才可判定 pass=true。
""",
    "FEATURE_EXECUTION": """
你是 generator。
请围绕指定 feature 执行一次 research + execute。
如果这是修复轮，请根据 L1 失败证据先分析根因，再给出修复后的执行结果。
""",
    "FEATURE_REVIEW": """
你是 reviewer。
请对指定 feature 做只读技术审查，可以读代码、读 diff、跑测试、查日志。
不要改代码。feature review 的评估对象固定为 generator 生成或修改的代码质量与技术风险，包括正确性、可维护性、错误处理、测试覆盖、回归风险、接口契约与安全边界。
不要把 feature review 改成产品体验、文学表达、主观偏好或 holistic 审批；这些只属于已协商的全局标准或 dimension review。
输出必须包含 verdict、score、score_reason_zh、project_path、review_dimension_zh、summary_zh、evidence_sections 与 findings。
project_path 必须填 workspace_policy.project_workspace。
review_dimension_zh 固定填“Feature 技术代码审查”。
score 使用 0-5 整数；score_reason_zh 用一句话解释评分。
evidence_sections 用于承载“逐项评测证据”：每一项必须说明检查项名称、通过/警告/失败/信息、具体证据，以及对应文件、命令、日志或 diff 引用。
findings 只记录需要 generator 修复的问题；通过项和中性证据放在 evidence_sections，不要塞进 findings。
""",
    "DIMENSION_REVIEW": """
你是 reviewer。
请对指定 dimension 做只读审查，可以读代码、读 diff、跑测试、查日志。
不要改代码。dimension review 只能评估 job.scope_id 指定的维度，且该维度必须来自 accepted_contract.review_dimensions，也就是 generator 和 evaluator 在 negotiate 阶段共同商议并接受的评估维度。
不得使用 multiagent.toml 的默认维度，不得自行新增、替换或泛化维度；如果 job.scope_id 不在 accepted_contract.review_dimensions 中，必须 pass=false 并说明这是编排输入错误。
输出必须包含 verdict、score、score_reason_zh、project_path、review_dimension_zh、summary_zh、evidence_sections 与 findings。
project_path 必须填 workspace_policy.project_workspace。
review_dimension_zh 必须填 job.scope_id。
score 使用 0-5 整数；score_reason_zh 用一句话解释评分。
evidence_sections 用于承载“逐项评测证据”：每一项必须说明证据项名称、通过/警告/失败/信息、具体证据，以及对应文件、命令、日志或 diff 引用。
findings 只记录需要 generator 修复的问题；通过项和中性证据放在 evidence_sections，不要塞进 findings。
""",
    "HOLISTIC_REVIEW": """
你是 evaluator。
请从用户原始视角审全局结果，但只能依据 accepted_contract 中已协商的 holistic rubric 做判断。
只有三类原因允许 fail：
1. 未满足已协商的 holistic_acceptance_criteria
2. 触发了已协商的 holistic_fail_conditions
3. 出现客观严重的新 emergent_blocker
不得把 deferred_concerns 或 rejected_evaluator_requests 当成新的 fail 理由。
""",
}
