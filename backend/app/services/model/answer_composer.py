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

from app.services.model.groq_client import agent_text_with_usage

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
- State the currency as INR and use the INDIAN convention: group digits as lakh/crore
  (e.g. INR 7,75,97,697.30) and you may phrase large amounts in crore/lakh (e.g. "77.60 crore").
  Never use $ or dollars. When computed_metrics provides *_inr / *_words fields, prefer those.
- Be direct: no preamble, no markdown, just the answer sentence.
"""


class AnswerComposer:
    def __init__(self, agent_factory, *, sample_rows: int = 10) -> None:
        self._agent_factory = agent_factory
        self.last_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        self.last_computed: dict = {}
        self._sample_rows = sample_rows

    @property
    def system_prompt(self) -> str:
        return _SYSTEM

    @staticmethod
    def _run_calculators(question: str, columns: list[str], rows: list[dict]) -> dict:
        """Run the relevant deterministic calculator tools over the executed rows.

        Keyword-routed so we only compute what the question asks for. All math is Decimal in the
        calculators; the LLM only states the returned figures. Returns {tool: result}.
        """
        import re

        from app.services.pipeline.calculators import (
            anomaly_calculator,
            cashflow_calculator,
            gst_calculator,
        )

        q = question.lower()
        out: dict = {}
        if "gst" in q or "tax" in q:
            # Extract an explicit rate like "18%" / "18 percent"; else default 18%.
            m = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|percent)", q)
            rate = (float(m.group(1)) / 100.0) if m else 0.18
            out["gst"] = gst_calculator(rows, columns, rate=rate)
        if any(k in q for k in ("cash flow", "cashflow", "net flow", "inflow", "outflow", "net")):
            out["cashflow"] = cashflow_calculator(rows, columns)
        if any(k in q for k in ("anomaly", "anomalies", "outlier", "unusual", "spike", "fraud")):
            out["anomaly"] = anomaly_calculator(rows, columns)
        # Keep only applicable results to avoid confusing the LLM with N/A tools.
        return {k: v for k, v in out.items() if v.get("applicable")}

    def compose(
        self, question: str, columns: list[str], rows: list[dict], total_rows: int | None = None
    ) -> str:
        agent: Agent = self._agent_factory()
        # The LLM NEVER receives a large result set: cap the sample hard. A big listing is
        # summarised by its total_rows count, not enumerated — this keeps tokens/latency bounded
        # and grounding tight regardless of whether the query returned 1 row or 1000.
        sample = rows[: self._sample_rows]
        total = total_rows if total_rows is not None else len(rows)
        # Run the deterministic calculator TOOLS over ALL rows (not the sample). The LLM does not
        # do the math — it picks which pre-computed figures are relevant to the question and
        # states them. Rates/assumptions are echoed so the answer stays honest.
        computed = self._run_calculators(question, columns, rows)
        self.last_computed = computed
        payload = {
            "columns": columns,
            "sample_rows": sample,
            "total_rows": total,
            "computed_metrics": computed,
            "note": (
                "sample_rows is ONLY a preview of total_rows results. Answer with the "
                "total_rows count and, if present, the date range. Do NOT state or characterise "
                "any amount, value, or that rows share a value — the preview is not "
                "representative of all rows. If computed_metrics has a value relevant to the "
                "question (GST, cash flow, anomalies), state it verbatim and mention any stated "
                "assumption (e.g. the GST rate)."
                if total > len(sample)
                else (
                    "sample_rows is the complete result. If computed_metrics is relevant to the "
                    "question (GST, cash flow, anomalies), state those figures verbatim including "
                    "any stated assumption (e.g. the GST rate)."
                )
            ),
        }
        prompt = (
            f"Question: {question}\n"
            f"Result (JSON): {json.dumps(payload, default=str)}\n"
            "Write the one-sentence answer."
        )
        text, self.last_usage = agent_text_with_usage(agent, prompt)
        return text.strip()
