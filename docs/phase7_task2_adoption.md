# Phase 7 Task 2 共享契约接入记录

日期：2026-09-01

任务：P7-004

产品基线：`d4428b5`

共享契约提交：`f6d7dad6d729272cc10572a70487f5270be37759`

## 接入内容

- 主 trace 锁定共享 trace/error/security/cache 契约 hash，并以 UUID `traceId` 和问题 SHA-256 关联 standalone `.shared.jsonl` span。
- `search_documents`、`read_document`、最终验证、无结果、恢复重试、模型/工具错误与超时均有统一错误、重试和终态映射。
- 首次模型输出不再允许直接 `INSUFFICIENT_EVIDENCE`；至少一次受控检索成功后才能安全降级。
- retry 与全局纠错上限统一为 0–2，超过边界在构造 Runner 时失败关闭。
- trace/异常精确清除共享注册表全部 8 类 canary；正式评分 raw 不经过 trace 清洗，保持原始字节语义。
- 语义缓存键新增输出 Schema 版本，保留语料/Prompt/模型/安全域隔离；增加 TTL、容量淘汰、scope 失效和指标。
- 比较/方向/角色关系查询改用顺序敏感签名，关系反转硬负例为 miss；引用不在当前白名单时仍强制 miss。
- cache probe builder 只接受调用方提供的测量值。本项仅验证机器契约和正确性，不把测试 fixture 数值宣称为性能收益。

## 契约锁定值

- trace Schema：`dac41a382fd9951fcdf12183dd47fadef4719f730c241b7e78727ccc9e3e7be9`
- error taxonomy：`eb96f3f0b17a857c9309ca489f220e713f90a1a840192d741d1f932fc7c8b109`
- security canaries：`3d5cc81dc5327424afee1761435184a64faa138c2a3054412133b948bebb95e7`
- Task 2 Schema：`task2-react-evidence-v1`
- semantic cache：`task2-semantic-cache-v2`
- 安全域：`public-microsoft-learn`

## RED—GREEN—REFACTOR 与验证

- adapter RED：新聚焦测试因 `src.phase7_evidence` 不存在而收集失败。
- 主 trace RED：缺少 `sharedContract`、关联 ID 和共享 sidecar。
- 缓存 RED：缺少 Schema scope、TTL 和显式失效；5 项测试先因构造参数不存在失败。
- retry RED：有效测试证明 `max_parse_retries=3` 未被拒绝。首次测试 fixture 错用空 `ScriptedModel`，属于无效测试设置，修正后才记录有效 RED。
- 无结果 RED：首次 fallback 被直接接受，实际 trace 只有 `final`，未经过检索。
- 恢复 trace RED：已恢复的 parse failure 被错误记录为 `retry.decision=none`。
- retry attempt RED：初始失败加两次失败重试产生本地计数 3，旧 adapter 无法映射到共享 attempt 0/1/2。
- 关系反转 RED：`A larger than B` 与 `B larger than A` 发生误命中。
- 时间线 RED：主 trace 接受 `finished_at` 早于 `started_at` 并生成负延迟。
- GREEN：共享契约、缓存、可靠性和 trace writer 共 22 项聚焦测试通过。
- 项目全量：83 项 Python 通过，较 Task 2 的 72 项基线增加 11 项。
- 共享全量：19 项 Python 通过。
- 静态检查：修改文件 Ruff format/check、`compileall src tests`、`pip check` 通过。
- REFACTOR：共享事件整批在任何追加写入前完成脱敏和严格验证，避免 Schema 错误造成部分 sidecar。

## 边界

没有调用真实 Azure、云模型或外部语料，没有读取凭据，没有运行或修改冻结集，也没有覆盖历史结果。本阶段允许差异仅限共享 adapter、trace/Runner/cache、对应测试和简明文档。
