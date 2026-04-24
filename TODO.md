# codex-ma TODO

更新时间：2026-04-24

- [x] 把各个 agent 配置设置为项目级 `codex-ma`，而不是 `codex` 全局级。
  结论：当前配置已从 `[profiles]` 改为项目根目录 `multiagent.toml` 的 `[agents.<role>]`，运行时直接展开为 `codex exec -m/-s/-a/-c` 参数，不再依赖全局 `~/.codex/config.toml` profile。
- [x] 修改 agent 配置，使性能与额度消耗达到平衡。
  结论：默认只让 generator 使用 `gpt-5.3-codex` + `medium` reasoning 做代码修改；evaluator 使用 `gpt-5.4` + `medium` reasoning 负责合同与最终把关；并发量大的 reviewer 和轻量 orchestrator 使用 `gpt-5.4-mini`，其中 orchestrator 降到 `low` reasoning。generator、evaluator、reviewer 默认开启 search，orchestrator 保持关闭。
- [ ] 优化多轮 sprint 的逻辑：可以提前告知 agent 任务可分阶段执行（暂定，后续需讨论方案），防止第一轮 negotiate 后生成过大过细的 plan，导致第一轮负担极重。
- [ ] 优化 agent session 复用问题：当前 `exec resume` 无法携带 schema，复用的会话无法支持结构化输出。
- [x] 理清同一个 profile 下的 agent 上下文是否共享，还是纯靠落盘的 JSON 文件实现信息传递。
  结论：当前 `codex-ma` 中，同一个 profile 不自动共享上下文；`profile` 只是 `~/.codex/config.toml` 里的配置别名。任务连续性主要依赖 `manifest.json`、`sprint-xxx.json`、`events.jsonl` 和 `project_workspace/.codex-ma/.../artifacts/*.json` 落盘，再由编排器在下一次 `codex exec` 时把这些状态重新注入 prompt。虽然代码会记录 `session_id`，但当前实现没有真正把旧会话恢复到后续调用里。
