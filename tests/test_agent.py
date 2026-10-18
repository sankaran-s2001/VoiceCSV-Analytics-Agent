"""Tests for AnalyticsAgent: SQL extraction, safety validation, and bounded self-healing."""

import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.db_engine import DatabaseEngine
from backend.agent import (
    AnalyticsAgent,
    extract_clean_sql,
    validate_sql_safety
)


def test_extract_clean_sql():
    # Plain SQL
    assert extract_clean_sql("SELECT * FROM uploaded_data") == "SELECT * FROM uploaded_data"
    
    # Markdown code fence with sql tag
    fenced = "```sql\nSELECT category, SUM(sales) FROM uploaded_data GROUP BY category;\n```"
    assert extract_clean_sql(fenced) == "SELECT category, SUM(sales) FROM uploaded_data GROUP BY category"

    # Markdown code fence without tag
    fenced_no_tag = "```\nSELECT * FROM uploaded_data;\n```"
    assert extract_clean_sql(fenced_no_tag) == "SELECT * FROM uploaded_data"

    # Backticks or whitespace
    assert extract_clean_sql(" `SELECT 1` ") == "SELECT 1"

    # Refined question prefix followed by SQL tag
    with_refined = (
        "REFINED_QUESTION: What are the top 5 product categories by revenue in USD?\n"
        "SQL:\n"
        "SELECT category, SUM(sales) FROM sales_transactions WHERE currency = 'USD' GROUP BY category LIMIT 5;"
    )
    assert extract_clean_sql(with_refined) == "SELECT category, SUM(sales) FROM sales_transactions WHERE currency = 'USD' GROUP BY category LIMIT 5"


def test_validate_sql_safety_valid():
    # Standard SELECT
    ok, err = validate_sql_safety("SELECT col1, col2 FROM uploaded_data WHERE col1 > 10")
    assert ok is True
    assert err is None

    # Read-only WITH CTE
    cte = "WITH regional_sales AS (SELECT region, SUM(amount) AS total FROM uploaded_data GROUP BY region) SELECT * FROM regional_sales"
    ok, err = validate_sql_safety(cte)
    assert ok is True
    assert err is None


def test_validate_sql_safety_blocks_prohibited_operations():
    # Empty SQL
    ok, err = validate_sql_safety("")
    assert ok is False

    # Comments
    ok, err = validate_sql_safety("SELECT * FROM uploaded_data -- bypass check")
    assert ok is False
    assert "comment" in err.lower()

    ok, err = validate_sql_safety("SELECT * FROM uploaded_data /* comment */")
    assert ok is False

    # Statement chaining
    ok, err = validate_sql_safety("SELECT 1; DROP TABLE uploaded_data")
    assert ok is False
    assert "multiple" in err.lower()

    # Mutation keywords
    mutations = [
        "DROP TABLE uploaded_data",
        "DELETE FROM uploaded_data",
        "UPDATE uploaded_data SET col1 = 0",
        "INSERT INTO uploaded_data VALUES (1, 2)",
        "ALTER TABLE uploaded_data ADD COLUMN new_col TEXT",
        "ATTACH DATABASE 'leak.db' AS leak",
        "PRAGMA table_info(uploaded_data)",
        "WITH hacked AS (SELECT 1) DELETE FROM uploaded_data",
    ]
    for stmt in mutations:
        ok, err = validate_sql_safety(stmt)
        assert ok is False, f"Expected '{stmt}' to be blocked!"


def test_validate_sql_safety_blocks_unexpected_tables():
    # Must only target uploaded_data
    ok, err = validate_sql_safety("SELECT * FROM sqlite_master")
    assert ok is False
    assert "uploaded_data" in err


@pytest.fixture
def agent_with_test_data(tmp_path):
    db_path = tmp_path / "test_agent.db"
    engine = DatabaseEngine(db_path=db_path)
    csv_data = b"product,category,revenue\nPhone,Electronics,1200\nChair,Furniture,150\nLaptop,Electronics,2400\n"
    engine.ingest_csv(csv_data, "products.csv")
    return AnalyticsAgent(engine=engine)


def test_agent_successful_query(agent_with_test_data):
    agent = agent_with_test_data

    # Mock Gemini model response
    mock_sql = "SELECT category, SUM(revenue) AS total FROM uploaded_data GROUP BY category ORDER BY total DESC"
    with patch.object(agent, "generate_sql", return_value=(mock_sql, 120.0)):
        result = agent.answer_question("What is total revenue by category?")

    assert result["status"] == "success"
    assert result["row_count"] == 2
    assert result["rows"][0] == ["Electronics", 3600]
    assert result["rows"][1] == ["Furniture", 150]
    assert result["heal_attempts"] == 0


def test_agent_self_healing_recovery(agent_with_test_data):
    agent = agent_with_test_data

    # First attempt generates SQL with a typo in column name ("rev_amount")
    broken_sql = "SELECT category, SUM(rev_amount) FROM uploaded_data GROUP BY category"
    # Repaired attempt fixes the column name to "revenue"
    repaired_sql = "SELECT category, SUM(revenue) FROM uploaded_data GROUP BY category"

    with patch.object(agent, "generate_sql", return_value=(broken_sql, 100.0)), \
         patch.object(agent, "repair_sql", return_value=(repaired_sql, 80.0)) as mock_repair:
        result = agent.answer_question("Revenue by category")

    assert mock_repair.call_count == 1
    assert result["status"] == "success"
    assert result["heal_attempts"] == 1
    assert result["sql"] == repaired_sql
    assert result["row_count"] == 2


def test_agent_exceeds_max_repairs(agent_with_test_data):
    agent = agent_with_test_data

    # Model generates persistently broken SQL that fails SQLite execution
    broken_sql = "SELECT non_existent_column FROM uploaded_data"

    with patch.object(agent, "generate_sql", return_value=(broken_sql, 50.0)), \
         patch.object(agent, "repair_sql", return_value=(broken_sql, 50.0)) as mock_repair:
        with pytest.raises(RuntimeError, match="Query execution failed after"):
            agent.answer_question("Bad query")

    # Confirms it tried up to 3 repair attempts and stopped
    assert mock_repair.call_count == 3
