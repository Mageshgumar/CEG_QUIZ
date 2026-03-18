"""
User data management — registration storage, input validation, and persistence.
"""

import json
import os
import re
from config import RESULTS_FILE


# ──────────────────────────────────────────────
# Input validators
# ──────────────────────────────────────────────

def validate_phone(phone: str) -> bool:
    """Return True if *phone* is all digits and 7-15 characters long."""
    return bool(re.fullmatch(r"\d{7,15}", phone.strip()))


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

    def update_score(self, chat_id: int, is_correct: bool) -> None:
        """Increment score if the answer was correct."""
        if chat_id in self._users:
            if is_correct:
                self._users[chat_id]["score"] += 1

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

    def get_parent_chat_id(self, username: str) -> int | None:
        return self._parent_chat_ids.get(username.lower())

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
