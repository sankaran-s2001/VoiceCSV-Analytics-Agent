"""Comprehensive SQL Security and Injection Attack Testing Suite.

Verifies multi-layer defenses against data manipulation, table dropping,
schema tampering, ATTACH database injections, PRAGMA access, multiple statements,
CTE injection, and malicious string payloads.
"""

from pathlib import Path
import pytest

from backend.agent import SecurityError, validate_sql
from backend.db_engine import DatabaseEngine


@pytest.fixture
def secure_engine(tmp_path: Path):
    """Provides an isolated SQLite engine loaded with sample data."""
    db_file = tmp_path / "security_test.db"
    engine = DatabaseEngine(db_path=db_file)
    csv_path = Path("tests/fixtures/sample_1000.csv")
    engine.ingest_csv(csv_path, filename="sample_1000.csv")
    return engine


UNSAFE_SQL_ATTACKS = [
    # Prohibited mutations
    "DROP TABLE uploaded_data;",
    "DELETE FROM uploaded_data;",
    "UPDATE uploaded_data SET sales = 0;",
    "INSERT INTO uploaded_data (order_id) VALUES ('hacked');",
    "ALTER TABLE uploaded_data ADD COLUMN injected TEXT;",
    # Database attaching and pragma inspection
    "ATTACH DATABASE 'other.db' AS other;",
    "PRAGMA table_info(uploaded_data);",
    "PRAGMA database_list;",
    # Multiple statements
    "SELECT * FROM uploaded_data; DROP TABLE uploaded_data;",
    "SELECT 1; UPDATE uploaded_data SET sales = 9999;",
    # Modification inside Common Table Expression (CTE)
    "WITH cte AS (DELETE FROM uploaded_data RETURNING *) SELECT * FROM cte;",
    "WITH hacked AS (SELECT 1) INSERT INTO uploaded_data SELECT * FROM hacked;",
    # Truncate & Vacuum
    "VACUUM;",
    "CREATE TABLE evil (id INT);",
]


@pytest.mark.parametrize("attack_sql", UNSAFE_SQL_ATTACKS)
def test_sql_validator_blocks_attacks(attack_sql: str):
    """Verify that validate_sql rejects all prohibited mutation keywords and multiple statements."""
    with pytest.raises(SecurityError):
        validate_sql(attack_sql)


@pytest.mark.parametrize("attack_sql", UNSAFE_SQL_ATTACKS)
def test_sqlite_engine_blocks_attacks(secure_engine: DatabaseEngine, attack_sql: str):
    """Verify that even if bypassed to the engine, read-only mode and SQLite authorizer deny modification."""
    # Attempt execution against SQLite
    with pytest.raises(Exception):
        secure_engine.execute_query_readonly(attack_sql)

    # Verify that uploaded_data remained completely intact!
    check = secure_engine.execute_query_readonly("SELECT COUNT(*) FROM uploaded_data")
    assert check["rows"][0][0] == 1000


def test_harmless_string_literal_with_prohibited_words():
    """Verify that words like 'UPDATE' inside string literals are NOT falsely blocked."""
    safe_query = "SELECT * FROM uploaded_data WHERE return_status = 'UPDATE';"
    validated = validate_sql(safe_query)
    assert "UPDATE" in validated


def test_markdown_fence_cleaning():
    """Verify that markdown code fences like ```sql ... ``` are cleanly unwrapped."""
    fenced = "```sql\nSELECT COUNT(*) FROM uploaded_data;\n```"
    unwrapped = validate_sql(fenced)
    assert unwrapped == "SELECT COUNT(*) FROM uploaded_data"


def test_recovery_after_blocked_attack(secure_engine: DatabaseEngine):
    """Verify that after an attack is rejected, subsequent legitimate queries succeed normally."""
    # 1. Blocked attack
    with pytest.raises(SecurityError):
        validate_sql("DROP TABLE uploaded_data;")

    # 2. Legitimate query
    legit_sql = "SELECT SUM(sales) FROM uploaded_data;"
    validated = validate_sql(legit_sql)
    res = secure_engine.execute_query_readonly(validated)
    assert res["rows"][0][0] > 0
