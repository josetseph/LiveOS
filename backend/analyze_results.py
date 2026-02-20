import json

# Load new results
with open("tests/benchmark/results/hotpotqa_20260218_031731.json", "r") as f:
    new = json.load(f)

# Baseline metrics (from previous session)
baseline = {
    "answer_exact_match": 0.1365,
    "answer_f1": 0.476,
    "retrieval_precision": 0.119,
    "retrieval_recall": 0.62,
    "retrieval_f1": 0.20,
}

print("=" * 70)
print("PERFORMANCE COMPARISON: Baseline → After Type Filtering")
print("=" * 70)
print()

print("ANSWER QUALITY:")
print(
    f"  Exact Match:    {baseline['answer_exact_match']:.2%} → {new['metrics']['answer_exact_match']:.2%}  ({(new['metrics']['answer_exact_match'] - baseline['answer_exact_match']) * 100:+.1f}pp)"
)
print(
    f"  F1 Score:       {baseline['answer_f1']:.2%} → {new['metrics']['answer_f1']:.2%}  ({(new['metrics']['answer_f1'] - baseline['answer_f1']) * 100:+.1f}pp)"
)
print(f"  Fuzzy Match:    N/A → {new['metrics']['answer_fuzzy_match']:.2%}")
print()

print("RETRIEVAL QUALITY:")
print(
    f"  Precision:      {baseline['retrieval_precision']:.2%} → {new['metrics']['retrieval_precision']:.2%}  ({(new['metrics']['retrieval_precision'] - baseline['retrieval_precision']) * 100:+.1f}pp)"
)
print(
    f"  Recall:         {baseline['retrieval_recall']:.2%} → {new['metrics']['retrieval_recall']:.2%}  ({(new['metrics']['retrieval_recall'] - baseline['retrieval_recall']) * 100:+.1f}pp)"
)
print(
    f"  F1 Score:       {baseline['retrieval_f1']:.2%} → {new['metrics']['retrieval_f1']:.2%}  ({(new['metrics']['retrieval_f1'] - baseline['retrieval_f1']) * 100:+.1f}pp)"
)
print()

print("PERFORMANCE:")
print(f"  Avg Response:   {new['metrics']['avg_response_time_ms']:.0f}ms")
print()

print("=" * 70)
print("KEY FINDINGS:")
print("=" * 70)

# Analyze the results
if new["metrics"]["answer_exact_match"] > baseline["answer_exact_match"] * 1.5:
    print("MAJOR IMPROVEMENT: Answer Exact Match increased significantly!")
    print("  More answers are now perfectly correct (+19.5pp)")
else:
    print("Answer Exact Match improved moderately")

if new["metrics"]["answer_f1"] < baseline["answer_f1"]:
    print("WARNING: Answer F1 decreased slightly (-2.3pp)")
    print("  Possible cause: More exact matches but shorter/more precise answers")
else:
    print("Answer F1 improved")

if new["metrics"]["retrieval_precision"] > baseline["retrieval_precision"] * 1.1:
    print("Retrieval Precision improved")
else:
    print("MINIMAL IMPROVEMENT: Retrieval Precision barely changed (+0.2pp)")
    print("  Type filtering may not be removing enough noise in this dataset")

print()

# Count how many candidates were filtered by type
print("=" * 70)
print("TYPE FILTERING ANALYSIS FROM LOGS:")
print("=" * 70)

import re

with open("logs/retrieval.log", "r") as f:
    log_content = f.read()

filtered_matches = re.findall(r"Filtered out (\d+) candidates", log_content)
if filtered_matches:
    filtered_counts = [int(x) for x in filtered_matches]
    total_filtered = sum(filtered_counts)
    avg_filtered = total_filtered / len(filtered_counts)
    print(f"Total queries with filtering: {len(filtered_counts)}")
    print(f"Average candidates filtered per query: {avg_filtered:.1f}")
    print(f"Max filtered in single query: {max(filtered_counts)}")
    print()
else:
    print("No filtering data found in logs")
