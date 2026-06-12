"""Florence, Whisper, PDF visual extraction, and Qwen reranker inference."""

from __future__ import annotations

import json
import gc
import os
import sys
import threading
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import torch

from inference_device import resolve_torch_device

DEVICE = resolve_torch_device()

FLORENCE_MODEL_PATH = Path(
    os.getenv("FLORENCE_MODEL_PATH", "/models/florence-2-large")
)
WHISPER_MODEL_PATH = Path(
    os.getenv("WHISPER_MODEL_PATH", "/models/whisper-large-v3-turbo")
)
RERANKER_MODEL_PATH = Path(
    os.getenv("RERANKER_MODEL_PATH", "/models/qwen3-reranker-0.6b")
)

PDF_VISUAL_EXTRACTION_ENABLED = (
    os.getenv("PDF_VISUAL_EXTRACTION_ENABLED", "true").lower() == "true"
)
PDF_VISUAL_EXTRACTION_MAX_PAGES = int(
    os.getenv("PDF_VISUAL_EXTRACTION_MAX_PAGES", "0")
)
PDF_VISUAL_RENDER_DPI = int(os.getenv("PDF_VISUAL_RENDER_DPI", "144"))
PDF_VISUAL_TEXT_THRESHOLD = int(os.getenv("PDF_VISUAL_TEXT_THRESHOLD", "80"))
# 0 = no downscale. The default keeps regular installs from stalling on huge PDF embeds.
FLORENCE_MAX_IMAGE_PIXELS = int(os.getenv("FLORENCE_MAX_IMAGE_PIXELS", "1500000"))

_SYSTEM_PROMPT = (
    "Judge whether the Document meets the requirements based on the Query and the "
    'Instruct provided. Note that the answer can only be "yes" or "no".'
)
_INSTRUCTION = "Given a question, retrieve relevant passages that answer the question"
_PROMPT_TEMPLATE = (
    "<|im_start|>system\n{system}\n<|im_end|>\n"
    "<|im_start|>user\n"
    "<Instruct>: {instruction}\n"
    "<Query>: {query}\n\n"
    "<Document>: {document}\n"
    "<|im_end|>\n"
    "<|im_start|>assistant\n<think>\n\n</think>\n"
)


