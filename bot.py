#!/usr/bin/env python3
"""
Telegram MCQ Quiz Bot — main entry point.

Uses python-telegram-bot v20 (async) with ConversationHandler to walk
users through registration then an inline-keyboard quiz.
"""

import logging
import asyncio
import difflib
import hashlib
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import NetworkError, TimedOut
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
    Defaults,
)
from imageio_ffmpeg import get_ffmpeg_exe

try:
    import speech_recognition as sr
    SR_AVAILABLE = True
except Exception as exc:
    SR_AVAILABLE = False
    sr = None
    logger = logging.getLogger(__name__)
    logger.warning("Speech recognition unavailable: %s", exc)

# Ensure local imports work regardless of cwd
sys.path.insert(0, os.path.dirname(__file__))

from config import BOT_TOKEN, NAME, PHONE, ROLL, PARENT, QUIZ, TEST_SELECT
from user_data import UserDataManager, validate_phone, validate_roll, validate_parent_username
from quiz import get_active_tests, get_test_by_id, get_question_message, check_answer, get_result_summary
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

try:
    FFMPEG_EXE = get_ffmpeg_exe()
except Exception:
    FFMPEG_EXE = "ffmpeg"

IST_TZ = timezone(timedelta(hours=5, minutes=30))

# Outbound send queue and rate limiting (Telegram limits ~30 msg/sec overall, ~1 msg/sec per chat)
SEND_QUEUE: asyncio.Queue = asyncio.Queue()
SEND_WORKER_TASK: asyncio.Task | None = None
GLOBAL_MIN_INTERVAL = 1.0 / 30.0
PER_CHAT_INTERVAL = 1.0
GLOBAL_LAST_SENT = 0.0
CHAT_LAST_SENT: dict[int, float] = {}


async def _rate_limit_send(chat_id: int | None) -> None:
    global GLOBAL_LAST_SENT

    now = time.monotonic()
    wait_s = max(0.0, GLOBAL_MIN_INTERVAL - (now - GLOBAL_LAST_SENT))
    if chat_id is not None:
        last_chat = CHAT_LAST_SENT.get(chat_id, 0.0)
        wait_s = max(wait_s, PER_CHAT_INTERVAL - (now - last_chat))

    if wait_s > 0:
        await asyncio.sleep(wait_s)

    now = time.monotonic()
    GLOBAL_LAST_SENT = now
    if chat_id is not None:
        CHAT_LAST_SENT[chat_id] = now


async def _send_worker() -> None:
    while True:
        item = await SEND_QUEUE.get()
        if item is None:
            SEND_QUEUE.task_done()
            break

        call_name = item["call_name"]
        operation = item["operation"]
        chat_id = item.get("chat_id")
        future = item["future"]

        try:
            await _rate_limit_send(chat_id)
            result = await _retry_telegram_call(call_name, operation)
            if not future.done():
                future.set_result(result)
        except Exception as exc:
            if not future.done():
                future.set_exception(exc)
        finally:
            SEND_QUEUE.task_done()


async def _queue_telegram_call(call_name: str, operation, chat_id: int | None = None):
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    await SEND_QUEUE.put(
        {
            "call_name": call_name,
            "operation": operation,
            "chat_id": chat_id,
            "future": future,
        }
    )
    return await future


_LETTER_TO_INDEX = {"a": 0, "b": 1, "c": 2, "d": 3}
_NUMBER_WORDS_TO_INDEX = {
    "1": 0,
    "one": 0,
    "first": 0,
    "2": 1,
    "two": 1,
    "second": 1,
    "3": 2,
    "three": 2,
    "third": 2,
    "4": 3,
    "four": 3,
    "fourth": 3,
}
_OPTION_PRONUNCIATIONS = {
    "a": {
        "a", "ay", "ai", "ae", "ei", "eh", "ehh", "aye", "hey", "ate", "eight", "aay", "aa", "ehhh"
    },
    "b": {
        "b", "bee", "be", "bi", "bii", "bee", "bhee", "bh", "pea", "p"
    },
    "c": {
        "c", "see", "sea", "cee", "si", "sii", "she", "chi", "shi"
    },
    "d": {
        "d", "dee", "di", "dii", "the", "tea", "thi", "ti", "t"
    },
}


def _expand_variations(token: str) -> set[str]:
    """Generate many misspelling-like variants for fuzzy token matching."""
    variants = {token}
    vowels = "aeiou"

    # Repeated-letter and trimmed variants.
    variants.add(token.replace("ee", "e"))
    variants.add(token.replace("ee", "i"))
    variants.add(token.replace("ii", "i"))
    variants.add(token.replace("aa", "a"))
    variants.add(token + token[-1])
    if len(token) > 2:
        variants.add(token[:-1])
        variants.add(token[1:])

    # Vowel-swap variants to absorb ASR vowel drift.
    for i, ch in enumerate(token):
        if ch in vowels:
            for v in vowels:
                variants.add(token[:i] + v + token[i + 1:])

    # Common consonant confusion at start.
    if token.startswith("b"):
        variants.add("p" + token[1:])
    if token.startswith("d"):
        variants.add("t" + token[1:])
    if token.startswith("c"):
        variants.add("s" + token[1:])

    return {v for v in variants if v}


