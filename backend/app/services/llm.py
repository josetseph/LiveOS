import os
import re
import torch
from app.core.config import settings
from app.core.logging_config import get_component_logger
import instructor
from openai import OpenAI
from pydantic import BaseModel
from typing import Optional, Type

logger = get_component_logger("LLMService")


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

        elif self.provider == "openai":
            if not settings.OPENAI_API_KEY:
                raise ValueError("OPENAI_API_KEY not set in configuration")
            logger.info(f"Initializing OpenAI (Model: {settings.OPENAI_MODEL})")

            self.extraction_client = instructor.patch(
                OpenAI(api_key=settings.OPENAI_API_KEY, timeout=300.0)
            )
            self.chat_client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=300.0)

        elif self.provider == "gemini":
            if not settings.GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY not set in configuration")
            logger.info(f"Initializing Gemini (Model: {settings.GEMINI_MODEL})")

            base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
            self.extraction_client = instructor.patch(
                OpenAI(
                    base_url=base_url, api_key=settings.GEMINI_API_KEY, timeout=300.0
                ),
                mode=instructor.Mode.MD_JSON,
            )
            self.chat_client = OpenAI(
                base_url=base_url, api_key=settings.GEMINI_API_KEY, timeout=300.0
            )

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
        Also strips markdown code blocks and sanitizes control characters.
        """
        # 1. Unwrap markdown (Common failure mode)
        if "```" in json_str:
            match = re.search(r"```(?:json)?(.*?)```", json_str, re.DOTALL)
            if match:
                json_str = match.group(1)

        # 2. Remove control characters (except allowed ones: \n \r \t inside strings are handled by json_repair)
        # This handles \u0000-\u001F that break JSON parsing
        json_str = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", json_str)

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
            entity_count = len(parsed.get("entities", []))
            concept_count = len(parsed.get("concepts", []))
            logger.info(
                f"[Ollama] Raw extraction: {entity_count} entities, {concept_count} concepts"
            )
            if entity_count == 0:
                logger.warning(
                    f"[Ollama] Empty entities. Full JSON: {cleaned_json[:2000]}"
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
        """Gemini extraction with JSON schema enforcement."""
        model = settings.GEMINI_MODEL
        logger.info(f"[Gemini] Extracting with {model} (schema enforced)")

        # Use instructor for Gemini (works well with their API)
        response = self.extraction_client.chat.completions.create(
            model=model,
            response_model=response_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_retries=2,
        )

        return response

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
        if self.provider == "ollama":
            model = settings.MODEL_REASONING
            extra_body = {"keep_alive": -1}
        elif self.provider == "openai":
            model = settings.OPENAI_MODEL_REASONING  # o1-mini for reasoning
            extra_body = {}
        elif self.provider == "gemini":
            model = settings.GEMINI_MODEL
            extra_body = {}
        elif self.provider == "anthropic":
            model = settings.ANTHROPIC_MODEL
            # Anthropic uses different API
            response = self.chat_client.messages.create(
                model=model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        else:
            model = settings.MODEL_REASONING
            extra_body = {}

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
            model = settings.MODEL_SUMMARIZATION
            extra_body = {}

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
        Returns intent, entities, temporal info, etc.
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
                description="Named entities mentioned (people, places, organizations, tools)",
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

        try:
            model = (
                settings.GEMINI_MODEL if self.is_gemini else settings.MODEL_ARCHITECT
            )

            prompt = f"""Analyze this user query and extract structured information:

Query: "{query}"

