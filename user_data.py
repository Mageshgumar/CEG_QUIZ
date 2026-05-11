"""
User data management — registration storage, input validation, and persistence.
"""

import json
import os
import re
from config import RESULTS_FILE, PARENTS_FILE, ATTEMPTS_FILE


# ──────────────────────────────────────────────
# Input validators
# ──────────────────────────────────────────────

def validate_phone(phone: str) -> bool:
    """Return True if *phone* is exactly 10 digits."""
    return bool(re.fullmatch(r"\d{10}", phone.strip()))


def validate_roll(roll: str) -> bool:
    """Return True if *roll* is exactly 10 digits."""
    return bool(re.fullmatch(r"\d{10}", roll.strip()))


def validate_parent_username(username: str) -> bool:
    """Return True if *username* starts with '@' and has ≥2 characters."""
    username = username.strip()
    return username.startswith("@") and len(username) >= 2


# ──────────────────────────────────────────────
# UserDataManager
# ──────────────────────────────────────────────

class UserDataManager:
    """In-memory store for user registration data and quiz results."""

    def __init__(self):
        # chat_id → {name, phone, roll, parent_username, score, answers, ...}
        self._users: dict[int, dict] = {}
        # parent_username → chat_id (populated when a parent /starts the bot)
        self._parent_chat_ids: dict[str, int] = {}
        self._load_parent_chat_ids()

    # ── user CRUD ────────────────────────────

    def create_user(self, chat_id: int) -> dict:
        """Initialise an empty record for *chat_id*."""
        self._users[chat_id] = {
            "name": "",
            "phone": "",
            "roll": "",
            "parent_username": "",
            "score": 0,
            "total_questions": 0,
            "current_question": 0,
            "answers": [],        # list of {question, user_answer, correct_answer, is_correct}
        }
        return self._users[chat_id]

    def get_user(self, chat_id: int) -> dict | None:
        """Return user dict or None."""
        return self._users.get(chat_id)

    def update_field(self, chat_id: int, field: str, value) -> None:
        if chat_id in self._users:
            self._users[chat_id][field] = value

    def update_score(self, chat_id: int, is_correct: bool, mark_correct: int = 1, mark_incorrect: int = 0) -> None:
        """Update score based on answer correctness and mark values."""
        if chat_id in self._users:
            if is_correct:
                self._users[chat_id]["score"] += mark_correct
            else:
                self._users[chat_id]["score"] += mark_incorrect

    def record_answer(self, chat_id: int, question_text: str,
                      user_answer: str, correct_answer: str,
                      is_correct: bool) -> None:
        """Append a per-question result entry."""
        if chat_id in self._users:
            self._users[chat_id]["answers"].append({
                "question": question_text,
                "user_answer": user_answer,
                "correct_answer": correct_answer,
                "is_correct": is_correct,
            })

    # ── parent chat-id mapping ───────────────

    def register_parent(self, username: str, chat_id: int) -> None:
        """Map a parent's @username to their chat_id."""
        self._parent_chat_ids[username.lower()] = chat_id
        self._save_parent_chat_ids()

    def get_parent_chat_id(self, username: str) -> int | None:
        return self._parent_chat_ids.get(username.lower())

    def _save_parent_chat_ids(self) -> None:
        """Persist parent @username → chat_id mapping to disk."""
        with open(PARENTS_FILE, "w") as fp:
            json.dump(self._parent_chat_ids, fp, indent=2)

    def _load_parent_chat_ids(self) -> None:
        """Load parent mapping from disk if it exists."""
        if not os.path.exists(PARENTS_FILE):
            return

        try:
            with open(PARENTS_FILE) as fp:
                data = json.load(fp)
            if isinstance(data, dict):
                # Normalize keys and ensure chat IDs are integers.
                self._parent_chat_ids = {
                    str(username).lower(): int(chat_id)
                    for username, chat_id in data.items()
                }
        except (json.JSONDecodeError, ValueError, TypeError):
            self._parent_chat_ids = {}

    def save_attempt(self, attempt: dict) -> None:
        """Append a completed test attempt to persistent storage."""
        attempts = self.load_attempts()
        attempts.append(attempt)
        with open(ATTEMPTS_FILE, "w") as fp:
            json.dump(attempts, fp, indent=2)

    def load_attempts(self) -> list[dict]:
        """Load historical attempts for teacher dashboard."""
        if os.path.exists(ATTEMPTS_FILE):
            try:
                with open(ATTEMPTS_FILE) as fp:
                    data = json.load(fp)
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                return []
        return []

    def has_attempt_for_roll(self, test_id: str, roll: str) -> bool:
        """Return True if the given roll has already submitted this test."""
        normalized_roll = str(roll).strip()
        for attempt in self.load_attempts():
            if str(attempt.get("test_id", "")) != str(test_id):
                continue
            student_roll = str((attempt.get("student") or {}).get("roll", "")).strip()
            if student_roll == normalized_roll:
                return True
        return False

    def delete_attempt_by_id(self, attempt_id: str) -> tuple[bool, dict | None]:
        """Delete an attempt by ID and return (deleted, removed_attempt)."""
        attempts = self.load_attempts()
        kept = []
        removed = None

        for attempt in attempts:
            if str(attempt.get("attempt_id", "")) == str(attempt_id) and removed is None:
                removed = attempt
                continue
            kept.append(attempt)

        if removed is None:
            return False, None

        with open(ATTEMPTS_FILE, "w") as fp:
            json.dump(kept, fp, indent=2)
        return True, removed

    def delete_attempts_by_test_id(self, test_id: str) -> int:
        """Delete all attempts for a test ID. Returns number removed."""
        attempts = self.load_attempts()
        kept = []
        removed_count = 0

        for attempt in attempts:
            if str(attempt.get("test_id", "")) == str(test_id):
                removed_count += 1
                continue
            kept.append(attempt)

        if removed_count:
            with open(ATTEMPTS_FILE, "w") as fp:
                json.dump(kept, fp, indent=2)
        return removed_count

    def roll_exists_in_attempts(self, roll: str) -> bool:
        """Return True if the roll has appeared in any historical attempt."""
        normalized_roll = str(roll).strip()
        for attempt in self.load_attempts():
            student_roll = str((attempt.get("student") or {}).get("roll", "")).strip()
            if student_roll == normalized_roll:
                return True
        return False

    # ── persistence ──────────────────────────

    def save_results(self) -> None:
        """Persist all user data to JSON."""
        serialisable = {str(k): v for k, v in self._users.items()}
        with open(RESULTS_FILE, "w") as fp:
            json.dump(serialisable, fp, indent=2)

    def load_results(self) -> dict:
        """Load previously saved results (if any)."""
        if os.path.exists(RESULTS_FILE):
            with open(RESULTS_FILE) as fp:
                return json.load(fp)
        return {}

    # ── leaderboard ──────────────────────────

    def get_leaderboard(self, top_n: int = 10) -> list[dict]:
        """Return the top *top_n* users sorted by score (desc)."""
        entries = []
        for cid, data in self._users.items():
            if data.get("total_questions", 0) > 0:
                entries.append({
                    "name": data["name"],
                    "roll": data["roll"],
                    "score": data["score"],
                    "total": data["total_questions"],
                })
        entries.sort(key=lambda e: e["score"], reverse=True)
        return entries[:top_n]
