"""
db_tools.py — طبقة الأدوات لوكيل NoorTrade

هذا الملف يحتوي ما "يستطيع" الوكيل فعله. لا شيء غير ذلك.
الوكيل لا يلمس القاعدة مباشرة أبداً — يمرّ من هنا حصراً.

ثلاثة أجزاء:
  1. SCHEMA_DESCRIPTION : ما يعرفه النموذج عن بياناتك
  2. TOOLS             : التعريف الرسمي للأدوات كما يراه الـ API
  3. run_sql / execute : التنفيذ الفعلي بلغة Python
"""

import re
import sqlite3
from pathlib import Path

DB_PATH = Path("data/noortrade.db")
MAX_ROWS = 200          # سقف الصفوف المُعادة للنموذج
MAX_CHARS = 6000        # سقف حجم النتيجة النصية


# ══════════════════════════════════════════════════════════════
# 1) وصف المخطط — أهم نص في المشروع كله
# ══════════════════════════════════════════════════════════════
# كل سطر هنا يمنع خطأً محتملاً. النموذج لا يرى بياناتك،
# يرى هذا النص فقط. وصف ناقص = SQL خاطئ = رقم خاطئ بثقة.

SCHEMA_DESCRIPTION = """
قاعدة بيانات NoorTrade — شركة تجزئة سعودية. SQLite. قراءة فقط.

═══ العرض الرئيسي: v_sales ═══
استخدم هذا العرض لمعظم الأسئلة. يدمج الطلبات والمنتجات والمرتجعات مسبقاً.

  Order_ID          TEXT     معرّف الطلب
  Order_Date        TEXT     تاريخ الطلب بصيغة 'YYYY-MM-DD' (نص وليس تاريخاً)
  Customer_ID       TEXT     معرّف العميل
  Product_ID        TEXT     معرّف المنتج
  Product_Name      TEXT     اسم المنتج بالإنجليزية
  Category          TEXT     الفئة: Electronics, Sports, Home, Fashion, Beauty
  Quantity          INTEGER  الكمية
  Unit_Price        INTEGER  سعر الوحدة قبل الخصم بالريال
  Discount_Pct      REAL     الخصم ككسر عشري من 0 إلى 0.3  (0.15 يعني 15%)
  Total_SAR         REAL     ★ الإيراد الفعلي بعد الخصم — استخدمه لكل أسئلة المبيعات
  Unit_Cost         REAL     تكلفة الوحدة بالريال
  Gross_Profit_SAR  REAL     ★ الربح الإجمالي المحسوب مسبقاً = Total_SAR - (Unit_Cost * Quantity)
  Channel           TEXT     قناة البيع: App, Online, Store
  City              TEXT     Riyadh, Jeddah, Dammam, Khobar, Mecca, Medina, Tabuk, Abha
  Payment_Method    TEXT     طريقة الدفع
  Is_Returned       INTEGER  1 إذا أُرجع الطلب، 0 إذا لا
  Refund_Amount     REAL     مبلغ الاسترداد، NULL إذا لم يُرجع
  Return_Reason     TEXT     سبب الإرجاع، NULL إذا لم يُرجع

═══ الجداول الأساسية ═══
orders     (8020) : Order_ID, Order_Date, Customer_ID, Product_ID, Quantity,
                    Unit_Price, Discount_Pct, Total_SAR, Channel, City, Payment_Method
customers  (2000) : Customer_ID, Customer_Name, Email, Gender, Age, City, Signup_Date
products     (34) : Product_ID, Product_Name, Category, Unit_Price, Unit_Cost
returns     (400) : Return_ID, Order_ID, Return_Date, Reason, Refund_Amount

═══ قواعد إلزامية ═══
1. الإيراد = SUM(Total_SAR) وليس Unit_Price * Quantity (يتجاهل الخصم).
2. الربح = SUM(Gross_Profit_SAR) — محسوب مسبقاً، لا تعد حسابه.
3. التواريخ نصية: استخدم substr(Order_Date,1,4) للسنة، substr(Order_Date,1,7) للشهر.
4. نطاق البيانات: 2022-01-01 إلى 2024-12-31 فقط. لا توجد بيانات 2025 أو بعدها.
5. معدل الإرجاع = 100.0 * SUM(Is_Returned) / COUNT(*).
6. صافي الإيراد = SUM(Total_SAR) - SUM(COALESCE(Refund_Amount, 0)).
7. اربط العميل عبر Customer_ID مع جدول customers لبيانات العمر والجنس.
8. استخدم ROUND(...,2) على كل قيمة مالية.
9. جدول customers فيه Age قد تكون NULL — استخدم WHERE Age IS NOT NULL عند حسابها.

10. ★ المرتجعات: Gross_Profit_SAR يتجاهل المرتجعات تماماً.
    عند أي سؤال عن الربح أو الأداء المالي، احسب المقياسين معاً في نفس الاستعلام:
      الربح الإجمالي : SUM(Gross_Profit_SAR)
      الربح الصافي   : SUM(Gross_Profit_SAR) - SUM(COALESCE(Refund_Amount,0))
    واذكر الاثنين في إجابتك. إن اختلف الترتيب بينهما، نبّه على ذلك صراحةً.

11. ★ معدل تآكل الربح بالمرتجعات مقياس إداري مهم:
      100.0 * SUM(COALESCE(Refund_Amount,0)) / SUM(Gross_Profit_SAR)
    أضفه عند مقارنة أداء المدن أو الفئات أو القنوات — الفروق بينها ذات دلالة.
"""


