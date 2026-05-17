"""
Supabase storage adapter for tests, attempts, and parent mappings.
Provides a unified interface for both JSON and Supabase backends.
"""

import json
import os
from datetime import datetime, timezone, timedelta

import requests

from config import (
    SUPABASE_URL,
    SUPABASE_KEY,
    USE_SUPABASE,
    TESTS_FILE,
    ATTEMPTS_FILE,
    PARENTS_FILE,
)

IST_TZ = timezone(timedelta(hours=5, minutes=30))


class StorageBackend:
    """Unified storage interface for tests, attempts, and parents."""

    @staticmethod
    def _rest_url(table: str) -> str:
        return f"{SUPABASE_URL.rstrip('/')}/rest/v1/{table}"

    @staticmethod
    def _headers(prefer: str | None = None) -> dict:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    @staticmethod
    def _request(method: str, table: str, params: dict | None = None, payload=None,
                 prefer: str | None = None, on_conflict: str | None = None):
        url = StorageBackend._rest_url(table)
        # on_conflict must be a query-string param for PostgREST upserts
        merged_params = dict(params or {})
        if on_conflict:
            merged_params["on_conflict"] = on_conflict
        resp = requests.request(
            method,
            url,
            params=merged_params or None,
            json=payload,
            headers=StorageBackend._headers(prefer),
            timeout=15,
        )
        try:
            resp.raise_for_status()
        except Exception:
            # Surface the response body to make silent failures visible
            body = ""
            try:
                body = resp.text[:500]
            except Exception:
                pass
            raise RuntimeError(f"Supabase {method} /{table} failed [{resp.status_code}]: {body}")
        if resp.content:
            return resp.json()
        return None

    @staticmethod
    def get_tests() -> list[dict]:
        """Load all tests."""
        if not USE_SUPABASE:
            if os.path.exists(TESTS_FILE):
                with open(TESTS_FILE) as fp:
                    return json.load(fp) or []
            return []

        try:
            data = StorageBackend._request("GET", "tests", params={"select": "*"})
            return data or []
        except Exception as e:
            print(f"Error loading tests from Supabase: {e}")
            return []

    @staticmethod
    def save_tests(tests: list[dict]) -> None:
        """Save all tests (replace collection)."""
        if not USE_SUPABASE:
            with open(TESTS_FILE, "w") as fp:
                json.dump(tests, fp, indent=2)
            return

        try:
            # Delete all existing rows — PostgREST requires at least one filter for DELETE.
            # "id=not.is.null" matches every row that has an id (i.e. all rows).
            StorageBackend._request(
                "DELETE", "tests",
                params={"id": "not.is.null"},
                prefer="return=minimal",
            )
            # Re-insert the updated batch
            if tests:
                StorageBackend._request(
                    "POST", "tests",
                    payload=tests,
                    prefer="return=representation",
                )
        except Exception as e:
            print(f"Error saving tests to Supabase: {e}")

    @staticmethod
    def add_test(test: dict) -> None:
        """Add a single test."""
        if not USE_SUPABASE:
            tests = StorageBackend.get_tests()
            tests.append(test)
            StorageBackend.save_tests(tests)
            return

        try:
            StorageBackend._request("POST", "tests", payload=test, prefer="return=representation")
        except Exception as e:
            print(f"Error adding test to Supabase: {e}")

    @staticmethod
    def update_test(test_id: str, updates: dict) -> bool:
        """Update a test by ID."""
        if not USE_SUPABASE:
            tests = StorageBackend.get_tests()
            for test in tests:
                if test.get("id") == test_id:
                    test.update(updates)
                    StorageBackend.save_tests(tests)
                    return True
            return False

        try:
            data = StorageBackend._request(
                "PATCH",
                "tests",
                params={"id": f"eq.{test_id}"},
                payload=updates,
                prefer="return=representation",
            )
            return bool(data)
        except Exception as e:
            print(f"Error updating test in Supabase: {e}")
            return False

    @staticmethod
    def delete_test(test_id: str) -> bool:
        """Delete a test by ID."""
        if not USE_SUPABASE:
            # JSON fallback: load, filter, save
            tests = []
            if os.path.exists(TESTS_FILE):
                with open(TESTS_FILE) as fp:
                    tests = json.load(fp) or []
            filtered = [t for t in tests if t.get("id") != test_id]
            if len(filtered) == len(tests):
                return False
            with open(TESTS_FILE, "w") as fp:
                json.dump(filtered, fp, indent=2)
            return True

        try:
            data = StorageBackend._request(
                "DELETE",
                "tests",
                params={"id": f"eq.{test_id}"},
                prefer="return=representation",
            )
            return bool(data)
        except Exception as e:
            print(f"Error deleting test from Supabase: {e}")
            return False

    @staticmethod
    def get_attempts() -> list[dict]:
        """Load all attempts."""
        if not USE_SUPABASE:
            if os.path.exists(ATTEMPTS_FILE):
                with open(ATTEMPTS_FILE) as fp:
                    return json.load(fp) or []
            return []

        try:
            data = StorageBackend._request("GET", "attempts", params={"select": "*"})
            return data or []
        except Exception as e:
            print(f"Error loading attempts from Supabase: {e}")
            return []

    @staticmethod
    def _normalize_attempt(attempt: dict) -> dict:
        """Fill in fields required by the Supabase attempts table."""
        normalized = dict(attempt)
        answers = normalized.get("answers")
        if not isinstance(answers, list):
            answers = []
        normalized["answers"] = answers
        total_questions = normalized.get("total_questions")
        if total_questions is None:
            total_questions = len(answers)
        normalized["total_questions"] = int(total_questions or 0)
        normalized["test_version"] = int(normalized.get("test_version", 1) or 1)
        normalized["total_marks"] = normalized.get("total_marks", normalized["total_questions"])
        student = normalized.get("student") or {}
        if not isinstance(student, dict):
            student = {}
        normalized["student"] = student
        # Ensure required string fields are present
        for field in ("attempt_id", "teacher_username", "test_id", "test_name"):
            if not normalized.get(field):
                raise ValueError(f"Missing required attempt field: {field}")
        return normalized

    @staticmethod
    def save_attempt(attempt: dict) -> None:
        """Add/save an attempt."""
        if not USE_SUPABASE:
            attempts = StorageBackend.get_attempts()
            attempts.append(attempt)
            with open(ATTEMPTS_FILE, "w") as fp:
                json.dump(attempts, fp, indent=2)
            return

        try:
            StorageBackend._request(
                "POST",
                "attempts",
                payload=StorageBackend._normalize_attempt(attempt),
                prefer="return=representation",
            )
        except Exception as e:
            print(f"Error saving attempt to Supabase: {e}")
            raise  # Re-raise so caller knows the save failed

    @staticmethod
    def delete_attempt(attempt_id: str) -> bool:
        """Delete an attempt by ID."""
        if not USE_SUPABASE:
            attempts = StorageBackend.get_attempts()
            filtered = [a for a in attempts if a.get("attempt_id") != attempt_id]
            if len(filtered) < len(attempts):
                with open(ATTEMPTS_FILE, "w") as fp:
                    json.dump(filtered, fp, indent=2)
                return True
            return False

        try:
            data = StorageBackend._request(
                "DELETE",
                "attempts",
                params={"attempt_id": f"eq.{attempt_id}"},
                prefer="return=representation",
            )
            return bool(data)
        except Exception as e:
            print(f"Error deleting attempt from Supabase: {e}")
            return False

    @staticmethod
    def delete_attempts_by_test(test_id: str) -> int:
        """Delete all attempts for a test. Returns count deleted."""
        if not USE_SUPABASE:
            attempts = StorageBackend.get_attempts()
            filtered = [a for a in attempts if a.get("test_id") != test_id]
            removed_count = len(attempts) - len(filtered)
            if removed_count > 0:
                with open(ATTEMPTS_FILE, "w") as fp:
                    json.dump(filtered, fp, indent=2)
            return removed_count

        try:
            data = StorageBackend._request(
                "DELETE",
                "attempts",
                params={"test_id": f"eq.{test_id}"},
                prefer="return=representation",
            )
            return len(data) if data else 0
        except Exception as e:
            print(f"Error deleting attempts by test from Supabase: {e}")
            return 0

    @staticmethod
    def get_parent_chat_id(parent_username: str, teacher_username: str) -> int | None:
        """Get parent chat ID by username and teacher."""
        if not USE_SUPABASE:
            if os.path.exists(PARENTS_FILE):
                with open(PARENTS_FILE) as fp:
                    data = json.load(fp)
                    if isinstance(data, dict):
                        teacher_data = data.get(teacher_username.lower(), {})
                        if isinstance(teacher_data, dict):
                            return teacher_data.get(parent_username.lower())
            return None

        try:
            data = StorageBackend._request(
                "GET",
                "parents",
                params={
                    "select": "chat_id",
                    "teacher_username": f"eq.{teacher_username.lower()}",
                    "username": f"eq.{parent_username.lower()}",
                },
            )
            if data:
                return int(data[0]["chat_id"])
            return None
        except Exception as e:
            print(f"Error getting parent chat ID from Supabase: {e}")
            return None

    @staticmethod
    def register_parent(parent_username: str, chat_id: int, teacher_username: str) -> None:
        """Register or update parent mapping."""
        if not USE_SUPABASE:
            data = {}
            if os.path.exists(PARENTS_FILE):
                with open(PARENTS_FILE) as fp:
                    data = json.load(fp)
            data.setdefault(teacher_username.lower(), {})
            data[teacher_username.lower()][parent_username.lower()] = chat_id
            with open(PARENTS_FILE, "w") as fp:
                json.dump(data, fp, indent=2)
            return

        try:
            StorageBackend._request(
                "POST",
                "parents",
                payload={
                    "teacher_username": teacher_username.lower(),
                    "username": parent_username.lower(),
                    "chat_id": chat_id,
                },
                prefer="resolution=merge-duplicates,return=representation",
                on_conflict="teacher_username,username",
            )
        except Exception as e:
            print(f"Error registering parent in Supabase: {e}")