"""Tests for deterministic multi-currency financial accuracy and safeguards."""

import pytest
from backend.agent import validate_currency_safety, validate_sql_safety


def test_currency_safety_single_currency_allowed():
    # When dataset has only 1 currency, aggregations are freely permitted
    sql = "SELECT SUM(sales) FROM uploaded_data;"
    ok, err = validate_currency_safety(sql, active_currencies=["USD"])
    assert ok is True
    assert err is None


def test_currency_safety_empty_currencies_allowed():
    sql = "SELECT SUM(sales) FROM uploaded_data;"
    ok, err = validate_currency_safety(sql, active_currencies=[])
    assert ok is True
    assert err is None


def test_currency_safety_mixed_currencies_unrestricted_sum_blocked():
    # Mixing multiple currencies without filter or grouping violates financial accuracy
    currencies = ["USD", "INR", "AUD", "CAD", "GBP", "SGD"]
    sql = "SELECT SUM(sales) FROM sales_transactions;"
    ok, err = validate_currency_safety(sql, active_currencies=currencies)
    assert ok is False
    assert "Multi-currency financial safety violation" in err
    assert "USD" in err


def test_currency_safety_mixed_currencies_avg_profit_blocked():
    currencies = ["USD", "INR", "AUD"]
    sql = "SELECT AVG(profit) FROM sales_transactions;"
    ok, err = validate_currency_safety(sql, active_currencies=currencies)
    assert ok is False
    assert "Multi-currency financial safety violation" in err


def test_currency_safety_mixed_currencies_where_filter_allowed():
    currencies = ["USD", "INR", "AUD", "CAD", "GBP", "SGD"]
    sql = "SELECT SUM(sales) FROM sales_transactions WHERE currency = 'USD';"
    ok, err = validate_currency_safety(sql, active_currencies=currencies)
    assert ok is True
    assert err is None


def test_currency_safety_mixed_currencies_where_in_filter_allowed():
    currencies = ["USD", "INR", "AUD"]
    sql = "SELECT SUM(sales) FROM sales_transactions WHERE currency IN ('USD');"
    ok, err = validate_currency_safety(sql, active_currencies=currencies)
    assert ok is True
    assert err is None


def test_currency_safety_mixed_currencies_group_by_allowed():
    currencies = ["USD", "INR", "AUD", "CAD", "GBP", "SGD"]
    sql = "SELECT currency, ROUND(SUM(sales), 2) AS total_sales FROM sales_transactions GROUP BY currency ORDER BY total_sales DESC;"
    ok, err = validate_currency_safety(sql, active_currencies=currencies)
    assert ok is True
    assert err is None


def test_currency_safety_multi_table_alias_and_join():
    currencies = ["USD", "INR", "AUD", "CAD", "GBP", "SGD"]
    sql = """
    SELECT 
        p.product_category,
        t.currency,
        ROUND(SUM(t.sales), 2) AS total_sales
    FROM sales_transactions AS t
    JOIN products AS p ON t.product_id = p.product_id
    WHERE t.currency = 'USD'
    GROUP BY p.product_category, t.currency
    ORDER BY total_sales DESC
    LIMIT 5;
    """
    ok, err = validate_currency_safety(sql, active_currencies=currencies)
    assert ok is True
    assert err is None


def test_currency_safety_non_monetary_aggregation_allowed():
    currencies = ["USD", "INR", "AUD", "CAD", "GBP", "SGD"]
    # Counting rows or distinct entities is not a monetary summation
    sql = "SELECT COUNT(*) AS total_txs FROM sales_transactions;"
    ok, err = validate_currency_safety(sql, active_currencies=currencies)
    assert ok is True
    assert err is None

    sql2 = "SELECT COUNT(DISTINCT customer_id) FROM sales_transactions;"
    ok2, err2 = validate_currency_safety(sql2, active_currencies=currencies)
    assert ok2 is True
    assert err2 is None


def test_validate_sql_safety_enforces_currency_policy():
    currencies = ["USD", "INR", "AUD"]
    allowed = {"sales_transactions", "products"}

    # Unrestricted sum across mixed currencies should fail validation
    unsafe_sql = "SELECT SUM(sales) FROM sales_transactions"
    ok, err = validate_sql_safety(unsafe_sql, allowed_tables=allowed, active_currencies=currencies)
    assert ok is False
    assert "Multi-currency financial safety violation" in err

    # Grouped or filtered query should pass
    safe_sql = "SELECT currency, SUM(sales) FROM sales_transactions GROUP BY currency"
    ok, err = validate_sql_safety(safe_sql, allowed_tables=allowed, active_currencies=currencies)
    assert ok is True
    assert err is None
