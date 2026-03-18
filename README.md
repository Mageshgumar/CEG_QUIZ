# 🤖 Telegram MCQ Quiz Bot

A modular Telegram bot for conducting interactive multiple-choice quizzes with automatic scoring, result breakdowns, and parent notifications.

---

## Features

- **Step-by-step registration** — collects name, phone, roll number, and parent's Telegram username
- **Input validation** — numeric phone check, `@` prefix for usernames
- **Inline keyboard quiz** — one question at a time with A/B/C/D buttons
- **Instant feedback** — shows correct/wrong after each answer
- **Detailed results** — score, percentage, grade, and per-question breakdown
- **Parent notification** — automatically sends results to the parent's Telegram
- **Leaderboard** — `/leaderboard` command for top scores
- **Multi-user support** — handles concurrent users via `ConversationHandler`
- **Persistent results** — saves all results to `results.json`

---

## Setup Instructions

### 1. Create a Bot with BotFather

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a **name** for your bot (e.g. "MCQ Quiz Bot")
4. Choose a **username** (must end in `bot`, e.g. `mcq_quiz_2024_bot`)
5. BotFather will give you an **API token** — copy it

### 2. Configure the Token

Open `config.py` and replace the placeholder:

```python
BOT_TOKEN = "123456789:ABCDEFghijklmn..."
```

### 3. Install Dependencies

```bash
cd telegram_quiz_bot
pip install -r requirements.txt
```

### 4. Run the Bot

```bash
python bot.py
```

You should see: `🤖 Bot is running …`

---

## Project Structure

```
telegram_quiz_bot/
├── bot.py              # Main entry point — ConversationHandler + polling
├── config.py           # Token, state constants, settings
├── questions.json      # 10 sample MCQs (easy/medium/hard)
├── quiz.py             # Question loading, formatting, answer checking
├── user_data.py        # Registration data, validation, persistence
├── notifications.py    # Parent notification with error handling
├── requirements.txt    # Python dependencies
└── README.md           # This file
```

---

## Commands

| Command        | Description                |
|----------------|----------------------------|
| `/start`       | Begin registration + quiz  |
| `/cancel`      | Cancel current session     |
| `/leaderboard` | View top scores            |

---

## How Parent Notification Works

1. During registration the student provides their parent's Telegram username (e.g. `@parent_user`)
2. The parent must **start the bot** at least once so the bot knows their `chat_id`
   - They can send `/start parent` to register as a parent without starting a quiz
3. After the quiz ends the bot automatically sends a formatted result summary to the parent
4. If the parent hasn't started the bot, the student receives a fallback message asking them to share results manually

---

## Customizing Questions

Edit `questions.json`. Each entry follows this schema:

```json
{
  "question": "Your question text?",
  "options": ["Option A", "Option B", "Option C", "Option D"],
  "correct_option": 0,
  "difficulty": "easy"
}
```

- `correct_option` is a **0-based index** into the `options` array
- `difficulty` can be `"easy"`, `"medium"`, or `"hard"`

---

## Technical Details

- Built with **python-telegram-bot v20** (async API)
- Uses `ConversationHandler` with states: `NAME → PHONE → ROLL → PARENT → QUIZ`
- Each user's data is stored in-memory via `UserDataManager` and persisted to `results.json`
- Inline keyboard buttons carry `callback_data` like `answer_0`, `answer_1`, etc.

---

## Optional Enhancements

- **Timer per question** — `config.TIMER_DURATION` is pre-configured; add a `asyncio` timer in `send_question()`
- **Difficulty levels** — `load_questions_by_difficulty()` is already available in `quiz.py`
- **Database** — swap `UserDataManager` JSON persistence for SQLite / PostgreSQL
- **Leaderboard** — already implemented via `/leaderboard`
