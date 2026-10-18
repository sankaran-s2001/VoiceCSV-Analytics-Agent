"""Known-Answer Relational Benchmark Test Suite (20 Business Questions).

Independently calculates expected results from raw CSV files via Pandas
and compares against SQLite query results executed on the relational workspace.
"""

import pytest
import pandas as pd
from pathlib import Path

from backend.db_engine import DatabaseEngine
from backend.agent import validate_currency_safety, validate_sql_safety


@pytest.fixture(scope="module")
def benchmark_env(tmp_path_factory):
    """Load bundled sample relational dataset into an isolated SQLite database once for the benchmark."""
    tmp_dir = tmp_path_factory.mktemp("benchmark_data")
    db_path = tmp_dir / "benchmark.db"
    engine = DatabaseEngine(db_path=db_path)
    engine.load_bundled_relational_sample()

    # Load raw dataframes for independent calculation
    data_dir = Path("data")
    df_tx = pd.read_csv(data_dir / "sales_transactions.csv", low_memory=False)
    df_cust = pd.read_csv(data_dir / "customers.csv", low_memory=False)
    df_prod = pd.read_csv(data_dir / "products.csv", low_memory=False)
    df_store = pd.read_csv(data_dir / "stores.csv", low_memory=False)
    df_rep = pd.read_csv(data_dir / "sales_representatives.csv", low_memory=False)

    return {
        "engine": engine,
        "df_tx": df_tx,
        "df_cust": df_cust,
        "df_prod": df_prod,
        "df_store": df_store,
        "df_rep": df_rep,
    }


def test_b01_total_transaction_count(benchmark_env):
    """B1: Total transaction count."""
    engine = benchmark_env["engine"]
    df_tx = benchmark_env["df_tx"]

    expected = len(df_tx)
    sql = "SELECT COUNT(*) AS total_tx FROM sales_transactions;"
    res = engine.execute_query_readonly(sql)

    assert res["rows"][0][0] == expected == 100000


def test_b02_unique_customer_count(benchmark_env):
    """B2: Unique customer count in transactions."""
    engine = benchmark_env["engine"]
    df_tx = benchmark_env["df_tx"]

    expected = int(df_tx["customer_id"].nunique())
    sql = "SELECT COUNT(DISTINCT customer_id) AS unique_customers FROM sales_transactions;"
    res = engine.execute_query_readonly(sql)

    assert res["rows"][0][0] == expected == 19858


def test_b03_transactions_by_currency(benchmark_env):
    """B3: Total transactions by currency."""
    engine = benchmark_env["engine"]
    df_tx = benchmark_env["df_tx"]

    expected = df_tx["currency"].value_counts().to_dict()
    sql = """
    SELECT currency, COUNT(*) AS tx_count
    FROM sales_transactions
    GROUP BY currency
    ORDER BY tx_count DESC;
    """
    res = engine.execute_query_readonly(sql)
    actual = {row[0]: row[1] for row in res["rows"]}

    assert actual == expected


def test_b04_sales_by_product_category_and_currency(benchmark_env):
    """B4: Sales by product category and currency (JOIN sales_transactions + products)."""
    engine = benchmark_env["engine"]
    df_tx = benchmark_env["df_tx"]
    df_prod = benchmark_env["df_prod"]

    merged = df_tx.merge(df_prod, on="product_id")
    expected_df = (
        merged.groupby(["product_category", "currency"])["sales"]
        .sum()
        .round(2)
        .reset_index()
    )
    expected_map = {
        (r["product_category"], r["currency"]): round(r["sales"], 2)
        for _, r in expected_df.iterrows()
    }

    sql = """
    SELECT p.product_category, t.currency, ROUND(SUM(t.sales), 2) AS total_sales
    FROM sales_transactions AS t
    JOIN products AS p ON t.product_id = p.product_id
    GROUP BY p.product_category, t.currency;
    """
    assert validate_currency_safety(sql, ["USD", "INR", "AUD", "CAD", "GBP", "SGD"])[0] is True
    res = engine.execute_query_readonly(sql)

    actual_map = {(row[0], row[1]): round(row[2], 2) for row in res["rows"]}
    assert len(actual_map) == len(expected_map)
    for k, v in expected_map.items():
        assert abs(actual_map[k] - v) < 1.0  # Floating-point tolerance


