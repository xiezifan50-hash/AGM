from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any
import json
import os
import re
import subprocess

from codex_ma.config import AgentConfig, ProjectConfig, resolve_codex_binary


class RunnerError(RuntimeError):
    pass


class AgentTimeoutError(RunnerError):
    pass


class AgentOutputError(RunnerError):
    def __init__(
        self,
        message: str,
        *,
        raw_output: str = "",
        session_id: str | None = None,
        raw_events: list[dict[str, Any]] | None = None,
        command: list[str] | None = None,
    ):
        super().__init__(message)
        self.raw_output = raw_output
        self.session_id = session_id
        self.raw_events = raw_events or []
        self.command = command or []


@dataclass(slots=True)
class RunnerRequest:
    role: str
    phase: str
    action: str
    prompt: str
    schema_path: Path
    output_path: Path
    cwd: Path
    logical_session: str
    session_id: str | None = None
    run_mode: str = "fresh"


@dataclass(slots=True)
class RunnerResult:
    payload: dict[str, Any]
    session_id: str | None
    raw_events: list[dict[str, Any]] = field(default_factory=list)
    command: list[str] = field(default_factory=list)
    raw_output: str = ""


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
                        raw_output=json.dumps(payload, ensure_ascii=False),
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
        try:
            proc = subprocess.run(
                cmd,
                cwd=request.cwd,
                input=request.prompt,
                text=True,
                capture_output=True,
                timeout=self.config.codex.agent_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise AgentTimeoutError(
                f"Codex command timed out after {self.config.codex.agent_timeout_seconds}s "
                f"for action={request.action} role={request.role}"
            ) from exc
        raw_events = _parse_jsonl(proc.stdout)
        session_id = _extract_session_id(raw_events) or request.session_id
        if proc.returncode != 0:
            raise RunnerError(
                f"Codex command failed with exit code {proc.returncode}: {proc.stderr.strip() or proc.stdout.strip()}"
            )
        if not request.output_path.exists():
            raise AgentOutputError(
                "Codex command finished without writing output file",
                raw_output=proc.stdout.strip() or proc.stderr.strip(),
                session_id=session_id,
                raw_events=raw_events,
                command=cmd,
            )
        raw_output = request.output_path.read_text(encoding="utf-8")
        try:
            payload = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise AgentOutputError(
                f"Invalid JSON output from Codex: {exc}",
                raw_output=raw_output,
                session_id=session_id,
                raw_events=raw_events,
                command=cmd,
            ) from exc
        return RunnerResult(
            payload=payload,
            session_id=session_id,
            raw_events=raw_events,
            command=cmd,
            raw_output=raw_output,
        )

    def _build_command(self, request: RunnerRequest) -> list[str]:
        if request.run_mode == "resume":
            return self._build_resume_command(request)
        if request.run_mode in {"fresh", "normalize"}:
            return self._build_fresh_command(request)
        raise RunnerError(f"Unsupported runner mode: {request.run_mode}")

    def _build_fresh_command(self, request: RunnerRequest) -> list[str]:
        binary = resolve_codex_binary(self.config.codex.binary)
        if not binary:
            raise RunnerError("未找到 Codex CLI，可在 multiagent.toml 的 [codex].binary 中配置绝对路径")
        cmd = [binary, "exec", "-C", str(request.cwd)]
        agent = self.config.agents.get(request.role, AgentConfig())
        cmd.extend(self._agent_flags(agent))
        cmd.extend(
            [
                "--output-schema",
                str(request.schema_path),
                "--json",
                "-o",
                str(request.output_path),
            ]
        )
        if self.config.codex.search or agent.search:
            cmd.append("--search")
        if self.config.codex.skip_git_repo_check:
            cmd.append("--skip-git-repo-check")
        cmd.append("-")
        return cmd

    def _build_resume_command(self, request: RunnerRequest) -> list[str]:
        binary = resolve_codex_binary(self.config.codex.binary)
        if not binary:
            raise RunnerError("未找到 Codex CLI，可在 multiagent.toml 的 [codex].binary 中配置绝对路径")
        if not request.session_id:
            raise RunnerError("resume mode requires a session_id")
        cmd = [binary, "exec", "resume"]
        agent = self.config.agents.get(request.role, AgentConfig())
        cmd.extend(self._resume_agent_flags(agent))
        cmd.extend(["--json", "-o", str(request.output_path)])
        if self.config.codex.skip_git_repo_check:
            cmd.append("--skip-git-repo-check")
        cmd.extend([request.session_id, "-"])
        return cmd

    def _agent_flags(self, agent: AgentConfig) -> list[str]:
        flags: list[str] = []
        if agent.model:
            flags.extend(["-m", agent.model])
        if agent.sandbox:
            flags.extend(["-s", agent.sandbox])
        if agent.approval_policy:
            flags.extend(["-a", agent.approval_policy])
        if agent.reasoning_effort:
            flags.extend(
                [
                    "-c",
                    f'model_reasoning_effort="{_toml_string(agent.reasoning_effort)}"',
                ]
            )
        return flags

    def _resume_agent_flags(self, agent: AgentConfig) -> list[str]:
        flags: list[str] = []
        if agent.model:
            flags.extend(["-m", agent.model])
        if agent.reasoning_effort:
            flags.extend(
                [
                    "-c",
                    f'model_reasoning_effort="{_toml_string(agent.reasoning_effort)}"',
                ]
            )
        return flags


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


def _toml_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
