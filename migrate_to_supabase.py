"""
Migration script to move data from JSON files to Supabase PostgreSQL.
Run this once before deploying with Supabase enabled.

Usage:
    python migrate_to_supabase.py
"""

import json
import os
from config import (
    TESTS_FILE,
    ATTEMPTS_FILE,
    PARENTS_FILE,
    USE_SUPABASE,
    SUPABASE_URL,
    SUPABASE_KEY,
)

if not USE_SUPABASE:
    print("ERROR: Supabase not configured. Set SUPABASE_URL and SUPABASE_KEY environment variables.")
    exit(1)

from supabase_storage import StorageBackend

print("Starting migration from JSON to Supabase...")


def migrate_tests():
    """Migrate tests.json to Supabase."""
    if not os.path.exists(TESTS_FILE):
        print(f"✓ {TESTS_FILE} not found, skipping tests migration")
        return 0

    with open(TESTS_FILE) as fp:
        tests = json.load(fp)

    if not isinstance(tests, list):
        print(f"✗ {TESTS_FILE} is not a list, skipping")
        return 0

    print(f"Migrating {len(tests)} tests...")
    StorageBackend.save_tests(tests)
    print(f"✓ Migrated {len(tests)} tests")
    return len(tests)


def migrate_attempts():
    """Migrate attempts.json to Supabase."""
    if not os.path.exists(ATTEMPTS_FILE):
        print(f"✓ {ATTEMPTS_FILE} not found, skipping attempts migration")
        return 0

    with open(ATTEMPTS_FILE) as fp:
        attempts = json.load(fp)

    if not isinstance(attempts, list):
        print(f"✗ {ATTEMPTS_FILE} is not a list, skipping")
        return 0

    print(f"Migrating {len(attempts)} attempts...")
    for attempt in attempts:
        StorageBackend.save_attempt(attempt)
    print(f"✓ Migrated {len(attempts)} attempts")
    return len(attempts)


def migrate_parents():
    """Migrate parents.json to Supabase."""
    if not os.path.exists(PARENTS_FILE):
        print(f"✓ {PARENTS_FILE} not found, skipping parents migration")
        return 0

    with open(PARENTS_FILE) as fp:
        data = json.load(fp)

    if not isinstance(data, dict):
        print(f"✗ {PARENTS_FILE} is not a dict, skipping")
        return 0

    count = 0
    for teacher_username, parent_dict in data.items():
        if not isinstance(parent_dict, dict):
            continue
        for parent_username, chat_id in parent_dict.items():
            StorageBackend.register_parent(parent_username, int(chat_id), teacher_username)
            count += 1

    print(f"✓ Migrated {count} parent mappings")
    return count


if __name__ == "__main__":
    try:
        print("\n" + "=" * 60)
        print("DATA MIGRATION: JSON → Supabase")
        print("=" * 60 + "\n")

        tests_count = migrate_tests()
        attempts_count = migrate_attempts()
        parents_count = migrate_parents()

        print("\n" + "=" * 60)
        print("MIGRATION SUMMARY")
        print("=" * 60)
        print(f"Tests:    {tests_count}")
        print(f"Attempts: {attempts_count}")
        print(f"Parents:  {parents_count}")
        print("\nMigration complete! Your data is now in Supabase.")
        print("You can safely keep the JSON files as backups.\n")

    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
