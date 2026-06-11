"""Multimedia processing: image captioning, audio transcription, and PDF text extraction."""

# pylint: disable=wrong-import-order,import-outside-toplevel
import os
import csv

from app.core.config import settings
from app.core.log import get_logger

logger = get_logger("MultimediaService")


def _format_timestamp(seconds: float) -> str:
    """Convert seconds to M:SS or H:MM:SS string."""
    s = int(seconds)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class MultimediaService:
    """Extract text from images (Florence-2), audio (Whisper), and PDFs; falls back gracefully if models are absent."""

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
        self.marlin_model = None

    def _load_whisper(self):
        from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor
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
        import tempfile

        import requests

        if not path_or_url.startswith("http"):
            return path_or_url

        logger.info(f"Downloading remote file: {path_or_url}...")
        try:
            response = requests.get(path_or_url, timeout=300)
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
        from transformers import AutoModelForCausalLM, AutoProcessor
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

    def _load_marlin(self):
        import torch
        from transformers import AutoModelForCausalLM
        if not self.marlin_model:
            model_path = os.path.join(self.models_path, settings.MODEL_MARLIN_LOCAL)
            logger.info(
                f"Loading Marlin ({settings.MODEL_MARLIN_HF}) from {model_path}..."
            )
            self.marlin_model = (
                AutoModelForCausalLM.from_pretrained(
                    model_path,
                    trust_remote_code=True,
                    torch_dtype=torch.float32,
                )
                .to(self.device)
                .eval()
            )

    def _describe_pil_image(self, image) -> str:
        """Generate a detailed Florence description for an already-loaded PIL image."""
        import torch

        self._load_florence()

        try:
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

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error(f"Florence Failed: {e}")
            return f"Image Description Failed: {e}"

    def describe_image(self, image_path: str) -> str:
        """
        Generates a detailed description using Florence vision model.
        Handles local paths and R2 URLs.
        """
        from PIL import Image

        local_path = self._download_temp_file(image_path)

        try:
            image = Image.open(local_path)
            return self._describe_pil_image(image)
        finally:
            if local_path != image_path and os.path.exists(local_path):
                os.remove(local_path)

    def transcribe_audio(self, audio_path: str) -> str:
        """
        Transcribes audio using Whisper.
        Handles local paths and R2 URLs.
        """
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

    def process_video(self, video_path: str) -> str:
        """
        Process a video: probe for a video stream, then run Whisper (audio) and
        Marlin (visual) in parallel streams. Falls back to audio-only transcription
        if no video stream is detected (e.g. an audio-only .webm upload).
        """
        import av

        local_path = self._download_temp_file(video_path)

        try:
            # Probe for a video stream before loading Marlin
            with av.open(local_path) as container:
                has_video = len(container.streams.video) > 0

            if not has_video:
                logger.info("No video stream detected — treating as audio-only.")
                return self.transcribe_audio(local_path)

            self._load_marlin()

            # --- Stream 1: Audio → Whisper ---
            transcript = ""
            try:
                logger.info("Transcribing video audio track...")
                transcript = self.transcribe_audio(local_path)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning(f"Audio transcription skipped (no audio track or failed): {e}")

            # --- Stream 2: Visual → Marlin ---
            scene = ""
            events_text = ""
            try:
                logger.info("Running Marlin video captioning...")
                result = self.marlin_model.caption(local_path)
                scene = result.get("scene", "")
                events = result.get("events", [])
                lines = [
                    f"- {_format_timestamp(ev.get('start', 0))}\u2013{_format_timestamp(ev.get('end', 0))} \u2014 {ev.get('description', '')}"
                    for ev in events
                ]
                events_text = "\n".join(lines)
                logger.info(f"Marlin: {len(events)} events extracted.")
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error(f"Marlin captioning failed: {e}")

            # --- Combine results ---
            parts = []
            if transcript:
                parts.append(f"### Spoken Content\n{transcript}")
            if scene:
                visual = f"### Visual Analysis\n**Scene:** {scene}"
                if events_text:
                    visual += f"\n\n**Events:**\n{events_text}"
                parts.append(visual)
            return "\n\n".join(parts) if parts else "(Video processing produced no output)"

        finally:
            if local_path != video_path and os.path.exists(local_path):
                os.remove(local_path)

    def _pdf_page_needs_visual_description(self, page, native_text: str) -> bool:
        """
        Decide whether a rendered PDF page should go through Florence.

        Rendering every page can be slow, so we target pages that are likely to
        contain non-text information: scans, embedded images, charts, or vector
        drawings.
        """
        if not settings.PDF_VISUAL_EXTRACTION_ENABLED:
            return False

        if len(native_text.strip()) < settings.PDF_VISUAL_TEXT_THRESHOLD:
            return True

        try:
            if page.get_images(full=True):
                return True
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.debug(f"Could not inspect PDF page images: {e}")

        try:
            if page.get_drawings():
                return True
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.debug(f"Could not inspect PDF page drawings: {e}")

        return False

    def _describe_pdf_page_render(self, page) -> str:
        """Render a PDF page to an image and describe it with Florence."""
        import fitz  # PyMuPDF
        from PIL import Image

        dpi = max(settings.PDF_VISUAL_RENDER_DPI, 72)
        zoom = dpi / 72
        pixmap = page.get_pixmap(
            matrix=fitz.Matrix(zoom, zoom),
            alpha=False,
            annots=True,
        )
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        return self._describe_pil_image(image)

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """
        Extract native text from a PDF and enrich image-heavy/scanned pages with
        Florence visual descriptions from rendered page images.
        """
        local_path = self._download_temp_file(pdf_path)
        extracted_pages = []

        try:
            try:
                import fitz  # PyMuPDF

                doc = fitz.open(local_path)
                try:
                    visual_pages_processed = 0
                    visual_pages_skipped = 0
                    max_visual_pages = max(settings.PDF_VISUAL_EXTRACTION_MAX_PAGES, 0)
                    has_visual_page_cap = max_visual_pages > 0

                    for i, page in enumerate(doc, start=1):
                        native_text = page.get_text().strip()
                        page_parts = [f"--- Page {i} ---"]
                        visual_description = ""

                        if native_text:
                            page_parts.append(f"Native text:\n{native_text}")

                        if self._pdf_page_needs_visual_description(page, native_text):
                            if (
                                not has_visual_page_cap
                                or visual_pages_processed < max_visual_pages
                            ):
                                visual_pages_processed += 1
                                logger.info(
                                    f"Rendering PDF page {i} for visual extraction..."
                                )
                                visual_description = self._describe_pdf_page_render(
                                    page
                                )
                                if visual_description:
                                    if not native_text:
                                        page_parts.append("Native text: (none found)")
                                    page_parts.append(
                                        f"Visual content:\n{visual_description}"
                                    )
                            else:
                                visual_pages_skipped += 1

                        if native_text or visual_description:
                            extracted_pages.append("\n\n".join(page_parts))
                finally:
                    doc.close()

                full_text = "\n\n".join(extracted_pages).strip()
                if visual_pages_skipped:
                    full_text += (
                        "\n\n[PDF visual extraction skipped "
                        f"{visual_pages_skipped} page(s) after reaching "
                        f"PDF_VISUAL_EXTRACTION_MAX_PAGES={max_visual_pages}. "
                        "Set it to 0 to process all visually relevant pages.]"
                    )

                if not full_text:
                    logger.info(
                        "PDF Extraction: No native or visual content extracted."
                    )
                    return "PDF contains no extractable native or visual content."

                logger.info(
                    "PDF Extraction: Used native text layer"
                    f" and {visual_pages_processed} visual page render(s)."
                )
                return full_text

            except ImportError:
                logger.error("PyMuPDF (fitz) not installed.")
                return "PDF extraction unavailable: PyMuPDF (fitz) is not installed."
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error(f"PyMuPDF failed: {e}")
                return f"PDF extraction failed: {e}"

        except Exception as e:  # pylint: disable=broad-exception-caught
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
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error(f"DOCX extraction failed: {e}")
                return f"Word extraction failed: {e}"

        finally:
            if (
                "local_path" in locals()
                and local_path != docx_path
                and os.path.exists(local_path)
            ):
                os.remove(local_path)

    def extract_text_from_spreadsheet(
        self, sheet_path: str
    ) -> (
        str
    ):  # pylint: disable=too-many-return-statements,too-many-nested-blocks,too-many-locals,too-many-branches
        """
        Extract text from spreadsheet-like files using native parsing:
        - .xlsx via openpyxl
        - .csv/.tsv via stdlib csv
        """

        local_path = self._download_temp_file(sheet_path)
        lower_path = local_path.lower()

        try:  # pylint: disable=too-many-nested-blocks
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
                except Exception as e:  # pylint: disable=broad-exception-caught
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
