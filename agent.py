"""
agent.py — حلقة وكيل NoorTrade (ثنائي اللغة: عربي / إنجليزي)
             NoorTrade agent loop (bilingual: Arabic / English)

الوكيل يجيب بلغة السؤال تلقائياً، أو بلغة تفرضها أنت.
The agent replies in the question's language, or in a language you force.

التشغيل / Usage:
    python agent.py "ما أعلى ثلاث مدن ربحاً في 2024؟"        -> عربي
    python agent.py "Top 3 cities by profit in 2024?"         -> English
    python agent.py --lang both "أعلى المدن ربحاً؟"            -> both
    python agent.py --lang en   "أعلى المدن ربحاً؟"            -> forced English
    python agent.py                                            -> interactive
"""

import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
import anthropic

from db_tools import TOOLS, SCHEMA_DESCRIPTION, execute_tool

load_dotenv()

MODEL = os.environ.get("ANTHROPIC_MODEL", "").strip() or "claude-sonnet-5"
MAX_TURNS = 8
MAX_TOKENS = 2048
ANSWER_FILE = Path("answer.md")
TRACE_FILE = Path("trace.md")

client = anthropic.Anthropic()

_ARABIC = re.compile(r"[؀-ۿ]")


def detect_lang(text: str) -> str:
    """
    كشف اللغة بعدّ الحروف العربية مقابل اللاتينية.
    Language detection by counting Arabic vs Latin letters.

    لماذا لا نستخدم مكتبة كشف لغة؟ لأنها تضيف تبعية ثقيلة
    لحل مشكلة تُحسم بسطرين هنا. الأسئلة قصيرة والحسم قاطع.
    """
    ar = len(_ARABIC.findall(text))
    en = len(re.findall(r"[A-Za-z]", text))
    return "ar" if ar >= en else "en"


# ══════════════════════════════════════════════════════════════
# تعليمات اللغة — الجزء الوحيد الذي يتغير بين الأوضاع
# ══════════════════════════════════════════════════════════════
LANG_RULES = {
    "ar": """أجب بالعربية الفصحى حصراً، بلغة أعمال واضحة لا بلغة تقنية.
أنهِ الإجابة بقسم بعنوان "## التوصية" يحتوي إجراءً عملياً واحداً محدداً.
اكتب الأرقام بفواصل الآلاف: 4,514,694 ريال — لا 4514693.7.
أسماء المدن والفئات في البيانات إنجليزية؛ ترجمها في إجابتك
(Riyadh=الرياض, Jeddah=جدة, Dammam=الدمام, Khobar=الخبر, Mecca=مكة,
 Medina=المدينة, Tabuk=تبوك, Abha=أبها, Electronics=إلكترونيات,
 Sports=رياضة, Home=منزل, Fashion=أزياء, Beauty=تجميل,
 App=التطبيق, Online=المتجر الإلكتروني, Store=الفرع).""",

    "en": """Answer in English only, in clear business language, not technical jargon.
End with a section titled "## Recommendation" containing one specific action.
Format numbers with thousand separators: SAR 4,514,694 — not 4514693.7.""",

    "both": """Answer in BOTH languages, Arabic first then English.
Use exactly this structure:

## الإجابة
<الإجابة بالعربية الفصحى، بلغة أعمال>

## التوصية
<إجراء عملي واحد محدد>

---

## Answer
<the same answer in English>

## Recommendation
<the same single action in English>

Both versions must carry identical numbers and identical conclusions.
Arabic numbers: 4,514,694 ريال — English: SAR 4,514,694.
Translate city and category names in the Arabic part
(Riyadh=الرياض, Jeddah=جدة, Dammam=الدمام, Khobar=الخبر, Mecca=مكة,
 Medina=المدينة, Tabuk=تبوك, Abha=أبها, Electronics=إلكترونيات,
 Sports=رياضة, Home=منزل, Fashion=أزياء, Beauty=تجميل).""",
}


def build_system_prompt(lang: str) -> str:
    return f"""You are a senior data analyst at NoorTrade, a Saudi retail company.
You answer business questions using ONLY the real data in the database.

Binding rules:
1. Never state a number that did not come from the run_sql tool. Never guess or estimate.
2. Always query first. Think about which number actually answers the question.
3. If you need several angles, run several queries, one at a time.
4. If a query returns an error, read it, fix the SQL, and retry.
5. If a result is EMPTY, say the data is not available. Never say the value is zero.
6. Do not expose SQL or column names in your final answer — write for a business reader.

Language of your final answer:
{LANG_RULES[lang]}

Database schema available to you:
{SCHEMA_DESCRIPTION}
"""


def log(msg: str) -> None:
    """Technical log — English only, because the terminal cannot shape Arabic."""
    print(msg, flush=True)


