from __future__ import annotations

from testlib import WorkspaceTestCase
from codex_ma.orchestrator import WorkspaceViolation
from codex_ma.runner import AgentTimeoutError, BaseRunner, RunnerRequest, RunnerResult


class CallbackRunner(BaseRunner):
    def __init__(self, payload: dict, callback):
        self.payload = payload
        self.callback = callback

    def run(self, request: RunnerRequest) -> RunnerResult:
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.callback()
        request.output_path.write_text("{}\n", encoding="utf-8")
        return RunnerResult(
            payload=self.payload,
            session_id="callback-session",
            command=["callback-runner", request.action],
        )


class TimeoutRunner(BaseRunner):
    def run(self, request: RunnerRequest) -> RunnerResult:
        raise AgentTimeoutError(
            f"Codex command timed out for action={request.action} role={request.role}"
        )


def make_contract(summary: str = "实现核心功能") -> dict:
    return {
        "summary_zh": summary,
        "features_planned": [
            {
                "feature_id": "core",
                "title_zh": "核心功能",
                "reason_zh": "这是主目标"
            }
        ],
        "acceptance_criteria": [
            {
                "feature_id": "core",
                "criteria_zh": ["命令可以成功执行", "核心输出存在"]
            }
        ],
        "non_goals_zh": ["不做 UI"],
        "l1_checks": [
            {
                "check_id": "smoke",
                "name_zh": "基础 smoke 检查",
                "command": "python3 -c \"print('ok')\"",
                "required": True
            }
        ],
        "review_dimensions": [
            "correctness",
            "regression-risk",
            "api-ux-contract"
        ],
        "risks_zh": ["需要确保审批标准一致"],
        "user_success_statement_zh": "用户可以完成核心任务且输出可信。",
        "must_have_features": ["core"],
        "nice_to_have_features": ["日志更完整"],
        "holistic_acceptance_criteria_zh": ["核心目标完成", "无阻断性错误"],
        "holistic_fail_conditions_zh": ["核心目标失败", "输出明显错误"],
        "deferred_concerns_zh": ["UI 体验"],
        "rejected_evaluator_requests": []
    }


def make_feedback(pass_value: bool, summary: str = "合同可接受") -> dict:
    return {
        "summary_zh": summary,
        "pass": pass_value,
        "issues_zh": [] if pass_value else ["仍需澄清全局标准"],
        "suggested_edits_zh": [] if pass_value else ["补充用户满意标准"],
        "challenge_points_zh": [] if pass_value else ["必须有清晰的 fail 条件"],
        "proposed_holistic_acceptance_criteria_zh": ["核心目标完成"],
        "proposed_holistic_fail_conditions_zh": ["核心目标失败"],
        "deferred_concerns_zh": ["UI 体验"]
    }


def make_resolution(
    contract: dict,
    unresolved_points: list[dict] | None = None,
    summary: str = "已完成修订"
) -> dict:
    return {
        "summary_zh": summary,
        "accepted_changes_zh": ["补充全局审批标准"],
        "rejected_evaluator_requests": [],
        "unresolved_points": unresolved_points or [],
        "resolved_contract": contract
    }


def make_review(review_id: str, scope_type: str, scope_id: str, pass_value: bool = True) -> dict:
    score = 5 if pass_value else 2
    return {
        "review_id": review_id,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "pass": pass_value,
        "severity": "low",
        "score": score,
        "score_reason_zh": "技术审查未发现阻断问题" if pass_value else "存在需要修复的技术问题",
        "project_path": "/tmp/project",
        "review_dimension_zh": "Feature 技术代码审查" if scope_type == "feature" else scope_id,
        "summary_zh": "检查通过" if pass_value else "发现问题",
        "evidence_sections": [
            {
                "section_id": "evidence-1",
                "title_zh": "基础证据",
                "result": "pass" if pass_value else "fail",
                "evidence_zh": "fixture 审查证据",
                "references": [
                    {
                        "kind": "other",
                        "target": "fixture",
                        "detail_zh": "测试构造的 review verdict"
                    }
                ]
            }
        ],
        "findings": []
    }


