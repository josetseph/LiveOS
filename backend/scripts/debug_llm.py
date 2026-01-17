import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.llm import llm_service

entity_name = "Christian Awudey"
entity_type = "Entity"
existing_summary = "None yet."
new_evidence = "Also, Christian Awudey called about the Votex365 project regarding the deadline."

print("🔍 Testing update_summary...")
try:
    summary = llm_service.update_summary(existing_summary, new_evidence, entity_name, entity_type)
    print(f"✅ Result: {summary}")
except Exception as e:
    print(f"❌ Failed: {e}")
