#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM Feedback Server  -  base model + LoRA adapter
=================================================
Loads the fine-tuned model once at startup and serves inference via a
lightweight FastAPI HTTP API.

Usage:
    python apps/realtime/llm_server.py \
        --adapter-dir outputs/model_gemma2_supervised/lora_adapter \
        --model-id google/gemma-2-9b-it \
        --port 8000

Endpoints:
    GET  /health          -> {"status": "ok", "model_loaded": true}
    POST /generate        -> {"instruction": "...", "input": "..."}
                          <- {"feedback": "...", "score": 3, "latency_s": 0.9}
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import sys
import time
from pathlib import Path
from typing import Optional

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Device / dtype helpers (same logic as test_danube_supervised.py)
# ---------------------------------------------------------------------------

def _pick_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _pick_dtype(device: torch.device) -> torch.dtype:
    if device.type == "cuda":
        return torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    if device.type == "mps":
        return torch.float16
    return torch.float32


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

_DEFAULT_MODEL_ID = "h2oai/h2o-danube3-4b-chat"
_MAX_NEW_TOKENS = 80
_SAFE_CTX = 8192

_model = None
_tokenizer = None
_device: Optional[torch.device] = None
_model_id: str = _DEFAULT_MODEL_ID
_device_report: dict[str, object] = {}


def _read_model_id_from_adapter(adapter_dir: Path) -> Optional[str]:
    cfg = adapter_dir / "adapter_config.json"
    if not cfg.exists():
        return None
    try:
        obj = json.loads(cfg.read_text(encoding="utf-8"))
    except Exception:
        return None
    model_id = obj.get("base_model_name_or_path")
    if isinstance(model_id, str) and model_id.strip():
        return model_id.strip()
    return None


def _build_device_report() -> dict[str, object]:
    report: dict[str, object] = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "torch": getattr(torch, "__version__", "unknown"),
        "torch_cuda_build": getattr(torch.version, "cuda", None),
        "cuda_available": bool(torch.cuda.is_available()),
        "mps_available": bool(
            getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()
        ),
    }

    if torch.cuda.is_available():
        try:
            device_count = torch.cuda.device_count()
        except Exception:
            device_count = 0
        report["cuda_device_count"] = device_count
        devices: list[str] = []
        for idx in range(device_count):
            try:
                devices.append(torch.cuda.get_device_name(idx))
            except Exception:
                devices.append(f"cuda:{idx}")
        report["cuda_devices"] = devices
    return report


def _cpu_fallback_reason(report: dict[str, object]) -> str:
    if report.get("cuda_available"):
        return "CUDA was available, so CPU fallback should not happen here."
    if report.get("torch_cuda_build") is None:
        return "PyTorch build has no CUDA support."
    return "CUDA runtime/driver or GPU visibility is unavailable for this Python environment."


def _log_device_report(report: dict[str, object], device: torch.device) -> None:
    print(f"[LLM] Platform: {report['platform']}")
    print(
        f"[LLM] Python: {report['python']} | torch: {report['torch']} | "
        f"torch CUDA build: {report['torch_cuda_build']}"
    )
    print(
        f"[LLM] CUDA available: {report['cuda_available']} | "
        f"MPS available: {report['mps_available']}"
    )
    if report.get("cuda_devices"):
        print(f"[LLM] CUDA devices: {', '.join(report['cuda_devices'])}")
    if device.type == "cpu":
        print(f"[LLM][warn] Falling back to CPU. Reason: {_cpu_fallback_reason(report)}")


