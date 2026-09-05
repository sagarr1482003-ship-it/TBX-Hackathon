# Chat SSE endpoint — FE integration reference

**Endpoint:** `POST /api/chat/stream`
**Request body (JSON):** `{ "q": "<question, 1..1000 chars>" }`
**Response:** `text/event-stream` (Server-Sent Events)

The native browser `EventSource` is GET-only, so consume this with a `fetch()` streaming reader
(e.g. `@microsoft/fetch-event-source`).

## Event sequence (each pipeline stage streams live)

`intake` → `sql_generation` (start/done) → `static_validation` (start/ok|rejected) →
`reviewer_verdict` (start/verdict) → `execution` (start/row_count+chart) →
`answer_composition` (start/answer) → `completion`.

For a vague/out-of-scope question the stream is: `intake` → `sql_generation` → `clarification`
→ `completion` (with `outcome: "clarification_requested"` and the follow-up question).

The `completion` event carries the full answer payload: `outcome`, `answer_text`, `answer_source`,
`chart` (pie/bar/line spec for the FE to render), `verdict`, `breakdown` (columns + preview rows +
`total_row_count`), `resolved_sql`, `total_ms`.

## FE usage sketch

```js
import { fetchEventSource } from "@microsoft/fetch-event-source";

await fetchEventSource("/api/chat/stream", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ q: question }),
  onmessage(ev) {
    const data = JSON.parse(ev.data);
    switch (ev.event) {
      case "sql_generation":      showStage("Generating SQL…"); break;
      case "reviewer_verdict":    showStage("Reviewing…"); break;
      case "execution":           showStage("Querying…"); if (data.chart) renderChart(data.chart); break;
      case "answer_composition":  showStage("Composing…"); break;
      case "clarification":       askUser(data.question); break;
      case "completion":          render(data.answer_text, data.chart, data.breakdown); break;
    }
  },
});
```

---

## Captured live example (POST /api/chat/stream, q="what is the total transaction amount per bank")

