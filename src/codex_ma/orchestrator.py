from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Any, Callable
import json
import os
import re
import subprocess
import tempfile

from codex_ma.config import ProjectConfig
from codex_ma.constants import (
    OUTPUT_SCHEMAS,
    PHASE_AWAITING_HUMAN,
    PHASE_CONTRACT_ACCEPTED,
    PHASE_DONE,
    PHASE_HOLISTIC_REVIEW,
    PHASE_IMPLEMENTING,
    PHASE_INIT,
    PHASE_L1_VERIFY,
    PHASE_NEGOTIATE_EVALUATOR_RESEARCH,
    PHASE_NEGOTIATE_GENERATOR_RESEARCH,
    PHASE_NEGOTIATE_ROUND,
    PHASE_NEXT_SPRINT_PREP,
    PHASE_PARALLEL_REVIEW,
    PHASE_REVIEW_AGGREGATE,
    PHASE_REVIEW_PREP,
    ROLE_EVALUATOR,
    ROLE_GENERATOR,
    ROLE_REVIEWER,
    STATUS_ABORTED,
    STATUS_BLOCKED,
    STATUS_CARRY_FORWARD,
    STATUS_DONE,
    STATUS_IN_PROGRESS,
)
from codex_ma.prompts import build_prompt
from codex_ma.runner import BaseRunner, RunnerError, RunnerRequest, RunnerResult
from codex_ma.schema import load_schema, validate
from codex_ma.state import (
    build_holistic_rubric,
    build_initial_manifest,
    build_initial_sprint,
    compute_feature_consensus,
    compute_global_consensus,
    copy_json,
    feature_status_summary,
    make_task_id,
    next_sprint_inheritance,
    now_iso,
)
from codex_ma.storage import Storage


class TaskStopped(RuntimeError):
    pass


class WorkspaceViolation(RunnerError):
    pass


