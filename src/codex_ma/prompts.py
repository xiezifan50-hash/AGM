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
请对指定 feature 做只读审查，可以读代码、读 diff、跑测试、查日志。
不要改代码。只输出 verdict 与 findings。
""",
    "DIMENSION_REVIEW": """
你是 reviewer。
请对指定 dimension 做只读审查，可以读代码、读 diff、跑测试、查日志。
不要改代码。只输出 verdict 与 findings。
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
