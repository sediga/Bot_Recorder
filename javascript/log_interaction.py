import os
import json

LOG_FILE = "dataset/selector_logs.jsonl"
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

def log_interaction(data):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        json.dump(data, f)
        f.write("\n")
