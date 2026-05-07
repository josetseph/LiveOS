import os
import re
from typing import Optional, Type

import httpx
import instructor
import torch
from app.core.config import settings
from app.core.log import get_logger
from google import genai
from google.genai import types
from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel

logger = get_logger("LLMService")


class LLMService:
    def __init__(self):
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.models_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "../../models")
        )

        # Determine Primary Provider
        self.provider = settings.LLM_PROVIDER.lower()
        self.fallback_provider = settings.LLM_FALLBACK_PROVIDER

        logger.info(f"Primary LLM Provider: {self.provider.upper()}")
        if self.fallback_provider:
            logger.info(f"Fallback LLM Provider: {self.fallback_provider.upper()}")

        # Initialize provider-specific clients
        self._init_clients()

        # Legacy compatibility flags
        self.is_gemini = self.provider == "gemini"

    def _init_clients(self):
        """Initialize clients for the configured provider."""
        if self.provider == "ollama":
            base_url = f"{settings.LLM_BASE_URL.rstrip('/')}/v1"
            logger.info(f"Initializing Ollama (URL: {base_url})")
            api_key = settings.LLM_API_KEY
            # Local models can take a long time to respond — use a generous read timeout
            _local_timeout = httpx.Timeout(
                connect=30.0, read=3600.0, write=60.0, pool=60.0
            )

            self.extraction_client = instructor.patch(
                OpenAI(
                    base_url=base_url,
                    api_key=api_key,
                    timeout=_local_timeout,
                    max_retries=3,
                ),
                mode=instructor.Mode.MD_JSON,
            )
            self.chat_client = OpenAI(
                base_url=base_url,
                api_key=api_key,
                timeout=_local_timeout,
                max_retries=3,
            )
            # Async client for batch processing
            self.async_chat_client = AsyncOpenAI(
                base_url=base_url,
                api_key=api_key,
                timeout=_local_timeout,
                max_retries=3,
            )

        elif self.provider == "lm_studio":
            base_url = f"{settings.LLM_BASE_URL.rstrip('/')}/v1"
            logger.info(
                f"Initializing LM Studio (URL: {base_url}, Model: {settings.LLM_MODEL})"
            )
            api_key = settings.LLM_API_KEY
            _local_timeout = httpx.Timeout(
                connect=30.0, read=3600.0, write=60.0, pool=60.0
            )

            self.extraction_client = instructor.patch(
                OpenAI(
                    base_url=base_url,
                    api_key=api_key,
                    timeout=_local_timeout,
                    max_retries=3,
                )
            )
            self.chat_client = OpenAI(
                base_url=base_url,
                api_key=api_key,
                timeout=_local_timeout,
                max_retries=3,
            )
            self.async_chat_client = AsyncOpenAI(
                base_url=base_url,
                api_key=api_key,
                timeout=_local_timeout,
                max_retries=3,
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
            class GeminiChatWrapper:
                def __init__(self, native_client):
                    self.native_client = native_client
                    self.chat = self

                class Completions:
                    def __init__(self, native_client):
                        self.native_client = native_client

                    def create(
                        self,
                        model,
                        messages,
                        max_tokens=None,
                        extra_body=None,
                        temperature=0.1,
                    ):
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
                        class Choice:
                            def __init__(self, text):
                                self.message = type("Message", (), {"content": text})()

                        class Response:
                            def __init__(self, text):
                                self.choices = [Choice(text)]

                        return Response(response.text)

                @property
                def completions(self):
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

    def _with_keep_alive(self, extra_body: dict | None = None) -> dict:
        """Attach provider keep-alive controls for local OpenAI-compatible backends."""
        body = dict(extra_body or {})
        if self.provider in ("ollama", "lm_studio"):
            body.setdefault("keep_alive", settings.LLM_KEEP_ALIVE)
        return body

    def _lm_studio_json_response_format(
        self, schema: dict | None = None, schema_name: str = "response"
    ) -> dict:
        """
        Force json_object mode to avoid LM Studio grammar compilation stalls
        on large nested schemas.
        """
        return {"type": "json_object"}

    def _lm_studio_text_response_format(self) -> dict:
        """Compatibility fallback for servers that don't accept json_object."""
        return {"type": "text"}

    def _lm_studio_response_format_candidates(
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
        except Exception as e:
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

    def extract_structured(
        self, prompt: str, response_model: Type[BaseModel], temperature: float = 0.1
    ) -> Optional[BaseModel]:
        """
        Provider-agnostic structured extraction with native schema enforcement.
        Supports: Ollama, LM Studio, OpenAI, Gemini, Anthropic (with fallback).
        """
        try:
            if self.provider == "ollama":
                return self._extract_ollama(prompt, response_model, temperature)
            elif self.provider == "lm_studio":
                return self._extract_lm_studio(prompt, response_model, temperature)
            elif self.provider == "openai":
                return self._extract_openai(prompt, response_model, temperature)
            elif self.provider == "gemini":
                return self._extract_gemini(prompt, response_model, temperature)
            elif self.provider == "anthropic":
                return self._extract_anthropic(prompt, response_model, temperature)
            elif self.provider == "huggingface":
                return self._extract_huggingface(prompt, response_model, temperature)
            else:
                raise ValueError(f"Unsupported provider: {self.provider}")

        except Exception as e:
            logger.error(f"Extraction failed with {self.provider}: {e}")

            # Try fallback provider if configured
            if self.fallback_provider:
                logger.info(f"Attempting fallback to {self.fallback_provider}")
                try:
                    original_provider = self.provider
                    self.provider = self.fallback_provider
                    self._init_clients()
                    result = self.extract_structured(
                        prompt, response_model, temperature
                    )
                    # Restore original provider
                    self.provider = original_provider
                    self._init_clients()
                    return result
                except Exception as fallback_error:
                    logger.error(f"Fallback extraction failed: {fallback_error}")
                    # Restore original provider
                    self.provider = original_provider
                    self._init_clients()

            # Final fallback: return empty model
            try:
                return response_model()
            except Exception:
                return None

    def _extract_ollama(
        self, prompt: str, response_model: Type[BaseModel], temperature: float
    ) -> BaseModel:
        """Ollama extraction with native structured outputs."""
        model = settings.LLM_MODEL
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
        except Exception:
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
        self, prompt: str, response_model: Type[BaseModel], temperature: float
    ) -> BaseModel:
        """LM Studio extraction using prompt-guided JSON object mode."""
        import json

        model = self._get_model_for_task("extraction")
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
        )
        cleaned_json = self._clean_json(raw_content)
        try:
            return response_model.model_validate_json(cleaned_json)
        except Exception:
            # Some LM Studio models wrap result in {"extraction": {...}}.
            import json

            data = json.loads(cleaned_json)
            if isinstance(data, dict) and isinstance(data.get("extraction"), dict):
                return response_model.model_validate(data["extraction"])
            raise

    def _extract_lm_studio_with_fallback(
        self,
        model: str,
        system_prompt: str,
        prompt: str,
        temperature: float,
        schema: dict | None = None,
        schema_name: str = "response",
    ) -> str:
        """
        Try configured response_format strategy with compatibility fallbacks.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        last_error = None
        for response_format in self._lm_studio_response_format_candidates(
            schema=schema, schema_name=schema_name
        ):
            try:
                response = self.chat_client.chat.completions.create(
                    model=model,
                    messages=messages,
                    response_format=response_format,
                    extra_body=self._with_keep_alive(),
                    temperature=temperature,
                )
                return response.choices[0].message.content
            except Exception as e:
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
            except Exception as e:
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

    def _extract_gemini(
        self, prompt: str, response_model: Type[BaseModel], temperature: float
    ) -> BaseModel:
        """Gemini extraction with native SDK and JSON schema enforcement."""
        import time

        model = settings.GEMINI_MODEL
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
                response = self.gemini_client.models.generate_content(
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

    def reason(self, prompt: str) -> str:
        """
        Uses the Reasoning Model for complex logic/refinement.
        Returns raw text (Chain-of-Thought + Answer).
        """
        # Select reasoning model based on provider
        if self.provider == "gemini":
            response = self.gemini_client.models.generate_content(
                model=settings.GEMINI_MODEL,
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
                contents=f"You are a deep reasoning engine. Analyze the input carefully. Detect conflicts, subtleties, or hidden connections.\n\n{prompt}",
            )
            return response.text
        elif self.provider == "anthropic":
            response = self.chat_client.messages.create(
                model=settings.ANTHROPIC_MODEL,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        else:
            # Ollama/LM Studio/OpenAI
            model = self._get_model_for_task("reasoning")
            extra_body = self._with_keep_alive()

            response = self.chat_client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a deep reasoning engine. Analyze the input carefully. Detect conflicts, subtleties, or hidden connections.",
                    },
                    {"role": "user", "content": prompt},
                ],
                extra_body=extra_body,
            )
            return response.choices[0].message.content

    def generate_title(self, text: str) -> str:
        """
        Generates a concise 3-5 word title for a note.
        """
        if not text or not text.strip():
            return "Untitled Note"

        # Select model based on provider
        if self.provider == "gemini":
            response = self.gemini_client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=f"Generate a concise, descriptive title for this note. Do not use quotes.\n\nNote content:\n{text}\n\nTitle:",
            )
            return response.text.strip().replace('"', "")
        elif self.provider == "anthropic":
            response = self.chat_client.messages.create(
                model=settings.ANTHROPIC_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": f"Generate a concise, descriptive title for this note. Do not use quotes.\n\nNote content:\n{text}\n\nTitle:",
                    }
                ],
            )
            return response.content[0].text.strip().replace('"', "")
        else:
            # Ollama/LM Studio/OpenAI
            model = self._get_model_for_task("summarization")
            extra_body = self._with_keep_alive()

            response = self.chat_client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant. Generate a concise, descriptive title (3-6 words) for the provided note content. Do not use quotes.",
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
        from typing import Literal, Optional

        from pydantic import Field

        class QueryAnalysis(BaseModel):
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
                description="What attribute is being asked about: nationality, occupation, birth_date, location, director, capacity, etc.",
            )

        # Use the same prompt style as ingestion - concrete JSON examples
        prompt = f"""Analyze this search query and extract structured information.

QUERY: "{query}"

ENTITY EXTRACTION RULES (CRITICAL):
- Extract COMPLETE multi-word names as SINGLE strings
- Person names: "Albert Einstein", "Marie Curie", "James P. Sullivan" (NOT split into individual words)
- Movie/Book titles: "The Great Gatsby", "Jurassic Park" (NOT split)
- Place names: "Eiffel Tower", "New York City" (NOT split)
- Organization names: "Yale University", "Microsoft Corporation" (NOT split)

