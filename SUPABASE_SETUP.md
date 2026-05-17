# Supabase Integration Guide

This document describes how to set up and use Supabase PostgreSQL as the persistent storage backend for the CegQuiz application.

## Why Supabase?

Supabase provides a managed PostgreSQL database with:
- **Reliability**: ACID-compliant relational database
- **Scalability**: Handles growth without data loss
- **Multi-tenancy**: Native support for teacher-scoped data isolation
- **Easy Backups**: Automatic daily backups with one-click restore
- **Simple Migration**: Clear data structure compared to JSON files

## Setup Steps

### 1. Create a Supabase Project

1. Go to [supabase.com](https://supabase.com) and sign up/login
2. Create a new project:
   - Choose a project name (e.g., "cegquiz")
   - Choose a password for `postgres` user (save this!)
   - Select your preferred region
3. Wait for the project to initialize

### 2. Create Database Tables

1. In your Supabase project, go to **SQL Editor**
2. Create a new query
3. Copy the entire contents of `supabase_setup.sql` and paste it into the editor
4. Click **Run** to create all tables
5. Verify tables were created under **Table Editor**

### 3. Get Your Credentials

1. Go to **Settings** → **API**
2. Copy:
   - `Project URL` → This is your `SUPABASE_URL`
   - `anon key` → Optionally for client libraries
   - `service_role key` → Use this as `SUPABASE_KEY` (Python backend)

### 4. Configure Environment Variables

Add to your `.env` file or hosting environment:

```bash
# Supabase Database Credentials
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=your-service-role-key-here
```

**Important**: Use the `service_role key` (not `anon key`) for Python backend operations.

### 5. Install Dependencies

```bash
pip install -r requirements.txt
```

This installs the `supabase` Python package.

### 6. Migrate Existing Data (if upgrading from JSON)

If you have existing data in `tests.json`, `attempts.json`, or `parents.json`:

```bash
python migrate_to_supabase.py
```

This script will:
- Copy all tests to `supabase.tests`
- Copy all attempts to `supabase.attempts`
- Copy all parent mappings to `supabase.parents`
- Display a summary of migrated records

Your JSON files remain as backups.

### 7. Deploy with Supabase Enabled

When deploying (Railway, Vercel, etc.):
1. Set the environment variables (`SUPABASE_URL` and `SUPABASE_KEY`)
2. No code changes needed—the app auto-detects Supabase configuration
3. If Supabase is not configured, the app falls back to JSON files

## How It Works

### Storage Backend Detection

The app checks `config.py` at startup:
- If both `SUPABASE_URL` and `SUPABASE_KEY` are set → Uses Supabase
- Otherwise → Falls back to JSON files

```python
USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_KEY)
```

### API Integration vs. Supabase

The app supports three storage modes (in order of precedence):
1. **API Mode**: If `API_BASE_URL` is set, uses the dashboard API
2. **Supabase Mode**: If `SUPABASE_URL` is set, uses PostgreSQL
3. **JSON Mode**: Default fallback (no external services)

### All Function Signatures Preserved

- `quiz.load_tests()` - Still works the same
- `quiz.add_test()` - Still works the same
- `user_data.save_attempt()` - Still works the same
- Internal storage layer transparently switches to Supabase

No code changes needed in bot.py or dashboard_app.py!

## Table Schemas

### `tests` Table
```
- id: TEXT (PRIMARY KEY)
- teacher_username: TEXT
- name: TEXT
- timer_seconds: INTEGER
- random_count: INTEGER
- one_time: BOOLEAN
- mark_correct: INTEGER
- mark_incorrect: INTEGER
- is_active: BOOLEAN
- version: INTEGER (for session invalidation)
- questions: JSONB (array of question objects)
- created_at: TIMESTAMP
- updated_at: TIMESTAMP
```

### `attempts` Table
```
- attempt_id: TEXT (PRIMARY KEY)
- teacher_username: TEXT
- test_id: TEXT
- test_name: TEXT
- test_version: INTEGER
- student: JSONB (name, phone, roll, parent_username)
- score: NUMERIC
- total_questions: INTEGER
- total_marks: NUMERIC
- answers: JSONB (array of answer objects)
- submitted_at: TIMESTAMP
```

### `parents` Table
```
- teacher_username: TEXT (PRIMARY KEY part 1)
- username: TEXT (PRIMARY KEY part 2, parent @username)
- chat_id: BIGINT
- created_at: TIMESTAMP
```

## Monitoring & Maintenance

### View Data in Supabase Dashboard

1. Go to **Table Editor** in your Supabase project
2. Select any table to view records
3. Search, filter, or download data as needed

### Query Examples

View all active tests:
```sql
SELECT id, name, timer_seconds, teacher_username 
FROM tests 
WHERE is_active = TRUE
ORDER BY updated_at DESC;
```

View attempts for a specific test:
```sql
SELECT attempt_id, (student->>'name') AS student_name, score, total_marks
FROM attempts
WHERE test_id = 'your-test-id'
ORDER BY submitted_at DESC;
```

Count attempts per teacher:
```sql
SELECT teacher_username, COUNT(*) AS attempt_count
FROM attempts
GROUP BY teacher_username
ORDER BY attempt_count DESC;
```

### Database Backups

Supabase automatically creates daily backups. To restore:
1. Go to **Settings** → **Backups**
2. Click **Restore** on any backup
3. Choose your recovery point

## Troubleshooting

### "Invalid Supabase credentials"
- Verify `SUPABASE_URL` format: `https://xxx.supabase.co`
- Ensure `SUPABASE_KEY` is the **service_role key** (not anon key)
- Check environment variables are set correctly

### Tables not found
- Run `supabase_setup.sql` in Supabase SQL Editor
- Verify you're connected to the correct project

### Data not persisting
- Check `config.py` for `USE_SUPABASE = True`
- Verify network connectivity to Supabase
- Check application logs for connection errors

### Slow queries
- Indexes are automatically created on common filter fields
- For custom queries, add indexes in Supabase SQL Editor
- Use the Supabase **Performance** dashboard to analyze slow queries

## Rollback to JSON

To temporarily revert to JSON files:
1. Unset `SUPABASE_URL` and `SUPABASE_KEY` environment variables
2. Restart the application
3. The app will use `tests.json`, `attempts.json`, `parents.json`

Your Supabase data remains untouched for future re-migration.

## Example Deployment: Railway

1. Create a new Railway project
2. Add environment variables:
   ```
   BOT_TOKEN=your_telegram_token
   SUPABASE_URL=https://xxx.supabase.co
   SUPABASE_KEY=your_service_role_key
   ```
3. Deploy (no code changes needed)
4. Monitor logs in Railway dashboard

## Next Steps

- Set up automated daily backups (Railway-native or Supabase dashboard)
- Add Row-Level Security (RLS) policies in `supabase_setup.sql` for multi-tenant isolation
- Monitor database usage in Supabase dashboard
- Set up database alerts for performance issues

---

**Questions?** Check the Supabase docs: https://supabase.com/docs
