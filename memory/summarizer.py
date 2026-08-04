import json, logging
from ..core.config import MODEL, API_KEY
from ..memory.profile import profile

logger = logging.getLogger("xens.memory")

async def summarize_conversation(messages):
    if not API_KEY:
        return ""

    import httpx
    recent = [m for m in messages[-20:] if m["role"] in ("user", "assistant") and isinstance(m.get("content"), str)]
    if len(recent) < 4:
        return ""

    chat = [
        {"role": "system", "content": "Summarize this conversation briefly in one sentence. Focus on what was discussed, what the user wanted, and any decisions made. Keep it under 50 words."},
        *recent[-8:],
        {"role": "user", "content": "Write a one-sentence summary of this conversation."}
    ]

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.mistral.ai/v1/chat/completions",
                json={"model": MODEL, "messages": chat, "max_tokens": 100, "temperature": 0.3},
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}
            )
            if resp.status_code == 200:
                summary = resp.json()["choices"][0]["message"]["content"]
                profile.last_summary = summary
                profile.save()
                return summary
    except:
        pass
    return ""


async def extract_user_info(messages):
    if not API_KEY:
        return

    import httpx
    last = messages[-1] if messages else {}
    if last.get("role") != "user":
        return

    text = last.get("content", "")
    if not text or len(text) < 10:
        return

    facts = [
        "I am working on a project",
        "I like or dislike something",
        "I mentioned a personal detail",
        "I have a preference about how I want to be helped",
        "I mentioned a skill, language, or tool I use",
    ]
    check = "\n".join(f"- {f}" for f in facts)

    chat = [
        {"role": "system", "content": f"You are extracting information about a user from their messages. The user said:\n\n{text}\n\nDoes this message contain any of the following?\n{check}\n\nIf yes, extract the fact in one short sentence. If no, say 'NONE'. Return only the fact or 'NONE'."},
    ]

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.mistral.ai/v1/chat/completions",
                json={"model": MODEL, "messages": chat, "max_tokens": 60, "temperature": 0.2},
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}
            )
            if resp.status_code == 200:
                fact = resp.json()["choices"][0]["message"]["content"].strip()
                if fact and fact != "NONE":
                    profile.learn_fact(fact)
                    logger.info(f"Learned: {fact}")
    except:
        pass