ENTITY TYPE INFERENCE (CRITICAL):
Based on what the question is asking about, determine what types of entities the answer requires.
- "nationality", "born", "age", "occupation", "married" → expected_entity_types: ["Person"]
- "directed by", "starring", "released" (for films) → expected_entity_types: ["Film", "Person"]
- "located in", "capital of", "population" → expected_entity_types: ["Place"]
- "founded", "headquarters", "CEO" → expected_entity_types: ["Organization", "Person"]
- "capacity", "seats", "arena" → expected_entity_types: ["Venue", "Place"]

QUESTION ATTRIBUTE:
Identify what specific attribute is being asked about:
- "nationality" for questions about country of origin
- "occupation" for job/profession questions
- "director" for who directed a film
- "location" for where something is
- "capacity" for size/seats
- "birth_date", "death_date" for dates

EXAMPLES:
Query: "Were Albert Einstein and Marie Curie of the same nationality?"
{{"entities": ["Albert Einstein", "Marie Curie"], "expected_entity_types": ["Person"], "question_attribute": "nationality"}}

Query: "What award did the author of 1984 win?"
{{"entities": ["1984"], "expected_entity_types": ["Book", "Person"], "question_attribute": "award"}}

Query: "How many seats does Madison Square Garden have?"
{{"entities": ["Madison Square Garden"], "expected_entity_types": ["Venue", "Place"], "question_attribute": "capacity"}}

Query: "Who directed the movie Inception?"
{{"entities": ["Inception"], "expected_entity_types": ["Film", "Person"], "question_attribute": "director"}}

Now analyze the query above and return a JSON object with:
- intent: The primary goal (search/summarize/compare/explain/list/recent)
- entities: List of COMPLETE named entities (never split names)
- concepts: List of abstract topics
- keywords: List of important search terms
- expected_entity_types: List of entity types the answer should be about (Person, Film, Place, Organization, Venue, etc.)
- question_attribute: What attribute is being asked about (nationality, occupation, director, location, capacity, etc.)
"""

        try:
            # Use extract_structured - same as ingestion
            result = self.extract_structured(prompt, QueryAnalysis, temperature=0)
            if result:
                return result.model_dump()
            else:
                raise ValueError("Empty extraction result")

        except Exception as e:
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

    def decompose_query(self, query: str) -> dict:
        """
        Detects if a query requires multi-hop reasoning and breaks it down into sub-questions.

        Returns:
            dict with:
                - requires_decomposition: bool (whether decomposition is needed)
                - question_type: str (comparison, multi_hop, single_hop, etc.)
                - sub_questions: list of dicts with 'text' and 'type'
                - synthesis_strategy: str (instructions for combining answers)
                - entities: list of main entities
                - attribute: str (attribute being queried)
        """
        from typing import Literal, Optional

        from pydantic import Field

        class SubQuestion(BaseModel):
            text: str = Field(description="The sub-question text")
            question_type: Literal[
                "entity_lookup",
                "entity",
                "attribute",
                "attribute_lookup",
                "relationship",
                "comparison",
            ] = Field(description="Type of sub-question")

        class QueryDecomposition(BaseModel):
            requires_decomposition: bool = Field(
                description="True if question requires multi-hop reasoning or comparison"
            )
            question_type: Literal[
                "comparison", "multi_hop", "single_hop", "counting", "list"
            ] = Field(description="Type of question")
            entities: list[str] = Field(
                default_factory=list, description="Main entities in the question"
            )
            attribute: Optional[str] = Field(
                default=None,
                description="Attribute being asked about (nationality, occupation, etc.)",
            )
            sub_questions: list[SubQuestion] = Field(
                default_factory=list,
                description="Sub-questions if decomposition is needed",
            )
            synthesis_strategy: str = Field(
                description="Instructions for combining sub-answers into final answer"
            )

        prompt = f"""Analyze this question and determine if it requires multi-hop reasoning or comparison.

QUESTION: "{query}"

MULTI-HOP QUESTIONS (require decomposition):
- Questions that chain information across multiple entities
    Example: "What award did the actor who played the lead in Example Film win?"
  → Need to first find the actress, then find what award she won

- Comparison questions between two or more entities
  Example: "Were Christopher Nolan and Denis Villeneuve both born in North America?"
  → Need to find each person's birthplace, then compare

- Questions requiring relationship traversal
  Example: "Who directed the movie starring the actor who won Best Actor in 1995?"
  → Need to find the actor, then the movie, then the director

SINGLE-HOP QUESTIONS (no decomposition needed):
- Direct attribute lookup: "What is Einstein's nationality?"
- Simple relationship: "Who directed Inception?"
- Existence check: "Did Einstein win a Nobel Prize?"

DECOMPOSITION RULES:
For comparison questions:
- Create one sub-question per entity for the attribute being compared
- Synthesis: "Compare the values and return 'yes' if same, 'no' if different"

For multi-hop questions:
- Break into sequential sub-questions following the chain
- First question extracts intermediate entity
- Second question uses that entity to get final answer
- Synthesis: "Extract the answer from the final sub-question"

EXAMPLES:

Input: "Were Christopher Nolan and Denis Villeneuve both born in North America?"
Output:
{{
    "requires_decomposition": true,
    "question_type": "comparison",
    "entities": ["Christopher Nolan", "Denis Villeneuve"],
    "attribute": "birthplace",
    "sub_questions": [
        {{"text": "Where was Christopher Nolan born?", "question_type": "attribute"}},
        {{"text": "Where was Denis Villeneuve born?", "question_type": "attribute"}}
    ],
    "synthesis_strategy": "Check if both birthplaces are in North America. Answer 'yes' if both are, 'no' otherwise."
}}

Input: "What award did the actor who played the lead in Example Film win?"
Output:
{{
    "requires_decomposition": true,
    "question_type": "multi_hop",
    "entities": ["Example Film"],
    "attribute": "award",
    "sub_questions": [
        {{"text": "Who played the lead in Example Film?", "question_type": "relationship"}},
        {{"text": "What award did [actor from previous answer] win?", "question_type": "attribute"}}
    ],
    "synthesis_strategy": "Use the actor name from the first answer to answer the second question. Return the award name."
}}

Input: "What is Einstein's nationality?"
Output:
{{
    "requires_decomposition": false,
    "question_type": "single_hop",
    "entities": ["Einstein"],
    "attribute": "nationality",
    "sub_questions": [],
    "synthesis_strategy": "Direct answer - no decomposition needed"
}}

Now analyze the question above and return JSON with the decomposition structure.
"""

        try:
            result = self.extract_structured(prompt, QueryDecomposition, temperature=0)
            if result:
                return result.model_dump()
            else:
                raise ValueError("Empty decomposition result")

        except Exception as e:
            logger.error(f"Query decomposition failed: {e}")
            # Return safe default - no decomposition
            return {
                "requires_decomposition": False,
                "question_type": "single_hop",
                "entities": [],
                "attribute": None,
                "sub_questions": [],
                "synthesis_strategy": "Direct answer",
            }

    async def generate(
        self, prompt: str, temperature: float = 0.1, max_tokens: int | None = None
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
                response = self.gemini_client.models.generate_content(
                    model=settings.GEMINI_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=temperature,
                        thinking_config=types.ThinkingConfig(
                            thinking_budget=0,  # thinking_level="MINIMAL"
                        ),
                    ),
                )
                return response.text.strip()

            elif self.provider == "anthropic":
                response = self.chat_client.messages.create(
                    model=settings.ANTHROPIC_MODEL,
                    max_tokens=max_tokens if max_tokens is not None else 8192,
                    temperature=temperature,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text.strip()

            else:  # OpenAI-compatible local or cloud providers
                model = self._get_model_for_task("brain")
                extra_body = self._with_keep_alive()

                _kwargs = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": temperature,
                    "extra_body": extra_body,
                }
                if max_tokens is not None:
                    _kwargs["max_tokens"] = max_tokens
                response = self.chat_client.chat.completions.create(**_kwargs)
                return response.choices[0].message.content.strip()

        except Exception as e:
            logger.error(f"[LLM] generate() failed: {e}")
            raise

    async def identify_information_needs(self, query: str) -> list[str]:
        """
        Ask the LLM what intermediate information it needs to answer a complex question.
        This enables iterative information discovery retrieval.

        Example:
        Query: "What prize did the author of 'The Remains of the Day' win?"
        Returns: [
            "Who wrote 'The Remains of the Day'?",
            "What prize did [author name] win?"
        ]

        Args:
            query: The user's question

        Returns:
            List of information needs (sub-queries) to retrieve
        """
        prompt = f"""You are a question decomposition expert for a PERSONAL knowledge base.

CONTEXT:
- The knowledge base contains notes, experiences, learnings, and named entities
- You are NOT answering the question — you are identifying what to look up
- Generate ALL required sub-questions regardless of whether you think the information exists

# QUESTION
{query}

# TASK
Break the question into a numbered sequence of information needs.
Each need must be a specific, independently searchable question.

RULES (read carefully — all must be followed):

1. SINGLE-HOP DETECTION: If the question is self-contained and asks for one fact directly, return exactly 1 need that mirrors the question verbatim. Do NOT split it further. Only decompose if the question requires looking up a missing intermediate fact.

2. PRESERVE SPECIFICITY: If the question names specific people, roles, or titles, keep those exact names in your sub-questions.

3. DON'T RE-ASK WHAT YOU KNOW: If the question already states a fact (e.g. "the author of Pride and Prejudice"), don't ask about it — use a [placeholder] and move on.

4. PRESERVE NAMED WORKS: If the question explicitly names a specific film, book, song, show, or other work, that name is already known — keep it verbatim in your sub-questions. Do NOT ask "what film/book/work?" when the name is right there. Example: "Who starred in the film Example Film?" — the film name is given, so ask "Who starred in the film Example Film?", not "What film did [actor] appear in?".

5. USE PLACEHOLDERS, NOT BACK-REFERENCES: For entities discovered in previous steps, you MUST use a typed placeholder like [founder], [director], [author], [film]. NEVER write "that person", "the series", "the film", "that author", or any other definite back-reference.

6. COMPARISON QUESTIONS: For "Were X and Y both…?" or "Are X and Y in the same…?", ask about each entity separately — one sub-question per entity. STOP there. Do NOT add a comparison or verification sub-question — synthesis handles the comparison step.
     Example: "Are the Eiffel Tower and the Arc de Triomphe in the same arrondissement?"
     ✓ CORRECT — exactly 2 sub-questions:
         1. What arrondissement is the Eiffel Tower in?
         2. What arrondissement is the Arc de Triomphe in?
     ✗ WRONG — do NOT add: 3. Are they in the same arrondissement?

7. QUESTION TYPE: If the original asks "what city?", your sub-question must ask "what city?", not "is X in a city?".