def make_holistic(pass_value: bool = True) -> dict:
    return {
        "pass": pass_value,
        "summary_zh": "整体结果满足预期" if pass_value else "整体结果未达预期",
        "satisfaction_gaps_zh": [] if pass_value else ["核心结果不稳定"],
        "carry_forward_required": [] if pass_value else ["core"],
        "rejected_review_findings": [],
        "decision_basis": {
            "unmet_acceptance_criteria_zh": [] if pass_value else ["核心目标完成"],
            "triggered_fail_conditions_zh": [] if pass_value else ["核心目标失败"],
            "emergent_blockers": []
        }
    }


class OrchestratorTests(WorkspaceTestCase):
    def workspace_path(self, name: str = "project") -> str:
        return (self.workspace / name).as_posix()

    def test_stop_marks_task_aborted_and_run_noops(self) -> None:
        orchestrator = self.make_orchestrator({"steps": []})
        orchestrator.init_workspace()
        orchestrator.create_task("实现核心功能", "task-stop", self.workspace_path())

        stopped = orchestrator.stop("task-stop")
        self.assertEqual(stopped["manifest"]["status"], "aborted")
        self.assertEqual(stopped["sprint"]["status"], "aborted")

        result = orchestrator.run("task-stop")
        self.assertEqual(result["manifest"]["status"], "aborted")
        self.assertEqual(result["sprint"]["phase"], "INIT")

        events = orchestrator.events("task-stop")
        self.assertEqual(events[-1]["event_type"], "TASK_STOPPED")

    def test_pause_marks_task_paused_and_resume_continues(self) -> None:
        contract = make_contract()
        scenario = {
            "steps": [
                {"match": {"action": "GENERATOR_RESEARCH"}, "payload": contract, "session_id": "gen-contract"},
                {"match": {"action": "EVALUATOR_RESEARCH"}, "payload": make_feedback(False, "先提出协商基线"), "session_id": "eval-contract"},
                {"match": {"action": "GENERATOR_PROPOSAL"}, "payload": contract, "session_id": "gen-contract"},
                {"match": {"action": "EVALUATOR_FEEDBACK"}, "payload": make_feedback(False, "需要补齐 wording"), "session_id": "eval-contract"},
                {"match": {"action": "GENERATOR_ARGUE_BACK"}, "payload": make_resolution(contract), "session_id": "gen-contract"},
                {"match": {"action": "EVALUATOR_RESOLUTION"}, "payload": make_feedback(True), "session_id": "eval-contract"},
                {
                    "match": {"action": "FEATURE_EXECUTION", "logical_session": "generator_feature_core"},
                    "payload": {
                        "summary_zh": "已完成核心功能实现",
                        "research_summary_zh": "确认实现路径",
                        "execution_summary_zh": "写入核心逻辑",
                        "status": "in_progress",
                        "changed_files": ["app.py"],
                        "blockers_zh": []
                    },
                    "session_id": "gen-core"
                },
                {
                    "match": {"action": "FEATURE_REVIEW", "logical_session": "reviewer_feature_core"},
                    "payload": make_review("feature-core", "feature", "core"),
                    "session_id": "review-core"
                },
                {
                    "match": {"action": "DIMENSION_REVIEW", "logical_session": "reviewer_dimension_correctness"},
                    "payload": make_review("dimension-correctness", "dimension", "correctness"),
                    "session_id": "review-dim-1"
                },
                {
                    "match": {"action": "DIMENSION_REVIEW", "logical_session": "reviewer_dimension_regression-risk"},
                    "payload": make_review("dimension-regression-risk", "dimension", "regression-risk"),
                    "session_id": "review-dim-2"
                },
                {
                    "match": {"action": "DIMENSION_REVIEW", "logical_session": "reviewer_dimension_api-ux-contract"},
                    "payload": make_review("dimension-api-ux-contract", "dimension", "api-ux-contract"),
                    "session_id": "review-dim-3"
                },
                {"match": {"action": "HOLISTIC_REVIEW"}, "payload": make_holistic(True), "session_id": "eval-holistic"}
            ]
        }
        orchestrator = self.make_orchestrator(scenario)
        orchestrator.init_workspace()
        orchestrator.create_task("实现核心功能", "task-pause", self.workspace_path())

        paused = orchestrator.pause("task-pause")
        self.assertEqual(paused["manifest"]["status"], "paused")
        self.assertEqual(paused["sprint"]["status"], "paused")
        self.assertEqual(paused["sprint"]["phase"], "INIT")

        result = orchestrator.run("task-pause")
        self.assertEqual(result["manifest"]["status"], "paused")
        self.assertEqual(result["sprint"]["phase"], "INIT")

        resumed = orchestrator.resume("task-pause")
        self.assertEqual(resumed["manifest"]["status"], "done")
        self.assertEqual(resumed["sprint"]["phase"], "DONE")

        events = orchestrator.events("task-pause")
        self.assertIn("TASK_PAUSED", [event["event_type"] for event in events])

    def test_workspace_must_not_be_tool_root(self) -> None:
        orchestrator = self.make_orchestrator({"steps": []})
        orchestrator.init_workspace()
        with self.assertRaises(ValueError):
            orchestrator.create_task("实现核心功能", "task-root", self.workspace)

    def test_review_jobs_use_negotiated_dimensions_only(self) -> None:
        contract = make_contract()
        contract["review_dimensions"] = ["security-hardening"]
        orchestrator = self.make_orchestrator({"steps": []})
        orchestrator.init_workspace()
        result = orchestrator.create_task("实现核心功能", "task-dimensions", self.workspace_path())
        manifest = result["manifest"]
        sprint = result["sprint"]
        sprint["contract"]["accepted_contract"] = contract

        orchestrator._prepare_reviews("task-dimensions", manifest, sprint)

        state = orchestrator.status("task-dimensions")
        self.assertEqual(
            [
                (job["scope_type"], job["scope_id"])
                for job in state["sprint"]["reviews"]["review_jobs"]
            ],
            [("feature", "core"), ("dimension", "security-hardening")],
        )

    def test_changed_files_are_limited_to_workspace(self) -> None:
        orchestrator = self.make_orchestrator({"steps": []})
        orchestrator.init_workspace()
        result = orchestrator.create_task("实现核心功能", "task-boundary", self.workspace_path())
        orchestrator._assert_payload_within_workspace(
            result["manifest"],
            {"changed_files": ["README.md", "src/app.py"]},
        )
        with self.assertRaises(WorkspaceViolation):
            orchestrator._assert_payload_within_workspace(
                result["manifest"],
                {"changed_files": ["../README.md"]},
            )

    def test_stop_during_agent_call_is_not_overwritten(self) -> None:
        orchestrator = self.make_orchestrator()
        orchestrator.init_workspace()
        orchestrator.create_task("实现核心功能", "task-stop-race", self.workspace_path())
        runner = CallbackRunner(
            make_contract(),
            lambda: orchestrator.stop("task-stop-race"),
        )
        orchestrator.runner = runner

        result = orchestrator.run("task-stop-race")
        self.assertEqual(result["manifest"]["status"], "aborted")
        self.assertIsNone(result["sprint"]["contract"]["generator_research"])

    def test_pause_during_agent_call_is_not_overwritten(self) -> None:
        orchestrator = self.make_orchestrator()
        orchestrator.init_workspace()
        orchestrator.create_task("实现核心功能", "task-pause-race", self.workspace_path())
        runner = CallbackRunner(
            make_contract(),
            lambda: orchestrator.pause("task-pause-race"),
        )
        orchestrator.runner = runner

        result = orchestrator.run("task-pause-race")
        self.assertEqual(result["manifest"]["status"], "paused")
        self.assertEqual(result["sprint"]["status"], "paused")
        self.assertIsNone(result["sprint"]["contract"]["generator_research"])

    def test_agent_timeout_marks_task_blocked(self) -> None:
        orchestrator = self.make_orchestrator()
        orchestrator.init_workspace()
        orchestrator.create_task("实现核心功能", "task-timeout", self.workspace_path())
        orchestrator.runner = TimeoutRunner()

        with self.assertRaises(AgentTimeoutError):
            orchestrator.run("task-timeout")

        result = orchestrator.status("task-timeout")
        self.assertEqual(result["manifest"]["status"], "blocked")
        self.assertEqual(result["sprint"]["status"], "blocked")
        events = orchestrator.events("task-timeout")
        self.assertEqual(events[-1]["event_type"], "AGENT_CALL_TIMED_OUT")

    def test_full_run_reaches_done(self) -> None:
        contract = make_contract()
        scenario = {
            "steps": [
                {"match": {"action": "GENERATOR_RESEARCH"}, "payload": contract, "session_id": "gen-contract"},
                {"match": {"action": "EVALUATOR_RESEARCH"}, "payload": make_feedback(False, "先提出协商基线"), "session_id": "eval-contract"},
                {"match": {"action": "GENERATOR_PROPOSAL"}, "payload": contract, "session_id": "gen-contract"},
                {"match": {"action": "EVALUATOR_FEEDBACK"}, "payload": make_feedback(False, "需要补齐 wording"), "session_id": "eval-contract"},
                {"match": {"action": "GENERATOR_ARGUE_BACK"}, "payload": make_resolution(contract), "session_id": "gen-contract"},
                {"match": {"action": "EVALUATOR_RESOLUTION"}, "payload": make_feedback(True), "session_id": "eval-contract"},
                {
                    "match": {"action": "FEATURE_EXECUTION", "logical_session": "generator_feature_core"},
                    "payload": {
                        "summary_zh": "已完成核心功能实现",
                        "research_summary_zh": "确认实现路径",
                        "execution_summary_zh": "写入核心逻辑",
                        "status": "in_progress",
                        "changed_files": ["app.py"],
                        "blockers_zh": []
                    },
                    "session_id": "gen-core"
                },
                {
                    "match": {"action": "FEATURE_REVIEW", "logical_session": "reviewer_feature_core"},
                    "payload": make_review("feature-core", "feature", "core"),
                    "session_id": "review-core"
                },
                {
                    "match": {"action": "DIMENSION_REVIEW", "logical_session": "reviewer_dimension_correctness"},
                    "payload": make_review("dimension-correctness", "dimension", "correctness"),
                    "session_id": "review-dim-1"
                },
                {
                    "match": {"action": "DIMENSION_REVIEW", "logical_session": "reviewer_dimension_regression-risk"},
                    "payload": make_review("dimension-regression-risk", "dimension", "regression-risk"),
                    "session_id": "review-dim-2"
                },
                {
                    "match": {"action": "DIMENSION_REVIEW", "logical_session": "reviewer_dimension_api-ux-contract"},
                    "payload": make_review("dimension-api-ux-contract", "dimension", "api-ux-contract"),
                    "session_id": "review-dim-3"
                },
                {"match": {"action": "HOLISTIC_REVIEW"}, "payload": make_holistic(True), "session_id": "eval-holistic"}
            ]
        }
        orchestrator = self.make_orchestrator(scenario)
        orchestrator.init_workspace()
        orchestrator.create_task("实现核心功能", "task-001", self.workspace_path())
        result = orchestrator.run("task-001")
        self.assertEqual(result["manifest"]["status"], "done")
        self.assertEqual(result["sprint"]["phase"], "DONE")
        self.assertEqual(result["sprint"]["implementation"]["features"][0]["status"], "passed")
        self.assertTrue(result["sprint"]["reviews"]["aggregate"]["all_required_passed"])

    def test_run_emits_readable_progress(self) -> None:
        contract = make_contract()
        scenario = {
            "steps": [
                {"match": {"action": "GENERATOR_RESEARCH"}, "payload": contract, "session_id": "gen-contract"},
                {"match": {"action": "EVALUATOR_RESEARCH"}, "payload": make_feedback(True), "session_id": "eval-contract"},
                {"match": {"action": "GENERATOR_PROPOSAL"}, "payload": contract, "session_id": "gen-contract"},
                {"match": {"action": "EVALUATOR_FEEDBACK"}, "payload": make_feedback(True), "session_id": "eval-contract"},
                {"match": {"action": "GENERATOR_ARGUE_BACK"}, "payload": make_resolution(contract), "session_id": "gen-contract"},
                {"match": {"action": "EVALUATOR_RESOLUTION"}, "payload": make_feedback(True), "session_id": "eval-contract"},
                {
                    "match": {"action": "FEATURE_EXECUTION", "logical_session": "generator_feature_core"},
                    "payload": {
                        "summary_zh": "已完成核心功能实现",
                        "research_summary_zh": "确认实现路径",
                        "execution_summary_zh": "写入核心逻辑",
                        "status": "in_progress",
                        "changed_files": ["app.py"],
                        "blockers_zh": []
                    },
                    "session_id": "gen-core"
                },
                {"match": {"action": "FEATURE_REVIEW"}, "payload": make_review("feature-core", "feature", "core"), "session_id": "review-core"},
                {"match": {"action": "DIMENSION_REVIEW", "logical_session": "reviewer_dimension_correctness"}, "payload": make_review("dimension-correctness", "dimension", "correctness"), "session_id": "review-dim-1"},
                {"match": {"action": "DIMENSION_REVIEW", "logical_session": "reviewer_dimension_regression-risk"}, "payload": make_review("dimension-regression-risk", "dimension", "regression-risk"), "session_id": "review-dim-2"},
                {"match": {"action": "DIMENSION_REVIEW", "logical_session": "reviewer_dimension_api-ux-contract"}, "payload": make_review("dimension-api-ux-contract", "dimension", "api-ux-contract"), "session_id": "review-dim-3"},
                {"match": {"action": "HOLISTIC_REVIEW"}, "payload": make_holistic(True), "session_id": "eval-holistic"}
            ]
        }
        orchestrator = self.make_orchestrator(scenario)
        orchestrator.init_workspace()
        orchestrator.create_task("实现核心功能", "task-progress", self.workspace_path())
        messages: list[str] = []

        orchestrator.run("task-progress", progress_func=messages.append)

        output = "\n".join(messages)
        self.assertIn("Generator 调研完成", output)
        self.assertIn("Negotiate 第 1 轮: Generator 提案开始", output)
        self.assertIn("Negotiate 第 1 轮: Evaluator 反馈完成", output)
        self.assertIn("Negotiate 第 1 轮: Generator 修订开始", output)
        self.assertIn("Negotiate 第 1 轮: Evaluator 终审完成", output)
        self.assertIn("合同已接受", output)
        self.assertIn("L1 检查通过", output)
        self.assertIn("Review 聚合通过", output)
        self.assertIn("Holistic Review 通过", output)

    def test_resume_after_human_gate(self) -> None:
        contract = make_contract("协商版核心功能")
        unresolved = [
            {
                "point_id": "g-1",
                "kind": "global",
                "target_id": "holistic",
                "title_zh": "用户满意标准仍需裁决",
                "generator_position_zh": "保持当前标准即可",
                "evaluator_position_zh": "需要补充更严格的硬门槛"
            }
        ]
        scenario = {
            "steps": [
                {"match": {"action": "GENERATOR_RESEARCH"}, "payload": contract, "session_id": "gen-contract"},
                {"match": {"action": "EVALUATOR_RESEARCH"}, "payload": make_feedback(False, "提出更严格基线"), "session_id": "eval-contract"},
                {"match": {"action": "GENERATOR_PROPOSAL"}, "payload": contract, "session_id": "gen-contract"},
                {"match": {"action": "EVALUATOR_FEEDBACK"}, "payload": make_feedback(False, "仍需裁决"), "session_id": "eval-contract"},
                {"match": {"action": "GENERATOR_ARGUE_BACK"}, "payload": make_resolution(contract, unresolved, "保留分歧"), "session_id": "gen-contract"},
                {"match": {"action": "EVALUATOR_RESOLUTION"}, "payload": make_feedback(False, "第一轮未收敛"), "session_id": "eval-contract"},
                {"match": {"action": "GENERATOR_PROPOSAL"}, "payload": contract, "session_id": "gen-contract"},
                {"match": {"action": "EVALUATOR_FEEDBACK"}, "payload": make_feedback(False, "第二轮仍未收敛"), "session_id": "eval-contract"},
                {"match": {"action": "GENERATOR_ARGUE_BACK"}, "payload": make_resolution(contract, unresolved, "第二轮仍有分歧"), "session_id": "gen-contract"},
                {"match": {"action": "EVALUATOR_RESOLUTION"}, "payload": make_feedback(False, "第二轮未收敛"), "session_id": "eval-contract"},
                {"match": {"action": "GENERATOR_PROPOSAL"}, "payload": contract, "session_id": "gen-contract"},
                {"match": {"action": "EVALUATOR_FEEDBACK"}, "payload": make_feedback(True, "人工意见已足够"), "session_id": "eval-contract"},
                {"match": {"action": "GENERATOR_ARGUE_BACK"}, "payload": make_resolution(contract, [], "人工裁决后已收敛"), "session_id": "gen-contract"},
                {"match": {"action": "EVALUATOR_RESOLUTION"}, "payload": make_feedback(True, "已同意"), "session_id": "eval-contract"},
                {
                    "match": {"action": "FEATURE_EXECUTION", "logical_session": "generator_feature_core"},
                    "payload": {
                        "summary_zh": "核心功能已落地",
                        "research_summary_zh": "根据人工裁决补齐标准",
                        "execution_summary_zh": "实现核心逻辑",
                        "status": "in_progress",
                        "changed_files": ["core.py"],
                        "blockers_zh": []
                    },
                    "session_id": "gen-core"
                },
                {
                    "match": {"action": "FEATURE_REVIEW", "logical_session": "reviewer_feature_core"},
                    "payload": make_review("feature-core", "feature", "core"),
                    "session_id": "review-core"
                },
                {
                    "match": {"action": "DIMENSION_REVIEW", "logical_session": "reviewer_dimension_correctness"},
                    "payload": make_review("dimension-correctness", "dimension", "correctness"),
                    "session_id": "review-dim-1"
                },
                {
                    "match": {"action": "DIMENSION_REVIEW", "logical_session": "reviewer_dimension_regression-risk"},
                    "payload": make_review("dimension-regression-risk", "dimension", "regression-risk"),
                    "session_id": "review-dim-2"
                },
                {
                    "match": {"action": "DIMENSION_REVIEW", "logical_session": "reviewer_dimension_api-ux-contract"},
                    "payload": make_review("dimension-api-ux-contract", "dimension", "api-ux-contract"),
                    "session_id": "review-dim-3"
                },
                {"match": {"action": "HOLISTIC_REVIEW"}, "payload": make_holistic(True), "session_id": "eval-holistic"}
            ]
        }
        orchestrator = self.make_orchestrator(scenario)
        orchestrator.init_workspace()
        orchestrator.create_task("实现协商式核心功能", "task-002", self.workspace_path())
        paused = orchestrator.run("task-002")
        self.assertEqual(paused["manifest"]["current_phase"], "AWAITING_HUMAN")

        answers = iter(["g", "", ""])
        def fake_input(prompt: str) -> str:
            return next(answers)

        result = orchestrator.resume("task-002", input_func=fake_input, output_func=lambda _: None)
        self.assertEqual(result["manifest"]["status"], "done")
        self.assertEqual(result["sprint"]["phase"], "DONE")
        self.assertTrue(result["sprint"]["contract"]["human_intervention"]["decisions"])
