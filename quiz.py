"""
Quiz logic — question loading, formatting, answer checking, and result summary.
"""

from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import QUESTIONS_FILE, TESTS_FILE

IST_TZ = timezone(timedelta(hours=5, minutes=30))

# ──────────────────────────────────────────────
# Question loading
# ──────────────────────────────────────────────

def load_questions(filepath: str | None = None) -> list[dict]:
    """Load questions from the JSON file."""
    path = filepath or os.path.join(os.path.dirname(__file__), QUESTIONS_FILE)
    with open(path, "r") as fp:
        return json.load(fp)


def _ensure_test_file() -> None:
    """Create tests store with a default active test if missing."""
    if os.path.exists(TESTS_FILE):
        return

    default_questions = load_questions()
    default_test = {
        "id": "default",
        "name": "Default Test",
        "timer_seconds": 30,
        "random_count": 0,
        "is_active": True,
        "version": 1,
        "questions": default_questions,
        "created_at": datetime.now(IST_TZ).isoformat(),
        "updated_at": datetime.now(IST_TZ).isoformat(),
    }

    with open(TESTS_FILE, "w") as fp:
        json.dump([default_test], fp, indent=2)


def load_tests() -> list[dict]:
    """Load all tests from persistent storage."""
    _ensure_test_file()
    with open(TESTS_FILE) as fp:
        tests = json.load(fp)
    tests = tests if isinstance(tests, list) else []

    normalized = False
    for test in tests:
        if "one_time" not in test:
            test["one_time"] = False
            normalized = True
        if "mark_correct" not in test:
            test["mark_correct"] = 1
            normalized = True
        if "mark_incorrect" not in test:
            test["mark_incorrect"] = 0
            normalized = True

        question_count = len(test.get("questions") or [])
        random_count = int(test.get("random_count", 0) or 0)
        if question_count and random_count > question_count:
            test["random_count"] = question_count
            normalized = True
        elif not question_count and random_count:
            test["random_count"] = 0
            normalized = True

    if normalized:
        save_tests(tests)

    return tests


def save_tests(tests: list[dict]) -> None:
    """Save all tests to persistent storage."""
    with open(TESTS_FILE, "w") as fp:
        json.dump(tests, fp, indent=2)


def get_active_test() -> dict | None:
    """Return currently active test or None when no active test exists."""
    tests = load_tests()
    for test in tests:
        if test.get("is_active"):
            return test
    return None


def get_active_tests() -> list[dict]:
    """Return all tests currently marked active."""
    return [test for test in load_tests() if test.get("is_active")]


def set_active_test(test_id: str) -> bool:
    """Mark a test active by ID. Returns True if found."""
    tests = load_tests()
    found = False
    for test in tests:
        if test.get("id") == test_id:
            test["is_active"] = True
            found = True
    if found:
        save_tests(tests)
    return found


def set_test_inactive(test_id: str) -> bool:
    """Mark a test inactive by ID. Returns True if found."""
    tests = load_tests()
    found = False
    for test in tests:
        if test.get("id") == test_id:
            test["is_active"] = False
            found = True
    if found:
        save_tests(tests)
    return found


def set_all_tests_inactive() -> bool:
    """Mark all tests inactive. Returns True if at least one test existed."""
    tests = load_tests()
    if not tests:
        return False
    for test in tests:
        test["is_active"] = False
    save_tests(tests)
    return True


def get_test_by_id(test_id: str) -> dict | None:
    """Return test dict by ID or None."""
    for test in load_tests():
        if test.get("id") == test_id:
            return test
    return None


def update_test(test_id: str,
                name: str,
                timer_seconds: int,
                random_count: int,
                questions: list[dict],
                one_time: bool,
                mark_correct: int = 1,
                mark_incorrect: int = 0,
                make_active: bool = False) -> bool:
    """Replace test content and metadata, incrementing version for session invalidation."""
    tests = load_tests()
    found = False
    now = datetime.now(IST_TZ).isoformat()

    for test in tests:
        if test.get("id") != test_id:
            continue

        found = True
        test["name"] = name.strip() or test.get("name", "Untitled Test")
        test["timer_seconds"] = max(5, int(timer_seconds))
        test["random_count"] = max(0, min(int(random_count), len(questions)))
        test["one_time"] = bool(one_time)
        test["mark_correct"] = int(mark_correct)
        test["mark_incorrect"] = int(mark_incorrect)
        test["questions"] = questions
        test["version"] = int(test.get("version", 1)) + 1
        test["updated_at"] = now
        if make_active:
            test["is_active"] = True

    if found:
        save_tests(tests)
    return found


