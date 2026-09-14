"""
test_loop.py — اختبار حلقة الوكيل بدون أي استدعاء API (تكلفة = صفر)

نستبدل عميل Anthropic بعميل وهمي يعيد ردوداً محضّرة،
فنتحقق من ميكانيكا الحلقة وحدها: هل تنفّذ الأدوات؟
هل تعيد النتائج بالشكل الصحيح؟ هل تتوقف عند الحد؟
"""
import types
import agent


class Blk:
    """بلوك وهمي يحاكي بنية رد الـ API"""
    def __init__(self, **kw):
        self.__dict__.update(kw)


class Usage:
    input_tokens = 100
    output_tokens = 50


class Resp:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content
        self.usage = Usage()


def make_fake(script):
    """يعيد ردود السيناريو بالترتيب، ويسجّل الرسائل المرسلة"""
    calls = {"n": 0, "sent": []}

    def create(**kw):
        calls["sent"].append(kw["messages"])
        r = script[calls["n"]]
        calls["n"] += 1
        return r

    return create, calls


# ═══ السيناريو: استعلام خاطئ -> تصحيح -> إجابة نهائية ═══
script = [
    Resp("tool_use", [
        Blk(type="text", text="سأبدأ بفحص الإيراد حسب المدينة."),
        Blk(type="tool_use", id="tu_1", name="run_sql",
            input={"sql": "SELECT Citty, SUM(Total_SAR) FROM v_sales GROUP BY Citty",
                   "purpose": "revenue by city"}),
    ]),
    Resp("tool_use", [
        Blk(type="tool_use", id="tu_2", name="run_sql",
            input={"sql": "SELECT City, ROUND(SUM(Total_SAR),2) rev FROM v_sales GROUP BY City ORDER BY rev DESC LIMIT 3",
                   "purpose": "corrected: revenue by city"}),
    ]),
    Resp("end_turn", [
        Blk(type="text", text="الرياض تتصدر بـ 4,514,694 ريال.\n\n## التوصية\nركّز الحملة القادمة على جدة."),
    ]),
]

fake_create, calls = make_fake(script)
agent.client = types.SimpleNamespace(messages=types.SimpleNamespace(create=fake_create))

print("#" * 64)
print("# TEST 1: self-correction after SQL error")
print("#" * 64)
answer, trace = agent.run_agent("ما أعلى المدن ربحاً؟", "ar")
print("\nFINAL ANSWER:\n", answer)

# ── فحوص البنية ──
print("\n" + "#" * 64)
print("# STRUCTURE CHECKS")
print("#" * 64)
msgs = calls["sent"][-1]
print(f"API calls made          : {calls['n']}  (expected 3)")
print(f"messages in last call   : {len(msgs)}  (expected 5)")
roles = [m["role"] for m in msgs]
print(f"role sequence           : {roles}")

tr = msgs[2]["content"][0]
print(f"tool_result linked id   : {tr['tool_use_id']}  (expected tu_1)")
print(f"error passed to model   : {tr['content'][:40]!r}")

# ── فحص المكابح ──
print("\n" + "#" * 64)
print("# TEST 2: MAX_TURNS guard (infinite tool loop)")
print("#" * 64)
loop_forever = [Resp("tool_use", [
    Blk(type="tool_use", id=f"tu_{i}", name="run_sql",
        input={"sql": "SELECT 1", "purpose": "loop"})]) for i in range(20)]
fake2, calls2 = make_fake(loop_forever)
agent.client = types.SimpleNamespace(messages=types.SimpleNamespace(create=fake2))
out, _ = agent.run_agent("سؤال يسبب حلقة لا نهائية", "ar")
print(f"\nAPI calls made : {calls2['n']}  (expected {agent.MAX_TURNS})")
print(f"returned       : {out[:60]}")

# ── فحص أداة غير موجودة ──
print("\n" + "#" * 64)
print("# TEST 3: unknown tool name")
print("#" * 64)
script3 = [
    Resp("tool_use", [Blk(type="tool_use", id="tu_x", name="delete_everything", input={})]),
    Resp("end_turn", [Blk(type="text", text="تم.")]),
]
fake3, calls3 = make_fake(script3)
agent.client = types.SimpleNamespace(messages=types.SimpleNamespace(create=fake3))
agent.run_agent("احذف كل شيء", "en")
print(f"\nresult sent to model: {calls3['sent'][-1][2]['content'][0]['content'][:70]!r}")
