from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import os
import tempfile

from codex_ma.schema import SchemaValidationError, load_schema, validate
from codex_ma.state import relative_path, touch


class Storage:
    def __init__(self, root: Path):
        self.root = root
        self.schemas_dir = root / "schemas"
        self.runs_dir = root / "runs"
        self.tmp_dir = root / "tmp"
        self._schema_cache: dict[Path, dict[str, Any]] = {}

    def ensure_layout(self) -> None:
        (self.root / "src").mkdir(parents=True, exist_ok=True)
        self.schemas_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

    def task_dir(self, task_id: str) -> Path:
        return self.runs_dir / task_id

    def manifest_path(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "manifest.json"

    def events_path(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "events.jsonl"

    def sprint_path(self, task_id: str, sprint_number: int) -> Path:
        return self.task_dir(task_id) / f"sprint-{sprint_number:03d}.json"

    def artifacts_dir(self, task_id: str, sprint_number: int) -> Path:
        return self.task_dir(task_id) / "artifacts" / f"sprint-{sprint_number:03d}"

    def ensure_task_layout(self, task_id: str, sprint_number: int = 1) -> None:
        self.task_dir(task_id).mkdir(parents=True, exist_ok=True)
        self.artifacts_dir(task_id, sprint_number).mkdir(parents=True, exist_ok=True)

    def _load_schema(self, relative: str) -> dict[str, Any]:
        path = self.root / relative
        if path not in self._schema_cache:
            self._schema_cache[path] = load_schema(path)
        return self._schema_cache[path]

    def _write_atomic(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            handle.write(content)
            temp_name = handle.name
        os.replace(temp_name, path)

    def write_json(self, path: Path, payload: dict[str, Any]) -> None:
        touch(payload)
        rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        self._write_atomic(path, rendered)

    def read_json(self, path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def save_manifest(self, task_id: str, manifest: dict[str, Any]) -> None:
        schema = self._load_schema("schemas/manifest.schema.json")
        validate(manifest, schema)
        self.write_json(self.manifest_path(task_id), manifest)

    def load_manifest(self, task_id: str) -> dict[str, Any]:
        return self.read_json(self.manifest_path(task_id))

    def save_sprint(self, task_id: str, sprint: dict[str, Any]) -> None:
        schema = self._load_schema("schemas/sprint-state.schema.json")
        validate(sprint, schema)
        self.ensure_task_layout(task_id, sprint["sprint_number"])
        self.write_json(self.sprint_path(task_id, sprint["sprint_number"]), sprint)

    def load_sprint(self, task_id: str, sprint_number: int) -> dict[str, Any]:
        return self.read_json(self.sprint_path(task_id, sprint_number))

    def append_event(self, task_id: str, event: dict[str, Any]) -> None:
        schema = self._load_schema("schemas/event-log.schema.json")
        validate(event, schema)
        path = self.events_path(task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def read_events(self, task_id: str) -> list[dict[str, Any]]:
        path = self.events_path(task_id)
        if not path.exists():
            return []
        events: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    events.append(json.loads(line))
        return events

    def list_task_ids(self) -> list[str]:
        if not self.runs_dir.exists():
            return []
        result = []
        for child in self.runs_dir.iterdir():
            if child.is_dir() and (child / "manifest.json").exists():
                result.append(child.name)
        return sorted(result)

    def ensure_default_files(self) -> list[str]:
        created: list[str] = []
        for relative in ("runs", "tmp"):
            path = self.root / relative
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
                created.append(relative)
        return created

    def schema_errors(self, task_id: str) -> list[str]:
        errors: list[str] = []
        try:
            manifest = self.load_manifest(task_id)
            validate(manifest, self._load_schema("schemas/manifest.schema.json"))
        except FileNotFoundError:
            errors.append("manifest.json 缺失")
            return errors
        except SchemaValidationError as exc:
            errors.append(f"manifest.json 校验失败: {exc}")
            return errors
        try:
            sprint = self.load_sprint(task_id, manifest["latest_sprint"])
            validate(sprint, self._load_schema("schemas/sprint-state.schema.json"))
        except FileNotFoundError:
            errors.append("最新 sprint 文件缺失")
        except SchemaValidationError as exc:
            errors.append(f"最新 sprint 校验失败: {exc}")
        return errors

    def artifact_file(
        self,
        task_id: str,
        sprint_number: int,
        filename: str,
    ) -> Path:
        path = self.artifacts_dir(task_id, sprint_number) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def relative(self, path: Path) -> str:
        try:
            return relative_path(self.root, path)
        except ValueError:
            return path.as_posix()
