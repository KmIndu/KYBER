"""Quick test: schema3.json through the API pipeline."""
import requests
import json

base = "http://127.0.0.1:8000"

# Upload
with open(r"C:\Users\hat9\OneDrive - Sun Life Financial\Desktop\Jedi\synthetic-data-ai\demo\schema3.json", "rb") as f:
    r = requests.post(f"{base}/upload", files={"files": ("schema3.json", f, "application/json")})

result = r.json()
session_id = result.get("session_id")
files_info = result.get("files", [])
print(f"Upload: {r.status_code}, session={session_id}")
print(f"File type: {files_info[0].get('file_type') if files_info else 'none'}")

# Parse
r2 = requests.post(f"{base}/parse?session_id={session_id}")
print(f"\nParse: {r2.status_code}")
parse_result = r2.json()
tables = parse_result.get("tables", [])
print(f"Tables: {len(tables)}")
if tables:
    print(f"Table: {tables[0].get('name')}, Cols: {tables[0].get('column_count')}")

# Generate
r3 = requests.post(f"{base}/generate?session_id={session_id}&row_count=100")
print(f"\nGenerate: {r3.status_code}")
if r3.status_code == 200:
    gen = r3.json()
    data = gen.get("data", {})
    print(f"Data keys: {list(data.keys())}")
    for tbl, rows in data.items():
        print(f"  {tbl}: {len(rows)} rows")
        if rows:
            print(f"  Columns: {list(rows[0].keys())[:10]}")
            sample = {k: v for k, v in list(rows[0].items())[:6]}
            print(f"  Sample: {json.dumps(sample, default=str)}")
else:
    print(f"Error: {r3.text[:1000]}")
