"""Check the AI layer end to end (week 3, step 2).

Run from the project root, with .venv active:
    python scripts/check_ai.py

It uses about 8 model calls (3 of them Cohere), so don't run it in a loop.
    1. keys        are the 3 keys and AI_DATABASE_URL in .env?
    2. query       can ai_reader read the data?
    3. models      does each model answer (Gemini, Groq, Cohere)?
    4. grounded    a real answer: generate -> judge -> show or withhold
    5. judge test  a deliberately wrong answer: the judge must FAIL it
Every call is logged in Neon (llm_calls).
"""
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline" / "src" / "pipeline"))
import llm  # noqa: E402

ok = True


def show(passed, name, detail=""):
    global ok
    ok &= passed
    print(f"{'PASS' if passed else 'FAIL'}  {name:<14} {detail}")


# 1. keys
for label, value in [("AI_DATABASE_URL", llm.AI_URL), ("Gemini key", llm.GEMINI_KEY),
                     ("GROQ_API_KEY", llm.GROQ_KEY), ("COHERE_API_KEY", llm.COHERE_KEY)]:
    show(bool(value), "keys", f"{label} {'set' if value else 'MISSING in .env'}")
if not ok:
    raise SystemExit("\nAdd the missing values to .env and run again.")

# 2. query (read-only role)
data = {"impressions_by_advertiser": llm.query("""
    SELECT advertiser_id, SUM(impressions) AS impressions, SUM(clicked_impressions) AS clicked
    FROM daily_campaign GROUP BY advertiser_id ORDER BY impressions DESC""")}
rows = data["impressions_by_advertiser"]["rows"]
show(len(rows) > 0, "query", f"{len(rows)} advertisers read as ai_reader")

# 3. each model, one tiny call
PING = {"type": "object", "properties": {"reply": {"type": "string"}}, "required": ["reply"]}
run = uuid.uuid4()
for provider in ("gemini", "groq", "cohere"):
    start = time.time()
    try:
        out = llm.call(provider, "Answer with JSON only.", 'Return {"reply": "ok"}.', PING,
                       run_id=run, purpose="test", step="generate", attempt=1)
        show(True, provider, f"answered '{out['reply']}' in {time.time() - start:.1f}s "
                             f"({llm.PROVIDERS[provider][1]()})")
    except llm.LLMError as e:
        show(False, provider, str(e)[:300])

# 4. a real grounded answer
SCHEMA = {"type": "object", "properties": {"headline": {"type": "string"}}, "required": ["headline"]}
task = "Write one sentence naming the advertiser with the most impressions, and how many it had."
result = llm.grounded(task, data, SCHEMA, purpose="test")
show(result["status"] == "pass", "grounded",
     f"{result['status']} (written by {result['provider']})")
print(f"      answer: {result['output'] or result['rejected']}")
print(f"      judge : {result['verdict']['reason'] if result['verdict'] else result['note']}")
print(f"      SQL   : {result['sql'][0][:110]}...")

# 5. the judge must catch an invented number
lie = {"headline": "Advertiser 1458 had 98,765,432 impressions, more than all others combined."}
try:
    verdict = llm.judge(task, data, lie, run_id=uuid.uuid4(), purpose="test")
    show(verdict["verdict"] == "fail", "judge test", f"wrong answer -> {verdict['verdict']}: {verdict['reason']}")
except llm.LLMError as e:
    show(False, "judge test", str(e)[:300])

print("\nThe AI layer works." if ok else "\nFix the FAIL lines above (the message says what went wrong).")
print("Every call above is in Neon: SELECT * FROM llm_calls ORDER BY id DESC LIMIT 10;")