```
=== STREAMED EVENTS (in order) ===
[intake] {"question": "what is the total transaction amount per bank"}
[sql_generation] {"status": "start"}
[sql_generation] {"status": "done", "sql": "SELECT b.bank_name, sum(t.transaction_amount) AS total FROM transaction t JOIN account a ON t.account_id = a.account_id JOIN bank b ON a.bank_code = b.bank_code GROUP BY b.bank_name ORDER BY total DESC"}
[static_validation] {"status": "start"}
[static_validation] {"status": "ok", "canonical_sql": "SELECT b.bank_name, SUM(t.transaction_amount) AS total FROM transaction AS t JOIN account AS a ON t.account_id = a.account_id JOIN bank AS b ON a.bank_code = b.bank_code GROUP BY b.bank_name ORDER BY total DESC LIMIT 1000"}
[reviewer_verdict] {"status": "start"}
[reviewer_verdict] {"verdict": "approve", "reason": "Correctly joins transaction\u2192account\u2192bank, sums transaction_amount grouped by bank_name, no sensitive columns selected, read-only, and join cardinality is sound (many-to-one at each step)."}
[execution] {"status": "start"}
[execution] {"row_count": 10, "chart": {"type": "bar", "label_field": "bank_name", "value_field": "total", "points": [{"label": "STATE BANK OF INDIA", "value": 292497443.3}, {"label": "KOTAK MAHINDRA BANK LIMITED", "value": 188732631.48}, {"label": "UNION BANK OF INDIA", "value": 177438686.09}, {"label": "ICICI BANK LIMITED", "value": 150670789.76}, {"label": "AU SMALL FINANCE BANK LIMITED", "value": 122947513.36}, {"label": "TAMILNAD MERCANTILE BANK LIMITED", "value": 117731849.43}, {"label": "RBL BANK LIMITED", "value": 115551686.64}, {"label": "CANARA BANK", "value": 109025635.83}, {"label": "AXIS BANK LIMITED", "value": 98223592.12}, {"label": "HDFC BANK LIMITED", "value": 63828378.54}]}}
[answer_composition] {"status": "start"}
[answer_composition] {"answer": "10 rows (showing 5 of 10):\nbank_name=STATE BANK OF INDIA, total=292497443.30\nbank_name=KOTAK MAHINDRA BANK LIMITED, total=188732631.48\nbank_name=UNION BANK OF INDIA, total=177438686.09\nbank_name=ICICI BANK LIMITED, total=150670789.76\nbank_name=AU SMALL FINANCE BANK LIMITED, total=122947513.36"}

=== COMPLETION PAYLOAD (full) ===
{
  "question": "what is the total transaction amount per bank",
  "outcome": "answered",
  "clarification": null,
  "resolved_sql": "SELECT b.bank_name, SUM(t.transaction_amount) AS total FROM transaction AS t JOIN account AS a ON t.account_id = a.account_id JOIN bank AS b ON a.bank_code = b.bank_code GROUP BY b.bank_name ORDER BY total DESC LIMIT 1000",
  "answer_text": "10 rows (showing 5 of 10):\nbank_name=STATE BANK OF INDIA, total=292497443.30\nbank_name=KOTAK MAHINDRA BANK LIMITED, total=188732631.48\nbank_name=UNION BANK OF INDIA, total=177438686.09\nbank_name=ICICI BANK LIMITED, total=150670789.76\nbank_name=AU SMALL FINANCE BANK LIMITED, total=122947513.36",
  "answer_source": "template_fallback",
  "chart": {
    "type": "bar",
    "label_field": "bank_name",
    "value_field": "total",
    "points": [
      {
        "label": "STATE BANK OF INDIA",
        "value": 292497443.3
      },
      {
        "label": "KOTAK MAHINDRA BANK LIMITED",
        "value": 188732631.48
      },
      {
        "label": "UNION BANK OF INDIA",
        "value": 177438686.09
      },
      {
        "label": "ICICI BANK LIMITED",
        "value": 150670789.76
      },
      {
        "label": "AU SMALL FINANCE BANK LIMITED",
        "value": 122947513.36
      },
      {
        "label": "TAMILNAD MERCANTILE BANK LIMITED",
        "value": 117731849.43
      },
      {
        "label": "RBL BANK LIMITED",
        "value": 115551686.64
      },
      {
        "label": "CANARA BANK",
        "value": 109025635.83
      },
      {
        "label": "AXIS BANK LIMITED",
        "value": 98223592.12
      },
      {
        "label": "HDFC BANK LIMITED",
        "value": 63828378.54
      }
    ]
  },
  "verdict": {
    "verdict": "approve",
    "reason": "Correctly joins transaction\u2192account\u2192bank, sums transaction_amount grouped by bank_name, no sensitive columns selected, read-only, and join cardinality is sound (many-to-one at each step)."
  },
  "breakdown": {
    "columns": [
      "bank_name",
      "total"
    ],
    "rows": [
      {
        "bank_name": "STATE BANK OF INDIA",
        "total": "292497443.30"
      },
      {
        "bank_name": "KOTAK MAHINDRA BANK LIMITED",
        "total": "188732631.48"
      },
      {
        "bank_name": "UNION BANK OF INDIA",
        "total": "177438686.09"
      },
      {
        "bank_name": "ICICI BANK LIMITED",
        "total": "150670789.76"
      },
      {
        "bank_name": "AU SMALL FINANCE BANK LIMITED",
        "total": "122947513.36"
      },
      {
        "bank_name": "TAMILNAD MERCANTILE BANK LIMITED",
        "total": "117731849.43"
      },
      {
        "bank_name": "RBL BANK LIMITED",
        "total": "115551686.64"
      },
      {
        "bank_name": "CANARA BANK",
        "total": "109025635.83"
      },
      {
        "bank_name": "AXIS BANK LIMITED",
        "total": "98223592.12"
      },
      {
        "bank_name": "HDFC BANK LIMITED",
        "total": "63828378.54"
      }
    ],
    "total_row_count": 10
  },
  "validation_ok": true,
  "validation_reason": null,
  "total_ms": 36760
}```
