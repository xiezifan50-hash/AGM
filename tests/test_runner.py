from __future__ import annotations

from pathlib import Path
from subprocess import TimeoutExpired
from unittest.mock import patch

from testlib import WorkspaceTestCase

from codex_ma.config import AgentConfig, CodexConfig, ProjectConfig
from codex_ma.runner import CodexRunner, RunnerError, RunnerRequest


class RunnerTests(WorkspaceTestCase):
    def test_codex_runner_times_out_single_agent_call(self) -> None:
        config = ProjectConfig(
            codex=CodexConfig(binary="/bin/sh", agent_timeout_seconds=120)
        )
        runner = CodexRunner(config)
        request = RunnerRequest(
            role="generator",
            phase="NEGOTIATE_ROUND",
            action="GENERATOR_ARGUE_BACK",
            prompt="{}",
            schema_path=Path("schema.json"),
            output_path=self.workspace / "output.json",
            cwd=self.workspace,
            logical_session="generator_contract",
        )

        with patch("codex_ma.runner.subprocess.run") as run_mock:
            run_mock.side_effect = TimeoutExpired(cmd=["codex"], timeout=120)
            with self.assertRaises(RunnerError) as raised:
                runner.run(request)

        self.assertIn("timed out after 120s", str(raised.exception))
        self.assertIn("action=GENERATOR_ARGUE_BACK", str(raised.exception))

    def test_codex_runner_uses_project_agent_config_without_profile(self) -> None:
        config = ProjectConfig(
            codex=CodexConfig(binary="/bin/echo"),
            agents={
                "generator": AgentConfig(
                    model="gpt-5.3-codex",
                    reasoning_effort="medium",
                    sandbox="workspace-write",
                    approval_policy="on-request",
                    search=True,
                )
            },
        )
        runner = CodexRunner(config)
        request = RunnerRequest(
            role="generator",
            phase="IMPLEMENTING",
            action="FEATURE_EXECUTION",
            prompt="{}",
            schema_path=Path("schema.json"),
            output_path=self.workspace / "output.json",
            cwd=self.workspace,
            logical_session="generator_feature_core",
        )

        cmd = runner._build_command(request)

        self.assertNotIn("-p", cmd)
        self.assertNotIn("-a", cmd)
        self.assertIn("gpt-5.3-codex", cmd)
        self.assertIn("workspace-write", cmd)
        self.assertIn('model_reasoning_effort="medium"', cmd)
        self.assertNotIn("--search", cmd)

    def test_codex_runner_resume_uses_session_without_output_schema(self) -> None:
        config = ProjectConfig(
            codex=CodexConfig(binary="/bin/echo"),
            agents={
                "generator": AgentConfig(
                    model="gpt-5.3-codex",
                    reasoning_effort="low",
                    sandbox="workspace-write",
                    approval_policy="on-request",
                    search=True,
                )
            },
        )
        runner = CodexRunner(config)
        request = RunnerRequest(
            role="generator",
            phase="NEGOTIATE_ROUND",
            action="GENERATOR_PROPOSAL",
            prompt="{}",
            schema_path=Path("schema.json"),
            output_path=self.workspace / "output.json",
            cwd=self.workspace,
            logical_session="generator_contract",
            session_id="session-123",
            run_mode="resume",
        )

        cmd = runner._build_command(request)

        self.assertEqual(cmd[:3], ["/bin/echo", "exec", "resume"])
        self.assertIn("session-123", cmd)
        self.assertNotIn("--output-schema", cmd)
        self.assertNotIn("-C", cmd)
        self.assertNotIn("-s", cmd)
        self.assertNotIn("-a", cmd)
        self.assertIn('model_reasoning_effort="low"', cmd)
