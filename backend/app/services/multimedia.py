"""Multimedia processing via local model services and lightweight document parsers."""

# pylint: disable=wrong-import-order,import-outside-toplevel
import os
import csv
from collections.abc import Callable

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
    """Extract text from attachments using local model services."""

    def _parse_storage_ref(self, path_or_url: str) -> tuple[str, str] | None:
        """Return (bucket, key) when the path points at RustFS / proxy storage."""
        from urllib.parse import urlparse

        if path_or_url.startswith("http"):
            parsed = urlparse(path_or_url)
            parts = parsed.path.strip("/").split("/", 1)
            if len(parts) == 2 and parts[1]:
                return parts[0], parts[1]
            return None

        if path_or_url.startswith("/files/"):
            remainder = path_or_url[len("/files/") :].lstrip("/")
            parts = remainder.split("/", 1)
            if len(parts) == 2 and parts[1]:
                return parts[0], parts[1]
            return None

        if path_or_url.startswith("/uploads/"):
            key = path_or_url[len("/uploads/") :].lstrip("/")
            if key:
                return settings.BUCKET_NAME, key

        files_url = settings.FILES_URL.rstrip("/")
        if files_url.startswith("/") and path_or_url.startswith(files_url + "/"):
            key = path_or_url[len(files_url) + 1 :]
            if key:
                return settings.BUCKET_NAME, key

        return None

    def _download_from_storage(self, bucket: str, key: str) -> str:
        """Download an object from RustFS/S3 to a temporary local file."""
        import tempfile

        import boto3
        from botocore.client import Config

        suffix = "." + key.rsplit(".", 1)[-1] if "." in key else ".tmp"
        client = boto3.client(
            "s3",
            aws_access_key_id=settings.BUCKET_ACCESS_KEY_ID,
            aws_secret_access_key=settings.BUCKET_SECRET_ACCESS_KEY,
            endpoint_url=settings.R2_ENDPOINT_URL,
            config=Config(s3={"addressing_style": "path"}),
        )
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            client.download_fileobj(bucket, key, tmp)
            return tmp.name

    def _resolve_storage_url(self, path_or_url: str) -> str:
        """Normalize attachment URLs/paths to something the backend can fetch."""
        if not path_or_url:
            return path_or_url

        if path_or_url.startswith("http"):
            return path_or_url

        if os.path.isfile(path_or_url):
            return path_or_url

        if path_or_url.startswith("/files/"):
            remainder = path_or_url[len("/files/") :].lstrip("/")
            if remainder:
                return f"{settings.R2_ENDPOINT_URL.rstrip('/')}/{remainder}"

        if path_or_url.startswith("/uploads/"):
            key = path_or_url[len("/uploads/") :].lstrip("/")
            if key:
                return (
                    f"{settings.R2_ENDPOINT_URL.rstrip('/')}/"
                    f"{settings.BUCKET_NAME}/{key}"
                )

        files_url = settings.FILES_URL.rstrip("/")
        if files_url.startswith("/") and path_or_url.startswith(files_url + "/"):
            key = path_or_url[len(files_url) + 1 :]
            if key:
                return (
                    f"{settings.R2_ENDPOINT_URL.rstrip('/')}/"
                    f"{settings.BUCKET_NAME}/{key}"
                )

        return path_or_url

    def _download_temp_file(self, path_or_url: str) -> str:
        """Download remote/storage attachments to a temporary local file."""
        import tempfile

        import requests

        if os.path.isfile(path_or_url):
            return path_or_url

        storage_ref = self._parse_storage_ref(path_or_url)
        if storage_ref:
            bucket, key = storage_ref
            logger.info(f"Downloading storage object: {bucket}/{key}")
            return self._download_from_storage(bucket, key)

        resolved = self._resolve_storage_url(path_or_url)
        if resolved != path_or_url:
            storage_ref = self._parse_storage_ref(resolved)
            if storage_ref:
                bucket, key = storage_ref
                logger.info(f"Downloading storage object: {bucket}/{key}")
                return self._download_from_storage(bucket, key)

        if not resolved.startswith("http"):
            return resolved

        logger.info(f"Downloading remote file: {resolved}...")
        response = requests.get(resolved, timeout=300)
        response.raise_for_status()
        suffix = "." + resolved.split(".")[-1] if "." in resolved else ".tmp"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(response.content)
            return tmp.name

    def _post_file_to_local_models(self, local_path: str, endpoint: str) -> dict:
        """Upload a local file to the local-models service."""
        import httpx

        if not settings.LOCAL_MODELS_SERVICE_URL:
            raise RuntimeError("Local models service is disabled")

        url = f"{settings.LOCAL_MODELS_SERVICE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
        timeout = httpx.Timeout(settings.LOCAL_MODELS_SERVICE_TIMEOUT_SECONDS)
        with open(local_path, "rb") as file_obj:
            files = {
                "file": (
                    os.path.basename(local_path),
                    file_obj,
                    "application/octet-stream",
                )
            }
            response = httpx.post(url, files=files, timeout=timeout)
            response.raise_for_status()
            return response.json()

    def _caption_video_with_marlin(self, local_path: str) -> dict:
        """Send a local video file to the dedicated Marlin service."""
        import httpx

        if not settings.MARLIN_SERVICE_URL:
            logger.info("Marlin service is disabled; skipping visual video analysis.")
            return {}

        url = f"{settings.MARLIN_SERVICE_URL.rstrip('/')}/caption"
        timeout = httpx.Timeout(settings.MARLIN_SERVICE_TIMEOUT_SECONDS)
        with open(local_path, "rb") as video_file:
            files = {
                "file": (
                    os.path.basename(local_path),
                    video_file,
                    "application/octet-stream",
                )
            }
            response = httpx.post(url, files=files, timeout=timeout)
            response.raise_for_status()
            return response.json()

    def unload_local_models(self, family: str | None = None) -> None:
        """Ask local-models to release a loaded model family."""
        import httpx

        if not settings.LOCAL_MODELS_SERVICE_URL:
            return

        url = f"{settings.LOCAL_MODELS_SERVICE_URL.rstrip('/')}/unload"
        try:
            response = httpx.post(
                url,
                json={"family": family},
                timeout=httpx.Timeout(30.0),
            )
            response.raise_for_status()
            logger.info(f"Unloaded local model family: {family or 'all'}")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(f"Local model unload skipped/failed: {exc}")

    def unload_marlin(self) -> None:
        """Ask the Marlin service to release the loaded video model."""
        import httpx

        if not settings.MARLIN_SERVICE_URL:
            return

        url = f"{settings.MARLIN_SERVICE_URL.rstrip('/')}/unload"
        try:
            response = httpx.post(url, timeout=httpx.Timeout(30.0))
            response.raise_for_status()
            logger.info("Unloaded Marlin model")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning(f"Marlin unload skipped/failed: {exc}")

    def describe_image(self, image_path: str) -> str:
        """Generate a detailed image description via the local-models service."""
        local_path = self._download_temp_file(image_path)
        try:
            result = self._post_file_to_local_models(local_path, "/image/describe")
            return result.get("text", "")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(f"Image description failed: {exc}")
            raise RuntimeError(f"Image description failed: {exc}") from exc
        finally:
            if local_path != image_path and os.path.exists(local_path):
                os.remove(local_path)

    def transcribe_audio(self, audio_path: str) -> str:
        """Transcribe audio via the local-models service."""
        local_path = self._download_temp_file(audio_path)
        try:
            logger.info(f"Transcribing audio: {local_path}")
            result = self._post_file_to_local_models(local_path, "/audio/transcribe")
            return result.get("text", "")
        finally:
            if local_path != audio_path and os.path.exists(local_path):
                os.remove(local_path)

    def process_video(self, video_path: str) -> str:
        """Process a video with Whisper audio transcription and Marlin visual analysis."""
        transcript = self.transcribe_video_audio(video_path)
        visual = self.describe_video_visual(video_path)
        parts = []
        if transcript:
            parts.append(f"### Spoken Content\n{transcript}")
        if visual:
            parts.append(visual)
        return "\n\n".join(parts) if parts else "(Video processing produced no output)"

    def transcribe_video_audio(self, video_path: str) -> str:
        """Transcribe a video's audio track without running visual analysis."""
        import av

        local_path = self._download_temp_file(video_path)
        try:
            with av.open(local_path) as container:
                has_video = len(container.streams.video) > 0

            if not has_video:
                logger.info("No video stream detected — treating as audio-only.")
                return self.transcribe_audio(local_path)

            try:
                logger.info("Transcribing video audio track...")
                return self.transcribe_audio(local_path)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning(
                    f"Audio transcription skipped (no audio track or failed): {exc}"
                )
                return ""
        finally:
            if local_path != video_path and os.path.exists(local_path):
                os.remove(local_path)

    def describe_video_visual(self, video_path: str) -> str:
        """Run Marlin visual analysis without transcribing audio."""
        import av

        local_path = self._download_temp_file(video_path)
        try:
            with av.open(local_path) as container:
                has_video = len(container.streams.video) > 0

            if not has_video:
                return ""

            try:
                logger.info("Running Marlin video captioning via service...")
                result = self._caption_video_with_marlin(local_path)
                scene = result.get("scene", "")
                events = result.get("events", [])
                lines = [
                    f"- {_format_timestamp(ev.get('start', 0))}\u2013{_format_timestamp(ev.get('end', 0))} \u2014 {ev.get('description', '')}"
                    for ev in events
                ]
                events_text = "\n".join(lines)
                logger.info(f"Marlin: {len(events)} events extracted.")
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error(f"Marlin captioning failed: {exc}")
                return ""

            if scene:
                visual = f"### Visual Analysis\n**Scene:** {scene}"
                if events_text:
                    visual += f"\n\n**Events:**\n{events_text}"
                return visual
            return ""
        finally:
            if local_path != video_path and os.path.exists(local_path):
                os.remove(local_path)

    def extract_text_from_pdf(
        self,
        pdf_path: str,
        progress_callback: Callable[[str, str | None], None] | None = None,
    ) -> str:
        """Extract PDF page text and describe embedded images with Florence."""
        import tempfile

        import fitz

        def _progress(stage: str, model: str | None = None) -> None:
            if progress_callback:
                progress_callback(stage, model)

        local_path = self._download_temp_file(pdf_path)
        try:
            extracted_pages: list[str] = []
            doc = fitz.open(local_path)
            total_pages = len(doc)
            try:
                for page_index, page in enumerate(doc, start=1):
                    _progress(
                        f"PDF: page {page_index}/{total_pages}, extracting text",
                        None,
                    )
                    native_text = page.get_text().strip()
                    page_parts = [f"--- Page {page_index} ---"]
                    image_descriptions: list[str] = []

                    if native_text:
                        page_parts.append(f"Native text:\n{native_text}")

                    images = page.get_images(full=True)
                    for image_index, image_info in enumerate(images, start=1):
                        _progress(
                            (
                                f"PDF: page {page_index}/{total_pages}, "
                                f"describing image {image_index}/{len(images)}"
                            ),
                            "Florence-2",
                        )
                        xref = image_info[0]
                        image_path = ""
                        try:
                            extracted = doc.extract_image(xref)
                            image_bytes = extracted.get("image")
                            if not image_bytes:
                                continue
                            image_ext = extracted.get("ext") or "png"
                            with tempfile.NamedTemporaryFile(
                                delete=False, suffix=f".{image_ext}"
                            ) as tmp:
                                image_path = tmp.name
                                tmp.write(image_bytes)
                            result = self._post_file_to_local_models(
                                image_path, "/image/describe"
                            )
                            description = result.get("text", "")
                        except Exception as exc:  # pylint: disable=broad-exception-caught
                            logger.warning(
                                "PDF image description skipped "
                                f"(page={page_index}, image={image_index}): {exc}"
                            )
                            continue
                        finally:
                            if image_path and os.path.exists(image_path):
                                os.remove(image_path)

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

                    _progress(f"PDF: page {page_index}/{total_pages} complete", None)
            finally:
                doc.close()

            full_text = "\n\n".join(extracted_pages).strip()
            if not full_text:
                return "PDF contains no extractable native or visual content."
            return full_text
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(f"PDF extraction failed: {exc}")
            raise RuntimeError(f"PDF extraction failed: {exc}") from exc
        finally:
            if local_path != pdf_path and os.path.exists(local_path):
                os.remove(local_path)

    def extract_text_from_docx(self, docx_path: str) -> str:
        """Extract text from a Word document (.docx) using native parsing only."""
        local_path = self._download_temp_file(docx_path)
        parts = []

        try:
            try:
                import docx

                document = docx.Document(local_path)
                for paragraph in document.paragraphs:
                    text = paragraph.text.strip()
                    if text:
                        parts.append(text)

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
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error(f"DOCX extraction failed: {exc}")
                return f"Word extraction failed: {exc}"

        finally:
            if local_path != docx_path and os.path.exists(local_path):
                os.remove(local_path)

    def extract_text_from_spreadsheet(
        self, sheet_path: str
    ) -> str:  # pylint: disable=too-many-return-statements,too-many-nested-blocks,too-many-locals,too-many-branches
        """Extract text from spreadsheet-like files using native parsing."""
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
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    logger.error(f"XLSX extraction failed: {exc}")
                    return f"Spreadsheet extraction failed: {exc}"

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
            if local_path != sheet_path and os.path.exists(local_path):
                os.remove(local_path)


multimedia_service = MultimediaService()