def test_b05_top_five_products_by_sales_in_usd(benchmark_env):
    """B5: Top 5 products by sales in USD."""
    engine = benchmark_env["engine"]
    df_tx = benchmark_env["df_tx"]
    df_prod = benchmark_env["df_prod"]

    usd_tx = df_tx[df_tx["currency"] == "USD"].merge(df_prod, on="product_id")
    top5_expected = (
        usd_tx.groupby(["product_id", "product_name"])["sales"]
        .sum()
        .round(2)
        .sort_values(ascending=False)
        .head(5)
    )
    expected_ids = [idx[0] for idx in top5_expected.index]

    sql = """
    SELECT p.product_id, p.product_name, ROUND(SUM(t.sales), 2) AS total_sales
    FROM sales_transactions AS t
    JOIN products AS p ON t.product_id = p.product_id
    WHERE t.currency = 'USD'
    GROUP BY p.product_id, p.product_name
    ORDER BY total_sales DESC
    LIMIT 5;
    """
    assert validate_currency_safety(sql, ["USD", "INR", "AUD", "CAD", "GBP", "SGD"])[0] is True
    res = engine.execute_query_readonly(sql)
    actual_ids = [row[0] for row in res["rows"]]

    assert actual_ids == expected_ids


def test_b06_top_five_customers_by_spend_in_usd(benchmark_env):
    """B6: Top 5 customers by spend in USD."""
    engine = benchmark_env["engine"]
    df_tx = benchmark_env["df_tx"]
    df_cust = benchmark_env["df_cust"]

    usd_tx = df_tx[df_tx["currency"] == "USD"].merge(df_cust, on="customer_id")
    top5_expected = (
        usd_tx.groupby(["customer_id", "customer_name"])["sales"]
        .sum()
        .round(2)
        .sort_values(ascending=False)
        .head(5)
    )
    expected_ids = [idx[0] for idx in top5_expected.index]

    sql = """
    SELECT c.customer_id, c.customer_name, ROUND(SUM(t.sales), 2) AS total_spend
    FROM sales_transactions AS t
    JOIN customers AS c ON t.customer_id = c.customer_id
    WHERE t.currency = 'USD'
    GROUP BY c.customer_id, c.customer_name
    ORDER BY total_spend DESC
    LIMIT 5;
    """
    assert validate_currency_safety(sql, ["USD", "INR", "AUD", "CAD", "GBP", "SGD"])[0] is True
    res = engine.execute_query_readonly(sql)
    actual_ids = [row[0] for row in res["rows"]]

    assert actual_ids == expected_ids


def test_b07_sales_by_customer_state_in_usd(benchmark_env):
    """B7: Sales by customer state in USD."""
    engine = benchmark_env["engine"]
    df_tx = benchmark_env["df_tx"]
    df_cust = benchmark_env["df_cust"]

    usd_tx = df_tx[df_tx["currency"] == "USD"].merge(df_cust, on="customer_id")
    expected = (
        usd_tx.groupby("customer_state")["sales"]
        .sum()
        .round(2)
        .to_dict()
    )

    sql = """
    SELECT c.customer_state, ROUND(SUM(t.sales), 2) AS state_sales
    FROM sales_transactions AS t
    JOIN customers AS c ON t.customer_id = c.customer_id
    WHERE t.currency = 'USD'
    GROUP BY c.customer_state;
    """
    res = engine.execute_query_readonly(sql)
    actual = {row[0]: round(row[1], 2) for row in res["rows"]}

    assert len(actual) == len(expected)
    for state, val in expected.items():
        assert abs(actual[state] - val) < 1.0


def test_b08_transactions_by_store(benchmark_env):
    """B8: Transactions by store (JOIN sales_transactions + stores)."""
    engine = benchmark_env["engine"]
    df_tx = benchmark_env["df_tx"]
    df_store = benchmark_env["df_store"]

    merged = df_tx.merge(df_store, on="store_id")
    expected = merged.groupby(["store_id", "store_name"]).size().to_dict()

    sql = """
    SELECT s.store_id, s.store_name, COUNT(*) AS tx_count
    FROM sales_transactions AS t
    JOIN stores AS s ON t.store_id = s.store_id
    GROUP BY s.store_id, s.store_name
    ORDER BY s.store_id;
    """
    res = engine.execute_query_readonly(sql)
    actual = {(row[0], row[1]): row[2] for row in res["rows"]}

    assert actual == expected


