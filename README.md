# NoorTrade Agent Core

**A tool-using AI agent built from scratch — no LangChain, no framework.**

An analytical agent that answers business questions about Saudi retail sales data in
Arabic or English. It writes its own SQL, reads its own errors, corrects itself, and
refuses to state a number it did not measure.

> Unit 1 of a six-unit Agentic AI Engineering series. Each unit is a standalone
> repository and a component of a final integrated agent.

---

## Why build the loop by hand?

Most "AI agent" projects call `AgentExecutor.run()` and stop there. When the agent
fails — and it will — there is no diagnostic surface, because the loop is someone
else's code.

Everything here is explicit: the loop, the tool dispatch, the guards, the error
channel. Roughly 250 lines, and every one of them is debuggable.

---

## Architecture

```
┌──────────────────────────────────────────────────┐
│  LOCAL                                           │
│                                                  │
│   agent.py      the loop, language routing,      │
│                 turn/token guards                │
│   db_tools.py   tool definitions, business       │
│                 rules, 4 safety layers           │
│   noortrade.db  SQLite, read-only                │
│                                                  │
└───────────────────┬──────────────────────────────┘
                    │ HTTPS — text only
                    │ sends: question + tool schema + query results
                    │ gets:  text, or a tool-call request
                    ▼
┌──────────────────────────────────────────────────┐
│  Anthropic API — claude-sonnet-5                 │
│  stateless · no data access · no execution       │
└──────────────────────────────────────────────────┘
```

The model never touches the database. It proposes SQL; the application decides
whether to run it.

### The loop

```python
for turn in range(1, MAX_TURNS + 1):
    response = client.messages.create(..., tools=TOOLS, messages=messages)

    if response.stop_reason != "tool_use":
        return final_text                      # (a) done

    messages.append({"role": "assistant", "content": response.content})

    tool_results = [                           # (b) run tools, feed results back
        {"type": "tool_result", "tool_use_id": b.id,
         "content": execute_tool(b.name, b.input)}
        for b in response.content if b.type == "tool_use"
    ]
    messages.append({"role": "user", "content": tool_results})
```

---

## Design decisions

### 1. SQLite over direct Excel access

The model writes far better SQL than pandas code. Bad SQL raises a readable error the
agent can act on; bad pandas code fails silently or returns the wrong frame. A single
file also means no server and trivial deployment.

### 2. Defense in depth — four layers, not one

| Layer | Mechanism |
|---|---|
| 1 | Reject `INSERT / UPDATE / DELETE / DROP / ALTER / PRAGMA …` |
| 2 | Require the statement to start with `SELECT` or `WITH` |
| 3 | Reject embedded `;` (one statement per call) |
| 4 | **`sqlite3.connect("file:...?mode=ro", uri=True)`** |

Layers 1–3 are string filters and could in principle be worked around. Layer 4 is
enforced by SQLite itself. Never rely on text filtering alone — make the dangerous
operation impossible, not merely disallowed.

### 3. Tools never raise — they return errors as text

```python
except sqlite3.Error as e:
    return f"SQL ERROR: {e}"
```

An uncaught exception ends the session. An error string becomes a teaching signal
inside the same loop: the model reads it, fixes the SQL, retries. Self-correction is
not a model feature — it is a consequence of this design choice.

### 4. A `purpose` field the executor ignores

Every `run_sql` call must carry a one-line English `purpose`. It is never used at
runtime. It exists to force the model to state intent before acting, which both
improves the query and makes the execution trace readable.

### 5. Language is a property of the output, not of the system

Logs, SQL, schema text and system prompt are English. Only the final answer is
translated. Arabic in logs and queries makes a system harder to debug for no benefit.

---

## Case study: the failure that mattered

**First run** — "Top 3 cities by profit in 2024?"

```sql
SELECT City, ROUND(SUM(Gross_Profit_SAR),2) AS total_profit
FROM v_sales WHERE substr(Order_Date,1,4)='2024'
GROUP BY City ORDER BY total_profit DESC LIMIT 3
```

Arithmetically correct. Analytically misleading: `Gross_Profit_SAR` ignores returns.
152 returned orders in 2024 carried SAR 86,380 of profit that never materialised.

**The fix was not a better model or a smarter prompt.** Two rules were added to the
tool's schema description:

```
10. Gross_Profit_SAR ignores returns. For any profit question, compute BOTH
    gross and net = SUM(Gross_Profit_SAR) - SUM(COALESCE(Refund_Amount,0)).
11. Report profit erosion: 100.0 * SUM(COALESCE(Refund_Amount,0))
                                 / SUM(Gross_Profit_SAR)
```

