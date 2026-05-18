# LiveOS Benchmark Testing

This directory contains tools for evaluating LiveOS retrieval and answer quality against standardized multi-hop reasoning datasets.

## Datasets

### 1. HotpotQA (Recommended Starting Point) ⭐ Local Data Available
- **What**: 113K question-answer pairs requiring multi-hop reasoning
- **Difficulty**: Medium (2-hop reasoning)
- **Best for**: Testing `find_paths_between_nodes` logic
- **Location**: `testing_data/longbeach/data-2/hotpotqa.jsonl`

### 2. MuSiQue (Hard Mode) ⭐ Local Data Available
- **What**: Questions requiring 2-4 hops across documents
- **Difficulty**: Hard (designed to break standard Vector RAG)
- **Best for**: Proving Graph-First architecture advantages
- **Location**: `testing_data/longbeach/data-2/musique.jsonl`

## Quick Start

### Step 1: Ingest Notes

```bash
# From backend/ with venv active
python tests/benchmark/prepare_dataset.py --dataset hotpotqa
python tests/benchmark/prepare_dataset.py --dataset musique

# Resume after interruption
python tests/benchmark/prepare_dataset.py --dataset hotpotqa --resume

# Retry only failed notes
python tests/benchmark/prepare_dataset.py --dataset hotpotqa --retry-failed

# Preview without sending
python tests/benchmark/prepare_dataset.py --dataset hotpotqa --dry-run

# Limit to a subset for quick testing
python tests/benchmark/prepare_dataset.py --dataset hotpotqa --limit 10
```

If you need a full manual community rebuild before evaluation:

```bash
# From backend/ with venv active
python scripts/run_community_detection.py
```

Start community detection only after ingestion has gone idle. Recompute requests are single-flight with superseding semantics — only the newest request proceeds.

### Step 2: Run Evaluation

```bash
# From backend/ with venv active
python tests/benchmark/evaluate.py --dataset hotpotqa --verbose
python tests/benchmark/evaluate.py --dataset musique --verbose

# Limit to a subset
python tests/benchmark/evaluate.py --dataset hotpotqa --limit 10 --verbose

# Custom output path
python tests/benchmark/evaluate.py --dataset hotpotqa --output /tmp/my_results.json

# Skip saving results
python tests/benchmark/evaluate.py --dataset hotpotqa --no-save
```

## Metrics Explained

### Answer Quality
- **Exact Match (EM)**: Answer matches ground truth exactly (after normalization)
- **F1 Score**: ⭐ **Standard QA benchmark metric** - Token-level overlap between predicted and ground truth answers (used in SQuAD, HotpotQA papers)
- **Fuzzy Match**: Answers are similar (Jaccard similarity ≥ 0.6)
- **Contains Answer**: Ground truth appears in the response

### Retrieval Quality
- **Precision**: What % of retrieved notes were relevant?
- **Recall**: What % of relevant notes were retrieved?
- **F1 Score**: Harmonic mean of precision and recall

## Installation

```bash
pip install httpx tqdm
```

The evaluation script (`evaluate.py`) uses only `httpx` and `tqdm` — no additional dependencies required.

## Directory Structure

```
tests/benchmark/
├── prepare_dataset.py           # Ingest notes from a manifest into LiveOS
├── evaluate.py                  # Run evaluation against a manifest
├── hotpotqa_manifest.json       # HotpotQA test cases + note index (100 questions)
├── musique_manifest.json        # MuSiQue test cases + note index (50 questions)
├── hotpotqa_notes/              # HotpotQA note files for ingestion
├── musique_notes/               # MuSiQue note files for ingestion
├── .prepare_progress.json       # Ingestion progress tracker (auto-managed)
└── results/                     # Evaluation results (auto-generated, timestamped)
    └── hotpotqa_20260510_033714.json
```

## Tips for Research Paper

1. **Report F1 on HotpotQA** — standard benchmark metric (SQuAD, HotpotQA papers all use this)
2. **Break down by question type** — "bridge" vs "comparison" questions
3. **Show retrieval quality** — not just final answer accuracy
4. **Compare timing** — graph traversal vs. embedding all documents
5. **Highlight multi-hop success** — cases where 3-4 hop paths were correctly found