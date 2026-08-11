"""Demo flow test — uploads all 3 sample files and runs the entire pipeline."""
import os

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def demo_dir():
    d = os.path.join(os.path.dirname(__file__), "..", "..", "demo")
    return os.path.abspath(d)


def test_demo_full_pipeline(client, demo_dir):
    """Upload 3 demo files → Parse → Generate → Validate → Download → Summary → Preview."""
    # --- Step 1: Upload all 3 demo files ---
    files = [
        ("files", ("schema.sql", open(os.path.join(demo_dir, "schema.sql"), "rb"), "text/plain")),
        ("files", ("swagger.yaml", open(os.path.join(demo_dir, "swagger.yaml"), "rb"), "text/plain")),
        ("files", ("claims.feature", open(os.path.join(demo_dir, "claims.feature"), "rb"), "text/plain")),
    ]
    r = client.post("/upload", files=files)
    assert r.status_code == 201, r.text
    data = r.json()
    sid = data["session_id"]
    assert len(data["files"]) == 3

    # --- Step 2: Parse ---
    r = client.post(f"/parse?session_id={sid}")
    assert r.status_code == 200, r.text
    p = r.json()
    assert len(p["tables"]) == 7
    assert p["openapi_schemas"] == 5
    assert p["bdd_scenarios"] >= 18

    # --- Step 3: Generate (valid + negative + boundary + duplicates) ---
    r = client.post(
        f"/generate?session_id={sid}&row_count=25"
        "&include_valid=true&include_invalid=true"
        "&include_boundary=true&include_duplicates=true"
    )
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["total_rows"] >= 175  # 25 * 7 tables at minimum
    assert g["negative_cases"] > 0

    # --- Step 4: Validation ---
    v = g["validation"]
    assert v["passed"] >= 170  # nearly all valid rows pass (orchestration may vary slightly)
    assert v["failed"] <= 5

    # --- Step 5: Download all 3 formats ---
    for fmt in ["csv", "json", "sql"]:
        r = client.get(f"/download/{fmt}?session_id={sid}")
        assert r.status_code == 200, f"{fmt}: {r.status_code}"
        assert len(r.content) > 0

    # --- Step 6: Summary ---
    r = client.get(f"/summary?session_id={sid}")
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["tables_parsed"] == 7
    assert s["total_rows"] == g["total_rows"]
    assert len(s["exports"]) == 3

    # --- Step 7: Preview ---
    r = client.get(f"/preview/policies?session_id={sid}&limit=3")
    assert r.status_code == 200, r.text
    prev = r.json()
    assert "policy_id" in prev["columns"]
    assert len(prev["rows"]) == 3
