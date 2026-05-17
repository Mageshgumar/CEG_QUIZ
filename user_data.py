"""
User data management — registration storage, input validation, and persistence.
"""

import json
import os
import re
from urllib.parse import quote

import requests

from config import RESULTS_FILE, PARENTS_FILE, ATTEMPTS_FILE, API_BASE_URL, API_KEY, TEACHER_USERNAME


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

    def _normalize_teacher_username(self, teacher_username: str | None) -> str:
        normalized = (teacher_username or TEACHER_USERNAME).strip().lower()
        return normalized or TEACHER_USERNAME.lower()

    def _attempt_belongs_to_teacher(self, attempt: dict, teacher_username: str) -> bool:
        stored = str(attempt.get("teacher_username", "")).strip().lower()
        if not stored:
            stored = TEACHER_USERNAME.lower()
        return stored == teacher_username

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

    def register_parent(self, username: str, chat_id: int, teacher_username: str | None = None) -> None:
        """Map a parent's @username to their chat_id."""
        if self._api_enabled():
            self._api_request(
                "POST",
                "/api/parents",
                payload={"username": username, "chat_id": chat_id},
            )
            return
        teacher_key = self._normalize_teacher_username(teacher_username)
        self._parent_chat_ids.setdefault(teacher_key, {})
        self._parent_chat_ids[teacher_key][username.lower()] = chat_id
        self._save_parent_chat_ids()

    def get_parent_chat_id(self, username: str, teacher_username: str | None = None) -> int | None:
        if self._api_enabled():
            data = self._api_request("GET", f"/api/parents/{quote(username)}")
            if isinstance(data, dict):
                return data.get("chat_id")
            return None
        teacher_key = self._normalize_teacher_username(teacher_username)
        return (self._parent_chat_ids.get(teacher_key) or {}).get(username.lower())

    def _save_parent_chat_ids(self) -> None:
        """Persist parent @username → chat_id mapping to disk."""
        if self._api_enabled():
            return
        with open(PARENTS_FILE, "w") as fp:
            json.dump(self._parent_chat_ids, fp, indent=2)

    def _load_parent_chat_ids(self) -> None:
        """Load parent mapping from disk if it exists."""
        if self._api_enabled():
            return
        if not os.path.exists(PARENTS_FILE):
            return

        try:
            with open(PARENTS_FILE) as fp:
                data = json.load(fp)
            if isinstance(data, dict):
                if all(isinstance(value, dict) for value in data.values()):
                    self._parent_chat_ids = {
                        str(teacher).lower(): {
                            str(username).lower(): int(chat_id)
                            for username, chat_id in value.items()
                        }
                        for teacher, value in data.items()
                    }
                else:
                    self._parent_chat_ids = {
                        TEACHER_USERNAME.lower(): {
                            str(username).lower(): int(chat_id)
                            for username, chat_id in data.items()
                        }
                    }
        except (json.JSONDecodeError, ValueError, TypeError):
            self._parent_chat_ids = {}

    def save_attempt(self, attempt: dict, teacher_username: str | None = None) -> None:
        """Append a completed test attempt to persistent storage."""
        owner = self._normalize_teacher_username(teacher_username)
        attempt["teacher_username"] = owner
        if self._api_enabled():
            self._api_request("POST", "/api/attempts", payload=attempt)
            return
        attempts = []
        if os.path.exists(ATTEMPTS_FILE):
            try:
                with open(ATTEMPTS_FILE) as fp:
                    data = json.load(fp)
                attempts = data if isinstance(data, list) else []
            except json.JSONDecodeError:
                attempts = []
        attempts.append(attempt)
        with open(ATTEMPTS_FILE, "w") as fp:
            json.dump(attempts, fp, indent=2)

    def load_attempts(self, teacher_username: str | None = None) -> list[dict]:
        """Load historical attempts for teacher dashboard."""
        owner = self._normalize_teacher_username(teacher_username)
        if self._api_enabled():
            data = self._api_request("GET", "/api/attempts")
            attempts = data if isinstance(data, list) else []
            return [a for a in attempts if self._attempt_belongs_to_teacher(a, owner)]
        if os.path.exists(ATTEMPTS_FILE):
            try:
                with open(ATTEMPTS_FILE) as fp:
                    data = json.load(fp)
                if isinstance(data, list):
                    return [a for a in data if self._attempt_belongs_to_teacher(a, owner)]
            except json.JSONDecodeError:
                return []
        return []

    def load_all_attempts(self) -> list[dict]:
        """Load all attempts without teacher filtering (API/admin use)."""
        if self._api_enabled():
            data = self._api_request("GET", "/api/attempts")
            return data if isinstance(data, list) else []
        if os.path.exists(ATTEMPTS_FILE):
            try:
                with open(ATTEMPTS_FILE) as fp:
                    data = json.load(fp)
                return data if isinstance(data, list) else []
            except json.JSONDecodeError:
                return []
        return []

    def has_attempt_for_roll(self, test_id: str, roll: str, teacher_username: str | None = None) -> bool:
        """Return True if the given roll has already submitted this test."""
        normalized_roll = str(roll).strip()
        for attempt in self.load_attempts(teacher_username):
            if str(attempt.get("test_id", "")) != str(test_id):
                continue
            student_roll = str((attempt.get("student") or {}).get("roll", "")).strip()
            if student_roll == normalized_roll:
                return True
        return False

    def delete_attempt_by_id(self, attempt_id: str, teacher_username: str | None = None) -> tuple[bool, dict | None]:
        """Delete an attempt by ID and return (deleted, removed_attempt)."""
        if self._api_enabled():
            data = self._api_request("DELETE", f"/api/attempts/{attempt_id}")
            if isinstance(data, dict):
                return bool(data.get("deleted")), data.get("removed")
            return False, None
        owner = self._normalize_teacher_username(teacher_username)
        attempts = []
        if os.path.exists(ATTEMPTS_FILE):
            try:
                with open(ATTEMPTS_FILE) as fp:
                    data = json.load(fp)
                attempts = data if isinstance(data, list) else []
            except json.JSONDecodeError:
                attempts = []
        kept = []
        removed = None

        for attempt in attempts:
            if (
                str(attempt.get("attempt_id", "")) == str(attempt_id)
                and self._attempt_belongs_to_teacher(attempt, owner)
                and removed is None
            ):
                removed = attempt
                continue
            kept.append(attempt)

        if removed is None:
            return False, None

        with open(ATTEMPTS_FILE, "w") as fp:
            json.dump(kept, fp, indent=2)
        return True, removed

    def delete_attempts_by_test_id(self, test_id: str, teacher_username: str | None = None) -> int:
        """Delete all attempts for a test ID. Returns number removed."""
        if self._api_enabled():
            data = self._api_request("DELETE", f"/api/attempts/by-test/{test_id}")
            if isinstance(data, dict):
                return int(data.get("removed_count", 0) or 0)
            return 0
        owner = self._normalize_teacher_username(teacher_username)
        attempts = []
        if os.path.exists(ATTEMPTS_FILE):
            try:
                with open(ATTEMPTS_FILE) as fp:
                    data = json.load(fp)
                attempts = data if isinstance(data, list) else []
            except json.JSONDecodeError:
                attempts = []
        kept = []
        removed_count = 0

        for attempt in attempts:
            if (
                str(attempt.get("test_id", "")) == str(test_id)
                and self._attempt_belongs_to_teacher(attempt, owner)
            ):
                removed_count += 1
                continue
            kept.append(attempt)

        if removed_count:
            with open(ATTEMPTS_FILE, "w") as fp:
                json.dump(kept, fp, indent=2)
        return removed_count

    def roll_exists_in_attempts(self, roll: str, teacher_username: str | None = None) -> bool:
        """Return True if the roll has appeared in any historical attempt."""
        normalized_roll = str(roll).strip()
        for attempt in self.load_attempts(teacher_username):
            student_roll = str((attempt.get("student") or {}).get("roll", "")).strip()
            if student_roll == normalized_roll:
                return True
        return False

    def _api_enabled(self) -> bool:
        return bool(API_BASE_URL)

    def _api_headers(self) -> dict:
        return {"X-API-Key": API_KEY} if API_KEY else {}

    def _api_url(self, path: str) -> str:
        base = API_BASE_URL.rstrip("/")
        if base and not base.startswith("http://") and not base.startswith("https://"):
            base = f"https://{base}"
        return f"{base}{path}"

    def _api_request(self, method: str, path: str, payload=None):
        if not self._api_enabled():
            return None
        resp = requests.request(
            method,
            self._api_url(path),
            json=payload,
            headers=self._api_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        if resp.content:
            return resp.json()
        return None

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
