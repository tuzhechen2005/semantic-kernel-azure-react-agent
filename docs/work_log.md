# Task 2 工作日志

## 2026-08-12

### 1. 接收任务并确定 MVP 技术路线

任务目标：基于 Microsoft Semantic Kernel 开发本地 Azure 技术文档问答 ReAct 命令行智能体，全程不配置外部云服务访问凭证，最终以源码 ZIP 交付。

已确认环境：

- Apple M4，ARM64。
- Python 3.11.15。
- Task 1 环境中的 `llama-cpp-python 0.3.34` 已可通过 Metal 运行 Phi-3 Mini GGUF。
- 当前剩余磁盘约18 GiB。
- 尚未安装 Semantic Kernel。

技术决策：

1. Task 2 使用独立项目和独立虚拟环境，Task 1 保持冻结。
2. 不复制 2.2 GiB 模型，通过配置引用 Task 1 的模型文件。
3. `llama-cpp-python` 负责本地推理，Semantic Kernel 负责注册和调用本地文档插件。
4. 不使用依赖模型原生 function calling 的自动调用；按照任务要求自行解析 ReAct 文本并控制循环。
5. MVP 先使用无需外部 embedding 服务的词法检索，优先打通完整闭环。
6. 每一步 ReAct 交互写入 JSONL trace，并设置最大步骤数。

遇到的问题：首次创建虚拟环境失败，因为目标项目目录尚不存在。

解决方法：先创建项目骨架文件，再创建虚拟环境。

当前状态：技术路线已确定，正在进行环境搭建与 Semantic Kernel 最小接口验证。

下一步：

1. 创建独立 `.venv`。
2. 安装并记录 Semantic Kernel 版本。
3. 编写最小插件注册测试，确认当前 SDK API。

### 2. Semantic Kernel 插件与文档加载冒烟测试

环境结果：

- Semantic Kernel 版本：`1.44.1`。
- `Kernel` 与 `kernel_function` 核心接口导入成功。
- `AzureDocumentPlugin.search_documents` 已成功注册到 Kernel，并通过 `kernel.invoke` 返回模拟结果。
- `requirements.txt` 已按实际环境锁定 `semantic-kernel==1.44.1`。

本地文档库已建立，包含三篇根据 Microsoft Learn 官方内容整理的 Markdown 文档：

```text
docs/corpus/availability_sets.md
docs/corpus/availability_zones.md
docs/corpus/managed_disk_types.md
```

新增 `DocumentStore`，负责校验目录、解析 front matter、检查必填字段与重复 ID，并将文档转换为不可变 `Document` 对象。加载使用临时字典，只有全部文档成功后才更新仓库，避免部分加载状态。

真实运行结果：

```text
成功加载 3 篇文档：
- availability_sets: Azure Virtual Machine Availability Sets (1376 characters)
- availability_zones: Azure Availability Zones (1767 characters)
- managed_disk_types: Azure Managed Disk Types (1849 characters)
```

遇到的问题：VS Code/Pylance 最初未选择 Task 2 的虚拟环境，`semantic_kernel` import 出现黄色波浪线。

解决方法：将 VS Code Python Interpreter 切换到本项目 `.venv/bin/python`，问题解决。运行环境本身始终正常。

当前状态：Semantic Kernel 插件调用和本地文档摄取均已通过冒烟测试。

下一步：按 Markdown 标题将文档切成可独立检索的章节块，并验证块数量、来源与内容。

### 3. 完成 Markdown 章节切块

新增不可变 `DocumentChunk` 数据结构，并在 `DocumentStore.load()` 完成文档加载后，按 Markdown 二级标题 `##` 切分章节。主标题与第一个二级标题之间的导言保存为 `Overview` 块。

真实运行结果：3 篇文档共生成16个非空章节块：

```text
availability_sets: 4块
availability_zones: 5块
managed_disk_types: 7块
总计: 16块
```

每个块均包含唯一 `chunk_id`、文档 ID、文档标题、章节标题、来源 URL 与正文。块 ID 使用 `<document_id>#<index>` 格式。

遇到的问题：首次将块打印代码放在 `main()` 外部，导致局部变量 `store` 在模块作用域不可见并触发 `NameError`。

解决方法：将块打印代码缩进到 `main()` 内、`store.load()` 之后。重新运行成功。

当前状态：文档读取、元数据校验与章节切块均已完成。

下一步：实现确定性的本地词法相关度评分，并用多组查询验证返回章节是否正确。

### 4. 完成本地词法检索冒烟测试

