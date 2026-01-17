from rerankers import Reranker
import traceback

model_path = "/Users/joey/Projects/LiveOS/backend/models/mxbai-rerank-large-v2-seq-cls"
print(f"Attempting to load Seq-Cls Reranker from: {model_path}")

try:
    # Try loading as a standard cross-encoder (Sequence Classification)
    ranker = Reranker(
        model_path, 
        model_type="cross-encoder", 
        device="mps",
        dtype="float32",
        verbose=1
    )
    print("SUCCESS: Reranker loaded as Cross-Encoder")
    print(f"Ranker Class: {type(ranker)}")
    
    # FIX: Qwen tokenizer needs pad_token set manually for batching
    if ranker.tokenizer.pad_token is None:
        ranker.tokenizer.pad_token = ranker.tokenizer.eos_token
        ranker.tokenizer.pad_token_id = ranker.tokenizer.eos_token_id
        print("Fixed: Set pad_token to eos_token")
    
    # Test scoring
    query = "fruit"
    docs = ["apple", "car"]
    results = ranker.rank(query, docs)
    print("\n--- Scoring ---")
    for res in results:
        print(f"Doc: {res.text} | Score: {res.score}")
        
except Exception as e:
    print("\nFAILURE: Could not load reranker")
    print(f"Error: {e}")
    traceback.print_exc()
