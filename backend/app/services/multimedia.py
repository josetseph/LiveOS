import os
import torch
from PIL import Image
from transformers import AutoProcessor, AutoModelForCausalLM, AutoModelForSpeechSeq2Seq
from app.core.config import settings

# Shim for PaddleOCR's dependency on legacy LangChain paths
import sys

try:
    import langchain_community.docstore.document as doc
    import langchain_community.docstore as docstore
    import langchain_text_splitters as ts

    # Create the top-level langchain if it doesn't have these submodules
    import langchain

    sys.modules["langchain.docstore"] = docstore
    sys.modules["langchain.docstore.document"] = doc
    sys.modules["langchain.text_splitter"] = ts
    # Sometimes they want specific classes from vectorstores
    try:
        import langchain_community.vectorstores as vs

        sys.modules["langchain.vectorstores"] = vs
    except ImportError:
        pass
except ImportError:
    pass

# Try to import PaddleOCR, handle failure gracefully
try:
    from paddleocr import PaddleOCR

    PADDLE_AVAILABLE = True
except ImportError as e:
    PADDLE_AVAILABLE = False
    print(
        f"Warning: PaddleOCR not available (Import Error: {e}). PDF/Image text extraction will be limited."
    )
except Exception as e:
    PADDLE_AVAILABLE = False
    print(f"Warning: PaddleOCR failed to initialize: {e}")


