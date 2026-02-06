import logging
import asyncio

logging.basicConfig(level=logging.INFO)

from app.services.retrieval import RetrievalService
from app.services.graph import GraphService
from app.services.llm import LLMService

rs = RetrievalService()
gs = GraphService()
llm = LLMService()

query = "Were Scott Derrickson and Ed Wood of the same nationality?"
print("Testing entity extraction pipeline...")
print()

# Test _extract_proper_names
proper_names = rs._extract_proper_names(query)
print(f"1. _extract_proper_names: {proper_names}")

# Test full analyze_query
analysis = llm.analyze_query(query)
print(f"2. LLM analyze_query: {analysis}")

# Test the entity merging logic
llm_entities = analysis.get("entities", [])
print(f"3. LLM entities: {llm_entities}")

# Now trace through the full flow
print()
print("4. Full retrieval (get all 16 candidates)...")
results = asyncio.run(rs.hybrid_search(query, top_k=20))  # Get more results
print(f"   Got {len(results)} results")
print()
print("Looking for edward davis wood jr.:")
for i, r in enumerate(results, 1):
    name = r.get("original_obj", {}).get("name", "N/A")
    score = r.get("final_score", 0)
    rtype = r.get("type", "unknown")
    if (
        "edward" in name.lower()
        or "wood" in name.lower()
        or "american" in r.get("text", "").lower()
    ):
        print(f"   #{i}. [{rtype}] {name}: {score:.1f}")
        if "edward" in name.lower():
            print(f'        Text: {r.get("text", "")[:200]}...')
