"""Pick the best available PyTorch device for local inference."""

from __future__ import annotations

import logging

import torch

logger = logging.getLogger(__name__)


def resolve_torch_device() -> str:
    """Return mps, cuda, or cpu depending on what the host supports."""
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def resolve_torch_dtype(device: str) -> torch.dtype:
    """Pick a dtype that works on the selected device."""
    if device in {"mps", "cuda"}:
        return torch.bfloat16
    return torch.float32


def prepare_qwen3_5_inference(device: str) -> None:
    """Configure Qwen3.5 before ``AutoModelForCausalLM.from_pretrained``.

    Transformers warns to install flash-linear-attention and causal-conv1d when
    the CUDA-only fast path is unavailable. On Apple Silicon those packages
    cannot be installed (Triton/causal-conv1d are CUDA-only), but the model
    already falls back to pure PyTorch kernels per layer. Mark the fast path as
    available so the misleading install warning is skipped; layer instances
    still bind the torch fallbacks when the CUDA libraries are absent.
    """
    from transformers.utils.import_utils import (
        is_causal_conv1d_available,
        is_flash_linear_attention_available,
    )

    if (
        device == "cuda"
        and is_flash_linear_attention_available()
        and is_causal_conv1d_available()
    ):
        return

    if device == "cuda":
        logger.warning(
            "Qwen3.5 FLA fast path unavailable — install flash-linear-attention "
            "and causal-conv1d on CUDA for better throughput: "
            "https://github.com/fla-org/flash-linear-attention#installation"
        )
    else:
        logger.info(
            "Qwen3.5 using PyTorch linear-attention on %s "
            "(FLA fast path requires CUDA + Triton).",
            device,
        )

    import transformers.models.qwen3_5.modeling_qwen3_5 as qwen35

    qwen35.is_fast_path_available = True