def load_model(adapter_dir: Path, model_id: str, use_4bit: bool = True) -> None:
    global _model, _tokenizer, _device, _model_id, _device_report

    from transformers import AutoTokenizer, AutoModelForCausalLM
    from peft import PeftModel

    _model_id = model_id
    _device = _pick_device()
    _device_report = _build_device_report()
    dtype = _pick_dtype(_device)
    is_darwin = platform.system() == "Darwin"

    _log_device_report(_device_report, _device)
    print(f"[LLM] Device: {_device} | dtype: {dtype}")
    print(f"[LLM] Loading tokenizer from {_model_id} ...")

    try:
        tok = AutoTokenizer.from_pretrained(_model_id, use_fast=True)
    except Exception:
        tok = AutoTokenizer.from_pretrained(_model_id, use_fast=False)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.model_max_length = _SAFE_CTX
    _tokenizer = tok

    print(f"[LLM] Loading base model {_model_id} ...")
    can_4bit = use_4bit and _device.type == "cuda"

    if can_4bit:
        try:
            from transformers import BitsAndBytesConfig
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=dtype if dtype in (torch.float16, torch.bfloat16) else torch.float16,
            )
            base = AutoModelForCausalLM.from_pretrained(
                _model_id,
                device_map="auto",
                quantization_config=bnb_config,
                torch_dtype=dtype,
            )
        except Exception as e:
            print(f"[LLM][warn] 4-bit failed ({e}), falling back to full precision.")
            can_4bit = False

    if not can_4bit:
        base = AutoModelForCausalLM.from_pretrained(
            _model_id,
            torch_dtype=dtype,
            device_map=None,
        ).to(_device)

    print(f"[LLM] Loading LoRA adapter from {adapter_dir} ...")
    if not adapter_dir.exists():
        raise FileNotFoundError(f"Adapter dir not found: {adapter_dir}")

    if can_4bit:
        _model = PeftModel.from_pretrained(base, adapter_dir, device_map="auto")
    else:
        _model = PeftModel.from_pretrained(base, adapter_dir)
        _model.to(_device)

    _model.eval()
    print("[LLM] Model ready [OK]")


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def _build_prompt(instruction: str, user_input: str) -> str:
    user_content = f"{instruction.strip()}\n\n{user_input.strip()}" if user_input else instruction.strip()
    msgs = [{"role": "user", "content": user_content}]
    try:
        return _tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    except Exception:
        return f"[INST] {user_content} [/INST]"


def _extract_score(text: str) -> Optional[int]:
    m = re.search(r"Score:\s*([1-5])", text, re.IGNORECASE)
    return int(m.group(1)) if m else None


@torch.inference_mode()
def _generate(instruction: str, user_input: str) -> tuple[str, Optional[int], float]:
    """Returns (feedback_text, score_int_or_None, latency_s)."""
    prompt = _build_prompt(instruction, user_input)
    inputs = _tokenizer(prompt, return_tensors="pt", truncation=True, max_length=_SAFE_CTX)
    inputs = {k: v.to(_device) for k, v in inputs.items()}

    t0 = time.perf_counter()
    gen = _model.generate(
        **inputs,
        max_new_tokens=_MAX_NEW_TOKENS,
        do_sample=False,
        eos_token_id=_tokenizer.eos_token_id,
        pad_token_id=_tokenizer.pad_token_id,
    )
    latency = time.perf_counter() - t0

    cut = inputs["input_ids"].shape[1]
    out_ids = gen[0][cut:] if gen.shape[1] > cut else gen[0]
    text = _tokenizer.decode(out_ids, skip_special_tokens=True).strip()
    # clean up repeated whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text, _extract_score(text), round(latency, 3)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Polonez LLM Feedback Server")


class GenerateRequest(BaseModel):
    instruction: str
    input: str = ""


class GenerateResponse(BaseModel):
    feedback: str
    score: Optional[int]
    latency_s: float


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model_loaded": _model is not None,
        "model_id": _model_id,
        "device": str(_device) if _device is not None else None,
        "device_report": _device_report,
    }


@app.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    if _model is None:
        raise HTTPException(status_code=503, detail="Model not loaded yet.")
    feedback, score, latency = _generate(req.instruction, req.input)
    return GenerateResponse(feedback=feedback, score=score, latency_s=latency)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Serve a LoRA-adapted local LLM via FastAPI.")
    ap.add_argument(
        "--adapter-dir",
        type=Path,
        default=PROJECT_ROOT / "outputs/manual/danube_4b/model_danube_supervised/lora_adapter",
        help="Path to saved LoRA adapter directory.",
    )
    ap.add_argument(
        "--model-id",
        default=None,
        help="Base model HF id. If omitted, read from adapter_config.json (base_model_name_or_path).",
    )
    ap.add_argument("--port", type=int, default=8000, help="HTTP port (default: 8000)")
    ap.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    ap.add_argument("--no-4bit", action="store_true", help="Disable 4-bit quantization (auto-disabled on non-CUDA).")
    args = ap.parse_args()

    adapter_dir = args.adapter_dir if args.adapter_dir.is_absolute() else (PROJECT_ROOT / args.adapter_dir)
    adapter_dir = adapter_dir.resolve()
    model_id = args.model_id or _read_model_id_from_adapter(adapter_dir) or _DEFAULT_MODEL_ID
    load_model(adapter_dir, model_id=model_id, use_4bit=not args.no_4bit)

    print(f"[LLM] Starting server on {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
