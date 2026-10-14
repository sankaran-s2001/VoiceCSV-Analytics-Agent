"""Executive Summary Generator using Gemini.

Synthesizes query results into concise, executive-level business takeaways.
Provides safe fallbacks if the model or network is temporarily unavailable.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional
from google import genai
from google.genai import types

from backend.config import settings

logger = logging.getLogger(__name__)

SUMMARY_SYSTEM_INSTRUCTION = """You are an executive business analyst.

Summarize the actual query results in two or three short, clear sentences suitable for a business stakeholder.

Rules:
1. Explain the most important finding using the values provided in the results.
2. Mention relevant figures, totals, and key comparisons where supported by the numbers.
3. Do not mention SQL, database tables, column names, or implementation details.
4. Do not invent facts, percentages, or numerical values not present in the data.
5. Do not claim trends or root causes that the data does not establish.
6. If the result is empty, clearly state that no matching records were found.
7. If the result contains only NULL or empty values, explain that no usable values were found for the requested metric.
8. Keep the tone polished, objective, and executive-ready.
"""

FALLBACK_SUMMARY = "Your query completed successfully, but the AI summary is temporarily unavailable."


class ExecutiveSummarizer:
    """Generates business summaries from executed query results."""

    def __init__(self):
        pass

    def _get_genai_client(self) -> Optional[genai.Client]:
        if not settings.is_gemini_configured:
            return None
        try:
            return genai.Client(api_key=settings.google_api_key)
        except Exception as e:
            logger.warning("Could not initialize Gemini client for summarizer: %s", e)
            return None

    def generate_summary(
        self,
        question: str,
        columns: List[str],
        rows: List[List[Any]],
        row_count: int
    ) -> Dict[str, Any]:
        """Generate executive summary from actual query results.
        
        Returns {"summary": str, "summary_latency_ms": float}.
        """
        start = time.perf_counter()

        # Handle trivial cases without LLM call if preferred or empty
        if row_count == 0 or not rows:
            return {
                "summary": "No matching records were found in the dataset for this question.",
                "summary_latency_ms": round((time.perf_counter() - start) * 1000, 2)
            }

        client = self._get_genai_client()
        if not client:
            return {
                "summary": "Query executed successfully. (Configure GOOGLE_API_KEY to enable AI executive summaries.)",
                "summary_latency_ms": round((time.perf_counter() - start) * 1000, 2)
            }

        # Cap rows sent to Gemini to max 10 to keep prompt bounded and fast
        sample_rows = rows[:10]
        data_payload = {
            "columns": columns,
            "sample_rows": sample_rows,
            "total_rows_returned": row_count
        }

        user_prompt = f"""Business Question:
"{question}"

Query Result Data:
{json.dumps(data_payload, default=str)}

Write a 2-3 sentence executive summary of these results.
"""

        try:
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SUMMARY_SYSTEM_INSTRUCTION,
                    temperature=0.2,
                )
            )
            summary_text = (response.text or "").strip()
            if not summary_text:
                summary_text = FALLBACK_SUMMARY
                
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            return {
                "summary": summary_text,
                "summary_latency_ms": latency_ms
            }
        except Exception as e:
            logger.warning("Executive summary generation failed: %s", e)
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            return {
                "summary": FALLBACK_SUMMARY,
                "summary_latency_ms": latency_ms
            }


# Global summarizer instance
executive_summarizer = ExecutiveSummarizer()