class LocalModelsEngine:
    """Lazy-loaded local model bundle for ingestion and retrieval helpers."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._florence_model = None
        self._florence_processor = None
        self._whisper_model = None
        self._whisper_processor = None
        self._reranker_model = None
        self._reranker_tokenizer = None
        self._yes_token_id: int | None = None
        self._no_token_id: int | None = None

    def _unload_except(self, keep: str) -> None:
        """Keep memory bounded by allowing only one heavy model family at a time."""
        changed = False
        if keep != "florence" and self._florence_model is not None:
            self._florence_model = None
            self._florence_processor = None
            changed = True
        if keep != "whisper" and self._whisper_model is not None:
            self._whisper_model = None
            self._whisper_processor = None
            changed = True
        if keep != "reranker" and self._reranker_model is not None:
            self._reranker_model = None
            self._reranker_tokenizer = None
            self._yes_token_id = None
            self._no_token_id = None
            changed = True
        if changed:
            gc.collect()

    def unload(self, family: str | None = None) -> dict[str, Any]:
        """Unload one model family, or all local models when no family is given."""
        family = family.lower() if family else None
        valid_families = {None, "florence", "whisper", "reranker"}
        if family not in valid_families:
            raise ValueError("family must be one of: florence, whisper, reranker")

        with self._lock:
            if family is None:
                self._unload_except("")
            elif family == "florence":
                self._florence_model = None
                self._florence_processor = None
                gc.collect()
            elif family == "whisper":
                self._whisper_model = None
                self._whisper_processor = None
                gc.collect()
            elif family == "reranker":
                self._reranker_model = None
                self._reranker_tokenizer = None
                self._yes_token_id = None
                self._no_token_id = None
                gc.collect()

            return {
                "loaded": {
                    "florence": self._florence_model is not None,
                    "whisper": self._whisper_model is not None,
                    "reranker": self._reranker_model is not None,
                }
            }

    def _load_florence(self) -> None:
        if self._florence_model is not None:
            return
        with self._lock:
            if self._florence_model is not None:
                return
            self._unload_except("florence")
            from transformers import AutoModelForCausalLM, AutoProcessor

            model_path = str(FLORENCE_MODEL_PATH)
            self._patch_florence_config_file(model_path)
            self._patch_florence_remote_code(model_path)
            print(f"Loading Florence from {model_path} on {DEVICE}...", flush=True)
            self._florence_model = (
                AutoModelForCausalLM.from_pretrained(
                    model_path, trust_remote_code=True
                )
                .to(DEVICE)
                .eval()
            )
            self._florence_processor = AutoProcessor.from_pretrained(
                model_path, trust_remote_code=True
            )
            self._patch_florence_generation_config()
            print("Florence loaded.", flush=True)

    def _load_whisper(self) -> None:
        if self._whisper_model is not None:
            return
        with self._lock:
            if self._whisper_model is not None:
                return
            self._unload_except("whisper")
            from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor

            model_path = str(WHISPER_MODEL_PATH)
            print(f"Loading Whisper from {model_path} on {DEVICE}...", flush=True)
            self._whisper_model = (
                AutoModelForSpeechSeq2Seq.from_pretrained(model_path)
                .to(DEVICE)
                .eval()
            )
            self._whisper_processor = AutoProcessor.from_pretrained(model_path)
            print("Whisper loaded.", flush=True)

    def _load_reranker(self) -> None:
        if self._reranker_model is not None:
            return
        with self._lock:
            if self._reranker_model is not None:
                return
            self._unload_except("reranker")
            from transformers import AutoModelForCausalLM, AutoTokenizer

            model_path = str(RERANKER_MODEL_PATH)
            if not RERANKER_MODEL_PATH.is_dir():
                raise RuntimeError(f"Reranker model directory not found: {model_path}")

            print(f"Loading reranker from {model_path}...", flush=True)
            self._reranker_tokenizer = AutoTokenizer.from_pretrained(model_path)
            self._reranker_model = AutoModelForCausalLM.from_pretrained(
                model_path,
                dtype=torch.float32,
            ).eval()
            self._yes_token_id = self._reranker_tokenizer.encode(
                "yes", add_special_tokens=False
            )[-1]
            self._no_token_id = self._reranker_tokenizer.encode(
                "no", add_special_tokens=False
            )[-1]
            print("Reranker loaded.", flush=True)

    def _patch_florence_config_file(self, model_path: str) -> None:
        config_path = os.path.join(model_path, "config.json")
        if not os.path.exists(config_path):
            return
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            text_config = config.setdefault("text_config", {})
            changed = False
            if "forced_bos_token_id" not in text_config:
                text_config["forced_bos_token_id"] = text_config.get("bos_token_id", 0)
                changed = True
            if "forced_eos_token_id" not in text_config:
                text_config["forced_eos_token_id"] = text_config.get("eos_token_id", 2)
                changed = True
            if "decoder_start_token_id" not in text_config:
                text_config["decoder_start_token_id"] = text_config.get(
                    "eos_token_id", 2
                )
                changed = True
            if changed:
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=2)
                    f.write("\n")
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    def _patch_florence_remote_code(self, model_path: str) -> None:
        patch_marker = "# LiveOS compatibility: transformers 5 may omit forced_bos_token_id"
        insertion = (
            f"        {patch_marker}\n"
            '        if not hasattr(self, "forced_bos_token_id"):\n'
            '            self.forced_bos_token_id = kwargs.get("forced_bos_token_id", None)\n\n'
        )
        paths = [Path(model_path) / "configuration_florence2.py"]
        cache_root = (
            Path.home() / ".cache" / "huggingface" / "modules" / "transformers_modules"
        )
        if cache_root.exists():
            paths.extend(cache_root.glob("**/configuration_florence2.py"))
        target = "        # ensure backward compatibility for BART CNN models\n"
        for path in paths:
            if not path.exists():
                continue
            try:
                source = path.read_text(encoding="utf-8")
                if patch_marker in source or target not in source:
                    continue
                path.write_text(
                    source.replace(target, insertion + target, 1),
                    encoding="utf-8",
                )
            except Exception:  # pylint: disable=broad-exception-caught
                pass

    def _patch_florence_generation_config(self) -> None:
        config_candidates = [
            getattr(self._florence_model, "config", None),
            getattr(self._florence_model, "generation_config", None),
        ]
        model_config = getattr(self._florence_model, "config", None)
        if model_config is not None:
            config_candidates.append(getattr(model_config, "text_config", None))
        language_model = getattr(self._florence_model, "language_model", None)
        if language_model is not None:
            config_candidates.append(getattr(language_model, "config", None))
            config_candidates.append(getattr(language_model, "generation_config", None))
        for cfg in config_candidates:
            if cfg is None:
                continue
            for attr, value in (
                ("forced_bos_token_id", None),
                ("forced_eos_token_id", None),
                ("decoder_start_token_id", getattr(cfg, "bos_token_id", None)),
            ):
                if not hasattr(cfg, attr):
                    setattr(cfg, attr, value)

    def describe_image_path(self, image_path: str) -> str:
        from PIL import Image

        with self._lock:
            self._load_florence()
            image = Image.open(image_path)
            return self.describe_image_path_from_pil(image)

    def describe_image_path_from_pil(self, image) -> str:
        with self._lock:
            self._load_florence()
            if image.mode != "RGB":
                image = image.convert("RGB")
            image = self._resize_for_florence(image)
            prompt = "<MORE_DETAILED_CAPTION>"
            raw = self._florence_processor(text=[prompt], images=[image], return_tensors="pt")
            model_dtype = next(self._florence_model.parameters()).dtype
            inputs = {}
            for key, value in raw.items():
                if value is None:
                    continue
                if torch.is_floating_point(value):
                    inputs[key] = value.to(device=DEVICE, dtype=model_dtype)
                else:
                    inputs[key] = value.to(DEVICE)
            with torch.no_grad():
                generated_ids = self._florence_model.generate(
                    **inputs, max_new_tokens=1024, num_beams=3, use_cache=False
                )
            generated_text = self._florence_processor.batch_decode(
                generated_ids, skip_special_tokens=False
            )[0]
            parsed_answer = self._florence_processor.post_process_generation(
                generated_text, task=prompt, image_size=(image.width, image.height)
            )
            return parsed_answer.get(prompt, "")

    def _resize_for_florence(self, image):
        """Keep pathological PDF-embedded images from monopolizing Florence."""
        if FLORENCE_MAX_IMAGE_PIXELS <= 0:
            return image
        pixels = image.width * image.height
        if pixels <= FLORENCE_MAX_IMAGE_PIXELS:
            return image

        scale = (FLORENCE_MAX_IMAGE_PIXELS / pixels) ** 0.5
        target_size = (
            max(1, int(image.width * scale)),
            max(1, int(image.height * scale)),
        )
        from PIL import Image

        resized = image.copy()
        resampling = getattr(getattr(Image, "Resampling", None), "LANCZOS", 1)
        resized.thumbnail(target_size, resampling)
        return resized

    def transcribe_audio_path(self, audio_path: str) -> str:
        import librosa
        from pydub import AudioSegment

        with self._lock:
            self._load_whisper()
            wav_path = audio_path + ".converted.wav"
            audio_segment = AudioSegment.from_file(audio_path)
            audio_segment = audio_segment.set_frame_rate(16000).set_channels(1)
            audio_segment.export(wav_path, format="wav")
            try:
                audio, _ = librosa.load(wav_path, sr=16000)
                input_features = self._whisper_processor(
                    audio, sampling_rate=16000, return_tensors="pt"
                ).input_features.to(DEVICE)
                generated_ids = self._whisper_model.generate(
                    input_features,
                    generation_config=self._whisper_model.generation_config,
                )
                return self._whisper_processor.batch_decode(
                    generated_ids, skip_special_tokens=True
                )[0]
            finally:
                if os.path.exists(wav_path):
                    os.remove(wav_path)

    def _pdf_page_needs_visual_description(self, page, native_text: str) -> bool:
        if not PDF_VISUAL_EXTRACTION_ENABLED:
            return False
        if len(native_text.strip()) < PDF_VISUAL_TEXT_THRESHOLD:
            return True
        try:
            if page.get_images(full=True):
                return True
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        try:
            if page.get_drawings():
                return True
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        return False

    def _describe_pdf_page_render(self, page) -> str:
        import fitz
        from PIL import Image

        dpi = max(PDF_VISUAL_RENDER_DPI, 72)
        zoom = dpi / 72
        pixmap = page.get_pixmap(
            matrix=fitz.Matrix(zoom, zoom),
            alpha=False,
            annots=True,
        )
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        return self.describe_image_path_from_pil(image)

    def extract_pdf_path(self, pdf_path: str) -> str:
        from io import BytesIO

        import fitz
        from PIL import Image

        with self._lock:
            extracted_pages = []
            doc = fitz.open(pdf_path)
            try:
                for i, page in enumerate(doc, start=1):
                    native_text = page.get_text().strip()
                    page_parts = [f"--- Page {i} ---"]
                    image_descriptions: list[str] = []

                    if native_text:
                        page_parts.append(f"Native text:\n{native_text}")

                    if PDF_VISUAL_EXTRACTION_ENABLED:
                        for image_index, image_info in enumerate(
                            page.get_images(full=True), start=1
                        ):
                            xref = image_info[0]
                            try:
                                extracted = doc.extract_image(xref)
                                image_bytes = extracted.get("image")
                                if not image_bytes:
                                    continue
                                image = Image.open(BytesIO(image_bytes))
                                description = self.describe_image_path_from_pil(image)
                            except Exception:  # pylint: disable=broad-exception-caught
                                continue
                            if description:
                                image_descriptions.append(
                                    f"Image {image_index}: {description}"
                                )

                    if image_descriptions:
                        page_parts.append(
                            "Image descriptions:\n" + "\n".join(image_descriptions)
                        )

                    if native_text or image_descriptions:
                        extracted_pages.append("\n\n".join(page_parts))
            finally:
                doc.close()

        full_text = "\n\n".join(extracted_pages).strip()
        if not full_text:
            return "PDF contains no extractable native or visual content."
        return full_text

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            self._load_reranker()
            results = []
            with torch.no_grad():
                for idx, doc in enumerate(documents):
                    prompt = _PROMPT_TEMPLATE.format(
                        system=_SYSTEM_PROMPT,
                        instruction=_INSTRUCTION,
                        query=query,
                        document=doc[:1500],
                    )
                    inputs = self._reranker_tokenizer(
                        prompt,
                        return_tensors="pt",
                        truncation=True,
                        max_length=2048,
                    )
                    outputs = self._reranker_model(**inputs)
                    last_logits = outputs.logits[0, -1, :]
                    yes_no_logits = torch.stack(
                        [last_logits[self._yes_token_id], last_logits[self._no_token_id]]
                    )
                    probs = torch.softmax(yes_no_logits, dim=0)
                    results.append(
                        {
                            "index": idx,
                            "text": doc,
                            "relevance_score": float(probs[0]),
                        }
                    )
        results.sort(key=lambda item: item["relevance_score"], reverse=True)
        if top_n is not None:
            results = results[:top_n]
        return results


engine = LocalModelsEngine()
