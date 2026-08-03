# Orb Benchmark Testing

Tools for evaluating Orb retrieval and answer quality against multi-hop QA datasets.

Question manifests are checked in. Note bodies are **not** — download and materialize them with `fetch_notes.py` before ingesting.

## Datasets

### HotpotQA (good starting point)
- **What**: Multi-hop Wikipedia QA (2-hop bridge / comparison questions)
- **Bundle**: 100 questions · 990 notes
- **Files**: `hotpotqa_manifest.json` (+ notes from `fetch_notes.py`)
- **Source**: HotpotQA distractor dev set

### MuSiQue (harder)
- **What**: Questions requiring 2–4 hops across documents
- **Bundle**: 50 questions · 526 notes
- **Files**: `musique_manifest.json` (+ notes from `fetch_notes.py`)
- **Source**: LongBench `musique.jsonl`

## Prerequisites

1. Orb API running at `http://localhost:8000` (desktop app or local uvicorn)
2. A clean / dedicated KB recommended so benchmark notes do not mix with personal vault data
3. Network access once, to download dataset sources
4. Python deps: `httpx`, `tqdm` (`pip install httpx tqdm` in the backend venv)

## Quick Start

### Step 0: Fetch notes

```bash
# From backend/ with venv active
python tests/benchmark/fetch_notes.py
# or one dataset:
python tests/benchmark/fetch_notes.py --dataset hotpotqa
python tests/benchmark/fetch_notes.py --dataset musique
```

This downloads HotpotQA / LongBench into `.cache/` (gitignored) and writes markdown into `hotpotqa_notes/` / `musique_notes/` (also gitignored).

### Step 1: Ingest notes

```bash
python tests/benchmark/prepare_dataset.py --dataset hotpotqa
python tests/benchmark/prepare_dataset.py --dataset musique

# Resume after interruption
python tests/benchmark/prepare_dataset.py --dataset hotpotqa --resume

# Retry only failed notes
python tests/benchmark/prepare_dataset.py --dataset hotpotqa --retry-failed

# Preview without sending
python tests/benchmark/prepare_dataset.py --dataset hotpotqa --dry-run

# Limit to a subset for a smoke test
python tests/benchmark/prepare_dataset.py --dataset hotpotqa --limit 10
```

Progress is written to `.prepare_progress.json` (gitignored) so `--resume` / `--retry-failed` work across runs.

Optional full Leiden rebuild after ingestion has gone idle (CLI), or use
`POST /api/v1/admin/rebuild-communities` while the API is running:

```bash
python scripts/run_community_detection.py
```

### Step 2: Run evaluation

```bash
python tests/benchmark/evaluate.py --dataset hotpotqa --verbose
python tests/benchmark/evaluate.py --dataset musique --verbose

python tests/benchmark/evaluate.py --dataset hotpotqa --limit 10 --verbose
python tests/benchmark/evaluate.py --dataset hotpotqa --output /tmp/my_results.json
python tests/benchmark/evaluate.py --dataset hotpotqa --no-save
```

Results default to `results/` (gitignored), timestamped per run.

## Metrics

### Answer quality
- **Exact Match (EM)**: Normalized string equality with ground truth
- **F1**: Token-level overlap (standard SQuAD / HotpotQA metric)
- **Fuzzy Match**: Jaccard similarity ≥ 0.6
- **Contains Answer**: Ground truth appears in the response

### Retrieval quality
- **Precision / Recall / F1**: Overlap between retrieved notes and supporting notes in the manifest

## Directory Structure

```
tests/benchmark/
├── README.md
├── fetch_notes.py           # Download sources + write note markdown
├── prepare_dataset.py       # Ingest notes into Orb
├── evaluate.py              # Score chat answers against a manifest
├── hotpotqa_manifest.json   # HotpotQA questions + note index
└── musique_manifest.json    # MuSiQue questions + note index
```

Local-only (created when you run the tools; not committed):

- `.cache/` — downloaded HotpotQA / LongBench sources
- `hotpotqa_notes/`, `musique_notes/` — materialized markdown
- `.prepare_progress.json` — ingest resume state
- `results/` — evaluation JSON outputs
