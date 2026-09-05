"""Answer_Composer — a Strands agent turns executed rows into a natural-language answer (Req 16).

Grounding rule: the DB computes every number; the model only phrases them. The composer is given
the question and the executed result rows (already masked for sensitive columns) and must reuse the
values verbatim — it may not invent or recompute figures. The Groundedness_Checker (already built)
is the backstop that rejects any number in the prose that is not present in the rows.

Runs on the configured Groq model via the Strands OpenAIModel provider, plain-text output.
"""

from __future__ import annotations

import json

from strands import Agent

from app.services.model.groq_client import agent_text

_SYSTEM = """You are a finance assistant that writes ONE concise, factual sentence (max 40 words)
answering the user's question from the provided result rows.

Strict rules:
- Use ONLY the numbers and values exactly as they appear in the rows. Never invent, round, or
  recompute any figure. Copy amounts and counts verbatim.
- sample_rows is a PREVIEW of at most a few rows. NEVER claim a property holds for "all",
  "each", or "every" row based on the sample. If total_rows exceeds the sample, describe it as
  "the first N of total_rows" and state the count — do not generalise the sample's values.
- For a large listing, answer with the total_rows count and the date range if present, not by
  characterising the amounts.
- Do not reveal masked values (shown with bullet characters) other than as given.
- State the currency as INR for monetary amounts.
- Be direct: no preamble, no markdown, just the answer sentence.
"""


class AnswerComposer:
    def __init__(self, agent_factory, *, sample_rows: int = 10) -> None:
        self._agent_factory = agent_factory
        self._sample_rows = sample_rows

    @property
    def system_prompt(self) -> str:
        return _SYSTEM

    def compose(self, question: str, columns: list[str], rows: list[dict]) -> str:
        agent: Agent = self._agent_factory()
        # The LLM NEVER receives a large result set: cap the sample hard. A big listing is
        # summarised by its total_rows count, not enumerated — this keeps tokens/latency bounded
        # and grounding tight regardless of whether the query returned 1 row or 1000.
        sample = rows[: self._sample_rows]
        payload = {
            "columns": columns,
            "sample_rows": sample,
            "total_rows": len(rows),
            "note": (
                "sample_rows is a preview; there are total_rows in all. "
                "Summarise counts/totals; do not claim to list every row."
                if len(rows) > len(sample)
                else "sample_rows is the complete result."
            ),
        }
        prompt = (
            f"Question: {question}\n"
            f"Result (JSON): {json.dumps(payload, default=str)}\n"
            "Write the one-sentence answer."
        )
        return agent_text(agent, prompt).strip()
