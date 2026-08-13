# Semantic Kernel Azure 文档问答 ReAct 智能体开发路线

## 1. 交付目标

构建一个完全本地运行的命令行智能体：用户提出 Azure 架构问题后，智能体通过 ReAct 循环自主调用 Semantic Kernel 本地文档插件，检索和读取本地技术文档，最终给出带来源依据的答案。

项目不连接 Azure、OpenAI 或其他外部推理服务，不需要云服务访问凭证。

## 2. MVP 范围

第一版只实现形成完整闭环所需的能力：

1. 使用 `llama-cpp-python` 加载本地 Phi-3 Mini GGUF，并通过 Apple Metal 推理。
2. 使用 Semantic Kernel 注册两个本地插件函数：
   - `search_documents(query, top_k)`：检索本地 Azure 文档片段。
   - `read_document(document_id)`：读取指定文档。
3. 使用受控 ReAct 状态机解析模型输出并调用插件。
4. 提供终端多轮问答循环。
5. 将每一步 Thought、Action、Action Input、Observation 和 Final Answer 写入 JSONL trace。
6. 设置最大步骤数、有限格式容错、严格动作校验和错误处理，避免无限循环或执行未知工具。

## 3. 技术路线

```text
本地 Azure Markdown/TXT 文档
        ↓ 加载、切块、建立关键词索引
Semantic Kernel 本地检索插件
        ↑                  ↓
用户问题 → ReAct Prompt → 本地 Phi-3 GGUF
                         ↓
          格式规范化 + 严格校验 Action / Final Answer
                         ↓
              插件 Observation 回填 Prompt
                         ↓
                 最终答案 + 来源 + Trace
```

### 3.1 为什么不使用 Semantic Kernel 自动函数调用

本任务明确要求模型遵循 ReAct 的思考、行动、观察循环，并由程序解析动作指令。Phi-3 Mini GGUF 也不提供稳定的原生 function-calling 协议，因此第一版采用显式文本 ReAct 与程序控制循环，而不是依赖自动函数调用。

### 3.2 为什么不使用 Ollama

Task 1 已验证 `llama-cpp-python 0.3.34`、GGUF 模型和 Metal 环境。Task 2 直接复用该推理栈，避免重新下载模型和引入第二套本地服务。Semantic Kernel 负责插件注册与调用，`llama-cpp-python` 负责模型推理。

### 3.3 检索方案

MVP 先采用不需要嵌入模型的本地词法检索，并保留可替换接口。这样无需额外下载模型或访问外部服务，能够优先验证 ReAct 自主检索闭环。后续可增加 BM25、TF-IDF 或本地 embedding 对照实验。

## 4. 分阶段开发

### 阶段 0：环境与项目骨架

- 创建独立 Python 3.11 ARM64 虚拟环境。
- 安装并锁定 Semantic Kernel。
- 通过最小测试确认 `Kernel` 和 `@kernel_function` 可用。
- 通过配置引用 Task 1 的 GGUF，不复制模型文件。

完成标准：可以注册并由 Kernel 手动调用一个本地函数。

### 阶段 1：本地文档检索插件

- 准备少量本地 Azure 文档。
- 实现文档加载、切块和检索。
- 实现 Semantic Kernel 插件。
- 编写检索单元测试。

完成标准：给定查询能稳定返回正确文档片段及来源标识。

### 阶段 2：ReAct 冒烟闭环

- 设计状态明确、格式受控的 ReAct Prompt。
- 实现动作解析器。
- 实现最大步数受控循环。
- 用一个固定问题完成 `Action → Observation → Final Answer`。

完成标准：真实 Metal 推理能够自主调用至少一次检索插件，并基于 Observation 回答。

### 阶段 3：CLI 与可靠性

- 构建终端交互循环。
- 增加 `exit`、空输入、未知动作、参数错误和超步数处理。
- 保存逐轮 trace 和运行元数据。
- 要求答案引用本地来源，不允许无依据回答。

完成标准：用户可连续提问，单次失败不会终止整个程序。

### 阶段 4：测试、文档与打包

- 完成解析器、检索器、插件和循环控制测试。
- 编写 README、依赖文件和复现命令。
- 记录限制与后续改进。
- 制作不含模型和虚拟环境的 ZIP。

完成标准：新环境按 README 可复现，提交包通过完整性检查。

## 5. 开发原则

- 先完成最小闭环，再扩充文档和检索算法。
- 原始模型输出与每步工具调用必须保留，不手工修改。
- 推理调用成功不等于问答成功。
- 解析器只规范化无歧义的表面格式，不静默修复未知动作、参数值或越权路径。
- 本地文档插件只能访问配置的文档根目录。
- 每次主要实验只改变一个变量，并使用独立结果文件。
- 每完成一个阶段更新 `docs/work_log.md`。

## 6. 当前完成状态

- 阶段 0：完成。
- 阶段 1：完成，3 篇文档共生成 16 个章节块，两个插件函数已通过 Semantic Kernel 调用。
- 阶段 2：完成，真实 Phi-3 + Metal 已跑通 `搜索 → 阅读 → 最终答案` 三步闭环。
- 阶段 3：完成，已实现交互 CLI、严格错误处理、来源校验和 JSONL trace。
- 阶段 4：完成，单元测试、README、工作日志和无模型源码打包流程均已补齐。

后续增强不属于本次 MVP：扩充 Azure 文档语料、加入 BM25/本地 embedding 检索，并建立多问题问答评测集。
