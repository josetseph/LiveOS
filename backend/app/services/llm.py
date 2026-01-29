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
        Also strips markdown code blocks pre-repair.
        """
        # 1. Unwrap markdown (Common failure mode)
        if "```" in json_str:
            match = re.search(r"```(?:json)?(.*?)```", json_str, re.DOTALL)
            if match:
                json_str = match.group(1)

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

        return response_model.model_validate_json(response.choices[0].message.content)

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

                analysis = QueryAnalysis.model_validate_json(
                    response.choices[0].message.content
                )
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
        # SYSTEM INSTRUCTIONS
        You are the User's "Second Brain" and intelligent personal assistant.
        Your goal is to provide INSIGHTS by linking graph consensus summaries and supporting notes.
        
        {domain_instructions}
        
        # CRITICAL CONSTRAINTS (VIOLATION = FAILURE)
        1. **NO ADVICE OR SUGGESTIONS**: NEVER tell the user what they "should", "must", "need to", or "have to" do.
           - FORBIDDEN: "You should focus on X", "You need to address Y", "will be crucial to Z"
           - ALLOWED: "You expressed concern about X", "You mentioned wanting to improve Y"
        
        2. **NO FOLLOW-UP QUESTIONS**: Do not ask if you should "delve deeper", "explore further", or help with anything else.
           - FORBIDDEN: "Do you want me to...", "Should I dive deeper into...", "Would you like help with..."
           - Simply answer the question and stop.
        
        3. **ONLY INSIGHTS**: Connect dots between notes (e.g., "Your desire for X conflicts with your fear of Y").
        
        4. **STRICT GROUNDING**: Use ONLY the provided CONTEXT. If the answer is not in the notes, say "I do not have enough information in your notes to answer that."
        
        5. **PERSONA**: Address user as "You".
        
        6. **CITATIONS**: Reference note titles when stating facts.
        
        7. **SUMMARY FORMAT**: If you include a summary/takeaway, make it a factual observation, NOT advice:
           - FORBIDDEN: "You need to address your emotional challenges to succeed."
           - ALLOWED: "Your notes reveal a pattern of ambition paired with uncertainty about direction."
        
        # CONTEXT
        {structured_context_str}
        
        # USER QUESTION
        {query}
        
        # YOUR ANSWER
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
        """
        prompt = f"""
        ### SYSTEM INSTRUCTIONS
        You are the LiveOS Core. Your goal is to update the Knowledge Graph summary and title for '{entity_name}'.
        
        ### RULES
        1. **Title**: Generate a concise, punchy title (MAX 5 WORDS) that captures the essence of this entity's role in the user's life.
           - Example: "Career Ambitions", "Fitness Goals", "Project Alpha".
        2. **Summary**: Update the summary with new evidence.
           - ADDRESS USER AS "YOU".
           - Omit chores/health unless relevant.
           - Keep it grounded.

        ### INPUT
        Entity: {entity_name} ({entity_type})
        Existing Summary: "{existing_summary}"
        New Note Context: "{new_evidence}"
        
        ### OUTPUT (JSON)
        {{
            "title": "Short Title Here",
            "summary": "Updated summary string here..."
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
        Organizes docs into:
        1. Mind (Concepts/Tasks)
        2. Evidence (Linked Notes)
        3. Anchor (Recent Notes)

        Applies Smart Snippet Extraction to notes.
        """
        # 1. Separate by Type
        mind_nodes = [d for d in docs if d.get("type") == "graph_consensus"]
        # Recent notes = anchor, older notes = evidence
        anchor_notes = [
            d for d in docs if d.get("type") == "note" and d.get("is_recent", False)
        ]
        evidence_notes = [
            d for d in docs if d.get("type") == "note" and not d.get("is_recent", False)
        ]

        parts = []

        # SECTION 1: THE MIND
        if mind_nodes:
            parts.append("### SECTION 1: KNOWLEDGE GRAPH (The Mind)")
            parts.append("High-level concepts and tasks related to the query:")
            for d in mind_nodes:
                node_text = d.get("text")
                parts.append(f"- {node_text}")

                # Add related nodes if available (from relationship enrichment)
                related_nodes = d.get("related_nodes", [])
                if related_nodes:
                    parts.append("  Related:")
                    for rn in related_nodes:
                        rel_path = " → ".join(rn.get("relationship_path", []))
                        rel_summary = rn.get("summary", "")[
                            :100
                        ]  # Truncate to 100 chars
                        parts.append(
                            f"    • {rn.get('name')} ({rn.get('label')}) [{rel_path}]: {rel_summary}"
                        )
            parts.append("")

        # SECTION 2: EVIDENCE (Linked Details)
        if evidence_notes:
            parts.append("### SECTION 2: LINKED EVIDENCE (Specific Details)")
            parts.append(
                "Key excerpts from notes directly linked to the above concepts:"
            )
            for d in evidence_notes:
                # Use 'text' field which contains the actual snippet from retrieval
                snippet = d.get("text", "")
                if snippet:
                    parts.append(f"- [From Note: {d.get('title')}]: {snippet}")
            parts.append("")

        # SECTION 3: ANCHOR (Recent Context)
        if anchor_notes:
            parts.append("### SECTION 3: RECENT CONTEXT (The Anchor)")
            parts.append("Snippets from your most recent notes:")
            for d in anchor_notes:
                # Use 'text' field which contains the actual snippet from retrieval
                snippet = d.get("text", "")
                if snippet:
                    parts.append(f"- [From Note: {d.get('title')}]: {snippet}")
            parts.append("")

        return "\n".join(parts)

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
