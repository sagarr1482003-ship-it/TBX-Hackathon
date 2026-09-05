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
- Do not reveal masked values (shown with bullet characters) other than as given.
- State the currency as INR for monetary amounts.
- Be direct: no preamble, no markdown, just the answer sentence.
"""


class AnswerComposer:
    def __init__(self, agent_factory) -> None:
        self._agent_factory = agent_factory

    @property
    def system_prompt(self) -> str:
        return _SYSTEM

    def compose(self, question: str, columns: list[str], rows: list[dict]) -> str:
        agent: Agent = self._agent_factory()
        # Give the model only a bounded sample of the rows (grounding + token thrift).
        sample = rows[:20]
        payload = {"columns": columns, "rows": sample, "total_rows": len(rows)}
        prompt = (
            f"Question: {question}\n"
            f"Result rows (JSON): {json.dumps(payload, default=str)}\n"
            "Write the one-sentence answer."
        )
        return agent_text(agent, prompt).strip()
