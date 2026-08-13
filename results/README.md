# 运行记录目录

CLI 和真实模型冒烟测试会在本目录追加 JSONL 运行记录。运行时文件使用 `*.jsonl`，已被 `.gitignore` 排除，避免将本机绝对模型路径、调试 Prompt 或大量原始输出误放入源码包。

每一行是一次独立运行，主要字段包括：

- `runId`、UTC 起止时间与延迟
- 用户问题、最终状态、答案和错误
- 模型文件、推理后端、Metal 加速和生成参数
- 每一步完整 Prompt、原始模型输出、Thought、Action、Action Input、Observation 和步骤结果

步骤结果 `outcome` 可能为 `action`、`final`、`parse_error`、`protocol_error`、`model_error` 或 `answer_error`。其中格式和协议错误会保留原始输出，并以结构化 Observation 回填给模型；因此一次运行即使最终成功，也可能包含有价值的恢复过程。

生成记录：

```bash
python -m src.cli --model /path/to/model.gguf
python -m src.react_smoke_test --model /path/to/model.gguf
```

此目录不附带人工编写或修改的示例 trace；验收者运行命令后会得到真实记录。