**Second run, same question, same model:**

| City | Gross (SAR) | Net (SAR) | Erosion |
|---|---:|---:|---:|
| Riyadh | 626,047.69 | 548,715.54 | 12.35% |
| Jeddah | 411,502.11 | 337,244.66 | **18.05%** |
| Dammam | 194,853.08 | 165,875.38 | 14.87% |

The agent surfaced Jeddah's return problem unprompted and recommended a specific
action. Cost of the upgrade: 865 extra input tokens, 583 output, 3 seconds.

> When an agent gives an answer that is arithmetically right but analytically
> incomplete, the defect is in the tool description — not the model. Upgrading the
> model costs multiples and fixes nothing.

---

## Testing without spending tokens

`test_loop.py` swaps the Anthropic client for a scripted fake, so loop mechanics are
verified at zero cost.

| Test | Verifies |
|---|---|
| Self-correction | Bad column → `SQL ERROR` → corrected query → answer |
| `MAX_TURNS` guard | A model that loops forever stops at exactly 8 turns |
| Unknown tool | Returns an error string, does not crash |

It also asserts the message structure: role sequence, and that every `tool_result`
carries the matching `tool_use_id`.

---

## Data

Synthetic Saudi retail dataset — 8,020 orders · 2,000 customers · 34 products ·
400 returns · 8 cities · 3 channels (App / Online / Store) · 2022–2024.

`build_db.py` loads the workbook into SQLite, adds six indexes, and creates a
`v_sales` view joining orders, products and returns with `Gross_Profit_SAR` and
`Is_Returned` precomputed — every join removed from the model's responsibility is one
less thing it can get wrong.

**Data quality note:** the source `City` and `Channel` columns contain trailing
whitespace (`'Riyadh  '` vs `'Riyadh'`), which SQL treats as distinct values. Left
uncleaned, the agent reports Riyadh revenue short by SAR 195,637 — confidently. The
build script strips all string columns.

---

## Setup

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows
pip install -r requirements.txt

echo ANTHROPIC_API_KEY=sk-ant-... > .env
echo ANTHROPIC_MODEL=claude-sonnet-5 >> .env

python build_db.py
python check_setup.py
python test_loop.py                  # free
```

## Usage

```bash
python agent.py "ما أعلى ثلاث مدن من حيث الربح في 2024؟"
python agent.py "Top 3 cities by profit in 2024?"
python agent.py --lang both "قارن أداء القنوات الثلاث"
python agent.py                      # interactive; :ar :en :both :auto
```

Outputs: `answer.md` (the answer) and `trace.md` (every query, purpose, result and
token count).

**Typical run:** 2 turns · 1 query · ~6,400 in / ~1,100 out tokens · ~12 s.

---

## Known limitations

This is a foundation, not a production system.

| Limitation | Addressed in |
|---|---|
| No conversational memory | Unit 3 |
| SQL only — no documents | Units 2 & 4 |
| No accuracy measurement | Unit 5 |
| No cost or latency ceiling | Unit 5 |
| CLI only, no auth or audit log | Unit 6 |
| Tool results arrive as `user` role → injection surface | Unit 6 |

The most important gap is the absence of an evaluation harness. The agent answers with
identical confidence whether it is right or wrong — shipping it without measured
accuracy would be shipping an employee never tested.

---

## الملخص بالعربية

وكيل تحليلي يجيب على أسئلة الأعمال حول بيانات مبيعات سعودية، بالعربية أو الإنجليزية.

**بُني من الصفر بلا أي إطار جاهز** — الحلقة، وتوزيع الأدوات، وحواجز الأمان، وقناة
الأخطاء، كلها مكتوبة صراحةً وقابلة للتشخيص.

**مبادئ التصميم:**

- النموذج يقترح SQL، والتطبيق وحده ينفّذ — القاعدة مفتوحة للقراءة فقط على مستوى النظام
- الأدوات لا ترفع استثناءً؛ تعيد الخطأ نصاً ليقرأه النموذج ويصحّح نفسه
- المكابح مبنية في `for` لا `while`، فالتوقف مضمون بحكم بنية اللغة
- **جودة الوكيل = جودة وصف أدواته** — وليست جودة النموذج

**الدرس المحوري:** الوكيل أعطى رقماً صحيحاً حسابياً ومضلّلاً تحليلياً لأنه تجاهل
المرتجعات. الإصلاح كان **سطرين في وصف الأداة** — لا ترقية نموذج ولا prompt أذكى.

---

## Author

**Saleh Mahbub** — [github.com/Salehmsa](https://github.com/Salehmsa)
