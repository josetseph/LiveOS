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
            logger.info(f"Initializing Ollama (URL: {settings.OLLAMA_BASE_URL})")
            base_url = f"{settings.OLLAMA_BASE_URL}/v1"
            api_key = "ollama"

            self.extraction_client = instructor.patch(
                OpenAI(base_url=base_url, api_key=api_key, timeout=300.0),
                mode=instructor.Mode.MD_JSON,
            )
            self.chat_client = OpenAI(base_url=base_url, api_key=api_key, timeout=300.0)
            # Async client for batch processing
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
            # Timeout: 1800 seconds for complex extractions
            self.gemini_client = genai.Client(
                api_key=settings.GEMINI_API_KEY,
                http_options=types.HttpOptions(timeout=1800000),
            )

            # Create a minimal wrapper for backward compatibility with methods that use chat_client
            # This allows verify_alias and other legacy methods to work
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
                            config=types.GenerateContentConfig(temperature=temperature),
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
        Supports: Ollama, OpenAI, Gemini, Anthropic (with fallback).
        """
        try:
            if self.provider == "ollama":
                return self._extract_ollama(prompt, response_model, temperature)
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
        model = settings.MODEL_ARCHITECT
        logger.info(f"[Ollama] Extracting with {model} (schema enforced)")

        extra_body = {
            "keep_alive": -1,
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
        except:
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

    def _extract_gemini(
        self, prompt: str, response_model: Type[BaseModel], temperature: float
    ) -> BaseModel:
        """Gemini extraction with native SDK and JSON schema enforcement."""
        model = settings.GEMINI_MODEL
        logger.info(f"[Gemini] Extracting with {model} (native SDK)")

        try:
            # Use native Google Gen AI SDK with schema
            response = self.gemini_client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    response_mime_type="application/json",
                    response_schema=response_model.model_json_schema(),
                ),
            )

            # Parse the JSON response into the Pydantic model
            import json

            response_data = json.loads(response.text)
            return response_model(**response_data)

        except Exception as e:
            # Handle content filter or parsing errors
            if "PROHIBITED_CONTENT" in str(e) or "content_filter" in str(e).lower():
                logger.warning(f"[Gemini] Content filtered. Returning empty model.")
                return response_model()
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
            # Ollama/OpenAI
            model = (
                settings.MODEL_REASONING
                if self.provider == "ollama"
                else settings.OPENAI_MODEL_REASONING
            )
            extra_body = {"keep_alive": -1} if self.provider == "ollama" else {}

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
            # Ollama/OpenAI
            model = (
                settings.MODEL_SUMMARIZATION
                if self.provider == "ollama"
                else settings.OPENAI_MODEL
            )
            extra_body = {"keep_alive": -1} if self.provider == "ollama" else {}

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
            # Ollama/OpenAI
            model = (
                settings.MODEL_SYNTHESIS
                if self.provider == "ollama"
                else settings.OPENAI_MODEL
            )
            extra_body = {"keep_alive": -1} if self.provider == "ollama" else {}

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
            # Ollama/OpenAI
            model = (
                settings.MODEL_SUMMARIZATION
                if self.provider == "ollama"
                else settings.OPENAI_MODEL
            )
            extra_body = {"keep_alive": -1} if self.provider == "ollama" else {}

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
                        max_output_tokens=max_tokens,
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

            else:  # OpenAI or Ollama
                model = (
                    settings.MODEL_BRAIN
                    if self.provider == "ollama"
                    else settings.OPENAI_MODEL
                )
                extra_body = {"keep_alive": -1} if self.provider == "ollama" else {}

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
        prompt = f"""You are a question analysis expert. Analyze this question and identify what intermediate information you would need to find in a knowledge base to answer it.

IMPORTANT CONTEXT:
- This is a PERSONAL knowledge base containing notes, experiences, learnings, and extracted entities
- Information may be incomplete - we can only answer from what exists in the knowledge base
- Focus on finding the MOST CRITICAL intermediate facts needed
- If the question seems unanswerable without external knowledge, still identify what we'd need if it exists

