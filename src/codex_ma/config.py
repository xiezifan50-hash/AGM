from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import shutil

import tomllib

from codex_ma.constants import DEFAULT_ROLE_AGENTS


@dataclass(slots=True)
class CodexConfig:
    binary: str = "codex"
    search: bool = False
    skip_git_repo_check: bool = True
    agent_timeout_seconds: int = 900


@dataclass(slots=True)
class AgentConfig:
    model: str = "gpt-5.4-mini"
    reasoning_effort: str = "low"
    sandbox: str = "read-only"
    approval_policy: str = "never"
    search: bool = False


@dataclass(slots=True)
class NegotiationConfig:
    max_rounds: int = 2


@dataclass(slots=True)
class ImplementationConfig:
    l1_retry_limit: int = 3
    check_timeout_seconds: int = 300


@dataclass(slots=True)
class ReviewConfig:
    max_concurrency: int = 4


@dataclass(slots=True)
class SafetyConfig:
    network_access: bool = False
    dangerous_approval_policy: str = "on-request"


@dataclass(slots=True)
class ProjectConfig:
    codex: CodexConfig = field(default_factory=CodexConfig)
    negotiation: NegotiationConfig = field(default_factory=NegotiationConfig)
    implementation: ImplementationConfig = field(default_factory=ImplementationConfig)
    review: ReviewConfig = field(default_factory=ReviewConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    agents: dict[str, AgentConfig] = field(default_factory=lambda: _default_agents())


def resolve_codex_binary(configured_binary: str) -> str | None:
    candidates = []
    if configured_binary:
        candidates.append(configured_binary)
    candidates.extend(
        [
            "codex",
            "/Applications/Codex.app/Contents/Resources/codex",
        ]
    )
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if "/" in candidate:
            path = Path(candidate).expanduser()
            if path.exists() and path.is_file():
                return str(path)
            continue
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def _default_agents() -> dict[str, AgentConfig]:
    return {
        role: AgentConfig(
            model=str(data["model"]),
            reasoning_effort=str(data["reasoning_effort"]),
            sandbox=str(data["sandbox"]),
            approval_policy=str(data["approval_policy"]),
            search=bool(data["search"]),
        )
        for role, data in DEFAULT_ROLE_AGENTS.items()
    }


def _as_agents(value: Any) -> dict[str, AgentConfig]:
    merged = _default_agents()
    if not isinstance(value, dict):
        return merged
    for role, raw in value.items():
        role_key = str(role)
        base = merged.get(role_key, AgentConfig())
        if not isinstance(raw, dict):
            continue
        merged[role_key] = AgentConfig(
            model=str(raw.get("model", base.model)),
            reasoning_effort=str(raw.get("reasoning_effort", base.reasoning_effort)),
            sandbox=str(raw.get("sandbox", base.sandbox)),
            approval_policy=str(raw.get("approval_policy", base.approval_policy)),
            search=bool(raw.get("search", base.search)),
        )
    return merged


def load_config(root: Path) -> ProjectConfig:
    path = root / "multiagent.toml"
    if not path.exists():
        return ProjectConfig()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    codex_data = data.get("codex", {})
    negotiation_data = data.get("negotiation", {})
    implementation_data = data.get("implementation", {})
    review_data = data.get("review", {})
    safety_data = data.get("safety", {})
    return ProjectConfig(
        codex=CodexConfig(
            binary=str(codex_data.get("binary", "codex")),
            search=bool(codex_data.get("search", False)),
            skip_git_repo_check=bool(codex_data.get("skip_git_repo_check", True)),
            agent_timeout_seconds=int(codex_data.get("agent_timeout_seconds", 900)),
        ),
        negotiation=NegotiationConfig(
            max_rounds=int(negotiation_data.get("max_rounds", 2))
        ),
        implementation=ImplementationConfig(
            l1_retry_limit=int(implementation_data.get("l1_retry_limit", 3)),
            check_timeout_seconds=int(
                implementation_data.get("check_timeout_seconds", 300)
            ),
        ),
        review=ReviewConfig(
            max_concurrency=int(review_data.get("max_concurrency", 4)),
        ),
        safety=SafetyConfig(
            network_access=bool(safety_data.get("network_access", False)),
            dangerous_approval_policy=str(
                safety_data.get("dangerous_approval_policy", "on-request")
            ),
        ),
        agents=_as_agents(data.get("agents")),
    )


def render_default_config() -> str:
    return """[agents.orchestrator]
model = "gpt-5.4-mini"
reasoning_effort = "low"
sandbox = "read-only"
approval_policy = "never"
search = false

[agents.generator]
model = "gpt-5.3-codex"
reasoning_effort = "medium"
sandbox = "workspace-write"
approval_policy = "on-request"
search = false

[agents.evaluator]
model = "gpt-5.4"
reasoning_effort = "medium"
sandbox = "read-only"
approval_policy = "never"
search = false

[agents.reviewer]
model = "gpt-5.4-mini"
reasoning_effort = "medium"
sandbox = "read-only"
approval_policy = "never"
search = false

[codex]
binary = "codex"
search = false
skip_git_repo_check = true
agent_timeout_seconds = 900

[negotiation]
max_rounds = 2

[implementation]
l1_retry_limit = 3
check_timeout_seconds = 300

[review]
max_concurrency = 4

[safety]
network_access = false
dangerous_approval_policy = "on-request"
"""
