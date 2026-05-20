"""Multi-provider LLM service supporting chat, structured extraction, and ingestion routing."""

# pylint: disable=too-many-lines,wrong-import-order,import-outside-toplevel
import asyncio
import os
import re
from typing import Optional, Type

import httpx
import instructor
from app.core.config import settings
from app.core.log import get_logger
from google import genai
from google.genai import types
from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel

logger = get_logger("LLMService")


class LLMService:
    """Multi-provider LLM client supporting structured extraction, generation, and ingestion routing."""

    def __init__(self):
        import torch
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.models_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "../../models")
        )

        # Declare client attributes upfront so they are always present on the
        # instance regardless of which provider branch _init_clients() takes.
        self.extraction_client = None
        self.chat_client = None
        self.async_chat_client = None
        self._lm_studio_model_cache: Optional[str] = None

        # Determine Primary Provider
        self.provider = settings.LLM_PROVIDER.lower()
        self.fallback_provider = settings.LLM_FALLBACK_PROVIDER

        logger.info(f"Primary LLM Provider: {self.provider.upper()}")
        if self.fallback_provider:
            logger.info(f"Fallback LLM Provider: {self.fallback_provider.upper()}")

        # Initialize provider-specific clients
        self.init_clients()

        # Initialize ingestion-specific clients (may be separate provider/server)
        self._init_ingestion_clients()

        # Legacy compatibility flags
        self.is_gemini = self.provider == "gemini"

    def _make_local_openai_clients(
        self,
        base_url: str,
        api_key: str,
        timeout: "httpx.Timeout",
        instructor_mode=None,
    ):
        """Create extraction, chat, and async_chat clients for a local OpenAI-compatible server.

        ``instructor_mode`` is passed to ``instructor.patch()``; omit it (or pass None)
        to use instructor's default mode (suitable for lm_studio).
        """
        raw_client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            max_retries=3,
        )
        patch_kwargs = {"mode": instructor_mode} if instructor_mode is not None else {}
        self.extraction_client = instructor.patch(raw_client, **patch_kwargs)
        self.chat_client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            max_retries=3,
        )
        self.async_chat_client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            max_retries=3,
        )

    def init_clients(self):  # pylint: disable=too-many-statements
        """Initialize clients for the configured provider."""
        if self.provider == "ollama":
            base_url = f"{settings.LLM_BASE_URL.rstrip('/')}/v1"
            logger.info(f"Initializing Ollama (URL: {base_url})")
            _local_timeout = httpx.Timeout(
                connect=30.0, read=3600.0, write=60.0, pool=60.0
            )
            self._make_local_openai_clients(
                base_url=base_url,
                api_key=settings.LLM_API_KEY,
                timeout=_local_timeout,
                instructor_mode=instructor.Mode.MD_JSON,
            )

        elif self.provider in ("lm_studio", "local"):
            base_url = f"{settings.LLM_BASE_URL.rstrip('/')}/v1"
            logger.info(
                f"Initializing local OpenAI-compatible server (URL: {base_url}, Model: {settings.LLM_MODEL})"
            )
            _local_timeout = httpx.Timeout(
                connect=30.0, read=3600.0, write=60.0, pool=60.0
            )
            self._make_local_openai_clients(
                base_url=base_url,
                api_key=settings.LLM_API_KEY,
                timeout=_local_timeout,
            )

        elif self.provider == "openai":
            if not settings.OPENAI_API_KEY:
                raise ValueError("OPENAI_API_KEY not set in configuration")
            logger.info(f"Initializing OpenAI (Model: {settings.OPENAI_MODEL})")

            self.extraction_client = instructor.patch(
                OpenAI(api_key=settings.OPENAI_API_KEY, timeout=300.0)
            )
            self.chat_client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=300.0)
            # Async client for batch processing
            self.async_chat_client = AsyncOpenAI(
                api_key=settings.OPENAI_API_KEY, timeout=300.0
            )

        elif self.provider == "gemini":
            if not settings.GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY not set in configuration")
            logger.info(f"Initializing Gemini (Model: {settings.GEMINI_MODEL})")

            # Use native Google Gen AI SDK for better rate limits
            # Timeout: 120 seconds per call — long enough for complex extractions, short
            # enough to fail fast rather than appear frozen when the API hangs.
            self.gemini_client = genai.Client(
                api_key=settings.GEMINI_API_KEY,
                http_options=types.HttpOptions(timeout=120000),
            )

            # Create a minimal wrapper for backward compatibility with methods that use chat_client
            # This allows detect_similarity and other legacy methods to work
            class GeminiChatWrapper:  # pylint: disable=too-few-public-methods
                """OpenAI-compatible wrapper that routes completion requests through the native Gemini SDK."""

                def __init__(self, native_client):
                    self.native_client = native_client
                    self.chat = self

                class Completions:  # pylint: disable=too-few-public-methods
                    """Inner completions namespace mirroring the OpenAI Completions interface."""

                    def __init__(self, native_client):
                        self.native_client = native_client

                    def create(
                        self,
                        model,
                        messages,
                        _max_tokens=None,
                        _extra_body=None,
                        temperature=0.1,
                    ):
                        """Execute a synchronous completion request against the Gemini API."""
                        # Convert OpenAI-style messages to Gemini format
                        # Combine system + user messages into single prompt
                        prompt_parts = []
                        for msg in messages:
                            if msg["role"] == "system":
                                prompt_parts.append(msg["content"])
                            elif msg["role"] == "user":
                                prompt_parts.append(msg["content"])

                        prompt = "\\n\\n".join(prompt_parts)

                        # Call native Gemini SDK
                        response = self.native_client.models.generate_content(
                            model=model,
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                temperature=temperature,
                                thinking_config=types.ThinkingConfig(
                                    thinking_budget=0,  # thinking_level="MINIMAL"
                                ),
                            ),
                        )

                        # Return OpenAI-compatible response structure
                        class Choice:  # pylint: disable=too-few-public-methods
                            """OpenAI-compatible Choice wrapper holding a single candidate message."""

                            def __init__(self, text):
                                self.message = type("Message", (), {"content": text})()

                        class Response:  # pylint: disable=too-few-public-methods
                            """OpenAI-compatible response wrapper containing a list of choices."""

                            def __init__(self, text):
                                self.choices = [Choice(text)]

                        return Response(response.text)

                @property
                def completions(self):
                    """Return the inner Completions object for OpenAI-style access."""
                    return self.Completions(self.native_client)

            self.chat_client = GeminiChatWrapper(self.gemini_client)

        elif self.provider == "anthropic":
            if not settings.ANTHROPIC_API_KEY:
                raise ValueError("ANTHROPIC_API_KEY not set in configuration")
            logger.info(f"Initializing Anthropic (Model: {settings.ANTHROPIC_MODEL})")

            # Anthropic uses instructor for structured outputs (prompt engineering mode)
            from anthropic import Anthropic

            self.anthropic_client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

            # Create OpenAI-compatible wrapper for backward compatibility
            # Note: Anthropic doesn't have native structured outputs, so we use instructor
            self.extraction_client = instructor.from_anthropic(
                self.anthropic_client,
                mode=instructor.Mode.ANTHROPIC_JSON,
            )
            self.chat_client = self.anthropic_client

        elif self.provider == "huggingface":
            if not settings.HUGGINGFACE_API_KEY:
                raise ValueError("HUGGINGFACE_API_KEY not set in configuration")
            if not settings.HUGGINGFACE_MODEL:
                raise ValueError("HUGGINGFACE_MODEL not set in configuration")
            base_url = "https://router.huggingface.co/v1"
            logger.info(
                f"Initializing HuggingFace Inference API "
                f"(Model: {settings.HUGGINGFACE_MODEL})"
            )
            self.chat_client = OpenAI(
                base_url=base_url,
                api_key=settings.HUGGINGFACE_API_KEY,
                timeout=300.0,
                max_retries=3,
            )
            self.async_chat_client = AsyncOpenAI(
                base_url=base_url,
                api_key=settings.HUGGINGFACE_API_KEY,
                timeout=300.0,
                max_retries=3,
            )
            # instructor in MD_JSON mode for structured extraction
            self.extraction_client = instructor.patch(
                OpenAI(
                    base_url=base_url,
                    api_key=settings.HUGGINGFACE_API_KEY,
                    timeout=300.0,
                    max_retries=3,
                ),
                mode=instructor.Mode.MD_JSON,
            )

        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")

    def _init_ingestion_clients(self):  # pylint: disable=too-many-statements
        """
        Set up a separate set of clients for ingestion (extraction/entity reasoning).

        If INGESTION_PROVIDER / INGESTION_BASE_URL / INGESTION_API_KEY are not set,
        the ingestion clients simply alias the main chat clients so there is zero overhead.
        """
        raw_provider = (settings.INGESTION_PROVIDER or "").strip().lower()
        self.ingestion_provider = raw_provider or self.provider

        ingestion_base_url = (
            settings.INGESTION_BASE_URL or ""
        ).strip() or settings.LLM_BASE_URL
        ingestion_api_key = (
            settings.INGESTION_API_KEY or ""
        ).strip() or settings.LLM_API_KEY

        # Determine whether ingestion truly differs from the main provider
        same_local = (
            self.ingestion_provider in ("local", "ollama", "lm_studio")
            and self.provider in ("local", "ollama", "lm_studio")
            and ingestion_base_url == settings.LLM_BASE_URL
            and ingestion_api_key == settings.LLM_API_KEY
        )
        same_provider = self.ingestion_provider == self.provider and (
            same_local
            or self.ingestion_provider not in ("local", "ollama", "lm_studio")
        )

        if same_provider:
            # Alias main clients — no extra connections needed
            self.i_chat_client = getattr(self, "chat_client", None)
            self.i_async_chat_client = getattr(self, "async_chat_client", None)
            self.i_extraction_client = getattr(self, "extraction_client", None)
            self.i_gemini_client = getattr(self, "gemini_client", None)
            self.i_anthropic_client = getattr(self, "anthropic_client", None)
            logger.info(
                f"Ingestion LLM: shared with main ({self.ingestion_provider.upper()})"
            )
            return

        logger.info(
            f"Ingestion LLM: separate provider {self.ingestion_provider.upper()}"
        )

        if self.ingestion_provider in ("local", "ollama", "lm_studio"):
            base_url = f"{ingestion_base_url.rstrip('/')}/v1"
            _timeout = httpx.Timeout(connect=30.0, read=3600.0, write=60.0, pool=60.0)
            instructor_mode = (
                instructor.Mode.MD_JSON if self.ingestion_provider == "ollama" else None
            )
            raw = OpenAI(
                base_url=base_url,
                api_key=ingestion_api_key,
                timeout=_timeout,
                max_retries=3,
            )
            patch_kwargs = (
                {"mode": instructor_mode} if instructor_mode is not None else {}
            )
            self.i_extraction_client = instructor.patch(raw, **patch_kwargs)
            self.i_chat_client = OpenAI(
                base_url=base_url,
                api_key=ingestion_api_key,
                timeout=_timeout,
                max_retries=3,
            )
            self.i_async_chat_client = AsyncOpenAI(
                base_url=base_url,
                api_key=ingestion_api_key,
                timeout=_timeout,
                max_retries=3,
            )
            self.i_gemini_client = None
            self.i_anthropic_client = None

        elif self.ingestion_provider == "gemini":
            if not settings.GEMINI_API_KEY:
                raise ValueError(
                    "GEMINI_API_KEY required for INGESTION_PROVIDER=gemini"
                )
            self.i_gemini_client = genai.Client(
                api_key=settings.GEMINI_API_KEY,
                http_options=types.HttpOptions(timeout=120000),
            )
            self.i_chat_client = None
            self.i_async_chat_client = None
            self.i_extraction_client = None
            self.i_anthropic_client = None

        elif self.ingestion_provider == "openai":
            if not settings.OPENAI_API_KEY:
                raise ValueError(
                    "OPENAI_API_KEY required for INGESTION_PROVIDER=openai"
                )
            self.i_chat_client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=300.0)
            self.i_async_chat_client = AsyncOpenAI(
                api_key=settings.OPENAI_API_KEY, timeout=300.0
            )
            self.i_extraction_client = instructor.patch(
                OpenAI(api_key=settings.OPENAI_API_KEY, timeout=300.0)
            )
            self.i_gemini_client = None
            self.i_anthropic_client = None

        elif self.ingestion_provider == "anthropic":
            if not settings.ANTHROPIC_API_KEY:
                raise ValueError(
                    "ANTHROPIC_API_KEY required for INGESTION_PROVIDER=anthropic"
                )
            from anthropic import Anthropic

            self.i_anthropic_client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            self.i_extraction_client = instructor.from_anthropic(
                self.i_anthropic_client, mode=instructor.Mode.ANTHROPIC_JSON
            )
            self.i_chat_client = None
            self.i_async_chat_client = None
            self.i_gemini_client = None

        elif self.ingestion_provider == "huggingface":
            if not settings.HUGGINGFACE_API_KEY:
                raise ValueError(
                    "HUGGINGFACE_API_KEY required for INGESTION_PROVIDER=huggingface"
                )
            base_url = "https://router.huggingface.co/v1"
            self.i_chat_client = OpenAI(
                base_url=base_url,
                api_key=settings.HUGGINGFACE_API_KEY,
                timeout=300.0,
                max_retries=3,
            )
            self.i_async_chat_client = AsyncOpenAI(
                base_url=base_url,
                api_key=settings.HUGGINGFACE_API_KEY,
                timeout=300.0,
                max_retries=3,
            )
            self.i_extraction_client = instructor.patch(
                OpenAI(
                    base_url=base_url,
                    api_key=settings.HUGGINGFACE_API_KEY,
                    timeout=300.0,
                    max_retries=3,
                ),
                mode=instructor.Mode.MD_JSON,
            )
            self.i_gemini_client = None
            self.i_anthropic_client = None

        else:
            raise ValueError(
                f"Unsupported INGESTION_PROVIDER: {self.ingestion_provider}"
            )

    def _with_keep_alive(self, extra_body: dict | None = None) -> dict:
        """Attach provider keep-alive controls for local OpenAI-compatible backends."""
        body = dict(extra_body or {})
        if self.provider in ("ollama", "lm_studio", "local"):
            body.setdefault("keep_alive", settings.LLM_KEEP_ALIVE)
        return body

    def _with_ingestion_keep_alive(self, extra_body: dict | None = None) -> dict:
        """keep_alive hint for local ingestion backends."""
        body = dict(extra_body or {})
        if self.ingestion_provider in ("ollama", "lm_studio", "local"):
            body.setdefault("keep_alive", settings.LLM_KEEP_ALIVE)
        return body

    def _lm_studio_json_response_format(
        self, _schema: dict | None = None, _schema_name: str = "response"
    ) -> dict:
        """
        Force json_object mode to avoid LM Studio grammar compilation stalls
        on large nested schemas.
        """
        return {"type": "json_object"}

    def _lm_studio_text_response_format(self) -> dict:
        """Compatibility fallback for servers that don't accept json_object."""
        return {"type": "text"}

    def _lm_studio_response_format_candidates(  # pylint: disable=unused-argument
        self, schema: dict | None = None, schema_name: str = "response"
    ) -> list[dict]:
        """
        Prioritize json_object to avoid schema-compiler hangs in LM Studio.
        """
        mode = settings.LLM_RESPONSE_FORMAT.lower().strip()
        json_object = {"type": "json_object"}
        text = {"type": "text"}
        if mode == "text":
            return [text]
        return [json_object, text]

    def _resolve_lm_studio_model(self, configured_model: str | None) -> str | None:
        """
        Resolve aliases (e.g. `gemma3:4b`) to LM Studio model IDs and, if possible,
        auto-select an available downloaded variant (often with quant suffix like `@4bit`).
        """
        if not configured_model:
            return configured_model

        cached = getattr(self, "_lm_studio_model_cache", None)
        if cached:
            return cached

        model = configured_model.strip()
        alias_map = {
            "gemma3:4b": "google/gemma-3-4b",
            "gemma3:12b": "google/gemma-3-12b",
        }
        model = alias_map.get(model, model)

        try:
            available = [m.id for m in self.chat_client.models.list().data]
            if model in available:
                self._lm_studio_model_cache = model
                return model

            # Prefer exact prefix matches, e.g. google/gemma-3-4b@4bit
            prefixed = [mid for mid in available if mid.startswith(f"{model}@")]
            if prefixed:
                logger.warning(
                    f"[LM Studio] Model '{configured_model}' not found, using '{prefixed[0]}'"
                )
                self._lm_studio_model_cache = prefixed[0]
                return prefixed[0]

            # Final fallback: contains base model string
            contains = [mid for mid in available if model in mid]
            if contains:
                logger.warning(
                    f"[LM Studio] Model '{configured_model}' not found, using '{contains[0]}'"
                )
                self._lm_studio_model_cache = contains[0]
                return contains[0]
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning(f"[LM Studio] Could not list models for resolution: {e}")

        logger.warning(
            f"[LM Studio] Using configured model '{configured_model}' as-is (could not auto-resolve)"
        )
        self._lm_studio_model_cache = model
        return model

    def _clean_json(self, json_str: str) -> str:
        """
        Uses json_repair to robustly fix malformed JSON from LLMs.
        Also strips markdown code blocks, sanitizes control characters,
        and normalizes smart/curly quotes to straight quotes.
        """
        # 1. Unwrap markdown (Common failure mode)
        if "```" in json_str:
            match = re.search(r"```(?:json)?(.*?)```", json_str, re.DOTALL)
            if match:
                json_str = match.group(1)

        # 2. Remove control characters (except allowed ones: \n \r \t inside strings are handled by json_repair)
        # This handles \u0000-\u001F that break JSON parsing
        json_str = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", json_str)

        # 3. Normalize smart/curly quotes to straight quotes
        # Single quotes: ' ' ‛ → '
        json_str = re.sub(r"[\u2018\u2019\u201B]", "'", json_str)
        # Double quotes: " " „ → "
        json_str = re.sub(r"[\u201C\u201D\u201E]", '"', json_str)

        try:
            from json_repair import repair_json

            return repair_json(json_str)
        except ImportError:
            logger.warning("json_repair not installed! Falling back to raw string.")
            return json_str

    def extract_structured(  # pylint: disable=too-many-return-statements
        self,
        prompt: str,
        response_model: Type[BaseModel],
        temperature: float = 0.1,
        model: str | None = None,
    ) -> Optional[BaseModel]:
        """
        Provider-agnostic structured extraction with native schema enforcement.
        Supports: Ollama, LM Studio, OpenAI, Gemini, Anthropic (with fallback).

        Args:
            model: Optional model override. When set, uses this model instead of
                   the default LLM_MODEL (e.g. pass settings.INGESTION_LLM_MODEL
                   from ingestion callers to use the lighter extraction model).
        """
        try:
            if self.provider == "ollama":
                return self._extract_ollama(
                    prompt, response_model, temperature, model=model
                )
            if self.provider in ("lm_studio", "local"):
                return self._extract_lm_studio(
                    prompt, response_model, temperature, model=model
                )
            if self.provider == "openai":
                return self._extract_openai(prompt, response_model, temperature)
            if self.provider == "gemini":
                return self._extract_gemini(
                    prompt, response_model, temperature, model=model
                )
            if self.provider == "anthropic":
                return self._extract_anthropic(prompt, response_model, temperature)
            if self.provider == "huggingface":
                return self._extract_huggingface(prompt, response_model, temperature)
            raise ValueError(f"Unsupported provider: {self.provider}")

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error(f"Extraction failed with {self.provider}: {e}")

            # Try fallback provider if configured
            if self.fallback_provider:
                logger.info(f"Attempting fallback to {self.fallback_provider}")
                try:
                    original_provider = self.provider
                    self.provider = self.fallback_provider
                    self.init_clients()
                    result = self.extract_structured(
                        prompt, response_model, temperature
                    )
                    # Restore original provider
                    self.provider = original_provider
                    self.init_clients()
                    return result
                except Exception as fallback_error:  # pylint: disable=broad-exception-caught
                    logger.error(f"Fallback extraction failed: {fallback_error}")
                    # Restore original provider
                    self.provider = original_provider
                    self.init_clients()

            # Final fallback: return empty model
            try:
                return response_model()
            except Exception:  # pylint: disable=broad-exception-caught
                return None

    def _extract_ollama(
        self,
        prompt: str,
        response_model: Type[BaseModel],
        temperature: float,
        model: str | None = None,
    ) -> BaseModel:
        """Ollama extraction with native structured outputs."""
        model = model or settings.LLM_MODEL
        logger.info(f"[Ollama] Extracting with {model} (schema enforced)")

        extra_body = {
            "keep_alive": settings.LLM_KEEP_ALIVE,
            "format": response_model.model_json_schema(),  # Native schema enforcement!
        }

        response = self.chat_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            extra_body=extra_body,
            temperature=temperature,
        )

        # Clean JSON response (strip markdown code fences, repair malformed JSON)
        raw_content = response.choices[0].message.content
        cleaned_json = self._clean_json(raw_content)

        # Always log raw JSON for debugging (first 500 chars)
        import json

        try:
            parsed = json.loads(cleaned_json)
            # Handle bare list (top-level array) or normal object
            if isinstance(parsed, list):
                # [[nodes...], [rels...]] — list-of-two-lists format
                if parsed and isinstance(parsed[0], list):
                    node_count = len(parsed[0])
                    rel_count = (
                        len(parsed[1])
                        if len(parsed) > 1 and isinstance(parsed[1], list)
                        else 0
                    )
                else:
                    node_count = len(parsed)
                    rel_count = sum(
                        len(n.get("relationships", []))
                        for n in parsed
                        if isinstance(n, dict)
                    )
            else:
                node_count = len(
                    parsed.get("nodes")
                    or parsed.get("entities")
                    or parsed.get("node_list")
                    or []
                )
                rel_count = len(
                    parsed.get("relationships")
                    or parsed.get("edges")
                    or parsed.get("links")
                    or []
                )
            logger.info(
                f"[Ollama] Raw extraction: {node_count} nodes, {rel_count} relationships"
            )
            if node_count == 0:
                logger.warning(f"[Ollama] Empty nodes. Full JSON: {cleaned_json}")
        except Exception:  # pylint: disable=broad-exception-caught
            logger.warning(f"[Ollama] Could not pre-parse JSON: {cleaned_json}")

        try:
            return response_model.model_validate_json(cleaned_json)
        except Exception as validation_error:
            # Log the raw response for debugging
            logger.error(f"[Ollama] Validation failed: {validation_error}")
            logger.error(f"[Ollama] Raw JSON: {cleaned_json}")
            raise  # Re-raise to trigger fallback handling

    def _extract_openai(
        self, prompt: str, response_model: Type[BaseModel], temperature: float
    ) -> BaseModel:
        """OpenAI extraction with native structured outputs."""
        model = settings.OPENAI_MODEL
        logger.info(f"[OpenAI] Extracting with {model} (structured outputs)")

        # OpenAI's beta structured outputs API
        response = self.chat_client.beta.chat.completions.parse(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format=response_model,
            temperature=temperature,
        )

        return response.choices[0].message.parsed  # Already validated!

    def _extract_lm_studio(
        self,
        prompt: str,
        response_model: Type[BaseModel],
        temperature: float,
        model: str | None = None,
        _client=None,
    ) -> BaseModel:
        """LM Studio/local extraction using prompt-guided JSON object mode."""
        import json

        model = model or self.get_chat_model()
        logger.info(f"[LM Studio] Extracting with {model} (JSON mode)")

        # Keep schema compact to reduce prompt-processing overhead.
        schema_json = json.dumps(
            response_model.model_json_schema(), separators=(",", ":")
        )
        system_prompt = (
            "You are a structured extraction engine. "
            "Return ONLY valid JSON with no markdown fences and no extra text. "
            "The output MUST match this JSON schema exactly:\n"
            f"{schema_json}"
        )

        raw_content = self._extract_lm_studio_with_fallback(
            model=model,
            system_prompt=system_prompt,
            prompt=prompt,
            temperature=temperature,
            schema=None,
            schema_name=response_model.__name__,
            _client=_client,
        )
        cleaned_json = self._clean_json(raw_content)
        try:
            return response_model.model_validate_json(cleaned_json)
        except Exception:
            # Some LM Studio models wrap result in {"extraction": {...}}.
            data = json.loads(cleaned_json)
            if isinstance(data, dict) and isinstance(data.get("extraction"), dict):
                return response_model.model_validate(data["extraction"])
            raise

    def _extract_lm_studio_with_fallback(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        model: str,
        system_prompt: str,
        prompt: str,
        temperature: float,
        schema: dict | None = None,
        schema_name: str = "response",
        _client=None,
    ) -> str:  # pylint: disable=too-many-arguments,too-many-positional-arguments
        """
        Try configured response_format strategy with compatibility fallbacks.
        ``_client`` allows routing to an ingestion-specific server.
        """
        client = _client or self.chat_client
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        last_error = None
        for response_format in self._lm_studio_response_format_candidates(
            schema=schema, schema_name=schema_name
        ):
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    response_format=response_format,
                    extra_body=self._with_keep_alive(),
                    temperature=temperature,
                )
                return response.choices[0].message.content
            except Exception as e:  # pylint: disable=broad-exception-caught
                last_error = e
                logger.warning(
                    f"[LM Studio] response_format={response_format.get('type')} failed: {e}"
                )

        if last_error:
            raise last_error
        raise RuntimeError(
            "[LM Studio] Extraction failed with no response formats to try"
        )

    def _extract_huggingface(
        self, prompt: str, response_model: Type[BaseModel], temperature: float
    ) -> BaseModel:
        """HuggingFace Inference API extraction via OpenAI-compatible endpoint.

        Uses prompt-guided JSON mode — json_object is attempted first and falls
        back to plain text so the method works across all HF-hosted models.
        """
        import json

        model = settings.HUGGINGFACE_MODEL
        logger.info(f"[HuggingFace] Extracting with {model}")

        schema_json = json.dumps(
            response_model.model_json_schema(), separators=(",", ":")
        )
        system_prompt = (
            "You are a structured extraction engine. "
            "Return ONLY valid JSON with no markdown fences and no extra text. "
            "The output MUST match this JSON schema exactly:\n"
            f"{schema_json}"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        # Try json_object first; fall back to text if the model rejects it.
        last_error = None
        for response_format in [{"type": "json_object"}, {"type": "text"}]:
            try:
                response = self.chat_client.chat.completions.create(
                    model=model,
                    messages=messages,
                    response_format=response_format,
                    temperature=temperature,
                )
                raw = response.choices[0].message.content
                cleaned = self._clean_json(raw)
                return response_model.model_validate_json(cleaned)
            except Exception as e:  # pylint: disable=broad-exception-caught
                last_error = e
                logger.warning(
                    f"[HuggingFace] format={response_format['type']} failed: {e}"
                )

        raise last_error

    @staticmethod
    def _inline_schema_refs(schema: dict) -> dict:
        """Inline all $ref references in a JSON schema so Gemini can parse it.

        Gemini's response_schema does not support $ref / $defs — any schema
        produced by Pydantic for nested models must be fully flattened first.
        """
        import copy

        schema = copy.deepcopy(schema)
        defs = schema.pop("$defs", {})

        def resolve(obj):
            if not isinstance(obj, dict):
                return obj
            if "$ref" in obj:
                ref_name = obj["$ref"].split("/")[-1]
                resolved = copy.deepcopy(defs.get(ref_name, obj))
                return resolve(resolved)
            return {k: resolve(v) for k, v in obj.items()}

        return resolve(schema)

    def _extract_gemini(  # pylint: disable=too-many-locals
        self,
        prompt: str,
        response_model: Type[BaseModel],
        temperature: float,
        model: str | None = None,
        _gemini_client=None,
    ) -> BaseModel:
        """Gemini extraction with native SDK and JSON schema enforcement."""
        import time

        gemini_client = _gemini_client or self.gemini_client
        model = model or settings.GEMINI_MODEL
        logger.info(f"[Gemini] Extracting with {model} (native SDK)")

        _retryable = (
            "504",
            "DEADLINE_EXCEEDED",
            "503",
            "UNAVAILABLE",
            "429",
            "RESOURCE_EXHAUSTED",
        )
        max_retries = 3

        for attempt in range(1, max_retries + 1):
            try:
                inlined_schema = self._inline_schema_refs(
                    response_model.model_json_schema()
                )
                response = gemini_client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=temperature,
                        response_mime_type="application/json",
                        response_schema=inlined_schema,
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                    ),
                )

                import json

                response_data = json.loads(response.text)
                # Use model_validate (not **kwargs) so model_validator(mode='before') fires
                return response_model.model_validate(response_data)

            except Exception as e:
                err = str(e)
                if "PROHIBITED_CONTENT" in err or "content_filter" in err.lower():
                    logger.warning("[Gemini] Content filtered. Returning empty model.")
                    return response_model()

                is_retryable = any(code in err for code in _retryable)
                if is_retryable and attempt < max_retries:
                    wait = 2**attempt  # 2s, 4s
                    logger.warning(
                        f"[Gemini] Retryable error (attempt {attempt}/{max_retries}), "
                        f"retrying in {wait}s: {err}"
                    )
                    time.sleep(wait)
                    continue

                logger.error(f"[Gemini] Extraction error: {e}")
                raise

    def _extract_anthropic(
        self, prompt: str, response_model: Type[BaseModel], temperature: float
    ) -> BaseModel:
        """Anthropic extraction with prompt engineering + validation."""
        model = settings.ANTHROPIC_MODEL
        logger.info(f"[Anthropic] Extracting with {model} (prompt-based)")

        # Anthropic doesn't have native schema enforcement, use instructor
        response = self.extraction_client.messages.create(
            model=model,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
            response_model=response_model,
        )

        return response

    def _reason_step(self, prompt: str) -> tuple[str, str | None]:
        """
        Like reason(), but also returns any model thinking/reasoning content.

        Returns:
            (content, thinking) where thinking is the model's internal chain-of-thought
            (from reasoning_content field or <think>…</think> tags), stripped from content.
            thinking is None if the model produced no separate thinking.
        """
        thinking: str | None = None

        if self.provider == "gemini":
            response = self.gemini_client.models.generate_content(
                model=self.get_chat_model(),
                contents=prompt,
            )
            return response.text or "", None

        if self.provider == "anthropic":
            response = self.chat_client.messages.create(
                model=self.get_chat_model(),
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text or "", None

        # Local / LM Studio / OpenAI
        _model = self.get_chat_model()
        extra_body = self._with_keep_alive()

        response = self.chat_client.chat.completions.create(
            model=_model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a deep reasoning engine. Analyze the input carefully. Detect conflicts, subtleties, or hidden connections.",  # pylint: disable=line-too-long
                },
                {"role": "user", "content": prompt},
            ],
            extra_body=extra_body,
        )
        message = response.choices[0].message
        content: str = message.content or ""

        # LM Studio (and some OpenAI-compat servers) expose thinking in reasoning_content
        thinking = getattr(message, "reasoning_content", None) or None

        # Fallback: extract <think>…</think> blocks embedded in content
        if not thinking and "<think>" in content:
            think_match = re.search(r"<think>(.*?)</think>", content, re.DOTALL)
            if think_match:
                thinking = think_match.group(1).strip()
                content = re.sub(
                    r"<think>.*?</think>", "", content, flags=re.DOTALL
                ).strip()

        return content, thinking

    def reason(self, prompt: str, model: str | None = None) -> str:
        """
        Uses the Reasoning Model for complex logic/refinement.
        Returns raw text (Chain-of-Thought + Answer).
        """
        # Select model based on provider
        if self.provider == "gemini":
            response = self.gemini_client.models.generate_content(
                model=model or self.get_chat_model(),
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
                contents=f"{prompt}",
            )
            return response.text
        if self.provider == "anthropic":
            response = self.chat_client.messages.create(
                model=model or self.get_chat_model(),
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        # Ollama/LM Studio/OpenAI
        _model = model or self.get_chat_model()
        extra_body = self._with_keep_alive()

        response = self.chat_client.chat.completions.create(
            model=_model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a deep reasoning engine. Analyze the input carefully. Detect conflicts, subtleties, or hidden connections.",  # pylint: disable=line-too-long
                },
                {"role": "user", "content": prompt},
            ],
            extra_body=extra_body,
        )
        return response.choices[0].message.content

    def generate_title(self, text: str, model: str | None = None) -> str:
        """
        Generates a concise 3-5 word title for a note.
        """
        if not text or not text.strip():
            return "Untitled Note"

        # Select model based on provider
        if self.provider == "gemini":
            response = self.gemini_client.models.generate_content(
                model=model or self.get_chat_model(),
                contents=f"Generate a concise, descriptive title for this note. Do not use quotes.\n\nNote content:\n{text}\n\nTitle:",  # pylint: disable=line-too-long
            )
            return response.text.strip().replace('"', "")
        if self.provider == "anthropic":
            response = self.chat_client.messages.create(
                model=model or self.get_chat_model(),
                messages=[
                    {
                        "role": "user",
                        "content": f"Generate a concise, descriptive title for this note. Do not use quotes.\n\nNote content:\n{text}\n\nTitle:",  # pylint: disable=line-too-long
                    }
                ],
            )
            return response.content[0].text.strip().replace('"', "")
        # Ollama/LM Studio/OpenAI
        _model = model or self.get_chat_model()
        extra_body = self._with_keep_alive()

        response = self.chat_client.chat.completions.create(
            model=_model,
            messages=[
                {
                    "role": "system",
                    "content": "Generate a concise, descriptive title for the provided note content. Do not use quotes.",  # pylint: disable=line-too-long
                },
                {"role": "user", "content": f"Note content:\n{text}\n\nTitle:"},
            ],
            extra_body=extra_body,
        )
        return response.choices[0].message.content.strip().replace('"', "")

    def analyze_query(self, query: str) -> dict:
        """
        Analyzes user query with structured outputs for better retrieval.
        Uses the same extraction approach as ingestion for consistency.
        """
        from typing import Literal

        from pydantic import Field

        class QueryAnalysis(BaseModel):
            """Structured output schema for query-analysis: sub-questions and search hints."""

            intent: Literal[
                "search", "summarize", "compare", "explain", "list", "recent", "verify"
            ] = Field(description="Primary intent of the query")
            entities: list[str] = Field(
                default_factory=list,
                description="Named entities mentioned in the query",
            )
            concepts: list[str] = Field(
                default_factory=list,
                description="Abstract concepts or topics mentioned",
            )
            keywords: list[str] = Field(
                default_factory=list,
                description="Important keywords for semantic search",
            )
            expected_entity_types: list[str] = Field(
                default_factory=list,
                description="Types of entities the answer should be about: Person, Film, Place, Organization, etc.",
            )
            question_attribute: Optional[str] = Field(
                default=None,
                description="What attribute is being asked about: nationality, occupation, birth_date, location, director, capacity, etc.",  # pylint: disable=line-too-long
            )

        # Use the same prompt style as ingestion - concrete JSON examples
        try:
            prompt = f"""Analyze the following search query and return a structured JSON object.

            QUERY: "{query}"

            Return a JSON object with these fields:

            - "entities": Complete named entities exactly as written — never split multi-word names.
            e.g. "Albert Einstein", "The Great Gatsby", "New York City", "Yale University"

            - "entity_types": The types of entities the answer will involve.
            e.g. ["Person"], ["Film", "Person"], ["Place"], ["Organization", "Person"], ["Venue"]

            - "question_attribute": The specific attribute being asked about.
            e.g. "nationality", "occupation", "director", "location", "capacity", "birth_date", "award"

            - "intent": One of — search / compare / summarize / explain / list

            - "keywords": Important terms to use when searching, excluding named entities already captured above.

            EXAMPLES:

            Query: "Were Albert Einstein and Marie Curie of the same nationality?"
            {{"entities": ["Albert Einstein", "Marie Curie"], "expected_entity_types": ["Person"], "question_attribute": "nationality", "intent": "compare", "keywords": ["nationality"]}}

            Query: "What award did the author of 1984 win?"
            {{"entities": ["1984"], "expected_entity_types": ["Book", "Person"], "question_attribute": "award", "intent": "search", "keywords": ["author", "award"]}}

            Query: "How many seats does Madison Square Garden have?"
            {{"entities": ["Madison Square Garden"], "expected_entity_types": ["Venue"], "question_attribute": "capacity", "intent": "search", "keywords": ["seats", "capacity"]}}

            Query: "Who directed Inception?"
            {{"entities": ["Inception"], "expected_entity_types": ["Film", "Person"], "question_attribute": "director", "intent": "search", "keywords": ["directed"]}}

            Return only the JSON object, no preamble or explanation.
            """

            # Use extract_structured - same as ingestion
            result = self.extract_structured(prompt, QueryAnalysis, temperature=0)
            if result:
                return result.model_dump()
            raise ValueError("Empty extraction result")

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error(f"Query analysis failed: {e}")
            # Return safe defaults
            return {
                "intent": "search",
                "entities": [],
                "concepts": [],
                "keywords": query.split(),
                "expected_entity_types": [],
                "question_attribute": None,
            }

    async def generate(
        self,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> str:
        """
        Generic text generation - provider-agnostic.

        Use this for simple text generation tasks (alias comparison, classification, etc).

        Args:
            prompt: The prompt to send to the LLM
            temperature: Sampling temperature (0=deterministic, 1=creative)
            max_tokens: Max tokens in response

        Returns:
            Generated text response
        """
        try:
            if self.provider == "gemini":
                _gemini_model = model or self.get_chat_model()
                _gemini_cfg = types.GenerateContentConfig(
                    temperature=temperature,
                    thinking_config=types.ThinkingConfig(
                        thinking_budget=0,  # thinking_level="MINIMAL"
                    ),
                )
                response = await asyncio.to_thread(
                    self.gemini_client.models.generate_content,
                    model=_gemini_model,
                    contents=prompt,
                    config=_gemini_cfg,
                )
                return response.text.strip()

            if self.provider == "anthropic":
                response = await asyncio.to_thread(
                    self.chat_client.messages.create,
                    model=model or self.get_chat_model(),
                    max_tokens=max_tokens if max_tokens is not None else 8192,
                    temperature=temperature,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text.strip()

            # OpenAI-compatible local or cloud providers
            model = model or self.get_chat_model()
            extra_body = self._with_keep_alive()

            _kwargs = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "extra_body": extra_body,
            }
            if max_tokens is not None:
                _kwargs["max_tokens"] = max_tokens
            response = await asyncio.to_thread(
                self.chat_client.chat.completions.create, **_kwargs
            )
            return response.choices[0].message.content.strip()

        except Exception as e:
            logger.error(f"[LLM] generate() failed: {e}")
            raise

    async def iterative_step(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals,too-many-branches,too-many-statements
        self,
        original_question: str,
        accumulated_steps: list[dict],
        search_query: str | None,
        docs: list[dict],
        tried_queries: list[str] | None = None,
    ) -> dict:  # pylint: disable=too-many-arguments,too-many-positional-arguments
        """
        Single iteration of the iterative retrieval loop.

        Args:
            original_question: The original user question.
            accumulated_steps: Steps taken so far:
                [{query, full_answer, reasoning}, ...]
            search_query: The query used to retrieve ``docs``, or None on the
                first call (before any retrieval).
            docs: Documents retrieved for ``search_query``, or [] on the first
                call.
            tried_queries: All queries already attempted (prevents loop from
                repeating the same search).

        Returns:
            {
                "reasoning":    str,           # reasoning over current docs
                "full_answer":  str,           # contextual answer from docs
                "can_answer":   bool,          # True if question can be answered
                "final_answer": str | None,    # bare answer phrase (if can_answer)
                "next_query":   str | None,    # next search query (if not can_answer)
            }
        """
        _non_answers = {"INSUFFICIENT", "NONE", "N/A", "UNKNOWN", "NOT FOUND"}

        # ── Build prior findings block ────────────────────────────────────────
        prior_block = ""
        if accumulated_steps:
            lines = []
            for i, step in enumerate(accumulated_steps, 1):
                q = step.get("query", "")
                r = step.get("reasoning", "")
                fa = step.get("full_answer", "")
                entry = f"Step {i}: Searched for '{q}'"
                if r:
                    entry += f"\n  Reasoning: {r}"
                entry += f"\n  Finding: {fa or 'Not found'}"
                lines.append(entry)
            prior_block = "PRIOR FINDINGS:\n" + "\n\n".join(lines) + "\n\n"

        # ── Already-tried queries block (prevents repetitive cycling) ─────────
        tried_block = ""
        if tried_queries:
            tried_block = (
                "QUERIES ALREADY TRIED (do NOT repeat these — choose a different angle):\n"
                + "\n".join(f"  - {q}" for q in tried_queries)
                + "\n\n"
            )

        # ── Build current search block ────────────────────────────────────────
        current_block = ""
        if search_query and docs:
            context_lines = []
            for doc in docs:
                text = (doc.get("text") or "").strip()
                if text:
                    context_lines.append(text)
            context = (
                "\n\n---\n\n".join(context_lines)
                if context_lines
                else "(no text found)"
            )
            current_block = (
                f"CURRENT SEARCH: '{search_query}'\n\n"
                f"RETRIEVED DOCUMENTS:\n{context}\n\n"
            )

        # ── Build task instructions ───────────────────────────────────────────
        if search_query and docs:
            if settings.BENCHMARK_MODE:
                task_instructions = (
                    "Assess the current results:\n"
                    "REASONING: <how these documents relate to the question "
                    "and prior findings>\n"
                    "FINDING: <the specific fact(s) extracted from these documents, "
                    "e.g. 'Scott Derrickson is American' or 'Ed Wood was born in 1924'. "
                    "This is NOT the final answer to the original question — just what "
                    "this search found. Always write something; use 'Not found' only "
                    "if nothing in these documents is relevant to the query>\n\n"
                    "Then decide:\n"
                    "  If you have enough information to answer the ORIGINAL QUESTION confidently:\n"
                    "  ANSWER: <the specific answer — see output rules below>\n\n"
                    "  If you need more information:\n"
                    "  NEXT_QUERY: <one specific search query, different from all prior ones>\n\n"
                    f"{self._REASONING_RULES}\n"
                    f"{self._OUTPUT_RULES}"
                )
            else:
                task_instructions = (
                    "Assess the current results:\n"
                    "REASONING: <how these documents relate to the question "
                    "and what you have found so far>\n"
                    "FINDING: <a summary of what is relevant in these documents — "
                    "key facts, entities, relationships. Always write something; "
                    "use 'Not found' only if truly nothing here is relevant>\n\n"
                    "Then decide:\n"
                    "  If you have enough information to answer the ORIGINAL QUESTION:\n"
                    "  ANSWER: <a complete, natural-language answer covering everything "
                    "relevant you found — see output rules below>\n\n"
                    "  If you need more information:\n"
                    "  NEXT_QUERY: <one specific search query, different from all prior ones>\n\n"
                    f"{self._REASONING_RULES_GENERAL}\n"
                    f"{self._OUTPUT_RULES_GENERAL}"
                )
        else:
            task_instructions = (
                "Output the first search query needed to start answering this question:\n"
                "NEXT_QUERY: <one specific search query>\n"
            )

        prompt = (
            "You are a research assistant solving a multi-hop question step by step.\n\n"
            f"ORIGINAL QUESTION: {original_question}\n\n"
            f"{prior_block}"
            f"{tried_block}"
            f"{current_block}"
            f"{task_instructions}"
            "\nReply:"
        )

        try:
            raw, step_thinking = await asyncio.to_thread(self._reason_step, prompt)
            raw = raw or ""
            logger.info(f"[LLM] iterative_step raw response:\n{raw}")
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning(f"[LLM] iterative_step failed: {e}")
            return {
                "reasoning": "",
                "full_answer": "",
                "can_answer": False,
                "final_answer": None,
                "next_query": None,
                "thinking": None,
            }

        # ── Parse response ────────────────────────────────────────────────────
        reasoning = ""
        full_answer = ""
        can_answer = False
        final_answer: str | None = None
        next_query: str | None = None

        # Regex-based section extractor — handles:
        #   * markdown bold: **ANSWER:** or **FINDING:**
        #   * multi-line section content (FINDING:\ntext on next line)
        #   * any mix of the above
        _section_re = re.compile(
            r"\*{0,3}(REASONING|FINDING|FULL_ANSWER|ANSWER|NEXT_QUERY)\*{0,3}\s*:[ \t]*(.*?)"
            r"(?=\*{0,3}(?:REASONING|FINDING|FULL_ANSWER|ANSWER|NEXT_QUERY)\*{0,3}\s*:|\Z)",
            re.IGNORECASE | re.DOTALL,
        )
        sections: dict[str, str] = {}
        for m in _section_re.finditer(raw):
            key = m.group(1).upper()
            val = m.group(2).strip()
            if key not in sections:  # first occurrence wins
                sections[key] = val

        reasoning = sections.get("REASONING", "")
        full_answer = sections.get("FINDING", "") or sections.get("FULL_ANSWER", "")
        answer_val = sections.get("ANSWER", "")
        next_query_val = sections.get("NEXT_QUERY", "")

        if answer_val and answer_val.upper() not in _non_answers:
            can_answer = True
            final_answer = answer_val
        elif next_query_val:
            next_query = next_query_val

        # ── Post-process ANSWER ───────────────────────────────────────────────
        # Fallback: if the LLM committed FULL_ANSWER but gave neither ANSWER nor
        # NEXT_QUERY, it found the information but forgot to switch to the
        # terminating format.  Treat FULL_ANSWER as the final answer.
        _not_found_vals = {"not found", "none", "insufficient", "n/a", "unknown"}
        if (
            not can_answer
            and not next_query
            and full_answer
            and full_answer.lower().strip() not in _not_found_vals
        ):
            logger.info(
                "[LLM] iterative_step FULL_ANSWER fallback (no ANSWER/NEXT_QUERY): "
                f"'{full_answer}'"
            )
            can_answer = True
            final_answer = full_answer

        return {
            "reasoning": reasoning,
            "full_answer": full_answer,
            "can_answer": can_answer,
            "final_answer": final_answer,
            "next_query": next_query,
            "thinking": step_thinking,
        }

    # Reasoning rules ported from benchmark v4/v5 (the 0.74-scoring pipeline).
    # Enforces correct answer-type discipline, comparison direction, specificity, and past/present.
    _REASONING_RULES = """
        REASONING RULES — apply these before writing your answer:

        CHAIN TRACING
        - For multi-hop questions, trace findings in order. The bridge entity (answer to an 
        intermediate step) is not the final answer — use it to reach what was actually asked.
        - Explicitly name the bridge entity first, then derive the final answer from it.

        COMPARISON & YES/NO
        - For yes/no comparisons: extract the relevant value per entity, compare, then output 
        YES or NO — never the compared value itself.
        - For "which of X or Y is more/older/greater": output the winner's full name, not the 
        metric. Older = earlier birth year.
        - If the question asks whether two entities BOTH share a property: verify each 
        separately. YES only if both are confirmed.
        - "Was X founded by the person who did Y?" → output the name, not YES.
        Only output YES/NO for explicit comparisons or shared-property questions.
        - For yes/no questions: your ANSWER line must be YES or NO — never an intermediate 
        value like a nationality, number, or name. Derive the YES/NO conclusion yourself 
        from the evidence before writing ANSWER.

        ANSWER TYPE
        - Match exactly what the question asks for.
        Common traps: song ≠ person; show ≠ character; position ≠ person holding it; 
        city ≠ building; number ≠ demonym; animal ≠ person named after it.
        - Before writing your answer, verify it matches the type asked for.

        SPECIFICITY & SCOPE
        - Use the most specific value the evidence supports. Do not broaden:
        neighborhood → city, city → country, person → organization.
        - If two entities share a parent region, output the parent. Only list sub-locations 
        when they differ.
        - One answer only. Do not list alternatives or add caveats.

        EXACT EXTRACTION
        - Do NOT add: parent geography, org prefix, or qualifiers not implied by the question.
        - Do NOT strip: first names, suffixes, units, or qualifiers that are part of the answer.
        - For time spans: copy the exact phrase from the source including connectives 
        (from/until/through/between). Do not normalize — if the source says "until", keep "until".
        - For qualified quantities (e.g. "net", "peak", "opening", "seat"): use the figure 
        carrying that exact qualifier, not a broader or unqualified figure.

        TEMPORAL
        - If the question asks for a former or historical value, use the value from that period.
        """

    _OUTPUT_RULES = """
        OUTPUT RULES:
        - Return only the specific fact the question asks for — nothing else
        - Yes/no question → YES or NO
        - Comparison / either-or → exactly one of the options given
        - Name → full name as it appears in the source
        - Number → include units or qualifiers the question implies
        - Date or time range → exact phrase from source, preserving all connectives
        - Role, title, or position → the role/title only, never the person holding it
        - Location → exact place name as it appears in the source
        - Never answer "Neither" or "Both" unless the question explicitly asks for it
        - If you cannot answer yet → output NEXT_QUERY, not ANSWER
        """

    # ── General KB mode rules (BENCHMARK_MODE=False) ──────────────────────────
    # Used for personal knowledge bases where the goal is a thorough,
    # natural-language answer — not a single extracted fact.

    _REASONING_RULES_GENERAL = """
        REASONING RULES:
        - Trace your findings step by step across all prior searches
        - Cover all relevant aspects you have found, not just one fact
        - Note relationships and connections between entities across searches
        - If multiple searches returned related information, synthesise them
        """

    _OUTPUT_RULES_GENERAL = """
        OUTPUT RULES:
        - Write a complete, natural-language answer covering all relevant things you found
        - Be thorough — it is better to include more than to leave something out
        - Organise clearly if there are multiple aspects (e.g. short paragraphs or a list)
        - Stick strictly to what the documents say — do not invent or infer beyond the evidence
        - If something relevant could not be found, acknowledge it briefly
        - Do not pad with filler phrases — every sentence should add information
        - If you cannot answer yet → output NEXT_QUERY, not ANSWER
        """

    def get_chat_model(self) -> str:
        """Return the model to use for chat and generation tasks.

        CHAT_MODEL always wins if set — provider-specific keys are fallbacks.
        """
        if settings.CHAT_MODEL:
            return settings.CHAT_MODEL
        if self.provider in ("ollama", "lm_studio", "local"):
            return settings.LLM_MODEL
        provider_model_map = {
            "openai": settings.OPENAI_MODEL,
            "gemini": settings.GEMINI_MODEL,
            "anthropic": settings.ANTHROPIC_MODEL,
            "huggingface": settings.HUGGINGFACE_MODEL,
        }
        return provider_model_map.get(self.provider, settings.LLM_MODEL)

    def get_ingestion_model(self) -> str | None:
        """Return the configured ingestion model for the active ingestion provider.

        INGESTION_MODEL always wins if set — provider-specific keys are fallbacks.
        """
        if settings.INGESTION_MODEL:
            return settings.INGESTION_MODEL
        p = getattr(self, "ingestion_provider", self.provider)
        _local = settings.INGESTION_LLM_MODEL or settings.LLM_MODEL or None
        ingestion_model_map = {
            "ollama": _local,
            "lm_studio": _local,
            "local": _local,
            "gemini": settings.INGESTION_GEMINI_MODEL or settings.GEMINI_MODEL or None,
            "openai": settings.OPENAI_MODEL or None,
            "anthropic": settings.ANTHROPIC_MODEL or None,
            "huggingface": settings.HUGGINGFACE_MODEL or None,
        }
        return ingestion_model_map.get(p)

    # ── Ingestion-specific generation ─────────────────────────────────────────

    async def ingestion_generate(
        self,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> str:
        """
        Like ``generate()`` but always routes to the ingestion provider/server.
        Use this for all LLM calls inside the ingestion pipeline.
        """
        model = self.get_ingestion_model()
        try:
            if self.ingestion_provider == "gemini":
                _gemini_model = model or settings.GEMINI_MODEL
                _gemini_cfg = types.GenerateContentConfig(
                    temperature=temperature,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                )
                response = await asyncio.to_thread(
                    self.i_gemini_client.models.generate_content,
                    model=_gemini_model,
                    contents=prompt,
                    config=_gemini_cfg,
                )
                return response.text.strip()

            if self.ingestion_provider == "anthropic":
                response = await asyncio.to_thread(
                    self.i_anthropic_client.messages.create,
                    model=settings.ANTHROPIC_MODEL,
                    max_tokens=max_tokens if max_tokens is not None else 8192,
                    temperature=temperature,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text.strip()

            # local / ollama / lm_studio / openai / huggingface
            _kwargs = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "extra_body": self._with_ingestion_keep_alive(),
            }
            if max_tokens is not None:
                _kwargs["max_tokens"] = max_tokens
            response = await asyncio.to_thread(
                self.i_chat_client.chat.completions.create, **_kwargs
            )
            content = response.choices[0].message.content
            if not content or not content.strip():
                raise ValueError(
                    "Local LLM returned empty content (0 output tokens). "
                    "Possible causes: context overflow, KV cache pressure, or "
                    "model crash. Check LM Studio / Ollama server logs."
                )
            return content.strip()

        except Exception as e:
            logger.error(f"[LLM] ingestion_generate() failed: {e}")
            raise

    def ingestion_extract_structured(  # pylint: disable=too-many-return-statements
        self,
        prompt: str,
        response_model: Type[BaseModel],
        temperature: float = 0.1,
    ):
        """
        Like ``extract_structured()`` but always routes to the ingestion provider/server.
        Use this for all structured extraction inside the ingestion pipeline.
        """
        model = self.get_ingestion_model()
        try:
            if self.ingestion_provider in ("local", "ollama", "lm_studio"):
                return self._extract_lm_studio(
                    prompt,
                    response_model,
                    temperature,
                    model=model,
                    _client=self.i_chat_client,
                )
            if self.ingestion_provider == "gemini":
                return self._extract_gemini(
                    prompt,
                    response_model,
                    temperature,
                    model=model,
                    _gemini_client=self.i_gemini_client,
                )
            if self.ingestion_provider == "openai":
                # Reuse main OpenAI extraction (uses i_chat_client via beta parse)
                return self._extract_openai(prompt, response_model, temperature)
            if self.ingestion_provider == "anthropic":
                return self._extract_anthropic(prompt, response_model, temperature)
            if self.ingestion_provider == "huggingface":
                return self._extract_huggingface(prompt, response_model, temperature)
            raise ValueError(
                f"Unsupported ingestion provider: {self.ingestion_provider}"
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error(
                f"Ingestion extraction failed ({self.ingestion_provider}): {e}"
            )
            try:
                return response_model()
            except Exception:  # pylint: disable=broad-exception-caught
                return None


class _LazyLLMService:
    """Proxy that defers LLMService construction until first attribute access.

    This keeps torch and all LLM provider clients out of the process until
    something actually calls into the service, saving ~150-200 MB of idle RAM.
    """

    def __init__(self) -> None:
        object.__setattr__(self, "_real", None)

    def _get_real(self) -> "LLMService":
        real = object.__getattribute__(self, "_real")
        if real is None:
            real = LLMService()
            object.__setattr__(self, "_real", real)
        return real

    def __getattr__(self, name: str):
        return getattr(self._get_real(), name)

    def __setattr__(self, name: str, value) -> None:
        setattr(self._get_real(), name, value)


llm_service = _LazyLLMService()
