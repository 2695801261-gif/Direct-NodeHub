import json
from .collector import collect

if __name__ == "__main__":
    result = collect()
    print(json.dumps({
        "total_candidates": result["total_candidates"],
        "sources": result["sources"],
        "output": "public/candidates.json"
    }, ensure_ascii=False, indent=2))
