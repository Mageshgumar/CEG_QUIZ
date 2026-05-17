"""
Supabase storage adapter for tests, attempts, and parent mappings.
Provides a unified interface for both JSON and Supabase backends.
"""

import json
import os
from datetime import datetime, timezone, timedelta

from config import (
    SUPABASE_URL,
    SUPABASE_KEY,
    USE_SUPABASE,
    TESTS_FILE,
    ATTEMPTS_FILE,
    PARENTS_FILE,
)

if USE_SUPABASE:
    from supabase import create_client, Client as SupabaseClient
    supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    supabase = None

IST_TZ = timezone(timedelta(hours=5, minutes=30))


class StorageBackend:
    """Unified storage interface for tests, attempts, and parents."""

    @staticmethod
    def get_tests() -> list[dict]:
        """Load all tests."""
        if not USE_SUPABASE:
            if os.path.exists(TESTS_FILE):
                with open(TESTS_FILE) as fp:
                    return json.load(fp) or []
            return []

        try:
            result = supabase.table("tests").select("*").execute()
            return result.data or []
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
            # Delete all existing
            supabase.table("tests").delete().neq("id", "").execute()
            # Insert new batch
            if tests:
                supabase.table("tests").insert(tests).execute()
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
            supabase.table("tests").insert(test).execute()
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
            result = supabase.table("tests").update(updates).eq("id", test_id).execute()
            return bool(result.data)
        except Exception as e:
            print(f"Error updating test in Supabase: {e}")
            return False

    @staticmethod
    def delete_test(test_id: str) -> bool:
        """Delete a test by ID."""
        if not USE_SUPABASE:
            tests = StorageBackend.get_tests()
            filtered = [t for t in tests if t.get("id") != test_id]
            if len(filtered) < len(tests):
                StorageBackend.save_tests(filtered)
                return True
            return False

        try:
            result = supabase.table("tests").delete().eq("id", test_id).execute()
            return bool(result.data)
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
            result = supabase.table("attempts").select("*").execute()
            return result.data or []
        except Exception as e:
            print(f"Error loading attempts from Supabase: {e}")
            return []

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
            supabase.table("attempts").insert(attempt).execute()
        except Exception as e:
            print(f"Error saving attempt to Supabase: {e}")

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
            result = supabase.table("attempts").delete().eq("attempt_id", attempt_id).execute()
            return bool(result.data)
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
            result = supabase.table("attempts").delete().eq("test_id", test_id).execute()
            return len(result.data) if result.data else 0
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
            result = (
                supabase.table("parents")
                .select("chat_id")
                .eq("teacher_username", teacher_username.lower())
                .eq("username", parent_username.lower())
                .execute()
            )
            if result.data:
                return int(result.data[0]["chat_id"])
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
            supabase.table("parents").upsert(
                {
                    "teacher_username": teacher_username.lower(),
                    "username": parent_username.lower(),
                    "chat_id": chat_id,
                }
            ).execute()
        except Exception as e:
            print(f"Error registering parent in Supabase: {e}")
