#!/usr/bin/env python3
"""
Telegram MCQ Quiz Bot — main entry point.

Uses python-telegram-bot v20 (async) with ConversationHandler to walk
users through registration then an inline-keyboard quiz.
"""

import logging
import os
import sys

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

# Ensure local imports work regardless of cwd
sys.path.insert(0, os.path.dirname(__file__))

from config import BOT_TOKEN, NAME, PHONE, ROLL, PARENT, QUIZ
from user_data import UserDataManager, validate_phone, validate_parent_username
from quiz import load_questions, get_question_message, check_answer, get_result_summary
from notifications import send_parent_notification

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Shared state
# ──────────────────────────────────────────────
user_manager = UserDataManager()
questions = load_questions()


# ══════════════════════════════════════════════
# Registration handlers
# ══════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /start — greet and ask for name."""
    chat_id = update.effective_chat.id

    # Check if the user might be a parent registering
    if context.args and context.args[0] == "parent":
        username = update.effective_user.username
        if username:
            user_manager.register_parent(f"@{username}", chat_id)
            await update.message.reply_text(
                "👋 Welcome! You have been registered as a parent.\n"
                "You will receive your child's quiz results here."
            )
            return ConversationHandler.END

    user_manager.create_user(chat_id)
    await update.message.reply_text(
        "👋 *Welcome to the MCQ Quiz Bot!*\n\n"
        "I'll ask you a few details before we begin.\n\n"
        "📝 Please enter your *full name*:",
        parse_mode="Markdown",
    )
    return NAME


async def name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store name and ask for phone number."""
    chat_id = update.effective_chat.id
    name = update.message.text.strip()

    if len(name) < 2:
        await update.message.reply_text("⚠️ Name must be at least 2 characters. Try again:")
        return NAME

    user_manager.update_field(chat_id, "name", name)
    await update.message.reply_text(
        f"Nice to meet you, *{name}*! 👋\n\n"
        "📱 Please enter your *phone number* (digits only):",
        parse_mode="Markdown",
    )
    return PHONE


async def phone_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validate & store phone, ask for roll number."""
    chat_id = update.effective_chat.id
    phone = update.message.text.strip()

    if not validate_phone(phone):
        await update.message.reply_text(
            "⚠️ Invalid phone number. Please enter a valid numeric phone number "
            "(7–15 digits):"
        )
        return PHONE

    user_manager.update_field(chat_id, "phone", phone)
    await update.message.reply_text("🆔 Please enter your *roll number*:", parse_mode="Markdown")
    return ROLL


async def roll_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store roll number and ask for parent username."""
    chat_id = update.effective_chat.id
    roll = update.message.text.strip()

    if not roll:
        await update.message.reply_text("⚠️ Roll number cannot be empty. Try again:")
        return ROLL

    user_manager.update_field(chat_id, "roll", roll)
    await update.message.reply_text(
        "👨‍👩‍👦 Please enter your *parent's Telegram username*\n"
        "(must start with @, e.g. @parent\\_username):",
        parse_mode="Markdown",
    )
    return PARENT


async def parent_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validate & store parent username, then start the quiz."""
    chat_id = update.effective_chat.id
    parent = update.message.text.strip()

    if not validate_parent_username(parent):
        await update.message.reply_text(
            "⚠️ Invalid format. The username must start with '@'. Try again:"
        )
        return PARENT

    user_manager.update_field(chat_id, "parent_username", parent)

    # Registration complete — show summary + launch quiz
    user = user_manager.get_user(chat_id)
    user["total_questions"] = len(questions)
    user["current_question"] = 0

    await update.message.reply_text(
        "✅ *Registration Complete!*\n\n"
        f"👤 Name: {user['name']}\n"
        f"📱 Phone: {user['phone']}\n"
        f"🆔 Roll: {user['roll']}\n"
        f"👨‍👩‍👦 Parent: {user['parent_username']}\n\n"
        f"📚 The quiz has *{len(questions)} questions*.\n"
        "Get ready — here comes the first question! 🚀",
        parse_mode="Markdown",
    )

    # Send the first question
    return await send_question(update, context, chat_id)


# ══════════════════════════════════════════════
# Quiz handlers
# ══════════════════════════════════════════════

