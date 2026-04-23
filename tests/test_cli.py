from __future__ import annotations

from argparse import Namespace

from testlib import WorkspaceTestCase

from codex_ma.cli import dispatch
from codex_ma.config import load_config
from codex_ma.storage import Storage


class CliTests(WorkspaceTestCase):
    def test_init_and_task_create(self) -> None:
        storage = Storage(self.workspace)
        config = load_config(self.workspace)
        init_args = Namespace(command="init")
        rc = dispatch(init_args, self.workspace, storage, config)
        self.assertEqual(rc, 0)
        self.assertTrue((self.workspace / "multiagent.toml").exists())

        config = load_config(self.workspace)
        create_args = Namespace(
            command="task",
            task_command="create",
            user_request="实现核心功能",
            task_id="task-123",
            workspace="project-space",
        )
        rc = dispatch(create_args, self.workspace, storage, config)
        self.assertEqual(rc, 0)
        self.assertTrue((self.workspace / "runs" / "task-123" / "manifest.json").exists())

        stop_args = Namespace(command="stop", task_id="task-123")
        rc = dispatch(stop_args, self.workspace, storage, config)
        self.assertEqual(rc, 0)
        manifest = storage.load_manifest("task-123")
        self.assertEqual(manifest["status"], "aborted")
        self.assertTrue(manifest["project_workspace"].endswith("project-space"))
