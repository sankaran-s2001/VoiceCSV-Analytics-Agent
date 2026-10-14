"""Tests for FastAPI REST endpoints: health, file upload, schema, and queries."""

import io
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

from backend.main import app
from backend.db_engine import DatabaseEngine
from backend.config import settings


@pytest.fixture
def client_with_isolated_db(tmp_path, monkeypatch):
    """Fixture providing TestClient backed by an isolated SQLite database."""
    test_db_path = tmp_path / "test_api_analytics.db"
    test_engine = DatabaseEngine(db_path=test_db_path)

    # Patch both global db_engine and settings
    monkeypatch.setattr("backend.main.db_engine", test_engine)
    monkeypatch.setattr("backend.agent.db_engine", test_engine)
    monkeypatch.setattr("backend.main.analytics_agent.engine", test_engine)

    with TestClient(app) as test_client:
        yield test_client, test_engine


def test_health_endpoint(client_with_isolated_db):
    client, _ = client_with_isolated_db
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["dataset_loaded"] is False
    assert data["database_available"] is True


def test_serve_dashboard_and_static_files(client_with_isolated_db):
    client, _ = client_with_isolated_db

    # Root dashboard
    res_index = client.get("/")
    assert res_index.status_code == 200
    assert "VoiceCSV" in res_index.text

    # Static CSS
    res_css = client.get("/css/style.css")
    assert res_css.status_code == 200

    # Static JS
    res_js = client.get("/js/app.js")
    assert res_js.status_code == 200


def test_schema_endpoint_empty(client_with_isolated_db):
    client, _ = client_with_isolated_db
    response = client.get("/api/schema")
    assert response.status_code == 404


def test_upload_invalid_extensions(client_with_isolated_db):
    client, _ = client_with_isolated_db

    # Upload text file
    file_payload = {"file": ("test.txt", io.BytesIO(b"hello world"), "text/plain")}
    res = client.post("/api/upload", files=file_payload)
    assert res.status_code == 400
    assert "csv" in res.json()["detail"].lower()


def test_upload_empty_csv(client_with_isolated_db):
    client, _ = client_with_isolated_db
    file_payload = {"file": ("empty.csv", io.BytesIO(b""), "text/csv")}
    res = client.post("/api/upload", files=file_payload)
    assert res.status_code == 400


def test_upload_valid_csv_and_inspect_schema(client_with_isolated_db):
    client, engine = client_with_isolated_db

    csv_bytes = b"customer,order_total,country\nAlice,120.50,USA\nBob,85.00,Canada\nCharlie,340.20,USA\n"
    file_payload = {"file": ("orders.csv", io.BytesIO(csv_bytes), "text/csv")}
    
    upload_res = client.post("/api/upload", files=file_payload)
    assert upload_res.status_code == 200
    upload_data = upload_res.json()
    assert upload_data["status"] == "success"
    assert upload_data["row_count"] == 3
    assert upload_data["column_count"] == 3
    assert len(upload_data["preview"]) == 3

    # Now verify GET /api/schema returns the loaded dataset
    schema_res = client.get("/api/schema")
    assert schema_res.status_code == 200
    schema_data = schema_res.json()
    assert schema_data["is_loaded"] is True
    assert schema_data["row_count"] == 3
    assert len(schema_data["columns"]) == 3


def test_query_endpoint(client_with_isolated_db, monkeypatch):
    client, engine = client_with_isolated_db

    # Load data first
    csv_bytes = b"dept,budget\nSales,1000\nEngineering,5000\n"
    client.post("/api/upload", files={"file": ("dept.csv", io.BytesIO(csv_bytes), "text/csv")})

    # Ensure Gemini is marked configured for this test
    monkeypatch.setattr(settings, "google_api_key", "AIzaSyValidTestKey123")

    # Mock agent and summarizer methods
    mock_agent_result = {
        "status": "success",
        "question": "Total budget across departments?",
        "sql": "SELECT SUM(budget) AS total_budget FROM uploaded_data",
        "columns": ["total_budget"],
        "rows": [[6000]],
        "row_count": 1,
        "is_capped": False,
        "execution_time_ms": 1.2,
        "sql_generation_time_ms": 145.0,
        "total_time_ms": 146.2,
        "heal_attempts": 0
    }
    mock_summary_result = {
        "summary": "Total department budget is 6,000.",
        "summary_latency_ms": 95.0
    }

    with patch("backend.main.analytics_agent.answer_question", return_value=mock_agent_result), \
         patch("backend.main.executive_summarizer.generate_summary", return_value=mock_summary_result):
        query_res = client.post("/api/query", json={"question": "Total budget across departments?"})

    assert query_res.status_code == 200
    data = query_res.json()
    assert data["status"] == "success"
    assert data["summary"] == "Total department budget is 6,000."
    assert data["rows"] == [[6000]]
    assert data["heal_attempts"] == 0
    assert data["total_time_ms"] > 0
