import json, glob

with open("tests/benchmark/results/hop_v4_hotpotqa_20260222_232700.json") as f:
    v4 = {r["id"]: r for r in json.load(f)["results"]}

with open("tests/benchmark/results/hop_v5_hotpotqa_20260223_035441.json") as f:
    v5 = {r["id"]: r for r in json.load(f)["results"]}

print(f"v4 fuzzy: {sum(r['fuzzy_match'] for r in v4.values())}/100")
print(f"v5 fuzzy: {sum(r['fuzzy_match'] for r in v5.values())}/100")
print()

print("=== v4 PASS, v5 FAIL (regressions) ===")
for qid in v4:
    if qid in v5:
        if v4[qid]["fuzzy_match"] and not v5[qid]["fuzzy_match"]:
            r4, r5 = v4[qid], v5[qid]
            print(f"Q: {r4['question']}")
            print(f"  Expected : {r4['expected']}")
            print(f"  v4 answer: {r4['final_answer']}")
            print(f"  v5 answer: {r5['final_answer']}")
            print()

print()
print("=== v5 PASS, v4 FAIL (improvements) ===")
for qid in v4:
    if qid in v5:
        if not v4[qid]["fuzzy_match"] and v5[qid]["fuzzy_match"]:
            r4, r5 = v4[qid], v5[qid]
            print(f"Q: {r4['question']}")
            print(f"  Expected : {r4['expected']}")
            print(f"  v4 answer: {r4['final_answer']}")
            print(f"  v5 answer: {r5['final_answer']}")
            print()
