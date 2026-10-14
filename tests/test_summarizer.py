"""Tests for ExecutiveSummarizer: summary generation, empty data handling, and fallbacks."""

from unittest.mock import MagicMock, patch
from backend.summarizer import ExecutiveSummarizer, FALLBACK_SUMMARY


def test_summarizer_empty_data():
    summarizer = ExecutiveSummarizer()
    res = summarizer.generate_summary(
        question="What were total sales?",
        columns=["total_sales"],
        rows=[],
        row_count=0
    )
    assert "No matching records" in res["summary"]
    assert res["summary_latency_ms"] >= 0


def test_summarizer_mocked_success():
    summarizer = ExecutiveSummarizer()

    # Mock client and response
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Electronics led overall performance with $3,600 in total sales, significantly outpacing Furniture at $150."
    mock_client.models.generate_content.return_value = mock_response

    with patch.object(summarizer, "_get_genai_client", return_value=mock_client):
        res = summarizer.generate_summary(
            question="Revenue by category",
            columns=["category", "sales"],
            rows=[["Electronics", 3600], ["Furniture", 150]],
            row_count=2
        )

    assert res["summary"] == mock_response.text
    assert res["summary_latency_ms"] >= 0


def test_summarizer_resilient_fallback():
    summarizer = ExecutiveSummarizer()

    # Mock client raising an exception (e.g. network/quota error)
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = Exception("API connection timed out")

    with patch.object(summarizer, "_get_genai_client", return_value=mock_client):
        res = summarizer.generate_summary(
            question="Revenue by category",
            columns=["category", "sales"],
            rows=[["Electronics", 3600]],
            row_count=1
        )

    # Valid query results are NOT lost; fallback summary is returned cleanly
    assert res["summary"] == FALLBACK_SUMMARY
    assert res["summary_latency_ms"] >= 0


def test_summarizer_unconfigured_api_key():
    summarizer = ExecutiveSummarizer()

    # When client is None (no API key configured)
    with patch.object(summarizer, "_get_genai_client", return_value=None):
        res = summarizer.generate_summary(
            question="Top items",
            columns=["name"],
            rows=[["Item A"]],
            row_count=1
        )

    assert "Configure GOOGLE_API_KEY" in res["summary"]
