"""Tests for Primary Key and Foreign Key discovery, integrity verification, and index creation."""

import pytest
import sqlite3
from pathlib import Path

from backend.db_engine import DatabaseEngine


def test_primary_key_discovery_unique_non_null(tmp_path):
    db_path = tmp_path / "test_pk.db"
    engine = DatabaseEngine(db_path=db_path)

    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("CREATE TABLE products (product_id TEXT, name TEXT, price REAL)")
        conn.execute("INSERT INTO products VALUES ('P1', 'Gadget', 10.0), ('P2', 'Widget', 20.0)")

        conn.execute("CREATE TABLE stores (store_id INTEGER, location TEXT)")
        conn.execute("INSERT INTO stores VALUES (1, 'Downtown'), (2, 'Uptown')")

        conn.execute("CREATE TABLE logs (log_msg TEXT, timestamp TEXT)")
        conn.execute("INSERT INTO logs VALUES ('started', '2026-01-01'), ('stopped', '2026-01-02')")

        pks, _ = engine.discover_and_verify_relationships(conn, ["products", "stores", "logs"])

    assert pks.get("products") == "product_id"
    assert pks.get("stores") == "store_id"
    # logs has no PK candidate
    assert "logs" not in pks


def test_primary_key_duplicate_rejected(tmp_path):
    db_path = tmp_path / "test_pk_dup.db"
    engine = DatabaseEngine(db_path=db_path)

    with sqlite3.connect(str(db_path)) as conn:
        # Table with duplicate product_id values
        conn.execute("CREATE TABLE products (product_id TEXT, name TEXT)")
        conn.execute("INSERT INTO products VALUES ('P1', 'Gadget'), ('P1', 'Duplicate Gadget')")

        pks, _ = engine.discover_and_verify_relationships(conn, ["products"])

    assert "products" not in pks


def test_primary_key_null_rejected(tmp_path):
    db_path = tmp_path / "test_pk_null.db"
    engine = DatabaseEngine(db_path=db_path)

    with sqlite3.connect(str(db_path)) as conn:
        # Table with null in product_id
        conn.execute("CREATE TABLE products (product_id TEXT, name TEXT)")
        conn.execute("INSERT INTO products VALUES ('P1', 'Gadget'), (NULL, 'Missing ID')")

        pks, _ = engine.discover_and_verify_relationships(conn, ["products"])

    assert "products" not in pks


def test_foreign_key_discovery_clean_and_orphan_detection(tmp_path):
    db_path = tmp_path / "test_fk.db"
    engine = DatabaseEngine(db_path=db_path)

    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("CREATE TABLE customers (customer_id TEXT, name TEXT)")
        conn.execute("INSERT INTO customers VALUES ('C1', 'Alice'), ('C2', 'Bob')")

        # orders has 1 orphan record ('C99')
        conn.execute("CREATE TABLE orders (order_id TEXT, customer_id TEXT, amount REAL)")
        conn.execute("INSERT INTO orders VALUES ('O1', 'C1', 50), ('O2', 'C2', 75), ('O3', 'C99', 100)")

        pks, rels = engine.discover_and_verify_relationships(conn, ["customers", "orders"])

    assert pks["customers"] == "customer_id"
    assert pks["orders"] == "order_id"

    assert len(rels) == 1
    rel = rels[0]
    assert rel["child_table"] == "orders"
    assert rel["parent_table"] == "customers"
    assert rel["child_column"] == "customer_id"
    assert rel["parent_column"] == "customer_id"
    assert rel["orphan_keys"] == 1  # 'C99' is an orphan
    assert rel["status"] == "warning"
    assert rel["coverage_pct"] == 100.0  # Both C1 and C2 in customers are referenced


def test_relational_indexes_creation(tmp_path):
    db_path = tmp_path / "test_indexes.db"
    engine = DatabaseEngine(db_path=db_path)

    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("CREATE TABLE customers (customer_id TEXT, name TEXT)")
        conn.execute("CREATE TABLE orders (order_id TEXT, customer_id TEXT, amount REAL)")

        pks = {"customers": "customer_id", "orders": "order_id"}
        relationships = [{
            "source_table": "orders",
            "source_col": "customer_id",
            "target_table": "customers",
            "target_col": "customer_id"
        }]

        engine.create_relational_indexes(conn, ["customers", "orders"], relationships, pks)

        # Inspect indexes created
        cur = conn.cursor()
        cur.execute("PRAGMA index_list('customers')")
        cust_indexes = [r[1] for r in cur.fetchall()]
        assert "idx_pk_customers_customer_id" in cust_indexes

        cur.execute("PRAGMA index_list('orders')")
        order_indexes = [r[1] for r in cur.fetchall()]
        assert "idx_pk_orders_order_id" in order_indexes
        assert "idx_fk_orders_customer_id" in order_indexes
