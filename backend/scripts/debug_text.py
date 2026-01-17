import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.text_processing import get_entity_context

text = "I need to clean my room today; it's a mess. Also, Christian Awudey called about the Votex365 project regarding the deadline. I felt tired after the gym."
name = "Christian Awudey"

print(f"Text: {text}")
print(f"Entity: {name}")

ctx_0 = get_entity_context(text, name, window=0)
print(f"Window 0: '{ctx_0}'")

ctx_1 = get_entity_context(text, name, window=1)
print(f"Window 1: '{ctx_1}'")

text2 = "Christian Awudey is here."
ctx_2 = get_entity_context(text2, name, window=0)
print(f"Simple: '{ctx_2}'")