class Orchestrator:
    def __init__(
        self,
        root: Path,
        storage: Storage,
        runner: BaseRunner | None,
        config: ProjectConfig,
    ):
        self.root = root
        self.storage = storage
        self.runner = runner
        self.config = config
        self._state_lock = Lock()
        self._progress_func: Callable[[str], None] | None = None

    def init_workspace(self) -> list[str]:
        self.storage.ensure_layout()
        created = self.storage.ensure_default_files()
        config_path = self.root / "multiagent.toml"
        if not config_path.exists():
            from codex_ma.config import render_default_config

            config_path.write_text(render_default_config(), encoding="utf-8")
            created.append("multiagent.toml")
        return created

    def create_task(
        self,
        user_request: str,
        task_id: str | None = None,
        project_workspace: str | Path | None = None,
    ) -> dict[str, Any]:
        if project_workspace is None:
            raise ValueError("创建任务必须指定项目空间: --workspace <path>")
        self.storage.ensure_layout()
        existing = set(self.storage.list_task_ids())
        task_id = task_id or make_task_id(existing)
        if task_id in existing:
            raise ValueError(f"任务 {task_id} 已存在")
        workspace = self._resolve_project_workspace(project_workspace)
        workspace.mkdir(parents=True, exist_ok=True)
        manifest = build_initial_manifest(task_id, user_request, workspace.as_posix())
        manifest["review_queue_summary"]["max_concurrency"] = self.config.review.max_concurrency
        sprint = build_initial_sprint(task_id, user_request, sprint_number=1)
        self.storage.ensure_task_layout(task_id, sprint_number=1)
        self.storage.save_sprint(task_id, sprint)
        self.storage.save_manifest(task_id, manifest)
        self._append_event(
            task_id,
            sprint,
            "TASK_CREATED",
            "orchestrator",
            "任务已创建。",
            {"task_id": task_id},
        )
        return {"task_id": task_id, "manifest": manifest, "sprint": sprint}

    def _resolve_project_workspace(self, project_workspace: str | Path) -> Path:
        path = Path(project_workspace).expanduser()
        if not path.is_absolute():
            path = self.root / path
        resolved = path.resolve()
        root = self.root.resolve()
        if resolved == root or root.is_relative_to(resolved):
            raise ValueError("项目空间不能是 codex-ma 工具仓库本身或其父目录")
        return resolved

    def _project_workspace(self, manifest: dict[str, Any]) -> Path:
        workspace = manifest.get("project_workspace")
        if not workspace:
            raise ValueError("任务未绑定项目空间，不能运行；请使用 task create --workspace <path> 创建新任务")
        return Path(workspace).expanduser().resolve()

    def run(
        self,
        task_id: str,
        progress_func: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        if self.runner is None:
            raise RunnerError("当前命令需要 runner，但 runner 未初始化")
        previous_progress = self._progress_func
        if progress_func is not None:
            self._progress_func = progress_func
        try:
            while True:
                manifest, sprint = self._load_current(task_id)
                if manifest["status"] in (STATUS_DONE, STATUS_BLOCKED, STATUS_ABORTED):
                    return {"manifest": manifest, "sprint": sprint}
                phase = sprint["phase"]
                try:
                    if phase == PHASE_INIT:
                        self._transition(task_id, manifest, sprint, PHASE_NEGOTIATE_GENERATOR_RESEARCH, "准备进行 generator 调研。", "generator")
                    elif phase == PHASE_NEGOTIATE_GENERATOR_RESEARCH:
                        self._run_generator_research(task_id, manifest, sprint)
                    elif phase == PHASE_NEGOTIATE_EVALUATOR_RESEARCH:
                        self._run_evaluator_research(task_id, manifest, sprint)
                    elif phase == PHASE_NEGOTIATE_ROUND:
                        self._run_negotiation_round(task_id, manifest, sprint)
                    elif phase == PHASE_CONTRACT_ACCEPTED:
                        self._prepare_implementation(task_id, manifest, sprint)
                    elif phase == PHASE_IMPLEMENTING:
                        self._run_feature_execution(task_id, manifest, sprint)
                    elif phase == PHASE_L1_VERIFY:
                        self._run_l1_verify(task_id, manifest, sprint)
                    elif phase == PHASE_REVIEW_PREP:
                        self._prepare_reviews(task_id, manifest, sprint)
                    elif phase == PHASE_PARALLEL_REVIEW:
                        self._run_parallel_reviews(task_id, manifest, sprint)
                    elif phase == PHASE_REVIEW_AGGREGATE:
                        self._aggregate_reviews(task_id, manifest, sprint)
                    elif phase == PHASE_HOLISTIC_REVIEW:
                        self._run_holistic_review(task_id, manifest, sprint)
                    elif phase == PHASE_NEXT_SPRINT_PREP:
                        self._prepare_next_sprint(task_id, manifest, sprint)
                    elif phase == PHASE_AWAITING_HUMAN:
                        return {"manifest": manifest, "sprint": sprint}
                    elif phase == PHASE_DONE:
                        manifest["status"] = STATUS_DONE
                        self.storage.save_manifest(task_id, manifest)
                        return {"manifest": manifest, "sprint": sprint}
                    else:
                        raise ValueError(f"未知 phase: {phase}")
                except TaskStopped:
                    manifest, sprint = self._load_current(task_id)
                    return {"manifest": manifest, "sprint": sprint}
        finally:
            self._progress_func = previous_progress

    def resume(
        self,
        task_id: str,
        input_func: Callable[[str], str] = input,
        output_func: Callable[[str], None] = print,
        progress_func: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        manifest, sprint = self._load_current(task_id)
        if manifest["status"] in (STATUS_DONE, STATUS_BLOCKED, STATUS_ABORTED):
            return {"manifest": manifest, "sprint": sprint}
        if sprint["phase"] == PHASE_AWAITING_HUMAN:
            self._collect_human_input(task_id, manifest, sprint, input_func, output_func)
        return self.run(task_id, progress_func=progress_func)

    def stop(self, task_id: str, reason_zh: str = "用户请求停止任务。") -> dict[str, Any]:
        manifest, sprint = self._load_current(task_id)
        if manifest["status"] == STATUS_DONE:
            return {"manifest": manifest, "sprint": sprint}
        if manifest["status"] == STATUS_ABORTED:
            return {"manifest": manifest, "sprint": sprint}
        manifest["status"] = STATUS_ABORTED
        sprint["status"] = STATUS_ABORTED
        sprint["resume_from"] = {
            "phase": sprint["phase"],
            "pending_actor": None,
            "reason_zh": "任务已被 stop 指令停止；不会继续自动运行。",
        }
        manifest["resume_pointer"] = {
            "phase": sprint["phase"],
            "file": f"runs/{task_id}/sprint-{sprint['sprint_number']:03d}.json",
            "reason_zh": reason_zh,
        }
        manifest["human_gate"] = {
            "active": False,
            "reason_zh": "",
            "unresolved_points": [],
        }
        self._save_state(task_id, manifest, sprint)
        self._append_event(
            task_id,
            sprint,
            "TASK_STOPPED",
            "orchestrator",
            reason_zh,
            {"status": STATUS_ABORTED},
        )
        return {"manifest": manifest, "sprint": sprint}

    def status(self, task_id: str) -> dict[str, Any]:
        manifest, sprint = self._load_current(task_id)
        return {"manifest": manifest, "sprint": sprint}

    def events(self, task_id: str) -> list[dict[str, Any]]:
        return self.storage.read_events(task_id)

    def _emit_progress(self, title: str, lines: list[str] | None = None) -> None:
        if self._progress_func is None:
            return
        rendered = [f"\n== {title} =="]
        rendered.extend(line for line in (lines or []) if line)
        self._progress_func("\n".join(rendered))

    def _short_text(self, value: Any, limit: int = 180) -> str:
        text = str(value or "").strip().replace("\n", " ")
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"

    def _format_items(self, items: list[Any], limit: int = 5) -> str:
        if not items:
            return "无"
        rendered = [self._short_text(item, 80) for item in items[:limit]]
        suffix = "" if len(items) <= limit else f" 等 {len(items)} 项"
        return "；".join(rendered) + suffix

    def _feature_title(self, contract: dict[str, Any], feature_id: str) -> str:
        for feature in contract.get("features_planned", []):
            if feature.get("feature_id") == feature_id:
                title = feature.get("title_zh") or feature_id
                return f"{feature_id}（{title}）"
        return feature_id

    def _load_current(self, task_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        manifest = self.storage.load_manifest(task_id)
        sprint = self.storage.load_sprint(task_id, manifest["latest_sprint"])
        return manifest, sprint

    def _save_state(
        self,
        task_id: str,
        manifest: dict[str, Any],
        sprint: dict[str, Any],
    ) -> None:
        self._raise_if_stopped(task_id, manifest)
        manifest["latest_sprint"] = sprint["sprint_number"]
        manifest["latest_file"] = f"runs/{task_id}/sprint-{sprint['sprint_number']:03d}.json"
        manifest["current_phase"] = sprint["phase"]
        manifest["timestamps"]["updated_at"] = now_iso()
        self.storage.save_sprint(task_id, sprint)
        self.storage.save_manifest(task_id, manifest)

    def _raise_if_stopped(self, task_id: str, manifest: dict[str, Any]) -> None:
        if manifest.get("status") == STATUS_ABORTED:
            return
        current = self.storage.load_manifest(task_id)
        if current.get("status") == STATUS_ABORTED:
            raise TaskStopped

    def _workspace_run_dir(self, manifest: dict[str, Any], task_id: str) -> Path:
        return self._project_workspace(manifest) / ".codex-ma" / "runs" / task_id

    def _workspace_artifact_file(
        self,
        task_id: str,
        manifest: dict[str, Any],
        sprint: dict[str, Any],
        filename: str,
    ) -> Path:
        path = (
            self._workspace_run_dir(manifest, task_id)
            / "artifacts"
            / f"sprint-{sprint['sprint_number']:03d}"
            / filename
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _workspace_relative(self, manifest: dict[str, Any], path: Path) -> str:
        try:
            return path.relative_to(self._project_workspace(manifest)).as_posix()
        except ValueError:
            return path.as_posix()

    def _workspace_schema_file(self, manifest: dict[str, Any], schema_key: str) -> Path:
        source = self.root / OUTPUT_SCHEMAS[schema_key]
        workspace = self._project_workspace(manifest)
        target = workspace / ".codex-ma" / OUTPUT_SCHEMAS[schema_key]
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() == source.read_bytes():
            return target
        with tempfile.NamedTemporaryFile("wb", dir=target.parent, delete=False) as handle:
            handle.write(source.read_bytes())
            temp_name = handle.name
        os.replace(temp_name, target)
        return target

    def _assert_payload_within_workspace(self, manifest: dict[str, Any], payload: dict[str, Any]) -> None:
        workspace = self._project_workspace(manifest)
        for raw_path in payload.get("changed_files", []):
            path = Path(raw_path).expanduser()
            resolved = path.resolve() if path.is_absolute() else (workspace / path).resolve()
            if resolved == workspace or workspace in resolved.parents:
                continue
            raise WorkspaceViolation(f"changed_files 包含项目空间外路径: {raw_path}")

    def _transition(
        self,
        task_id: str,
        manifest: dict[str, Any],
        sprint: dict[str, Any],
        next_phase: str,
        reason_zh: str,
        pending_actor: str | None,
    ) -> None:
        sprint["phase"] = next_phase
        sprint["resume_from"] = {
            "phase": next_phase,
            "pending_actor": pending_actor,
            "reason_zh": reason_zh,
        }
        manifest["current_phase"] = next_phase
        manifest["resume_pointer"] = {
            "phase": next_phase,
            "file": f"runs/{task_id}/sprint-{sprint['sprint_number']:03d}.json",
            "reason_zh": reason_zh,
        }
        self._save_state(task_id, manifest, sprint)
        self._append_event(
            task_id,
            sprint,
            "PHASE_TRANSITION",
            "orchestrator",
            reason_zh,
            {"next_phase": next_phase},
        )

    def _append_event(
        self,
        task_id: str,
        sprint: dict[str, Any],
        event_type: str,
        actor: str,
        summary_zh: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        event = {
            "timestamp": now_iso(),
            "task_id": task_id,
            "sprint_id": sprint["sprint_id"],
            "phase": sprint["phase"],
            "event_type": event_type,
            "actor": actor,
            "summary_zh": summary_zh,
            "details": details or {},
        }
        self.storage.append_event(task_id, event)

    def _invoke_agent(
        self,
        *,
        task_id: str,
        manifest: dict[str, Any],
        sprint: dict[str, Any],
        role: str,
        phase: str,
        action: str,
        schema_key: str,
        logical_session: str,
        artifact_name: str,
        context: dict[str, Any],
        scope: str,
        notes_zh: str,
    ) -> RunnerResult:
        workspace = self._project_workspace(manifest)
        schema_path = self._workspace_schema_file(manifest, schema_key)
        validation_schema_path = self.root / OUTPUT_SCHEMAS[schema_key]
        output_path = self._workspace_artifact_file(
            task_id,
            manifest,
            sprint,
            artifact_name,
        )
        prompt = build_prompt(
            role,
            action,
            {
                "workspace_policy": {
                    "project_workspace": workspace.as_posix(),
                    "scope_zh": "你只能在 project_workspace 内观察、创建和修改文件；不要读取、引用或修改其父目录或兄弟目录。",
                    "state_dir_zh": "内部运行产物保存在 project_workspace/.codex-ma 下。",
                    "readme_policy_zh": "project_workspace 内的 README.md / README.markdown 属于项目文件，可以按任务需要修改；project_workspace 外的 README 或其它文件都不属于你的工作范围。",
                },
                **context,
            },
        )
        session_info = manifest["agent_sessions"].get(logical_session, {})
        request = RunnerRequest(
            role=role,
            phase=phase,
            action=action,
            prompt=prompt,
            schema_path=schema_path,
            output_path=output_path,
            cwd=workspace,
            profile=self.config.profiles[role],
            logical_session=logical_session,
            session_id=session_info.get("session_id"),
        )
        result = self.runner.run(request)
        self._raise_if_stopped(task_id, manifest)
        validate(result.payload, load_schema(validation_schema_path))
        self._assert_payload_within_workspace(manifest, result.payload)
        with self._state_lock:
            manifest["agent_sessions"][logical_session] = {
                "role": role,
                "profile": self.config.profiles[role],
                "session_id": result.session_id,
                "scope": scope,
                "last_used_at": now_iso(),
                "notes_zh": notes_zh,
            }
            self._append_event(
                task_id,
                sprint,
                "AGENT_CALL_COMPLETED",
                role,
                f"{role} 完成 {action}。",
                {
                    "action": action,
                    "logical_session": logical_session,
                    "artifact": self._workspace_relative(manifest, output_path),
                    "command": result.command,
                },
            )
        return result

    def _run_generator_research(
        self,
        task_id: str,
        manifest: dict[str, Any],
        sprint: dict[str, Any],
    ) -> None:
        result = self._invoke_agent(
            task_id=task_id,
            manifest=manifest,
            sprint=sprint,
            role=ROLE_GENERATOR,
            phase=sprint["phase"],
            action="GENERATOR_RESEARCH",
            schema_key="contract_proposal",
            logical_session="generator_contract",
            artifact_name="generator-research.json",
            context={
                "user_request": sprint["user_request"],
                "inheritance": sprint["inheritance"],
            },
            scope="contract",
            notes_zh="负责合同调研与提案。",
        )
        sprint["contract"]["generator_research"] = result.payload
        self._emit_progress(
            "Generator 调研完成",
            [
                f"摘要: {self._short_text(result.payload.get('summary_zh'))}",
                "计划 features: "
                + self._format_items(
                    [
                        f"{item.get('feature_id')} / {item.get('title_zh')}"
                        for item in result.payload.get("features_planned", [])
                    ]
                ),
                "主要风险: " + self._format_items(result.payload.get("risks_zh", []), limit=3),
            ],
        )
        self._save_state(task_id, manifest, sprint)
        self._transition(
            task_id,
            manifest,
            sprint,
            PHASE_NEGOTIATE_EVALUATOR_RESEARCH,
            "generator 调研完成，等待 evaluator 独立调研。",
            "evaluator",
        )

    def _run_evaluator_research(
        self,
        task_id: str,
        manifest: dict[str, Any],
        sprint: dict[str, Any],
    ) -> None:
        result = self._invoke_agent(
            task_id=task_id,
            manifest=manifest,
            sprint=sprint,
            role=ROLE_EVALUATOR,
            phase=sprint["phase"],
            action="EVALUATOR_RESEARCH",
            schema_key="contract_feedback",
            logical_session="evaluator_contract",
            artifact_name="evaluator-research.json",
            context={
                "user_request": sprint["user_request"],
                "inheritance": sprint["inheritance"],
                "generator_research": sprint["contract"]["generator_research"],
            },
            scope="contract",
            notes_zh="负责合同调研、协商与 holistic 审批。",
        )
        sprint["contract"]["evaluator_research"] = result.payload
        self._emit_progress(
            "Evaluator 调研完成",
            [
                f"结论: {'通过' if result.payload.get('pass') else '需协商'}",
                f"摘要: {self._short_text(result.payload.get('summary_zh'))}",
                "关注点: " + self._format_items(result.payload.get("issues_zh", []), limit=3),
            ],
        )
        self._save_state(task_id, manifest, sprint)
        self._transition(
            task_id,
            manifest,
            sprint,
            PHASE_NEGOTIATE_ROUND,
            "双方独立调研完成，进入 negotiate。",
            "generator",
        )

    def _run_negotiation_round(
        self,
        task_id: str,
        manifest: dict[str, Any],
        sprint: dict[str, Any],
    ) -> None:
        contract = sprint["contract"]
        rounds = contract["negotiation_rounds"]
        round_number = len(rounds) + 1
        has_human_decisions = bool(contract["human_intervention"]["decisions"])
        if round_number > self.config.negotiation.max_rounds and not has_human_decisions:
            self._enter_human_gate(task_id, manifest, sprint, contract.get("unresolved_points", []))
            return
        generator_context = {
            "user_request": sprint["user_request"],
            "inheritance": sprint["inheritance"],
            "generator_research": contract["generator_research"],
            "evaluator_research": contract["evaluator_research"],
            "previous_rounds": rounds,
            "human_intervention": contract["human_intervention"],
        }
        proposal = self._invoke_agent(
            task_id=task_id,
            manifest=manifest,
            sprint=sprint,
            role=ROLE_GENERATOR,
            phase=sprint["phase"],
            action="GENERATOR_PROPOSAL",
            schema_key="contract_proposal",
            logical_session="generator_contract",
            artifact_name=f"round-{round_number:03d}-generator-proposal.json",
            context=generator_context,
            scope="contract",
            notes_zh="负责合同调研与提案。",
        ).payload
        feedback = self._invoke_agent(
            task_id=task_id,
            manifest=manifest,
            sprint=sprint,
            role=ROLE_EVALUATOR,
            phase=sprint["phase"],
            action="EVALUATOR_FEEDBACK",
            schema_key="contract_feedback",
            logical_session="evaluator_contract",
            artifact_name=f"round-{round_number:03d}-evaluator-feedback.json",
            context={
                **generator_context,
                "generator_proposal": proposal,
            },
            scope="contract",
            notes_zh="负责合同调研、协商与 holistic 审批。",
        ).payload
        resolution = self._invoke_agent(
            task_id=task_id,
            manifest=manifest,
            sprint=sprint,
            role=ROLE_GENERATOR,
            phase=sprint["phase"],
            action="GENERATOR_ARGUE_BACK",
            schema_key="contract_resolution",
            logical_session="generator_contract",
            artifact_name=f"round-{round_number:03d}-generator-resolution.json",
            context={
                **generator_context,
                "generator_proposal": proposal,
                "evaluator_feedback": feedback,
            },
            scope="contract",
            notes_zh="负责合同调研与提案。",
        ).payload
        evaluator_resolution = self._invoke_agent(
            task_id=task_id,
            manifest=manifest,
            sprint=sprint,
            role=ROLE_EVALUATOR,
            phase=sprint["phase"],
            action="EVALUATOR_RESOLUTION",
            schema_key="contract_feedback",
            logical_session="evaluator_contract",
            artifact_name=f"round-{round_number:03d}-evaluator-resolution.json",
            context={
                **generator_context,
                "generator_proposal": proposal,
                "evaluator_feedback": feedback,
                "generator_resolution": resolution,
            },
            scope="contract",
            notes_zh="负责合同调研、协商与 holistic 审批。",
        ).payload
        resolved_contract = resolution["resolved_contract"]
        unresolved_points = resolution.get("unresolved_points", [])
        holistic_rubric = build_holistic_rubric(resolved_contract)
        feature_consensus = compute_feature_consensus(resolved_contract, unresolved_points)
        global_consensus = compute_global_consensus(holistic_rubric, unresolved_points)
        round_state = {
            "round_number": round_number,
            "generator_proposal": proposal,
            "evaluator_feedback": feedback,
            "generator_argue_back": resolution,
            "evaluator_resolution": evaluator_resolution,
            "round_status": "passed"
            if evaluator_resolution["pass"] and all(item["pass"] for item in feature_consensus) and global_consensus["pass"]
            else "needs_followup",
        }
        rounds.append(round_state)
        contract["holistic_rubric"] = holistic_rubric
        contract["feature_consensus"] = feature_consensus
        contract["global_consensus"] = global_consensus
        contract["unresolved_points"] = unresolved_points
        self._emit_progress(
            f"Negotiate 第 {round_number} 轮完成",
            [
                f"状态: {round_state['round_status']}",
                f"Generator 修订: {self._short_text(resolution.get('summary_zh'))}",
                f"Evaluator 结论: {'通过' if evaluator_resolution.get('pass') else '未通过'} - {self._short_text(evaluator_resolution.get('summary_zh'))}",
                "未决点: "
                + self._format_items(
                    [item.get("title_zh", item.get("point_id", "")) for item in unresolved_points],
                    limit=4,
                ),
            ],
        )
        if (
            evaluator_resolution["pass"]
            and all(item["pass"] for item in feature_consensus)
            and global_consensus["pass"]
            and not unresolved_points
        ):
            contract["accepted_contract"] = resolved_contract
            contract["human_intervention"]["required"] = False
            contract["human_intervention"]["reason_zh"] = ""
            manifest["human_gate"] = {
                "active": False,
                "reason_zh": "",
                "unresolved_points": [],
            }
            self._save_state(task_id, manifest, sprint)
            self._emit_progress(
                "合同已接受",
                [
                    f"合同摘要: {self._short_text(resolved_contract.get('summary_zh'))}",
                    "本轮 features: "
                    + self._format_items(
                        [
                            f"{item.get('feature_id')} / {item.get('title_zh')}"
                            for item in resolved_contract.get("features_planned", [])
                        ],
                        limit=8,
                    ),
                    "全局验收: "
                    + self._format_items(
                        resolved_contract.get("holistic_acceptance_criteria_zh", []),
                        limit=3,
                    ),
                ],
            )
            self._transition(
                task_id,
                manifest,
                sprint,
                PHASE_CONTRACT_ACCEPTED,
                "合同已达成一致，进入实现准备。",
                "orchestrator",
            )
            return
        self._save_state(task_id, manifest, sprint)
        if round_number >= self.config.negotiation.max_rounds and not has_human_decisions:
            self._enter_human_gate(task_id, manifest, sprint, unresolved_points)
            return
        if has_human_decisions:
            sprint["status"] = STATUS_BLOCKED
            manifest["status"] = STATUS_BLOCKED
            manifest["human_gate"] = {
                "active": True,
                "reason_zh": "人工介入后协商仍未收敛，需要人工重新定义任务边界。",
                "unresolved_points": unresolved_points,
            }
            self._save_state(task_id, manifest, sprint)
            self._emit_progress(
                "任务阻塞",
                [
                    "原因: 人工介入后协商仍未收敛。",
                    "未决点: "
                    + self._format_items(
                        [item.get("title_zh", item.get("point_id", "")) for item in unresolved_points],
                        limit=5,
                    ),
                ],
            )
            self._append_event(
                task_id,
                sprint,
                "TASK_BLOCKED",
                "orchestrator",
                "人工介入后协商仍未收敛，任务阻塞。",
                {"round_number": round_number},
            )
            return
        self._transition(
            task_id,
            manifest,
            sprint,
            PHASE_NEGOTIATE_ROUND,
            f"第 {round_number} 轮协商仍有分歧，继续下一轮。",
            "generator",
        )

    def _enter_human_gate(
        self,
        task_id: str,
        manifest: dict[str, Any],
        sprint: dict[str, Any],
        unresolved_points: list[dict[str, Any]],
    ) -> None:
        sprint["contract"]["human_intervention"]["required"] = True
        sprint["contract"]["human_intervention"]["reason_zh"] = "协商轮次达到上限，等待人工裁决。"
        sprint["phase"] = PHASE_AWAITING_HUMAN
        sprint["resume_from"] = {
            "phase": PHASE_AWAITING_HUMAN,
            "pending_actor": "human",
            "reason_zh": "请处理未决分歧后继续。",
        }
        manifest["current_phase"] = PHASE_AWAITING_HUMAN
        manifest["resume_pointer"] = {
            "phase": PHASE_AWAITING_HUMAN,
            "file": f"runs/{task_id}/sprint-{sprint['sprint_number']:03d}.json",
            "reason_zh": "等待人工裁决未决分歧。",
        }
        manifest["human_gate"] = {
            "active": True,
            "reason_zh": "协商轮次达到上限，等待人工裁决。",
            "unresolved_points": unresolved_points,
        }
        self._save_state(task_id, manifest, sprint)
        self._append_event(
            task_id,
            sprint,
            "HUMAN_GATE_OPENED",
            "orchestrator",
            "协商未收敛，已打开人工裁决入口。",
            {"unresolved_points": unresolved_points},
        )
        self._emit_progress(
            "等待人工裁决",
            [
                "原因: 协商轮次达到上限。",
                "未决点: "
                + self._format_items(
                    [item.get("title_zh", item.get("point_id", "")) for item in unresolved_points],
                    limit=5,
                ),
            ],
        )

    def _collect_human_input(
        self,
        task_id: str,
        manifest: dict[str, Any],
        sprint: dict[str, Any],
        input_func: Callable[[str], str],
        output_func: Callable[[str], None],
    ) -> None:
        unresolved_points = sprint["contract"].get("unresolved_points", [])
        decisions: list[dict[str, Any]] = []
        output_func("检测到未决分歧，请为每个点选择处理方式。")
        for point in unresolved_points:
            output_func(f"\n[{point.get('point_id', 'unknown')}] {point.get('title_zh', '未命名分歧')}")
            output_func(f"Generator: {point.get('generator_position_zh', '未提供')}")
            output_func(f"Evaluator: {point.get('evaluator_position_zh', '未提供')}")
            choice = input_func("选择 [g=采纳 Generator / e=采纳 Evaluator / c=自定义]: ").strip().lower()
            while choice not in {"g", "e", "c"}:
                choice = input_func("请输入 g / e / c: ").strip().lower()
            decision = {"point_id": point.get("point_id"), "choice": choice}
            if choice == "c":
                decision["note_zh"] = input_func("请输入自定义裁决说明: ").strip()
            else:
                decision["note_zh"] = input_func("可选：补充裁决说明（回车跳过）: ").strip()
            decisions.append(decision)
        sprint["contract"]["human_intervention"] = {
            "required": False,
            "reason_zh": "",
            "decisions": decisions,
        }
        manifest["human_gate"] = {
            "active": False,
            "reason_zh": "",
            "unresolved_points": [],
        }
        self._save_state(task_id, manifest, sprint)
        self._append_event(
            task_id,
            sprint,
            "HUMAN_GATE_RESOLVED",
            "human",
            "人工裁决已记录，将继续 negotiate。",
            {"decisions": decisions},
        )
        self._transition(
            task_id,
            manifest,
            sprint,
            PHASE_NEGOTIATE_ROUND,
            "人工裁决已写入，继续最后一轮协商。",
            "generator",
        )

    def _prepare_implementation(
        self,
        task_id: str,
        manifest: dict[str, Any],
        sprint: dict[str, Any],
    ) -> None:
        accepted_contract = sprint["contract"]["accepted_contract"]
        if not sprint["implementation"]["feature_queue"]:
            sprint["implementation"]["feature_queue"] = [
                feature["feature_id"] for feature in accepted_contract["features_planned"]
            ]
        self._save_state(task_id, manifest, sprint)
        self._emit_progress(
            "实现队列已准备",
            [
                "队列: "
                + self._format_items(
                    [
                        self._feature_title(accepted_contract, feature_id)
                        for feature_id in sprint["implementation"]["feature_queue"]
                    ],
                    limit=10,
                )
            ],
        )
        self._transition(
            task_id,
            manifest,
            sprint,
            PHASE_IMPLEMENTING,
            "已准备 feature 队列，开始实现。",
            "generator",
        )

    def _run_feature_execution(
        self,
        task_id: str,
        manifest: dict[str, Any],
        sprint: dict[str, Any],
    ) -> None:
        implementation = sprint["implementation"]
        accepted_contract = sprint["contract"]["accepted_contract"]
        if implementation["current_feature_id"] is None:
            if not implementation["feature_queue"]:
                self._emit_progress(
                    "Feature 实现完成",
                    [
                        f"已完成 features: {len(implementation['features'])}",
                        "下一步: 准备 review。",
                    ],
                )
                self._transition(
                    task_id,
                    manifest,
                    sprint,
                    PHASE_REVIEW_PREP,
                    "所有 feature 已完成实现，准备 review。",
                    "orchestrator",
                )
                return
            implementation["current_feature_id"] = implementation["feature_queue"].pop(0)
        feature_id = implementation["current_feature_id"]
        feature_spec = next(
            feature
            for feature in accepted_contract["features_planned"]
            if feature["feature_id"] == feature_id
        )
        previous_attempts = [
            item for item in implementation["features"] if item["feature_id"] == feature_id
        ]
        action = "FEATURE_EXECUTION"
        result = self._invoke_agent(
            task_id=task_id,
            manifest=manifest,
            sprint=sprint,
            role=ROLE_GENERATOR,
            phase=sprint["phase"],
            action=action,
            schema_key="feature_execution",
            logical_session=f"generator_feature_{feature_id}",
            artifact_name=f"{feature_id}-attempt-{len(previous_attempts)+1:03d}.json",
            context={
                "user_request": sprint["user_request"],
                "accepted_contract": accepted_contract,
                "feature": feature_spec,
                "previous_attempts": previous_attempts,
                "l1_checks": implementation["l1_checks"],
            },
            scope=f"feature:{feature_id}",
            notes_zh=f"负责 {feature_id} 的实现与修复。",
        )
        payload = result.payload
        payload["feature_id"] = feature_id
        payload["attempts"] = len(previous_attempts) + 1
        self._upsert_feature_result(implementation, payload)
        for path in payload.get("changed_files", []):
            if path not in implementation["changed_files"]:
                implementation["changed_files"].append(path)
        self._save_state(task_id, manifest, sprint)
        self._emit_progress(
            f"Feature 执行完成: {self._feature_title(accepted_contract, feature_id)}",
            [
                f"尝试次数: {payload['attempts']}",
                f"状态: {payload.get('status', 'unknown')}",
                f"摘要: {self._short_text(payload.get('execution_summary_zh') or payload.get('summary_zh'))}",
                "变更文件: " + self._format_items(payload.get("changed_files", []), limit=8),
                "阻塞: " + self._format_items(payload.get("blockers_zh", []), limit=3),
            ],
        )
        self._transition(
            task_id,
            manifest,
            sprint,
            PHASE_L1_VERIFY,
            f"{feature_id} 已执行，进入 L1 检查。",
            "orchestrator",
        )

    def _upsert_feature_result(self, implementation: dict[str, Any], payload: dict[str, Any]) -> None:
        features = implementation["features"]
        for index, current in enumerate(features):
            if current["feature_id"] == payload["feature_id"]:
                features[index] = payload
                return
        features.append(payload)

    def _run_l1_verify(
        self,
        task_id: str,
        manifest: dict[str, Any],
        sprint: dict[str, Any],
    ) -> None:
        implementation = sprint["implementation"]
        feature_id = implementation["current_feature_id"]
        if not feature_id:
            raise ValueError("L1_VERIFY 缺少 current_feature_id")
        accepted_contract = sprint["contract"]["accepted_contract"]
        execution = next(
            item for item in implementation["features"] if item["feature_id"] == feature_id
        )
        checks = accepted_contract.get("l1_checks", [])
        results: list[dict[str, Any]] = []
        for check in checks:
            check_result = self._run_check(check, feature_id, self._project_workspace(manifest))
            results.append(check_result)
        implementation["l1_checks"] = [
            item for item in implementation["l1_checks"] if item.get("feature_id") != feature_id
        ] + results
        all_passed = all(result["pass"] for result in results if result.get("required", True))
        if all_passed:
            execution["status"] = "passed"
            implementation["current_feature_id"] = None
            self._save_state(task_id, manifest, sprint)
            self._emit_progress(
                f"L1 检查通过: {self._feature_title(accepted_contract, feature_id)}",
                [
                    "检查: "
                    + self._format_items(
                        [
                            f"{item.get('check_id')}={'PASS' if item.get('pass') else 'FAIL'}"
                            for item in results
                        ],
                        limit=8,
                    ),
                    "下一步: 进入下一个 feature。",
                ],
            )
            self._transition(
                task_id,
                manifest,
                sprint,
                PHASE_IMPLEMENTING,
                f"{feature_id} 的 L1 检查通过。",
                "generator",
            )
            return
        if execution.get("attempts", 0) >= self.config.implementation.l1_retry_limit or execution.get("status") == "blocked":
            execution["status"] = "blocked"
            sprint["status"] = STATUS_BLOCKED
            manifest["status"] = STATUS_BLOCKED
            self._save_state(task_id, manifest, sprint)
            self._emit_progress(
                f"L1 检查阻塞: {self._feature_title(accepted_contract, feature_id)}",
                [
                    "失败检查: "
                    + self._format_items(
                        [
                            f"{item.get('check_id')}: {self._short_text(item.get('evidence_zh'), 90)}"
                            for item in results
                            if not item.get("pass")
                        ],
                        limit=5,
                    ),
                    "下一步: 任务 blocked，需要人工处理。",
                ],
            )
            self._append_event(
                task_id,
                sprint,
                "TASK_BLOCKED",
                "orchestrator",
                f"{feature_id} 的 L1 检查未通过且已达到重试上限。",
                {"feature_id": feature_id, "results": results},
            )
            return
        execution["status"] = "l1_failed"
        self._save_state(task_id, manifest, sprint)
        self._emit_progress(
            f"L1 检查失败，返工: {self._feature_title(accepted_contract, feature_id)}",
            [
                "失败检查: "
                + self._format_items(
                    [
                        f"{item.get('check_id')}: {self._short_text(item.get('evidence_zh'), 90)}"
                        for item in results
                        if not item.get("pass")
                    ],
                    limit=5,
                ),
                "下一步: 回到 generator 修复。",
            ],
        )
        self._transition(
            task_id,
            manifest,
            sprint,
            PHASE_IMPLEMENTING,
            f"{feature_id} 的 L1 检查失败，回到 generator 修复。",
            "generator",
        )

    def _run_check(self, check: dict[str, Any], feature_id: str, workspace: Path) -> dict[str, Any]:
        command = check["command"]
        if not self._looks_like_shell_command(command):
            return self._run_builtin_l1_check(check, feature_id, workspace)
        try:
            proc = subprocess.run(
                command,
                cwd=workspace,
                text=True,
                capture_output=True,
                shell=True,
                timeout=self.config.implementation.check_timeout_seconds,
            )
            passed = proc.returncode == 0
            evidence = (proc.stdout + proc.stderr).strip()[:4000]
            if not evidence:
                evidence = f"exit_code={proc.returncode}"
        except subprocess.TimeoutExpired:
            passed = False
            evidence = "L1 检查超时。"
        return {
            "feature_id": feature_id,
            "check_id": check["check_id"],
            "name_zh": check["name_zh"],
            "command": command,
            "required": check.get("required", True),
            "pass": passed,
            "evidence_zh": evidence,
        }

    def _looks_like_shell_command(self, command: str) -> bool:
        if not command or re.search(r"[\u4e00-\u9fff]", command):
            return False
        first_token = command.strip().split()[0]
        if first_token.startswith(("./", "/", "python", "node", "npm", "npx")):
            return True
        return first_token in {
            "bash",
            "sh",
            "pytest",
            "unittest",
            "true",
            "test",
            "rg",
            "grep",
            "find",
            "ls",
        }

    def _run_builtin_l1_check(self, check: dict[str, Any], feature_id: str, workspace: Path) -> dict[str, Any]:
        html_files = sorted(workspace.glob("*.html")) + sorted((workspace / "public").glob("*.html"))
        if not html_files:
            return {
                "feature_id": feature_id,
                "check_id": check["check_id"],
                "name_zh": check["name_zh"],
                "command": check["command"],
                "required": check.get("required", True),
                "pass": False,
                "evidence_zh": "L1 command 不是可执行 shell 命令，且未找到可用于静态冒烟检查的 HTML 文件。",
            }
        target = html_files[0]
        text = target.read_text(encoding="utf-8", errors="ignore").lower()
        checks = {
            "html": "<html" in text,
            "style": "<style" in text or ".css" in text,
            "script": "<script" in text or ".js" in text,
            "game_surface": "canvas" in text or "board" in text,
            "score": "score" in text or "分数" in text,
            "restart": "restart" in text or "重新" in text,
            "controls": "keydown" in text or "wasd" in text or "方向键" in text,
        }
        passed = all(checks.values())
        evidence = (
            f"内置静态网页冒烟检查: {target.name}; "
            + ", ".join(f"{name}={'OK' if ok else 'MISS'}" for name, ok in checks.items())
            + "。原 L1 command 不是可执行 shell 命令，已按网页任务降级为静态检查。"
        )
        return {
            "feature_id": feature_id,
            "check_id": check["check_id"],
            "name_zh": check["name_zh"],
            "command": check["command"],
            "required": check.get("required", True),
            "pass": passed,
            "evidence_zh": evidence,
        }

    def _prepare_reviews(
        self,
        task_id: str,
        manifest: dict[str, Any],
        sprint: dict[str, Any],
    ) -> None:
        accepted_contract = sprint["contract"]["accepted_contract"]
        review_jobs: list[dict[str, Any]] = []
        for feature in accepted_contract["features_planned"]:
            review_jobs.append(
                {
                    "review_id": f"feature-{feature['feature_id']}",
                    "scope_type": "feature",
                    "scope_id": feature["feature_id"],
                    "status": "queued",
                }
            )
        for dimension in accepted_contract.get("review_dimensions", self.config.review.dimensions):
            review_jobs.append(
                {
                    "review_id": f"dimension-{dimension}",
                    "scope_type": "dimension",
                    "scope_id": dimension,
                    "status": "queued",
                }
            )
        sprint["reviews"]["review_jobs"] = review_jobs
        manifest["review_queue_summary"] = {
            "queued": len(review_jobs),
            "running": 0,
            "completed": 0,
            "max_concurrency": self.config.review.max_concurrency,
        }
        self._save_state(task_id, manifest, sprint)
        self._emit_progress(
            "Review 队列已生成",
            [
                f"任务数: {len(review_jobs)}",
                "队列: "
                + self._format_items(
                    [
                        f"{job['scope_type']}:{job['scope_id']}"
                        for job in review_jobs
                    ],
                    limit=10,
                ),
            ],
        )
        self._transition(
            task_id,
            manifest,
            sprint,
            PHASE_PARALLEL_REVIEW,
            "Review 任务已生成，开始并行执行。",
            "reviewer",
        )

    def _run_parallel_reviews(
        self,
        task_id: str,
        manifest: dict[str, Any],
        sprint: dict[str, Any],
    ) -> None:
        jobs = sprint["reviews"]["review_jobs"]
        queued_jobs = [job for job in jobs if job["status"] == "queued"]
        if not queued_jobs:
            self._transition(
                task_id,
                manifest,
                sprint,
                PHASE_REVIEW_AGGREGATE,
                "Review 任务已全部完成，进入聚合。",
                "orchestrator",
            )
            return
        manifest["review_queue_summary"]["running"] = min(
            len(queued_jobs), self.config.review.max_concurrency
        )
        self._save_state(task_id, manifest, sprint)
        results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=self.config.review.max_concurrency) as pool:
            future_map = {
                pool.submit(self._execute_review_job, task_id, manifest, sprint, job): job
                for job in queued_jobs
            }
            for future in as_completed(future_map):
                job = future_map[future]
                verdict = future.result()
                results.append(verdict)
                job["status"] = "completed"
                manifest["review_queue_summary"]["completed"] += 1
                self._emit_progress(
                    f"Review 完成: {job['scope_type']}:{job['scope_id']}",
                    [
                        f"结论: {'通过' if verdict.get('pass') else '未通过'}",
                        f"摘要: {self._short_text(verdict.get('summary_zh'))}",
                        "Findings: "
                        + self._format_items(
                            [
                                finding.get("summary_zh", finding.get("finding_id", ""))
                                for finding in verdict.get("findings", [])
                            ],
                            limit=3,
                        ),
                    ],
                )
        sprint["reviews"]["feature_reviews"] = [
            item for item in results if item["scope_type"] == "feature"
        ]
        sprint["reviews"]["dimension_reviews"] = [
            item for item in results if item["scope_type"] == "dimension"
        ]
        manifest["review_queue_summary"]["queued"] = 0
        manifest["review_queue_summary"]["running"] = 0
        self._save_state(task_id, manifest, sprint)
        self._emit_progress(
            "Review 执行完成",
            [
                f"完成数: {len(results)}",
                f"通过数: {sum(1 for item in results if item.get('pass'))}",
                f"未通过数: {sum(1 for item in results if not item.get('pass'))}",
            ],
        )
        self._transition(
            task_id,
            manifest,
            sprint,
            PHASE_REVIEW_AGGREGATE,
            "Review verdict 已收集完成。",
            "orchestrator",
        )

    def _execute_review_job(
        self,
        task_id: str,
        manifest: dict[str, Any],
        sprint: dict[str, Any],
        job: dict[str, Any],
    ) -> dict[str, Any]:
        action = "FEATURE_REVIEW" if job["scope_type"] == "feature" else "DIMENSION_REVIEW"
        result = self._invoke_agent(
            task_id=task_id,
            manifest=manifest,
            sprint=sprint,
            role=ROLE_REVIEWER,
            phase=sprint["phase"],
            action=action,
            schema_key="review_verdict",
            logical_session=f"reviewer_{job['scope_type']}_{job['scope_id']}",
            artifact_name=f"{job['review_id']}.json",
            context={
                "user_request": sprint["user_request"],
                "accepted_contract": sprint["contract"]["accepted_contract"],
                "implementation": sprint["implementation"],
                "job": job,
            },
            scope=f"{job['scope_type']}:{job['scope_id']}",
            notes_zh=f"负责 {job['scope_type']}:{job['scope_id']} 的只读审查。",
        )
        return result.payload

    def _aggregate_reviews(
        self,
        task_id: str,
        manifest: dict[str, Any],
        sprint: dict[str, Any],
    ) -> None:
        verdicts = sprint["reviews"]["feature_reviews"] + sprint["reviews"]["dimension_reviews"]
        open_findings: list[dict[str, Any]] = []
        all_passed = True
        for verdict in verdicts:
            if not verdict["pass"]:
                all_passed = False
            for finding in verdict.get("findings", []):
                merged = copy_json(finding)
                merged["scope_type"] = verdict["scope_type"]
                merged["scope_id"] = verdict["scope_id"]
                open_findings.append(merged)
        sprint["reviews"]["aggregate"] = {
            "all_required_passed": all_passed,
            "open_findings": open_findings,
        }
        self._save_state(task_id, manifest, sprint)
        if all_passed:
            self._emit_progress(
                "Review 聚合通过",
                [
                    "结论: 所有必需 review 均通过。",
                    "下一步: 进入 holistic review。",
                ],
            )
            self._transition(
                task_id,
                manifest,
                sprint,
                PHASE_HOLISTIC_REVIEW,
                "机械 review 全部通过，进入 holistic review。",
                "evaluator",
            )
            return
        sprint["holistic_review"] = {
            "pass": False,
            "summary_zh": "机械 review 未全部通过，跳过 holistic review。",
            "satisfaction_gaps_zh": ["存在 review finding 未解决。"],
            "carry_forward_required": sorted({item["scope_id"] for item in open_findings}),
            "rejected_review_findings": [],
            "decision_basis": {
                "unmet_acceptance_criteria_zh": [],
                "triggered_fail_conditions_zh": [],
                "emergent_blockers": [],
            },
        }
        self._save_state(task_id, manifest, sprint)
        self._emit_progress(
            "Review 聚合未通过，准备返工",
            [
                f"Open findings: {len(open_findings)}",
                "建议: "
                + self._format_items(
                    [
                        item.get("suggested_fix_zh") or item.get("summary_zh", "")
                        for item in open_findings
                    ],
                    limit=5,
                ),
                "下一步: 创建下一轮 Sprint。",
            ],
        )
        self._transition(
            task_id,
            manifest,
            sprint,
            PHASE_NEXT_SPRINT_PREP,
            "存在 review finding，准备创建下一轮 Sprint。",
            "orchestrator",
        )

    def _run_holistic_review(
        self,
        task_id: str,
        manifest: dict[str, Any],
        sprint: dict[str, Any],
    ) -> None:
        result = self._invoke_agent(
            task_id=task_id,
            manifest=manifest,
            sprint=sprint,
            role=ROLE_EVALUATOR,
            phase=sprint["phase"],
            action="HOLISTIC_REVIEW",
            schema_key="holistic_review",
            logical_session="evaluator_holistic",
            artifact_name="holistic-review.json",
            context={
                "user_request": sprint["user_request"],
                "accepted_contract": sprint["contract"]["accepted_contract"],
                "implementation": sprint["implementation"],
                "aggregate_review": sprint["reviews"]["aggregate"],
            },
            scope="holistic",
            notes_zh="负责从用户视角做整体审批。",
        )
        sprint["holistic_review"] = result.payload
        self._save_state(task_id, manifest, sprint)
        if result.payload["pass"]:
            sprint["phase"] = PHASE_DONE
            sprint["status"] = STATUS_DONE
            manifest["status"] = STATUS_DONE
            self._save_state(task_id, manifest, sprint)
            self._emit_progress(
                "Holistic Review 通过",
                [
                    f"摘要: {self._short_text(result.payload.get('summary_zh'))}",
                    "结论: 任务完成。",
                ],
            )
            self._append_event(
                task_id,
                sprint,
                "SPRINT_DONE",
                "orchestrator",
                "Holistic review 通过，任务完成。",
                {},
            )
            return
        self._emit_progress(
            "Holistic Review 未通过，准备返工",
            [
                f"摘要: {self._short_text(result.payload.get('summary_zh'))}",
                "满意度缺口: " + self._format_items(result.payload.get("satisfaction_gaps_zh", []), limit=5),
                "需结转 features: " + self._format_items(result.payload.get("carry_forward_required", []), limit=8),
                "下一步: 创建下一轮 Sprint。",
            ],
        )
        self._transition(
            task_id,
            manifest,
            sprint,
            PHASE_NEXT_SPRINT_PREP,
            "Holistic review 未通过，准备下一轮 Sprint。",
            "orchestrator",
        )

    def _prepare_next_sprint(
        self,
        task_id: str,
        manifest: dict[str, Any],
        sprint: dict[str, Any],
    ) -> None:
        next_seed = self._build_next_sprint_seed(sprint)
        sprint["next_sprint_seed"] = next_seed
        sprint["status"] = STATUS_CARRY_FORWARD
        self._save_state(task_id, manifest, sprint)
        next_number = sprint["sprint_number"] + 1
        next_sprint = build_initial_sprint(
            task_id,
            sprint["user_request"],
            sprint_number=next_number,
            inherited=next_sprint_inheritance(sprint),
        )
        self.storage.ensure_task_layout(task_id, sprint_number=next_number)
        self.storage.save_sprint(task_id, next_sprint)
        manifest["latest_sprint"] = next_number
        manifest["latest_file"] = f"runs/{task_id}/sprint-{next_number:03d}.json"
        manifest["status"] = STATUS_IN_PROGRESS
        manifest["current_phase"] = PHASE_INIT
        manifest["resume_pointer"] = {
            "phase": PHASE_INIT,
            "file": manifest["latest_file"],
            "reason_zh": "上一轮已结转，开始下一轮 Sprint。",
        }
        self.storage.save_manifest(task_id, manifest)
        self._emit_progress(
            f"已创建 Sprint {next_number}",
            [
                "继承已通过 features: "
                + self._format_items(
                    [item.get("feature_id", "") for item in next_seed.get("accepted_features_inherited", [])],
                    limit=8,
                ),
                "待处理 features: "
                + self._format_items(
                    [item.get("feature_id", "") for item in next_seed.get("open_features", [])],
                    limit=8,
                ),
                "Open findings: " + str(len(next_seed.get("open_findings", []))),
            ],
        )
        self._append_event(
            task_id,
            sprint,
            "SPRINT_CARRY_FORWARD_CREATED",
            "orchestrator",
            f"已创建 Sprint {next_number}。",
            {"next_sprint": next_number},
        )

    def _build_next_sprint_seed(self, sprint: dict[str, Any]) -> dict[str, Any]:
        contract = sprint["contract"]["accepted_contract"]
        implementation = sprint["implementation"]
        reviews = sprint["reviews"]["aggregate"]
        holistic = sprint["holistic_review"]
        feature_state = feature_status_summary(contract, implementation)
        carry_forward = set(holistic.get("carry_forward_required", []))
        accepted_features = []
        open_features = []
        for feature in contract["features_planned"]:
            item = {
                "feature_id": feature["feature_id"],
                "title_zh": feature["title_zh"],
                "status": feature_state.get(feature["feature_id"], "planned"),
                "notes_zh": feature.get("reason_zh", ""),
            }
            if item["feature_id"] in carry_forward or item["status"] != "passed":
                open_features.append(item)
            else:
                accepted_features.append(item)
        emergent_blockers = [
            {
                "finding_id": blocker["blocker_id"],
                "scope_type": "holistic",
                "scope_id": "emergent-blocker",
                "severity": blocker["severity"],
                "summary_zh": blocker["reason_zh"],
                "evidence_zh": blocker["why_now_zh"],
                "repro_steps_zh": [],
                "suggested_fix_zh": blocker["next_negotiation_hint_zh"],
            }
            for blocker in holistic["decision_basis"].get("emergent_blockers", [])
        ]
        return {
            "should_create_next_sprint": True,
            "accepted_features_inherited": accepted_features,
            "open_features": open_features,
            "open_findings": reviews.get("open_findings", []) + emergent_blockers,
            "rejected_findings": holistic.get("rejected_review_findings", []),
            "canonical_context": holistic.get("summary_zh", ""),
        }