在 `DocumentStore` 中实现确定性词法检索：英文小写化、停用词过滤、简单复数归一、标题/章节/正文加权，以及基于章节文档频率的 IDF 权重。检索返回 `SearchResult`，包含章节块、得分和命中词。

三组真实查询结果：

1. `fault domains and update domains`：前两名分别为 Availability Sets 的 `Update domains` 与 `Fault domains`。
2. `protect virtual machines from datacenter failure`：前两名分别为 Availability Sets 的限制说明和 Availability Zones 的 VM 章节；两者均包含回答所需证据。
3. `disk for backup and infrequently accessed data`：第一名为 Managed Disk Types 的 `Standard HDD`。

观察：第二个查询说明词法相关度不等同于最终语义判断。Availability Sets 章节因同时描述“不能充分抵御数据中心故障”和“应改用 Zones”而排名第一，并非无关结果。因此插件应返回 Top-K 片段，由 ReAct 智能体结合多个 Observation 作答，不能只使用 Top-1 作为最终答案。

当前状态：三类主题均能召回包含答案的相关章节，本地检索 MVP 通过。

下一步：将 `DocumentStore.search()` 和安全的按 ID 阅读能力包装为 Semantic Kernel 插件，并通过 `kernel.invoke` 做真实调用测试。

### 5. Semantic Kernel 真实检索插件调用成功

新增 `AzureDocumentPlugin.search_documents`，使用 `@kernel_function` 注册真实本地检索能力。插件参数使用 `Annotated` 提供类型和语义说明，`top_k` 被限制在1至5之间，以控制 Observation 长度。插件返回结构化 JSON，包含章节 ID、文档 ID、标题、来源、得分、命中词和正文。

通过以下真实链路完成测试：

```text
kernel.invoke
→ azure_docs.search_documents
→ DocumentStore.search
→ SearchResult
→ JSON FunctionResult
```

查询 `disk for backup and infrequently accessed data`、`top_k=2` 的第一条结果为：

```text
chunkId: managed_disk_types#6
section: Standard HDD
score: 17.4161
source: Microsoft Learn / Azure managed disk types
```

返回正文明确说明 Standard HDD 适用于备份、非关键工作负载和低频访问数据，结果正确。

当前状态：Semantic Kernel 已真实参与业务插件注册、参数绑定和执行，不是仅作为依赖或装饰器存在。

下一步：实现只接受文档 ID 的 `read_document`，拒绝任意文件路径，完成第二个本地插件函数。

### 6. 完成安全的完整文档读取插件

新增 `DocumentStore.get_document(document_id)` 与 Semantic Kernel 函数 `AzureDocumentPlugin.read_document`。读取接口只接受已经加载到内存索引中的文档 ID，不接收文件路径，也不将模型输入拼接到文件系统路径中。

验证结果：

- `managed_disk_types` 成功返回完整文档，正文长度1849字符。
- 来源 URL 与标题正确。
- 非法输入 `../../task2` 返回结构化 `document_not_found` 错误和可用文档 ID 列表。
- 非法输入未触发任何文件读取，因此不存在通过该接口进行路径穿越的执行路径。
- `py_compile` 对文档仓库、插件和冒烟测试全部通过。

当前插件能力：

```text
azure_docs.search_documents(query, top_k)
azure_docs.read_document(document_id)
```

当前状态：Task 2 的本地文档工具层已经形成完整最小闭环。

下一步：编写严格 ReAct 输出解析器。先用固定字符串验证 `Action + Action Input` 与 `Final Answer` 两种状态，再接入本地 Phi-3。

### 7. 完成严格 ReAct 输出解析器

新增 `src/react_parser.py`，将单次模型输出严格解析为两种不可变状态：

```text
ReactAction：Thought + Action + 单行 JSON Action Input
ReactFinalAnswer：Thought + 可多行 Final Answer
```

安全与可靠性约束：

- Action 白名单仅包含 `search_documents` 和 `read_document`。
- `Action Input` 必须为合法 JSON 对象。
- 按 Action 分别校验必填参数、允许参数与参数类型。
- `search_documents.top_k` 必须为1至5的整数。
- 拒绝未知 Action、多余参数、空字符串和 Markdown 围栏。
- 解析器不从杂乱输出中猜测或修复工具调用，只有完整符合协议的输出才能进入执行层。

新增 `tests/test_react_parser.py`，覆盖两种合法 Action、多行 Final Answer、未知 Action、Markdown 围栏、多余参数和越界 `top_k` 共7个场景。

验证结果：`py_compile` 通过，7个单元测试全部通过。

当前状态：模型文本与工具执行之间的严格协议闸门已经完成。

