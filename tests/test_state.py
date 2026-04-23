from __future__ import annotations

from testlib import WorkspaceTestCase

from codex_ma.state import compute_feature_consensus, compute_global_consensus


class StateTests(WorkspaceTestCase):
    def test_feature_consensus_requires_criteria_and_no_unresolved_points(self) -> None:
        contract = {
            "features_planned": [
                {"feature_id": "core", "title_zh": "核心功能", "reason_zh": "必须实现"},
                {"feature_id": "extras", "title_zh": "额外功能", "reason_zh": "可选"},
            ],
            "acceptance_criteria": [
                {"feature_id": "core", "criteria_zh": ["可以运行"]},
                {"feature_id": "extras", "criteria_zh": []},
            ],
        }
        unresolved = [
            {
                "point_id": "p-1",
                "kind": "feature",
                "target_id": "extras",
                "title_zh": "extras 的验收标准未定",
                "generator_position_zh": "先不做",
                "evaluator_position_zh": "至少补一条标准",
            }
        ]
        consensus = compute_feature_consensus(contract, unresolved)
        self.assertTrue(consensus[0]["pass"])
        self.assertFalse(consensus[1]["pass"])
        self.assertIn("extras 的验收标准未定", consensus[1]["unresolved_points_zh"])

    def test_global_consensus_requires_holistic_fields_and_no_global_unresolved(self) -> None:
        rubric = {
            "user_success_statement_zh": "用户能完成核心流程",
            "must_have_features": ["core"],
            "nice_to_have_features": [],
            "holistic_acceptance_criteria_zh": ["核心功能可用"],
            "holistic_fail_conditions_zh": ["核心流程不可用"],
            "deferred_concerns_zh": [],
            "rejected_evaluator_requests": [],
        }
        unresolved = [
            {
                "point_id": "g-1",
                "kind": "global",
                "target_id": "holistic",
                "title_zh": "用户成功定义仍有争议",
                "generator_position_zh": "保持宽松",
                "evaluator_position_zh": "需要更严格",
            }
        ]
        result = compute_global_consensus(rubric, unresolved)
        self.assertFalse(result["pass"])
        self.assertEqual(result["unresolved_points_zh"], ["用户成功定义仍有争议"])
        self.assertEqual(result["missing_fields"], [])
