# Semantic Kernel Azure 文档问答 ReAct 智能体

这是一个完全本地运行的命令行问答智能体。它使用 Phi-3 Mini GGUF 生成 ReAct 动作，通过 Microsoft Semantic Kernel 调用本地 Azure 文档插件，再根据检索到的证据生成带来源链接的答案。运行时不连接 Azure、OpenAI 或其他云端推理服务，也不需要云服务凭证。

## 核心链路

```text
用户问题
  → Phi-3 输出 Thought + Action + Action Input
  → 有边界的宽容解析器规范化表面格式并严格校验语义
  → Semantic Kernel 调用 azure_docs 插件
  → 本地文档检索/读取返回 Observation
  → Observation 回填下一轮 Prompt
  → Phi-3 输出带来源的 Final Answer
  → 完整过程写入 JSONL trace
```

Semantic Kernel 在本项目中负责插件注册、参数绑定和真实调用；`ReactRunner` 负责显式的 ReAct 状态机。之所以不使用自动函数调用，是因为任务要求程序解析 Thought/Action/Observation，且本地 Phi-3 GGUF 没有稳定的原生 function-calling 协议。

## 功能

- 本地 Phi-3 Mini Q4 GGUF 推理，支持 Apple Metal 加速。
- `search_documents(query, top_k)`：检索本地 Azure 文档章节。
- `read_document(document_id)`：按白名单文档 ID 读取全文，不接受文件路径。
- 强化的 ReAct 状态协议：首轮必须检索，Observation 只能由程序生成。
- 对大小写、全角冒号、外层代码围栏和多行 JSON 做有限容错；不猜测工具名、字段或参数值。
- 非法格式会作为结构化 Observation 回填给模型，在有限次数内自我纠正。
- 空参数、错误类型、超长输入、最大步数、未知/重复动作、插件异常与来源 URL 均有校验。
- 单次提问和持续终端对话两种运行方式。
- 保存 Prompt、原始输出、Action、Observation、结果和耗时等 JSONL 记录。

## 项目结构

```text
semantic-kernel-azure-react-agent/
├── docs/
│   ├── corpus/                 # 本地 Azure 技术文档
│   └── work_log.md             # 开发过程、问题和解决方法
├── results/
│   └── README.md               # 运行记录格式说明
├── src/
│   ├── azure_document_plugin.py
│   ├── cli.py
│   ├── document_store.py
│   ├── local_phi3_model.py
│   ├── react_parser.py
│   ├── react_prompt.py
│   ├── react_runner.py
│   ├── react_smoke_test.py
│   └── trace_writer.py
├── tests/
├── DEVELOPMENT_ROADMAP.md
└── requirements.txt
```

## 环境要求

- Python 3.11
- macOS Apple Silicon（当前验证环境为 Apple M4）
- 本地 Phi-3 Mini Instruct GGUF 模型
- 建议至少保留 5 GiB 可用磁盘空间

当前验证版本：

```text
semantic-kernel==1.44.1
llama-cpp-python==0.3.34
```

## 安装

在项目根目录执行：

```bash
/opt/homebrew/bin/python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install semantic-kernel==1.44.1
CMAKE_ARGS="-DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_APPLE_SILICON_PROCESSOR=arm64 -DGGML_METAL=on" \
  python -m pip install --no-cache-dir --no-binary=llama-cpp-python llama-cpp-python==0.3.34
```

`requirements.txt` 用于锁定依赖版本；Apple Silicon 上建议使用上面的源码编译命令，确保启用 Metal。

模型文件不包含在源码 ZIP 中。默认路径为相邻 Task 1 项目中的：

```text
../phi3-azure-tool-benchmark/models/Phi-3-mini-4k-instruct-q4.gguf
```

如果模型位于其他目录，运行时传入 `--model`。

默认会将全部模型层卸载到 Apple Metal。如果运行在不暴露 GPU 的沙箱、远程会话或无 Metal 环境中，可以显式添加 `--cpu`；程序会同时隐藏不可用的 Metal 后端并将模型层设为 CPU，不需要额外配置环境变量。它只改变推理后端，不改变 ReAct、Semantic Kernel 插件或 trace 逻辑。

## 运行

交互模式（模型只加载一次，可以连续提问）：

```bash
python -m src.cli --model /absolute/path/to/Phi-3-mini-4k-instruct-q4.gguf
```

单次提问：

```bash
python -m src.cli \
  --model /absolute/path/to/Phi-3-mini-4k-instruct-q4.gguf \
  --max-parse-retries 2 \
  --question "Which Azure managed disk type is suitable for backup and infrequently accessed data?"
```

CPU 回退：

```bash
python -m src.cli \
  --cpu \
  --model /absolute/path/to/Phi-3-mini-4k-instruct-q4.gguf \
  --question "Which Azure managed disk type is suitable for backup and infrequently accessed data?"
```

固定问题的真实模型冒烟测试：

```bash
python -m src.react_smoke_test \
  --model /absolute/path/to/Phi-3-mini-4k-instruct-q4.gguf
```

默认运行记录写入 `results/react_runs.jsonl` 或 `results/react_smoke_trace.jsonl`。可通过 `--trace-output` 指定其他位置。
`--max-parse-retries` 控制连续格式错误的纠正次数，默认值为 2；纠错轮次也计入 `--max-steps`，因此复杂问题可以适当提高总步数。

## 测试

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tests
python -m src.document_store_smoke_test
python -m src.search_smoke_test
python -m src.real_plugin_smoke_test
```

## 已验证结果

真实 Phi-3 + Metal 冒烟测试完成了三步闭环：

1. 调用 `search_documents` 检索低频访问与备份磁盘。
2. 调用 `read_document` 阅读 `managed_disk_types`。
3. 回答 `Standard HDD`，并引用 Observation 中的 Microsoft Learn 来源。

47 项单元与集成测试覆盖了解析器、Prompt、Semantic Kernel 插件、格式恢复、循环终止、失败工具重试、错误证据隔离、重复动作、来源验证、CLI 异常隔离、模型配置和 trace 写入。

## 安全与可靠性设计

- 动作仅允许 `search_documents` 和 `read_document`。
- 每个动作使用独立参数 schema，拒绝多余字段和错误类型。
- 插件对空查询、非法 `top_k`、超长输入和内部异常返回统一 JSON 错误，不把异常抛到交互层。
- 文档读取只查内存索引，不把模型输入拼接成文件路径。
- 相同动作不会重复执行，防止小模型陷入循环。
- 解析失败不会立即结束整轮问答；Runner 会回填格式错误和唯一合法模板，默认最多连续纠正两次。
- Final Answer 必须包含 Observation 中出现过的来源 URL；允许同一文档 URL 增加锚点，但拒绝新域名或新路径。
- 原始模型输出原样保存在 trace 中，失败不会被静默美化。

## 当前限制

- 文档库目前只有三个 Azure VM 主题，适合验证框架闭环，不代表完整 Azure 知识库。
- 检索为确定性词法检索，尚未使用 embedding 或向量数据库。
- Phi-3 Mini Q4 是小型量化模型，偶尔可能偏离输出协议；程序只容忍表现层差异，语义不明确时要求模型重试而不猜测意图。
- 本项目只检索文档，不执行任何真实 Azure 资源操作。

详细技术路线见 `DEVELOPMENT_ROADMAP.md`，开发过程与排障记录见 `docs/work_log.md`。
