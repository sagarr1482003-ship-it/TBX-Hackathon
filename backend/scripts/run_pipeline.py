"""Run the agent pipeline against Groq (via Strands) for one question; report latency + verdict.

Usage:
    export GROQ_API_KEY=...            # or set it in .env
    python -m scripts.run_pipeline "how many debit transactions are there?"
    python -m scripts.run_pipeline           # runs a small default question set
"""

from __future__ import annotations

import sys

from app.config import get_settings
from app.services.model.groq_client import agent_for
from app.services.model.reviewer import _SYSTEM as REVIEWER_SYSTEM
from app.services.model.reviewer import ReviewerAgent
from app.services.model.sql_generator import _SYSTEM as GENERATOR_SYSTEM
from app.services.model.sql_generator import SqlGenerator
from app.services.pipeline.simple_pipeline import SimplePipeline

_DEFAULT_QUESTIONS = [
    "how many debit transactions are there?",
    "what is the total credit amount across all accounts?",
    "which bank has the most accounts?",
]


def _build() -> SimplePipeline:
    s = get_settings()
    key = s.groq_api_key or ""

    def gen_agent():
        return agent_for(
            key, s.sql_generator_model, GENERATOR_SYSTEM, base_url=s.groq_base_url,
            reasoning_effort=s.sql_generator_reasoning_effort,
        )

    def rev_agent():
        return agent_for(
            key, s.reviewer_model, REVIEWER_SYSTEM, base_url=s.groq_base_url,
            reasoning_effort=s.reviewer_reasoning_effort,
        )

    return SimplePipeline(SqlGenerator(gen_agent), ReviewerAgent(rev_agent))


def _run_one(pipeline: SimplePipeline, question: str) -> None:
    r = pipeline.run(question)
    print("=" * 72)
    print(f"Q: {question}")
    print(f"outcome: {r.outcome}   total: {r.total_ms} ms")
    if r.candidate:
        print(f"generated SQL: {r.candidate.sql}")
    if r.canonical_sql:
        print(f"canonical SQL: {r.canonical_sql}")
    if not r.validation_ok and r.validation_reason:
        print(f"validation: REJECTED — {r.validation_reason}")
    if r.verdict:
        print(f"verdict: {r.verdict.verdict} — {r.verdict.reason}")
    print(f"stages: {r.stage_ms}")
    print(f"latency budget (<=10s): {'OK' if r.total_ms <= 10_000 else 'OVER 10s'}")


def main() -> None:
    pipeline = _build()
    questions = [" ".join(sys.argv[1:])] if len(sys.argv) > 1 else _DEFAULT_QUESTIONS
    for q in questions:
        _run_one(pipeline, q)


if __name__ == "__main__":
    main()
