from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import copy
import re

from codex_ma.constants import (
    DEFAULT_DIMENSIONS,
    PHASE_INIT,
    STATUS_IN_PROGRESS,
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def slugify_task_id(value: str) -> str:
    raw = value.strip().lower()
    raw = re.sub(r"[^a-z0-9]+", "-", raw)
    raw = raw.strip("-")
    return raw or "task"


def make_task_id(existing: set[str]) -> str:
    index = 1
    while True:
        candidate = f"task-{index:03d}"
        if candidate not in existing:
            return candidate
        index += 1


def empty_contract() -> dict[str, Any]:
    return {
        "generator_research": None,
        "evaluator_research": None,
        "negotiation_rounds": [],
        "feature_consensus": [],
        "global_consensus": {
            "pass": False,
            "unresolved_points_zh": [],
            "missing_fields": [],
        },
        "holistic_rubric": {
            "user_success_statement_zh": "",
            "must_have_features": [],
            "nice_to_have_features": [],
            "holistic_acceptance_criteria_zh": [],
            "holistic_fail_conditions_zh": [],
            "deferred_concerns_zh": [],
            "rejected_evaluator_requests": [],
        },
        "accepted_contract": None,
        "unresolved_points": [],
        "human_intervention": {
            "required": False,
            "reason_zh": "",
            "decisions": [],
        },
    }


def empty_implementation() -> dict[str, Any]:
    return {
        "feature_queue": [],
        "current_feature_id": None,
        "features": [],
        "changed_files": [],
        "l1_checks": [],
    }


def empty_reviews() -> dict[str, Any]:
    return {
        "review_jobs": [],
        "feature_reviews": [],
        "dimension_reviews": [],
        "aggregate": {
            "all_required_passed": False,
            "open_findings": [],
        },
    }


def empty_holistic_review() -> dict[str, Any]:
    return {
        "pass": None,
        "summary_zh": "",
        "satisfaction_gaps_zh": [],
        "carry_forward_required": [],
        "rejected_review_findings": [],
        "decision_basis": {
            "unmet_acceptance_criteria_zh": [],
            "triggered_fail_conditions_zh": [],
            "emergent_blockers": [],
        },
    }


def empty_next_sprint_seed() -> dict[str, Any]:
    return {
        "should_create_next_sprint": False,
        "accepted_features_inherited": [],
        "open_features": [],
        "open_findings": [],
        "rejected_findings": [],
        "canonical_context": "",
    }


def build_initial_manifest(
    task_id: str,
    user_request: str,
    project_workspace: str | None = None,
) -> dict[str, Any]:
    timestamp = now_iso()
    return {
        "task_id": task_id,
        "user_request": user_request,
        "project_workspace": project_workspace,
        "latest_sprint": 1,
        "latest_file": f"runs/{task_id}/sprint-001.json",
        "status": STATUS_IN_PROGRESS,
        "current_phase": PHASE_INIT,
        "resume_pointer": {
            "phase": PHASE_INIT,
            "file": f"runs/{task_id}/sprint-001.json",
            "reason_zh": "任务已创建，等待首次运行。",
        },
        "agent_sessions": {},
        "human_gate": {
            "active": False,
            "reason_zh": "",
            "unresolved_points": [],
        },
        "review_queue_summary": {
            "queued": 0,
            "running": 0,
            "completed": 0,
            "max_concurrency": 0,
        },
        "timestamps": {
            "created_at": timestamp,
            "updated_at": timestamp,
        },
    }


def build_initial_sprint(
    task_id: str,
    user_request: str,
    sprint_number: int = 1,
    inherited: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timestamp = now_iso()
    inherited = inherited or {
        "from_sprint_number": None,
        "accepted_features_inherited": [],
        "open_findings_inherited": [],
        "rejected_findings_inherited": [],
        "canonical_context": {
            "summary_zh": "首次 Sprint，无继承状态。",
            "artifact_index": [],
        },
    }
    return {
        "task_id": task_id,
        "sprint_id": f"{task_id}-sprint-{sprint_number:03d}",
        "sprint_number": sprint_number,
        "status": STATUS_IN_PROGRESS,
        "phase": PHASE_INIT,
        "user_request": user_request,
        "inheritance": inherited,
        "contract": empty_contract(),
        "implementation": empty_implementation(),
        "reviews": empty_reviews(),
        "holistic_review": empty_holistic_review(),
        "next_sprint_seed": empty_next_sprint_seed(),
        "resume_from": {
            "phase": PHASE_INIT,
            "pending_actor": "orchestrator",
            "reason_zh": "等待开始 Sprint。",
        },
        "timestamps": {
            "created_at": timestamp,
            "updated_at": timestamp,
        },
    }


def touch(document: dict[str, Any]) -> None:
    document.setdefault("timestamps", {})
    created_at = document["timestamps"].get("created_at") or now_iso()
    document["timestamps"]["created_at"] = created_at
    document["timestamps"]["updated_at"] = now_iso()


def copy_json(data: Any) -> Any:
    return copy.deepcopy(data)


def feature_status_summary(contract: dict[str, Any], implementation: dict[str, Any]) -> dict[str, str]:
    status_by_feature: dict[str, str] = {}
    for feature in contract.get("features_planned", []):
        status_by_feature[feature["feature_id"]] = feature.get("status", "planned")
    for execution in implementation.get("features", []):
        status_by_feature[execution["feature_id"]] = execution.get("status", "in_progress")
    return status_by_feature


def build_holistic_rubric(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_success_statement_zh": contract.get("user_success_statement_zh", ""),
        "must_have_features": contract.get("must_have_features", []),
        "nice_to_have_features": contract.get("nice_to_have_features", []),
        "holistic_acceptance_criteria_zh": contract.get("holistic_acceptance_criteria_zh", []),
        "holistic_fail_conditions_zh": contract.get("holistic_fail_conditions_zh", []),
        "deferred_concerns_zh": contract.get("deferred_concerns_zh", []),
        "rejected_evaluator_requests": contract.get("rejected_evaluator_requests", []),
    }


def compute_feature_consensus(
    accepted_contract: dict[str, Any] | None,
    unresolved_points: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not accepted_contract:
        return []
    criteria_map = {
        item["feature_id"]: list(item.get("criteria_zh", []))
        for item in accepted_contract.get("acceptance_criteria", [])
    }
    result: list[dict[str, Any]] = []
    for feature in accepted_contract.get("features_planned", []):
        feature_id = feature["feature_id"]
        unresolved = [
            point for point in unresolved_points if point.get("target_id") == feature_id
        ]
        criteria = criteria_map.get(feature_id, [])
        passed = bool(criteria) and not unresolved
        result.append(
            {
                "feature_id": feature_id,
                "title_zh": feature.get("title_zh", feature_id),
                "pass": passed,
                "agreed_acceptance_criteria_zh": criteria,
                "unresolved_points_zh": [point.get("title_zh", "") for point in unresolved],
            }
        )
    return result


def compute_global_consensus(
    holistic_rubric: dict[str, Any],
    unresolved_points: list[dict[str, Any]],
) -> dict[str, Any]:
    unresolved_global = [
        point.get("title_zh", "")
        for point in unresolved_points
        if point.get("kind") == "global"
    ]
    required_fields = [
        "user_success_statement_zh",
        "must_have_features",
        "holistic_acceptance_criteria_zh",
        "holistic_fail_conditions_zh",
    ]
    missing: list[str] = []
    for field_name in required_fields:
        value = holistic_rubric.get(field_name)
        if value in ("", [], None):
            missing.append(field_name)
    return {
        "pass": not unresolved_global and not missing,
        "unresolved_points_zh": unresolved_global,
        "missing_fields": missing,
    }


def next_sprint_inheritance(previous_sprint: dict[str, Any]) -> dict[str, Any]:
    seed = previous_sprint["next_sprint_seed"]
    return {
        "from_sprint_number": previous_sprint["sprint_number"],
        "accepted_features_inherited": copy_json(seed.get("accepted_features_inherited", [])),
        "open_findings_inherited": copy_json(seed.get("open_findings", [])),
        "rejected_findings_inherited": copy_json(seed.get("rejected_findings", [])),
        "canonical_context": {
            "summary_zh": seed.get("canonical_context", ""),
            "artifact_index": [],
        },
    }


def relative_path(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()