8. COUNT REQUIRED HOPS: Count how many unknown facts the original question requires chaining through. Generate exactly that many sub-questions — one per hop.
   - "What [attribute] did the [person who did X] hold?" → ALWAYS 2 hops: (1) who did X, (2) what [attribute] did [person] hold.
   - CRITICAL: Do NOT stop after finding the person. The attribute question about that person is a MANDATORY second sub-question.
   - Even if you believe you know the answer to hop 2, you MUST still include it as a sub-question so the knowledge base can be checked.
     Example: "What government position was held by the actor who played Character X?" requires 2 hops:
         1. Who played Character X?
         2. What government position did [actor] hold?

9. KEEP IT MINIMAL: Use only as many sub-questions as there are required hops. Do not add sub-questions for facts already stated in the original question.

10. DEPENDENCIES FIRST: If question B requires information from question A, list A first.

OUTPUT FORMAT: Return ONLY the numbered list. No preamble, no explanation.

# EXAMPLES

Question: "What political office was held by the actor who starred in Example Film?"
1. Who starred in Example Film?
2. What political office did [actor] hold?

Question: "What university did the founder of Tesla attend?"
1. Who founded Tesla?
2. What university did [founder] attend?

Question: "Were Marie Curie and Albert Einstein both born in Europe?"
1. Where was Marie Curie born?
2. Where was Albert Einstein born?

Question: "The author who wrote 'Pride and Prejudice' lived in what English county?"
1. Who wrote 'Pride and Prejudice'?
2. What English county did [author] live in?

Question: "What young adult series is told in first person and has companion books about enslaved alien worlds?"
1. Which companion book(s) are about enslaved alien worlds in that young adult setting?
2. What young adult series are [companion book(s)] companion to?

Question: "What is the capital of France?"
1. What is the capital of France?

