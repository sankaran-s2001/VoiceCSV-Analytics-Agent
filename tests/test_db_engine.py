"""Tests for DatabaseEngine: ingestion, schema reflection, and read-only authorizer."""

import tempfile
import sqlite3
import pytest
from pathlib import Path
from backend.db_engine import DatabaseEngine, normalize_column_name, normalize_column_list


@pytest.fixture
def temp_engine(tmp_path):
    """Create a temporary database engine with an isolated SQLite database."""
    db_path = tmp_path / "test_analytics.db"
    return DatabaseEngine(db_path=db_path)


def test_normalize_column_name():
    assert normalize_column_name("Customer ID") == "customer_id"
    assert normalize_column_name("Product Category") == "product_category"
    assert normalize_column_name("Total Sales ($)") == "total_sales"
    assert normalize_column_name("Order-Date") == "order_date"
    assert normalize_column_name("123Count") == "col_123count"
    assert normalize_column_name("   ") == "col"
    assert normalize_column_name("") == "col"
    assert normalize_column_name(None) == "col"


def test_normalize_column_list():
    raw_cols = ["Sales", "Sales", "Sales", "Customer Name", "123", "", "Sales"]
    norm = normalize_column_list(raw_cols)
    assert norm == ["sales", "sales_2", "sales_3", "customer_name", "col_123", "col_6", "sales_4"]
    # Ensure all names are unique
    assert len(norm) == len(set(norm))


def test_ingest_valid_csv(temp_engine):
    csv_data = b"product,price,quantity\nWidget,19.99,10\nGadget,29.99,5\n"
    res = temp_engine.ingest_csv(csv_data, "test.csv")

    assert res["status"] == "success"
    assert res["row_count"] == 2
    assert res["column_count"] == 3
    assert temp_engine.has_active_dataset() is True

    schema = temp_engine.get_schema_info()
    assert schema["is_loaded"] is True
    assert schema["row_count"] == 2
    col_names = [c["name"] for c in schema["columns"]]
    assert col_names == ["product", "price", "quantity"]


def test_ingest_empty_or_invalid_csv(temp_engine):
    # Completely empty file
    with pytest.raises(ValueError, match="empty"):
        temp_engine.ingest_csv(b"", "empty.csv")

    # Only header, no data rows
    with pytest.raises(ValueError, match="empty"):
        temp_engine.ingest_csv(b"col1,col2\n", "no_rows.csv")


def test_failed_upload_preserves_previous_dataset(temp_engine):
    """Critical: If a second upload fails, the initial valid dataset must remain intact."""
    csv_valid = b"id,val\n1,100\n2,200\n"
    temp_engine.ingest_csv(csv_valid, "initial.csv")
    assert temp_engine.get_schema_info()["row_count"] == 2

    # Attempt to upload an invalid/empty file
    with pytest.raises(ValueError):
        temp_engine.ingest_csv(b"", "broken.csv")

    # Verify previous dataset still exists and is untouched!
    schema = temp_engine.get_schema_info()
    assert schema["is_loaded"] is True
    assert schema["row_count"] == 2
    assert schema["filename"] == "initial.csv"


def test_readonly_execution_select(temp_engine):
    csv_data = b"category,revenue\nTech,500.5\nBooks,150.0\nTech,350.0\n"
    temp_engine.ingest_csv(csv_data, "sales.csv")

    query = "SELECT category, ROUND(SUM(revenue), 2) as total FROM uploaded_data GROUP BY category ORDER BY total DESC"
    result = temp_engine.execute_query_readonly(query)

    assert result["columns"] == ["category", "total"]
    assert len(result["rows"]) == 2
    assert result["rows"][0] == ["Tech", 850.5]
    assert result["rows"][1] == ["Books", 150.0]
    assert result["execution_time_ms"] >= 0


def test_readonly_authorizer_blocks_mutations(temp_engine):
    csv_data = b"id,val\n1,10\n2,20\n"
    temp_engine.ingest_csv(csv_data, "data.csv")

    # Test DROP TABLE
    with pytest.raises(sqlite3.DatabaseError):
        temp_engine.execute_query_readonly("DROP TABLE uploaded_data")

    # Test DELETE
    with pytest.raises(sqlite3.DatabaseError):
        temp_engine.execute_query_readonly("DELETE FROM uploaded_data")

    # Test UPDATE
    with pytest.raises(sqlite3.DatabaseError):
        temp_engine.execute_query_readonly("UPDATE uploaded_data SET val = 0")

    # Test INSERT
    with pytest.raises(sqlite3.DatabaseError):
        temp_engine.execute_query_readonly("INSERT INTO uploaded_data (id, val) VALUES (3, 30)")

    # Verify data is still intact!
    res = temp_engine.execute_query_readonly("SELECT COUNT(*) FROM uploaded_data")
    assert res["rows"][0][0] == 2


def test_output_capping(temp_engine):
    # Create dataset with 20 rows
    rows_csv = "id,score\n" + "\n".join(f"{i},{i*10}" for i in range(20))
    temp_engine.ingest_csv(rows_csv.encode('utf-8'), "scores.csv")

    # Query with max_rows = 5
    result = temp_engine.execute_query_readonly("SELECT * FROM uploaded_data", max_rows=5)
    assert len(result["rows"]) == 5
    assert result["is_capped"] is True
    assert result["max_rows"] == 5


def test_large_dataset_performance(temp_engine):
    """Test performance with 50,000 synthetic rows."""
    import io
    import pandas as pd
    import numpy as np

    n = 50000
    df = pd.DataFrame({
        "id": range(n),
        "department": np.random.choice(["Finance", "Engineering", "Marketing", "Sales"], size=n),
        "salary": np.random.uniform(50000, 150000, size=n).round(2)
    })
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    
    res = temp_engine.ingest_csv(buf.getvalue(), "large_dataset.csv")
    assert res["row_count"] == n

    query = "SELECT department, COUNT(*) as headcount, ROUND(AVG(salary), 2) as avg_salary FROM uploaded_data GROUP BY department"
    q_res = temp_engine.execute_query_readonly(query)
    assert len(q_res["rows"]) == 4
    assert q_res["execution_time_ms"] < 2000  # SQLite aggregation should be very fast