# QUESTION
{query}

# TASK
Break down the question into a sequence of information needs. Each need should be a specific question that, when answered, provides information needed for the final answer.

CRITICAL RULES:
1. PRESERVE SPECIFICITY: If the question mentions specific names, roles, or attributes, KEEP them in your sub-questions
   - Bad: "Who starred in X?" (too vague)
   - Good: "Who portrayed [character name] in X?" (preserves the specific role)
2. DON'T OVER-DECOMPOSE: If the question already tells you something, don't ask about it again
   - If question says "who played the main character in film X", don't ask "what character did they play"
3. PRESERVE QUESTION TYPE: If the original asks "what city?", don't change it to "is X in a city?" (yes/no)
   - Bad: "Is [person] based in New York?" 
   - Good: "What city in New York is [person] based in?"
4. NO FINAL COMPARISON QUESTIONS: For "Were X and Y both...?" or "Did X and Y share...", DON'T add a final question asking if they match
   - Just ask about each entity separately - the synthesis will handle the comparison
   - Bad: "1. What is X's nationality? 2. What is Y's nationality? 3. Are they the same?"
   - Good: "1. What is X's nationality? 2. What is Y's nationality?"
5. THINK ABOUT DEPENDENCIES: If question B requires info from question A, list A first
   - Example: Must find "who wrote X" before asking "when was [author] born"
6. Use placeholders like [actress], [director], [person], [author] for entities discovered in previous steps
   - These will be filled in with actual names as we retrieve
7. Keep it simple - usually 1-3 information needs (rarely 4+)
   - Single-hop: 1 need (direct fact lookup)
   - Two-hop: 2 needs (find entity, then find fact about entity)
   - Three-hop: 3 needs (rare, only for very complex chains)
8. Return ONLY the list of questions, one per line, numbered

# EXAMPLES

Question: "What university did the founder of Tesla attend?"
Information Needs:
1. Who founded Tesla?
2. What university did [founder] attend?

Question: "Were Marie Curie and Albert Einstein both born in Europe?"  
Information Needs:
1. Where was Marie Curie born?
2. Where was Albert Einstein born?

Question: "The author who wrote 'Pride and Prejudice' lived in what English county?"
Information Needs:
1. Who wrote 'Pride and Prejudice'?
2. What English county did [author] live in?

Question: "What award did the physicist who discovered radioactivity receive?"
Information Needs:
1. Who discovered radioactivity?
2. What award did [physicist] receive?

Question: "When was the film directed by Christopher Nolan released?"
Information Needs:
1. What film did Christopher Nolan direct?
2. When was [film] released?