Now decompose the question above:
"""

        try:
            if self.is_gemini:
                model = settings.GEMINI_MODEL
                response = self.gemini_client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        thinking_config=types.ThinkingConfig(
                            thinking_budget=0,  # thinking_level="MINIMAL"
                        ),
                    ),
                )
                answer = response.text.strip()
            else:
                model = self._get_model_for_task("brain")
                extra_body = self._with_keep_alive()

                response = self.chat_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    extra_body=extra_body,
                )

                answer = response.choices[0].message.content.strip()

            logger.info(f"[LLM] identify_information_needs raw response:\n{answer}")

            # Parse numbered list
            needs = []
            for line in answer.split("\n"):
                line = line.strip()
                # Match patterns like "1. Who played..." or "1) Who played..."
                match = re.match(r"^\d+[\.\)]\s+(.+)$", line)
                if match:
                    needs.append(match.group(1).strip())

            # If no numbered format found, try simple questions (lines ending with ?)
            if not needs:
                needs = [
                    line.strip()
                    for line in answer.split("\n")
                    if line.strip() and line.strip().endswith("?")
                ]

            logger.info(
                f"[LLM] Identified {len(needs)} information needs for query: {query}"
            )
            for i, need in enumerate(needs, 1):
                logger.info(f"  {i}. {need}")

            return needs if needs else [query]  # Fallback to original query

        except Exception as e:
            logger.error(f"[LLM] Failed to identify information needs: {e}")
            return [query]  # Fallback to simple retrieval

    @staticmethod
    def _is_yes_no_question(question: str) -> bool:
        q = (question or "").strip().lower()
        if not q:
            return False
        starts = (
            "is ",
            "are ",
            "was ",
            "were ",
            "do ",
            "does ",
            "did ",
            "has ",
            "have ",
            "had ",
            "can ",
            "could ",
            "will ",
            "would ",
            "should ",
        )
        return q.startswith(starts)

    @staticmethod
    def _normalize_yes_no_answer(question: str, answer: str) -> str | None:
        """Return canonical YES/NO for boolean questions, otherwise passthrough.

        For yes/no questions (detected via _is_yes_no_question), the answer
        must resolve to YES or NO.  We accept a broad set of natural-language
        affirmatives/negatives so that wordy model responses like "Yes, that is
        correct" or "No, they did not" are correctly normalised rather than
        being rejected as None.

        Returns:
            "YES"   — question is boolean and answer is affirmative
            "NO"    — question is boolean and answer is negative
            answer  — question is not boolean (passthrough, unchanged)
            None    — question is boolean but answer is neither affirmative nor
                      negative (caller should treat as INSUFFICIENT)
        """
        if not LLMService._is_yes_no_question(question):
            return answer

        val = (answer or "").strip().lower()
        # Strip common trailing punctuation before matching
        val = val.rstrip(".,!?;:")

        _YES_PREFIXES = (
            "yes",
            "yeah",
            "yep",
            "yup",
            "correct",
            "that is correct",
            "that's correct",
            "affirmative",
            "indeed",
            "absolutely",
            "certainly",
            "definitely",
            "true",
        )
        _NO_PREFIXES = (
            "no",
            "nope",
            "nah",
            "incorrect",
            "not correct",
            "that is not correct",
            "that's not correct",
            "negative",
            "false",
            "never",
        )

        for prefix in _YES_PREFIXES:
            if (
                val == prefix
                or val.startswith(prefix + " ")
                or val.startswith(prefix + ",")
            ):
                return "YES"
        for prefix in _NO_PREFIXES:
            if (
                val == prefix
                or val.startswith(prefix + " ")
                or val.startswith(prefix + ",")
            ):
                return "NO"
        return None

    async def select_relevant_relationships(
        self,
        relationship_entries: list[dict],
        question: str,
    ) -> list[int]:
        """
        Given the 1-hop neighbourhood of already-relevant nodes, ask the LLM
        which connected nodes would provide additional evidence for the question.

        Each entry has: source (str), rel_type (str), neighbor (dict with
        name/summary/entity_type/label), context (str | None).

        Returns a deduplicated list of selected indices.
        """
        if not relationship_entries:
            return []

        lines = []
        for i, entry in enumerate(relationship_entries):
            source = entry["source"]
            neighbor = entry["neighbor"]
            neighbor_name = neighbor.get("name", "Unknown")
            neighbor_type = neighbor.get("entity_type") or neighbor.get("label", "")
            summary = neighbor.get("summary") or neighbor.get("description", "")
            context = entry.get("context") or ""
            type_clause = f" ({neighbor_type})" if neighbor_type else ""
            detail = summary or context
            detail_clause = f" — {detail}" if detail else ""
            # Prefer the stored natural language sentence; fall back to formatted rel_type.
            # Respect edge direction: for incoming edges the neighbor is the source.
            nl_sentence = entry.get("nl_sentence")
            if nl_sentence:
                lines.append(f"{i}: {nl_sentence}{detail_clause}")
            else:
                rel_type = entry["rel_type"].replace("_", " ").lower()
                edge_direction = entry.get("edge_direction", "outgoing")
                if edge_direction == "incoming":
                    display_source, display_target = neighbor_name, source
                else:
                    display_source, display_target = source, neighbor_name
                lines.append(
                    f'{i}: "{display_source}" {rel_type} "{display_target}"{type_clause}{detail_clause}'
                )

        rel_list = "\n".join(lines)
        prompt = (
            f"QUESTION: {question}\n\n"
            "The following relationships connect already-relevant nodes to nodes not yet "
            "in context.\n"
            "Select ONLY the relationships whose connected node would add useful evidence "
            "to answer the question. Be selective — skip generic, tangential, or redundant "
            "nodes. Temporal facts (birth dates, death dates) are NOT relevant to questions "
            "about nationality, occupation, or other non-temporal attributes.\n"
            "If none are useful, reply: NONE\n\n"
            "For each relevant relationship, reply with its number followed by a colon and a brief reason.\n"
            "One per line. Example:\n"
            "0: the connected node directly provides the missing date\n"
            "3: named as the author in context\n\n"
            f"RELATIONSHIPS:\n{rel_list}\n\n"
            "Relevant relationship numbers (number: reason):"
        )
        try:
            raw = await self.generate(prompt, temperature=0.0)
            logger.info(f"[LLM] select_relevant_relationships raw response:\n{raw}")
            if not raw or raw.strip().upper() == "NONE":
                return []
            indices: list[int] = []
            for line in raw.strip().splitlines():
                line = line.strip()
                if not line:
                    continue
                match = re.match(r"^(\d+)", line)
                if match:
                    idx = int(match.group(1))
                    if 0 <= idx < len(relationship_entries):
                        reason = line[match.end() :].lstrip(":, ").strip()
                        if reason:
                            logger.info(f"[LLM] relationship {idx} selected: {reason}")
                        indices.append(idx)
            seen: set[int] = set()
            return [idx for idx in indices if not (idx in seen or seen.add(idx))]  # type: ignore[func-returns-value]
        except Exception as e:
            logger.warning(f"[LLM] select_relevant_relationships failed: {e}")
            return []

    async def answer_sub_question(
        self,
        sub_question: str,
        docs: list[dict],
        keep: int = 12,
        skip_filter: bool = False,
    ) -> str | None:
        """
        Given retrieved docs for a sub-question, produce a concise answer.

        When skip_filter=True the docs are assumed to have been pre-filtered and
        graph-expanded by the caller; the internal select_relevant_docs pass is
        skipped to avoid a redundant LLM call.

        Returns (answer, follow_up_query) where:
          - answer is the extracted answer string if found
          - follow_up_query is a targeted search query describing what's still
            needed when the context is insufficient (so the caller can search
            for that specific information before drilling deeper)
          - (None, None) when there is no context at all
        """
        # Filter to the most relevant docs (unless pre-filtered externally)
        relevant = (
            docs if skip_filter else await self.select_relevant_docs(docs, sub_question)
        )
        if not relevant:
            return None, None

        # Build context from filtered docs — full text, no truncation
        context_parts = []
        for doc in relevant:
            node = doc.get("original_obj", {})
            # Use doc['text'] first — it is already assembled as natural language
            # prose ("Joseph is a person. ...") and must not be re-prefixed with
            # "name: " to avoid duplicating the entity name in context.
            text = (
                doc.get("text") or node.get("summary") or node.get("description") or ""
            ).strip()
            if text:
                context_parts.append(text)

        context = "\n\n".join(context_parts)
        if not context:
            return None, None

        prompt = (
            "Answer the question below using ONLY the context provided.\n\n"
            "Rules:\n"
            "- Extract the exact phrase from the context that answers the question — preserve all qualifying words (units, descriptors, suffixes, articles) that are part of the answer as it appears in the source\n"
            "- Do NOT paraphrase, generalise, or infer beyond what is stated\n"
            "- If the question asks for a name, title, or role: return that exact value from the context, including post-nominal letters (e.g. 'DSC'), first names, and corporate suffixes (e.g. 'Inc.')\n"
            "- If the question asks for one thing, give one thing. If it explicitly asks for a list, give the list\n"
            "- For either/or or comparison questions, return exactly one option named in the question when the context supports it\n"
            "- Do NOT answer with 'Neither' or 'Both' unless the question explicitly asks whether both or neither apply\n"
            "- For yes/no questions, return YES or NO only\n"
            "- If the context does not contain enough information to answer, reply in this exact format:\n"
            "  INSUFFICIENT\n"
            "  NEED: <5-10 word search query for the specific missing information>\n\n"
            f"QUESTION: {sub_question}\n\n"
            f"CONTEXT:\n{context}\n\n"
            "ANSWER:"
        )
        try:
            if self.is_gemini:
                response = self.gemini_client.models.generate_content(
                    model=settings.GEMINI_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.0,
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                    ),
                )
                raw = response.text.strip()
            else:
                raw = await self.generate(prompt, temperature=0.0)

            if not raw:
                return None, None
            if raw.split("\n")[0].strip().upper().startswith("INSUFFICIENT"):
                follow_up = None
                for line in raw.splitlines():
                    if line.strip().upper().startswith("NEED:"):
                        follow_up = line.split(":", 1)[1].strip()
                        break
                return None, follow_up
            answer = raw.split("\n")[0].strip()
            return answer, None
        except Exception as e:
            logger.warning(f"[LLM] answer_sub_question failed: {e}")
            return None, None

    async def final_synthesis_from_sub_answers(
        self,
        original_question: str,
        sub_answers: list[dict],
    ) -> tuple[str | None, str | None]:
        """
        Produce a final answer from structured sub-question/answer pairs.

        Two-pass approach:
          Pass 1 (reasoning): SYNTHESIS_RULES-guided, outputs a verbose answer
                              sentence — no extraction pressure.
          Pass 2 (extraction): dead-simple prompt copies the minimal phrase from
                               the verbose sentence; avoids rule conflicts with
                               formatting.

        Returns (answer, missing) where:
          - answer is the final answer string if the sub-answers are sufficient
          - missing is a one-phrase description of what's still needed (if not)
          - (None, None) on hard failure
        """
        if not sub_answers:
            return None, original_question

        # BRIDGE-ENTITY VALIDATION: reject clearly unresolved/placeholder hops only.
        # This intentionally avoids word-count/casing limits so long bridge entities
        # (e.g., multi-word titles) are allowed.
        def _is_unresolved_bridge_answer(answer: str) -> bool:
            a = (answer or "").strip()
            if not a:
                return False

            normalized = re.sub(r"\s+", " ", a)
            low = normalized.lower()

            non_answers = {
                "insufficient",
                "none",
                "n/a",
                "unknown",
                "not found",
                "not enough information",
                "no information",
            }
            if low in non_answers:
                return True

            # Narrative fallback responses often appear as sentence-like clauses
            # rather than the requested bridge entity/value.
            if "\n" in a:
                return True
            if any(p in normalized for p in ".!?;") and re.match(
                r"^(it|this|that|these|those|he|she|they|there)\s+(is|was|are|were|has|have|had)\b",
                low,
            ):
                return True

            return False

        qa_block = "\n".join(
            f"Q{i+1}: {sa['question']}\nA{i+1}: {sa['answer']}"
            for i, sa in enumerate(sub_answers)
        )

        # Detect the expected answer type from the question wording so we can
        # inject a concrete, prominent constraint into the prompt.  This stops
        # small models (e.g. gemma3:4b) from returning an intermediate bridge
        # entity instead of the requested attribute.
        _q_lower = original_question.lower().strip()
        _answer_type_constraint = ""
        _what_match = re.match(
            r"^what\s+([\w][^,?]*?)\s+(was|is|were|did|held|does|do|has|had|served|is there|are there)\b",
            _q_lower,
        )
        if _what_match:
            _attr = _what_match.group(1).strip()
            _answer_type_constraint = (
                f"\n⚠️  ANSWER TYPE CONSTRAINT: The question asks 'what {_attr}'. "
                f"The ANSWER must be a {_attr} — NOT a person's name, entity, or anything else. "
                f"If your answer would be a person's name, you are returning a bridge entity instead of the final answer. "
                f"Find the research finding that contains the actual {_attr} and use that.\n"
            )

        # Comparison direction: "who is older/younger/oldest/youngest"
        _older_match = re.search(
            r"\bwho\s+is\s+(the\s+)?(older|oldest|younger|youngest)\b", _q_lower
        )
        if _older_match:
            _dir = _older_match.group(2)
            _is_older = "older" in _dir or "oldest" in _dir
            _answer_type_constraint += (
                f"\n⚠️  COMPARISON CONSTRAINT: This question asks who is {_dir}. "
                f"{'Older = born in an EARLIER year (smaller year number).' if _is_older else 'Younger = born in a LATER year (larger year number).'} "
                f"Find each person's birth year in the findings above. "
                f"The person with the {'earlier' if _is_older else 'later'} birth year is {_dir}. "
                f"Output their FULL NAME as the ANSWER — NOT the birth year.\n"
            )

        # Both-entity YES/NO: "are X and Y both Z?"
        _both_match = re.search(r"\bare\s+.+?\s+and\s+.+?\s+both\b", _q_lower)
        if _both_match:
            _answer_type_constraint += (
                "\n⚠️  BOTH-ENTITY CONSTRAINT: Check EACH entity separately in the findings. "
                "Note: 'American', 'from the United States', or formed/based in a US state all indicate US nationality. "
                "If BOTH entities clearly have the required property → YES. "
                "If EITHER clearly lacks it → NO. "
                "If evidence is missing for either entity → INSUFFICIENT.\n"
            )

        # Mid-sentence "in what X?" — "is based in what New York city?"
        if not _answer_type_constraint:
            _in_what_match = re.search(r"\bin\s+what\s+([\w][^,?]*?)\??$", _q_lower)
            if _in_what_match:
                _loc_attr = _in_what_match.group(1).strip()
                _answer_type_constraint = (
                    f"\n⚠️  ANSWER TYPE CONSTRAINT: The question asks 'in what {_loc_attr}'. "
                    f"The ANSWER must be the MOST SPECIFIC location name (neighborhood, district, village) "
                    f"found in the sub-question findings — NOT a person's name or a broad city name. "
                    f"Prefer a sub-location (neighborhood, borough, district) over a plain city name when evidence supports it.\n"
                )

        # ── PASS 1: reasoning ────────────────────────────────────────────────
        # Ask for a bare answer phrase directly in ANSWER: — no full sentence.
        # SYNTHESIS_RULES guide correct reasoning (YES/NO, comparison winner,
        # shared-location parent, etc.). FORMAT RULES specify exact phrase shape.
        reasoning_prompt = (
            "You are answering a multi-hop question using research findings below.\n\n"
            "Use the research findings as your PRIMARY evidence. "
            "Do NOT use your general knowledge to fill in missing entity data — "
            "if any required entity's information is absent from the findings, "
            "output ANSWER: INSUFFICIENT.\n\n"
            f"RESEARCH FINDINGS:\n{qa_block}\n\n"
            f"Final question: {original_question}\n"
            f"{_answer_type_constraint}\n"
            f"{self._SYNTHESIS_RULES}\n\n"
            "Write 1–2 sentences of reasoning that trace through the findings to your conclusion, "
            "then on a new line write:\n"
            "ANSWER: <bare answer phrase — NOT a full sentence>\n\n"
            "FORMAT RULES for the ANSWER phrase:\n"
            "- YES/NO question → YES or NO only\n"
            "- Either/or or comparison question → answer with exactly one option named in the question, unless it is explicitly a yes/no question\n"
            "- Never answer 'Neither' or 'Both' unless the question explicitly asks about both or neither\n"
            "- Person's name → full name as it appears in the source, including all given names and post-nominal letters\n"
            "- Number → include any unit or qualifier the question implies\n"
            "- Date range → copy the exact phrase from the source, preserving any leading 'from'/'between' and the exact connective word ('to', 'until', 'through') — do not substitute or drop any of these words\n"
            "- Title or award → exact title, no leading organization abbreviation\n"
            "- Song, film, or book → exact primary title, no parenthetical alternate names\n"
            "- Location → copy the location exactly as it appears in the source, including city/region/country qualifiers (e.g. 'Springfield, Illinois', not just 'Springfield')\n\n"
            "- Government position, role, job, office, or title → the position/title name ONLY — NEVER include the name of the person who holds/held that position, even if that person was a bridge entity in the reasoning chain. Example: if the question asks 'what position did X hold?' and X was Secretary of State, answer 'Secretary of State' — NOT 'X, Secretary of State'\n\n"
            "If you truly cannot answer even with your general knowledge, write:\n"
            "ANSWER: INSUFFICIENT\n"
            "MISSING: <one key entity or concept absent from the findings>\n\n"
            "Reply:"
        )
        try:
            raw1 = self.reason(reasoning_prompt) or ""
            logger.debug(f"[LLM] final_synthesis_from_sub_answers raw1:\n{raw1}")
        except Exception as e:
            logger.warning(f"[LLM] final_synthesis_from_sub_answers pass1 failed: {e}")
            return None, None

        _non_answers = {"INSUFFICIENT", "NONE", "N/A", "UNKNOWN", "NOT FOUND"}
        verbose_answer: str | None = None
        missing: str | None = None
        for line in raw1.splitlines():
            line = line.strip()
            if line.lower().startswith("answer:"):
                val = line.split(":", 1)[1].strip()
                if val.upper() not in _non_answers:
                    verbose_answer = val
            elif line.lower().startswith("missing:"):
                missing = line.split(":", 1)[1].strip() or None

        if not verbose_answer:
            return None, missing

        normalized_verbose = self._normalize_yes_no_answer(
            original_question, verbose_answer
        )
        if normalized_verbose is None:
            if self._is_yes_no_question(original_question):
                yes_no_prompt = (
                    "Answer the yes/no question using ONLY the findings below.\n"
                    "Do NOT use your general knowledge to fill gaps.\n"
                    "If any required entity's data is absent or marked 'Not found', answer INSUFFICIENT.\n"
                    "Otherwise return ONLY YES or NO.\n\n"
                    f"QUESTION: {original_question}\n"
                    f"{_answer_type_constraint}\n"
                    f"FINDINGS:\n{qa_block}\n\n"
                    "ANSWER:"
                )
                try:
                    fallback_bool = self.reason(yes_no_prompt) or ""
                    fallback_bool = (
                        (fallback_bool or "").strip().splitlines()[0].strip()
                    )
                    logger.info(
                        f"[LLM] final_synthesis_from_sub_answers yes/no fallback raw: '{fallback_bool}'"
                    )
                    if fallback_bool.upper() == "INSUFFICIENT":
                        return None, missing
                    normalized_fallback = self._normalize_yes_no_answer(
                        original_question, fallback_bool
                    )
                    if normalized_fallback is not None:
                        return normalized_fallback, None
                except Exception as e:
                    logger.warning(
                        f"[LLM] final_synthesis_from_sub_answers yes/no fallback failed: {e}"
                    )
            logger.warning(
                f"[LLM] final_synthesis_from_sub_answers rejected non-boolean answer "
                f"for yes/no question: '{verbose_answer}'"
            )
            return None, missing
        verbose_answer = normalized_verbose

        # ── PASS 2: extraction ───────────────────────────────────────────────
        # Pass 1 now outputs a bare phrase directly. Pass 2 is a lightweight
        # cleanup for edge cases where the model still writes a full sentence.
        # Skip Pass 2 if Pass 1 already output a bare phrase (≤ 8 tokens, no verb signal)
        _words = verbose_answer.split()
        if len(_words) <= 8 and not any(
            w.lower()
            in {"is", "are", "was", "were", "has", "have", "had", "be", "been"}
            for w in _words
        ):
            return verbose_answer, None

        extraction_prompt = (
            "The question below was answered. Determine if the answer is already a bare phrase.\n\n"
            "A bare phrase is: a name, number, date, title, YES, NO, or a short noun phrase (≤ 8 words, no verb).\n\n"
            f"Question: {original_question}\n"
            f"Answer: {verbose_answer}\n\n"
            "- If the Answer IS already a bare phrase: copy it exactly, unchanged, with no additions or removals.\n"
            "- If the Answer IS NOT a bare phrase (it is a full sentence): extract only the core phrase that directly answers the question. Do not include surrounding explanation.\n\n"
            "Reply with the phrase only:"
        )
        try:
            bare = await self.generate(extraction_prompt, temperature=0.0)
            bare = (bare or "").strip()
            if bare and bare.upper() not in _non_answers:
                normalized_bare = self._normalize_yes_no_answer(original_question, bare)
                if normalized_bare is None:
                    logger.warning(
                        f"[LLM] final_synthesis_from_sub_answers rejected non-boolean "
                        f"pass2 answer for yes/no question: '{bare}'"
                    )
                    return None, missing
                bare = normalized_bare

                return bare, None
        except Exception as e:
            logger.warning(f"[LLM] final_synthesis_from_sub_answers pass2 failed: {e}")

        # Fallback: return the verbose answer from pass 1
        return verbose_answer, None

    async def select_relevant_docs_with_reasoning(
        self,
        docs: list[dict],
        question: str,
        original_query: str | None = None,
    ) -> tuple[list[dict], dict[int, str]]:
        """
        Same as select_relevant_docs but also returns per-doc reasoning strings.

        Returns (selected_docs, reasons) where reasons is a dict mapping the
        original doc index to the LLM's reason string.  Callers should log
        reasons to trace why each doc was kept or skipped.

        Falls back to (all docs, {}) on any failure so the pipeline is never
        blocked by a bad LLM response.
        """
        if not docs:
            return [], {}

        lines = []
        for i, doc in enumerate(docs):
            node = doc.get("original_obj", {})
            name = node.get("name") or doc.get("name", "?")
            summary = (
                doc.get("text") or node.get("summary") or node.get("description") or ""
            ).strip()
            snippet = summary if summary else "(no text)"
            lines.append(f"{i}: [{name}] {snippet}")

        doc_list = "\n".join(lines)
        query_header = (
            f"ORIGINAL QUESTION (full context): {original_query}\n"
            f"CURRENT SUB-QUESTION: {question}\n\n"
            if original_query and original_query != question
            else f"QUESTION: {question}\n\n"
        )

        prompt = (
            f"{query_header}"
            f"Below are {len(docs)} retrieved passages numbered 0–{len(docs) - 1}.\n"
            "Be selective — only include passages with direct, useful evidence. "
            "Exclude passages that only mention a topic tangentially or share a keyword without adding relevant facts.\n"
            "If no passages are relevant, return: NONE\n\n"
            "For each relevant passage, reply with its number followed by a colon and a brief reason (1 sentence).\n"
            "One per line. Example:\n"
            "0: directly states the founding year\n"
            "3: names the person who led the project\n\n"
            f"PASSAGES:\n{doc_list}\n\n"
            "Relevant passages (number: reason):"
        )

        try:
            raw = await self.generate(prompt, temperature=0.0)
            logger.info(
                f"[LLM] select_relevant_docs_with_reasoning raw response:\n{raw}"
            )
            if not raw or raw.strip().upper() == "NONE":
                return [], {}
            indices: list[int] = []
            reasons: dict[int, str] = {}
            for line in raw.strip().splitlines():
                line = line.strip()
                if not line:
                    continue
                match = re.match(r"^(\d+)", line)
                if match:
                    idx = int(match.group(1))
                    if 0 <= idx < len(docs):
                        reason = line[match.end() :].lstrip(":, ").strip()
                        # Drop selections whose own stated reason indicates the
                        # passage has no relevant information (contradictory selection).
                        _reason_lower = reason.lower()
                        _neg_phrases = (
                            "no information",
                            "no relevant",
                            "does not contain",
                            "does not provide",
                            "does not mention",
                            "not relevant",
                            "insufficient",
                            "unrelated",
                            "no direct",
                        )
                        if any(p in _reason_lower for p in _neg_phrases):
                            logger.debug(
                                f"[LLM] Dropped contradictory selection {idx}: reason='{reason}'"
                            )
                            continue
                        reasons[idx] = reason
                        indices.append(idx)
            seen: set[int] = set()
            unique_indices = [idx for idx in indices if not (idx in seen or seen.add(idx))]  # type: ignore[func-returns-value]
            if unique_indices:
                return [docs[i] for i in unique_indices], {
                    i: reasons.get(i, "") for i in unique_indices
                }
        except Exception as e:
            logger.warning(f"[LLM] select_relevant_docs_with_reasoning failed: {e}")

        return docs, {}  # fail-open

    async def answer_sub_question_dual(
        self,
        sub_question: str,
        docs: list[dict],
    ) -> tuple[str | None, str | None, str]:
        """
        Answer a sub-question with two granularities + visible reasoning.

        Returns (full_answer, direct_answer, reasoning) where:
          - full_answer: answer covering the topic with all relevant context
          - direct_answer: the single key fact / shortest complete answer
          - reasoning: the LLM's chain-of-thought explaining its answer

        Returns (None, None, "") if context is insufficient.
        """
        if not docs:
            return None, None, "No context documents provided."

        # Separate primary retrieved docs from graph-expansion neighbours.
        # Expansion docs carry _origin_name and _link_sentence so they can be
        # grouped directly under the primary doc they extend, giving the LLM
        # a single coherent passage rather than isolated text blocks.
        primary_docs = [d for d in docs if d.get("type") != "graph_expansion"]
        expansion_docs = [d for d in docs if d.get("type") == "graph_expansion"]

        expansions_by_origin: dict[str, list[dict]] = {}
        for exp in expansion_docs:
            origin = exp.get("_origin_name", "")
            if origin:
                expansions_by_origin.setdefault(origin, []).append(exp)

        context_parts = []
        primary_names: set[str] = set()
        for doc in primary_docs:
            node = doc.get("original_obj", {})
            name = node.get("name", "")
            text = (
                doc.get("text") or node.get("summary") or node.get("description") or ""
            ).strip()
            if not text:
                continue
            block = text
            for exp in expansions_by_origin.get(name, []):
                link = exp.get("_link_sentence", "")
                exp_node = exp.get("original_obj", {})
                exp_text = (
                    exp.get("text")
                    or exp_node.get("summary")
                    or exp_node.get("description")
                    or ""
                ).strip()
                if link:
                    block += f"\n{link}"
                if exp_text:
                    block += f"\n{exp_text}"
            context_parts.append(block)
            primary_names.add(name)

        # Expansion docs whose origin isn't among the primary docs get appended as-is.
        for exp in expansion_docs:
            if exp.get("_origin_name", "") not in primary_names:
                exp_node = exp.get("original_obj", {})
                exp_text = (
                    exp.get("text")
                    or exp_node.get("summary")
                    or exp_node.get("description")
                    or ""
                ).strip()
                if exp_text:
                    context_parts.append(exp_text)

        context = "\n\n".join(context_parts)
        if not context:
            return None, None, "All context documents had empty text."

        # Build an answer-type hint for location questions so the small LLM
        # doesn't confuse an intermediate entity (director name) with the
        # requested attribute (city / neighborhood).
        _q_lower = sub_question.lower().strip()
        _loc_type_match = re.search(
            r"\bwhat\s+(city|neighborhood|borough|area|district|state|country|place"
            r"|region|village|town|street|avenue|block|quarter)\b",
            _q_lower,
        )
        _type_hint = ""
        if _loc_type_match:
            _loc_type = _loc_type_match.group(1)
            _type_hint = (
                f"\n⚠️  ANSWER TYPE: The question asks for a {_loc_type}. "
                f"DIRECT_ANSWER must be a {_loc_type} name — NOT a person's name, "
                f"event, or any other entity type. "
                f"If the context does not contain a {_loc_type}, write INSUFFICIENT.\n"
            )

        # Both-entity YES/NO: "are X and Y both Z?"
        _both_yn_match = re.search(r"\bare\s+.+?\s+and\s+.+?\s+both\b", _q_lower)
        if _both_yn_match and not _type_hint:
            _type_hint = (
                "\n⚠️  YES/NO CONSTRAINT: This question asks whether BOTH entities share a property. "
                "Check each entity in the context separately. "
                "Note: 'American', 'from the United States', or based/formed in a US state all mean US nationality. "
                "If BOTH entities clearly have the property → DIRECT_ANSWER: YES. "
                "If EITHER entity lacks it → DIRECT_ANSWER: NO. "
                "Do NOT output a nationality label — output only YES or NO.\n"
            )

        prompt = (
            "Answer the question below using ONLY the context provided.\n\n"
            f"QUESTION: {sub_question}\n\n"
            f"CONTEXT:\n{context}\n"
            f"{_type_hint}\n"
            "Reply in this EXACT format (all three sections required):\n\n"
            "REASONING: <sentences tracing which part of the context answers the question and why>\n\n"
            "FULL_ANSWER: <cover the topic with all relevant context from the passage — not just the bare fact, include all details that may be needed to answer the original question>\n\n"
            "DIRECT_ANSWER: <the single key fact that directly answers the question — "
            "must be the SPECIFIC ATTRIBUTE asked for (e.g. if asked about nationality, answer 'American' not the person's name; "
            "if asked about a date, answer the date; if asked yes/no, answer YES or NO; "
            "if asked about a city/neighborhood/location, answer the location name not a person's name) — "
            "exact value from context, no elaboration>\n\n"
            "If the context does not contain enough information to answer:\n"
            "REASONING: <explain what is missing>\n"
            "FULL_ANSWER: INSUFFICIENT\n"
            "DIRECT_ANSWER: INSUFFICIENT\n"
        )
        try:
            if self.is_gemini:
                response = self.gemini_client.models.generate_content(
                    model=settings.GEMINI_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.0,
                        thinking_config=types.ThinkingConfig(thinking_budget=512),
                    ),
                )
                raw = response.text.strip()
            else:
                raw = await self.generate(prompt, temperature=0.0)

            logger.info(f"[LLM] answer_sub_question_dual raw response:\n{raw}")
            if not raw:
                return None, None, "LLM returned empty response."

            reasoning = ""
            full_answer = None
            direct_answer = None

            # Parse the structured response robustly.
            # Problem: FULL_ANSWER and REASONING may span multiple lines when the
            # model wraps long text.  A naive line-by-line loop truncates to the
            # first line.  Instead we split on section headers and take everything
            # between headers as the section's value.
            _SECTION_RE = re.compile(
                r"^(REASONING|FULL_ANSWER|DIRECT_ANSWER)\s*:",
                re.IGNORECASE | re.MULTILINE,
            )
            sections: dict[str, str] = {}
            parts = _SECTION_RE.split(raw)
            # parts layout after split: [pre, key1, val1, key2, val2, ...]
            it = iter(parts[1:])  # skip pre-match text
            for key_raw, val_raw in zip(it, it):
                sections[key_raw.upper()] = val_raw.strip()

            if "REASONING" in sections:
                reasoning = sections["REASONING"]
            if "FULL_ANSWER" in sections:
                val = sections["FULL_ANSWER"]
                if val.upper() != "INSUFFICIENT":
                    full_answer = val
            if "DIRECT_ANSWER" in sections:
                val = sections["DIRECT_ANSWER"]
                if val.upper() != "INSUFFICIENT":
                    direct_answer = val

            return full_answer, direct_answer, reasoning

        except Exception as e:
            logger.warning(f"[LLM] answer_sub_question_dual failed: {e}")
            return None, None, f"Exception: {e}"

    async def final_synthesis_from_sub_results(
        self,
        original_question: str,
        sub_results: list[dict],
        query_attr: str | None = None,
    ) -> str | None:
        """
        Synthesize a final answer from structured sub-question results.

        Each entry in sub_results has:
          - question: original sub-question template
          - resolved_question: with placeholders filled
          - full_answer: 2-3 sentence contextual answer
          - direct_answer: bare key fact

        Uses both full_answer (for reasoning) and direct_answer (for precision).
        Returns the final bare answer phrase, or None if insufficient.

        Args:
            query_attr: Optional pre-computed question attribute (e.g. "role",
                "date") from a prior ``analyze_query`` call.  When provided the
                function skips the redundant ``analyze_query`` call.
        """
        if not sub_results:
            return None

        # GUARD: Extract question attributes for answer-type validation.
        # Accept a pre-computed value to avoid the redundant analyze_query call
        # that was previously made here even when hybrid_search already did it.
        if query_attr is None:
            try:
                qa = self.analyze_query(original_question)
                query_attr = qa.get("question_attribute", "").lower()
            except Exception:
                pass
        else:
            query_attr = (query_attr or "").lower()

        qa_block_lines = []
        for i, sr in enumerate(sub_results, 1):
            q = sr.get("resolved_question") or sr.get("question", "")
            reasoning = sr.get("answer_reasoning") or ""
            full = sr.get("full_answer") or "Not found"
            block = f"Sub-question {i}: {q}\n"
            if reasoning:
                block += f"  Reasoning: {reasoning}\n"
            block += f"  Answer: {full}"
            qa_block_lines.append(block)
        qa_block = "\n\n".join(qa_block_lines)

        # ── Extra per-question constraints (Q9 / Q10 style fixes) ──────────
        _q_lower = original_question.lower().strip()
        _extra_constraints = ""

        # Comparison direction: "who is older/younger/oldest/youngest"
        _older_match = re.search(
            r"\bwho\s+is\s+(the\s+)?(older|oldest|younger|youngest)\b", _q_lower
        )
        if _older_match:
            _dir = _older_match.group(2)
            _is_older = "older" in _dir or "oldest" in _dir
            _extra_constraints += (
                f"\n⚠️  COMPARISON CONSTRAINT: This question asks who is {_dir}. "
                f"{'Older = born in an EARLIER year (smaller year number).' if _is_older else 'Younger = born in a LATER year (larger year number).'} "
                f"Find each person's birth year in the Full context above. "
                f"The person with the {'earlier' if _is_older else 'later'} birth year is {_dir}. "
                f"Output their FULL NAME as the ANSWER — NOT the birth year.\n"
            )

        # Both-entity YES/NO: "are X and Y both Z?"
        _both_match = re.search(r"\bare\s+.+?\s+and\s+.+?\s+both\b", _q_lower)
        if _both_match:
            _extra_constraints += (
                "\n⚠️  BOTH-ENTITY CONSTRAINT: Check EACH entity separately in the Full context. "
                "Note: 'American', 'from the United States', or formed/based in a US state all indicate US nationality. "
                "If BOTH entities clearly have the required property → YES. "
                "If EITHER clearly lacks it → NO. "
                "If evidence is missing for either entity → INSUFFICIENT.\n"
            )

        # Mid-sentence "in what X?" — "is based in what New York city?"
        _in_what_match = re.search(r"\bin\s+what\s+([\w][^,?]*?)\??$", _q_lower)
        if _in_what_match and not _extra_constraints:
            _loc_attr = _in_what_match.group(1).strip()
            _extra_constraints += (
                f"\n⚠️  ANSWER TYPE CONSTRAINT: The question asks 'in what {_loc_attr}'. "
                f"The ANSWER must be the MOST SPECIFIC location name (neighborhood, district, village) "
                f"found in the sub-question findings — NOT a person's name or a broad city name. "
                f"Prefer a sub-location (neighborhood, borough, district) over a plain city name when evidence supports it.\n"
            )

        reasoning_prompt = (
            "You are answering a multi-hop question using structured research findings.\n"
            "Use the retrieved sub-question findings as your primary evidence. "
            "If some sub-question findings are marked 'Not found', reason from what was "
            "found combined with your knowledge to attempt a complete answer.\n\n"
            f"RESEARCH FINDINGS:\n{qa_block}\n\n"
            f"Original question: {original_question}\n"
            f"{_extra_constraints}\n"
            f"{self._SYNTHESIS_RULES}\n\n"
            "Write 1–2 sentences of reasoning tracing through the findings to your conclusion, "
            "then on a new line write:\n"
            "ANSWER: <bare answer phrase — NOT a full sentence>\n\n"
            "FORMAT RULES for the ANSWER phrase:\n"
            "- YES/NO question → YES or NO only\n"
            "- Either/or or comparison question → answer with exactly one option named in the question\n"
            "- Never answer 'Neither' or 'Both' unless the question explicitly asks about both or neither\n"
            "- Person's name → full name as it appears in the source\n"
            "- Number → include any unit or qualifier the question implies\n"
            "- Date range → copy exact phrase from source, preserving connective words\n"
            "- Title or award → exact title\n"
            "- Government position, role, job, office, or title → return ONLY the role/title phrase. NEVER include the person's name or leading apposition. Example: right='Chief of Protocol', wrong='Alex Doe, Chief of Protocol'.\n"
            "- Location → copy location exactly as it appears in the source; strip any leading subject — wrong: 'X is based in City', right: 'City'\n"
            "- The ANSWER must contain ONLY the specific fact asked for — never include the subject or framing. Wrong: 'John Smith was born in Paris'. Right: 'Paris, France'.\n\n"
            "If findings are insufficient:\n"
            "ANSWER: INSUFFICIENT\n\n"
            "Reply:"
        )
        try:
            raw = self.reason(reasoning_prompt) or ""
            logger.info(f"[LLM] final_synthesis_from_sub_results raw response:\n{raw}")
        except Exception as e:
            logger.warning(f"[LLM] final_synthesis_from_sub_results failed: {e}")
            return None

        _non_answers = {"INSUFFICIENT", "NONE", "N/A", "UNKNOWN", "NOT FOUND"}
        for line in raw.splitlines():
            line = line.strip()
            if line.lower().startswith("answer:"):
                val = line.split(":", 1)[1].strip()
                if val.upper() not in _non_answers:
                    normalized = self._normalize_yes_no_answer(original_question, val)
                    if normalized is None:
                        if self._is_yes_no_question(original_question):
                            yes_no_prompt = (
                                "Answer the yes/no question using ONLY the findings below.\n"
                                "Do NOT use your general knowledge to fill gaps.\n"
                                "If any required entity's data is absent or marked 'Not found', answer INSUFFICIENT.\n"
                                "Otherwise return ONLY YES or NO.\n\n"
                                f"QUESTION: {original_question}\n"
                                f"{_extra_constraints}\n"
                                f"FINDINGS:\n{qa_block}\n\n"
                                "ANSWER:"
                            )
                            try:
                                fallback_bool = self.reason(yes_no_prompt) or ""
                                fallback_bool = (
                                    fallback_bool.strip().splitlines()[0].strip()
                                )
                                logger.info(
                                    "[LLM] final_synthesis_from_sub_results yes/no "
                                    f"fallback raw: '{fallback_bool}'"
                                )
                                if fallback_bool.upper() == "INSUFFICIENT":
                                    return None
                                normalized_fallback = self._normalize_yes_no_answer(
                                    original_question, fallback_bool
                                )
                                if normalized_fallback is not None:
                                    return normalized_fallback
                            except Exception as e:
                                logger.warning(
                                    "[LLM] final_synthesis_from_sub_results yes/no "
                                    f"fallback failed: {e}"
                                )
                        logger.warning(
                            f"[LLM] final_synthesis_from_sub_results rejected non-boolean "
                            f"answer for yes/no question: '{val}'"
                        )
                        return None
                    val = normalized

                    # ── PASS 2: extraction ──────────────────────────────────
                    # Pass 1 asks for a bare phrase but models sometimes emit a
                    # full sentence.  If the answer is already compact (≤8 tokens,
                    # no copula verb) skip pass 2 to avoid an extra LLM call.
                    _words = val.split()
                    _has_copula = any(
                        w.lower()
                        in {
                            "is",
                            "are",
                            "was",
                            "were",
                            "has",
                            "have",
                            "had",
                            "be",
                            "been",
                        }
                        for w in _words
                    )
                    if len(_words) > 8 or _has_copula:
                        extraction_prompt = (
                            "The question below was answered. Determine if the answer is already a bare phrase.\n\n"
                            "A bare phrase is: a name, number, date, title, YES, NO, or a short noun phrase (≤ 8 words, no verb).\n\n"
                            f"Question: {original_question}\n"
                            f"Answer: {val}\n\n"
                            "- If the Answer IS already a bare phrase: copy it exactly, unchanged.\n"
                            "- If the Answer IS NOT a bare phrase (it is a full sentence): extract only the core phrase that directly answers the question.\n\n"
                            "Reply with the phrase only:"
                        )
                        try:
                            bare = await self.generate(
                                extraction_prompt, temperature=0.0
                            )
                            bare = (bare or "").strip()
                            if bare and bare.upper() not in _non_answers:
                                normalized_bare = self._normalize_yes_no_answer(
                                    original_question, bare
                                )
                                if normalized_bare is None:
                                    logger.warning(
                                        f"[LLM] final_synthesis_from_sub_results rejected "
                                        f"non-boolean pass2 answer: '{bare}'"
                                    )
                                    return None
                                bare = normalized_bare
                                logger.info(
                                    f"[LLM] final_synthesis_from_sub_results pass2 extracted: '{bare}'"
                                )
                                return bare
                        except Exception as _p2e:
                            logger.warning(
                                f"[LLM] final_synthesis_from_sub_results pass2 failed: {_p2e}"
                            )
                    return val
        return None

    async def iterative_step(
        self,
        original_question: str,
        accumulated_steps: list[dict],
        search_query: str | None,
        docs: list[dict],
    ) -> dict:
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
                entry += f"\n  Answer: {fa or 'Not found'}"
                lines.append(entry)
            prior_block = "PRIOR FINDINGS:\n" + "\n\n".join(lines) + "\n\n"

        # ── Build current search block ────────────────────────────────────────
        current_block = ""
        if search_query and docs:
            context_lines = []
            for doc in docs:
                node = doc.get("original_obj") or {}
                name = node.get("name") or doc.get("name", "?")
                text = (
                    doc.get("text")
                    or node.get("summary")
                    or node.get("description")
                    or ""
                ).strip()
                if text:
                    context_lines.append(f"[{name}] {text}")
            context = (
                "\n\n".join(context_lines) if context_lines else "(no text found)"
            )
            current_block = (
                f"CURRENT SEARCH: '{search_query}'\n\n"
                f"RETRIEVED DOCUMENTS:\n{context}\n\n"
            )

        # ── Build task instructions ───────────────────────────────────────────
        if search_query and docs:
            task_instructions = (
                "First assess the current search results:\n"
                "REASONING: <1-2 sentences tracing how these documents relate to the "
                "question and prior findings>\n"
                "FULL_ANSWER: <1-2 sentence contextual answer based on current "
                "documents, or 'Not found' if irrelevant>\n\n"
                "Then decide:\n"
                "- If you now have enough information to answer the original question "
                "with confidence, output:\n"
                "  CAN_ANSWER: <bare terse answer phrase>\n"
                "- If you need more information, output:\n"
                "  NEXT_QUERY: <one specific search query to look up next>\n\n"
                f"{self._SYNTHESIS_RULES}\n\n"
                "FORMAT RULES for CAN_ANSWER:\n"
                "- YES/NO question → YES or NO only\n"
                "- Either/or or comparison → exactly one option from the question\n"
                "- Never answer 'Neither' or 'Both' unless the question asks for it\n"
                "- Person's name → full name as it appears in the source\n"
                "- Number → include any unit or qualifier the question implies\n"
                "- Date range → copy exact phrase from source, preserving connectives\n"
                "- Title or award → exact title\n"
                "- Government position, role, job, office → return ONLY the role/title "
                "phrase, NEVER the person's name\n"
                "- Location → copy exactly as in source; strip any leading subject\n"
                "- CAN_ANSWER must contain ONLY the specific fact asked for\n"
                "- If insufficient information: output NEXT_QUERY instead\n"
            )
        else:
            task_instructions = (
                "Output the first search query needed to start answering this "
                "question:\n"
                "NEXT_QUERY: <one specific search query>\n"
            )

        prompt = (
            "You are a research assistant solving a multi-hop question step by "
            "step.\n\n"
            f"ORIGINAL QUESTION: {original_question}\n\n"
            f"{prior_block}"
            f"{current_block}"
            f"{task_instructions}"
            "\nReply:"
        )

        try:
            raw = self.reason(prompt) or ""
            logger.info(f"[LLM] iterative_step raw response:\n{raw}")
        except Exception as e:
            logger.warning(f"[LLM] iterative_step failed: {e}")
            return {
                "reasoning": "",
                "full_answer": "",
                "can_answer": False,
                "final_answer": None,
                "next_query": None,
            }

        # ── Parse response ────────────────────────────────────────────────────
        reasoning = ""
        full_answer = ""
        can_answer = False
        final_answer: str | None = None
        next_query: str | None = None

        for line in raw.splitlines():
            ls = line.strip()
            ll = ls.lower()
            if ll.startswith("reasoning:"):
                reasoning = ls[len("reasoning:"):].strip()
            elif ll.startswith("full_answer:"):
                full_answer = ls[len("full_answer:"):].strip()
            elif ll.startswith("can_answer:"):
                val = ls[len("can_answer:"):].strip()
                if val.upper() in _non_answers:
                    logger.info(
                        "[LLM] iterative_step CAN_ANSWER=INSUFFICIENT → need next query"
                    )
                else:
                    can_answer = True
                    final_answer = val
            elif ll.startswith("next_query:"):
                next_query = ls[len("next_query:"):].strip()

        # ── Post-process CAN_ANSWER ───────────────────────────────────────────
        if can_answer and final_answer:
            normalized = self._normalize_yes_no_answer(original_question, final_answer)
            if normalized is None and self._is_yes_no_question(original_question):
                logger.warning(
                    f"[LLM] iterative_step rejected non-boolean for yes/no Q: "
                    f"'{final_answer}'"
                )
                can_answer = False
                final_answer = None
            elif normalized is not None:
                final_answer = normalized

            # Pass 2: extract bare phrase if the answer is a full sentence
            if final_answer:
                _words = final_answer.split()
                _has_copula = any(
                    w.lower()
                    in {"is", "are", "was", "were", "has", "have", "had", "be", "been"}
                    for w in _words
                )
                if len(_words) > 8 or _has_copula:
                    extraction_prompt = (
                        "The question below was answered. Determine if the answer is "
                        "already a bare phrase.\n\n"
                        "A bare phrase is: a name, number, date, title, YES, NO, or a "
                        "short noun phrase (≤ 8 words, no verb).\n\n"
                        f"Question: {original_question}\n"
                        f"Answer: {final_answer}\n\n"
                        "- If the Answer IS already a bare phrase: copy it exactly, "
                        "unchanged.\n"
                        "- If the Answer IS NOT a bare phrase (it is a full sentence): "
                        "extract only the core phrase that directly answers the "
                        "question.\n\n"
                        "Reply with the phrase only:"
                    )
                    try:
                        bare = await self.generate(extraction_prompt, temperature=0.0)
                        bare = (bare or "").strip()
                        if bare and bare.upper() not in _non_answers:
                            normalized_bare = self._normalize_yes_no_answer(
                                original_question, bare
                            )
                            if (
                                normalized_bare is None
                                and self._is_yes_no_question(original_question)
                            ):
                                logger.warning(
                                    f"[LLM] iterative_step pass2 rejected non-boolean: "
                                    f"'{bare}'"
                                )
                                can_answer = False
                                final_answer = None
                            else:
                                final_answer = (
                                    normalized_bare
                                    if normalized_bare is not None
                                    else bare
                                )
                                logger.info(
                                    f"[LLM] iterative_step pass2 extracted: "
                                    f"'{final_answer}'"
                                )
                    except Exception as _p2e:
                        logger.warning(
                            f"[LLM] iterative_step pass2 failed: {_p2e}"
                        )

        return {
            "reasoning": reasoning,
            "full_answer": full_answer,
            "can_answer": can_answer,
            "final_answer": final_answer,
            "next_query": next_query,
        }

    async def select_relevant_docs(
        self,
        docs: list[dict],
        question: str,
    ) -> list[dict]:
        """
        Batch context filter — single LLM call, O(1) per retrieval pass.

        Shows all accumulated docs as a numbered list and asks the LLM to
        select ALL passages it considers relevant — no fixed count. The LLM
        picks 2 when only 2 are useful, or more for multi-hop questions that
        need multiple supporting passages.

        Falls back to returning all docs unmodified on any failure so the
        pipeline is never blocked by a bad LLM response.
        """
        lines = []
        for i, doc in enumerate(docs):
            node = doc.get("original_obj", {})
            name = node.get("name") or doc.get("name", "?")
            # Use doc['text'] first — it includes relationship context ("and is
            # connected to ...") that may contain the key fact being filtered for.
            summary = (
                doc.get("text") or node.get("summary") or node.get("description") or ""
            ).strip()
            snippet = summary if summary else "(no text)"
            rerank_score = doc.get("rerank_score")
            score_tag = (
                f" [relevance={rerank_score:.3f}]" if rerank_score is not None else ""
            )
            lines.append(f"{i}: [{name}]{score_tag} {snippet}")

        doc_list = "\n".join(lines)
        prompt = (
            f"QUESTION: {question}\n\n"
            f"Below are {len(docs)} retrieved passages numbered 0–{len(docs) - 1}.\n"
            "Each passage has a [relevance=N] score (0–1) from a semantic search model. "
            "Higher scores mean the passage is more semantically relevant to the question.\n"
            "Be selective — only include passages with direct, useful evidence. "
            "Exclude passages that only mention a topic tangentially or share a keyword without adding relevant facts.\n"
            "If no passages are relevant, return: NONE\n\n"
            "For each relevant passage, reply with its number followed by a colon and a brief reason.\n"
            "One per line. Example:\n"
            "0: directly states the founding year\n"
            "3: names the person who led the project\n\n"
            f"PASSAGES:\n{doc_list}\n\n"
            "Relevant passages (number: reason):"
        )

        try:
            raw = await self.generate(prompt, temperature=0.0)
            if not raw or raw.strip().upper() == "NONE":
                return []
            indices = []
            for line in raw.strip().splitlines():
                line = line.strip()
                if not line:
                    continue
                # Accept "0: reason" or bare "0" or "0, 3" formats
                match = re.match(r"^(\d+)", line)
                if match:
                    idx = int(match.group(1))
                    if 0 <= idx < len(docs):
                        reason = line[match.end() :].lstrip(":, ").strip()
                        if reason:
                            logger.debug(f"[LLM] passage {idx} selected: {reason}")
                        indices.append(idx)
            # Deduplicate while preserving order
            seen: set[int] = set()
            unique_indices = [
                idx for idx in indices if not (idx in seen or seen.add(idx))  # type: ignore[func-returns-value]
            ]
            if unique_indices:
                logger.debug(
                    f"[LLM] select_relevant_docs: selected {unique_indices} "
                    f"from {len(docs)} docs"
                )
                return [docs[i] for i in unique_indices]
        except Exception as e:
            logger.warning(f"[LLM] select_relevant_docs failed: {e}")

        return docs  # fail-open

    async def generate_redirect_query(
        self,
        docs: list[dict],
        question: str,
    ) -> str | None:
        """
        When select_relevant_docs returns [], generate a new search query that
        targets the specific missing information rather than retrying the same query.

        Presents retrieved node names + snippets to the LLM and asks it to craft
        a focused 5-10 word query for the fact that is still missing.
        """
        lines = []
        for doc in docs:
            node = doc.get("original_obj", {})
            name = node.get("name") or doc.get("name", "?")
            text = (doc.get("text") or node.get("summary") or "").strip()
            lines.append(f"- [{name}]: {text}")

        doc_list = "\n".join(lines) if lines else "(no documents retrieved)"
        prompt = (
            f'You were searching for: "{question}"\n\n'
            f"The following passages were retrieved but NONE contained directly "
            f"relevant information:\n{doc_list}\n\n"
            f"Generate a short 5-10 word search query that would find the SPECIFIC "
            f"missing information needed to answer the question.\n"
            f"Focus on the key entity or fact that is absent from the passages above.\n"
            f"Reply with ONLY the search query — no explanation, no quotes."
        )
        try:
            raw = await self.generate(prompt, temperature=0.1)
            query = raw.strip().strip('"').strip("'")
            if query and 2 <= len(query.split()) <= 15:
                return query
        except Exception as e:
            logger.warning(f"[LLM] generate_redirect_query failed: {e}")
        return None

    async def summarize_search_failure(
        self,
        question: str,
        all_docs: list[dict],
    ) -> str:
        """
        After all search attempts are exhausted, produce a single informative
        sentence describing what was found and what is still missing.

        This is used as the sub-answer for synthesis so the final answer can
        acknowledge the gap rather than silently returning None.
        """
        lines = []
        for doc in all_docs:
            node = doc.get("original_obj", {})
            name = node.get("name") or doc.get("name", "?")
            text = (doc.get("text") or node.get("summary") or "").strip()
            lines.append(f"- [{name}]: {text}")

        context = "\n".join(lines) if lines else "No relevant documents were found."
        prompt = (
            f"Question: {question}\n\n"
            f"After multiple searches the following information was found but "
            f"the question could not be answered:\n{context}\n\n"
            f"In ONE sentence, describe what was found and what information is "
            f"still missing to answer the question.\n"
            f"Reply with ONLY the one sentence."
        )
        try:
            raw = await self.generate(prompt, temperature=0.0)
            sentence = raw.strip()
            if sentence:
                return sentence
        except Exception as e:
            logger.warning(f"[LLM] summarize_search_failure failed: {e}")
        return f"Could not find sufficient information to answer: {question}"

    async def generate_embedding_instruction(self, query: str) -> str:
        """
        Generate a query-specific instruction for Qwen3-Embedding.

        Creates a tailored instruction that tells the embedding model what kind of
        information to retrieve for this specific query.

        Example:
        Query: "What movies did Tom Hanks star in?"
        Returns: "Instruct: Retrieve filmography and acting credits for the person mentioned\nQuery: "

        Args:
            query: The user's search query

        Returns:
            Custom instruction prefix for this query
        """
        prompt = f"""Generate a concise instruction for an embedding model to retrieve relevant information.

