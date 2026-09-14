"""check_setup.py - فحص الاتصال بـ Claude API"""
import os, sys
from dotenv import load_dotenv
import anthropic

load_dotenv()
key = os.environ.get("ANTHROPIC_API_KEY", "").strip()

if not key.startswith("sk-ant-"):
    print("X المفتاح مفقود أو شكله خاطئ في .env")
    sys.exit(1)
print(f"OK المفتاح مقروء ({key[:14]}...{key[-4:]})")

client = anthropic.Anthropic(api_key=key)

try:
    models = client.models.list(limit=20).data
except Exception as e:
    print(f"X فشل الاتصال: {type(e).__name__}: {e}")
    sys.exit(1)

print(f"\nOK النماذج المتاحة ({len(models)}):\n")
for m in models:
    print("   ", m.id)

model = os.environ.get("ANTHROPIC_MODEL", "").strip() or models[0].id
print(f"\n-> اختبار الاستدعاء بـ: {model}")

try:
    r = client.messages.create(
        model=model, max_tokens=64,
        messages=[{"role": "user", "content": "قل: الاتصال ناجح"}])
except Exception as e:
    print(f"X فشل الاستدعاء: {type(e).__name__}: {e}")
    sys.exit(1)

print("   رد النموذج :", r.content[0].text.strip())
print(f"   التوكنات   : دخل {r.usage.input_tokens} | خرج {r.usage.output_tokens}")
print(f"   سبب التوقف : {r.stop_reason}")
print(f"\nOK ضع هذا في .env:\n   ANTHROPIC_MODEL={model}")
