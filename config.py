"""
Configuration constants for the Telegram Quiz Bot.
"""

# ──────────────────────────────────────────────
# Bot Token — replace with your own from @BotFather
# ──────────────────────────────────────────────
BOT_TOKEN = "7607288915:AAGa3tkdqkqo83cip-uvaYiveAFaLvFrbQc"

# ──────────────────────────────────────────────
# ConversationHandler state constants
# ──────────────────────────────────────────────
NAME = 0
PHONE = 1
ROLL = 2
PARENT = 3
QUIZ = 4

# ──────────────────────────────────────────────
# Quiz settings
# ──────────────────────────────────────────────
QUESTIONS_FILE = "questions.json"
RESULTS_FILE = "results.json"
TIMER_DURATION = 30  # seconds per question (optional feature)