# ══════════════════════════════════════════════════════════════
# 2) تعريف الأدوات — الصيغة التي يفهمها الـ API
# ══════════════════════════════════════════════════════════════

TOOLS = [
    {
        "name": "run_sql",
        "description": (
            "ينفّذ استعلام SELECT على قاعدة بيانات مبيعات NoorTrade ويعيد النتيجة كجدول. "
            "استخدم هذه الأداة لكل سؤال يتطلب رقماً أو حقيقة من البيانات. "
            "لا تخمّن أي رقم أبداً — نفّذ استعلاماً. "
            "يُسمح بـ SELECT فقط؛ أي أمر تعديل سيُرفض. "
            "إن أعاد الاستعلام خطأً، اقرأ رسالة الخطأ وصحّح الاستعلام وأعد المحاولة."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "استعلام SELECT صالح بلغة SQLite.",
                },
                "purpose": {
                    "type": "string",
                    "description": "A short ENGLISH sentence explaining what this query measures. Always English, never Arabic — this goes to a technical log.",
                },
            },
            "required": ["sql", "purpose"],
        },
    }
]


# ══════════════════════════════════════════════════════════════
# 3) التنفيذ الفعلي
# ══════════════════════════════════════════════════════════════

_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|PRAGMA|VACUUM)\b",
    re.IGNORECASE,
)


def _connect() -> sqlite3.Connection:
    """اتصال للقراءة فقط — حتى لو تجاوز الوكيل كل الفحوص، القاعدة محميّة."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"{DB_PATH} not found -- run build_db.py first")
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def run_sql(sql: str, purpose: str = "") -> str:
    """
    ينفّذ SELECT ويعيد نصاً.

    مبدأ جوهري: هذه الدالة لا ترفع استثناءً أبداً.
    كل خطأ يُعاد كنص للنموذج ليقرأه ويصحّح نفسه.
    استثناء غير ملتقط = انهيار الوكيل. نص خطأ = فرصة تصحيح ذاتي.
    """
    sql = sql.strip().rstrip(";")

    # حاجز 1: الأوامر المدمّرة
    if _FORBIDDEN.search(sql):
        return "ERROR: Only SELECT queries are allowed. Rewrite this as a read-only query."

    # حاجز 2: يجب أن يبدأ بـ SELECT أو WITH
    if not re.match(r"^\s*(SELECT|WITH)\b", sql, re.IGNORECASE):
        return "ERROR: Query must start with SELECT or WITH."

    # حاجز 3: استعلام واحد فقط — يمنع حقن أمر ثانٍ
    if ";" in sql:
        return "ERROR: Only one statement per call. Remove the semicolon."

    try:
        with _connect() as conn:
            cur = conn.cursor()
            cur.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchmany(MAX_ROWS + 1)
    except sqlite3.Error as e:
        # هذا النص يعود للنموذج ليصحّح استعلامه
        return f"SQL ERROR: {e}"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"

    if not rows:
        return "EMPTY RESULT: no matching rows. Check your WHERE clause -- the data may not exist for this filter."

    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]

    out = _to_table(cols, rows)
    if truncated:
        out += f"\n\n[TRUNCATED at {MAX_ROWS} rows -- use aggregation or LIMIT]"
    if len(out) > MAX_CHARS:
        out = out[:MAX_CHARS] + "\n\n[TRUNCATED -- result too large]"
    return out


def _to_table(cols, rows) -> str:
    """جدول نصي مصفوف الأعمدة — أسهل على النموذج من CSV خام."""
    data = [cols] + [[("NULL" if v is None else str(v)) for v in r] for r in rows]
    widths = [max(len(r[i]) for r in data) for i in range(len(cols))]
    line = "-+-".join("-" * w for w in widths)
    head = " | ".join(c.ljust(widths[i]) for i, c in enumerate(cols))
    body = "\n".join(
        " | ".join(c.ljust(widths[i]) for i, c in enumerate(r)) for r in data[1:]
    )
    return f"{head}\n{line}\n{body}\n\n({len(rows)} rows)"


# ══════════════════════════════════════════════════════════════
# 4) الموزّع — يربط اسم الأداة بدالتها
# ══════════════════════════════════════════════════════════════

_REGISTRY = {"run_sql": run_sql}


def execute_tool(name: str, args: dict) -> str:
    """
    ينفّذ أداة بالاسم. النموذج قد يطلب أداة غير موجودة — نعيد نصاً لا استثناء.
    """
    fn = _REGISTRY.get(name)
    if fn is None:
        return f"ERROR: no tool named '{name}'. Available tools: {list(_REGISTRY)}"
    try:
        return fn(**args)
    except TypeError as e:
        return f"ERROR: bad arguments for tool '{name}': {e}"


if __name__ == "__main__":
    # اختبار سريع بلا استدعاء API
    tests = [
        ("استعلام صحيح", "SELECT City, ROUND(SUM(Total_SAR),2) rev FROM v_sales GROUP BY City ORDER BY rev DESC LIMIT 3"),
        ("خطأ إملائي",   "SELECT Citty FROM v_sales LIMIT 1"),
        ("أمر مدمّر",     "DROP TABLE orders"),
        ("حقن أمر ثانٍ",  "SELECT 1; DROP TABLE orders"),
        ("نتيجة فارغة",   "SELECT * FROM v_sales WHERE City = 'Paris'"),
    ]
    for label, q in tests:
        print("=" * 64)
        print(f"[{label}]  {q}")
        print("-" * 64)
        print(run_sql(q))
