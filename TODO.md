# codex-ma TODO

更新时间：2026-04-24

- [ ] 把各个 agent 配置设置为项目级 `codex-ma`，而不是 `codex` 全局级。
- [ ] 修改 agent 配置，使性能与额度消耗达到平衡。
- [x] 理清同一个 profile 下的 agent 上下文是否共享，还是纯靠落盘的 JSON 文件实现信息传递。
  结论：当前 `codex-ma` 中，同一个 profile 不自动共享上下文；`profile` 只是 `~/.codex/config.toml` 里的配置别名。任务连续性主要依赖 `manifest.json`、`sprint-xxx.json`、`events.jsonl` 和 `project_workspace/.codex-ma/.../artifacts/*.json` 落盘，再由编排器在下一次 `codex exec` 时把这些状态重新注入 prompt。虽然代码会记录 `session_id`，但当前实现没有真正把旧会话恢复到后续调用里。