下一步：实现 ReAct 循环控制器，并先使用确定性的假模型输出验证 `搜索 → 阅读 → 最终答案` 状态转换、Semantic Kernel 调用和最大步数终止。

### 8. 完成可注入模型的 ReAct 循环控制器

新增 `src/react_runner.py`，通过最小 `TextGenerationModel.generate(prompt)` 协议将循环控制器与具体模型后端解耦。假模型和后续真实 Phi-3 适配器均可使用同一个 Runner。

Runner 的职责：

1. 接收并校验用户问题。
2. 根据问题和历史 Action/Observation 构造每轮 Prompt。
3. 保存原始模型输出并交给严格解析器。
4. 通过 Semantic Kernel 调用白名单插件。
5. 将 Observation 回填到下一轮 transcript。
6. 在 Final Answer、解析失败、插件失败或达到最大步数时确定性终止。

运行状态分为：

```text
completed
max_steps
parse_error
tool_error
```

新增不可变的 `ReactTraceStep` 和 `ReactRunResult`，保存每一步 Prompt、原始模型输出、Thought、Action、参数、Observation 与错误。

新增 `ScriptedModel`，用固定的三轮输出验证以下完整路径：

```text
search_documents
→ Observation进入下一轮Prompt
→ read_document
→ Observation进入下一轮Prompt
→ Final Answer
```

测试还覆盖：非法模型输出立即停止、最大步数终止、Semantic Kernel 插件不存在时返回工具错误。

遇到的问题：将工具错误内部表示由临时 `ReactRunResult` 重构为专用 `ToolInvocationError` 时，异常分支残留旧变量名 `error_step`，工具错误测试触发 `NameError`。

解决方法：将该分支的 outcome 明确设为 `tool_error`，重新运行全部测试。

最终验证：`py_compile` 通过，11个单元测试全部通过。

当前状态：确定性的 ReAct 状态机已完成，项目总体进度约60%。

下一步：编写正式 ReAct Prompt 与 `llama-cpp-python` 本地 Phi-3 适配器，再在本机 Metal 环境运行第一条真实问答。

## 2026-08-13

### 9. 完成正式 ReAct Prompt 与本地 Phi-3 适配器

新增 `src/react_prompt.py`：

- 使用 Phi-3 Instruct 的 `<|system|>`、`<|user|>`、`<|assistant|>` 与 `<|end|>` 模板。
- 首轮强制调用 `search_documents`，未获得 Observation 前禁止直接回答。
- 要求模型只能输出一个 Action 或一个 Final Answer。
- Final Answer 必须使用用户问题的语言，并引用 Observation 中真实出现的来源 URL。
- 禁止编造文档 ID、重复相同动作和输出 Markdown 围栏。

新增 `src/local_phi3_model.py`：

- 用最小 `generate(prompt)` 接口适配 `llama-cpp-python`，无需修改 `ReactRunner`。
- 默认配置与 Task 1 保持一致：`n_ctx=4096`、全部层 Metal offload、`temperature=0`、`top_p=1`、`seed=42`、`max_tokens=256`。
- 使用 `asyncio.to_thread` 包装 llama.cpp 的同步推理，避免阻塞异步 ReAct 控制器。
- 使用延迟导入，使不需要模型的单元测试不依赖 `llama_cpp`。
- 在模型文件不存在、依赖缺失或响应结构异常时显式失败。

新增 `src/react_smoke_test.py`，组装以下真实链路：

```text
本地 Phi-3 GGUF
→ ReactRunner
→ 严格 ReAct Parser
→ Semantic Kernel
→ AzureDocumentPlugin
→ DocumentStore
```

冒烟问题固定为：

```text
Which Azure managed disk type is suitable for backup and infrequently accessed data?
```

模型直接引用 Task 1 的 GGUF 文件，不复制2.2 GiB模型。模型 SHA-256 已再次核对为：

```text
8a83c7fb9049a9b2e92266fa7ad04933bb53aa1e85136b7b30f1b8000ff2edef
```

新增2个 Prompt 测试和1个模型路径测试。当前共14个单元测试，全部通过。历史文档、检索和插件冒烟入口也全部通过。

遇到的问题：正式入口改为 Python 包方式后，`azure_document_plugin.py` 仍使用早期顶层导入 `from document_store import ...`，导致 `ModuleNotFoundError`。

解决方法：统一项目内部使用 `from src...` 包导入，标准运行方式改为 `python -m src.<module>`。修复后全部入口导入和运行成功。

环境问题：Task 2 独立 `.venv` 尚未安装 `llama-cpp-python`。两次自动源码安装均只执行到下载源码包阶段，未进入构建和安装；检查确认包仍不存在。该问题未标记为已解决。

