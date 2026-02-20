import json

# Load both recent results
with open("tests/benchmark/results/hotpotqa_20260218_013453.json", "r") as f:
    run1 = json.load(f)

with open("tests/benchmark/results/hotpotqa_20260218_031731.json", "r") as f:
    run2 = json.load(f)

print("=" * 70)
print("COMPARING TWO RECENT BENCHMARK RUNS")
print("=" * 70)
print()
print(f"Run 1: {run1['timestamp']} (01:34 AM)")
print(f"Run 2: {run2['timestamp']} (03:17 AM)")
print()

print("=" * 70)
print("METRICS COMPARISON")
print("=" * 70)
print()

metrics = [
    ("Answer Exact Match", "answer_exact_match"),
    ("Answer F1", "answer_f1"),
    ("Answer Fuzzy Match", "answer_fuzzy_match"),
    ("Retrieval Precision", "retrieval_precision"),
    ("Retrieval Recall", "retrieval_recall"),
    ("Retrieval F1", "retrieval_f1"),
]

for label, key in metrics:
    val1 = run1["metrics"][key]
    val2 = run2["metrics"][key]
    diff = val2 - val1
    pct_change = (diff / val1 * 100) if val1 > 0 else 0

    arrow = "→"
    if diff > 0.001:
        status = "↑"
    elif diff < -0.001:
        status = "↓"
    else:
        status = "="

    print(f"{label:25s}: {val1:.2%} → {val2:.2%}  ({diff*100:+.1f}pp)  {status}")

print()
print("=" * 70)
print("WHAT CHANGED?")
print("=" * 70)
print()

# Check if answer quality got worse
em_diff = (
    run2["metrics"]["answer_exact_match"] - run1["metrics"]["answer_exact_match"]
) * 100
f1_diff = (run2["metrics"]["answer_f1"] - run1["metrics"]["answer_f1"]) * 100

if em_diff < -1:
    print(f"⚠️  REGRESSION: Answer Exact Match DECREASED by {abs(em_diff):.1f}pp")
    print(f"   From 36% to 33% - lost 3 exact matches")
else:
    print(f"✓  Answer Exact Match stable or improved")

if f1_diff < -1:
    print(f"⚠️  REGRESSION: Answer F1 DECREASED by {abs(f1_diff):.1f}pp")
    print(f"   From 47.6% to 45.3%")
else:
    print(f"✓  Answer F1 stable or improved")

# Check retrieval quality
prec_diff = (
    run2["metrics"]["retrieval_precision"] - run1["metrics"]["retrieval_precision"]
) * 100
recall_diff = (
    run2["metrics"]["retrieval_recall"] - run1["metrics"]["retrieval_recall"]
) * 100

print()
if prec_diff > 0.1:
    print(f"✓  Retrieval Precision improved slightly (+{prec_diff:.1f}pp)")
else:
    print(f"≈  Retrieval Precision essentially unchanged (+{prec_diff:.2f}pp)")

if recall_diff < -1:
    print(f"⚠️  REGRESSION: Retrieval Recall DECREASED by {abs(recall_diff):.1f}pp")
    print(f"   From 67% to 62%")
else:
    print(f"≈  Retrieval Recall stable")

print()
print("=" * 70)
print("ANALYZING SPECIFIC QUESTIONS")
print("=" * 70)
print()

# Compare same questions
changes = []
for i, (r1, r2) in enumerate(zip(run1["results"], run2["results"])):
    if r1["test_id"] == r2["test_id"]:
        if r1["exact_match"] != r2["exact_match"]:
            changes.append(
                {
                    "question": r1["question"],
                    "expected": r1["expected_answer"],
                    "run1_match": r1["exact_match"],
                    "run2_match": r2["exact_match"],
                    "run1_precision": r1["retrieval_precision"],
                    "run2_precision": r2["retrieval_precision"],
                }
            )

if changes:
    print(f"Found {len(changes)} questions where exact match changed:")
    print()

    # Questions that got worse
    worse = [c for c in changes if c["run1_match"] and not c["run2_match"]]
    if worse:
        print(f"REGRESSIONS (was correct, now wrong): {len(worse)}")
        for c in worse[:3]:
            print(f"  - Q: {c['question'][:80]}...")
            print(f"    Expected: {c['expected']}")
            print(
                f"    Precision: {c['run1_precision']:.2%} → {c['run2_precision']:.2%}"
            )
            print()

    # Questions that got better
    better = [c for c in changes if not c["run1_match"] and c["run2_match"]]
    if better:
        print(f"IMPROVEMENTS (was wrong, now correct): {len(better)}")
        for c in better[:3]:
            print(f"  - Q: {c['question'][:80]}...")
            print(f"    Expected: {c['expected']}")
            print(
                f"    Precision: {c['run1_precision']:.2%} → {c['run2_precision']:.2%}"
            )
            print()

print()
print("=" * 70)
print("SUMMARY")
print("=" * 70)
print()

total_diff = em_diff + f1_diff + prec_diff + recall_diff
if total_diff < -5:
    print("⚠️  Overall REGRESSION: Performance got worse in Run 2")
    print("   Changes between runs may have introduced issues")
elif total_diff > 5:
    print("✓  Overall IMPROVEMENT: Performance got better in Run 2")
else:
    print("≈  Overall STABLE: Performance mostly unchanged")
    print("   Differences likely due to randomness or minor changes")

print()
print("Key observations:")
print(f"  • Lost 3 exact matches (36% → 33%)")
print(f"  • F1 score decreased (-2.3pp)")
print(f"  • Recall dropped significantly (67% → 62%)")
print(f"  • Precision improved slightly (+0.2pp)")
print()
print("Hypothesis: Changes may have filtered out some relevant documents,")
print("reducing recall and causing some questions to fail.")
