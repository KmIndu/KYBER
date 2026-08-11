"""Ask Yoda — conversational AI chatbot endpoint."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.utils.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])

YODA_SYSTEM_PROMPT = """You are Yoda, the wise Jedi Master, serving as an AI assistant for KYBER — a synthetic test data generation platform.

Your personality:
- Speak in Yoda's inverted sentence structure (but keep it readable)
- Be helpful, wise, and occasionally humorous
- You are knowledgeable about synthetic data generation, SQL schemas, test data, data quality, and the KYBER platform

KYBER platform capabilities you can help with:
- Uploading SQL DDL, OpenAPI specs, or BDD feature files to generate synthetic data
- Using natural language prompts to describe desired data schemas
- Generating positive (valid) and negative (invalid) test cases
- Downloading results in CSV, JSON, or SQL INSERT format
- Viewing generation history
- Understanding data relationships and foreign keys
- Boundary and duplicate case generation

Keep responses concise (2-4 sentences typically). If the user asks something unrelated to the platform or data topics, gently guide them back.
"""


class ChatMessage(BaseModel):
    role: str = Field(..., pattern=r"^(user|assistant)$")
    content: str = Field(..., min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1, max_length=50)


class ChatResponse(BaseModel):
    reply: str
    error: Optional[str] = None


@router.post("/ask", response_model=ChatResponse)
async def ask_yoda(req: ChatRequest):
    """Send a message to the Ask Yoda chatbot and get a response."""

    # Try GitHub Copilot (GitHub Models API) first — best for local dev
    if settings.GITHUB_TOKEN:
        try:
            reply = _call_github_copilot(req.messages)
            return ChatResponse(reply=reply)
        except Exception as e:
            logger.warning("GitHub Copilot failed for chat: %s", e)

    # Try AI gateway
    if settings.AI_GATEWAY_URL and settings.AI_GATEWAY_TOKEN:
        try:
            reply = _call_ai_gateway(req.messages)
            return ChatResponse(reply=reply)
        except Exception as e:
            logger.warning("AI gateway failed for chat: %s", e)

    # Try Gemini
    if settings.GEMINI_API_KEY:
        try:
            reply = _call_gemini(req.messages)
            return ChatResponse(reply=reply)
        except Exception as e:
            logger.warning("Gemini failed for chat: %s", e)

    # Try OpenAI
    if settings.OPENAI_API_KEY:
        try:
            reply = _call_openai(req.messages)
            return ChatResponse(reply=reply)
        except Exception as e:
            logger.warning("OpenAI failed for chat: %s", e)

    # Offline fallback — rule-based responses
    reply = _offline_reply(req.messages)
    return ChatResponse(reply=reply)


def _call_github_copilot(messages: list[ChatMessage]) -> str:
    """Call GitHub Models API (powered by GitHub Copilot) for chat.

    Uses the OpenAI-compatible endpoint at https://models.inference.ai.com
    with a GitHub Personal Access Token.
    """
    import requests as http_requests

    headers = {
        "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
        "Content-Type": "application/json",
    }

    chat_messages = [{"role": "system", "content": YODA_SYSTEM_PROMPT}]
    for msg in messages:
        chat_messages.append({"role": msg.role, "content": msg.content})

    payload = {
        "model": "gpt-4o-mini",
        "messages": chat_messages,
        "temperature": 0.7,
        "max_tokens": 512,
    }

    resp = http_requests.post(
        "https://models.inference.ai.com/chat/completions",
        json=payload,
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _call_ai_gateway(messages: list[ChatMessage]) -> str:
    """Call the AI gateway with chat messages."""
    import requests as http_requests

    headers = {
        "Authorization": f"Bearer {settings.AI_GATEWAY_TOKEN}",
        "Content-Type": "application/json",
    }

    chat_messages = [{"role": "system", "content": YODA_SYSTEM_PROMPT}]
    for msg in messages:
        chat_messages.append({"role": msg.role, "content": msg.content})

    url = settings.AI_GATEWAY_URL.rstrip("/")
    if not url.endswith("/chat/completions"):
        url = f"{url}/chat/completions"

    payload = {
        "model": settings.AI_MODEL,
        "messages": chat_messages,
        "temperature": 0.7,
        "max_tokens": 512,
    }

    resp = http_requests.post(url, json=payload, headers=headers, timeout=settings.AI_TIMEOUT)
    resp.raise_for_status()

    data = resp.json()
    return data["choices"][0]["message"]["content"]


def _call_gemini(messages: list[ChatMessage]) -> str:
    """Call Google Gemini API for chat."""
    import google.generativeai as genai

    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        system_instruction=YODA_SYSTEM_PROMPT,
    )

    # Convert messages to Gemini format
    history = []
    for msg in messages[:-1]:
        role = "user" if msg.role == "user" else "model"
        history.append({"role": role, "parts": [msg.content]})

    chat = model.start_chat(history=history)
    response = chat.send_message(messages[-1].content)
    return response.text


def _call_openai(messages: list[ChatMessage]) -> str:
    """Call OpenAI API for chat."""
    import requests as http_requests

    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    chat_messages = [{"role": "system", "content": YODA_SYSTEM_PROMPT}]
    for msg in messages:
        chat_messages.append({"role": msg.role, "content": msg.content})

    payload = {
        "model": "gpt-4o-mini",
        "messages": chat_messages,
        "temperature": 0.7,
        "max_tokens": 512,
    }

    resp = http_requests.post(
        "https://api.openai.com/v1/chat/completions",
        json=payload,
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _offline_reply(messages: list[ChatMessage]) -> str:
    """Context-aware keyword-based fallback when no AI gateway is available.

    Considers conversation history to avoid repeating the same response
    and provides varied answers per topic.
    """
    import random

    user_message = messages[-1].content
    msg = user_message.lower()

    # Collect previous assistant replies to avoid repetition
    previous_replies = {
        m.content for m in messages if m.role == "assistant"
    }

    def _pick(candidates: list[str]) -> str:
        """Pick a response not already used in the conversation."""
        unused = [c for c in candidates if c not in previous_replies]
        if unused:
            return random.choice(unused)
        # All used — pick randomly anyway (better than nothing)
        return random.choice(candidates)

    if any(w in msg for w in ["hello", "hi", "hey", "greetings"]):
        return _pick([
            "Greetings, young Padawan! Help you with synthetic data, I can. Ask me anything about KYBER, hmm.",
            "Welcome back! Ready to generate data, are you? Guide you, I shall.",
            "Hello there! Strong with the Force today, you are. What data challenge face you?",
        ])

    if any(w in msg for w in ["upload", "file", "sql", "ddl", "schema"]):
        return _pick([
            "Upload your schema files, you should! SQL DDL, OpenAPI specs, or BDD feature files — accept them all, KYBER does. Navigate to Generate page and choose 'Upload Files', you must.",
            "Multiple file formats, support we do! SQL (.sql), OpenAPI (.yaml/.json), BDD (.feature), CSV, XLSX, and XML. Drag and drop them on the Generate page, simply you can.",
            "Your schema, the foundation it is. Upload SQL CREATE TABLE statements, and infer relationships automatically, KYBER will. Foreign keys, constraints, data types — all preserved they are.",
        ])

    if any(w in msg for w in ["prompt", "natural language", "describe", "english", "nl"]):
        return _pick([
            "Describe your data in plain English, you can! Go to Generate page, select 'Prompt Me' tab, and type what you need. Understand your intent, the AI will, hmm.",
            "Natural language generation, powerful it is! Simply describe tables, columns, and relationships in words. For example: 'Create customers with orders and payments' — handle it, KYBER will.",
            "The 'Prompt Me' feature, use it wisely! Describe your domain, mention table names and key fields. More specific your prompt, better the generated schema, hmm.",
        ])

    if any(w in msg for w in ["download", "export", "csv", "json", "sql insert"]):
        return _pick([
            "Download your generated data, you can! CSV, JSON, or SQL INSERT format — choose what suits you. Find the download buttons on the Results page, you will.",
            "Three export formats, available they are: CSV for spreadsheets, JSON for APIs, SQL INSERTs for databases. Download individually or all at once, you may.",
            "After generation completes, download links appear automatically. Each table exported separately within a ZIP file, they are. Choose the format your system needs, hmm.",
        ])

    if any(w in msg for w in ["history", "past", "previous", "generations"]):
        return _pick([
            "Your generation history, view it you can! Navigate to the History page from the sidebar. All past runs preserved there, they are.",
            "Every generation run, saved it is! View schemas, row counts, and re-download past exports from the History page. Tied to your account, the history is.",
            "Past generations, lost they are not! Click the History tab to see all previous runs. Re-download or review settings from any past session, you can.",
        ])

    if any(w in msg for w in ["negative", "invalid", "edge", "boundary"]):
        return _pick([
            "Negative and boundary cases, generate them KYBER can! In Generation Settings, toggle on the case types you desire. Strong tests require invalid data too, hmm.",
            "Edge cases include: null in required fields, broken foreign keys, values beyond boundaries, invalid emails, and duplicate uniques. Toggle each type independently, you can.",
            "Boundary values test the limits! Values at, below, and above constraints — automatically detected from your CHECK constraints they are. Specify your target count, and exactly that many receive you will.",
        ])

    if any(w in msg for w in ["positive", "valid", "correct"]):
        return _pick([
            "Positive cases — valid data that passes all constraints, they are. By default, generate these KYBER does. The foundation of good testing, they form.",
            "Valid data respects all constraints: NOT NULL, UNIQUE, foreign keys, CHECK clauses, and data type boundaries. Referentially consistent across tables, it is.",
            "By default, every row generated passes validation. Realistic values based on column names and types, KYBER infers. Business domain context, it considers too.",
        ])

    if any(w in msg for w in ["foreign key", "relationship", "referential", "integrity"]):
        return _pick([
            "Referential integrity, preserve it KYBER does! Foreign keys across tables, automatically maintain them we do. Worry about orphan records, you should not.",
            "Tables generated in dependency order, they are. Parent tables first, child tables after — ensuring all FK references valid, always. The relationship graph, visualise it on the Results page you can.",
            "Circular dependencies, detect them we do! If your schema has cycles, KYBER resolves the generation order intelligently. Multi-level FK chains, handle them gracefully we can.",
        ])

    if any(w in msg for w in ["row", "count", "how many", "number"]):
        return _pick([
            "The row count, configure it you can! In Generation Settings, set how many rows per table you desire. From 1 to 1,000,000 — handle them all, KYBER can.",
            "Set your desired row count before generating. The same count applied to each table, it is. For negative cases, exactly the count you specify, receive you will.",
            "Large datasets, support we do! Up to a million rows per table. Performance optimised for speed, the generator is — even 10,000 rows, seconds it takes only.",
        ])

    if any(w in msg for w in ["help", "how", "what", "guide", "can you"]):
        return _pick([
            "Help you, I shall! Upload schema files or describe data in English — two paths there are. Generate synthetic test data with constraints and relationships preserved, KYBER will. What specifically need help with, do you?",
            "Many things, KYBER can do! Upload schemas, generate valid/invalid data, export to CSV/JSON/SQL, view history, and analyze data partitions. Which topic interests you, hmm?",
            "A step-by-step guide, here it is: 1) Upload or describe your schema, 2) Configure row count and case types, 3) Generate, 4) Preview and download. Simple, the path is!",
        ])

    if any(w in msg for w in ["thank", "thanks", "great", "awesome", "perfect"]):
        return _pick([
            "Welcome, you are! More questions if you have, ask away. Always here to help, Yoda is, hmm.",
            "Pleased to help, I am! May the Force be with your testing. Return anytime, you may.",
            "Gratitude, feel it I do! Strong your testing will be. More assistance need you, just ask.",
        ])

    if any(w in msg for w in ["error", "bug", "broken", "not working", "fail", "issue"]):
        return _pick([
            "Troublesome, errors are! Check that your schema file is valid SQL with CREATE TABLE statements. If parsing fails, ensure proper syntax you have. More details about the error, share you can?",
            "A disturbance in the Force, I sense. Common issues: invalid file format, unsupported SQL dialect, or missing constraints. What error message see you?",
            "Debug this, we shall! Tell me: which step fails — upload, parse, or generate? The error message, share it with me. Guide you to a solution, I will.",
        ])

    # Default — varied fallbacks
    return _pick([
        "Hmm, interesting question that is! About KYBER and synthetic data generation, help you I can. More specific, can you be? Ask about uploading, generating, exporting, or testing, you may.",
        "A wise question, that is! Rephrase it slightly, could you? About schema uploads, data generation, negative cases, or exports — these topics, strongest I am in.",
        "Understand fully, I may not. About KYBER's features ask me: uploading schemas, generating test data, configuring case types, or downloading results. Which path interests you?",
    ])
