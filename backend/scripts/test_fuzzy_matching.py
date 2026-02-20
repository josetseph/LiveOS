#!/usr/bin/env python3
"""Test the fuzzy matching logic to see why bad matches occur."""

import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.services.graph import graph_service

# Test the FIXED fuzzy matching query
query = """
MATCH (n:Entity)
WHERE n.name <> $value
  AND n.type = $type
  AND NOT EXISTS {
    MATCH (source:Entity {name: $value})
    MATCH (source)-[]-(n)
  }
  AND (
    // Very close Levenshtein distance (1-2 char difference)
    apoc.text.distance(toLower(n.name), toLower($value)) <= 2
    OR
    // One name fully contains the other (min 4 chars to avoid noise)
    (
      size($value) >= 4 AND size(n.name) >= 4 AND
      (
        toLower(n.name) CONTAINS toLower($value)
        OR toLower($value) CONTAINS toLower(n.name)
      )
    )
    OR
    // Multi-word names with same first initial and significant word overlap
    (
      size(split(n.name, ' ')) > 1 
      AND size(split($value, ' ')) > 1
      AND substring(toLower(n.name), 0, 1) = substring(toLower($value), 0, 1)
      AND size([word IN split(toLower(n.name), ' ') WHERE word IN split(toLower($value), ' ') AND size(word) > 2]) >= 1
    )
  )
WITH n, apoc.text.distance(toLower(n.name), toLower($value)) as distance
RETURN n.name as name,
       distance,
       // Which condition matched?
       (distance <= 2) as levenshtein_match,
       (size($value) >= 4 AND size(n.name) >= 4 AND toLower(n.name) CONTAINS toLower($value)) as contains_in_candidate,
       (size($value) >= 4 AND size(n.name) >= 4 AND toLower($value) CONTAINS toLower(n.name)) as contains_in_value,
       (size(split(n.name, ' ')) > 1 AND size(split($value, ' ')) > 1 AND substring(toLower(n.name), 0, 1) = substring(toLower($value), 0, 1)) as multi_word_match
ORDER BY distance ASC
LIMIT 10
"""

params = {"value": "gamba", "type": "Anonymous"}

print("Testing fuzzy match for 'gamba' (type: Anonymous)")
print("=" * 80)

results = graph_service.execute_query(query, params)

for r in results:
    print(f"\nCandidate: '{r['name']}'")
    print(f"  Distance: {r['distance']}")
    print(f"  Matched by:")
    if r["levenshtein_match"]:
        print(f"    ✓ Levenshtein (distance <= 2)")
    if r["contains_in_candidate"]:
        print(f"    ✓ Candidate contains value")
    if r["contains_in_value"]:
        print(f"    ✓ Value contains candidate")
    if r["multi_word_match"]:
        print(f"    ✓ Multi-word with shared words")

    if not any(
        [
            r["levenshtein_match"],
            r["contains_in_candidate"],
            r["contains_in_value"],
            r["multi_word_match"],
        ]
    ):
        print(f"    ⚠️  NO MATCH CONDITIONS MET - This is a bug!")

print("\n" + "=" * 80)
