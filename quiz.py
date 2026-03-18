"""
Quiz logic — question loading, formatting, answer checking, and result summary.
"""

import json
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import QUESTIONS_FILE

# ──────────────────────────────────────────────
# Question loading
# ──────────────────────────────────────────────

def load_questions(filepath: str | None = None) -> list[dict]:
    """Load questions from the JSON file."""
    path = filepath or os.path.join(os.path.dirname(__file__), QUESTIONS_FILE)
    with open(path, "r") as fp:
        return json.load(fp)


def load_questions_by_difficulty(difficulty: str | None = None) -> list[dict]:
    """Optionally filter questions by difficulty level."""
    questions = load_questions()
    if difficulty:
        questions = [q for q in questions if q.get("difficulty") == difficulty]
    return questions


# ──────────────────────────────────────────────
# Question formatting
# ──────────────────────────────────────────────

def get_question_message(question: dict, index: int, total: int):
    """
    Return (text, reply_markup) for a single question.
    Uses inline keyboard buttons labelled A / B / C / D.
    """
    labels = ["A", "B", "C", "D"]
    text = (
        f"📝 *Question {index + 1}/{total}*\n\n"
        f"{question['question']}\n\n"
    )
    for i, option in enumerate(question["options"]):
        text += f"  {labels[i]}. {option}\n"

    # Each button's callback_data encodes the option index
    keyboard = [
        [
            InlineKeyboardButton(f"{labels[i]}",
                                 callback_data=f"answer_{i}")
            for i in range(len(question["options"]))
        ]
    ]
    return text, InlineKeyboardMarkup(keyboard)


# ──────────────────────────────────────────────
# Answer checking
# ──────────────────────────────────────────────

def check_answer(question: dict, selected_index: int) -> bool:
    """Return True if *selected_index* matches the correct option."""
    return selected_index == question["correct_option"]


# ──────────────────────────────────────────────
# Result summary
# ──────────────────────────────────────────────

def get_result_summary(user_data: dict) -> str:
    """Build a formatted result summary string."""
    labels = ["A", "B", "C", "D"]
    score = user_data["score"]
    total = user_data["total_questions"]
    percentage = (score / total * 100) if total else 0

    lines = [
        "🏆 *Quiz Results*",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"👤 *Name:* {user_data['name']}",
        f"🆔 *Roll Number:* {user_data['roll']}",
        f"📊 *Score:* {score}/{total} ({percentage:.0f}%)",
        f"━━━━━━━━━━━━━━━━━━━━\n",
    ]

    # Grade emoji
    if percentage >= 90:
        lines.append("🌟 *Outstanding!*\n")
    elif percentage >= 70:
        lines.append("👏 *Great job!*\n")
    elif percentage >= 50:
        lines.append("👍 *Good effort!*\n")
    else:
        lines.append("📖 *Keep studying!*\n")

    lines.append("📋 *Detailed Breakdown:*\n")
    for i, ans in enumerate(user_data["answers"]):
        status = "✅" if ans["is_correct"] else "❌"
        lines.append(
            f"{status} *Q{i + 1}.* {ans['question']}\n"
            f"   Your answer: {ans['user_answer']}\n"
            f"   Correct answer: {ans['correct_answer']}\n"
        )

    return "\n".join(lines)
