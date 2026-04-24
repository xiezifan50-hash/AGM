from __future__ import annotations

from testlib import WorkspaceTestCase

from codex_ma.config import load_config


class ConfigTests(WorkspaceTestCase):
    def test_codex_agent_timeout_defaults_to_fifteen_minutes(self) -> None:
        config = load_config(self.workspace)

        self.assertEqual(config.codex.agent_timeout_seconds, 900)
        self.assertEqual(config.agents["generator"].model, "gpt-5.3-codex")
        self.assertEqual(config.agents["generator"].sandbox, "workspace-write")
        self.assertEqual(config.agents["reviewer"].model, "gpt-5.4-mini")

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

    def test_agent_config_can_be_overridden_per_role(self) -> None:
        (self.workspace / "multiagent.toml").write_text(
            """[agents.generator]
model = "gpt-5.3-codex"
reasoning_effort = "high"
sandbox = "workspace-write"
approval_policy = "on-request"
search = true
""",
            encoding="utf-8",
        )

        config = load_config(self.workspace)

        self.assertEqual(config.agents["generator"].reasoning_effort, "high")
        self.assertTrue(config.agents["generator"].search)
        self.assertEqual(config.agents["reviewer"].model, "gpt-5.4-mini")