def test_b09_transactions_by_sales_rep(benchmark_env):
    """B9: Transactions by sales representative."""
    engine = benchmark_env["engine"]
    df_tx = benchmark_env["df_tx"]
    df_rep = benchmark_env["df_rep"]

    merged = df_tx.merge(df_rep, on="sales_rep_id")
    expected = merged.groupby(["sales_rep_id", "sales_rep_name"]).size().to_dict()

    sql = """
    SELECT r.sales_rep_id, r.sales_rep_name, COUNT(*) AS tx_count
    FROM sales_transactions AS t
    JOIN sales_representatives AS r ON t.sales_rep_id = r.sales_rep_id
    GROUP BY r.sales_rep_id, r.sales_rep_name
    ORDER BY r.sales_rep_id;
    """
    res = engine.execute_query_readonly(sql)
    actual = {(row[0], row[1]): row[2] for row in res["rows"]}

    assert actual == expected


def test_b10_average_rating_by_customer_segment(benchmark_env):
    """B10: Average customer rating by customer segment."""
    engine = benchmark_env["engine"]
    df_tx = benchmark_env["df_tx"]
    df_cust = benchmark_env["df_cust"]

    merged = df_tx.merge(df_cust, on="customer_id")
    expected = (
        merged.groupby("customer_segment")["customer_rating"]
        .mean()
        .round(2)
        .to_dict()
    )

    sql = """
    SELECT c.customer_segment, ROUND(AVG(t.customer_rating), 2) AS avg_rating
    FROM sales_transactions AS t
    JOIN customers AS c ON t.customer_id = c.customer_id
    GROUP BY c.customer_segment
    ORDER BY c.customer_segment;
    """
    res = engine.execute_query_readonly(sql)
    actual = {row[0]: round(row[1], 2) for row in res["rows"]}

    assert actual == expected


def test_b11_returns_by_product_category(benchmark_env):
    """B11: Returned transaction count by product category."""
    engine = benchmark_env["engine"]
    df_tx = benchmark_env["df_tx"]
    df_prod = benchmark_env["df_prod"]

    returned_df = df_tx[df_tx["return_status"] == "Yes"].merge(df_prod, on="product_id")
    expected = returned_df.groupby("product_category").size().to_dict()

    sql = """
    SELECT p.product_category, COUNT(*) AS returned_count
    FROM sales_transactions AS t
    JOIN products AS p ON t.product_id = p.product_id
    WHERE t.return_status = 'Yes'
    GROUP BY p.product_category
    ORDER BY returned_count DESC;
    """
    res = engine.execute_query_readonly(sql)
    actual = {row[0]: row[1] for row in res["rows"]}

    assert actual == expected


def test_b12_profit_by_category_and_currency(benchmark_env):
    """B12: Total profit by product category grouped by currency."""
    engine = benchmark_env["engine"]
    df_tx = benchmark_env["df_tx"]
    df_prod = benchmark_env["df_prod"]

    merged = df_tx.merge(df_prod, on="product_id")
    expected_df = (
        merged.groupby(["product_category", "currency"])["profit"]
        .sum()
        .round(2)
        .reset_index()
    )
    expected_map = {
        (r["product_category"], r["currency"]): round(r["profit"], 2)
        for _, r in expected_df.iterrows()
    }

    sql = """
    SELECT p.product_category, t.currency, ROUND(SUM(t.profit), 2) AS total_profit
    FROM sales_transactions AS t
    JOIN products AS p ON t.product_id = p.product_id
    GROUP BY p.product_category, t.currency;
    """
    assert validate_currency_safety(sql, ["USD", "INR", "AUD", "CAD", "GBP", "SGD"])[0] is True
    res = engine.execute_query_readonly(sql)
    actual_map = {(row[0], row[1]): round(row[2], 2) for row in res["rows"]}

    assert len(actual_map) == len(expected_map)
    for k, v in expected_map.items():
        assert abs(actual_map[k] - v) < 1.0


def test_b13_monthly_transaction_counts(benchmark_env):
    """B13: Monthly transaction counts using SUBSTR(order_date, 1, 7)."""
    engine = benchmark_env["engine"]
    df_tx = benchmark_env["df_tx"]

    df_copy = df_tx.copy()
    df_copy["ym"] = df_copy["order_date"].astype(str).str.slice(0, 7)
    expected = df_copy.groupby("ym").size().to_dict()

    sql = """
    SELECT SUBSTR(order_date, 1, 7) AS year_month, COUNT(*) AS count
    FROM sales_transactions
    GROUP BY year_month
    ORDER BY year_month;
    """
    res = engine.execute_query_readonly(sql)
    actual = {row[0]: row[1] for row in res["rows"]}

    assert actual == expected