当前状态：真实模型接入代码已完成，等待在本机 VS Code Terminal 安装 Metal 版 `llama-cpp-python==0.3.34` 后运行真实 ReAct 冒烟测试。项目总体进度约70%。

下一步：完成本地依赖安装并运行 `python -m src.react_smoke_test`，根据原始模型输出判断 Prompt、协议或循环是否需要调整。

### 10. 完成 Metal 环境与真实 ReAct 闭环

在 Task 2 独立 `.venv` 中从源码编译并安装 `llama-cpp-python==0.3.34`，确认 Python 与扩展均为 ARM64，`pip check` 无依赖冲突。模型继续复用 Task 1 的 GGUF，未复制进项目。

真实冒烟测试最初暴露了三类问题：

1. 模型在合法 Action 后继续虚构 Observation 和下一轮回答。解决方法是在单步生成配置中加入协议边界 stop sequence，只允许程序产生真实 Observation。
2. 检索结果同时向模型暴露 `chunkId` 和 `documentId`，模型把章节 ID 传给只接受文档 ID 的 `read_document`。解决方法是精简模型可见的搜索返回，仅公开下一步实际需要的 `documentId`、标题、章节、来源和正文；内部评分信息仍由检索层保留。
3. 小模型可能重复完全相同的读取动作。解决方法是在 Runner 中对“动作名 + 规范化 JSON 参数”建立签名，重复动作不再执行，而是返回结构化 `duplicate_action` Observation，引导模型使用已有证据回答。

排查过程中还发现 `managed_disk_types.md` 的 Selecting a disk type 末句在早期写入时被截断。该问题属于语料完整性问题，不是模型错误；补全原始段落后重新运行。

最终真实运行完成三步闭环：

```text
search_documents
→ read_document(managed_disk_types)
→ Final Answer: Standard HDD + Microsoft Learn 来源
```

模型运行日志确认计算层已卸载到 Apple Metal。最终状态为 `completed`。

### 11. 加固答案来源校验

真实输出中的来源 URL 在原文档 URL 后增加了合法章节锚点。最初的逐字符 URL 校验会误判这种引用。最终规则使用 `urldefrag` 比较 scheme、host、path 和 query：允许已观察文档增加片段锚点，但仍拒绝模型发明新域名或新路径。

同时将 Thought 限制为单行，避免额外的 `Action: Final Answer` 被多行正则吞入 Thought。相关正常、恶意域名和错误路径场景均加入单元测试。

### 12. 完成 CLI、JSONL trace 与交付文档

新增终端入口 `src/cli.py`：模型只加载一次，支持连续提问、`exit`/`quit`、空输入处理、单轮异常隔离和 `--question` 单次运行。

新增 `src/trace_writer.py`：每次运行保存 UUID、UTC 时间、延迟、问题、状态、答案、错误、模型元数据与完整步骤 trace。JSONL 使用追加写入，保留原始模型输出，不覆盖历史记录。

CLI 的参数解析、帮助入口、Runner 和 trace writer 已通过静态检查与单元测试。尝试额外执行一次 CLI 真机 Metal 端到端验证时，本地命令的权限审批通道中断并拒绝执行，因此没有生成或伪造 `results/cli_validation.jsonl`。同一模型、Runner、插件和 trace writer 组成的 `react_smoke_test` 已完成真实端到端运行；该限制在日志中如实保留。

新增根目录 `README.md`、`results/README.md`，说明架构、安装、运行、测试、trace schema、安全边界和当前限制。源码交付包不包含 `.venv`、GGUF、缓存或本机运行 trace。

### 13. 正式 CLI 真实模型验证与 CPU 回退

后续获得终端执行条件后，再次通过正式 `src.cli --question` 入口进行端到端验证。自动执行环境不暴露 macOS Metal 设备，详细日志显示：

```text
picking default device: (null)
failed to create command queue
failed to create llama_context
```

这与此前本机终端成功出现 `MTL0` 的结果并不矛盾：失败发生在受限执行环境的 Metal 设备发现阶段，而不是模型文件、Prompt 或 ReAct 逻辑。

为使同一源码也能在 GPU 不可见的沙箱和远程环境中验证，CLI 与冒烟入口新增显式 `--cpu` 回退。仅将 `n_gpu_layers` 设为0仍不够，因为 Metal 版 llama.cpp 会继续发现 Metal 后端；最终在模型导入前设置 `GGML_METAL_DEVICES=none`，确保全部模型层、KV cache 和 compute buffer 使用 CPU。该设置只在用户主动传入 `--cpu` 时生效，默认行为仍是 Metal 全层卸载。

