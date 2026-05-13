"""
Configuration constants for the Telegram Quiz Bot.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────
# Bot Token — set BOT_TOKEN in your environment
# ──────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Shared API (optional). If set, bot reads/writes via dashboard API.
API_BASE_URL = os.environ.get("API_BASE_URL", "")
API_KEY = os.environ.get("API_KEY", "")

# ──────────────────────────────────────────────
# ConversationHandler state constants
# ──────────────────────────────────────────────
NAME = 0
PHONE = 1
ROLL = 2
PARENT = 3
QUIZ = 4
TEST_SELECT = 5

# ──────────────────────────────────────────────
# Quiz settings
# ──────────────────────────────────────────────
QUESTIONS_FILE = "questions.json"
RESULTS_FILE = "results.json"
PARENTS_FILE = "parents.json"
TESTS_FILE = "tests.json"
ATTEMPTS_FILE = "attempts.json"
TIMER_DURATION = 30  # seconds per question (optional feature)

# Teacher dashboard login
TEACHER_USERNAME = "teacher"
TEACHER_PASSWORD = "teacher123"
