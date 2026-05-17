"""
SQL setup script for Supabase tables.
Run this in the Supabase SQL editor to create the required tables.

This creates:
1. tests table - stores quiz test definitions
2. attempts table - stores student quiz attempts
3. parents table - stores parent phone number mappings
"""

-- Drop existing tables if needed (CAUTION: this deletes data!)
-- DROP TABLE IF EXISTS attempts CASCADE;
-- DROP TABLE IF EXISTS tests CASCADE;
-- DROP TABLE IF EXISTS parents CASCADE;

-- Create tests table
CREATE TABLE IF NOT EXISTS tests (
    id TEXT PRIMARY KEY,
    teacher_username TEXT NOT NULL,
    name TEXT NOT NULL,
    timer_seconds INTEGER NOT NULL DEFAULT 30,
    random_count INTEGER NOT NULL DEFAULT 0,
    one_time BOOLEAN NOT NULL DEFAULT FALSE,
    mark_correct INTEGER NOT NULL DEFAULT 1,
    mark_incorrect INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    version INTEGER NOT NULL DEFAULT 1,
    questions JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tests_teacher ON tests(teacher_username);
CREATE INDEX IF NOT EXISTS idx_tests_active ON tests(is_active);

-- Create attempts table
CREATE TABLE IF NOT EXISTS attempts (
    attempt_id TEXT PRIMARY KEY,
    teacher_username TEXT NOT NULL,
    test_id TEXT NOT NULL,
    test_name TEXT NOT NULL,
    test_version INTEGER NOT NULL,
    student JSONB NOT NULL,  -- {name, phone, roll, parent_username}
    score NUMERIC NOT NULL,
    total_questions INTEGER NOT NULL,
    total_marks NUMERIC NOT NULL,
    answers JSONB NOT NULL,  -- [{question, user_answer, correct_answer, is_correct}, ...]
    submitted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_attempts_teacher ON attempts(teacher_username);
CREATE INDEX IF NOT EXISTS idx_attempts_test ON attempts(test_id);
CREATE INDEX IF NOT EXISTS idx_attempts_roll ON attempts((student->>'roll'));

-- Create parents table (for parent phone number mappings)
CREATE TABLE IF NOT EXISTS parents (
    username TEXT PRIMARY KEY,  -- parent @username, unique identifier
    chat_id BIGINT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Optional: Enable RLS (Row Level Security) for multi-tenancy
-- Uncomment if you want to add row-level security policies

-- ALTER TABLE tests ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE attempts ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE parents ENABLE ROW LEVEL SECURITY;

-- CREATE POLICY "Users can view their own teacher's tests"
--   ON tests FOR SELECT
--   USING (teacher_username = current_user_id());

-- CREATE POLICY "Users can view their own teacher's attempts"
--   ON attempts FOR SELECT
--   USING (teacher_username = current_user_id());

-- CREATE POLICY "Users can view their own teacher's parents"
--   ON parents FOR SELECT
--   USING (teacher_username = current_user_id());
