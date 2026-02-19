import os
import torch
from PIL import Image
from transformers import AutoProcessor, AutoModelForCausalLM, AutoModelForSpeechSeq2Seq
from app.core.config import settings
from app.core.log import get_logger

logger = get_logger("MultimediaService")


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

    def _load_whisper(self):
        if not self.whisper_model:
            model_path = os.path.join(self.models_path, settings.MODEL_WHISPER_LOCAL)
            logger.info(
                f"Loading Whisper ({settings.MODEL_WHISPER_HF}) from {model_path}..."
            )
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

        if not path_or_url.startswith("http"):
            return path_or_url

        logger.info(f"Downloading remote file: {path_or_url}...")
        try:
            response = requests.get(path_or_url)
            response.raise_for_status()

            # Create temp file
            suffix = "." + path_or_url.split(".")[-1] if "." in path_or_url else ".tmp"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(response.content)
                return tmp.name
        except Exception as e:
            logger.error(f"Failed to download file: {e}")
            raise e

    def _load_florence(self):
        if not self.florence_model:
            model_path = os.path.join(self.models_path, settings.MODEL_FLORENCE_LOCAL)
            logger.info(
                f"Loading Florence ({settings.MODEL_FLORENCE_HF}) from {model_path}..."
            )
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
            raw = self.florence_processor(
                text=[prompt], images=[image], return_tensors="pt"
            )
            model_dtype = next(self.florence_model.parameters()).dtype
            inputs = {}
            for k, v in raw.items():
                if v is None:
                    continue
                if torch.is_floating_point(v):
                    inputs[k] = v.to(device=self.device, dtype=model_dtype)
                else:
                    inputs[k] = v.to(self.device)

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
            logger.info(f"Florence Description: {description}")
            return description

        except Exception as e:
            logger.error(f"Florence Failed: {e}")
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
            logger.info(f"Transcribing audio: {local_path}")

            # Convert to WAV using pydub to ensure compatibility with librosa/soundfile
            # This fixes "PySoundFile failed" and "Processing Multimedia Sources" warnings
            from pydub import AudioSegment

            # Determine format or let pydub auto-detect
            # We convert to a new temp WAV file
            wav_path = local_path + ".converted.wav"
            logger.info(f"Converting to WAV: {wav_path}")

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

            # Explicitly pass generation_config to suppress "defaults modified" warning
            generated_ids = self.whisper_model.generate(
                input_features, generation_config=self.whisper_model.generation_config
            )
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
        Extract text from a PDF using only the native text layer (PyMuPDF).
        OCR fallback is intentionally disabled.
        """
        import os

        local_path = self._download_temp_file(pdf_path)
        extracted_text = []

        try:
            try:
                import fitz  # PyMuPDF

                doc = fitz.open(local_path)

                for i, page in enumerate(doc):
                    text = page.get_text().strip()
                    extracted_text.append(f"--- Page {i+1} ---\n{text}")

                doc.close()
                full_native_text = "\n\n".join(extracted_text).strip()
                if not full_native_text:
                    logger.info(
                        "PDF Text Extraction: No native text layer content found."
                    )
                    return "PDF contains no extractable native text."

                logger.info("PDF Text Extraction: Used native text layer (PyMuPDF).")
                return full_native_text

            except ImportError:
                logger.error("PyMuPDF (fitz) not installed.")
                return "PDF extraction unavailable: PyMuPDF (fitz) is not installed."
            except Exception as e:
                logger.error(f"PyMuPDF failed: {e}")
                return f"PDF extraction failed: {e}"

        except Exception as e:
            return f"PDF Extraction Failed: {e}"
        finally:
            if (
                "local_path" in locals()
                and local_path != pdf_path
                and os.path.exists(local_path)
            ):
                os.remove(local_path)

    def extract_text_from_docx(self, docx_path: str) -> str:
        """
        Extract text from a Word document (.docx) using native parsing only.
        """
        import os

        local_path = self._download_temp_file(docx_path)
        parts = []

        try:
            try:
                import docx

                document = docx.Document(local_path)

                # Paragraph content
                for paragraph in document.paragraphs:
                    text = paragraph.text.strip()
                    if text:
                        parts.append(text)

                # Table content
                for idx, table in enumerate(document.tables, start=1):
                    rows = []
                    for row in table.rows:
                        cells = [cell.text.strip() for cell in row.cells]
                        if any(cells):
                            rows.append(" | ".join(cells))
                    if rows:
                        parts.append(f"--- Table {idx} ---\n" + "\n".join(rows))

                full_text = "\n\n".join(parts).strip()
                if not full_text:
                    return "Word document contains no extractable text."
                return full_text

            except ImportError:
                return "Word extraction unavailable: python-docx is not installed."
            except Exception as e:
                logger.error(f"DOCX extraction failed: {e}")
                return f"Word extraction failed: {e}"

        finally:
            if (
                "local_path" in locals()
                and local_path != docx_path
                and os.path.exists(local_path)
            ):
                os.remove(local_path)

    def extract_text_from_spreadsheet(self, sheet_path: str) -> str:
        """
        Extract text from spreadsheet-like files using native parsing:
        - .xlsx via openpyxl
        - .csv/.tsv via stdlib csv
        """
        import csv
        import os

        local_path = self._download_temp_file(sheet_path)
        lower_path = local_path.lower()

        try:
            if lower_path.endswith(".xlsx"):
                try:
                    from openpyxl import load_workbook

                    workbook = load_workbook(
                        filename=local_path,
                        read_only=True,
                        data_only=True,
                    )
                    parts = []
                    for sheet_name in workbook.sheetnames:
                        sheet = workbook[sheet_name]
                        rows = []
                        for row in sheet.iter_rows(values_only=True):
                            values = [
                                str(cell).strip() for cell in row if cell is not None
                            ]
                            if values:
                                rows.append("\t".join(values))
                        if rows:
                            parts.append(
                                f"--- Sheet: {sheet_name} ---\n" + "\n".join(rows)
                            )

                    workbook.close()
                    full_text = "\n\n".join(parts).strip()
                    if not full_text:
                        return "Spreadsheet contains no extractable text."
                    return full_text

                except ImportError:
                    return (
                        "Spreadsheet extraction unavailable: openpyxl is not installed."
                    )
                except Exception as e:
                    logger.error(f"XLSX extraction failed: {e}")
                    return f"Spreadsheet extraction failed: {e}"

            if lower_path.endswith((".csv", ".tsv")):
                delimiter = "\t" if lower_path.endswith(".tsv") else ","
                rows = []
                with open(local_path, "r", encoding="utf-8", errors="ignore") as f:
                    reader = csv.reader(f, delimiter=delimiter)
                    for row in reader:
                        values = [cell.strip() for cell in row if cell and cell.strip()]
                        if values:
                            rows.append("\t".join(values))

                if not rows:
                    return "Spreadsheet contains no extractable text."
                return "\n".join(rows)

            if lower_path.endswith(".xls"):
                return "Legacy .xls is not supported. Please convert to .xlsx."

            return "Unsupported spreadsheet format."
        finally:
            if (
                "local_path" in locals()
                and local_path != sheet_path
                and os.path.exists(local_path)
            ):
                os.remove(local_path)


multimedia_service = MultimediaService()
