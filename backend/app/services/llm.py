import os
import re
import torch
from app.core.config import settings
from app.core.logging_config import get_component_logger
import instructor
from openai import OpenAI
from pydantic import BaseModel

logger = get_component_logger("LLMService")


class LLMService:
    def __init__(self):
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.models_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "../../models")
        )

        # Determine Provider
        if settings.GEMINI_API_KEY:
            logger.info(f"Using Gemini Provider (Model: {settings.GEMINI_MODEL})")
            base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
            api_key = settings.GEMINI_API_KEY
            self.is_gemini = True
        else:
            logger.info(f"Using Local Provider (Ollama: {settings.OLLAMA_BASE_URL})")
            base_url = f"{settings.OLLAMA_BASE_URL}/v1"
            api_key = "ollama"
            self.is_gemini = False

        # 1. Unified Client
        self.extraction_client = instructor.patch(
            OpenAI(
                base_url=base_url,
                api_key=api_key,
                timeout=300.0,
            ),
            mode=instructor.Mode.MD_JSON,
        )

        # 2. Synthesis Client
        self.chat_client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=300.0,
        )

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
        self, prompt: str, response_model: type[BaseModel]
    ) -> BaseModel:
        """
        Uses Architect model with Manual Repair.
        Instructor is bypassed for the outer loop to allow custom string cleanup.
        """

        system_msg = """You are a specialized data extraction agent. Output valid JSON (RFC 8259) matching this schema:
{
  "summary": "Concise summary of note",
  "domain": "Academic|Personal|Professional|Creative",
  "entities": [{"name": "string", "type": "Person|Place|Organization|Tool"}],
  "concepts": ["string"],
  "tasks": [{"description": "string", "status": "string|null", "due_date": "string|null"}],
  "persona_traits": [{"trait": "string", "evidence_quote": "string"}],
  "references": [{"title": "string", "type": "Paper|Book|Quote|Video|Song", "content": "string", "source": "string"}]
}

RULES:
1. NO comments.
2. ALL keys must be double-quoted.
3. NO "OR" options.
4. Return ONLY valid JSON found in the schema.
5. ENGLISH ONLY: Do not use non-English characters."""

        try:
            model = (
                settings.GEMINI_MODEL if self.is_gemini else settings.MODEL_ARCHITECT
            )
            logger.info(f"extract_structured calling model: {model}")
            extra_body = {} if self.is_gemini else {"keep_alive": -1, "format": "json"}

            # We use the raw client to get the string, ignoring instructor's validation loop
            response = self.extraction_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt},
                ],
                max_retries=1,  # We handle retries or just accept 1st attempt with cleanup
                extra_body=extra_body,
            )

            raw_content = response.choices[0].message.content
            cleaned_content = self._clean_json(raw_content)

            # Manual Validation
            return response_model.model_validate_json(cleaned_content)

        except Exception as e:
            logger.error(f"Extraction Failed: {e}")
            if "raw_content" in locals():
                logger.info(f"FAILED RAW CONTENT:\n{raw_content}")
            if "cleaned_content" in locals():
                logger.info(f"FAILED JSON (Cleaned):\n{cleaned_content}")

            # Fallback: Return empty/default if possible or re-raise
            # For now, we return empty to not crash the pipeline
            try:
                return response_model()
            except:
                return None

    def reason(self, prompt: str) -> str:
        """
        Uses the Reasoning Model (phi4-mini-reasoning) for complex logic/refinement.
        Returns raw text (Chain-of-Thought + Answer).
        """
        model = settings.GEMINI_MODEL if self.is_gemini else settings.MODEL_REASONING
        extra_body = {} if self.is_gemini else {"keep_alive": -1}

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

    def generate_title(self, content: str) -> str:
        """
        Generates a short, essence-capturing title for a note.
        """
        model = settings.GEMINI_MODEL if self.is_gemini else settings.MODEL_ARCHITECT
        extra_body = {} if self.is_gemini else {"keep_alive": -1}

        response = self.chat_client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a title generator. Generate a concise (3-6 words), descriptive title that captures the essence of the text. Do not use quotes.",
                },
                {"role": "user", "content": f"Text: {content}\nTitle:"},
            ],
            extra_body=extra_body,
        )
        return response.choices[0].message.content.strip().replace('"', "")

    def summarize(self, text: str) -> str:
        """
        Generates a summary using the 'You' persona.
        STRICT GROUNDING: No outside info.
        """
        model = (
            settings.GEMINI_MODEL if self.is_gemini else settings.MODEL_SUMMARIZATION
        )
        extra_body = {} if self.is_gemini else {"keep_alive": -1}

        response = self.chat_client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a personal knowledge assistant. Summarize the user's note based ONLY on the provided text. Do not add outside information. Keep sentences EXTREMELY short (max 15 words) and simple. Use multiple sentences if needed. Address the user as 'You'. Example: 'You went hiking in Yosemite. You felt small connecting to nature.'",
                },
                {"role": "user", "content": f"Note content:\n{text}\n\nSummary:"},
            ],
            extra_body=extra_body,
        )
        return response.choices[0].message.content.strip()

    async def synthesize(self, context: str, query: str) -> str:
        """
        Uses reasoning model for Synthesis with domain-aware prompting.
        STRICT: No Advice, Only Insights.
        Non-blocking (runs in thread).
        """
        # Detect query domain for tailored system prompt
        query_domain = self._detect_query_domain(query)

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
        Your goal is to provide INSIGHTS by linking the provided notes.
        
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
        {context}
        
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
        return response.choices[0].message.content

    def _detect_query_domain(self, query: str) -> str:
        """
        Heuristic to detect if query is Academic, Personal, Professional, or Creative.
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
            "dream",
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

        academic_score = sum(1 for kw in academic_keywords if kw in query_lower)
        personal_score = sum(1 for kw in personal_keywords if kw in query_lower)
        professional_score = sum(1 for kw in professional_keywords if kw in query_lower)
        creative_score = sum(1 for kw in creative_keywords if kw in query_lower)

        # Return domain with highest score, default to Personal
        max_score = max(academic_score, personal_score, professional_score, creative_score)
        if max_score == 0:
            return "Personal"  # Default

        if academic_score == max_score:
            return "Academic"
        elif professional_score == max_score:
            return "Professional"
        elif creative_score == max_score:
            return "Creative"
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


llm_service = LLMService()