正式 CLI 的 CPU 端到端结果：

```text
exit code: 0
Step 1: search_documents
Step 2: read_document(managed_disk_types)
Step 3: Final Answer
status: completed
answer: Standard HDD
source: https://learn.microsoft.com/en-us/azure/virtual-machines/disks-types#standard-hdd
wall time: 约 27 秒
```

`--cpu` 无需调用者额外设置环境变量，已再次在独立进程中验证。运行产生的真实记录位于 `results/cli_validation_standalone.jsonl`，按交付策略不会收入源码 ZIP。

### 14. 按 Task 2 原文完成最终交付审计

重新按任务四个步骤逐项核验，而不是仅依据单元测试判断完成：

1. 本地推理与 ReAct：正式 Phi-3 GGUF 已真实输出受控 Action，系统 Prompt 明确规定 Thought/Action/Action Input 与 Thought/Final Answer 两种格式，程序产生并回填真实 Observation。
2. Semantic Kernel 插件：两个函数均使用 `@kernel_function` 注册，Runner 通过 `Kernel.invoke` 执行；搜索和读取的内容均来自本地 `docs/corpus`。
3. 终端循环：使用 PTY 真实启动交互模式，看到 `Azure>` 后输入问题，完成三步回答，再次返回 `Azure>`；输入 `exit` 后退出码为0。由此验证模型只加载一次且循环可持续交互，不只是 `--question` 单次入口。
4. 源码 ZIP：重新检查依赖、README、源码、语料与测试，排除 `.venv`、GGUF、缓存、运行 trace 和本机绝对路径；从最终 ZIP 解压副本运行测试和 CLI 帮助入口。

审计中清理了 `document_store.py` 的重复 import，并将 CPU 模式的 Metal 设备屏蔽由 `setdefault` 改为显式赋值，确保用户传入 `--cpu` 时行为确定。

## 2026-08-14

### 15. 根据导师反馈加固 ReAct 协议、插件与解析恢复

导师指出三类可靠性风险：系统提示词对 ReAct 循环约束不足；检索插件缺少空输入、非法参数和异常隔离；解析器对模型的轻微格式偏差过于敏感，解析失败会让整轮问答直接终止。

本轮改动如下：

1. 将 Prompt 明确为状态机。首轮只能调用 `search_documents`；获得程序生成的 Observation 后才能继续读取或回答；模型禁止自行生成 Observation。补充合法/非法示例，并新增 `FORMAT RECOVERY` 状态。
2. 解析器改为“表面格式有限宽容、语义保持严格”。允许标签大小写、全角冒号、列表符号、一个外层代码围栏和多行 JSON；仍拒绝前置解释、未知工具、多余字段、多个动作以及 Action 与 Final Answer 混在同一轮。
3. Runner 遇到解析错误时生成结构化 `format_error` Observation，并在默认最多连续两次的范围内让模型纠正，不再第一次失败就终止。首个成功动作仍必须是检索，未观察到的文档 ID 不能读取，重复动作不会再次执行。
4. 插件增加空查询、非法 `top_k`、超长查询、空/超长文档 ID 和内部异常处理，全部返回统一 JSON 错误。只有 `status=success` 的插件 Observation 才会推进 Runner 的成功状态。
5. CLI 会显示格式纠错、协议错误、模型错误和插件错误，但单轮异常不会使交互程序崩溃。

自动化测试由 23 项扩充至 47 项，`compileall` 与全部单元、集成测试通过。新增边界用例还确认：失败的工具调用可以使用相同参数重试，错误 Observation 不会被误当成最终答案的来源证据。

真实 Phi-3 CPU 回归恰好触发了目标故障：第二轮同时输出 Action 和 Final Answer，被解析器拒绝并回填 `format_error`；第三轮模型按要求修正为单一 Final Answer，最终状态为 `completed`，答案为 Standard HDD，来源 URL 通过 Observation 白名单校验。这证明纠错路径不是只对假模型生效。

完成审计时继续发现并修复两个状态边界：恢复状态现在只取最后一条 Observation 判断，历史中的旧 `format_error` 不会永久污染后续轮次；插件只有返回 `status=success` 后才会将动作记入去重集合并收集文档 ID/来源，失败调用可用相同参数重试，错误响应中的 URL 不能充当答案证据。补齐搜索与读取异常、状态恢复和失败重试测试后，共 47 项测试全部通过。最终再次运行真实 Phi-3 CPU 闭环，模型在第二轮发生格式偏差后成功自我纠正，进程退出码为 0，状态为 `completed`。
