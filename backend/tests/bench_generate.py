import time
from app.parsers.sql_parser import parse_sql_schema
from app.generators.synthetic_generator import SyntheticDataGenerator
from pathlib import Path

sql = Path("tests/fixtures/sample_schema.sql").read_text()
schema = parse_sql_schema(sql)

for count in [100, 1000, 10000]:
    start = time.perf_counter()
    gen = SyntheticDataGenerator(schema, row_count=count)
    data = gen.generate()
    elapsed = time.perf_counter() - start
    total_rows = sum(len(rows) for rows in data.values())
    print(f"{count:>5} rows/table | {total_rows:>6} total rows | {elapsed:.3f}s")

    cust_ids = {r["customer_id"] for r in data["customers"]}
    pol_ids = {r["policy_id"] for r in data["policies"]}
    claim_ids = {r["claim_id"] for r in data["claims"]}
    fk_ok = all(r["customer_id"] in cust_ids for r in data["policies"])
    fk_ok = fk_ok and all(r["policy_id"] in pol_ids for r in data["claims"])
    fk_ok = fk_ok and all(r["claim_id"] in claim_ids for r in data["payments"])
    emails = [r["email"] for r in data["customers"] if r["email"] is not None]
    uniq_ok = len(emails) == len(set(emails))
    print(f"        FK integrity: {'PASS' if fk_ok else 'FAIL'} | Unique emails: {'PASS' if uniq_ok else 'FAIL'}")
