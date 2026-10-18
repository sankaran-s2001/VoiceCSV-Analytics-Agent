"""Tests for multi-table relational CSV ingestion, staging atomicity, and table normalization."""

import pytest
from pathlib import Path
import sqlite3

from backend.db_engine import DatabaseEngine, normalize_table_name
from backend.operations import operation_tracker


def test_normalize_table_name():
    assert normalize_table_name("customers.csv") == "customers"
    assert normalize_table_name("Sales Transactions.csv") == "sales_transactions"
    assert normalize_table_name("Product-Details.CSV") == "product_details"
    assert normalize_table_name("123_data.csv") == "tbl_123_data"
    assert normalize_table_name("_staging_temp.csv") == "tbl_staging_temp"
    assert normalize_table_name("sqlite_master.csv") == "tbl_sqlite_master"
    assert normalize_table_name("") == "table_1"


def test_relational_ingestion_atomic_success(tmp_path):
    db_path = tmp_path / "test_relational.db"
    engine = DatabaseEngine(db_path=db_path)

    customers_csv = b"customer_id,name,city\nC1,Alice,New York\nC2,Bob,Chicago\nC3,Charlie,Seattle\n"
    orders_csv = b"order_id,customer_id,amount\nO1,C1,120\nO2,C2,250\nO3,C1,80\n"

    files = [
        ("customers.csv", customers_csv),
        ("orders.csv", orders_csv),
    ]

    res = engine.ingest_relational_dataset(files)

    assert res["status"] == "success"
    assert res["workspace_mode"] == "relational"
    assert "customers" in res["tables"]
    assert "orders" in res["tables"]
    assert res["tables"]["customers"]["row_count"] == 3
    assert res["tables"]["orders"]["row_count"] == 3
    assert res["total_rows"] == 6

    # Verify relationships detected
    assert len(res["relationships"]) == 1
    rel = res["relationships"][0]
    assert rel["child_table"] == "orders"
    assert rel["child_column"] == "customer_id"
    assert rel["parent_table"] == "customers"
    assert rel["parent_column"] == "customer_id"
    assert rel["orphan_keys"] == 0

    # Allowed tables
    assert engine.get_allowed_tables() == {"customers", "orders"}
    assert engine.get_active_workspace_mode() == "relational"


def test_relational_duplicate_normalized_names_rejected(tmp_path):
    db_path = tmp_path / "test_dup.db"
    engine = DatabaseEngine(db_path=db_path)

    files = [
        ("Customers.csv", b"id,val\n1,a\n"),
        ("customers.CSV", b"id,val\n2,b\n"),
    ]

    with pytest.raises(ValueError, match="Duplicate normalized table name"):
        engine.ingest_relational_dataset(files)


def test_relational_staging_rollback_on_malformed_file(tmp_path):
    db_path = tmp_path / "test_rollback.db"
    engine = DatabaseEngine(db_path=db_path)

    # First load a valid single dataset
    initial_csv = b"id,name\n1,Initial\n"
    engine.ingest_csv(initial_csv, "initial.csv")
    assert engine.get_active_workspace_mode() == "single"
    assert engine.has_active_dataset() is True

    # Attempt a relational upload where one file is malformed (no header/empty)
    files = [
        ("valid_table.csv", b"id,title\n10,Book\n"),
        ("broken.csv", b""),  # Empty file triggers ValueError
    ]

    with pytest.raises(ValueError):
        engine.ingest_relational_dataset(files)

    # Verify initial dataset was preserved and not corrupted
    assert engine.get_active_workspace_mode() == "single"
    preview = engine.get_dataset_preview()
    assert preview["total_rows"] == 1
    assert preview["rows"][0][1] == "Initial"