_PHONETIC_VARIANT_TO_LETTER = {}
for letter, seeds in _OPTION_PRONUNCIATIONS.items():
    all_forms = set()
    for seed in seeds:
        all_forms.update(_expand_variations(seed))
    for form in all_forms:
        _PHONETIC_VARIANT_TO_LETTER.setdefault(form, letter)


def _token_to_option_index(token: str, options_count: int) -> int | None:
    t = re.sub(r"[^a-z0-9]", "", token.lower())
    if not t:
        return None

    if t in _LETTER_TO_INDEX:
        idx = _LETTER_TO_INDEX[t]
        return idx if idx < options_count else None

    if t in _NUMBER_WORDS_TO_INDEX:
        idx = _NUMBER_WORDS_TO_INDEX[t]
        return idx if idx < options_count else None

    direct = _PHONETIC_VARIANT_TO_LETTER.get(t)
    if direct and _LETTER_TO_INDEX[direct] < options_count:
        return _LETTER_TO_INDEX[direct]

    # Fuzzy token fallback against generated phonetic variants.
    close = difflib.get_close_matches(t, _PHONETIC_VARIANT_TO_LETTER.keys(), n=1, cutoff=0.78)
    if close:
        letter = _PHONETIC_VARIANT_TO_LETTER[close[0]]
        idx = _LETTER_TO_INDEX[letter]
        return idx if idx < options_count else None

    return None


async def _retry_telegram_call(call_name: str, operation, retries: int = 2, base_delay: float = 1.5):
    """Retry transient Telegram network errors before failing."""
    for attempt in range(retries + 1):
        try:
            return await operation()
        except (TimedOut, NetworkError) as exc:
            if attempt == retries:
                raise
            wait_s = base_delay * (attempt + 1)
            logger.warning(
                "%s failed (%s). Retrying in %.1fs (%d/%d)",
                call_name,
                exc.__class__.__name__,
                wait_s,
                attempt + 1,
                retries,
            )
            await asyncio.sleep(wait_s)


async def safe_reply(message, text: str, **kwargs):
    kwargs.setdefault("protect_content", True)
    chat_id = getattr(message, "chat_id", None)
    return await _queue_telegram_call(
        "reply_text",
        lambda: message.reply_text(text, **kwargs),
        chat_id=chat_id,
    )


async def safe_send(bot, chat_id: int, text: str, **kwargs):
    kwargs.setdefault("protect_content", True)
    return await _queue_telegram_call(
        "send_message",
        lambda: bot.send_message(chat_id=chat_id, text=text, **kwargs),
        chat_id=chat_id,
    )


async def safe_edit(query, text: str, **kwargs):
    chat_id = None
    if getattr(query, "message", None) is not None:
        chat_id = getattr(query.message, "chat_id", None)
    return await _queue_telegram_call(
        "edit_message_text",
        lambda: query.edit_message_text(text=text, **kwargs),
        chat_id=chat_id,
    )


