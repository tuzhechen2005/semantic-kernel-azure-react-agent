import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from semantic_kernel import Kernel

from src.azure_document_plugin import AzureDocumentPlugin
from src.document_store import DocumentStore
from src.local_phi3_model import LocalPhi3Model, Phi3GenerationConfig
from src.react_prompt import build_react_prompt
from src.react_runner import ReactRunResult, ReactRunner
from src.trace_writer import append_trace_record, build_trace_record


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_PATH = (
    PROJECT_ROOT.parent
    / "phi3-azure-tool-benchmark"
    / "models"
    / "Phi-3-mini-4k-instruct-q4.gguf"
)
DEFAULT_TRACE_PATH = PROJECT_ROOT / "results" / "react_runs.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Local Semantic Kernel Azure documentation ReAct agent."
    )
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--question", help="Run one question and exit.")
    parser.add_argument("--max-steps", type=int, default=5)
    parser.add_argument(
        "--max-parse-retries",
        type=int,
        default=2,
        help="Maximum consecutive ReAct format correction attempts.",
    )
    parser.add_argument("--trace-output", type=Path, default=DEFAULT_TRACE_PATH)
    parser.add_argument("--verbose-model", action="store_true")
    parser.add_argument(
        "--cpu",
        action="store_true",
        help="Disable Metal offload and run inference on CPU.",
    )
    return parser.parse_args()


def build_runner(args: argparse.Namespace) -> tuple[ReactRunner, LocalPhi3Model]:
    store = DocumentStore(PROJECT_ROOT / "docs" / "corpus")
    store.load()

    kernel = Kernel()
    kernel.add_plugin(
        AzureDocumentPlugin(store),
        plugin_name="azure_docs",
    )

    model = LocalPhi3Model(
        args.model,
        Phi3GenerationConfig(n_gpu_layers=0 if args.cpu else -1),
        verbose=args.verbose_model,
    )
    runner = ReactRunner(
        kernel=kernel,
        model=model,
        prompt_builder=build_react_prompt,
        max_steps=args.max_steps,
        max_parse_retries=args.max_parse_retries,
    )
    return runner, model


async def run_and_record(
    runner: ReactRunner,
    model: LocalPhi3Model,
    question: str,
    trace_output: Path,
) -> ReactRunResult:
    started_at = datetime.now(timezone.utc)
    result = await runner.run(question)
    finished_at = datetime.now(timezone.utc)

    config = model.config
    record = build_trace_record(
        result,
        started_at_utc=started_at,
        finished_at_utc=finished_at,
        model_metadata={
            "file": model.model_path.name,
            "path": str(model.model_path),
            "backend": "llama-cpp-python",
            "acceleration": (
                "CPU" if config.n_gpu_layers == 0 else "Apple Metal"
            ),
            "generationConfig": {
                "n_ctx": config.n_ctx,
                "n_gpu_layers": config.n_gpu_layers,
                "max_tokens": config.max_tokens,
                "temperature": config.temperature,
                "top_p": config.top_p,
                "seed": config.seed,
                "stop": list(config.stop),
            },
        },
    )
    append_trace_record(trace_output, record)
    return result


def print_result(result: ReactRunResult, trace_output: Path) -> None:
    for step in result.trace:
        if step.outcome == "parse_error":
            print(
                f"[Step {step.step_number}] "
                "模型格式不符合协议，已回填纠错提示。"
            )
        elif step.outcome == "protocol_error":
            print(
                f"[Step {step.step_number}] "
                "动作违反 ReAct 状态约束，未执行并已要求模型纠正。"
            )
        elif step.outcome == "model_error":
            print(f"[Step {step.step_number}] 本地模型生成失败。")
        elif step.outcome == "tool_error":
            print(f"[Step {step.step_number}] 插件调用失败。")
        elif step.action is not None:
            print(
                f"[Step {step.step_number}] Action: "
                f"{step.action} {step.arguments}"
            )
        elif step.outcome == "answer_error":
            print(f"[Step {step.step_number}] Answer validation failed")

    print(f"\n状态：{result.status}")
    if result.answer is not None:
        print(result.answer)
    if result.error is not None:
        print(f"错误：{result.error}")
    print(f"Trace：{trace_output.expanduser().resolve()}")


async def main() -> int:
    args = parse_args()

    print(f"正在加载本地 Phi-3：{args.model}")
    try:
        runner, model = build_runner(args)
    except Exception as exc:
        print(f"模型或插件初始化失败：{exc}")
        if not args.cpu:
            print("如果当前环境无法访问 Metal，可添加 --cpu 进行回退验证。")
        return 2
    print("模型与本地 Azure 文档插件已就绪。")

    if args.question is not None:
        if not args.question.strip():
            print("问题不能为空。")
            return 1
        try:
            result = await run_and_record(
                runner,
                model,
                args.question,
                args.trace_output,
            )
        except Exception as exc:
            print(f"本轮执行失败：{exc}")
            print("程序已安全结束本轮，没有执行未验证的动作。")
            return 1
        print_result(result, args.trace_output)
        return 0 if result.status == "completed" else 1

    print("输入 Azure 技术问题；输入 exit 或 quit 退出。")
    while True:
        try:
            question = input("\nAzure> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            return 0

        if question.lower() in {"exit", "quit"}:
            print("已退出。")
            return 0
        if not question:
            print("问题不能为空。")
            continue

        try:
            result = await run_and_record(
                runner,
                model,
                question,
                args.trace_output,
            )
            print_result(result, args.trace_output)
        except Exception as exc:
            print(f"本轮执行失败：{exc}")
            print("本轮已安全终止，可以继续输入下一个问题。")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
