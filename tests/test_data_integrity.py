"""Data Integrity and Accurate Loading Verification Tests.

Performs known-answer tests, independent mathematical calculations (using Pandas),
leading zero preservation checks, encoding handling (BOM, CP1252), and transactional
table recovery on isolated SQLite databases.
"""

from pathlib import Path
import pandas as pd
import pytest

from backend.db_engine import DatabaseEngine


@pytest.fixture
def isolated_engine(tmp_path: Path):
    """Provides an isolated SQLite engine bound to a temporary directory."""
    db_file = tmp_path / "integrity_test.db"
    return DatabaseEngine(db_path=db_file)


def test_sample_1000_mathematical_accuracy(isolated_engine: DatabaseEngine):
    """Verify 1,000-row dataset loads faithfully and matches exact mathematical totals."""
    csv_path = Path("tests/fixtures/sample_1000.csv")
    assert csv_path.exists(), "sample_1000.csv fixture must exist"

    # 1. Independent calculations using Pandas
    df_raw = pd.read_csv(csv_path)
    expected_row_count = len(df_raw)
    assert expected_row_count == 1000

    expected_sum_sales = float(df_raw["sales"].sum())
    expected_sum_profit = float(df_raw["profit"].sum())
    expected_sum_quantity = int(df_raw["quantity"].sum())
    expected_avg_sales = float(df_raw["sales"].mean())

    # Top 3 products by sales
    top_products_series = df_raw.groupby("product_name")["sales"].sum().sort_values(ascending=False).head(3)
    expected_top_products = list(zip(top_products_series.index, [float(v) for v in top_products_series.values]))

    # 2. Ingest into isolated SQLite database
    summary = isolated_engine.ingest_csv(str(csv_path), filename="sample_1000.csv")
    assert summary["row_count"] == 1000
    assert summary["table_name"] == "uploaded_data"

    # 3. Compare with SQLite aggregations
    res_count = isolated_engine.execute_query_readonly("SELECT COUNT(*) AS total_rows FROM uploaded_data")
    assert res_count["rows"][0][0] == expected_row_count

    res_sums = isolated_engine.execute_query_readonly(
        "SELECT SUM(sales) AS total_sales, SUM(profit) AS total_profit, SUM(quantity) AS total_qty, AVG(sales) AS avg_sales FROM uploaded_data"
    )
    db_total_sales, db_total_profit, db_total_qty, db_avg_sales = res_sums["rows"][0]

    # Verify floating point tolerances within 0.01
    assert abs(db_total_sales - expected_sum_sales) < 0.01
    assert abs(db_total_profit - expected_sum_profit) < 0.01
    assert db_total_qty == expected_sum_quantity
    assert abs(db_avg_sales - expected_avg_sales) < 0.01

    # Verify top products grouping
    res_top = isolated_engine.execute_query_readonly(
        "SELECT product_name, SUM(sales) AS total_sales FROM uploaded_data GROUP BY product_name ORDER BY total_sales DESC LIMIT 3"
    )
    for idx, (expected_prod, expected_val) in enumerate(expected_top_products):
        db_prod = res_top["rows"][idx][0]
        db_val = res_top["rows"][idx][1]
        assert db_prod == expected_prod
        assert abs(db_val - expected_val) < 0.01


def test_leading_zero_preservation(isolated_engine: DatabaseEngine):
    """Verify numeric-looking identifiers with leading zeros (e.g. '00125') remain strings."""
    csv_path = Path("tests/fixtures/adversarial_leading_zeros.csv")
    assert csv_path.exists()

    summary = isolated_engine.ingest_csv(str(csv_path), filename="adversarial_leading_zeros.csv")
    assert summary["row_count"] == 3

    res = isolated_engine.execute_query_readonly(
        "SELECT account_code, zip_code, amount FROM uploaded_data ORDER BY account_code ASC"
    )

    account_codes = [r[0] for r in res["rows"]]
    zip_codes = [r[1] for r in res["rows"]]

    # Leading zeros MUST NOT be stripped
    assert "00034" in account_codes
    assert "00105" in account_codes
    assert "00208" in account_codes
    assert "02134" in zip_codes
    assert "08540" in zip_codes


def test_bom_and_cp1252_encodings(isolated_engine: DatabaseEngine):
    """Verify UTF-8 with BOM and Windows CP1252 files ingest without corrupted headers or crashes."""
    # Test UTF-8 with BOM
    bom_csv = Path("tests/fixtures/adversarial_bom.csv")
    summary_bom = isolated_engine.ingest_csv(str(bom_csv), filename="adversarial_bom.csv")
    assert summary_bom["row_count"] == 2
    # Check headers do not have \ufeff
    cols = [c["name"] for c in summary_bom["columns"]]
    assert "id" in cols
    assert not any("\ufeff" in c for c in cols)

    # Test CP1252
    cp1252_csv = Path("tests/fixtures/adversarial_cp1252.csv")
    summary_cp1252 = isolated_engine.ingest_csv(str(cp1252_csv), filename="adversarial_cp1252.csv")
    assert summary_cp1252["row_count"] == 2


def test_duplicate_headers_disambiguation(isolated_engine: DatabaseEngine):
    """Verify duplicate CSV headers are disambiguated safely into unique SQLite columns."""
    dup_csv = Path("tests/fixtures/adversarial_duplicate_headers.csv")
    summary = isolated_engine.ingest_csv(str(dup_csv), filename="adversarial_duplicate_headers.csv")
    cols = [c["name"] for c in summary["columns"]]
    assert len(cols) == len(set(cols)), "All normalized SQLite columns must be strictly unique"
    assert "sales" in cols
    assert "sales_2" in cols


def test_atomic_replacement_and_rollback_on_failure(isolated_engine: DatabaseEngine):
    """Verify that uploading an invalid/malformed file does not destroy or corrupt the active dataset."""
    valid_csv = Path("tests/fixtures/sample_1000.csv")
    isolated_engine.ingest_csv(str(valid_csv), filename="sample_1000.csv")

    initial_schema = isolated_engine.get_schema_info()
    assert initial_schema["is_loaded"] is True
    assert initial_schema["row_count"] == 1000

    # Attempt to upload a malformed CSV with inconsistent/unparseable structure
    malformed_csv = Path("tests/fixtures/adversarial_malformed.csv")
    with pytest.raises(Exception):
        isolated_engine.ingest_csv(str(malformed_csv), filename="adversarial_malformed.csv")

    # The previous valid dataset MUST remain 100% intact!
    recovered_schema = isolated_engine.get_schema_info()
    assert recovered_schema["is_loaded"] is True
    assert recovered_schema["row_count"] == 1000
    assert recovered_schema["filename"] == "sample_1000.csv"

    # Query against uploaded_data must still succeed
    res = isolated_engine.execute_query_readonly("SELECT COUNT(*) FROM uploaded_data")
    assert res["rows"][0][0] == 1000