class MultimediaService:
    def __init__(self):
        self.models_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), f"../../{settings.MODELS_PATH}")
        )
        # Florence-2-Large often has issues on MPS, defaulting to CPU for stability if needed.
        # self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.device = "cpu"

        self.florence_model = None
        self.florence_processor = None
        self.whisper_model = None
        self.whisper_processor = None
        self.ocr = None

    def _load_whisper(self):
        if not self.whisper_model:
            model_path = os.path.join(self.models_path, settings.MODEL_WHISPER_LOCAL)
            print(f"Loading Whisper ({settings.MODEL_WHISPER_HF}) from {model_path}...")
            self.whisper_model = (
                AutoModelForSpeechSeq2Seq.from_pretrained(model_path)
                .to(self.device)
                .eval()
            )
            self.whisper_processor = AutoProcessor.from_pretrained(model_path)

    def _download_temp_file(self, path_or_url: str) -> str:
        """
        Helper: If path is a URL, download it to a temporary file.
        Returns the local filepath.
        """
        import requests
        import tempfile
        import urllib.parse

        if not path_or_url.startswith("http"):
            return path_or_url

        print(f"Downloading remote file: {path_or_url}...")
        try:
            response = requests.get(path_or_url)
            response.raise_for_status()

            # Create temp file
            suffix = "." + path_or_url.split(".")[-1] if "." in path_or_url else ".tmp"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(response.content)
                return tmp.name
        except Exception as e:
            print(f"Failed to download file: {e}")
            raise e

    def _load_florence(self):
        if not self.florence_model:
            model_path = os.path.join(self.models_path, settings.MODEL_FLORENCE_LOCAL)
            print(f"Loading Florence ({settings.MODEL_FLORENCE_HF}) from {model_path}...")
            # Florence-2-Large requires trust_remote_code=True
            self.florence_model = (
                AutoModelForCausalLM.from_pretrained(model_path, trust_remote_code=True)
                .to(self.device)
                .eval()
            )
            self.florence_processor = AutoProcessor.from_pretrained(
                model_path, trust_remote_code=True
            )

    def describe_image(self, image_path: str) -> str:
        """
        Generates a detailed description using Florence vision model.
        Handles local paths and R2 URLs.
        """
        self._load_florence()

        local_path = self._download_temp_file(image_path)

        try:
            image = Image.open(local_path)
            if image.mode != "RGB":
                image = image.convert("RGB")

            # Task: Detailed Caption
            prompt = "<MORE_DETAILED_CAPTION>"

            # Wraps inputs in lists to ensure correct processing
            inputs = self.florence_processor(
                text=[prompt], images=[image], return_tensors="pt"
            )
            inputs = {k: v.to(self.device) for k, v in inputs.items() if v is not None}

            with torch.no_grad():
                generated_ids = self.florence_model.generate(
                    **inputs, max_new_tokens=1024, num_beams=3, use_cache=False
                )

            generated_text = self.florence_processor.batch_decode(
                generated_ids, skip_special_tokens=False
            )[0]

            # Post-process to get pure text
            parsed_answer = self.florence_processor.post_process_generation(
                generated_text, task=prompt, image_size=(image.width, image.height)
            )

            description = parsed_answer.get(prompt, "")
            print(f"Florence Description: {description}")
            return description

        except Exception as e:
            print(f"Florence Failed: {e}")
            return f"Image Description Failed: {e}"
        finally:
            if local_path != image_path and os.path.exists(local_path):
                os.remove(local_path)

    def transcribe_audio(self, audio_path: str) -> str:
        """
        Transcribes audio using Whisper.
        Handles local paths and R2 URLs.
        """
        import os

        self._load_whisper()
        import librosa

        local_path = self._download_temp_file(audio_path)

        try:
            print(f"Transcribing audio: {local_path}")

            # Convert to WAV using pydub to ensure compatibility with librosa/soundfile
            # This fixes "PySoundFile failed" and "Processing Multimedia Sources" warnings
            from pydub import AudioSegment

            # Determine format or let pydub auto-detect
            # We convert to a new temp WAV file
            wav_path = local_path + ".converted.wav"
            print(f"Converting to WAV: {wav_path}")

            audio_segment = AudioSegment.from_file(local_path)
            audio_segment = audio_segment.set_frame_rate(16000).set_channels(
                1
            )  # Normalize to 16kHz Mono
            audio_segment.export(wav_path, format="wav")

            # Load the CLEAN WAV file
            audio, _ = librosa.load(wav_path, sr=16000)

            input_features = self.whisper_processor(
                audio, sampling_rate=16000, return_tensors="pt"
            ).input_features.to(self.device)

            generated_ids = self.whisper_model.generate(input_features)
            transcription = self.whisper_processor.batch_decode(
                generated_ids, skip_special_tokens=True
            )[0]

            # Cleanup the converted wav
            if os.path.exists(wav_path):
                os.remove(wav_path)

            return transcription
        finally:
            if local_path != audio_path and os.path.exists(local_path):
                os.remove(local_path)

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """
        Extracts text from PDF.
        Strategy:
        1. Attempt native text extraction via PyMuPDF (fast, accurate for digital PDFs).
        2. If native text is sparse (< 50 chars/page), fallback to DeepSeek-OCR / VLM (slow, handles scans).
        """
        import os

        local_path = self._download_temp_file(pdf_path)
        extracted_text = []
        used_ocr = False

        try:
            # --- Strategy 1: Native Text Extraction (PyMuPDF) ---
            try:
                import fitz  # PyMuPDF

                doc = fitz.open(local_path)

                for i, page in enumerate(doc):
                    text = page.get_text().strip()
                    # Check text density. If page is mostly empty/scanned, this will be short.
                    if len(text) > 50:
                        extracted_text.append(f"--- Page {i+1} ---\n{text}")
                    else:
                        # Page might be an image/scan.
                        # We could mix strategies, but for simplicity, if a page has no text, mark it for OCR?
                        # For now, let's just collect what we can.
                        # If the WHOLE document yields little text, we fallback.
                        pass

                doc.close()

                full_native_text = "\n\n".join(extracted_text)

                # Heuristic: If we got a decent amount of text, return it.
                if len(full_native_text) > 100:
                    print("PDF Text Extraction: Used Native Text Layer (PyMuPDF).")
                    return full_native_text

                print(
                    "PDF Text Extraction: Native text too sparse. Falling back to OCR..."
                )
                extracted_text = []  # Reset for OCR

            except ImportError:
                print("PyMuPDF (fitz) not installed. Skipping native text check.")
            except Exception as e:
                print(f"PyMuPDF failed: {e}. Falling back to OCR.")

            # --- Strategy 2: Vision Model (DeepSeek-OCR) ---
            # Fallback for Scanned PDFs or images
            from pdf2image import convert_from_path
            import io
            import base64
            from app.core.config import settings
            from openai import OpenAI

            print(f"Converting PDF {local_path} to images for OCR...")
            images = convert_from_path(local_path)

            client = OpenAI(
                base_url=f"{settings.OLLAMA_BASE_URL}/v1",
                api_key="ollama",
            )

            for i, img in enumerate(images):
                print(f"Processing PDF Page {i+1}/{len(images)} (OCR)...")

                # Convert PIL image to base64
                buffered = io.BytesIO()
                img.save(buffered, format="JPEG")
                img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")

                response = client.chat.completions.create(
                    model=settings.MODEL_VISION,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Extract all text from this document image. Return only the text content, no markdown or comments. Preserve layout.",
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{img_str}"
                                    },
                                },
                            ],
                        }
                    ],
                )
                page_text = response.choices[0].message.content
                extracted_text.append(f"--- Page {i+1} ---\n{page_text}")

            return "\n\n".join(extracted_text)

        except Exception as e:
            return f"PDF Extraction Failed: {e}"
        finally:
            if (
                "local_path" in locals()
                and local_path != pdf_path
                and os.path.exists(local_path)
            ):
                os.remove(local_path)


multimedia_service = MultimediaService()