async def send_question(update: Update, context: ContextTypes.DEFAULT_TYPE,
                        chat_id: int) -> int:
    """Send the current question for *chat_id*."""
    user = user_manager.get_user(chat_id)
    idx = user["current_question"]

    if idx >= len(questions):
        return await end_quiz(update, context, chat_id)

    text, markup = get_question_message(questions[idx], idx, len(questions))
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=markup,
        parse_mode="Markdown",
    )
    return QUIZ


async def quiz_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Process an inline-button answer press."""
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    user = user_manager.get_user(chat_id)

    if user is None:
        await query.edit_message_text("⚠️ Session expired. Please /start again.")
        return ConversationHandler.END

    # Decode answer
    selected_index = int(query.data.split("_")[1])
    idx = user["current_question"]
    question = questions[idx]
    labels = ["A", "B", "C", "D"]

    is_correct = check_answer(question, selected_index)
    user_manager.update_score(chat_id, is_correct)
    user_manager.record_answer(
        chat_id,
        question_text=question["question"],
        user_answer=f"{labels[selected_index]}. {question['options'][selected_index]}",
        correct_answer=f"{labels[question['correct_option']]}. {question['options'][question['correct_option']]}",
        is_correct=is_correct,
    )

    # Instant feedback
    if is_correct:
        feedback = f"✅ Correct! The answer is *{labels[question['correct_option']]}. {question['options'][question['correct_option']]}*"
    else:
        feedback = (
            f"❌ Wrong! You chose *{labels[selected_index]}. {question['options'][selected_index]}*\n"
            f"The correct answer is *{labels[question['correct_option']]}. {question['options'][question['correct_option']]}*"
        )

    await query.edit_message_text(text=feedback, parse_mode="Markdown")

    # Advance to next question
    user["current_question"] += 1
    return await send_question(update, context, chat_id)


# ══════════════════════════════════════════════
# End of quiz
# ══════════════════════════════════════════════

async def end_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE,
                   chat_id: int) -> int:
    """Display results and notify parent."""
    user = user_manager.get_user(chat_id)
    summary = get_result_summary(user)

    await context.bot.send_message(
        chat_id=chat_id,
        text=summary,
        parse_mode="Markdown",
    )

    # Save to disk
    user_manager.save_results()

    # Notify parent
    parent_username = user.get("parent_username", "")
    parent_chat_id = user_manager.get_parent_chat_id(parent_username)

    success, msg = await send_parent_notification(
        bot=context.bot,
        parent_chat_id=parent_chat_id,
        user_data=user,
    )

    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")

    return ConversationHandler.END


# ══════════════════════════════════════════════
# Leaderboard
# ══════════════════════════════════════════════

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show top scores."""
    entries = user_manager.get_leaderboard()
    if not entries:
        await update.message.reply_text("📊 No quiz results yet!")
        return

    lines = ["🏆 *Leaderboard*\n"]
    medals = ["🥇", "🥈", "🥉"]
    for i, e in enumerate(entries):
        prefix = medals[i] if i < 3 else f"  {i + 1}."
        lines.append(f"{prefix} {e['name']} (Roll: {e['roll']}) — {e['score']}/{e['total']}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ══════════════════════════════════════════════
# Cancel
# ══════════════════════════════════════════════

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel."""
    await update.message.reply_text(
        "❌ Quiz cancelled. Send /start to begin again."
    )
    return ConversationHandler.END


# ══════════════════════════════════════════════
# Error handler
# ══════════════════════════════════════════════

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log uncaught exceptions."""
    logger.error("Exception while handling update:", exc_info=context.error)


# ══════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════

def main() -> None:
    """Build the Application and run polling."""
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌  Please set your bot token in config.py first!")
        sys.exit(1)

    app = Application.builder().token(BOT_TOKEN).build()

    # Conversation handler for registration + quiz
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, name_handler)],
            PHONE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, phone_handler)],
            ROLL:   [MessageHandler(filters.TEXT & ~filters.COMMAND, roll_handler)],
            PARENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, parent_handler)],
            QUIZ:   [CallbackQueryHandler(quiz_callback_handler, pattern=r"^answer_\d+$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_error_handler(error_handler)

    logger.info("🤖 Bot is running …")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