def _get_timeout_jobs(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.application.bot_data.setdefault("timeout_jobs", {})


def _cancel_timeout_job(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    jobs = _get_timeout_jobs(context)
    job = jobs.pop(chat_id, None)
    if job is not None:
        job.schedule_removal()


def _is_submission_late(user: dict,
                        answered_question_index: int,
                        submitted_ts: float | None = None) -> bool:
    """Return True if answer was submitted after current question deadline."""
    deadline_ts = user.get("question_deadline_ts")
    active_index = user.get("active_question_index")

    if deadline_ts is None or active_index != answered_question_index:
        return False

    ref_ts = submitted_ts if submitted_ts is not None else datetime.now(timezone.utc).timestamp()
    return ref_ts > float(deadline_ts)


async def _advance_on_timeout(context: ContextTypes.DEFAULT_TYPE,
                              chat_id: int,
                              question_index: int,
                              message: str = "⏰ Time is up for this question! Moving to the next one...") -> int:
    """Record timeout for current question (idempotent) and advance quiz."""
    user = user_manager.get_user(chat_id)
    if user is None:
        return ConversationHandler.END

    question_set = user.get("question_set", [])
    current_index = int(user.get("current_question", 0))
    if current_index != question_index or current_index >= len(question_set):
        return QUIZ

    _cancel_timeout_job(context, chat_id)
    await _disable_active_question_buttons(context, chat_id, expected_index=current_index)

    question = question_set[current_index]
    labels = [chr(ord("A") + i) for i in range(len(question["options"]))]
    user_manager.record_answer(
        chat_id,
        question_text=question["question"],
        user_answer="No answer (Timed out)",
        correct_answer=f"{labels[question['correct_option']]}. {question['options'][question['correct_option']]}",
        is_correct=False,
    )

    mark_correct = user.get("mark_correct", 1)
    mark_incorrect = user.get("mark_incorrect", 0)
    user_manager.update_score(
        chat_id,
        False,
        mark_correct=mark_correct,
        mark_incorrect=mark_incorrect,
    )

    user["current_question"] += 1
    await safe_send(context.bot, chat_id, message)
    return await send_question(update=None, context=context, chat_id=chat_id)


async def _disable_active_question_buttons(context: ContextTypes.DEFAULT_TYPE,
                                          chat_id: int,
                                          expected_index: int | None = None) -> None:
    """Remove inline buttons from the currently tracked question message."""
    user = user_manager.get_user(chat_id)
    if user is None:
        return

    message_id = user.get("active_question_message_id")
    message_index = user.get("active_question_index")
    if message_id is None:
        return

    if expected_index is not None and message_index != expected_index:
        return

    try:
        await _retry_telegram_call(
            "edit_message_reply_markup",
            lambda: context.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=None,
            ),
        )
    except Exception:
        # Message may already be edited/deleted; safe to ignore.
        pass
    finally:
        user.pop("active_question_message_id", None)
        user.pop("active_question_index", None)


def _build_test_select_markup(tests: list[dict]) -> InlineKeyboardMarkup:
    keyboard = []
    for test in tests:
        keyboard.append(
            [InlineKeyboardButton(test.get("name", "Untitled Test"), callback_data=f"test_{test.get('id')}")]
        )
    return InlineKeyboardMarkup(keyboard)


def _initialize_user_test_session(user: dict, test: dict) -> None:
    question_pool = list(test.get("questions", []))
    random_count = int(test.get("random_count", 0) or 0)
    if 0 < random_count < len(question_pool):
        # Same random subset for everyone in a given test/version.
        subset_seed_src = (
            f"{test.get('id', '')}:{int(test.get('version', 1))}:"
            f"{len(question_pool)}:{random_count}"
        )
        subset_seed = int(hashlib.sha256(subset_seed_src.encode("utf-8")).hexdigest()[:16], 16)
        subset_rng = random.Random(subset_seed)

        indices = list(range(len(question_pool)))
        subset_rng.shuffle(indices)
        selected_questions = [question_pool[i] for i in indices[:random_count]]

        # Shuffle order per student so order varies while subset stays same.
        student_roll = str(user.get("roll", ""))
        order_seed_src = f"{test.get('id', '')}:{int(test.get('version', 1))}:{student_roll}"
        order_seed = int(hashlib.sha256(order_seed_src.encode("utf-8")).hexdigest()[:16], 16)
        order_rng = random.Random(order_seed)
        order_rng.shuffle(selected_questions)
    else:
        selected_questions = question_pool

    timer_seconds = int(test.get("timer_seconds", 30) or 30)
    mark_correct = int(test.get("mark_correct", 1) or 1)
    mark_incorrect = int(test.get("mark_incorrect", 0) or 0)
    total_marks = (len(selected_questions) * mark_correct) if mark_correct > 0 else 0
    
    user["score"] = 0
    user["answers"] = []
    user["test_id"] = test.get("id", "default")
    user["test_name"] = test.get("name", "Untitled Test")
    user["test_version"] = int(test.get("version", 1))
    user["timer_seconds"] = timer_seconds
    user["mark_correct"] = mark_correct
    user["mark_incorrect"] = mark_incorrect
    user["total_marks"] = total_marks
    user["question_set"] = selected_questions
    user["total_questions"] = len(selected_questions)
    user["current_question"] = 0


async def _validate_user_test_session(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> bool:
    """Ensure user's test is still valid/active after teacher edits/deletes/deactivates."""
    user = user_manager.get_user(chat_id)
    if user is None:
        return False

    test_id = user.get("test_id")
    if not test_id:
        return True

    current_test = get_test_by_id(test_id)
    if current_test is None:
        _cancel_timeout_job(context, chat_id)
        await safe_send(
            context.bot,
            chat_id,
            "⚠️ This test was deleted by the teacher. Your session has been reset. Please send /start to attend from beginning.",
        )
        return False

    if not current_test.get("is_active"):
        _cancel_timeout_job(context, chat_id)
        await safe_send(
            context.bot,
            chat_id,
            "⚠️ This test is no longer active. Your session has been reset. Please send /start to choose another test.",
        )
        return False

    stored_version = int(user.get("test_version", 1))
    live_version = int(current_test.get("version", 1))
    if live_version != stored_version:
        _cancel_timeout_job(context, chat_id)
        await safe_send(
            context.bot,
            chat_id,
            "⚠️ This test was updated by the teacher. Session reset. Please send /start and attend from the first question.",
        )
        return False

    return True


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
            await safe_reply(
                update.message,
                "👋 Welcome! You have been registered as a parent.\n"
                "You will receive your child's quiz results here."
            )
            return ConversationHandler.END

    user_manager.create_user(chat_id)
    await safe_reply(
        update.message,
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
        await safe_reply(update.message, "⚠️ Name must be at least 2 characters. Try again:")
        return NAME

    user_manager.update_field(chat_id, "name", name)
    await safe_reply(
        update.message,
        f"Nice to meet you, *{name}*! 👋\n\n"
        "📱 Please enter your *phone number* (digits only):",
        parse_mode="Markdown",
    )
    return PHONE


async def phone_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validate & store phone, ask for parent username."""
    chat_id = update.effective_chat.id
    phone = update.message.text.strip()

    if not validate_phone(phone):
        await safe_reply(
            update.message,
            "⚠️ Invalid phone number. Please enter exactly 10 digits:"
        )
        return PHONE

    user_manager.update_field(chat_id, "phone", phone)
    await safe_reply(
        update.message,
        "👨‍👩‍👦 Please enter your *parent's Telegram username*\n"
        "(must start with @, e.g. @parent\\_username):",
        parse_mode="Markdown",
    )
    return PARENT


async def roll_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validate roll after test selection, then start chosen test."""
    chat_id = update.effective_chat.id
    roll = update.message.text.strip()

    if not validate_roll(roll):
        await safe_reply(update.message, "⚠️ Invalid roll number. Please enter exactly 10 digits:")
        return ROLL

    user = user_manager.get_user(chat_id)
    if user is None:
        await safe_reply(update.message, "⚠️ Session expired. Please /start again.")
        return ConversationHandler.END

    pending_test_id = user.get("pending_test_id")
    if not pending_test_id:
        await safe_reply(update.message, "⚠️ Please choose a test first. Send /start to begin.")
        return ConversationHandler.END

    selected_test = get_test_by_id(pending_test_id)
    if selected_test is None or not selected_test.get("is_active"):
        await safe_reply(update.message, "🚫 Selected test is not active anymore. Please /start again.")
        return ConversationHandler.END

    if selected_test.get("one_time") and user_manager.has_attempt_for_roll(pending_test_id, roll):
        active_tests = get_active_tests()
        await safe_reply(
            update.message,
            "🚫 *One Time Test*\n"
            "This roll number has already attended this test once.\n\n"
            "Please choose another test:",
            parse_mode="Markdown",
            reply_markup=_build_test_select_markup(active_tests) if active_tests else None,
        )
        return TEST_SELECT

    user_manager.update_field(chat_id, "roll", roll)
    _initialize_user_test_session(user, selected_test)
    user.pop("pending_test_id", None)

    await safe_reply(
        update.message,
        "🎯 *Test Selected!*\n\n"
        f"🧪 Test: *{user['test_name']}*\n"
        f"⏱️ Timer per question: *{user['timer_seconds']} seconds*\n"
        f"📚 Questions you'll get: *{user['total_questions']}*\n"
        f"✅ Marks for correct: *{user['mark_correct']}*\n"
        f"❌ Marks for wrong: *{user['mark_incorrect']}*\n"
        "⏳ Timeouts will be considered as wrong answers.\n"
        f"🆔 Roll: *{user['roll']}*\n\n"
        "Get ready — first question is coming now!",
        parse_mode="Markdown",
    )
    return await send_question(update, context, chat_id)


async def parent_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validate & store parent username, then ask student to choose a test."""
    chat_id = update.effective_chat.id
    parent = update.message.text.strip()

    if not validate_parent_username(parent):
        await safe_reply(
            update.message,
            "⚠️ Invalid format. The username must start with '@'. Try again:"
        )
        return PARENT

    user_manager.update_field(chat_id, "parent_username", parent)

    active_tests = get_active_tests()
    if not active_tests:
        await safe_reply(update.message, "🚫 *No Active Tests*\nPlease try again later.", parse_mode="Markdown")
        return ConversationHandler.END

    user = user_manager.get_user(chat_id)
    await safe_reply(
        update.message,
        "✅ *Registration Complete!*\n\n"
        f"👤 Name: {user['name']}\n"
        f"📱 Phone: {user['phone']}\n"
        f"👨‍👩‍👦 Parent: {user['parent_username']}\n\n"
        "🧪 Please choose a test to attend.\n"
        "🆔 You will enter your roll number after selecting a test.",
        parse_mode="Markdown",
        reply_markup=_build_test_select_markup(active_tests),
    )
    return TEST_SELECT


async def test_select_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle selected test and then prompt for roll number."""
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    user = user_manager.get_user(chat_id)
    if user is None:
        await safe_edit(query, "⚠️ Session expired. Please /start again.")
        return ConversationHandler.END

    test_id = query.data.replace("test_", "", 1)
    selected_test = get_test_by_id(test_id)
    if selected_test is None or not selected_test.get("is_active"):
        await safe_edit(query, "🚫 Selected test is not active anymore. Please /start again.")
        return ConversationHandler.END

    if not selected_test.get("questions"):
        await safe_edit(query, "⚠️ Selected test has no questions. Please contact your teacher.")
        return ConversationHandler.END

    user["pending_test_id"] = test_id
    await safe_edit(
        query,
        "🆔 Please enter your *roll number* to continue:",
        parse_mode="Markdown",
    )
    return ROLL


# ══════════════════════════════════════════════
# Quiz handlers
# ══════════════════════════════════════════════

async def send_question(update: Update, context: ContextTypes.DEFAULT_TYPE,
                        chat_id: int) -> int:
    """Send the current question for *chat_id*."""
    user = user_manager.get_user(chat_id)
    if user is None:
        return ConversationHandler.END

    if not await _validate_user_test_session(context, chat_id):
        return ConversationHandler.END

    question_set = user.get("question_set", [])
    idx = user["current_question"]

    if idx >= len(question_set):
        return await end_quiz(update, context, chat_id)

    text, markup = get_question_message(question_set[idx], idx, len(question_set))
    sent_msg = await safe_send(context.bot, chat_id, text, reply_markup=markup, parse_mode="Markdown")
    user["active_question_message_id"] = sent_msg.message_id
    user["active_question_index"] = idx

    _cancel_timeout_job(context, chat_id)
    timer_seconds = int(user.get("timer_seconds", 0) or 0)
    user["question_deadline_ts"] = (
        datetime.now(timezone.utc).timestamp() + timer_seconds
        if timer_seconds > 0
        else None
    )

    if timer_seconds > 0 and context.job_queue is not None:
        job = context.job_queue.run_once(
            question_timeout_handler,
            when=timer_seconds,
            data={"chat_id": chat_id, "question_index": idx},
            name=f"qtimeout_{chat_id}",
        )
        _get_timeout_jobs(context)[chat_id] = job

    return QUIZ


async def question_timeout_handler(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Auto-progress when a user doesn't answer within the configured timer."""
    data = context.job.data or {}
    chat_id = data.get("chat_id")
    question_index = data.get("question_index")
    if chat_id is None:
        return

    user = user_manager.get_user(chat_id)
    if user is None:
        return

    if not await _validate_user_test_session(context, chat_id):
        return

    await _advance_on_timeout(context, chat_id, int(question_index))


def _extract_option_index_from_text(transcript: str, options_count: int) -> int | None:
    """Return option index parsed from transcript (A/B/C/D), else None."""
    text = transcript.lower().strip().replace("-", " ")

    # Strategy 1: explicit phrase capture: "option b", "answer is dee", etc.
    phrase_patterns = [
        r"\b(?:option|answer|ans|choice|choose|chose)\s*(?:is|number|num|no)?\s*([a-z0-9]+)\b",
        r"\b(?:i\s*choose|my\s*answer\s*is|it\s*is|its)\s+([a-z0-9]+)\b",
    ]
    for pattern in phrase_patterns:
        for match in re.finditer(pattern, text):
            idx = _token_to_option_index(match.group(1), options_count)
            if idx is not None:
                return idx

    # Strategy 2: standalone letter token in transcript.
    standalone = re.findall(r"\b([a-d])\b", text)
    if standalone:
        idx = _token_to_option_index(standalone[-1], options_count)
        if idx is not None:
            return idx

    # Strategy 3: general token scan from right to left (most likely final answer token).
    tokens = re.findall(r"[a-z0-9]+", text)
    for token in reversed(tokens):
        idx = _token_to_option_index(token, options_count)
        if idx is not None:
            return idx

    # Strategy 4: fuzzy bigram scan for phrases like "option bee" split oddly.
    for i in range(len(tokens) - 1):
        combined = tokens[i] + tokens[i + 1]
        idx = _token_to_option_index(combined, options_count)
        if idx is not None:
            return idx

    return None


async def _transcribe_voice_message(update: Update,
                                    context: ContextTypes.DEFAULT_TYPE,
                                    options_count: int | None = None) -> str | None:
    """Download voice note, convert to wav, and return transcript text."""
    if not SR_AVAILABLE:
        return None
    message = update.message
    if not message or not message.voice:
        return None

    input_path = ""
    wav_path = ""
    cleaned_wav_path = ""

    try:
        file_obj = await context.bot.get_file(message.voice.file_id)

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as src:
            input_path = src.name

        wav_path = input_path.replace(".ogg", ".wav")
        cleaned_wav_path = input_path.replace(".ogg", "_clean.wav")
        await file_obj.download_to_drive(custom_path=input_path)

        # Convert Telegram voice note to WAV using ffmpeg directly.
        subprocess.run(
            [
                FFMPEG_EXE,
                "-y",
                "-i",
                input_path,
                "-ar",
                "16000",
                "-ac",
                "1",
                wav_path,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        recognizer = sr.Recognizer()
        candidates: list[str] = []

        def _try_add_candidate(text: str | None) -> int | None:
            if not text:
                return None
            clean = text.strip()
            if not clean:
                return None
            candidates.append(clean)
            if options_count is not None:
                idx = _extract_option_index_from_text(clean, options_count)
                if idx is not None:
                    return idx
            return None

        def _collect_fast(path: str) -> int | None:
            """Fast path: a few direct calls with early exit."""
            with sr.AudioFile(path) as source:
                audio_data = recognizer.record(source)

            for lang in ("en-IN", "en-US"):
                try:
                    transcript = recognizer.recognize_google(audio_data, language=lang)
                    idx = _try_add_candidate(transcript)
                    if idx is not None:
                        return idx
                except sr.UnknownValueError:
                    continue
                except Exception:
                    continue

            # One alternative pass only (primary locale) for speed.
            try:
                alt = recognizer.recognize_google(audio_data, language="en-IN", show_all=True)
                if isinstance(alt, dict):
                    for candidate in alt.get("alternative", []):
                        idx = _try_add_candidate(candidate.get("transcript", ""))
                        if idx is not None:
                            return idx
            except Exception:
                pass

            return None

        # 1) Fast raw-audio pass (most requests should finish here).
        fast_idx = _collect_fast(wav_path)
        if fast_idx is not None and options_count is not None:
            for text in candidates:
                if _extract_option_index_from_text(text, options_count) == fast_idx:
                    return text

        # 2) Heavy fallback only if not yet parseable: denoise + retry.
        subprocess.run(
            [
                FFMPEG_EXE,
                "-y",
                "-i",
                input_path,
                "-af",
                "highpass=f=120,lowpass=f=3800,dynaudnorm",
                "-ar",
                "16000",
                "-ac",
                "1",
                cleaned_wav_path,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        if os.path.exists(cleaned_wav_path):
            fallback_idx = _collect_fast(cleaned_wav_path)
            if fallback_idx is not None and options_count is not None:
                for text in candidates:
                    if _extract_option_index_from_text(text, options_count) == fallback_idx:
                        return text

        # Keep first occurrence order and remove empty duplicates.
        deduped: list[str] = []
        seen = set()
        for text in candidates:
            norm = text.lower().strip()
            if norm and norm not in seen:
                seen.add(norm)
                deduped.append(text)

        # Prefer transcripts that actually decode into A/B/C/D.
        if options_count is not None:
            for text in deduped:
                if _extract_option_index_from_text(text, options_count) is not None:
                    return text

        return deduped[0] if deduped else None
    except Exception as exc:
        logger.exception("Voice transcription failed: %s", exc)
        return None
    finally:
        for p in (input_path, wav_path, cleaned_wav_path):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    logger.warning("Failed to remove temp file: %s", p)


async def _process_selected_answer(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE,
                                   chat_id: int,
                                   selected_index: int,
                                   query=None,
                                   answered_question_index: int | None = None,
                                   submitted_ts: float | None = None) -> int:
    """Score selected answer, send feedback, then move to next question."""
    user = user_manager.get_user(chat_id)
    if user is None:
        if query is not None:
            await safe_edit(query, "⚠️ Session expired. Please /start again.")
        elif update.message:
            await safe_reply(update.message, "⚠️ Session expired. Please /start again.")
        return ConversationHandler.END

    if not await _validate_user_test_session(context, chat_id):
        return ConversationHandler.END

    idx = int(user["current_question"] if answered_question_index is None else answered_question_index)
    question_set = user.get("question_set", [])
    if idx >= len(question_set):
        return await end_quiz(update, context, chat_id)

    if _is_submission_late(user, idx, submitted_ts=submitted_ts):
        return await _advance_on_timeout(
            context,
            chat_id,
            idx,
            message="⏰ Answer received after timeout. Moving to the next question...",
        )

    # Protect against stale answers reaching this point.
    if idx != int(user.get("current_question", 0)):
        return QUIZ

    _cancel_timeout_job(context, chat_id)

    # Button-based answers edit the message text and remove keyboard naturally.
    if query is None:
        await _disable_active_question_buttons(context, chat_id, expected_index=idx)

    question = question_set[idx]
    labels = [chr(ord("A") + i) for i in range(len(question["options"]))]

    if selected_index < 0 or selected_index >= len(question["options"]):
        if query is not None:
            await safe_edit(query, "⚠️ Invalid option selected.")
        elif update.message:
            await safe_reply(update.message, "⚠️ Invalid option selected.")
        return QUIZ

    is_correct = check_answer(question, selected_index)
    mark_correct = user.get("mark_correct", 1)
    mark_incorrect = user.get("mark_incorrect", 0)
    user_manager.update_score(chat_id, is_correct, mark_correct=mark_correct, mark_incorrect=mark_incorrect)
    user_manager.record_answer(
        chat_id,
        question_text=question["question"],
        user_answer=f"{labels[selected_index]}. {question['options'][selected_index]}",
        correct_answer=f"{labels[question['correct_option']]}. {question['options'][question['correct_option']]}",
        is_correct=is_correct,
    )

    if is_correct:
        feedback = f"✅ Correct! The answer is *{labels[question['correct_option']]}. {question['options'][question['correct_option']]}*"
    else:
        feedback = (
            f"❌ Wrong! You chose *{labels[selected_index]}. {question['options'][selected_index]}*\n"
            f"The correct answer is *{labels[question['correct_option']]}. {question['options'][question['correct_option']]}*"
        )

    if query is not None:
        await safe_edit(query, text=feedback, parse_mode="Markdown")
        user.pop("active_question_message_id", None)
        user.pop("active_question_index", None)
    elif update.message:
        await safe_reply(update.message, text=feedback, parse_mode="Markdown")

    user["current_question"] += 1
    return await send_question(update, context, chat_id)


async def quiz_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Process an inline-button answer press."""
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    user = user_manager.get_user(chat_id)
    if user is None:
        await safe_edit(query, "⚠️ Session expired. Please /start again.")
        return ConversationHandler.END

    parts = query.data.split("_")
    if len(parts) != 3:
        await query.answer("Invalid answer payload.", show_alert=False)
        return QUIZ

    answered_question_index = int(parts[1])
    selected_index = int(parts[2])

    current_index = int(user.get("current_question", 0))
    if answered_question_index != current_index:
        await query.answer("⏰ Time over for that question. Please answer the latest one.", show_alert=False)
        return QUIZ

    return await _process_selected_answer(
        update=update,
        context=context,
        chat_id=chat_id,
        selected_index=selected_index,
        query=query,
        answered_question_index=answered_question_index,
    )


async def quiz_voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Process a voice-note answer by transcribing to A/B/C/D."""
    if not SR_AVAILABLE:
        await safe_reply(update.message, "🎤 Voice answers are not available right now. Please type A, B, C, or D.")
        return QUIZ
    chat_id = update.effective_chat.id
    user = user_manager.get_user(chat_id)

    if user is None:
        await safe_reply(update.message, "⚠️ Session expired. Please /start again.")
        return ConversationHandler.END

    if not await _validate_user_test_session(context, chat_id):
        return ConversationHandler.END

    idx = user["current_question"]
    question_set = user.get("question_set", [])
    if idx >= len(question_set):
        return await end_quiz(update, context, chat_id)

    transcript = await _transcribe_voice_message(update, context, options_count=len(question_set[idx]["options"]))
    if not transcript:
        await safe_reply(
            update.message,
            "🎤 I couldn't understand that voice answer. "
            "Try saying: option A / option B / option C / option D."
        )
        return QUIZ

    options_count = len(question_set[idx]["options"])
    selected_index = _extract_option_index_from_text(transcript, options_count)

    if selected_index is None:
        await safe_reply(
            update.message,
            f"🎤 I heard: *{transcript}*\n"
            "Please answer with only A, B, C, or D.",
            parse_mode="Markdown",
        )
        return QUIZ

    await safe_reply(update.message, f"🎧 Heard: *{transcript}*", parse_mode="Markdown")
    return await _process_selected_answer(
        update=update,
        context=context,
        chat_id=chat_id,
        selected_index=selected_index,
        answered_question_index=idx,
        submitted_ts=update.message.date.timestamp() if update.message and update.message.date else None,
    )


async def quiz_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Allow typed A/B/C/D answers while in quiz state."""
    chat_id = update.effective_chat.id
    user = user_manager.get_user(chat_id)

    if user is None:
        await safe_reply(update.message, "⚠️ Session expired. Please /start again.")
        return ConversationHandler.END

    if not await _validate_user_test_session(context, chat_id):
        return ConversationHandler.END

    idx = user["current_question"]
    question_set = user.get("question_set", [])
    if idx >= len(question_set):
        return await end_quiz(update, context, chat_id)

    selected_index = _extract_option_index_from_text(update.message.text, len(question_set[idx]["options"]))
    if selected_index is None:
        await safe_reply(update.message, "Please answer with A, B, C, or D.")
        return QUIZ

    return await _process_selected_answer(
        update=update,
        context=context,
        chat_id=chat_id,
        selected_index=selected_index,
        answered_question_index=idx,
        submitted_ts=update.message.date.timestamp() if update.message and update.message.date else None,
    )


# ══════════════════════════════════════════════
# End of quiz
# ══════════════════════════════════════════════

async def end_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE,
                   chat_id: int) -> int:
    """Display results and notify parent."""
    _cancel_timeout_job(context, chat_id)
    user = user_manager.get_user(chat_id)
    if user is None:
        return ConversationHandler.END
    summary = get_result_summary(user)

    await safe_send(context.bot, chat_id, summary, parse_mode="Markdown")

    # Save to disk
    user_manager.save_results()
    attempt = {
        "attempt_id": uuid4().hex,
        "submitted_at": datetime.now(IST_TZ).isoformat(),
        "test_id": user.get("test_id", "default"),
        "test_name": user.get("test_name", "Untitled Test"),
        "test_version": user.get("test_version", 1),
        "student": {
            "name": user.get("name", ""),
            "roll": user.get("roll", ""),
            "phone": user.get("phone", ""),
            "chat_id": chat_id,
            "parent_username": user.get("parent_username", ""),
        },
        "score": user.get("score", 0),
        "total_questions": user.get("total_questions", 0),
        "total_marks": user.get("total_marks", user.get("total_questions", 0)),
        "answers": user.get("answers", []),
    }
    user_manager.save_attempt(attempt)

    # Notify parent
    parent_username = user.get("parent_username", "")
    parent_chat_id = user_manager.get_parent_chat_id(parent_username)

    success, msg = await send_parent_notification(
        bot=context.bot,
        parent_chat_id=parent_chat_id,
        user_data=user,
    )

    await safe_send(context.bot, chat_id, msg, parse_mode="Markdown")

    return ConversationHandler.END


# ══════════════════════════════════════════════
# Leaderboard
# ══════════════════════════════════════════════

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show top scores."""
    entries = user_manager.get_leaderboard()
    if not entries:
        await safe_reply(update.message, "📊 No quiz results yet!")
        return

    lines = ["🏆 *Leaderboard*\n"]
    medals = ["🥇", "🥈", "🥉"]
    for i, e in enumerate(entries):
        prefix = medals[i] if i < 3 else f"  {i + 1}."
        lines.append(f"{prefix} {e['name']} (Roll: {e['roll']}) — {e['score']}/{e['total']}")

    await safe_reply(update.message, "\n".join(lines), parse_mode="Markdown")


# ══════════════════════════════════════════════
# Cancel
# ══════════════════════════════════════════════

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel."""
    await safe_reply(
        update.message,
        "❌ Quiz cancelled. Send /start to begin again."
    )
    return ConversationHandler.END


# ══════════════════════════════════════════════
# Error handler
# ══════════════════════════════════════════════

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log uncaught exceptions."""
    if isinstance(context.error, TimedOut):
        logger.warning("Telegram request timed out; update will continue on next interaction.")
        return
    logger.error("Exception while handling update:", exc_info=context.error)


# ══════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════

def main() -> None:
    """Build the Application and run polling."""
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌  Please set your bot token in config.py first!")
        sys.exit(1)

    async def _post_init(app: Application) -> None:
        global SEND_WORKER_TASK
        if SEND_WORKER_TASK is None:
            SEND_WORKER_TASK = asyncio.create_task(_send_worker(), name="send_worker")

    async def _post_shutdown(app: Application) -> None:
        global SEND_WORKER_TASK
        if SEND_WORKER_TASK is not None:
            await SEND_QUEUE.put(None)
            await SEND_WORKER_TASK
            SEND_WORKER_TASK = None

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .defaults(Defaults(protect_content=True))
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .pool_timeout(30.0)
        .get_updates_connect_timeout(30.0)
        .get_updates_read_timeout(30.0)
        .get_updates_write_timeout(30.0)
        .get_updates_pool_timeout(30.0)
        .build()
    )

    # Conversation handler for registration + quiz
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, name_handler)],
            PHONE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, phone_handler)],
            PARENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, parent_handler)],
            TEST_SELECT: [CallbackQueryHandler(test_select_handler, pattern=r"^test_.+")],
            ROLL:   [MessageHandler(filters.TEXT & ~filters.COMMAND, roll_handler)],
            QUIZ:   [
                CallbackQueryHandler(quiz_callback_handler, pattern=r"^answer_\d+_\d+$"),
                MessageHandler(filters.VOICE, quiz_voice_handler),
                MessageHandler(filters.TEXT & ~filters.COMMAND, quiz_text_handler),
            ],
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
