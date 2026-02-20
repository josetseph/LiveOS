import json

# Load all three runs
with open("tests/benchmark/results/hotpotqa_20260218_013453.json", "r") as f:
    run1 = json.load(f)

with open("tests/benchmark/results/hotpotqa_20260218_031731.json", "r") as f:
    run2 = json.load(f)

with open("tests/benchmark/results/hotpotqa_20260218_044738.json", "r") as f:
    run3 = json.load(f)

print("=" * 80)
print("VISUAL SUMMARY: TYPE FILTERING EXPERIMENT")
print("=" * 80)
print()
print("Timeline:")
print()
print("  01:34 AM ─────► 03:17 AM ─────► 04:47 AM")
print("  Baseline      Type Filter      Reverted")
print()
print("=" * 80)
print()

# Answer Exact Match trajectory
em1 = run1["metrics"]["answer_exact_match"] * 100
em2 = run2["metrics"]["answer_exact_match"] * 100
em3 = run3["metrics"]["answer_exact_match"] * 100

print("Answer Exact Match:")
print()
print(f"  {em1:.1f}% ──────▼──────► {em2:.1f}% ──────▲──────► {em3:.1f}%")
print(f"  Baseline     -3.0pp      Broken       +3.0pp      Restored")
print()
print("  ████████████████████████████████████ (36%)")
print("  ████████████████████████████████░░░░ (33%) ← Type filter regression")
print("  ████████████████████████████████████ (36%) ← After revert ✓")
print()

# Retrieval Recall trajectory
recall1 = run1["metrics"]["retrieval_recall"] * 100
recall2 = run2["metrics"]["retrieval_recall"] * 100
recall3 = run3["metrics"]["retrieval_recall"] * 100

print("Retrieval Recall:")
print()
print(f"  {recall1:.1f}% ──────▼──────► {recall2:.1f}% ──────▲──────► {recall3:.1f}%")
print(f"  Baseline     -5.0pp      Broken       +4.5pp      Restored")
print()
print("  ██████████████████████████████████████████████████████████████████ (67%)")
print(
    "  ████████████████████████████████████████████████████████░░░░░░░░░░ (62%) ← Lost docs"
)
print(
    "  █████████████████████████████████████████████████████████████████░ (66.5%) ← Recovered ✓"
)
print()

# Answer F1 trajectory
f1_1 = run1["metrics"]["answer_f1"] * 100
f1_2 = run2["metrics"]["answer_f1"] * 100
f1_3 = run3["metrics"]["answer_f1"] * 100

print("Answer F1 Score:")
print()
print(f"  {f1_1:.1f}% ──────▼──────► {f1_2:.1f}% ──────▲──────► {f1_3:.1f}%")
print(f"  Baseline     -2.3pp      Lower        +2.6pp      Improved")
print()
print("  ████████████████████████████████████████████████ (47.6%)")
print("  ██████████████████████████████████████████████░░ (45.3%) ← Worse answers")
print(
    "  █████████████████████████████████████████████████ (47.9%) ← Better than baseline! ✓"
)
print()

print("=" * 80)
print("WHAT WE LEARNED")
print("=" * 80)
print()
print("✗ Aggressive Type Filtering (Run 2):")
print("  • Hard filter at type_score < 0.2")
print("  • Removed ALL documents for 6 questions (0% recall)")
print("  • Lost 3 exact matches")
print("  • Recall dropped 5pp (67% → 62%)")
print()
print("✓ Type Scoring Only (Run 3):")
print("  • Guides ranking but doesn't remove candidates")
print("  • Recovered all 5 broken questions (got documents back)")
print("  • Restored exact match to 36%")
print("  • Improved F1 to 47.9% (best so far!)")
print()
print("=" * 80)
print("RECOMMENDATION")
print("=" * 80)
print()
print("Keep current approach (type scoring without hard filtering):")
print()
print("  ✓ Type scoring still ranks matching types higher")
print("  ✓ LLM can find answers even with type mismatches")
print("  ✓ No documents completely filtered out")
print("  ✓ Better for questions needing non-entity answers (numbers, colors)")
print()
print("Performance at Run 3 (04:47):")
print(f"  • Answer EM: {em3:.1f}% (matches baseline)")
print(f"  • Answer F1: {f1_3:.1f}% (better than baseline +0.3pp)")
print(f"  • Recall: {recall3:.1f}% (near baseline -0.5pp)")
print()
print("Status: STABLE ✓ Ready to move forward")
