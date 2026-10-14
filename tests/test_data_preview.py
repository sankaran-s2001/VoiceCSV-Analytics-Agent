"""Unit and Integration Tests for Full Dataset Explorer API (/api/data/preview).

Verifies server-side pagination, bounded page limits, global search across all columns,
safe server-side column sorting, injection defense, and read-only preservation.
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.db_engine import DatabaseEngine


@pytest.fixture
def populated_engine(tmp_path: Path):
    """Provides an isolated SQLite engine populated with deterministic 1,000-row fixture."""
    db_file = tmp_path / "preview_test.db"
    engine = DatabaseEngine(db_path=db_file)
    csv_path = Path("tests/fixtures/sample_1000.csv")
    engine.ingest_csv(csv_path, filename="sample_1000.csv")
    return engine


def test_preview_first_page_and_metadata(populated_engine: DatabaseEngine):
    """Verify first page returns accurate metadata, columns, and 50 rows."""
    res = populated_engine.get_dataset_preview(offset=0, limit=50)

    assert res["status"] == "success"
    assert res["total_rows"] == 1000
    assert res["filtered_total_rows"] == 1000
    assert res["offset"] == 0
    assert res["limit"] == 50
    assert res["returned_rows"] == 50
    assert len(res["rows"]) == 50
    assert res["total_columns"] == 12
    assert res["columns"][0]["name"] == "transaction_id"


def test_preview_pagination_boundaries(populated_engine: DatabaseEngine):
    """Verify subsequent pages, page offsets, and the final page remaining rows."""
    # 1. Page 2 (offset 50, limit 50)
    page2 = populated_engine.get_dataset_preview(offset=50, limit=50)
    assert page2["offset"] == 50
    assert page2["returned_rows"] == 50
    # Ensure rows on page 2 differ from page 1
    page1 = populated_engine.get_dataset_preview(offset=0, limit=50)
    assert page1["rows"][0][0] != page2["rows"][0][0]

    # 2. Final page (offset 950, limit 50)
    page_last = populated_engine.get_dataset_preview(offset=950, limit=50)
    assert page_last["returned_rows"] == 50

    # 3. Beyond boundary (offset 1000, limit 50)
    page_empty = populated_engine.get_dataset_preview(offset=1000, limit=50)
    assert page_empty["returned_rows"] == 0
    assert page_empty["rows"] == []


def test_preview_clamping_and_max_page_size(populated_engine: DatabaseEngine):
    """Verify page limits are clamped between 1 and 200, and negative offsets clamped to 0."""
    # Limit exceeds 200 -> clamped to 200
    res_large = populated_engine.get_dataset_preview(offset=0, limit=500)
    assert res_large["limit"] == 200
    assert res_large["returned_rows"] == 200

    # Negative offset -> clamped to 0
    res_neg = populated_engine.get_dataset_preview(offset=-10, limit=25)
    assert res_neg["offset"] == 0
    assert res_neg["returned_rows"] == 25


def test_preview_column_sorting(populated_engine: DatabaseEngine):
    """Verify server-side ascending and descending sorting on validated columns."""
    # Sort by sales DESC
    res_desc = populated_engine.get_dataset_preview(offset=0, limit=10, sort_by="sales", sort_order="desc")
    assert res_desc["sort_by"] == "sales"
    assert res_desc["sort_order"] == "desc"
    # Verify sales are descending
    sales_col_idx = [i for i, c in enumerate(res_desc["columns"]) if c["name"] == "sales"][0]
    sales_vals = [r[sales_col_idx] for r in res_desc["rows"]]
    assert sales_vals == sorted(sales_vals, reverse=True)

    # Sort by sales ASC
    res_asc = populated_engine.get_dataset_preview(offset=0, limit=10, sort_by="sales", sort_order="asc")
    assert res_asc["sort_order"] == "asc"
    sales_asc_vals = [r[sales_col_idx] for r in res_asc["rows"]]
    assert sales_asc_vals == sorted(sales_asc_vals)

    # Invalid sort column rejected
    with pytest.raises(ValueError, match="Invalid sort column"):
        populated_engine.get_dataset_preview(offset=0, limit=10, sort_by="evil_nonexistent_column")


def test_preview_global_search(populated_engine: DatabaseEngine):
    """Verify global search across all columns finds matches outside the first page and filters count."""
    # Search for a customer code that occurs on multiple rows
    search_term = "CUST-002"
    res_search = populated_engine.get_dataset_preview(offset=0, limit=50, search=search_term)

    assert res_search["filtered_total_rows"] > 0
    assert res_search["filtered_total_rows"] < res_search["total_rows"]
    assert res_search["search"] == search_term

    # Verify every returned row contains the search term in at least one column
    for row in res_search["rows"]:
        assert any(search_term in str(cell) for cell in row)

    # Non-matching search returns 0 rows
    res_zero = populated_engine.get_dataset_preview(offset=0, limit=50, search="XYZ999NONEXISTENT")
    assert res_zero["filtered_total_rows"] == 0
    assert res_zero["returned_rows"] == 0
    assert res_zero["rows"] == []


def test_preview_search_injection_safety(populated_engine: DatabaseEngine):
    """Verify search input containing quotes, semicolons, and wildcards is safely escaped and parameterized."""
    # Malicious injection payloads
    attacks = [
        "'; DROP TABLE uploaded_data; --",
        "' OR '1'='1",
        "\" OR 1=1 --",
        "%",
        "_",
        "\\",
    ]

    for attack in attacks:
        res = populated_engine.get_dataset_preview(offset=0, limit=25, search=attack)
        # Must return valid response without raising SQL error
        assert res["status"] == "success"

    # Verify table remains 100% intact
    check = populated_engine.execute_query_readonly("SELECT COUNT(*) FROM uploaded_data")
    assert check["rows"][0][0] == 1000


def test_preview_api_endpoint_integration():
    """Verify FastAPI GET /api/data/preview endpoint responses, validation, and error handling."""
    client = TestClient(app)

    # 1. Health check or active dataset preview
    res = client.get("/api/data/preview?offset=0&limit=25")
    # In live app or test environment with active dataset
    if res.status_code == 200:
        data = res.json()
        assert data["status"] == "success"
        assert data["limit"] == 25
        assert len(data["rows"]) <= 25
    else:
        # If no active dataset loaded in test runner, must return 404
        assert res.status_code == 404

    # 2. Validation error for invalid sort_order regex
    res_bad_order = client.get("/api/data/preview?sort_order=INVALID_ORDER")
    assert res_bad_order.status_code == 422


def test_preview_missing_dataset(tmp_path: Path):
    """Verify that attempting to preview when no table exists raises a clear error."""
    empty_engine = DatabaseEngine(db_path=tmp_path / "empty.db")
    with pytest.raises(RuntimeError, match="no active dataset is loaded"):
        empty_engine.get_dataset_preview()


def test_preview_duplicate_rows_and_nulls(tmp_path: Path):
    """Verify preview handles duplicate rows and NULL/empty values without assuming first column is unique."""
    csv_content = (
        "id,category,amount\n"
        "101,Electronics,250.50\n"
        "101,Electronics,250.50\n"  # Duplicate row
        "102,,100.00\n"             # Empty string
        "103,Furniture,\n"          # NULL amount
    )
    csv_file = tmp_path / "duplicates.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    engine = DatabaseEngine(db_path=tmp_path / "dup_test.db")
    engine.ingest_csv(csv_file, filename="duplicates.csv")

    preview = engine.get_dataset_preview(offset=0, limit=10)
    assert preview["total_rows"] == 4
    assert preview["returned_rows"] == 4

    # Both duplicate rows returned
    rows = preview["rows"]
    assert rows[0][:2] == rows[1][:2]

    # Empty string and NULL handled safely
    assert rows[2][1] == "" or rows[2][1] is None
    assert rows[3][2] is None


def test_preview_readonly_preservation(populated_engine: DatabaseEngine):
    """Verify that multiple preview, search, and sort operations do not alter any data in SQLite."""
    count_before = populated_engine.execute_query_readonly("SELECT COUNT(*) FROM uploaded_data")["rows"][0][0]
    sample_before = populated_engine.execute_query_readonly("SELECT * FROM uploaded_data LIMIT 10")["rows"]

    # Execute various preview operations
    populated_engine.get_dataset_preview(offset=0, limit=50)
    populated_engine.get_dataset_preview(offset=100, limit=50, sort_by="sales", sort_order="desc")
    populated_engine.get_dataset_preview(offset=0, limit=50, search="CUST")
    populated_engine.get_dataset_preview(offset=200, limit=100, sort_by="quantity", sort_order="asc")

    count_after = populated_engine.execute_query_readonly("SELECT COUNT(*) FROM uploaded_data")["rows"][0][0]
    sample_after = populated_engine.execute_query_readonly("SELECT * FROM uploaded_data LIMIT 10")["rows"]

    assert count_before == count_after == 1000
    assert sample_before == sample_after


def test_preview_dataset_replacement_consistency(tmp_path: Path):
    """Verify that replacing a dataset refreshes preview metadata and rows completely."""
    engine = DatabaseEngine(db_path=tmp_path / "replace_test.db")

    csv1 = tmp_path / "ds1.csv"
    csv1.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    engine.ingest_csv(csv1, filename="ds1.csv")

    p1 = engine.get_dataset_preview()
    assert p1["filename"] == "ds1.csv"
    assert p1["total_rows"] == 2
    assert p1["total_columns"] == 2

    # Replace with second dataset
    csv2 = tmp_path / "ds2.csv"
    csv2.write_text("x,y,z\n10,20,30\n40,50,60\n70,80,90\n", encoding="utf-8")
    engine.ingest_csv(csv2, filename="ds2.csv")

    p2 = engine.get_dataset_preview()
    assert p2["filename"] == "ds2.csv"
    assert p2["total_rows"] == 3
    assert p2["total_columns"] == 3
    assert [c["name"] for c in p2["columns"]] == ["x", "y", "z"]

