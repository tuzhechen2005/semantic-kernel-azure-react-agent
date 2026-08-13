import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from semantic_kernel import Kernel

from src.azure_document_plugin import AzureDocumentPlugin
from src.document_store import DocumentStore
from src.local_phi3_model import LocalPhi3Model, Phi3GenerationConfig
from src.react_prompt import build_react_prompt
from src.react_runner import ReactRunner
from src.trace_writer import append_trace_record, build_trace_record


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_PATH = (
    PROJECT_ROOT.parent
    / "phi3-azure-tool-benchmark"
    / "models"
    / "Phi-3-mini-4k-instruct-q4.gguf"
)
DEFAULT_QUESTION = (
    "Which Azure managed disk type is suitable for backup and "
    "infrequently accessed data?"
)
DEFAULT_TRACE_PATH = PROJECT_ROOT / "results" / "react_smoke_trace.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one real local Phi-3 ReAct smoke test."
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=DEFAULT_MODEL_PATH,
        help="Path to the local Phi-3 GGUF model.",
    )
    parser.add_argument(
        "--question",
        default=DEFAULT_QUESTION,
        help="Azure documentation question to ask.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=4,
        help="Maximum number of ReAct model turns.",
    )
    parser.add_argument(
        "--max-parse-retries",
        type=int,
        default=2,
        help="Maximum consecutive ReAct format correction attempts.",
    )
    parser.add_argument(
        "--verbose-model",
        action="store_true",
        help="Show detailed llama.cpp model loading and performance logs.",
    )
    parser.add_argument(
        "--cpu",
        action="store_true",
        help="Disable Metal offload and run inference on CPU.",
    )
    parser.add_argument(
        "--trace-output",
        type=Path,
        default=DEFAULT_TRACE_PATH,
        help="Append the complete run trace to this JSONL file.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    store = DocumentStore(PROJECT_ROOT / "docs" / "corpus")
    store.load()

    kernel = Kernel()
    kernel.add_plugin(
        AzureDocumentPlugin(store),
        plugin_name="azure_docs",
    )

    print(f"正在加载模型：{args.model}")
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

    print(f"\n问题：{args.question}")
    started_at = datetime.now(timezone.utc)
    result = await runner.run(args.question)
    finished_at = datetime.now(timezone.utc)

    record = build_trace_record(
        result,
        started_at_utc=started_at,
        finished_at_utc=finished_at,
        model_metadata={
            "file": model.model_path.name,
            "path": str(model.model_path),
            "backend": "llama-cpp-python",
            "acceleration": (
                "CPU" if model.config.n_gpu_layers == 0 else "Apple Metal"
            ),
            "generationConfig": {
                "n_ctx": model.config.n_ctx,
                "n_gpu_layers": model.config.n_gpu_layers,
                "max_tokens": model.config.max_tokens,
                "temperature": model.config.temperature,
                "top_p": model.config.top_p,
                "seed": model.config.seed,
                "stop": list(model.config.stop),
            },
        },
    )
    append_trace_record(args.trace_output, record)

    for step in result.trace:
        print(f"\n--- ReAct Step {step.step_number} ---")
        print(step.raw_model_output)
        if step.observation is not None:
            print(f"Observation: {step.observation}")
        if step.error is not None:
            print(f"Error: {step.error}")

    print(f"\n运行状态：{result.status}")
    if result.answer is not None:
        print("最终答案：")
        print(result.answer)
    if result.error is not None:
        print(f"错误：{result.error}")
    print(f"Trace：{args.trace_output.expanduser().resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