The instruction should tell the model what TYPE of information to look for in a personal knowledge base.

# USER QUERY
{query}

# TASK
Create a single-sentence instruction (max 20 words) that describes what information the embedding should retrieve.

FOCUS ON:
- The semantic category (biography, filmography, technical docs, events, etc.)
- The relationship type (worked on, starred in, founded, located in, etc.)
- Keep it generic and semantic, not query-specific

# FORMAT
Return ONLY the instruction, starting with "Retrieve"

# EXAMPLES

Query: "What films did Akira Kurosawa direct?"
Instruction: Retrieve filmography and directing credits for the person mentioned

Query: "Where did Marie Curie conduct her research?"
Instruction: Retrieve biographical information about research locations and institutions

Query: "What frameworks does the frontend use?"
Instruction: Retrieve technical documentation about frontend technologies and libraries

Query: "When did I visit Tokyo?"
Instruction: Retrieve personal travel events and location visits

Now generate the instruction:
"""

        try:
            if self.is_gemini:
                response = self.gemini_client.models.generate_content(
                    model=settings.GEMINI_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.3,
                        thinking_config=types.ThinkingConfig(
                            thinking_budget=0,  # thinking_level="MINIMAL"
                        ),
                    ),
                )
                instruction_text = response.text.strip()
            else:
                model = self._get_model_for_task("brain")
                extra_body = self._with_keep_alive()

                response = self.chat_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    extra_body=extra_body,
                )
                instruction_text = response.choices[0].message.content.strip()

            # Format as Qwen3 instruction
            formatted = f"Instruct: {instruction_text}\nQuery: "
            logger.info(f"[LLM] Generated embedding instruction: {instruction_text}")
            return formatted

        except Exception as e:
            logger.warning(f"[LLM] Failed to generate instruction, using default: {e}")
            # Fallback to generic PKM instruction
            return "Instruct: Retrieve relevant information from the personal knowledge base\nQuery: "

    # Synthesis rules ported from benchmark v4/v5 (the 0.74-scoring pipeline).
    # Injected into BENCHMARK_MODE prompt and personal mode to enforce correct
    # answer-type discipline, comparison direction, specificity, and past/present.
    _SYNTHESIS_RULES = (
        "SYNTHESIS RULES — follow all of these when reasoning to your answer:\n\n"
        "RULE 1 — YES/NO: For yes/no comparisons, extract the relevant value per entity, "
        "compare them, then output YES or NO. Never output the compared value itself as the answer.\n"
        "RULE 2 — COMPARISON: For 'which of X or Y is more/older/greater', output the winner's "
        "full name, not the metric or value. Older = earlier birth year. "
        "Higher ratio = more instruments per person. Output the name of the winning entity.\n"
        "RULE 3 — MULTI-HOP CHAIN: Trace all findings in order. The bridge entity (the answer "
        "to an intermediate sub-question) is NOT the final answer — use it to find what was "
        "actually asked.\n"
        "RULE 4 — ANSWER TYPE: Match the exact type the question asks for. Common traps: "
        "song ≠ person who sang it; show ≠ character; number ≠ demonym; city ≠ building; "
        "position ≠ person who holds it; animal ≠ person named after it.\n"
        "RULE 5 — SPECIFICITY: Use the most specific value the evidence supports. "
        "Do not broaden: neighborhood → city, city → country, person → organization.\n"
        "RULE 6 — TEMPORAL: If the question asks for a former or historical value, use the "
        "value from that period, not the current one.\n"
        "RULE 7 — CHAIN TRACING: For two-hop questions, explicitly name the bridge entity "
        "first, then use it to reach the final answer. Do not shortcut.\n"
        "RULE 8 — ONE ANSWER: If the question asks for one thing, give one thing. "
        "Do not list alternatives or add caveats.\n"
        "RULE 9 — EXACT EXTRACTION:\n"
        "  (a) Do NOT ADD: parent geography, org prefix, or any qualifier not in the question.\n"
        "  (b) Do NOT STRIP: first names, suffixes, units, or qualifiers that are part of the answer.\n"
        "RULE 10 — CONFIRMATION QUESTION: When a question is phrased as a factual statement "
        "ending in '?' (e.g. 'X was founded by the person who did Y?'), output the specific "
        "name or entity being described — not YES. Only output YES/NO for questions that "
        "explicitly compare two named entities or ask whether two things share a property.\n"
        "RULE 11 — SHARED LOCATION: If two entities share a parent region, output the parent. "
        "Only list sub-locations when they differ from each other.\n"
        "RULE 12 — TYPE SANITY CHECK: Before writing your answer, verify it matches what was "
        "asked. A hedgehog is not a human; a country is not a city; a film is not a person.\n"
        "RULE 13 — PRESERVE TEMPORAL CONNECTIVES: When the answer describes a time span, "
        "copy the exact phrase from the source — including any leading 'from' or 'between' "
        "and the exact connective word ('to', 'until', 'through', 'and'). "
        "Do not normalise connectives: if the source uses 'until', keep 'until' — do not replace it with 'to'. "
        "If the source phrase has a leading 'from', keep it — do not drop it.\n"
        "RULE 14 — QUALIFIER MATCHING: When the question contains a qualifier that narrows the "
        "type of quantity (e.g. 'seat', 'net', 'original', 'peak', 'opening'), use the figure "
        "from the evidence that carries that same qualifier — not an unqualified or broader figure. "
        "Example: if evidence gives both a total figure and a qualified subset in parentheses, "
        "and the question asks for the qualified subset, use the parenthetical figure. "
        "Read the question's qualifier first, then select the matching value from the evidence."
    )

    def _get_model_for_task(self, task: str) -> str:
        """Get the appropriate model name for a given task based on provider."""
        if self.provider in ("ollama", "lm_studio"):
            return settings.LLM_MODEL
        elif self.provider == "openai":
            if task == "reasoning":
                return settings.OPENAI_MODEL_REASONING
            return settings.OPENAI_MODEL
        elif self.provider == "gemini":
            return settings.GEMINI_MODEL
        elif self.provider == "anthropic":
            return settings.ANTHROPIC_MODEL
        elif self.provider == "huggingface":
            return settings.HUGGINGFACE_MODEL
        return settings.LLM_MODEL

    def _extract_relevant_snippet(
        self, content: str, query_terms: set, window_size: int = 300
    ) -> str:
        """
        Finds the 300-char window with the highest density of query terms.
        If no terms found, returns the first 300 chars.
        """
        if not content:
            return ""

        content_lower = content.lower()
        if len(content) <= window_size:
            return content.replace("\n", " ")

        best_window = content
        max_score = 0

        # Simple sliding window (step 50)
        for i in range(0, len(content) - window_size, 50):
            window = content_lower[i : i + window_size]
            score = 0
            for term in query_terms:
                if term in window:
                    score += 1

            if score > max_score:
                max_score = score
                best_window = content[i : i + window_size]

        return best_window.replace("\n", " ")


llm_service = LLMService()
