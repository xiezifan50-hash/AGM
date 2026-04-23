from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any
import json
import os
import re
import subprocess

from codex_ma.config import ProjectConfig


class RunnerError(RuntimeError):
    pass


@dataclass(slots=True)
class RunnerRequest:
    role: str
    phase: str
    action: str
    prompt: str
    schema_path: Path
    output_path: Path
    cwd: Path
    profile: str
    logical_session: str
    session_id: str | None = None


@dataclass(slots=True)
class RunnerResult:
    payload: dict[str, Any]
    session_id: str | None
    raw_events: list[dict[str, Any]] = field(default_factory=list)
    command: list[str] = field(default_factory=list)


class BaseRunner:
    def run(self, request: RunnerRequest) -> RunnerResult:
        raise NotImplementedError


class FixtureRunner(BaseRunner):
    def __init__(self, scenario: dict[str, Any]):
        self.scenario = scenario
        self._lock = Lock()
        self._used_indexes: set[int] = set()

    @classmethod
    def from_file(cls, path: Path) -> "FixtureRunner":
        with path.open("r", encoding="utf-8") as handle:
            return cls(json.load(handle))

    def run(self, request: RunnerRequest) -> RunnerResult:
        with self._lock:
            for index, step in enumerate(self.scenario.get("steps", [])):
                if index in self._used_indexes:
                    continue
                match = step.get("match", {})
                if all(getattr(request, key) == value for key, value in match.items()):
                    self._used_indexes.add(index)
                    payload = step["payload"]
                    request.output_path.parent.mkdir(parents=True, exist_ok=True)
                    request.output_path.write_text(
                        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    return RunnerResult(
                        payload=payload,
                        session_id=step.get("session_id"),
                        raw_events=step.get("events", []),
                        command=["fixture-runner", request.action],
                    )
        raise RunnerError(
            f"Fixture runner has no remaining step for role={request.role} action={request.action}"
        )


class CodexRunner(BaseRunner):
    def __init__(self, config: ProjectConfig):
        self.config = config

    def run(self, request: RunnerRequest) -> RunnerResult:
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = self._build_command(request)
        proc = subprocess.run(
            cmd,
            cwd=request.cwd,
            input=request.prompt,
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            raise RunnerError(
                f"Codex command failed with exit code {proc.returncode}: {proc.stderr.strip() or proc.stdout.strip()}"
            )
        if not request.output_path.exists():
            raise RunnerError("Codex command finished without writing output file")
        try:
            payload = json.loads(request.output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RunnerError(f"Invalid JSON output from Codex: {exc}") from exc
        raw_events = _parse_jsonl(proc.stdout)
        session_id = _extract_session_id(raw_events) or request.session_id
        return RunnerResult(
            payload=payload,
            session_id=session_id,
            raw_events=raw_events,
            command=cmd,
        )

    def _build_command(self, request: RunnerRequest) -> list[str]:
        cmd = [self.config.codex.binary, "exec"]
        if request.session_id:
            cmd.extend(["resume", request.session_id])
        cmd.extend(
            [
                "-C",
                str(request.cwd),
                "-p",
                request.profile,
                "--output-schema",
                str(request.schema_path),
                "--json",
                "-o",
                str(request.output_path),
            ]
        )
        if self.config.codex.search:
            cmd.append("--search")
        if self.config.codex.skip_git_repo_check:
            cmd.append("--skip-git-repo-check")
        cmd.append("-")
        return cmd


def build_runner(root: Path, config: ProjectConfig) -> BaseRunner:
    mode = os.environ.get("CODEX_MA_RUNNER", "").strip().lower()
    if mode == "fixture":
        fixture_file = os.environ.get("CODEX_MA_FIXTURE_FILE")
        if not fixture_file:
            raise RunnerError("CODEX_MA_FIXTURE_FILE 未设置，无法启用 fixture runner")
        return FixtureRunner.from_file(Path(fixture_file))
    return CodexRunner(config)


def _parse_jsonl(stdout: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


def _extract_session_id(events: list[dict[str, Any]]) -> str | None:
    def visit(value: Any) -> str | None:
        if isinstance(value, dict):
            if "session_id" in value and isinstance(value["session_id"], str):
                return value["session_id"]
            for nested in value.values():
                found = visit(nested)
                if found:
                    return found
        if isinstance(value, list):
            for nested in value:
                found = visit(nested)
                if found:
                    return found
        if isinstance(value, str):
            match = re.search(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", value)
            if match:
                return match.group(0)
        return None

    for event in events:
        found = visit(event)
        if found:
            return found
    return None