Extract:
- Intent (search, summarize, compare, explain, list, or recent)
- Whether it's asking for recent/latest/newest content
- Time range if mentioned
- Named entities (people, places, organizations, tools)
- Abstract concepts or topics
- Important keywords
- Whether answer requires recent notes/events
"""

            if self.is_gemini:
                response = self.extraction_client.chat.completions.create(
                    model=model,
                    response_model=QueryAnalysis,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.model_dump()
            else:
                extra_body = {
                    "keep_alive": -1,
                    "format": QueryAnalysis.model_json_schema(),
                }

                response = self.chat_client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    extra_body=extra_body,
                    temperature=0,  # Deterministic analysis
                )

                # Clean markdown code fences from LLM response
                raw_content = response.choices[0].message.content
                cleaned_json = self._clean_json(raw_content)

                analysis = QueryAnalysis.model_validate_json(cleaned_json)
                return analysis.model_dump()

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
            }

    def summarize(self, text: str) -> str:
        """
        Generates a summary using the 'You' persona.
        STRICT GROUNDING: No outside info.
        """
        if not text or not text.strip():
            return "No content provided."

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
                max_tokens=500,
                messages=[
                    {
                        "role": "user",
                        "content": f"You are a personal knowledge assistant. Summarize the user's note based ONLY on the provided text. Keep sentences EXTREMELY short (max 15 words) and simple. Address the user as 'You'. If the note is just a link (e.g. [[...]]) or very short, simply state what it references. Do NOT ask for more content. Example: 'You referenced a meeting about Ceruba.'\n\nNote content:\n{text}\n\nSummary:",
                    }
                ],
            )
            return response.content[0].text.strip()
        else:
            model = settings.MODEL_SUMMARIZATION
            extra_body = {}

        response = self.chat_client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a personal knowledge assistant. Summarize the user's note based ONLY on the provided text. Keep sentences EXTREMELY short (max 15 words) and simple. Address the user as 'You'. If the note is just a link (e.g. [[...]]) or very short, simply state what it references. Do NOT ask for more content. Example: 'You referenced a meeting about Ceruba.'",
                },
                {"role": "user", "content": f"Note content:\n{text}\n\nSummary:"},
            ],
            extra_body=extra_body,
        )
        return response.choices[0].message.content.strip()

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

        model = settings.GEMINI_MODEL if self.is_gemini else settings.MODEL_BRAIN
        extra_body = {} if self.is_gemini else {"keep_alive": -1}

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

    def update_summary(
        self,
        existing_summary: str,
        new_evidence: str,
        entity_name: str,
        entity_type: str,
    ) -> dict:
        """
        Uses Architect to update Summary AND generate a Short Title.
        Generates ENTITY-ISOLATED, CONTENT-RICH summaries.

        NOTE: The `new_evidence` is already pre-isolated by the LLM extraction phase.
        It should only contain context relevant to this specific entity.
        """
        prompt = f"""
        ### SYSTEM INSTRUCTIONS
        You are the LiveOS Core. Update the Knowledge Graph entry for '{entity_name}'.
        The context provided has already been filtered to only include information about this entity.
        
        ### CONTENT RICHNESS RULES (CRITICAL)
        1. This is NOT a brief summary - include ALL relevant details about '{entity_name}'.
        2. Preserve specific facts: dates, numbers, names, outcomes, feelings, decisions.
        3. Accumulate knowledge over time - never lose important details from the existing summary.
        4. If new evidence contradicts existing summary, keep both with temporal context if possible.
        5. Write in a way that captures the FULL picture of this entity in the user's life.
        
        ### TITLE RULES
        Generate a punchy title (MAX 5 WORDS) capturing '{entity_name}''s role in the user's life.
        
        ### FORMAT RULES
        - ADDRESS USER AS "YOU" (not "I" or third person).
        - Be factual and grounded.

        ### INPUT
        Entity: {entity_name} ({entity_type})
        
        Existing Summary (preserve important details): 
        "{existing_summary}"
        
        New Evidence (pre-isolated context about {entity_name}): 
        "{new_evidence}"
        
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
            extra_body = {} if self.is_gemini else {"keep_alive": -1, "format": "json"}

            # We use extraction_client for JSON mode
            response = self.extraction_client.chat.completions.create(
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
Double-quote all keys.""",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_model=self.SummaryUpdate,
                max_retries=2,
                extra_body=extra_body,
            )
            return {"title": response.title, "summary": response.summary}
        except Exception as e:
            logger.error(f"Summary Update Failed: {e}")
            return {"title": entity_name, "summary": existing_summary}

    def _format_structured_context(self, docs: list[dict], query: str) -> str:
        """
        Unified Fact Pool format - treats all retrieved knowledge as facts to use,
        not sections to summarize. This prevents the LLM from being indirect.

        Labels:
        - [CORE CONSENSUS]: Direct entity/concept matches (distilled knowledge)
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
