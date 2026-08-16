import json, logging, time
from ..llm.base import Message
from ..core.llm import get_provider
from ..memory.profile import profile

logger = logging.getLogger("xens.memory")

_last_summary = 0.0
_last_userinfo = 0.0

def _to_messages(chat: list[dict]) -> list[Message]:
    return [Message(role=m["role"], content=m.get("content", "")) for m in chat]

async def summarize_conversation(messages):
    global _last_summary
    if time.time() - _last_summary < 90.0:
        return ""
    _last_summary = time.time()

    recent = [m for m in messages[-20:] if m["role"] in ("user", "assistant") and isinstance(m.get("content"), str)]
    if len(recent) < 4:
        return ""

    chat = [
        {"role": "system", "content": "Summarize this conversation briefly in one sentence. Focus on what was discussed, what the user wanted, and any decisions made. Keep it under 50 words."},
        *recent[-8:],
        {"role": "user", "content": "Write a one-sentence summary of this conversation."}
    ]

    try:
        provider = get_provider()
        result = await provider.chat(_to_messages(chat), tier="free", background=True,
                                     max_tokens=100, temperature=0.3)
        summary = (result.content or "").strip()
        if summary:
            profile.last_summary = summary
            profile.save()
            return summary
    except Exception as e:
        logger.warning("summarize_conversation failed: %s", e)
    return ""


async def extract_user_info(messages):
    global _last_userinfo
    if time.time() - _last_userinfo < 30.0:
        return
    _last_userinfo = time.time()

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
        provider = get_provider()
        result = await provider.chat(_to_messages(chat), tier="free", background=True,
                                     max_tokens=60, temperature=0.2)
        fact = (result.content or "").strip()
        if fact and fact != "NONE":
            profile.learn_fact(fact)
            logger.info(f"Learned: {fact}")
    except Exception as e:
        logger.warning("extract_user_info failed: %s", e)
