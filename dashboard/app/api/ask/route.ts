// POST /api/ask {question} -> the agent's judged answer with its SQL (see lib/ai.ts).
import { NextResponse } from "next/server";
import { aiReady, allowVisitor, ask, LIMITS } from "@/lib/ai";

export const maxDuration = 60;   // seconds: a question may need several model calls

export async function POST(req: Request) {
  if (!aiReady) {
    return NextResponse.json({ error: "Ask the data is not set up: AI_DATABASE_URL, a model key and COHERE_API_KEY are needed." },
                             { status: 503 });
  }
  const visitor = req.headers.get("x-forwarded-for")?.split(",")[0].trim() || "local";
  if (!allowVisitor(visitor)) {
    return NextResponse.json({ error: `Limit reached: ${LIMITS.perVisitor} questions per ${LIMITS.perMinutes} minutes. Please wait a little.` },
                             { status: 429 });
  }
  let question = "";
  try {
    question = String((await req.json()).question ?? "").trim();
  } catch { /* handled below */ }
  if (!question) return NextResponse.json({ error: "Please type a question." }, { status: 400 });
  if (question.length > LIMITS.questionChars) {
    return NextResponse.json({ error: `Please keep the question under ${LIMITS.questionChars} characters.` }, { status: 400 });
  }
  return NextResponse.json(await ask(question));
}