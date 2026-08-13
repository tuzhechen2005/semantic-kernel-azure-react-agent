import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Phi3GenerationConfig:
    n_ctx: int = 4096
    n_gpu_layers: int = -1
    max_tokens: int = 256
    temperature: float = 0.0
    top_p: float = 1.0
    seed: int = 42
    n_threads: int | None = None
    stop: tuple[str, ...] = (
        "<|end|>",
        "\nObservation:",
        "\n\nObservation:",
        "\n- response from tool:",
        "\n\n- response from tool:",
        "\n- response:",
        "\n\n- response:",
        "\n\nThought:",
    )


class LocalPhi3Model:
    """Async adapter around the synchronous llama-cpp-python API."""

    def __init__(
        self,
        model_path: Path,
        config: Phi3GenerationConfig | None = None,
        *,
        verbose: bool = True,
    ) -> None:
        resolved_path = model_path.expanduser().resolve()
        if not resolved_path.is_file():
            raise FileNotFoundError(f"Phi-3 模型文件不存在：{resolved_path}")

        # A Metal-enabled llama.cpp build still discovers the Metal backend
        # when n_gpu_layers is zero. In GPU-less sandboxes that discovery can
        # fail before the CPU context is created, so explicitly hide Metal
        # devices for the opt-in CPU mode.
        effective_config = config or Phi3GenerationConfig()
        if effective_config.n_gpu_layers == 0:
            os.environ["GGML_METAL_DEVICES"] = "none"

        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise RuntimeError(
                "当前虚拟环境未安装 llama-cpp-python。请先安装带 Metal "
                "支持的 llama-cpp-python==0.3.34。"
            ) from exc

        self.model_path = resolved_path
        self.config = effective_config

        load_options: dict[str, Any] = {
            "model_path": str(self.model_path),
            "n_ctx": self.config.n_ctx,
            "n_gpu_layers": self.config.n_gpu_layers,
            "seed": self.config.seed,
            "verbose": verbose,
        }
        if self.config.n_threads is not None:
            load_options["n_threads"] = self.config.n_threads

        self._llm = Llama(**load_options)

    async def generate(self, prompt: str) -> str:
        if not prompt.strip():
            raise ValueError("Prompt 不能为空")

        return await asyncio.to_thread(self._generate_sync, prompt)

    def _generate_sync(self, prompt: str) -> str:
        response = self._llm(
            prompt,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            top_p=self.config.top_p,
            seed=self.config.seed,
            stop=list(self.config.stop),
            echo=False,
        )

        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("llama.cpp 返回结果中没有 choices")

        text = choices[0].get("text")
        if not isinstance(text, str):
            raise RuntimeError("llama.cpp 返回的文本格式无效")

        return text.strip()
