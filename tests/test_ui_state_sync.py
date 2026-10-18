"""Tests for UI layout stability and relational table state synchronization.

Verifies:
1. /api/schema returns table-specific metadata in relational mode.
2. Switching table via ?table= parameter updates row_count, column_count, columns, and preview.
3. CSS stylesheet maintains critical layout stability rules (minmax(0, 1fr), flex-wrap on pipeline, word-break).
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.db_engine import db_engine
from backend.config import PROJECT_ROOT

client = TestClient(app)


def test_schema_endpoint_relational_active_table():
    """Verify that /api/schema returns table-specific metadata for the active dataset."""
    # Ensure bundled relational sample is loaded
    if not db_engine.has_active_dataset() or db_engine.get_active_workspace_mode() != "relational":
        res_sample = client.post("/api/load-sample-relational")
        assert res_sample.status_code == 200

    # Default /api/schema
    res = client.get("/api/schema")
    assert res.status_code == 200
    data = res.json()
    assert data["workspace_mode"] == "relational"
    assert data["table_name"] in ["customers", "sales_transactions"]
    assert data["row_count"] > 0
    assert data["column_count"] > 0
    assert len(data["columns"]) == data["column_count"]
    assert len(data["preview"]) > 0


def test_schema_endpoint_table_switching():
    """Verify that querying /api/schema?table=... switches metadata correctly."""
    # Ensure relational mode
    if not db_engine.has_active_dataset() or db_engine.get_active_workspace_mode() != "relational":
        client.post("/api/load-sample-relational")

    # 1. Switch to customers
    res_cust = client.get("/api/schema?table=customers")
    assert res_cust.status_code == 200
    data_cust = res_cust.json()
    assert data_cust["table_name"] == "customers"
    assert data_cust["row_count"] == 19858
    assert data_cust["column_count"] == 8
    assert len(data_cust["preview"]) == 5

    # 2. Switch to products
    res_prod = client.get("/api/schema?table=products")
    assert res_prod.status_code == 200
    data_prod = res_prod.json()
    assert data_prod["table_name"] == "products"
    assert data_prod["row_count"] == 1000
    assert data_prod["column_count"] == 6
    assert len(data_prod["preview"]) == 5

    # 3. Switch to stores
    res_stores = client.get("/api/schema?table=stores")
    assert res_stores.status_code == 200
    data_stores = res_stores.json()
    assert data_stores["table_name"] == "stores"
    assert data_stores["row_count"] == 5
    assert data_stores["column_count"] == 2
    assert len(data_stores["preview"]) == 5


def test_css_layout_invariants():
    """Verify that style.css includes critical layout anti-shift and overflow prevention rules."""
    css_path = PROJECT_ROOT / "frontend" / "css" / "style.css"
    assert css_path.exists(), "style.css not found"
    css_content = css_path.read_text(encoding="utf-8")

    # Invariant 1: main-content grid column uses minmax(0, 1fr) to prevent track blow-out
    assert "minmax(0, 1fr)" in css_content, "CSS must use minmax(0, 1fr) on main-content grid"

    # Invariant 2: pipeline-steps has flex-wrap to prevent horizontal stretching
    assert "flex-wrap: wrap" in css_content, "Pipeline steps must wrap to fit container"

    # Invariant 3: html, body overflow-x hidden
    assert "overflow-x: hidden" in css_content, "Root overflow-x must be hidden to guard viewport"

    # Invariant 4: rel-table-name uses word-break to prevent table name truncation
    assert "word-break: break-word" in css_content, "Table names must use word-break instead of ellipsis truncation"


def test_transcribe_endpoint_empty_file():
    """Verify /api/transcribe rejects empty audio data with 400 Bad Request."""
    res = client.post("/api/transcribe", files={"file": ("audio.webm", b"", "audio/webm")})
    assert res.status_code == 400
    assert "empty" in res.json()["detail"].lower()


def test_query_endpoint_context_modalities():
    """Verify that /api/query correctly returns raw_question, refined_question, and source."""
    from unittest.mock import patch

    mock_agent_result = {
        "status": "success",
        "question": "top prod usd",
        "raw_question": "top prod usd",
        "refined_question": "What are the top 5 product categories by revenue in USD?",
        "sql": "SELECT category, SUM(sales) FROM sales_transactions WHERE currency = 'USD' GROUP BY category LIMIT 5",
        "columns": ["category", "total_sales"],
        "rows": [["Electronics", 45000]],
        "row_count": 1,
        "is_capped": False,
        "execution_time_ms": 1.2,
        "sql_generation_time_ms": 120.0,
        "total_time_ms": 130.0,
        "heal_attempts": 0
    }
    mock_summary_result = {
        "summary": "Electronics is the top category in USD.",
        "summary_latency_ms": 80.0
    }

    with patch("backend.main.analytics_agent.answer_question", return_value=mock_agent_result), \
         patch("backend.main.executive_summarizer.generate_summary", return_value=mock_summary_result):
        res = client.post("/api/query", json={
            "question": "top prod usd",
            "source": "voice"
        })

    assert res.status_code == 200
    data = res.json()
    assert data["source"] == "voice"
    assert data["raw_question"] == "top prod usd"
    assert data["refined_question"] == "What are the top 5 product categories by revenue in USD?"
    assert data["sql"].startswith("SELECT category")

