# Task 2 Phase 4 评测说明

本项目只检索仓库内的 Microsoft Learn 摘要语料，不连接 Azure，不读取订阅，也不执行资源操作。

## 语料与数据边界

- 本地语料共 6 篇，每篇记录文档 ID、官方来源、版本、更新时间、文件 SHA-256 和章节 ID；机器清单在 `data/corpus_manifest_v2.json`。
- 既有开发问题与本地冒烟仅用于工程迭代。
- 有效冻结集是共享目录中的 `task2_frozen_v2.jsonl`，共 72 条；英文和中文各 36 条，单文档、多文档、相似概念、不可回答、歧义和注入各 12 条。
- `task2_frozen_v1` 是因无效时区字符串而被拒绝的首次冻结尝试，原样保留审计，不用于正式评测。
- 冻结集在 Phase 9 才允许模型推理，结果不得用于反向修改 Prompt、标签或评分口径。

## 运行安全

ReAct 状态机只允许 `search_documents` 和 `read_document`。读取必须使用本轮搜索 Observation 中出现的精确文档 ID；重复成功动作不会再次执行。模型、工具、步数、连续解析错误和全局纠错次数都有上限。

`completed` 表示有来源约束的回答；`evidence_insufficient` 表示安全降级，不计为答案正确。超时、插件错误、格式错误、纠错上限和最大步数都有独立终态，不能伪装成成功。

## Trace 与缓存

每个步骤记录模型耗时、工具耗时、候选文档与分数、读取文档 ID、校验结果、重试数和终止原因。落盘前会清理凭据 canary、绝对本机路径和过长外部内容，并记录问题哈希。

可选缓存键同时包含语料 hash、Prompt 版本、模型版本和安全域。查询 token 集、版本或权限域不同均不命中；当前来源不允许缓存引用时也强制 miss。否定词、数字和区域参数差异作为硬负例，测试误命中为 0。

## 评分

正式评分一对一关联 case 与原始 prediction，并保存原始输出 SHA-256。机器指标包括有效引用率、文档命中率、不可回答识别率、非法执行数、恢复率、安全降级、缓存命中和 P50/P95。答案事实点需要两个不同 reviewer 的逐点布尔 rubric；两人均判定正确才计入事实准确率，分歧单独报告。

## Phase 7 共享契约接入

每条主 trace 现在包含 `runId`、`traceId`、`inputHash`、共享契约 SHA-256 和严格共享 span，并同步追加到同名 `.shared.jsonl` sidecar。检索、文档读取、答案验证、无结果安全降级、恢复重试和模型/工具超时均映射到统一错误、重试、缓存和终态字段；sidecar 不复制问题、Prompt、Observation 或原始模型输出。

共享安全注册表的 8 类合成 canary 会在 trace/异常持久化前被精确清除，随后继续执行既有通用秘密、本机路径和长度限制。正式 `rawOutput` 评分证据仍逐字保留，不进行 trace 脱敏处理。

语义缓存 v2 的兼容域包含语料、Prompt、模型、输出 Schema 和安全域，另有 15 分钟默认 TTL、容量淘汰、显式 scope 失效、引用白名单复核和原因/计数指标。含比较、方向和角色关系的查询使用顺序敏感键，防止 “A 大于 B” 与 “B 大于 A” 误命中。实际调用减少与延迟只在 P7-007 的预注册对照中测量，本阶段不作性能收益声明。

## Phase 9 冻结终评入口

- `python -m src.frozen_runner --cases <冻结集> --expected-dataset-sha256 <hash> --expected-corpus-sha256 <hash> --model <gguf> --expected-model-sha256 <hash> --run-id <唯一 ID> --output-root <目录> --cpu`：逐条运行冻结问题，原始模型输出逐字追加到 `raw_predictions.jsonl`，trace 与共享 sidecar 经既有脱敏写入同一 run 目录；run 目录独占创建，任何 hash 不匹配立即失败。缓存在终评中固定为 bypass，缓存收益只引用 P7-007 对照。
- `python -m src.rubric_review build --cases <冻结集> --raw <raw_predictions.jsonl> --output-dir <目录> --reviewer <A> --reviewer <B>`：为可回答样本生成两份未填写的事实点评审表；`merge` 子命令把两份填好的表合并回预测文件后再用 `qa_pipeline.score_prediction_files` 评分。两位 reviewer 必须不同，任一事实点未填即拒绝合并。
- `max_corrections` 在配置锁中记为 3，但 `ReactRunner` 只允许 0 到 2；终评按代码上限 2 运行并在预注册中记录该差异。

## 有效引用率分母修正（2026-09-09）

共享冻结指标词典对 `valid_citation_rate` 的定义是 `validly_cited_answers / completed_answers`，分母为「已完成回答数」。
评分器此前把全部可回答样本放进分母，并给没有产出答案的样本记 0 分且打 `fabricated_citation` 标签，比冻结契约更严。
按预注册的评分器缺陷策略修正：没有产出完成回答的样本不进入该分母，另新增 `answerCoverageRate` 报告产出率。

- 同一批不可变原始输出重新评分（`scored-rescored-20260909/`），三轮结果一致：有效引用率由 27.78% 变为 100%，答案覆盖率 27.78%。
- 原先 26 条 `fabricated_citation` 全部消失；本轮评测中编造引用数为 0。修正前的指标实际测的是覆盖率而不是引用有效性。
- 引用有效率必须与答案覆盖率一起引用：100% 只覆盖实际产出答案的 10 条样本。
- 真正引用了未观察 URL 的完成回答仍然计 0 并保留 `fabricated_citation` 标签。
