#!/usr/bin/env python
"""Quick test script to check LLM extraction"""
from app.services.llm import LLMService
from app.schemas.extraction import Extraction

svc = LLMService()

test_prompt = """
Analyze the following user note and extract structured metadata.

Return a JSON object with:
- summary: A brief summary
- domain: "Personal" or "Professional" or "Academic"
- entities: List of people/things (name, type, importance, isolated_context)
- concepts: List of themes (name, definition, isolated_context)
- tasks: List of actionable items (description, status, due_date)
- persona_traits: List of traits (trait, evidence_quote)
- relationships: Connections between entities
- references: External citations

CONTENT:
"I had lunch with John today. He told me about his new startup called TechVenture. We discussed machine learning applications for healthcare. I need to send him the research paper tomorrow."
"""

print("Calling extraction...")
result = svc.extract_structured(test_prompt, Extraction)
print(f"Result type: {type(result)}")
print(f"Summary: {result.summary}")
print(f"Domain: {result.domain}")
print(f"Entities: {result.entities}")
print(f"Concepts: {result.concepts}")
print(f"Tasks: {result.tasks}")
