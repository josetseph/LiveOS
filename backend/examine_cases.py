import json

# Load results
with open("tests/benchmark/results/hotpotqa_20260218_031731.json", "r") as f:
    results = json.load(f)

print("=" * 70)
print("EXAMINING SPECIFIC TEST CASES")
print("=" * 70)
print()

# Look at cases where we got exact match
exact_matches = [r for r in results['results'] if r['exact_match']]
print(f"EXACT MATCHES: {len(exact_matches)} / {len(results['results'])}")
print()

# Sample 3 exact matches
print("Sample Exact Matches:")
for i, r in enumerate(exact_matches[:3], 1):
    print(f"\n{i}. Question: {r['question']}")
    print(f"   Expected: {r['expected_answer']}")
    print(f"   Got: {r['actual_answer'][:100]}...")
    print(f"   Retrieval Precision: {r['retrieval_precision']:.2%}")

print("\n" + "=" * 70)

# Look at cases with low retrieval precision but correct answer
low_precision_correct = [
    r for r in results['results'] 
    if r['exact_match'] and r['retrieval_precision'] < 0.15
]

print(f"\nEXACT MATCHES WITH LOW RETRIEVAL PRECISION: {len(low_precision_correct)}")
print("(Correct answer despite noisy retrieval)")
print()

if low_precision_correct:
    r = low_precision_correct[0]
    print(f"Example:")
    print(f"  Question: {r['question']}")
    print(f"  Answer: {r['actual_answer'][:80]}... (Expected: {r['expected_answer']})")
    print(f"  Retrieval Precision: {r['retrieval_precision']:.2%}")

print("\n" + "=" * 70)

# Look at F1 scores - need to calculate since not stored
from collections import Counter

print(f"\nEXACT/FUZZY MATCH DISTRIBUTION:")
exact_count = sum(1 for r in results['results'] if r['exact_match'])
fuzzy_count = sum(1 for r in results['results'] if r['fuzzy_match'])
print(f"  Exact: {exact_count} / {len(results['results'])} ({exact_count/len(results['results']):.1%})")
print(f"  Fuzzy: {fuzzy_count} / {len(results['results'])} ({fuzzy_count/len(results['results']):.1%})")

print("\n" + "=" * 70)
print("RETRIEVAL PRECISION ANALYSIS")
print("=" * 70)

retrieval_precisions = [r['retrieval_precision'] for r in results['results']]
print(f"\nRetrieval Precision Distribution:")
print(f"  Average: {sum(retrieval_precisions)/len(retrieval_precisions):.2%}")
print(f"  Good (>0.20): {sum(1 for p in retrieval_precisions if p > 0.20)} cases")
print(f"  Medium (0.10-0.20): {sum(1 for p in retrieval_precisions if 0.10 <= p <= 0.20)} cases")
print(f"  Poor (<0.10): {sum(1 for p in retrieval_precisions if p < 0.10)} cases")

# Compare exact match rate by retrieval precision bucket
high_precision = [r for r in results['results'] if r['retrieval_precision'] > 0.20]
low_precision = [r for r in results['results'] if r['retrieval_precision'] < 0.10]

if high_precision:
    high_em = sum(1 for r in high_precision if r['exact_match']) / len(high_precision)
    print(f"\nExact Match Rate:")
    print(f"  High retrieval precision (>0.20): {high_em:.1%} ({len(high_precision)} cases)")

if low_precision:
    low_em = sum(1 for r in low_precision if r['exact_match']) / len(low_precision)
    print(f"  Low retrieval precision (<0.10): {low_em:.1%} ({len(low_precision)} cases)")