def run_agent(question: str, lang: str = "auto"):
    """The loop: send -> check stop_reason -> run tools -> return results -> repeat."""
    if lang == "auto":
        lang = detect_lang(question)

    messages = [{"role": "user", "content": question}]
    trace = [f"# أثر التنفيذ / Execution Trace\n\n"
             f"**Question:** {question}\n\n**Answer language:** `{lang}`\n"]
    total_in = total_out = 0
    sql_count = 0
    t0 = time.time()

    log(f"lang={lang}")

    for turn in range(1, MAX_TURNS + 1):
        log(f"\n--- turn {turn}/{MAX_TURNS} ---")

        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=build_system_prompt(lang),
            tools=TOOLS,
            messages=messages,
        )

        total_in += response.usage.input_tokens
        total_out += response.usage.output_tokens
        log(f"stop_reason={response.stop_reason}  "
            f"tokens: in={response.usage.input_tokens} out={response.usage.output_tokens}")

        # ═══ (أ) انتهى ═══
        if response.stop_reason != "tool_use":
            answer = "".join(b.text for b in response.content if b.type == "text")
            elapsed = time.time() - t0
            log("\n=== DONE ===")
            log(f"turns={turn}  sql_queries={sql_count}  "
                f"tokens: in={total_in} out={total_out}  time={elapsed:.1f}s")
            trace.append(f"\n---\n\n**Stats:** {turn} turns | {sql_count} queries | "
                         f"in={total_in} out={total_out} tokens | {elapsed:.1f}s\n")
            return answer, "\n".join(trace)

        # ═══ (ب) طلب أدوات ═══
        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type == "text" and block.text.strip():
                trace.append(f"\n## Thinking (turn {turn})\n\n{block.text.strip()}\n")
                log(f"[thinking] {len(block.text)} chars -> trace.md")

            if block.type != "tool_use":
                continue

            sql_count += 1
            args = block.input
            sql_clean = " ".join(args.get("sql", "").split())
            log(f"[tool] {block.name}  #{sql_count}")
            log(f"  purpose: {args.get('purpose', '-')}")
            log(f"  sql: {sql_clean[:200]}")

            result = execute_tool(block.name, args)
            status = "ERROR" if result.startswith(("ERROR", "SQL ERROR", "EMPTY")) else "OK"
            log(f"  -> [{status}] {result.splitlines()[0][:90]}")

            trace.append(
                f"\n## Query {sql_count} (turn {turn})\n\n"
                f"**Purpose:** {args.get('purpose','-')}\n\n"
                f"```sql\n{sql_clean}\n```\n\n"
                f"**Result:**\n\n```\n{result[:1500]}\n```\n"
            )

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})

    log(f"\n!!! MAX_TURNS ({MAX_TURNS}) reached — loop stopped by guard")
    msg = ("لم أصل إلى إجابة نهائية ضمن الحد المسموح من الخطوات. جرّب سؤالاً أضيق."
           if lang == "ar" else
           "Could not reach a final answer within the step limit. Try a narrower question.")
    return msg, "\n".join(trace)


def ask(question: str, lang: str = "auto") -> None:
    log("\n" + "=" * 60)
    log(f"model={MODEL}  max_turns={MAX_TURNS}")
    log("=" * 60)

    try:
        answer, trace = run_agent(question, lang)
    except anthropic.APIError as e:
        log(f"\nAPI ERROR: {type(e).__name__}: {e}")
        return

    ANSWER_FILE.write_text(
        f"# {question}\n\n---\n\n{answer}\n", encoding="utf-8")
    TRACE_FILE.write_text(trace, encoding="utf-8")
    log(f"\n>>> answer : {ANSWER_FILE.resolve()}")
    log(f">>> trace  : {TRACE_FILE.resolve()}")


def parse_args(argv):
    lang = "auto"
    if "--lang" in argv:
        i = argv.index("--lang")
        lang = argv[i + 1]
        del argv[i:i + 2]
    if lang not in {"auto", "ar", "en", "both"}:
        sys.exit("ERROR: --lang must be one of: auto, ar, en, both")
    return lang, " ".join(argv)


if __name__ == "__main__":
    lang, question = parse_args(sys.argv[1:])

    if question:
        ask(question, lang)
    else:
        log("NoorTrade Agent — bilingual")
        log("Ask in Arabic or English. Commands: :ar  :en  :both  :auto  exit")
        while True:
            try:
                q = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if q.lower() in {"exit", "quit", "q", ""}:
                break
            if q.startswith(":"):
                cmd = q[1:].strip().lower()
                if cmd in {"ar", "en", "both", "auto"}:
                    lang = cmd
                    log(f"language mode -> {lang}")
                else:
                    log("unknown command. use :ar :en :both :auto")
                continue
            ask(q, lang)
