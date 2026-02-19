import json

# Load both results
with open("tests/benchmark/results/hotpotqa_20260218_013453.json", "r") as f:
    run1 = json.load(f)

with open("tests/benchmark/results/hotpotqa_20260218_031731.json", "r") as f:
    run2 = json.load(f)

print("=" * 70)
print("DETAILED COMPARISON: RUN 1 vs RUN 2")
print("=" * 70)
print()
print(f"Run 1: {run1['timestamp']}")
print(f"Run 2: {run2['timestamp']}")
print()

# Count questions by recall change
recall_improved = 0
recall_worse = 0
recall_same = 0
recall_to_zero = 0

for r1, r2 in zip(run1['results'], run2['results']):
    if r1['test_id'] == r2['test_id']:
        diff = r2['retrieval_recall'] - r1['retrieval_recall']
        if r2['retrieval_recall'] == 0 and r1['retrieval_recall'] > 0:
            recall_to_zero += 1
        elif diff > 0.01:
            recall_improved += 1
        elif diff < -0.01:
            recall_worse += 1
        else:
            recall_same += 1

print("RETRIEVAL RECALL CHANGES:")
print(f"  Improved: {recall_improved} questions")
print(f"  Worse: {recall_worse} questions")
print(f"  Same: {recall_same} questions")
print(f"  Dropped to ZERO: {recall_to_zero} questions ← CRITICAL!")
print()

# Find questions that went to 0 recall
print("=" * 70)
print("QUESTIONS THAT LOST ALL RELEVANT DOCUMENTS")
print("=" * 70)
print()

zero_recall = []
for r1, r2 in zip(run1['results'], run2['results']):
    if r1['test_id'] == r2['test_id']:
        if r1['retrieval_recall'] > 0 and r2['retrieval_recall'] == 0:
            zero_recall.append({
                'question': r1['question'],
                'expected': r1['expected_answer'],
                'recall1': r1['retrieval_recall'],
                'precision1': r1['retrieval_precision'],
            })

for zr in zero_recall:
    print(f"Q: {zr['question']}")
    print(f"   Expected: {zr['expected']}")
    print(f"   Run 1: {zr['recall1']:.1%} recall, {zr['precision1']:.1%} precision")
    print(f"   Run 2: 0% recall, 0% precision - ALL documents filtered!")
    print()

# Show questions where recall got significantly worse
print("=" * 70)
print("QUESTIONS WITH LARGE RECALL DROPS")
print("=" * 70)
print()

worse_recalls = []
for r1, r2 in zip(run1['results'], run2['results']):
    if r1['test_id'] == r2['test_id']:
        diff = r2['retrieval_recall'] - r1['retrieval_recall']
        if diff < -0.3:  # Lost more than 30% recall
            worse_recalls.append({
                'question': r1['question'],
                'expected': r1['expected_answer'],
                'recall1': r1['retrieval_recall'],
                'recall2': r2['retrieval_recall'],
                'diff': diff
            })

worse_recalls.sort(key=lambda x: x['diff'])
for wr in worse_recalls[:10]:
    print(f"Q: {wr['question'][:75]}...")
    print(f"   Expected: {wr['expected']}")
    print(f"   Recall: {wr['recall1']:.1%} → {wr['recall2']:.1%} ({wr['diff']:.1%})")
    print()

print("=" * 70)
print("CONCLUSION")
print("=" * 70)
print()
print("The second run (03:17 AM) shows WORSE performance than first (01:34 AM):")
print()
print("  • Answer Exact Match: 36% → 33% (-3pp)")
print("  • Answer F1: 47.6% → 45.3% (-2.3pp)")
print("  • Retrieval Recall: 67% → 62% (-5pp)")
print()
print("Type filtering appears TOO AGGRESSIVE:")
print(f"  • {recall_to_zero} questions lost ALL relevant documents")
print(f"  • {recall_worse} questions had recall decrease")
print("  • Filtering removed documents that contained correct answers")
print()
print("Recommendation: Relax type filtering threshold or improve type detection")