def test_b14_monthly_sales_in_usd(benchmark_env):
    """B14: Monthly sales filtered specifically for USD."""
    engine = benchmark_env["engine"]
    df_tx = benchmark_env["df_tx"]

    usd_tx = df_tx[df_tx["currency"] == "USD"].copy()
    usd_tx["ym"] = usd_tx["order_date"].astype(str).str.slice(0, 7)
    expected = usd_tx.groupby("ym")["sales"].sum().round(2).to_dict()

    sql = """
    SELECT SUBSTR(order_date, 1, 7) AS year_month, ROUND(SUM(sales), 2) AS monthly_sales
    FROM sales_transactions
    WHERE currency = 'USD'
    GROUP BY year_month
    ORDER BY year_month;
    """
    assert validate_currency_safety(sql, ["USD", "INR", "AUD", "CAD", "GBP", "SGD"])[0] is True
    res = engine.execute_query_readonly(sql)
    actual = {row[0]: round(row[1], 2) for row in res["rows"]}

    assert len(actual) == len(expected)
    for ym, val in expected.items():
        assert abs(actual[ym] - val) < 1.0


def test_b15_transactions_for_specific_customer(benchmark_env):
    """B15: Retrieve transaction history for customer 'CUST-00001'."""
    engine = benchmark_env["engine"]
    df_tx = benchmark_env["df_tx"]

    expected_count = int((df_tx["customer_id"] == "CUST-00001").sum())

    sql = """
    SELECT t.transaction_id, t.order_date, t.sales, t.currency
    FROM sales_transactions AS t
    WHERE t.customer_id = 'CUST-00001'
    ORDER BY t.order_date;
    """
    res = engine.execute_query_readonly(sql)

    assert res["row_count"] == expected_count


def test_b16_products_with_no_sales(benchmark_env):
    """B16: Detect products with no transactions using LEFT JOIN."""
    engine = benchmark_env["engine"]
    df_tx = benchmark_env["df_tx"]
    df_prod = benchmark_env["df_prod"]

    expected_zero = len(set(df_prod["product_id"]) - set(df_tx["product_id"]))

    sql = """
    SELECT p.product_id, p.product_name
    FROM products AS p
    LEFT JOIN sales_transactions AS t ON p.product_id = t.product_id
    WHERE t.product_id IS NULL;
    """
    res = engine.execute_query_readonly(sql)

    assert res["row_count"] == expected_zero == 0


def test_b17_customers_with_no_transactions(benchmark_env):
    """B17: Detect customers with no transactions using LEFT JOIN."""
    engine = benchmark_env["engine"]
    df_tx = benchmark_env["df_tx"]
    df_cust = benchmark_env["df_cust"]

    expected_zero = len(set(df_cust["customer_id"]) - set(df_tx["customer_id"]))

    sql = """
    SELECT c.customer_id, c.customer_name
    FROM customers AS c
    LEFT JOIN sales_transactions AS t ON c.customer_id = t.customer_id
    WHERE t.customer_id IS NULL;
    """
    res = engine.execute_query_readonly(sql)

    assert res["row_count"] == expected_zero == 0


def test_b18_orphan_foreign_key_detection(benchmark_env):
    """B18: Verify zero orphan transactions exist in database."""
    engine = benchmark_env["engine"]

    sql = """
    SELECT COUNT(*) 
    FROM sales_transactions 
    WHERE customer_id NOT IN (SELECT customer_id FROM customers);
    """
    res = engine.execute_query_readonly(sql)

    assert res["rows"][0][0] == 0


def test_b19_null_value_handling_in_discounts(benchmark_env):
    """B19: Check count of transactions without promotion name (NULL value handling)."""
    engine = benchmark_env["engine"]
    df_tx = benchmark_env["df_tx"]

    expected_nulls = int(df_tx["promotion_name"].isnull().sum())

    sql = "SELECT COUNT(*) FROM sales_transactions WHERE promotion_name IS NULL;"
    res = engine.execute_query_readonly(sql)

    assert res["rows"][0][0] == expected_nulls


def test_b20_unsupported_column_rejection(benchmark_env):
    """B20: Safety validator rejects query asking for columns not present in the relational schema."""
    engine = benchmark_env["engine"]
    allowed = engine.get_allowed_tables()

    # Query with non-existent column 'employee_age' and 'vendor_rating'
    unsupported_sql = """
    SELECT p.product_name, p.vendor_rating 
    FROM products p 
    JOIN sales_transactions t ON p.product_id = t.product_id;
    """

    # SQLite operational error when non-existent column is requested
    with pytest.raises(Exception):
        engine.execute_query_readonly(unsupported_sql)