Now analyze the question above and list the information needs:
"""

        try:
            if self.is_gemini:
                model = settings.GEMINI_MODEL
                response = self.gemini_client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        max_output_tokens=500,
                    ),
                )
                answer = response.text.strip()
            else:
                model = settings.MODEL_BRAIN
                extra_body = {"keep_alive": -1} if self.provider == "ollama" else {}

                response = self.chat_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    extra_body=extra_body,
                )

                answer = response.choices[0].message.content.strip()

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
                # Truncate long texts
                if len(text) > 500:
                    text = text[:500] + "..."
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
                    config=types.GenerateContentConfig(temperature=0.1),
                )
                answer = response.text
            else:
                model = settings.MODEL_BRAIN
                extra_body = {"keep_alive": -1} if self.provider == "ollama" else {}

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
                        max_output_tokens=100,
                    ),
                )
                instruction_text = response.text.strip()
            else:
                model = settings.MODEL_BRAIN
                extra_body = {"keep_alive": -1} if self.provider == "ollama" else {}

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
                        temperature=0.1, max_output_tokens=100
                    ),
                )
                answer = response.text.strip()
            else:
                response = self.chat_client.chat.completions.create(
                    model=settings.MODEL_BRAIN,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=100,
                    extra_body={"keep_alive": -1} if self.provider == "ollama" else {},
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

    async def synthesize(self, top_docs: list[dict], query: str) -> str:
        """
        Uses reasoning model for Synthesis with domain-aware prompting.
        Accepts structured Top Docs (not just string).
        STRICT: No Advice, Only Insights.
        Non-blocking (runs in thread).
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
            prompt = f"""
        # ROLE
        You are a factual question-answering system for benchmark evaluation.
        Answer ONLY using the provided context.
        
        # YOUR PRIMARY TASK
        Answer this EXACT question: "{query}"
        
        CRITICAL: The context may contain information gathered through multiple retrieval steps.
        Some context may be background information (e.g., about movies, relationships, careers).
        Your job is to find the FINAL ANSWER to the original question above.
        
        # REASONING APPROACH
        Think through the question carefully:
        - Identify EXACTLY what is being asked in the original question
        - Find the chain of relevant facts needed to answer it
        - For multi-hop questions:
          * First identify intermediate entities (e.g., "Who played X?" → person name)
          * Then find the final answer about that entity (e.g., "What position did [person] hold?" → the position)
        - For comparisons, extract the specific attribute being compared
        - Determine the answer based on the evidence
        
        # ANSWER FORMAT RULES
        **ABSOLUTELY CRITICAL: Your answer must EXACTLY match what the question asks for.**
        
        Question Analysis:
        - "what government position?" → answer is a POSITION NAME (e.g., "Secretary of State")
        - "what award?" → answer is an AWARD NAME (e.g., "Academy Award")
        - "what city/location?" → answer is a CITY/LOCATION NAME (e.g., "Los Angeles")
        - "what company?" → answer is a COMPANY NAME
        - "what year?" → answer is a YEAR
        - "who [verb]?" → answer is a PERSON NAME
        - "were X and Y...?" → answer is "yes" or "no"
        
        For yes/no questions:
        - Answer "yes" or "no" FIRST, then explain
        - CRITICAL: If both entities share the same attribute, answer "yes"
        - Example: Q: "Were X and Y of the same nationality?" + Both are American → "yes, both are American"
        
        For "what" questions (positions, awards, locations, etc.):
        - Start with the DIRECT ANSWER to what was asked
        - Do NOT answer with a person's name unless the question asks "who"
        - Example: Q: "What position did [person] hold?" → Answer: "Secretary of State" (NOT the person's name)
        - Example: Q: "What city is [person] based in?" → Answer: "Los Angeles" (NOT the person's name)
        - Example: Q: "What award did [person] win?" → Answer: "Nobel Prize" (NOT the person's name)
        
        For multi-hop questions:
        - The context contains intermediate facts (who/what) AND final answer
        - Return the FINAL ANSWER that matches the question type
        - Example: "What award did the actress playing X win?"
          * Context has: (1) Julia Roberts played X, (2) Julia Roberts won Academy Award
          * Answer: "Academy Award" NOT "Julia Roberts"
        - Example: "The founder of X attended what university?"
          * Context has: (1) Steve Jobs founded Apple, (2) Jobs attended Reed College  
          * Answer: "Reed College" NOT "Steve Jobs"
        
        # NAME DISAMBIGUATION (CRITICAL)
        - Match short names to their full biographical entries using profession/context
        - Person A (profession X) = Person A Full Name if both have profession X
        - ALWAYS check labels/professions to distinguish similar names
        - "Jr." and "Sr." ALWAYS indicate different people (father and son)
        - When multiple people share similar names, use the [Consensus - Label] prefix to distinguish
        - Example: [Consensus - Person: Name] (occupation 1) vs [Consensus - Person: Name Sr.] (occupation 2)
        
        # CONSTRAINTS
        - Use ONLY facts from the provided context
        - Answer EXACTLY what the question asks (not related but different information)
        - For multi-hop questions: You MUST connect facts from different parts of the context
          * Example: If one part says "Jane Smith wrote Novel X" and another says "Jane Smith won the Pulitzer Prize",
            you CAN and SHOULD answer "Pulitzer Prize" for "What award did the author of Novel X win?"
          * The answer exists if ALL the connecting facts exist in the context, even if separated
        - ONLY say "The answer is not in the provided context" if you genuinely cannot find the connecting facts
        
        # CONTEXT
        {structured_context_str}
        
        # QUESTION (ANSWER THIS EXACTLY)
        {query}
        
        # ANSWER
        """
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
                    config=types.GenerateContentConfig(temperature=0.1),
                )

            logger.info(f"synthesize calling model: {settings.GEMINI_MODEL}")
            response = await loop.run_in_executor(None, _call_model)
            return response.text
        else:
            model = settings.MODEL_BRAIN
            extra_body = {"keep_alive": -1}

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
            # Ollama/OpenAI
            extra_body = {"keep_alive": -1} if self.provider == "ollama" else {}

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
        if self.provider == "ollama":
            task_models = {
                "extraction": settings.MODEL_ARCHITECT,
                "summarization": settings.MODEL_SUMMARIZATION,
                "reasoning": settings.MODEL_REASONING,
                "brain": settings.MODEL_BRAIN,
            }
            return task_models.get(task, settings.MODEL_ARCHITECT)
        elif self.provider == "openai":
            if task == "reasoning":
                return settings.OPENAI_MODEL_REASONING
            return settings.OPENAI_MODEL
        elif self.provider == "gemini":
            return settings.GEMINI_MODEL
        elif self.provider == "anthropic":
            return settings.ANTHROPIC_MODEL
        return settings.MODEL_ARCHITECT

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
                "title": entity_name,
                "summary": f"Information about {entity_name}.",
            }

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
                settings.GEMINI_MODEL if self.is_gemini else settings.MODEL_ARCHITECT
            )

            if not self.is_gemini:
                extra_body = {"keep_alive": -1, "format": "json"}
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
                    ),
                )
                import json

                response_data = json.loads(response.text)
                return {
                    "title": response_data.get("title", entity_name),
                    "summary": response_data.get(
                        "summary", f"Information about {entity_name}."
                    ),
                }
        except Exception as e:
            logger.error(f"Entity Summary Generation Failed for {entity_name}: {e}")
            return {
                "title": entity_name,
                "summary": f"Information about {entity_name}.",
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
                settings.GEMINI_MODEL if self.is_gemini else settings.MODEL_ARCHITECT
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
                    ),
                )
                import json

                response_data = json.loads(response.text)
                return {
                    "title": response_data.get("title", entity_name),
                    "summary": response_data.get(
                        "summary", f"Information about {entity_name}."
                    ),
                }
            elif self.provider in ["ollama", "openai"]:
                # Use async OpenAI client for Ollama and OpenAI batch processing
                response = await self.async_chat_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    extra_body={"response_format": {"type": "json_object"}},
                )
                import json

                response_data = json.loads(response.choices[0].message.content)
                return {
                    "title": response_data.get("title", entity_name),
                    "summary": response_data.get(
                        "summary", f"Information about {entity_name}."
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
                "title": entity_name,
                "summary": f"Information about {entity_name}.",
            }

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
                settings.GEMINI_MODEL if self.is_gemini else settings.MODEL_ARCHITECT
            )
            logger.info(f"update_summary calling model: {model}")

            # For Ollama: use raw client to get JSON, then clean and validate manually
            # This avoids Instructor's validation before we can sanitize control characters
            if not self.is_gemini:
                extra_body = {"keep_alive": -1, "format": "json"}
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
                settings.GEMINI_MODEL if self.is_gemini else settings.MODEL_ARCHITECT
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
                    ),
                )
                import json

                response_data = json.loads(response.text)
                return {
                    "title": response_data.get("title", entity_name),
                    "summary": response_data.get("summary", existing_summary),
                }
            elif self.provider in ["ollama", "openai"]:
                # Use async OpenAI client for Ollama and OpenAI batch processing
                response = await self.async_chat_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    extra_body={"response_format": {"type": "json_object"}},
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
            if dtype == "graph_consensus":
                # Primary entity matches - highest authority
                parts.append(f"[CORE CONSENSUS]: {text}")
            elif dtype == "vector_similar":
                # Semantic matches - may contain aliases, full names, related entities
                # These are equally important as they catch name variations
                parts.append(f"[SEMANTIC MATCH]: {text}")
            elif dtype == "related_node":
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

    def verify_alias(
        self,
        name1: str,
        name2: str,
        context1: str = "",
        context2: str = "",
    ) -> tuple[bool, float]:
        """
        Use LLM to verify if two entity names refer to the same real-world entity.

        This is used during ingestion to create ALIAS_OF relationships when
        we detect potential aliases (e.g., "Robert Smith" vs "Bob Smith").

        Args:
            name1: First entity name
            name2: Second entity name
            context1: Summary/description of entity1 (if available)
            context2: Summary/description of entity2 (if available)

        Returns:
            Tuple of (is_alias: bool, confidence: float)
        """
        import json

        prompt = f"""Determine if these two names refer to the SAME real-world entity (person, place, organization, etc.).

NAME 1: "{name1}"
CONTEXT 1: {context1 if context1 else "No additional context"}

NAME 2: "{name2}"  
CONTEXT 2: {context2 if context2 else "No additional context"}

CRITICAL RULES:
1. "Sr." and "Jr." ALWAYS indicate DIFFERENT people (father and son)
2. Roman numerals (I, II, III) indicate DIFFERENT people in a family line
3. Context MUST be consistent - same profession, time period, and relationships
4. If contexts describe different professions or time periods, they are DIFFERENT people
5. When in doubt, say DIFFERENT (false positives are worse than false negatives)

SAME PERSON examples:
- "Robert Smith" and "Bob Smith" -> SAME (nickname)
- "Margaret Johnson" and "Margaret Johnson-Williams" -> SAME (married name)
- "William Gates III" and "Bill Gates" -> SAME (nickname, same person despite numeral)

DIFFERENT PERSON examples:
- "John Adams" and "John Adams Jr." -> DIFFERENT (father and son)
- "James Wilson Sr." and "James Wilson" -> DIFFERENT (could be father/son)
- "George Bush" (41st president) and "George Bush" (43rd president) -> DIFFERENT
- "Thomas Anderson" (farmer, 1800s) and "Thomas Anderson" (programmer, 2000s) -> DIFFERENT

Respond with ONLY a JSON object:
{{"is_same_entity": true/false, "confidence": 0.0-1.0, "reason": "brief explanation"}}

JSON response:"""

        try:
            # Select model based on provider
            if self.provider == "ollama":
                model = settings.MODEL_SUMMARIZATION
                extra_body = {"keep_alive": -1}
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
                model = settings.MODEL_SUMMARIZATION
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
                r'\{[^{}]*"is_same_entity"[^{}]*\}', response_text, re.DOTALL
            )
            if json_match:
                response_text = json_match.group(0)

            # Clean up common issues
            response_text = response_text.strip()

            result = json.loads(response_text)
            is_same = result.get("is_same_entity", False)
            confidence = float(result.get("confidence", 0.0))
            reason = result.get("reason", "")

            logger.info(
                f"[Alias Check] {name1} <-> {name2}: "
                f"{'SAME' if is_same else 'DIFFERENT'} "
                f"(confidence={confidence:.2f}, reason={reason})"
            )

            return is_same, confidence

        except json.JSONDecodeError as e:
            logger.warning(f"[Alias Check] Failed for {name1} <-> {name2}: {e}")
            logger.debug(
                f"[Alias Check] Raw response was: {response_text[:200] if 'response_text' in dir() else 'N/A'}"
            )
            # Default to not creating alias if we can't verify
            return False, 0.0
        except Exception as e:
            logger.warning(f"[Alias Check] Failed for {name1} <-> {name2}: {e}")
            # Default to not creating alias if we can't verify
            return False, 0.0

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
