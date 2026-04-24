from __future__ import annotations

from testlib import WorkspaceTestCase

from codex_ma.config import load_config


class ConfigTests(WorkspaceTestCase):
    def test_codex_agent_timeout_defaults_to_fifteen_minutes(self) -> None:
        config = load_config(self.workspace)

        self.assertEqual(config.codex.agent_timeout_seconds, 900)

    def test_codex_agent_timeout_can_be_configured(self) -> None:
        (self.workspace / "multiagent.toml").write_text(
            """[codex]
binary = "codex"
agent_timeout_seconds = 120
""",
            encoding="utf-8",
        )

        config = load_config(self.workspace)

        self.assertEqual(config.codex.agent_timeout_seconds, 120)
