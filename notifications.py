"""
Notification helpers — send quiz results to the parent's Telegram account.
"""

import logging
from telegram import Bot
from telegram.error import TelegramError

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Result message formatting
# ──────────────────────────────────────────────

def format_result_message(user_data: dict) -> str:
    """
    Build a concise result message suitable for sending to a parent.
    """
    score = user_data["score"]
    total = user_data.get("total_marks", user_data["total_questions"])
    percentage = (score / total * 100) if total else 0

    text = (
        "📬 *Student Quiz Result Notification*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 *Student Name:* {user_data['name']}\n"
        f"🆔 *Roll Number:* {user_data['roll']}\n"
        f"📊 *Score:* {score}/{total} ({percentage:.0f}%)\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📋 *Answer Summary:*\n\n"
    )

    for i, ans in enumerate(user_data["answers"]):
        status = "✅" if ans["is_correct"] else "❌"
        text += (
            f"{status} *Q{i + 1}.* {ans['question']}\n"
            f"   Answer given: {ans['user_answer']}\n"
            f"   Correct answer: {ans['correct_answer']}\n\n"
        )

    return text


# ──────────────────────────────────────────────
# Send notification
# ──────────────────────────────────────────────

async def send_parent_notification(
    bot: Bot,
    parent_chat_id: int | None,
    user_data: dict,
) -> tuple[bool, str]:
    """
    Attempt to send the result to the parent's chat.

    Returns (success: bool, message: str).
    - If *parent_chat_id* is None the parent hasn't /started the bot.
    - Catches TelegramError for blocked / deactivated accounts.
    """
    if parent_chat_id is None:
        return (
            False,
            "⚠️ Could not deliver the result to your parent.\n"
            "They need to start this bot first by sending /start "
            "so they can receive notifications.",
        )

    message = format_result_message(user_data)

    try:
        await bot.send_message(
            chat_id=parent_chat_id,
            text=message,
            parse_mode="Markdown",
        )
        return True, "✅ Your quiz results have been sent to your parent!"

    except TelegramError as exc:
        logger.warning("Failed to send parent notification: %s", exc)
        return (
            False,
            "⚠️ Could not deliver results to your parent. "
            "They may have blocked the bot or not started it yet.\n"
            "Please share your results with them manually.",
        )
