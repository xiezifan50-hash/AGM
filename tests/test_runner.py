from __future__ import annotations

from pathlib import Path
from subprocess import TimeoutExpired
from unittest.mock import patch

from testlib import WorkspaceTestCase

from codex_ma.config import CodexConfig, ProjectConfig
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
            profile="missing-profile",
            logical_session="generator_contract",
        )

        with patch("codex_ma.runner.subprocess.run") as run_mock:
            run_mock.side_effect = TimeoutExpired(cmd=["codex"], timeout=120)
            with self.assertRaises(RunnerError) as raised:
                runner.run(request)

        self.assertIn("timed out after 120s", str(raised.exception))
        self.assertIn("action=GENERATOR_ARGUE_BACK", str(raised.exception))
