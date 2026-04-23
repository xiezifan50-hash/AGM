from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import shutil
import tomllib

from codex_ma.constants import DEFAULT_DIMENSIONS, DEFAULT_ROLE_PROFILES


@dataclass(slots=True)
class CodexConfig:
    binary: str = "codex"
    search: bool = False
    skip_git_repo_check: bool = True


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
    dimensions: tuple[str, ...] = field(default_factory=lambda: DEFAULT_DIMENSIONS)


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
    profiles: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_ROLE_PROFILES))


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


def codex_profile_exists(profile_name: str) -> bool:
    if not profile_name:
        return False
    config_path = Path("~/.codex/config.toml").expanduser()
    if not config_path.exists():
        return False
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    profiles = data.get("profiles", {})
    return isinstance(profiles, dict) and profile_name in profiles


def _as_tuple(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return default


def _as_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return dict(DEFAULT_ROLE_PROFILES)
    merged = dict(DEFAULT_ROLE_PROFILES)
    for key, raw in value.items():
        merged[str(key)] = str(raw)
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
            dimensions=_as_tuple(review_data.get("dimensions"), DEFAULT_DIMENSIONS),
        ),
        safety=SafetyConfig(
            network_access=bool(safety_data.get("network_access", False)),
            dangerous_approval_policy=str(
                safety_data.get("dangerous_approval_policy", "on-request")
            ),
        ),
        profiles=_as_dict(data.get("profiles")),
    )


def render_default_config() -> str:
    return """[profiles]
orchestrator = "orchestrator_readonly"
generator = "generator_execute"
evaluator = "evaluator"
reviewer = "reviewer"

[codex]
binary = "codex"
search = false
skip_git_repo_check = true

[negotiation]
max_rounds = 2

[implementation]
l1_retry_limit = 3
check_timeout_seconds = 300

[review]
max_concurrency = 4
dimensions = ["correctness", "regression-risk", "api-ux-contract"]

[safety]
network_access = false
dangerous_approval_policy = "on-request"
"""
