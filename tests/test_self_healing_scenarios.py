"""Self-Healing and Error Recovery Scenario Tests (Scenarios A through H).

Tests deterministic error correction, bounded repair loops, unsafe repair defense,
valid empty result handling, and executive summary resilience.
"""

from pathlib import Path
from unittest.mock import MagicMock
import pytest

from backend.agent import AnalyticsAgent, SecurityError
from backend.db_engine import DatabaseEngine
from backend.summarizer import ExecutiveSummarizer


@pytest.fixture
def agent_env(tmp_path: Path):
    """Provides an isolated database loaded with sample data and a mock-ready agent."""
    db_file = tmp_path / "self_healing.db"
    engine = DatabaseEngine(db_path=db_file)
    csv_path = Path("tests/fixtures/sample_1000.csv")
    engine.ingest_csv(csv_path, filename="sample_1000.csv")

    agent = AnalyticsAgent(engine=engine)
    mock_agent_client = MagicMock()
    agent._get_genai_client = MagicMock(return_value=mock_agent_client)

    summarizer = ExecutiveSummarizer()
    mock_sum_client = MagicMock()
    summarizer._get_genai_client = MagicMock(return_value=mock_sum_client)

    return engine, agent, summarizer, mock_agent_client, mock_sum_client


def test_scenario_a_initial_success(agent_env):
    """Scenario A: Initial success - Gemini generates valid SQL on first attempt."""
    _, agent, _, mock_agent_client, _ = agent_env
    # Mock Gemini returning valid SQL
    mock_response = MagicMock()
    mock_response.text = "SELECT COUNT(*) AS total FROM uploaded_data;"
    mock_agent_client.models.generate_content.return_value = mock_response

    result = agent.answer_question("How many records?")
    assert result["heal_attempts"] == 0
    assert result["row_count"] == 1
    assert result["rows"][0][0] == 1000


def test_scenario_b_one_correctable_error(agent_env):
    """Scenario B: One correctable error - Misspelled column repaired on first attempt."""
    _, agent, _, mock_agent_client, _ = agent_env

    # First response: misspelled column 'salez'
    bad_resp = MagicMock()
    bad_resp.text = "SELECT SUM(salez) FROM uploaded_data;"

    # Second response: corrected column 'sales'
    good_resp = MagicMock()
    good_resp.text = "SELECT SUM(sales) FROM uploaded_data;"

    mock_agent_client.models.generate_content.side_effect = [bad_resp, good_resp]

    result = agent.answer_question("What is total sales?")
    assert result["heal_attempts"] == 1
    assert "sales" in result["sql"]
    assert result["rows"][0][0] > 0


def test_scenario_c_multiple_repair_attempts(agent_env):
    """Scenario C: Multiple repair attempts - First repair also fails, second repair succeeds."""
    _, agent, _, mock_agent_client, _ = agent_env

    # 1. First attempt: bad syntax
    resp1 = MagicMock()
    resp1.text = "SELEC * FROM uploaded_data;"
    # 2. Repair attempt 1: bad column
    resp2 = MagicMock()
    resp2.text = "SELECT invalid_col FROM uploaded_data;"
    # 3. Repair attempt 2: valid SQL
    resp3 = MagicMock()
    resp3.text = "SELECT COUNT(*) FROM uploaded_data;"

    mock_agent_client.models.generate_content.side_effect = [resp1, resp2, resp3]

    result = agent.answer_question("Count rows please")
    assert result["heal_attempts"] == 2
    assert result["rows"][0][0] == 1000


def test_scenario_d_exhausted_repair_attempts(agent_env):
    """Scenario D: Exhausted repairs - Model repeatedly generates invalid SQL."""
    _, agent, _, mock_agent_client, _ = agent_env

    bad_resp = MagicMock()
    bad_resp.text = "SELECT totally_fake_column FROM uploaded_data;"
    mock_agent_client.models.generate_content.return_value = bad_resp

    with pytest.raises(RuntimeError) as exc_info:
        agent.answer_question("Total profit")

    assert "Failed to execute valid SQL" in str(exc_info.value) or "no such column" in str(exc_info.value)


def test_scenario_e_unsafe_repair(agent_env):
    """Scenario E: Unsafe repair - Model tries to return a prohibited query during repair."""
    _, agent, _, mock_agent_client, _ = agent_env

    bad_syntax = MagicMock()
    bad_syntax.text = "SELECT * FORM uploaded_data;"

    unsafe_repair = MagicMock()
    unsafe_repair.text = "DROP TABLE uploaded_data;"

    mock_agent_client.models.generate_content.side_effect = [bad_syntax, unsafe_repair]

    with pytest.raises(SecurityError):
        agent.answer_question("Fix this query")


def test_scenario_g_valid_empty_results(agent_env):
    """Scenario G: Valid empty results - Legitimate query matches 0 rows without failing."""
    _, agent, _, mock_agent_client, _ = agent_env

    empty_query_resp = MagicMock()
    empty_query_resp.text = "SELECT * FROM uploaded_data WHERE region = 'NonExistentRegion';"
    mock_agent_client.models.generate_content.return_value = empty_query_resp

    result = agent.answer_question("Show orders from NonExistentRegion")
    assert result["row_count"] == 0
    assert result["rows"] == []
    assert result["heal_attempts"] == 0


def test_scenario_h_summary_failure_resilience(agent_env):
    """Scenario H: Summary failure resilience - SQL succeeds even if Gemini summary API fails."""
    _, agent, summarizer, mock_agent_client, mock_sum_client = agent_env

    # 1. SQL succeeds
    sql_resp = MagicMock()
    sql_resp.text = "SELECT COUNT(*) FROM uploaded_data;"
    mock_agent_client.models.generate_content.return_value = sql_resp
    sql_result = agent.answer_question("Total rows")
    assert sql_result["row_count"] == 1

    # 2. Gemini summary fails with API exception
    mock_sum_client.models.generate_content.side_effect = Exception("Gemini Quota Exceeded")
    summary_result = summarizer.generate_summary(
        question="Total rows",
        columns=sql_result["columns"],
        rows=sql_result["rows"],
        row_count=sql_result["row_count"]
    )

    # 3. Verified: Fallback summary returned gracefully without crashing the application!
    assert "unavailable" in summary_result["summary"].lower() or "returned" in summary_result["summary"].lower()
    assert summary_result["summary_latency_ms"] >= 0
