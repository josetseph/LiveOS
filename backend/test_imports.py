import sys
print("Python:", sys.version)

print("Importing torch...")
import torch
print("Torch imported.")

print("Importing transformers...")
try:
    import transformers
    print("Transformers imported.")
except ImportError as e:
    print(f"Transformers failed: {e}")

print("Importing sklearn...")
try:
    import sklearn
    from sklearn.metrics import roc_curve
    print("Sklearn imported.")
except ImportError as e:
    print(f"Sklearn failed: {e}")

print("Importing paddleocr...")
try:
    from paddleocr import PaddleOCR
    print("PaddleOCR imported.")
except ImportError as e:
    print(f"PaddleOCR failed: {e}")

print("Done.")
