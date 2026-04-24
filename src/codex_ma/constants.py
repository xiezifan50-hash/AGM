from __future__ import annotations

PHASE_INIT = "INIT"
PHASE_NEGOTIATE_GENERATOR_RESEARCH = "NEGOTIATE_GENERATOR_RESEARCH"
PHASE_NEGOTIATE_EVALUATOR_RESEARCH = "NEGOTIATE_EVALUATOR_RESEARCH"
PHASE_NEGOTIATE_ROUND = "NEGOTIATE_ROUND"
PHASE_CONTRACT_ACCEPTED = "CONTRACT_ACCEPTED"
PHASE_IMPLEMENTING = "IMPLEMENTING"
PHASE_L1_VERIFY = "L1_VERIFY"
PHASE_REVIEW_PREP = "REVIEW_PREP"
PHASE_PARALLEL_REVIEW = "PARALLEL_REVIEW"
PHASE_REVIEW_AGGREGATE = "REVIEW_AGGREGATE"
PHASE_HOLISTIC_REVIEW = "HOLISTIC_REVIEW"
PHASE_DONE = "DONE"
PHASE_NEXT_SPRINT_PREP = "NEXT_SPRINT_PREP"
PHASE_AWAITING_HUMAN = "AWAITING_HUMAN"

PHASES = (
    PHASE_INIT,
    PHASE_NEGOTIATE_GENERATOR_RESEARCH,
    PHASE_NEGOTIATE_EVALUATOR_RESEARCH,
    PHASE_NEGOTIATE_ROUND,
    PHASE_CONTRACT_ACCEPTED,
    PHASE_IMPLEMENTING,
    PHASE_L1_VERIFY,
    PHASE_REVIEW_PREP,
    PHASE_PARALLEL_REVIEW,
    PHASE_REVIEW_AGGREGATE,
    PHASE_HOLISTIC_REVIEW,
    PHASE_DONE,
    PHASE_NEXT_SPRINT_PREP,
    PHASE_AWAITING_HUMAN,
)

STATUS_IN_PROGRESS = "in_progress"
STATUS_PAUSED = "paused"
STATUS_DONE = "done"
STATUS_CARRY_FORWARD = "carry_forward"
STATUS_BLOCKED = "blocked"
STATUS_ABORTED = "aborted"

TASK_STATUSES = (
    STATUS_IN_PROGRESS,
    STATUS_PAUSED,
    STATUS_DONE,
    STATUS_CARRY_FORWARD,
    STATUS_BLOCKED,
    STATUS_ABORTED,
)

ROLE_ORCHESTRATOR = "orchestrator"
ROLE_GENERATOR = "generator"
ROLE_EVALUATOR = "evaluator"
ROLE_REVIEWER = "reviewer"

DEFAULT_DIMENSIONS = (
    "correctness",
    "regression-risk",
    "api-ux-contract",
)

DEFAULT_ROLE_PROFILES = {
    ROLE_ORCHESTRATOR: "orchestrator_readonly",
    ROLE_GENERATOR: "generator_execute",
    ROLE_EVALUATOR: "evaluator",
    ROLE_REVIEWER: "reviewer",
}

OUTPUT_SCHEMAS = {
    "contract_proposal": "schemas/agent-output/contract-proposal.schema.json",
    "contract_feedback": "schemas/agent-output/contract-feedback.schema.json",
    "contract_resolution": "schemas/agent-output/contract-resolution.schema.json",
    "feature_execution": "schemas/agent-output/feature-execution.schema.json",
    "review_verdict": "schemas/agent-output/review-verdict.schema.json",
    "holistic_review": "schemas/agent-output/holistic-review.schema.json",
}
