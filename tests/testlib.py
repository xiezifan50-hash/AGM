from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

import sys

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from codex_ma.config import load_config
from codex_ma.orchestrator import Orchestrator
from codex_ma.runner import FixtureRunner
from codex_ma.storage import Storage


class WorkspaceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmpdir.name)
        shutil.copytree(ROOT / "schemas", self.workspace / "schemas")
        self.storage = Storage(self.workspace)
        self.storage.ensure_layout()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def make_orchestrator(self, scenario: dict | None = None) -> Orchestrator:
        config = load_config(self.workspace)
        runner = FixtureRunner(scenario or {"steps": []}) if scenario is not None else None
        return Orchestrator(self.workspace, self.storage, runner, config)
