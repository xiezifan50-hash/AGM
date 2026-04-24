from __future__ import annotations

from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Any
import json
import sys

from codex_ma.config import load_config, resolve_codex_binary
from codex_ma.orchestrator import Orchestrator
from codex_ma.runner import RunnerError, build_runner
from codex_ma.storage import Storage


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(prog="codex-ma", description="Codex 多 Agent Sprint 协作系统")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="初始化工作区")
    subparsers.add_parser("doctor", help="检查工作区和 Codex 环境")

    task_parser = subparsers.add_parser("task", help="任务操作")
    task_subparsers = task_parser.add_subparsers(dest="task_command", required=True)
    create_parser = task_subparsers.add_parser("create", help="创建任务")
    create_parser.add_argument("user_request", help="用户原始需求")
    create_parser.add_argument("--task-id", help="自定义 task id")
    create_parser.add_argument(
        "--workspace",
        required=True,
        help="任务项目空间；内部 agent 只能在此目录内工作",
    )

    run_parser = subparsers.add_parser("run", help="运行任务直到暂停或完成")
    run_parser.add_argument("task_id")

    pause_parser = subparsers.add_parser("pause", help="软暂停任务")
    pause_parser.add_argument("task_id")

    resume_parser = subparsers.add_parser("resume", help="恢复任务")
    resume_parser.add_argument("task_id")

    stop_parser = subparsers.add_parser("stop", help="停止任务并标记为 aborted")
    stop_parser.add_argument("task_id")

    status_parser = subparsers.add_parser("status", help="查看状态")
    status_parser.add_argument("task_id")
    status_parser.add_argument("--json", action="store_true", dest="as_json")

    events_parser = subparsers.add_parser("events", help="查看事件流")
    events_parser.add_argument("task_id")
    events_parser.add_argument("--tail", type=int, default=0)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path.cwd()
    storage = Storage(root)
    config = load_config(root)
    try:
        return dispatch(args, root, storage, config)
    except (FileNotFoundError, ValueError, RunnerError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


def dispatch(args: Namespace, root: Path, storage: Storage, config: Any) -> int:
    if args.command == "init":
        orchestrator = Orchestrator(root, storage, None, config)
        created = orchestrator.init_workspace()
        if created:
            print("已创建: " + ", ".join(created))
        else:
            print("工作区已就绪，无需新增文件。")
        return 0
    if args.command == "doctor":
        return run_doctor(root, storage, config)
    if args.command == "task" and args.task_command == "create":
        orchestrator = Orchestrator(root, storage, None, config)
        result = orchestrator.create_task(
            args.user_request,
            task_id=args.task_id,
            project_workspace=args.workspace,
        )
        print(result["task_id"])
        return 0
    if args.command == "stop":
        orchestrator = Orchestrator(root, storage, None, config)
        result = orchestrator.stop(args.task_id)
        print(render_status(result["manifest"], result["sprint"]))
        return 0
    if args.command == "pause":
        orchestrator = Orchestrator(root, storage, None, config)
        result = orchestrator.pause(args.task_id)
        print(render_status(result["manifest"], result["sprint"]))
        return 0
    runner = build_runner(root, config)
    orchestrator = Orchestrator(root, storage, runner, config)
    if args.command == "run":
        print(f"开始运行任务: {args.task_id}")
        result = orchestrator.run(args.task_id, progress_func=print)
        print("\n== 当前状态 ==")
        print(render_status(result["manifest"], result["sprint"]))
        return 0
    if args.command == "resume":
        print(f"恢复任务: {args.task_id}")
        result = orchestrator.resume(args.task_id, progress_func=print)
        print("\n== 当前状态 ==")
        print(render_status(result["manifest"], result["sprint"]))
        return 0
    if args.command == "status":
        result = orchestrator.status(args.task_id)
        if args.as_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(render_status(result["manifest"], result["sprint"]))
        return 0
    if args.command == "events":
        events = orchestrator.events(args.task_id)
        if args.tail:
            events = events[-args.tail :]
        for event in events:
            print(json.dumps(event, ensure_ascii=False))
        return 0
    raise ValueError(f"未知命令: {args.command}")


def run_doctor(root: Path, storage: Storage, config: Any) -> int:
    checks: list[tuple[str, bool, str]] = []
    resolved_binary = resolve_codex_binary(config.codex.binary)
    checks.append(("codex binary", resolved_binary is not None, resolved_binary or config.codex.binary))
    for role, agent in sorted(config.agents.items()):
        detail = (
            f"model={agent.model}, reasoning={agent.reasoning_effort}, "
            f"sandbox={agent.sandbox}, approval={agent.approval_policy}, search={agent.search}"
        )
        checks.append((f"agent:{role}", True, detail))
    checks.append(("multiagent.toml", (root / "multiagent.toml").exists(), "配置文件"))
    checks.append(("schemas", (root / "schemas").exists(), "schema 目录"))
    checks.append(("runs", (root / "runs").exists(), "运行目录"))
    task_ids = storage.list_task_ids()
    for task_id in task_ids:
        errors = storage.schema_errors(task_id)
        checks.append((f"task:{task_id}", not errors, "; ".join(errors) or "ok"))
    success = True
    for name, ok, detail in checks:
        success = success and ok
        label = "OK" if ok else "FAIL"
        print(f"[{label}] {name}: {detail}")
    return 0 if success else 1


def render_status(manifest: dict[str, Any], sprint: dict[str, Any]) -> str:
    lines = [
        f"task_id: {manifest['task_id']}",
        f"status: {manifest['status']}",
        f"project_workspace: {manifest.get('project_workspace') or '(未绑定)'}",
        f"current_phase: {manifest['current_phase']}",
        f"latest_sprint: {manifest['latest_sprint']}",
        f"resume_reason: {manifest['resume_pointer']['reason_zh']}",
    ]
    human_gate = manifest.get("human_gate", {})
    if human_gate.get("active"):
        lines.append(f"human_gate: {human_gate.get('reason_zh', '')}")
    accepted_contract = sprint["contract"].get("accepted_contract")
    if accepted_contract:
        lines.append(f"accepted_features: {len(accepted_contract.get('features_planned', []))}")
    lines.append(f"review_jobs: {manifest.get('review_queue_summary', {}).get('completed', 0)} completed")
    return "\n".join(lines)
