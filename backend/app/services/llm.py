import os
import re
import torch
from app.core.config import settings
from app.core.log import get_logger
import instructor
from openai import OpenAI, AsyncOpenAI
from pydantic import BaseModel
from typing import Optional, Type
from google import genai
from google.genai import types

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

            self.extraction_client = instructor.patch(
                OpenAI(base_url=base_url, api_key=api_key, timeout=300.0),
                mode=instructor.Mode.MD_JSON,
            )
            self.chat_client = OpenAI(base_url=base_url, api_key=api_key, timeout=300.0)
            # Async client for batch processing
            self.async_chat_client = AsyncOpenAI(
                base_url=base_url, api_key=api_key, timeout=300.0
            )

        elif self.provider == "lm_studio":
            base_url = f"{settings.LLM_BASE_URL.rstrip('/')}/v1"
            logger.info(
                f"Initializing LM Studio (URL: {base_url}, Model: {settings.LLM_MODEL})"
            )
            api_key = settings.LLM_API_KEY

            self.extraction_client = instructor.patch(
                OpenAI(base_url=base_url, api_key=api_key, timeout=300.0)
            )
            self.chat_client = OpenAI(base_url=base_url, api_key=api_key, timeout=300.0)
            self.async_chat_client = AsyncOpenAI(
                base_url=base_url, api_key=api_key, timeout=300.0
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
            # Case-insensitive key lookup for logging
            entities = []
            concepts = []

            for k, v in parsed.items():
                if k.lower() == "entities" and isinstance(v, list):
                    entities = v
                elif k.lower() == "concepts" and isinstance(v, list):
                    concepts = v

            entity_count = len(entities)
            concept_count = len(concepts)

            logger.info(
                f"[Ollama] Raw extraction: {entity_count} entities, {concept_count} concepts"
            )
            if entity_count == 0:
                # Only warn if it's truly empty, but check if we might have missed the key due to structure
                # We check for list content to avoid false positives on empty lists
                logger.warning(
                    f"[Ollama] Empty entities (or capture failed). Full JSON: {cleaned_json[:2000]}"
                )
        except Exception:
            logger.warning(f"[Ollama] Could not pre-parse JSON: {cleaned_json[:500]}")

        try:
            return response_model.model_validate_json(cleaned_json)
        except Exception as validation_error:
            # Log the raw response for debugging
            logger.error(f"[Ollama] Validation failed: {validation_error}")
            logger.error(f"[Ollama] Raw JSON (first 1000 chars): {cleaned_json[:1000]}")
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

        _retryable = ("504", "DEADLINE_EXCEEDED", "503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED")
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
                return response_model(**response_data)

            except Exception as e:
                err = str(e)
                if "PROHIBITED_CONTENT" in err or "content_filter" in err.lower():
                    logger.warning("[Gemini] Content filtered. Returning empty model.")
                    return response_model()

                is_retryable = any(code in err for code in _retryable)
                if is_retryable and attempt < max_retries:
                    wait = 2 ** attempt  # 2s, 4s
                    logger.warning(
                        f"[Gemini] Retryable error (attempt {attempt}/{max_retries}), "
                        f"retrying in {wait}s: {err[:120]}"
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
            max_tokens=4096,
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
                max_tokens=4096,
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
                contents=f"Generate a concise, descriptive title (3-6 words) for this note. Do not use quotes.\n\nNote content:\n{text}\n\nTitle:",
            )
            return response.text.strip().replace('"', "")
        elif self.provider == "anthropic":
            response = self.chat_client.messages.create(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=100,
                messages=[
                    {
                        "role": "user",
                        "content": f"Generate a concise, descriptive title (3-6 words) for this note. Do not use quotes.\n\nNote content:\n{text}\n\nTitle:",
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
        from pydantic import Field
        from typing import Literal, Optional

        class QueryAnalysis(BaseModel):
            intent: Literal[
                "search", "summarize", "compare", "explain", "list", "recent"
            ] = Field(description="Primary intent of the query")
            is_temporal: bool = Field(
                description="Whether query asks for recent/latest/newest content"
            )
            time_range: Optional[str] = Field(
                default=None,
                description="Time range if specified: 'today', 'yesterday', 'last week', 'last month'",
            )
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
            requires_recent_context: bool = Field(
                description="Whether answer requires recent notes/events"
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
- is_temporal: true if asking about recent/latest content, false otherwise
- time_range: "today"/"yesterday"/"last week"/"last month" if mentioned, null otherwise
- entities: List of COMPLETE named entities (never split names)
- concepts: List of abstract topics
- keywords: List of important search terms
- requires_recent_context: true if answer needs recent notes, false otherwise
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
                "is_temporal": False,
                "time_range": None,
                "entities": [],
                "concepts": [],
                "keywords": query.split(),
                "requires_recent_context": False,
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
        from pydantic import Field
        from typing import Literal, Optional

        class SubQuestion(BaseModel):
            text: str = Field(description="The sub-question text")
            question_type: Literal["entity_lookup", "attribute", "relationship"] = (
                Field(description="Type of sub-question")
            )

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
  Example: "What award did the actress who played Erin Brockovich win?"
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

Input: "What award did the actress who played Erin Brockovich win?"
Output:
{{
    "requires_decomposition": true,
    "question_type": "multi_hop",
    "entities": ["Erin Brockovich"],
    "attribute": "award",
    "sub_questions": [
        {{"text": "Who played Erin Brockovich in the film?", "question_type": "relationship"}},
        {{"text": "What award did [actress from previous answer] win?", "question_type": "attribute"}}
    ],
    "synthesis_strategy": "Use the actress name from the first answer to answer the second question. Return the award name."
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

    def synthesize_multi_hop_answer(
        self, original_question: str, sub_answers: list[dict], synthesis_strategy: str
    ) -> str:
        """
        Synthesizes final answer from sub-question answers for multi-hop queries.

        Args:
            original_question: The original user question
            sub_answers: List of dicts with 'question' and 'answer' keys
            synthesis_strategy: Instructions for combining answers

        Returns:
            Final synthesized answer
        """
        # Format sub-answers for the prompt
        sub_answers_text = ""
        for i, sub in enumerate(sub_answers, 1):
            sub_answers_text += f"\nSub-Question {i}: {sub['question']}\n"
            sub_answers_text += f"Answer {i}: {sub['answer']}\n"

        prompt = f"""You are answering a complex question by synthesizing information from multiple sub-answers.

ORIGINAL QUESTION: "{original_question}"

SUB-QUESTIONS AND ANSWERS:
{sub_answers_text}

SYNTHESIS STRATEGY:
{synthesis_strategy}

Based on the sub-answers above, provide a concise, direct answer to the original question.
Rules:
- Use ONLY information from the sub-answers provided
- Be concise - answer in 1-3 sentences maximum
- If comparing, clearly state whether they are the same or different
- If extracting a specific value, return just that value
- If the sub-answers don't contain enough information, say "Unable to determine based on available information"

FINAL ANSWER:"""

        # Select model based on provider
        if self.provider == "gemini":
            response = self.gemini_client.models.generate_content(
                model=settings.GEMINI_MODEL, contents=prompt
            )
            return response.text.strip()
        elif self.provider == "anthropic":
            response = self.chat_client.messages.create(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
        else:
            # Ollama/LM Studio/OpenAI
            if self.provider == "ollama":
                model = settings.MODEL_SYNTHESIS
            elif self.provider == "lm_studio":
                model = self._get_model_for_task("summarization")
            else:
                model = settings.OPENAI_MODEL
            extra_body = self._with_keep_alive()

            response = self.chat_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                extra_body=extra_body,
            )
            return response.choices[0].message.content.strip()

    def summarize(self, text: str) -> str:
        """
        Generates a summary using the 'You' persona.
        STRICT GROUNDING: No outside info.
        """
        if not text or not text.strip():
            return "No content provided."

        # Benchmark mode uses factual, objective prompts
        if settings.BENCHMARK_MODE:
            system_prompt = "You are a factual summarization engine. Summarize the content based ONLY on the provided text. Use third-person, objective language. Keep sentences concise. Do NOT add personal framing or address any 'user'. Example: 'The document discusses the 2011 Patras Open tennis tournament.'"
        else:
            system_prompt = "You are a personal knowledge assistant. Summarize the user's note based ONLY on the provided text. Keep sentences EXTREMELY short (max 15 words) and simple. Address the user as 'You'. If the note is just a link (e.g. [[...]]) or very short, simply state what it references. Do NOT ask for more content. Example: 'You referenced a meeting about Ceruba.'"

        # Select model based on provider
        if self.provider == "gemini":
            response = self.gemini_client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=f"{system_prompt}\n\nContent:\n{text}\n\nSummary:",
            )
            return response.text.strip()
        elif self.provider == "anthropic":
            response = self.chat_client.messages.create(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=500,
                messages=[
                    {
                        "role": "user",
                        "content": f"{system_prompt}\n\nContent:\n{text}\n\nSummary:",
                    }
                ],
            )
            return response.content[0].text.strip()
        else:
            # Ollama/LM Studio/OpenAI
            model = self._get_model_for_task("summarization")
            extra_body = self._with_keep_alive()

            response = self.chat_client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {"role": "user", "content": f"Content:\n{text}\n\nSummary:"},
                ],
                extra_body=extra_body,
            )
            return response.choices[0].message.content.strip()

    async def generate(
        self, prompt: str, temperature: float = 0.1, max_tokens: int = 1000
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
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text.strip()

            else:  # OpenAI-compatible local or cloud providers
                model = self._get_model_for_task("brain")
                extra_body = self._with_keep_alive()

                response = self.chat_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    extra_body=extra_body,
                )
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
- Information may be incomplete — only identify what might plausibly exist in the knowledge base
- You are NOT answering the question — you are identifying what to look up

# QUESTION
{query}

# TASK
Break the question into a numbered sequence of information needs.
Each need must be a specific, independently searchable question.

RULES (read carefully — all must be followed):

1. SINGLE-HOP DETECTION: If the question is self-contained and asks for one fact directly, return exactly 1 need that mirrors the question verbatim. Do NOT split it further. Only decompose if the question requires looking up a missing intermediate fact.

2. PRESERVE SPECIFICITY: If the question names specific people, roles, or titles, keep those exact names in your sub-questions.

3. DON'T RE-ASK WHAT YOU KNOW: If the question already states a fact (e.g. "the author of Pride and Prejudice"), don't ask about it — use a [placeholder] and move on.

4. USE PLACEHOLDERS, NOT BACK-REFERENCES: For entities discovered in previous steps, you MUST use a typed placeholder like [founder], [director], [author], [film]. NEVER write "that person", "the series", "the film", "that author", or any other definite back-reference.

5. COMPARISON QUESTIONS: For "Were X and Y both…?", ask about each entity separately. Do NOT add a third question comparing the results — synthesis handles that.

6. QUESTION TYPE: If the original asks "what city?", your sub-question must ask "what city?", not "is X in a city?".

7. KEEP IT MINIMAL: Use 1–3 sub-questions. Use 4+ only when the chain genuinely requires it.

8. DEPENDENCIES FIRST: If question B requires information from question A, list A first.

OUTPUT FORMAT: Return ONLY the numbered list. No preamble, no explanation.

# EXAMPLES

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
1. What young adult series is told in first person and has companion books about enslaved alien worlds?

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

            logger.info(
                f"[LLM] identify_information_needs raw response:\n{answer}"
            )

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

    async def extract_discovered_entities(
        self, query: str, retrieval_results: list[dict]
    ) -> dict[str, str]:
        """
        Extract key entities/facts from retrieval results to fill placeholders in subsequent queries.

        Example:
        Query: "Who played Erin Brockovich in the film?"
        Results: [{"text": "Julia Roberts starred in Erin Brockovich as the title character..."}]
        Returns: {"actress name": "Julia Roberts", "played erin brockovich": "Julia Roberts"}

        Args:
            query: The information need query
            retrieval_results: Results from hybrid_search

        Returns:
            Dictionary mapping placeholder concepts to discovered entities
        """
        if not retrieval_results:
            return {}

        # Extract text from top 3 results
        context_snippets = []
        for doc in retrieval_results[:3]:
            text = doc.get("text", "")
            if text:
                context_snippets.append(text)

        if not context_snippets:
            return {}

        context = "\n\n".join(context_snippets)

        prompt = f"""Extract the key entities/facts that DIRECTLY ANSWER this question from the provided context.

# QUESTION
{query}

# CONTEXT
{context}

# TASK
Identify the specific entities (people, places, organizations, concepts) that DIRECTLY answer the question.

CRITICAL RULES:
1. Read ALL context snippets and find which snippet(s) ANSWER the question
2. IGNORE snippets that are unrelated or mention different topics
3. Extract ONLY from the snippet that directly answers the question
4. If the question asks "Who played X in film Y?", look for statements like "[Person] played X in Y" or "[Person] starred as X in Y"
5. Do NOT extract names just because they appear in context - they must be THE ANSWER
6. If you see multiple unrelated people mentioned (e.g., politicians, other actors), ignore them if they don't answer this specific question
7. Look for explicit verb connections: "X starred in...", "X directed...", "X portrayed...", "X was born in...", "X founded..."

Return them as key-value pairs where:
- Key: generic placeholder describing the entity type (e.g., "actor", "director", "location")  
- Value: THE specific entity name that directly answers the question

# FORMAT
Return ONLY the mappings, one per line in format: key = value

# EXAMPLES

Question: Who wrote 'The Great Gatsby'?
Context: F. Scott Fitzgerald wrote The Great Gatsby in 1925. The novel is set in New York...
Output:
author = F. Scott Fitzgerald
person = F. Scott Fitzgerald
wrote great gatsby = F. Scott Fitzgerald

Question: What is Marie Curie's nationality?
Context: Marie Curie was a Polish-French physicist who discovered radium. She won two Nobel Prizes...
Output:
nationality = Polish-French
marie curie nationality = Polish-French

Question: Who founded Microsoft?
Context: Microsoft was founded in 1975. Bill Gates and Paul Allen started the company in Albuquerque...
Output:
founder = Bill Gates
co-founder = Paul Allen
microsoft founder = Bill Gates

Now extract entities from the context above:
"""

        try:
            # Use reasoning model for entity extraction
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
                answer = response.text
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

            # Parse key = value pairs
            entities = {}
            for line in answer.split("\n"):
                line = line.strip()
                if "=" in line:
                    key, value = line.split("=", 1)
                    entities[key.strip().lower()] = value.strip()

            logger.info(
                f"[LLM] Extracted {len(entities)} entities from retrieval results"
            )
            for key, value in entities.items():
                logger.debug(f"  {key} = {value}")

            return entities

        except Exception as e:
            logger.error(f"[LLM] Failed to extract entities: {e}")
            return {}

    async def rewrite_back_references(self, sub_questions: list[str]) -> list[str]:
        """
        Post-process sub-questions to replace vague back-references with [placeholder].

        Mirrors _rewrite_back_references / _gemini_rewrite_back_refs from the benchmark
        pipeline (v4/v5). Calls the LLM for each sub-question after the first so that
        open-ended references like 'that series', 'the film', 'that company', 'the author'
        are replaced with [placeholder] tokens even when a regex wouldn't catch them.
        The first sub-question is always returned unchanged.
        """
        if not sub_questions:
            return []
        rewritten = [sub_questions[0]]
        for q in sub_questions[1:]:
            prompt = (
                "Rewrite the question by replacing vague references with [placeholder] tokens.\n\n"
                "A vague reference is a noun phrase that:\n"
                "- Uses a definite article or demonstrative ('the', 'that', 'this', 'those')\n"
                "- AND refers to something NOT named or defined within the question itself\n\n"
                "Examples of vague references: 'that series', 'the film', 'the author', 'that car', 'this work'\n"
                "NOT a vague reference: 'the Eiffel Tower' (it IS named), 'Marie Curie' (proper noun)\n\n"
                "Rules:\n"
                "- Replace each vague reference with a typed [placeholder] describing the entity type, e.g. [series], [film], [author]\n"
                "- If the question contains NO vague references, return it UNCHANGED\n"
                "- Return one line only — no explanation\n\n"
                f"QUESTION: {q}\n\n"
                "REWRITTEN:"
            )
            try:
                result = await self.generate(prompt, temperature=0.0, max_tokens=80)
                result = result.split("\n")[0].strip()
                if not result:
                    result = q
            except Exception:
                result = q
            if result != q:
                logger.info(f"[LLM] back-ref rewrite: '{q}' → '{result}'")
            rewritten.append(result)
        return rewritten

    async def identify_answer_type(self, question: str) -> str:
        """
        Return a short phrase describing what type of answer this question requires.

        Used to inject an ANSWER TYPE CONSTRAINT into the synthesis prompt —
        the key improvement in benchmark v4/v5 that prevents the LLM from
        returning the bridge entity instead of the actual requested value.

        Examples: 'a year', 'a person\'s name', 'a song or album title',
                  'yes or no', 'a number or count', 'a place name',
                  'a job title or role', 'an award or distinction'.
        """
        prompt = (
            "What single type of answer does this question require?\n"
            "Reply with one short phrase only. No punctuation, no line breaks, no explanation.\n"
            "Examples: a year, a person's name, a song or album title, "
            "yes or no, a number or count, a place name, a date range, "
            "a job title or role, an award or distinction, a company name\n\n"
            f"Question: {question}\n\nAnswer type:"
        )
        try:
            raw = await self.generate(prompt, temperature=0.0, max_tokens=20)
            # Collapse internal newlines that some models emit (e.g. 'yes or\nno')
            return " ".join(raw.split())
        except Exception:
            return "an answer"

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
            detail = (summary or context)[:150]
            detail_clause = f" — {detail}" if detail else ""
            # Prefer the stored natural language sentence; fall back to formatted rel_type
            nl_sentence = entry.get("nl_sentence")
            if nl_sentence:
                lines.append(f"{i}: {nl_sentence}{detail_clause}")
            else:
                rel_type = entry["rel_type"].replace("_", " ").lower()
                lines.append(
                    f'{i}: "{source}" {rel_type} "{neighbor_name}"{type_clause}{detail_clause}'
                )

        rel_list = "\n".join(lines)
        prompt = (
            f"QUESTION: {question}\n\n"
            "The following relationships connect already-relevant nodes to nodes not yet "
            "in context.\n"
            "Select ONLY the relationships whose connected node would add useful evidence "
            "to answer the question. Be selective — skip generic, tangential, or redundant "
            "nodes.\n"
            "If none are useful, reply: NONE\n\n"
            "For each relevant relationship, reply with its number followed by a colon and a brief reason.\n"
            "One per line. Example:\n"
            "0: the connected node directly provides the missing date\n"
            "3: named as the author in context\n\n"
            f"RELATIONSHIPS:\n{rel_list}\n\n"
            "Relevant relationship numbers (number: reason):"
        )
        try:
            raw = await self.generate(prompt, temperature=0.0, max_tokens=200)
            logger.info(
                f"[LLM] select_relevant_relationships raw response:\n{raw}"
            )
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
                        reason = line[match.end():].lstrip(":, ").strip()
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
                        max_output_tokens=150,
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                    ),
                )
                raw = response.text.strip()
            else:
                raw = await self.generate(prompt, temperature=0.0, max_tokens=150)

            if not raw:
                return None, None
            if raw.split("\n")[0].strip().upper().startswith("INSUFFICIENT"):
                follow_up = None
                for line in raw.splitlines():
                    if line.strip().upper().startswith("NEED:"):
                        follow_up = line.split(":", 1)[1].strip()
                        break
                return None, follow_up
            return raw.split("\n")[0].strip(), None
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

        qa_block = "\n".join(
            f"Q{i+1}: {sa['question']}\nA{i+1}: {sa['answer']}"
            for i, sa in enumerate(sub_answers)
        )

        # ── PASS 1: reasoning ────────────────────────────────────────────────
        # Ask for a bare answer phrase directly in ANSWER: — no full sentence.
        # SYNTHESIS_RULES guide correct reasoning (YES/NO, comparison winner,
        # shared-location parent, etc.). FORMAT RULES specify exact phrase shape.
        reasoning_prompt = (
            "You are answering a multi-hop question using research findings below.\n\n"
            f"RESEARCH FINDINGS:\n{qa_block}\n\n"
            f"Final question: {original_question}\n\n"
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
            "- Location → copy the location exactly as it appears in the source (e.g. 'Greenwich Village, New York City', not just 'Greenwich Village')\n\n"
            "If the findings do NOT contain enough information to answer, write:\n"
            "ANSWER: INSUFFICIENT\n"
            "MISSING: <one key entity or concept absent from the findings>\n\n"
            "Reply:"
        )
        try:
            raw1 = self.reason(reasoning_prompt) or ""
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
            bare = await self.generate(
                extraction_prompt, temperature=0.0, max_tokens=60
            )
            bare = (bare or "").strip()
            if bare and bare.upper() not in _non_answers:
                return bare, None
        except Exception as e:
            logger.warning(f"[LLM] final_synthesis_from_sub_answers pass2 failed: {e}")

        # Fallback: return the verbose answer from pass 1
        return verbose_answer, None

    async def extract_final_answer(
        self,
        question: str,
        docs: list[dict],
        keep: int = 8,
    ) -> str | None:
        """
        Option A+B fallback: select best docs then use reason() with an
        extraction-focused prompt that demands a minimal answer (name / yes|no /
        short fact).  Unlike answer_sub_question this uses the thinking model so
        it can handle multi-hop reasoning, and the prompt prohibits full sentences.
        """
        relevant = await self.select_relevant_docs(docs, question)
        if not relevant:
            return None

        context_parts = []
        for doc in relevant:
            node = doc.get("original_obj", {})
            name = node.get("name", "")
            text = (
                node.get("summary") or node.get("description") or doc.get("text", "")
            ).strip()
            if text:
                context_parts.append(f"{name}: {text}" if name else text)

        context = "\n\n".join(context_parts[:keep])
        if not context:
            return None

        prompt = (
            "You are answering a multi-hop question using retrieved evidence below.\n\n"
            f"EVIDENCE:\n{context}\n\n"
            f"Final question: {question}\n\n"
            f"{self._SYNTHESIS_RULES}\n\n"
            "First write 1–2 sentences of reasoning that end with a clear statement "
            "of your answer, then on a new line write:\n"
            "FINAL: <bare answer only — a name, number, or yes/no — no surrounding explanation or extra words>"
        )
        try:
            raw = (self.reason(prompt) or "").strip()
            # Parse FINAL: prefix
            for line in raw.split("\n"):
                line = line.strip()
                if line.upper().startswith("FINAL:"):
                    raw = line[6:].strip()
                    break
            else:
                # No FINAL: line found — take last non-empty line (after reasoning)
                lines = [line.strip() for line in raw.split("\n") if line.strip()]
                raw = lines[-1] if lines else ""
            if not raw or raw.upper() in (
                "UNKNOWN",
                "INSUFFICIENT",
                "UNABLE TO DETERMINE",
                "N/A",
            ):
                return None
            return raw
        except Exception as e:
            logger.warning(f"[LLM] extract_final_answer failed: {e}")
            return None

    async def select_relevant_docs_with_reasoning(
        self,
        docs: list[dict],
        question: str,
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
        prompt = (
            f"QUESTION: {question}\n\n"
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
            raw = await self.generate(prompt, temperature=0.0, max_tokens=1500)
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
                        reason = line[match.end():].lstrip(":, ").strip()
                        reasons[idx] = reason
                        indices.append(idx)
            seen: set[int] = set()
            unique_indices = [idx for idx in indices if not (idx in seen or seen.add(idx))]  # type: ignore[func-returns-value]
            if unique_indices:
                return [docs[i] for i in unique_indices], {i: reasons.get(i, "") for i in unique_indices}
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
          - full_answer: 2-3 sentence answer covering the topic with context
          - direct_answer: the single key fact / shortest complete answer
          - reasoning: the LLM's chain-of-thought explaining its answer

        Returns (None, None, "") if context is insufficient.
        """
        if not docs:
            return None, None, "No context documents provided."

        context_parts = []
        for doc in docs:
            node = doc.get("original_obj", {})
            text = (
                doc.get("text") or node.get("summary") or node.get("description") or ""
            ).strip()
            if text:
                context_parts.append(text)
        context = "\n\n".join(context_parts)
        if not context:
            return None, None, "All context documents had empty text."

        prompt = (
            "Answer the question below using ONLY the context provided.\n\n"
            f"QUESTION: {sub_question}\n\n"
            f"CONTEXT:\n{context}\n\n"
            "Reply in this EXACT format (all three sections required):\n\n"
            "REASONING: <1-3 sentences tracing which part of the context answers the question and why>\n\n"
            "FULL_ANSWER: <2-3 sentences covering the topic with relevant context — not just the bare fact>\n\n"
            "DIRECT_ANSWER: <the single key fact, name, date, or yes/no that directly answers the question — "
            "exact phrase from context, no elaboration>\n\n"
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
                        max_output_tokens=400,
                        thinking_config=types.ThinkingConfig(thinking_budget=512),
                    ),
                )
                raw = response.text.strip()
            else:
                raw = await self.generate(prompt, temperature=0.0, max_tokens=400)

            logger.info(
                f"[LLM] answer_sub_question_dual raw response:\n{raw}"
            )
            if not raw:
                return None, None, "LLM returned empty response."

            reasoning = ""
            full_answer = None
            direct_answer = None
            for line in raw.splitlines():
                line = line.strip()
                if line.upper().startswith("REASONING:"):
                    reasoning = line.split(":", 1)[1].strip()
                elif line.upper().startswith("FULL_ANSWER:"):
                    val = line.split(":", 1)[1].strip()
                    if val.upper() != "INSUFFICIENT":
                        full_answer = val
                elif line.upper().startswith("DIRECT_ANSWER:"):
                    val = line.split(":", 1)[1].strip()
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
        """
        if not sub_results:
            return None

        qa_block_lines = []
        for i, sr in enumerate(sub_results, 1):
            q = sr.get("resolved_question") or sr.get("question", "")
            full = sr.get("full_answer") or "Not found"
            direct = sr.get("direct_answer") or "Not found"
            qa_block_lines.append(
                f"Sub-question {i}: {q}\n"
                f"  Full context: {full}\n"
                f"  Direct answer: {direct}"
            )
        qa_block = "\n\n".join(qa_block_lines)

        reasoning_prompt = (
            "You are answering a multi-hop question using structured research findings.\n\n"
            f"RESEARCH FINDINGS:\n{qa_block}\n\n"
            f"Original question: {original_question}\n\n"
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
            "- Location → copy location exactly as it appears in the source\n\n"
            "If findings are insufficient:\n"
            "ANSWER: INSUFFICIENT\n\n"
            "Reply:"
        )
        try:
            raw = self.reason(reasoning_prompt) or ""
            logger.info(
                f"[LLM] final_synthesis_from_sub_results raw response:\n{raw}"
            )
        except Exception as e:
            logger.warning(f"[LLM] final_synthesis_from_sub_results failed: {e}")
            return None

        _non_answers = {"INSUFFICIENT", "NONE", "N/A", "UNKNOWN", "NOT FOUND"}
        for line in raw.splitlines():
            line = line.strip()
            if line.lower().startswith("answer:"):
                val = line.split(":", 1)[1].strip()
                if val.upper() not in _non_answers:
                    return val
        return None

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
            lines.append(f"{i}: [{name}] {snippet}")

        doc_list = "\n".join(lines)
        prompt = (
            f"QUESTION: {question}\n\n"
            f"Below are {len(docs)} retrieved passages numbered 0–{len(docs) - 1}.\n"
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
            raw = await self.generate(prompt, temperature=0.0, max_tokens=1000)
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
                        reason = line[match.end():].lstrip(":, ").strip()
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
        for doc in docs[:8]:
            node = doc.get("original_obj", {})
            name = node.get("name") or doc.get("name", "?")
            text = (doc.get("text") or node.get("summary") or "").strip()[:200]
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
            raw = await self.generate(prompt, temperature=0.1, max_tokens=30)
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
        for doc in all_docs[:6]:
            node = doc.get("original_obj", {})
            name = node.get("name") or doc.get("name", "?")
            text = (doc.get("text") or node.get("summary") or "").strip()[:200]
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
            raw = await self.generate(prompt, temperature=0.0, max_tokens=100)
            sentence = raw.strip()
            if sentence:
                return sentence
        except Exception as e:
            logger.warning(f"[LLM] summarize_search_failure failed: {e}")
        return f"Could not find sufficient information to answer: {question}"

    async def extract_name_for_hop(
        self,
        question: str,
        verified_docs: list[dict],
        original_question: str = "",
    ) -> str:
        """
        Extract a short bridge-entity value (1–6 words) from verified docs.

        Used between pipeline hops to fill [placeholder] tokens in the next
        sub-question.  Mirrors _extract_name_only / _gemini_extract_name from
        benchmark v4/v5: builds a plain-text context from the top 3 verified
        docs, optionally adds a granularity hint derived from the original
        question, and asks the LLM for just the name or value.
        """
        context_parts = []
        for doc in verified_docs[:3]:
            node = doc.get("original_obj", {})
            text = (
                node.get("summary") or node.get("description") or doc.get("text", "")
            ).strip()
            name = node.get("name", "")
            if name and text:
                context_parts.append(f"{name}: {text}")
            elif text:
                context_parts.append(text)
        context = "\n\n".join(context_parts)

        granularity_hint = ""
        if original_question:
            granularity_hint = (
                f'\nIMPORTANT: The final question is: "{original_question}"\n'
                "Return only the part of your answer relevant to that question's level of detail "
                "(e.g. if the final question compares neighborhoods, return the neighborhood name only, not the city)."
            )
        prompt = (
            f"Extract the answer to the question from the context below.{granularity_hint}\n"
            "Reply with ONLY the name or value — 1 to 6 words, no sentence, no explanation.\n\n"
            f"CONTEXT:\n{context}\n\n"
            f"QUESTION: {question}\n\nANSWER:"
        )
        try:
            result = await self.generate(prompt, temperature=0.0, max_tokens=20)
            return result.split("\n")[0].strip()
        except Exception:
            return ""

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

    def expand_type_synonyms(self, entity_type: str) -> list[str]:
        """
        Dynamically generate type synonyms using LLM reasoning.

        Args:
            entity_type: The entity type to expand (e.g., "film", "person")

        Returns:
            List of synonym types (including original)
        """
        prompt = f"""List all common synonyms and related terms for the entity type "{entity_type}".

# EXAMPLES
- film → movie, cinema, motion picture
- person → individual, actor, director, writer, artist, musician
- place → location, venue, city, country, region
- organization → company, corporation, institution, business, firm

# INSTRUCTIONS
1. List ONLY valid synonyms and closely related types
2. Keep it concise (max 5 synonyms)
3. Return comma-separated list

Entity type: {entity_type}
Synonyms:"""

        try:
            if self.is_gemini:
                response = self.gemini_client.models.generate_content(
                    model=settings.GEMINI_MODEL,
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
                response = self.chat_client.chat.completions.create(
                    model=self._get_model_for_task("brain"),
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=100,
                    extra_body=self._with_keep_alive(),
                )
                answer = response.choices[0].message.content.strip()

            # Parse synonyms
            synonyms = [
                s.strip().lower()
                for s in answer.replace("\n", ",").split(",")
                if s.strip()
            ]
            # Always include original
            if entity_type.lower() not in synonyms:
                synonyms.insert(0, entity_type.lower())

            logger.debug(f"[LLM] Type synonyms for '{entity_type}': {synonyms}")
            return synonyms[:6]  # Limit to 6

        except Exception as e:
            logger.warning(
                f"[LLM] Failed to expand type synonyms for '{entity_type}': {e}"
            )
            return [entity_type.lower()]  # Fallback to original

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
        "If the source phrase has a leading 'from', keep it — do not drop it."
    )

    async def synthesize(
        self, top_docs: list[dict], query: str, answer_type: str = ""
    ) -> str:
        """
        Uses reasoning model for Synthesis with domain-aware prompting.
        Accepts structured Top Docs (not just string).
        STRICT: No Advice, Only Insights.
        Non-blocking (runs in thread).

        answer_type: optional short phrase from identify_answer_type() injected as
            an ANSWER TYPE CONSTRAINT into BENCHMARK_MODE prompt (v4/v5 pattern).
        """
        # Detect query domain for tailored system prompt
        query_domain = self._detect_query_domain(query)

        # Build Structured Context
        structured_context_str = self._format_structured_context(top_docs, query)

        # Domain-specific system instructions
        if query_domain == "Academic":
            domain_instructions = """
        # MODE: Academic Learning Assistant
        - Focus on conceptual understanding and knowledge synthesis
        - Connect theoretical concepts and their relationships
        - Highlight prerequisites, derivations, and contradictions
        - Reference papers, books, or theorems cited in notes
        - Explain complex ideas in clear, pedagogical language
            """
        elif query_domain == "Professional":
            domain_instructions = """
        # MODE: Professional Knowledge Base
        - Focus on project context and technical documentation
        - Connect related tasks, meetings, and decisions
        - Reference technical resources and best practices
        - Maintain professional, concise language
            """
        elif query_domain == "Creative":
            domain_instructions = """
        # MODE: Creative Expression Companion
        - Focus on themes, metaphors, and emotional resonance in creative works
        - Connect recurring symbols and imagery across poems/lyrics
        - Identify emotional arcs and stylistic patterns
        - Reference specific lines or verses when relevant
        - Use poetic, interpretive language
            """
        elif query_domain == "Dreams":
            domain_instructions = """
        # MODE: Dream Analysis Companion
        - Focus on symbolic interpretation and pattern recognition across dreams
        - Connect recurring symbols, people, places, and themes
        - Identify emotional undertones and subconscious patterns
        - Reference specific dream imagery and narrative elements
        - Use exploratory, non-literal language for symbolic meaning
        - NO interpretation as prophecy or literal events
            """
        else:  # Personal
            domain_instructions = """
        # MODE: Personal Journal Companion
        - Focus on personal insights and emotional patterns
        - Connect experiences, feelings, and personal growth
        - Reference daily activities and relationships
        - Use empathetic, personal language
            """

        # Benchmark mode uses factual, objective prompts for accurate evaluation
        if settings.BENCHMARK_MODE:
            answer_type_constraint = (
                f"ANSWER TYPE CONSTRAINT: This question requires {answer_type}. "
                f"Your FINAL: answer MUST be {answer_type} — do not substitute a related "
                "entity, person, or broader concept instead.\n\n"
                if answer_type
                else ""
            )
            prompt = (
                "You are answering a multi-hop question using retrieved evidence below.\n\n"
                f"{structured_context_str}\n\n"
                f"Final question: {query}\n\n"
                f"{answer_type_constraint}"
                f"{self._SYNTHESIS_RULES}\n\n"
                "Write 1–2 sentences of reasoning that trace through the evidence, "
                "then on a new line write:\n"
                "FINAL: <bare answer only — a name, number, date range, or yes/no — no explanation>"
            )
        else:
            prompt = f"""
        # ROLE
        You are the User's "Second Brain"—a thoughtful, conversational AI partner.
        Your goal is to answer the query based on the retrieved knowledge from their life.
        
        {domain_instructions}
        
        # STYLE GUIDELINES
        - **CONVERSATIONAL**: Write naturally. Avoid headers like "DIRECT ANSWER" or "INSIGHTS".
        - **GROUNDED**: Every claim must be based on the provided [CORE CONSENSUS] or [RELATED CONTEXT].
        - **PEER PERSONA**: Address the user as "You". Don't say "The notes reveal"; say "You mentioned" or "As far as your projects go..."
        - **DIRECT BUT FLUID**: Answer the question immediately, but weave the supporting facts into the narrative.
        
        # CONSTRAINTS
        - **NO ADVICE**: Do not tell the user what they "should" do. Just state the facts.
        - **NO PREAMBLE**: Don't start with "Looking at your notes..." or "I found this...". Just start the conversation.
        - **NO CITATIONS**: Do not use "(/notes/id)" or "Note: X". The UI handles this.
        - **NO FOLLOW-UP QUESTIONS**: Don't ask "Would you like me to explore..." - just answer and stop.
        
        # CONTEXT
        {structured_context_str}
        
        # USER QUESTION
        {query}
        
        # YOUR RESPONSE (Conversational and grounded)
        """
        import asyncio

        loop = asyncio.get_running_loop()

        if self.is_gemini:

            def _call_model():
                return self.gemini_client.models.generate_content(
                    model=settings.GEMINI_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        thinking_config=types.ThinkingConfig(
                            thinking_budget=0,  # thinking_level="MINIMAL"
                        ),
                    ),
                )

            logger.info(f"synthesize calling model: {settings.GEMINI_MODEL}")
            response = await loop.run_in_executor(None, _call_model)
            return response.text
        else:
            model = self._get_model_for_task("brain")
            extra_body = self._with_keep_alive()

            def _call_model():
                return self.chat_client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a strict insight engine. You do not give advice. You only analyze the provided text.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    extra_body=extra_body,
                    temperature=0.1,
                )

            logger.info(f"synthesize calling model: {model}")
            response = await loop.run_in_executor(None, _call_model)

            # Handle Anthropic response wrapper
            if hasattr(response, "__class__") and "ResponseWrapper" in str(
                response.__class__
            ):
                return response.choices[0].message.content

            return response.choices[0].message.content

    def generate_answer(
        self, question: str, context_docs: list[dict], max_length: int = 200
    ) -> str:
        """
        Generate a concise answer to a question given context documents.
        Simplified version of synthesize() for sub-question answering in decomposition.

        Args:
            question: The question to answer
            context_docs: List of retrieved document dicts
            max_length: Maximum length of answer in tokens (default 200)

        Returns:
            str: Generated answer
        """
        # Format context from docs
        context_str = self._format_structured_context(context_docs, question)

        # Use benchmark-style prompt for precise answers
        prompt = f"""Answer concisely using ONLY the provided context. Be direct and factual.

CONTEXT:
{context_str}

QUESTION: {question}

ANSWER (be brief, max 2-3 sentences):"""

        # Select model based on provider
        model = self._get_model_for_task("reasoning")

        if self.provider == "gemini":
            response = self.gemini_client.models.generate_content(
                model=model, contents=prompt
            )
            return response.text.strip()
        elif self.provider == "anthropic":
            response = self.chat_client.messages.create(
                model=model,
                max_tokens=max_length,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
        else:
            # Ollama/LM Studio/OpenAI
            extra_body = self._with_keep_alive()

            response = self.chat_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=max_length,
                extra_body=extra_body,
            )
            return response.choices[0].message.content.strip()

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
        return settings.LLM_MODEL

    def detect_domain(self, text: str) -> str:
        """
        Public wrapper for domain detection. Used by ingestion to assign nodes to communities.

        Args:
            text: Content to analyze for domain classification

        Returns:
            Domain string: "Academic", "Professional", "Personal", "Creative", or "Dreams"
        """
        return self._detect_query_domain(text)

    def _detect_query_domain(self, query: str) -> str:
        """
        Heuristic to detect if query is Academic, Personal, Professional, Creative, or Dreams.
        Uses same logic as retrieval service for consistency.
        """
        query_lower = query.lower()

        # Academic keywords
        academic_keywords = [
            "learn",
            "study",
            "concept",
            "theorem",
            "paper",
            "book",
            "course",
            "lecture",
            "understand",
            "explain",
            "theory",
            "research",
            "academic",
            "mathematics",
            "science",
            "proof",
            "definition",
            "algorithm",
        ]

        # Personal keywords
        personal_keywords = [
            "feel",
            "feeling",
            "emotion",
            "happy",
            "sad",
            "anxious",
            "worried",
            "relationship",
            "friend",
            "family",
            "daily",
            "today",
            "yesterday",
            "personal",
            "goal",
            "hope",
            "fear",
            "love",
            "hate",
        ]

        # Professional keywords
        professional_keywords = [
            "work",
            "project",
            "meeting",
            "career",
            "job",
            "task",
            "deadline",
            "professional",
            "team",
            "client",
            "manager",
            "office",
            "business",
        ]

        # Creative keywords
        creative_keywords = [
            "poem",
            "poetry",
            "verse",
            "lyric",
            "lyrics",
            "song",
            "metaphor",
            "stanza",
            "rhyme",
            "creative",
            "fiction",
            "story",
            "prose",
            "writing",
        ]

        # Dreams keywords
        dreams_keywords = [
            "dream",
            "dreamt",
            "dreamed",
            "nightmare",
            "subconscious",
            "recurring",
            "symbol",
            "sleep",
            "woke",
            "vision",
        ]

        academic_score = sum(1 for kw in academic_keywords if kw in query_lower)
        personal_score = sum(1 for kw in personal_keywords if kw in query_lower)
        professional_score = sum(1 for kw in professional_keywords if kw in query_lower)
        creative_score = sum(1 for kw in creative_keywords if kw in query_lower)
        dreams_score = sum(1 for kw in dreams_keywords if kw in query_lower)

        # Return domain with highest score, default to Personal
        max_score = max(
            academic_score,
            personal_score,
            professional_score,
            creative_score,
            dreams_score,
        )
        if max_score == 0:
            return "Personal"  # Default

        if academic_score == max_score:
            return "Academic"
        elif professional_score == max_score:
            return "Professional"
        elif creative_score == max_score:
            return "Creative"
        elif dreams_score == max_score:
            return "Dreams"
        else:
            return "Personal"

    class SummaryUpdate(BaseModel):
        title: str
        summary: str

    def generate_entity_summary(
        self,
        context: str,
        entity_name: str,
        entity_type: str,
    ) -> dict:
        """
        Generates a FRESH summary for an entity from the provided context.
        This is used when creating new entities or when no existing summary exists.

        Returns:
            dict with 'title' and 'summary' keys
        """
        if not context or not context.strip():
            return {
                "description": f"Information about {entity_name}.",
            }

        # Benchmark mode uses factual, objective prompts
        if settings.BENCHMARK_MODE:
            format_rules = """### FORMAT RULES
        - Write a concise prose summary of the entity in 2–4 sentences.
        - Prioritize key facts by node type:
            Person       → nationality, occupation, known_for
            Place        → country, type, located_in
            Organization → founded_year, headquarters, type
            Event        → date, location, outcome
        - Normalize values: nationalities as country names ("United States" not "American"). Years as 4-digit integers.
        - If the same fact appears multiple times, deduplicate — include it ONCE only.
        - Use third-person, objective language (not "you" or "I").
        - Be factual and grounded IN THE PROVIDED CONTEXT ONLY.
        - Do NOT use personal framing or address any user."""
            title_rules = f"""### TITLE RULES
        Generate a short descriptive title (MAX 5 WORDS) for '{entity_name}'."""
        else:
            format_rules = """### FORMAT RULES
        - Write a concise prose summary of the entity.
        - ADDRESS USER AS "YOU" (not "I" or third person).
        - Be factual and grounded IN THE PROVIDED CONTEXT ONLY."""
            title_rules = f"""### TITLE RULES
        Generate a punchy title (MAX 5 WORDS) capturing '{entity_name}''s role in the user's life."""

        prompt = f"""
        ### SYSTEM INSTRUCTIONS
        You are the LiveOS Core. Create a Knowledge Graph entry for '{entity_name}'.
        
        ### ANTI-HALLUCINATION RULES (ABSOLUTELY CRITICAL)
        ⚠️ NEVER invent, assume, or add information not explicitly present in the context below.
        ⚠️ NEVER use your training knowledge to fill in gaps (no external facts, dates, names, numbers).
        ⚠️ If something is unclear or missing, say "details pending" - DO NOT GUESS.
        ⚠️ ONLY include facts that are EXPLICITLY stated in the Context.
        
        ### CONTENT RICHNESS RULES
        1. Include ALL relevant details from the context about '{entity_name}'.
        2. Preserve specific facts: dates, numbers, names, outcomes FROM THE CONTEXT ONLY.
        3. Write in a way that captures what was ACTUALLY written, not what you think was meant.
        4. If the same fact appears multiple times in the context, include it ONCE only — deduplicate aggressively.
        
        {title_rules}
        
        {format_rules}

        ### INPUT
        Entity: {entity_name} ({entity_type})
        
        Context about {entity_name}: 
        "{context}"
        
        ### OUTPUT (JSON)
        {{
            "title": "Short Title Here",
            "summary": "Content-rich summary here..."
        }}
        """

        try:
            model = (
                settings.GEMINI_MODEL
                if self.is_gemini
                else self._get_model_for_task("extraction")
            )

            if not self.is_gemini:
                extra_body = self._with_keep_alive({"format": "json"})
                response = self.chat_client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": """You are a JSON-only definition engine. Valid JSON (RFC 8259). 
Example:
{
  "title": "My Title",
  "summary": "My summary."
}
Double-quote all keys. Use straight quotes, not curly quotes.""",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    extra_body=extra_body,
                )
                raw_content = response.choices[0].message.content
                cleaned_json = self._clean_json(raw_content)
                parsed = self.SummaryUpdate.model_validate_json(cleaned_json)
                return {"description": parsed.summary}
            else:
                # For Gemini: use native SDK with schema enforcement
                response = self.gemini_client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        response_mime_type="application/json",
                        response_schema=self.SummaryUpdate.model_json_schema(),
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                    ),
                )
                import json

                response_data = json.loads(response.text)
                return {
                    "description": response_data.get(
                        "summary", f"Information about {entity_name}."
                    ),
                }
        except Exception as e:
            logger.error(f"Entity Summary Generation Failed for {entity_name}: {e}")
            return {
                "description": f"Information about {entity_name}.",
            }

    async def generate_entity_summary_async(
        self, context: str, entity_name: str, entity_type: str
    ) -> dict:
        """
        Async version of generate_entity_summary for batch processing.
        Generates a FRESH summary from isolated context using Gemini's async API.
        """
        # Benchmark mode uses factual, objective prompts
        if settings.BENCHMARK_MODE:
            format_rules = """### FORMAT RULES
        - Write a concise prose summary of the entity in 2–4 sentences.
        - Prioritize key facts by node type:
            Person       → nationality, occupation, known_for
            Place        → country, type, located_in
            Organization → founded_year, headquarters, type
            Event        → date, location, outcome
        - Normalize values: nationalities as country names ("United States" not "American"). Years as 4-digit integers.
        - If the same fact appears multiple times, deduplicate — include it ONCE only.
        - Use third-person, objective language (not "you" or "I").
        - Be factual and grounded IN THE PROVIDED CONTEXT ONLY.
        - Do NOT use personal framing or address any user."""
            title_rules = f"""### TITLE RULES
        Generate a short descriptive title (MAX 5 WORDS) for '{entity_name}'."""
        else:
            format_rules = """### FORMAT RULES
        - Write a concise prose summary of the entity.
        - ADDRESS USER AS "YOU" (not "I" or third person).
        - Be factual and grounded IN THE PROVIDED CONTEXT ONLY."""
            title_rules = f"""### TITLE RULES
        Generate a punchy title (MAX 5 WORDS) capturing '{entity_name}''s role in the user's life."""


        prompt = f"""
        ### SYSTEM INSTRUCTIONS
        You are the LiveOS Core. Generate a Knowledge Graph entry for '{entity_name}'.
        
        ### ANTI-HALLUCINATION RULES (ABSOLUTELY CRITICAL)
        ⚠️ NEVER invent, assume, or add information not explicitly present in the context below.
        ⚠️ NEVER use your training knowledge to fill in gaps (no external facts, dates, names, numbers).
        ⚠️ If something is unclear or missing, say "details pending" or "not yet known" - DO NOT GUESS.
        ⚠️ ONLY include facts that are EXPLICITLY stated in the Context.
        
        ### CONTENT RICHNESS RULES
        1. Include ALL relevant details from the provided context about '{entity_name}'.
        2. Preserve specific facts: dates, numbers, names, outcomes FROM THE CONTEXT ONLY.
        3. Write in a way that captures what was ACTUALLY written, not what you think was meant.
        4. If the same fact appears multiple times in the context, include it ONCE only — deduplicate aggressively.
        
        {title_rules}
        
        {format_rules}

        ### INPUT
        Entity: {entity_name} ({entity_type})
        
        Context about {entity_name}: 
        "{context}"
        
        ### OUTPUT (JSON)
        {{
            "title": "Short Title Here",
            "summary": "Content-rich summary here..."
        }}
        """

        try:
            model = (
                settings.GEMINI_MODEL
                if self.is_gemini
                else self._get_model_for_task("extraction")
            )

            if self.is_gemini:
                # Use Gemini async client for batch processing
                response = await self.gemini_client.aio.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        response_mime_type="application/json",
                        response_schema=self.SummaryUpdate.model_json_schema(),
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                    ),
                )
                import json

                response_data = json.loads(response.text)
                return {
                    "description": response_data.get(
                        "summary", response_data.get("description", f"Information about {entity_name}.")
                    ),
                }
            elif self.provider in ["ollama", "lm_studio", "openai"]:
                # Use async OpenAI client for Ollama, LM Studio, and OpenAI batch processing
                response_format = (
                    self._lm_studio_text_response_format()
                    if self.provider == "lm_studio"
                    else {"type": "json_object"}
                )
                response = await self.async_chat_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    extra_body=self._with_keep_alive(
                        {"response_format": response_format}
                    ),
                )
                import json

                response_data = json.loads(response.choices[0].message.content)
                return {
                    "description": response_data.get(
                        "summary", response_data.get("description", f"Information about {entity_name}.")
                    ),
                }
            else:
                # Fallback to sync for other providers
                return self.generate_entity_summary(context, entity_name, entity_type)
        except Exception as e:
            logger.error(
                f"Async Entity Summary Generation Failed for {entity_name}: {e}"
            )
            return {
                "description": f"Information about {entity_name}.",
            }

    def extract_atomic_facts(
        self,
        context: str,
        entity_name: str,
        entity_type: str,
    ) -> list[str]:
        """
        Atomize the context about entity_name into proposition sentences.

        Each fact is a self-contained sentence that can be understood without
        additional context, e.g.:
            "The Eiffel Tower was built in 1889."
            "Neil Armstrong walked on the Moon in 1969."

        Returns a list of plain English proposition strings (NOT key-value pairs).
        """
        if not context or not context.strip():
            return []

        prompt = (
            f"Atomize the following context about '{entity_name}' into individual "
            f"proposition sentences.\n\n"
            f"Rules:\n"
            f"- Each proposition must be a complete, self-contained sentence.\n"
            f"- Use the entity's full name in each sentence (not pronouns).\n"
            f"- Only include facts EXPLICITLY stated in the context. Do NOT invent or infer.\n"
            f"- Do NOT use key-value format. Only plain English sentences.\n"
            f"- Deduplicate: if the same fact appears twice, include it once.\n"
            f"- Include all factual propositions from the context. Do not limit the count.\n\n"
            f"Examples:\n"
            f'Input: "The Eiffel Tower, built in 1889, is a wrought-iron lattice tower in Paris."\n'
            f'Output: ["The Eiffel Tower was built in 1889.", '
            f'"The Eiffel Tower is a wrought-iron lattice tower.", '
            f'"The Eiffel Tower is located in Paris."]\n\n'
            f"CONTEXT:\n{context}\n\n"
            f'OUTPUT (JSON array of strings only): ["fact 1", "fact 2", ...]'
        )

        class _FactList(BaseModel):
            facts: list[str]

        try:
            model = (
                settings.GEMINI_MODEL
                if self.is_gemini
                else self._get_model_for_task("extraction")
            )
            if not self.is_gemini:
                extra_body = self._with_keep_alive({"format": "json"})
                resp = self.chat_client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": 'Return valid JSON only: {"facts": ["sentence 1", "sentence 2"]}',
                        },
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=2000,
                    extra_body=extra_body,
                )
                raw = resp.choices[0].message.content
                cleaned = self._clean_json(raw)
                import json as _json
                import re as _re
                try:
                    data = _json.loads(cleaned)
                    if isinstance(data, dict) and "facts" in data:
                        return [str(f) for f in data["facts"]]
                    if isinstance(data, list):
                        return [str(f) for f in data]
                    return []
                except Exception:
                    match = _re.search(r"\[.*?\]", cleaned, _re.DOTALL)
                    if match:
                        return _json.loads(match.group())
                    return []
            else:
                from google.genai import types as _gtypes

                resp = self.gemini_client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=_gtypes.GenerateContentConfig(
                        temperature=0.0,
                        response_mime_type="application/json",
                        response_schema=_FactList.model_json_schema(),
                        thinking_config=_gtypes.ThinkingConfig(thinking_budget=0),
                        automatic_function_calling=_gtypes.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                    ),
                )
                import json as _json
                data = _json.loads(resp.text)
                if isinstance(data, dict) and "facts" in data:
                    return data["facts"]
                return []
        except Exception as e:
            logger.warning(f"Atomic fact extraction failed for {entity_name}: {e}")
            return []

    def generate_potential_questions(
        self,
        name: str,
        node_type: str,
        description: str,
        facts_list: list[str],
    ) -> list[str]:
        """Generate up to MAX_POTENTIAL_QUESTIONS questions this node's information could answer.

        Questions are based on name + description + facts (proposition sentences).
        Relationships are intentionally excluded (they are separate Qdrant points).

        Returns a list of plain-English question strings (no leading numbering).
        """
        if not description and not facts_list:
            return []

        facts_text = ""
        if facts_list:
            facts_text = "\n".join(f"- {f}" for f in facts_list)

        prompt = (
            f"You are generating retrieval questions for a knowledge-graph node.\n\n"
            f"Node name: {name}\n"
            f"Node type: {node_type}\n"
            f"Description: {description}\n"
            + (f"Facts:\n{facts_text}\n" if facts_text else "")
            + f"\nGenerate all specific, meaningful questions that the information "
            f"above could directly answer. Include every relevant question — do not limit the count. "
            f"Focus on factual, precise questions "
            f"(e.g. 'What year was X founded?' 'Where is X located?' 'Who leads X?').\n\n"
            f"Rules:\n"
            f"- Only ask questions answerable from the information provided.\n"
            f"- Do NOT ask vague or overly broad questions.\n"
            f"- Do NOT number the questions.\n"
            f'- Return ONLY a JSON array of strings: ["question 1", "question 2", ...]'
        )

        try:
            model = (
                settings.GEMINI_MODEL
                if self.is_gemini
                else self._get_model_for_task("extraction")
            )
            if not self.is_gemini:
                extra_body = self._with_keep_alive({"format": "json"})
                resp = self.chat_client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": "Return valid JSON only: a flat array of question strings.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=1000,
                    extra_body=extra_body,
                )
                import json as _json
                import re as _re

                raw = resp.choices[0].message.content
                cleaned = self._clean_json(raw)
                match = _re.search(r"\[.*?\]", cleaned, _re.DOTALL)
                if match:
                    return _json.loads(match.group())
                return []
            else:
                from google.genai import types as _gtypes

                resp = self.gemini_client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=_gtypes.GenerateContentConfig(
                        temperature=0.1,
                        response_mime_type="application/json",
                        thinking_config=types.ThinkingConfig(
                            thinking_budget=0,
                        ),
                    ),
                )
                import json as _json

                data = _json.loads(resp.text)
                if isinstance(data, list):
                    return [str(q) for q in data]
                return []
        except Exception as exc:
            logger.warning(f"generate_potential_questions failed for {name}: {exc}")
            return []

    def update_summary(
        self,
        existing_summary: str,
        new_evidence: str,
        entity_name: str,
        entity_type: str,
        related_context: str = "",
    ) -> dict:
        """
        Uses Architect to update Summary AND generate a Short Title.
        Generates ENTITY-ISOLATED, CONTENT-RICH summaries.

        NOTE: The `new_evidence` is already pre-isolated by the LLM extraction phase.
        It should only contain context relevant to this specific entity.

        Args:
            related_context: Optional context from related nodes (for richer summaries)
        """
        # Build related context section if provided
        related_section = ""
        if related_context and related_context.strip():
            related_section = f"""
        Related Context (from connected entities - use for reference only):
        "{related_context}"
        """

        # Benchmark mode uses factual, objective prompts
        if settings.BENCHMARK_MODE:
            format_rules = """### FORMAT RULES
        - Use third-person, objective language (not "you" or "I").
        - Be factual and grounded IN THE PROVIDED CONTEXT ONLY.
        - Do NOT use personal framing or address any user."""
            title_rules = f"""### TITLE RULES
        Generate a short descriptive title (MAX 5 WORDS) for '{entity_name}'."""
        else:
            format_rules = """### FORMAT RULES
        - ADDRESS USER AS "YOU" (not "I" or third person).
        - Be factual and grounded IN THE PROVIDED CONTEXT ONLY."""
            title_rules = f"""### TITLE RULES
        Generate a punchy title (MAX 5 WORDS) capturing '{entity_name}''s role in the user's life."""

        prompt = f"""
        ### SYSTEM INSTRUCTIONS
        You are the LiveOS Core. Update the Knowledge Graph entry for '{entity_name}'.
        The new evidence is RAW isolated context extracted from a note - NOT a pre-written summary.
        
        ### ANTI-HALLUCINATION RULES (ABSOLUTELY CRITICAL)
        ⚠️ NEVER invent, assume, or add information not explicitly present in the inputs below.
        ⚠️ NEVER use your training knowledge to fill in gaps (no external facts, dates, names, numbers).
        ⚠️ If something is unclear or missing, say "details pending" or "not yet known" - DO NOT GUESS.
        ⚠️ ONLY include facts that are EXPLICITLY stated in the Existing Summary, New Evidence, or Related Context.
        ⚠️ If the New Evidence is vague (e.g., "project went well"), keep it vague - don't elaborate.
        
        ### CONTENT RICHNESS RULES (CRITICAL FOR RETRIEVAL QUALITY)
        1. Include ALL relevant details from the provided inputs about '{entity_name}'.
        2. **PRESERVE SPECIFIC FACTS**: dates, numbers, names, positions, titles, outcomes, feelings, decisions.
        3. **NEVER generalize specific details**: "Chief of Protocol" should NOT become "diplomat."
        4. Accumulate knowledge over time - NEVER lose important details from the existing summary.
        5. If new evidence contradicts existing summary, keep both with temporal context if possible.
        6. Write in a way that captures what was ACTUALLY written, not what you think was meant.
        7. If existing summary has general terms and new evidence has specifics, REPLACE with specifics.
           Example: Existing "diplomat" + New "served as Chief of Protocol 1976-1977" → "served as Chief of Protocol 1976-1977"
        
        {title_rules}
        
        {format_rules}

        ### INPUT
        Entity: {entity_name} ({entity_type})
        
        Existing Summary (preserve important details): 
        "{existing_summary}"
        
        New Evidence (RAW isolated context from note about {entity_name}): 
        "{new_evidence}"
        {related_section}
        ### OUTPUT (JSON)
        {{
            "title": "Short Title Here",
            "summary": "Content-rich summary here..."
        }}
        """

        try:
            model = (
                settings.GEMINI_MODEL
                if self.is_gemini
                else self._get_model_for_task("extraction")
            )
            logger.info(f"update_summary calling model: {model}")

            # For Ollama: use raw client to get JSON, then clean and validate manually
            # This avoids Instructor's validation before we can sanitize control characters
            if not self.is_gemini:
                extra_body = self._with_keep_alive({"format": "json"})
                response = self.chat_client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": """You are a JSON-only definition engine. Valid JSON (RFC 8259). 
Example:
{
  "title": "My Title",
  "summary": "My summary."
}
Double-quote all keys. Use straight quotes, not curly quotes.""",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    extra_body=extra_body,
                )
                raw_content = response.choices[0].message.content
                cleaned_json = self._clean_json(raw_content)
                parsed = self.SummaryUpdate.model_validate_json(cleaned_json)
                return {"title": parsed.title, "summary": parsed.summary}
            else:
                # For Gemini: use native SDK with schema enforcement
                response = self.gemini_client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        response_mime_type="application/json",
                        response_schema=self.SummaryUpdate.model_json_schema(),
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                    ),
                )
                import json

                response_data = json.loads(response.text)
                return {
                    "title": response_data.get("title", entity_name),
                    "summary": response_data.get("summary", existing_summary),
                }
        except Exception as e:
            logger.error(f"Summary Update Failed: {e}")
            return {"title": entity_name, "summary": existing_summary}

    async def update_summary_async(
        self,
        existing_summary: str,
        new_evidence: str,
        entity_name: str,
        entity_type: str,
        related_context: str = "",
    ) -> dict:
        """
        Async version of update_summary for batch processing with Gemini.
        Uses Gemini's async client for efficient concurrent requests.

        Args:
            existing_summary: Current comprehensive summary from previous notes
            new_evidence: RAW isolated_context from new note (not pre-summarized)
            entity_name: Entity identifier
            entity_type: Entity/Concept/etc
            related_context: Summaries from related nodes (optional)

        Returns:
            dict with 'title' and 'summary' keys - summary should accumulate ALL facts
        """
        # Build related context section if provided
        related_section = ""
        if related_context and related_context.strip():
            related_section = f"""
        Related Context (from connected entities - use for reference only):
        "{related_context}"
        """

        # Benchmark mode uses factual, objective prompts
        if settings.BENCHMARK_MODE:
            format_rules = """### FORMAT RULES
        - Use third-person, objective language (not "you" or "I").
        - Be factual and grounded IN THE PROVIDED CONTEXT ONLY.
        - Do NOT use personal framing or address any user."""
            title_rules = f"""### TITLE RULES
        Generate a short descriptive title (MAX 5 WORDS) for '{entity_name}'."""
        else:
            format_rules = """### FORMAT RULES
        - ADDRESS USER AS "YOU" (not "I" or third person).
        - Be factual and grounded IN THE PROVIDED CONTEXT ONLY."""
            title_rules = f"""### TITLE RULES
        Generate a punchy title (MAX 5 WORDS) capturing '{entity_name}''s role in the user's life."""

        prompt = f"""
        ### SYSTEM INSTRUCTIONS
        You are the LiveOS Core. Update the Knowledge Graph entry for '{entity_name}'.
        The new evidence is RAW isolated context extracted from a note - NOT a pre-written summary.
        
        ### ANTI-HALLUCINATION RULES (ABSOLUTELY CRITICAL)
        ⚠️ NEVER invent, assume, or add information not explicitly present in the inputs below.
        ⚠️ NEVER use your training knowledge to fill in gaps (no external facts, dates, names, numbers).
        ⚠️ If something is unclear or missing, say "details pending" or "not yet known" - DO NOT GUESS.
        ⚠️ ONLY include facts that are EXPLICITLY stated in the Existing Summary, New Evidence, or Related Context.
        ⚠️ If the New Evidence is vague (e.g., "project went well"), keep it vague - don't elaborate.
        
        ### CONTENT RICHNESS RULES (CRITICAL FOR RETRIEVAL QUALITY)
        1. Include ALL relevant details from the provided inputs about '{entity_name}'.
        2. **PRESERVE SPECIFIC FACTS**: dates, numbers, names, positions, titles, outcomes, feelings, decisions.
        3. **NEVER generalize specific details**: "Chief of Protocol" should NOT become "diplomat."
        4. Accumulate knowledge over time - NEVER lose important details from the existing summary.
        5. If new evidence contradicts existing summary, keep both with temporal context if possible.
        6. Write in a way that captures what was ACTUALLY written, not what you think was meant.
        7. If existing summary has general terms and new evidence has specifics, REPLACE with specifics.
           Example: Existing "diplomat" + New "served as Chief of Protocol 1976-1977" → "served as Chief of Protocol 1976-1977"
        
        {title_rules}
        
        {format_rules}

        ### INPUT
        Entity: {entity_name} ({entity_type})
        
        Existing Summary (preserve important details): 
        "{existing_summary}"
        
        New Evidence (RAW isolated context from note about {entity_name}): 
        "{new_evidence}"
        {related_section}
        ### OUTPUT (JSON)
        {{
            "title": "Short Title Here",
            "summary": "Content-rich summary here..."
        }}
        """

        try:
            model = (
                settings.GEMINI_MODEL
                if self.is_gemini
                else self._get_model_for_task("extraction")
            )
            logger.info(f"update_summary_async calling model: {model}")

            if self.is_gemini:
                # Use Gemini async client for batch processing
                response = await self.gemini_client.aio.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        response_mime_type="application/json",
                        response_schema=self.SummaryUpdate.model_json_schema(),
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                    ),
                )
                import json

                response_data = json.loads(response.text)
                return {
                    "title": response_data.get("title", entity_name),
                    "summary": response_data.get("summary", existing_summary),
                }
            elif self.provider in ["ollama", "lm_studio", "openai"]:
                # Use async OpenAI client for Ollama, LM Studio, and OpenAI batch processing
                response_format = (
                    self._lm_studio_text_response_format()
                    if self.provider == "lm_studio"
                    else {"type": "json_object"}
                )
                response = await self.async_chat_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    extra_body=self._with_keep_alive(
                        {"response_format": response_format}
                    ),
                )
                import json

                response_data = json.loads(response.choices[0].message.content)
                return {
                    "title": response_data.get("title", entity_name),
                    "summary": response_data.get("summary", existing_summary),
                }
            else:
                # Fallback to sync for other providers
                return self.update_summary(
                    existing_summary,
                    new_evidence,
                    entity_name,
                    entity_type,
                    related_context,
                )
        except Exception as e:
            logger.error(f"Async Summary Update Failed for {entity_name}: {e}")
            return {"title": entity_name, "summary": existing_summary}

    def _format_structured_context(self, docs: list[dict], query: str) -> str:
        """
        Unified Fact Pool format - treats all retrieved knowledge as facts to use,
        not sections to summarize. This prevents the LLM from being indirect.

        Labels:
        - [CORE CONSENSUS]: Direct entity/concept matches (distilled knowledge)
        - [SEMANTIC MATCH]: Vector-similar entities (may include aliases, full names)
        - [RELATED CONTEXT]: Expanded neighbors from graph traversal
        - [DOMAIN OVERVIEW]: Community-level summaries for broad context
        - [CONNECTION PATH]: Multi-hop paths showing how entities relate
        """
        parts = ["# KNOWLEDGE RETRIEVED FROM YOUR BRAIN"]
        parts.append("Use the following facts to answer the question directly.\n")

        for d in docs:
            dtype = d.get("type", "unknown")
            text = d.get("text", "")

            if not text:
                continue

            # Label based on type to signal authority level
            # Supports both retrieval.py types (entity_match, vector_match, neighbor_node)
            # and any legacy types (graph_consensus, vector_similar, related_node)
            if dtype in ("entity_match", "graph_consensus"):
                # Primary entity matches - highest authority
                parts.append(f"[CORE CONSENSUS]: {text}")
            elif dtype in ("vector_match", "vector_similar"):
                # Semantic matches - may contain aliases, full names, related entities
                # These are equally important as they catch name variations
                parts.append(f"[SEMANTIC MATCH]: {text}")
            elif dtype in ("neighbor_node", "related_node"):
                # Graph neighbors - supporting context
                parts.append(f"[RELATED CONTEXT]: {text}")
            elif dtype == "community_summary":
                # High-level domain overviews
                parts.append(f"[DOMAIN OVERVIEW]: {text}")
            elif dtype == "multi_hop_path":
                # Paths connecting query entities
                parts.append(f"[CONNECTION PATH]: {text}")
            elif dtype == "note":
                # Raw note snippets (fallback)
                title = d.get("title", "Unknown")
                parts.append(f"[NOTE EXCERPT - {title}]: {text}")
            else:
                # Unknown type - include anyway
                parts.append(f"[CONTEXT]: {text}")

        return "\n\n".join(parts)

    def detect_similarity(
        self,
        name1: str,
        name2: str,
        context1: str = "",
        context2: str = "",
        facts1: str = "",
        facts2: str = "",
    ) -> tuple[bool, float, str]:
        """
        Use LLM to detect the similarity relationship between two entity names.

        Returns a 3-tuple: (has_relationship, confidence, relationship_type).
        relationship_type is a free-text phrase normalized to a Neo4j label, e.g.:
            IS_SHORTENED_TITLE, IS_CANONICAL_NAME_VARIANT, IS_FORMER_TITLE, etc.
        Returns (False, 0.0, "") if no meaningful relationship exists.
        """
        import json

        def _format_facts(facts_json: str) -> str:
            """Parse stored JSON facts (proposition sentences) into readable bullet lines."""
            if not facts_json:
                return ""
            try:
                import json as _j

                items = _j.loads(facts_json)
                if not items:
                    return ""
                lines = [f"  - {f}" for f in items if isinstance(f, str) and f.strip()]
                return "\nKnown facts:\n" + "\n".join(lines) if lines else ""
            except Exception:
                return ""

        ctx1 = (context1 if context1 else "No additional context") + _format_facts(
            facts1
        )
        ctx2 = (context2 if context2 else "No additional context") + _format_facts(
            facts2
        )

        prompt = f"""You are a graph database assistant. Two entity names were flagged as textually similar.

NAME 1: "{name1}"
CONTEXT 1: {ctx1}

NAME 2: "{name2}"
CONTEXT 2: {ctx2}"

What is the relationship between these two names, if any?

Default answer: NONE. Only return a relationship if there is a specific, meaningful connection worth creating as a graph edge.

If a relationship exists, write a short noun phrase (2–5 words) that completes: "NAME 1 is a ______ of NAME 2".
- Return only the core label. No filler words like "is", "a", "the", "of".
- If the two names refer to completely different things that merely share some words, return "none".
- If you are uncertain, return "none".

Respond with ONLY a JSON object:
{{"relationship": "<your label or 'none'>", "confidence": <1.0=obvious, 0.5=plausible, 0.2=speculative>, "reason": "<one sentence>"}}

JSON response:"""

        try:
            # Select model based on provider
            if self.provider in ("ollama", "lm_studio"):
                model = settings.LLM_MODEL
                extra_body = self._with_keep_alive()
            elif self.provider == "openai":
                model = settings.OPENAI_MODEL
                extra_body = {}
            elif self.provider == "gemini":
                model = settings.GEMINI_MODEL
                extra_body = {}
            elif self.provider == "anthropic":
                model = settings.ANTHROPIC_MODEL
                # Anthropic uses different API
                response = self.chat_client.messages.create(
                    model=model,
                    max_tokens=200,
                    messages=[
                        {
                            "role": "user",
                            "content": prompt,
                        }
                    ],
                )
                response_text = response.content[0].text.strip()
            else:
                model = self._get_model_for_task("summarization")
                extra_body = {}

            # Non-Anthropic providers use OpenAI-compatible API
            if self.provider != "anthropic":
                response = self.chat_client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=200,
                    extra_body=extra_body,
                )
                response_text = response.choices[0].message.content.strip()

            # Parse JSON response
            # Handle markdown code blocks
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]

            # Try to extract JSON object from response if it's wrapped in other text
            import re

            json_match = re.search(
                r'\{[^{}]*"relationship"[^{}]*\}', response_text, re.DOTALL
            )
            if json_match:
                response_text = json_match.group(0)

            response_text = response_text.strip()

            result = json.loads(response_text)
            confidence = float(result.get("confidence", 0.0))
            reason = result.get("reason", "")
            relationship_raw = result.get("relationship", "").strip()

            # "none" (or empty) means no edge gets created
            if not relationship_raw or relationship_raw.lower() in (
                "none",
                "no relationship",
                "no",
                "",
            ):
                logger.info(
                    f"[Similarity] {name1} <-> {name2}: none "
                    f"(confidence={confidence:.2f}, reason={reason})"
                )
                return False, 0.0, ""

            # Normalize free-text phrase to a Neo4j relationship label:
            # uppercase, replace non-alphanumeric with _, prefix with IS_
            import re as _re_alias

            label = (
                _re_alias.sub(r"[^A-Za-z0-9]+", "_", relationship_raw.strip())
                .upper()
                .strip("_")
            )
            if not label.startswith("IS_"):
                label = "IS_" + label
            rel_type = label

            logger.info(
                f"[Similarity] {name1} <-> {name2}: {rel_type} "
                f"(confidence={confidence:.2f}, reason={reason})"
            )

            return True, confidence, rel_type

        except json.JSONDecodeError as e:
            logger.warning(f"[Similarity] Failed for {name1} <-> {name2}: {e}")
            logger.debug(
                f"[Similarity] Raw response was: {response_text[:200] if 'response_text' in dir() else 'N/A'}"
            )
            return False, 0.0, ""
        except Exception as e:
            logger.warning(f"[Similarity] Failed for {name1} <-> {name2}: {e}")
            return False, 0.0, ""

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

        best_window = content[:window_size]
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