def test_relational_preserves_single_table_coexistence(tmp_path):
    db_path = tmp_path / "test_coexistence.db"
    engine = DatabaseEngine(db_path=db_path)

    # 1. Ingest single table
    single_csv = b"item,price\nKeyboard,75\nMouse,30\n"
    engine.ingest_csv(single_csv, "hardware.csv")
    assert engine.get_active_workspace_mode() == "single"

    # 2. Ingest relational dataset
    users_csv = b"user_id,username\nU10,John\n"
    logs_csv = b"log_id,user_id,action\nL1,U10,login\n"
    engine.ingest_relational_dataset([
        ("users.csv", users_csv),
        ("logs.csv", logs_csv),
    ])

    assert engine.get_active_workspace_mode() == "relational"
    assert engine.get_allowed_tables() == {"users", "logs"}

    # 3. Direct verification: uploaded_data table is still physically intact in SQLite!
    with sqlite3.connect(str(db_path)) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM uploaded_data")
        assert cursor.fetchone()[0] == 2

    # 4. Switch back to single mode
    engine.set_active_workspace_mode("single")
    assert engine.get_allowed_tables() == {"uploaded_data"}
    prev = engine.get_dataset_preview()
    assert prev["total_rows"] == 2


def test_load_bundled_sample_on_isolated_db(tmp_path):
    db_path = tmp_path / "test_sample.db"
    engine = DatabaseEngine(db_path=db_path)

    op_record = operation_tracker.create_relational_upload_operation()
    res = engine.load_bundled_relational_sample(op_record=op_record)

    assert res["status"] == "success"
    assert res["workspace_mode"] == "relational"
    tables = res["tables"]

    # Verify all 5 tables loaded
    expected_tables = {
        "customers": 19858,
        "products": 1000,
        "stores": 5,
        "sales_representatives": 5,
        "sales_transactions": 100000,
    }
    for t_name, exp_count in expected_tables.items():
        assert t_name in tables, f"Missing table {t_name}"
        assert tables[t_name]["row_count"] == exp_count, f"Table {t_name} expected {exp_count} rows, got {tables[t_name]['row_count']}"

    # Verify primary keys
    assert tables["customers"]["primary_key"] == "customer_id"
    assert tables["products"]["primary_key"] == "product_id"
    assert tables["stores"]["primary_key"] == "store_id"
    assert tables["sales_representatives"]["primary_key"] == "sales_rep_id"
    assert tables["sales_transactions"]["primary_key"] == "transaction_id"

    # Verify all 4 FK relationships verified with 0 orphans
    rels = res["relationships"]
    assert len(rels) >= 4
    rel_map = {(r["child_table"], r["parent_table"]): r for r in rels}

    expected_links = [
        ("sales_transactions", "customers", "customer_id"),
        ("sales_transactions", "products", "product_id"),
        ("sales_transactions", "stores", "store_id"),
        ("sales_transactions", "sales_representatives", "sales_rep_id"),
    ]
    for child, parent, key in expected_links:
        assert (child, parent) in rel_map, f"Missing relationship link {child} -> {parent}"
        link = rel_map[(child, parent)]
        assert link["child_column"] == key
        assert link["parent_column"] == key
        assert link["orphan_keys"] == 0
        assert link["coverage_pct"] == 100.0


def test_relational_query_readonly_execution(tmp_path):
    db_path = tmp_path / "test_ro.db"
    engine = DatabaseEngine(db_path=db_path)

    customers_csv = b"customer_id,name\nC1,Alice\nC2,Bob\n"
    orders_csv = b"order_id,customer_id,amount\nO1,C1,100\nO2,C1,150\nO3,C2,200\n"
    engine.ingest_relational_dataset([
        ("customers.csv", customers_csv),
        ("orders.csv", orders_csv),
    ])

    # Multi-table join query
    join_sql = """
    SELECT c.name, SUM(o.amount) AS total_spent
    FROM orders AS o
    JOIN customers AS c ON o.customer_id = c.customer_id
    GROUP BY c.name
    ORDER BY total_spent DESC;
    """
    res = engine.execute_query_readonly(join_sql)
    assert res["row_count"] == 2
    assert res["rows"][0] == ["Alice", 250]
    assert res["rows"][1] == ["Bob", 200]

    # Unauthorized table access must fail
    with pytest.raises(Exception):
        engine.execute_query_readonly("SELECT * FROM sqlite_master;")