def delete_test(test_id: str) -> bool:
    """Delete test by ID and keep remaining tests as-is."""
    tests = load_tests()
    filtered = [test for test in tests if test.get("id") != test_id]
    if len(filtered) == len(tests):
        return False
    save_tests(filtered)
    return True


def parse_test_file(content: str) -> list[dict]:
    """
    Parse uploaded text into a question list.

    Expected format:
    Q: Question text?
    A) Option A
    B) Option B
    C) Option C
    D) Option D
    ANS: B
    ---
    """
    lines = [line.strip() for line in content.splitlines()]
    idx = 0

    questions: list[dict] = []
    while idx < len(lines):
        if not lines[idx]:
            idx += 1
            continue
        if not lines[idx].upper().startswith("Q:"):
            raise ValueError(f"Expected 'Q:' at line {idx + 1}")

        question_text = lines[idx].split(":", 1)[1].strip()
        idx += 1

        options: list[str] = []
        expected_prefixes = ["A)", "B)", "C)", "D)"]
        for prefix in expected_prefixes:
            if idx >= len(lines) or not lines[idx].upper().startswith(prefix):
                raise ValueError(f"Expected '{prefix}' for question: {question_text}")
            options.append(lines[idx][2:].strip())
            idx += 1

        if idx >= len(lines) or not lines[idx].upper().startswith("ANS:"):
            raise ValueError(f"Expected 'ANS:' for question: {question_text}")

        ans_label = lines[idx].split(":", 1)[1].strip().upper()
        if ans_label not in ["A", "B", "C", "D"]:
            raise ValueError(f"Invalid answer label '{ans_label}' for question: {question_text}")
        correct_option = ord(ans_label) - ord("A")
        idx += 1

        # Optional separator.
        if idx < len(lines) and lines[idx] == "---":
            idx += 1

        questions.append(
            {
                "question": question_text,
                "options": options,
                "correct_option": correct_option,
            }
        )

    if not questions:
        raise ValueError("No questions parsed from the uploaded file")

    return questions


def add_test(test: dict, make_active: bool = False) -> None:
    """Insert a new test and optionally mark it active."""
    tests = load_tests()
    if make_active:
        test["is_active"] = True
    test.setdefault("version", 1)
    test.setdefault("updated_at", datetime.now(IST_TZ).isoformat())
    tests.append(test)
    save_tests(tests)


def build_test(name: str,
               questions: list[dict],
               timer_seconds: int,
               random_count: int,
               one_time: bool,
               mark_correct: int = 1,
               mark_incorrect: int = 0,
               is_active: bool = False) -> dict:
    """Create a normalized test document."""
    safe_name = name.strip() or "Untitled Test"
    hash_src = f"{safe_name}:{datetime.now(IST_TZ).isoformat()}"
    test_id = hashlib.sha1(hash_src.encode("utf-8")).hexdigest()[:12]
    now = datetime.now(IST_TZ).isoformat()

    return {
        "id": test_id,
        "name": safe_name,
        "timer_seconds": max(5, int(timer_seconds)),
        "random_count": max(0, min(int(random_count), len(questions))),
        "one_time": bool(one_time),
        "mark_correct": int(mark_correct),
        "mark_incorrect": int(mark_incorrect),
        "is_active": bool(is_active),
        "version": 1,
        "questions": questions,
        "created_at": now,
        "updated_at": now,
    }


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
                                 callback_data=f"answer_{index}_{i}")
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
    # Use total_marks if available (new system), otherwise fall back to total_questions (legacy)
    total = user_data.get("total_marks", user_data["total_questions"])
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
