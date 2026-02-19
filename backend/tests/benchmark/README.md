# LiveOS Benchmark Testing

This directory contains tools for evaluating LiveOS retrieval and answer quality against standardized multi-hop reasoning datasets.

## ⚠️ Important: Benchmark Mode

LiveOS is designed for **personal knowledge management** with prompts that address the user as "You" and build personal narratives. This causes issues when testing with Wikipedia-style benchmark data.

### Enable Benchmark Mode

Before ingesting benchmark data, enable `BENCHMARK_MODE` in your environment:

```bash
# Option 1: Environment variable
export BENCHMARK_MODE=true

# Option 2: In your .env file
BENCHMARK_MODE=true
```

**What Benchmark Mode Does:**
- **Ingestion**: Uses third-person, objective summaries instead of "You did X"
- **Retrieval**: Returns factual answers without personal framing
- **Prompts**: Removes "Second Brain" persona and "peer" language

**When to Use:**
- ✅ Testing with HotpotQA, MuSiQue, or other external datasets
- ✅ Academic evaluation and research benchmarks
- ❌ NOT for personal notes (disable for normal usage)

**After Benchmarking:**
```bash
# Disable benchmark mode for normal usage
unset BENCHMARK_MODE
# or set BENCHMARK_MODE=false in .env
```

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
# Make sure your backend services are running (Neo4j, PostgreSQL)
python ../batch-note-processing/batch_ingest.py tests/benchmark/musique_notes/ # MuSiQue
python ../batch-note-processing/batch_ingest.py tests/benchmark/hotpotqa_notes/ # HotPotQA
```

### Step 2: Run Evaluation

```bash
# With RAGAS metrics (uses local Ollama by default)
python tests/benchmark/evaluate.py --dataset musique --verbose  # MuSiQue
python tests/benchmark/evaluate.py --dataset hotpotqa --verbose  # HotPotQA
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

### RAGAS Metrics (Semantic)
- **Faithfulness**: Is the answer grounded in retrieved context? (no hallucinations)
- **Answer Relevancy**: Is the answer relevant to the question?
- **Answer Correctness**: Semantic similarity to ground truth
- **Context Precision**: Are relevant contexts ranked higher?
- **Context Recall**: Are all relevant contexts retrieved?

## Installation & Configuration

### Basic Evaluation
```bash
pip install httpx tqdm
```

### With RAGAS Metrics (Local LLM - Recommended)
```bash
pip install ragas datasets langchain-ollama

# Ensure Ollama is running with your models
ollama pull gemma3:4b        # For LLM evaluation
ollama pull nomic-embed-text  # For embeddings
```

### With RAGAS Metrics (OpenAI)
```bash
pip install ragas datasets langchain-openai
export OPENAI_API_KEY="your-key"

# Then run with --llm openai flag
python tests/benchmark/evaluate_ragas.py --dataset musique --use-ragas --llm openai
```

### Ollama Configuration

By default, the evaluation uses your local Ollama installation:
- **Base URL**: `http://localhost:11434`
- **LLM Model**: `gemma3:4b` (configurable in evaluate_ragas.py)
- **Embed Model**: `nomic-embed-text`

You can customize these in `evaluate_ragas.py` at the top of the file.

## Research Validation

To validate that Graph-First retrieval outperforms Vector RAG:

1. **Run benchmarks with your system** → Record metrics
2. **Compare with baseline**: Standard RAG systems typically get ~40-50% on HotpotQA
3. **Your hypothesis**: Graph traversal should improve multi-hop questions

### Key Questions to Answer

1. Does `find_paths_between_nodes` successfully connect entities across documents?
2. Are "bridge" type questions (requiring 2 hops) answered better than "comparison" types?
3. How does retrieval recall compare between name-based lookup vs. vector fallback?

## Output Files

After preparation:
```
tests/benchmark/
├── prepare_musique_local.py     # Uses local LongBench MuSiQue data
├── prepare_hotpotqa_local.py    # Uses local LongBench HotpotQA data
├── evaluate_ragas.py            # Evaluation with RAGAS metrics (works for both datasets)
├── musique_notes/               # MuSiQue note files for ingestion
│   ├── musique_0_0.md
│   └── ...
├── musique_test_cases.json      # MuSiQue test cases with questions & answers
├── hotpotqa_notes/              # HotpotQA note files for ingestion
│   ├── hotpotqa_0_0.md
│   └── ...
├── hotpotqa_test_cases.json     # HotpotQA test cases with questions & answers
└── results/                     # Saved evaluation results (auto-generated)
    ├── musique_20240115_143022.json
    └── hotpotqa_20240115_150033.json
```

## Saved Results

Results are automatically saved to `tests/benchmark/results/` with timestamped filenames.
To skip saving, use the `--no-save` flag:

```bash
python tests/benchmark/evaluate_ragas.py --dataset musique --no-save
```

## Tips for Research Paper

1. **Report F1 on HotpotQA** - This is the standard benchmark metric
2. **Break down by question type** - "bridge" vs "comparison" questions
3. **Show retrieval quality** - Not just final answer accuracy
4. **Compare timing** - Your graph traversal vs. embedding all documents
5. **Highlight multi-hop success** - Cases where 3-4 hop paths were correctly found
6. **Compare RAGAS metrics** - Faithfulness and Context Recall are key for RAG systems
