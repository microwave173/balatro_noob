import json


with open('in_jsonl.json','r', encoding='utf-8') as f:
    data = json.load(f)

with open('in_jsonl.json','w', encoding='utf-8') as f:
    json.dump(data, f, indent=4, ensure_ascii=False)
