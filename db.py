import sqlite3
import threading
from datetime import datetime

DB_NAME = "chatbot_memory.db"


# =============================
# SETUP
# =============================

def setup_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT,
        content TEXT,
        timestamp TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_profile(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trait TEXT,
        value TEXT,
        confidence REAL DEFAULT 0.5,
        timestamp TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    conn.commit()
    conn.close()


# =============================
# SETTINGS
# =============================

def save_setting(key, value):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT OR REPLACE INTO settings (key, value)
    VALUES (?, ?)
    """, (key, value))
    conn.commit()
    conn.close()


def load_setting(key, default=None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0]
    return default


# =============================
# MESSAGES
# =============================

def save_message(role, content, on_embedding=None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT INTO messages(role, content, timestamp) VALUES(?,?,?)",
        (role, content, timestamp)
    )

    message_id = cursor.lastrowid
    conn.commit()
    conn.close()

    if on_embedding and _should_store_memory(content):
        threading.Thread(
            target=on_embedding,
            args=(content, message_id)
        ).start()


def load_recent_messages(limit=20):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
    SELECT role, content
    FROM messages
    ORDER BY id DESC
    LIMIT ?
    """, (limit,))

    rows = cursor.fetchall()
    rows.reverse()
    conn.close()

    return [{"role": role, "content": content} for role, content in rows]


# =============================
# USER PROFILE
# =============================

def save_profile_facts(facts_text):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for line in facts_text.splitlines():
        if ":" not in line:
            continue
        parts = line.split(":", 1)
        if len(parts) != 2:
            continue
        trait = parts[0].strip().lower()
        value = parts[1].strip()
        if not trait or not value:
            continue

        cursor.execute("""
        SELECT id FROM user_profile WHERE trait=? AND value=?
        """, (trait, value))

        if cursor.fetchone():
            cursor.execute("""
            UPDATE user_profile
            SET confidence = MIN(confidence + 0.1, 1.0), timestamp=?
            WHERE trait=? AND value=?
            """, (timestamp, trait, value))
        else:
            cursor.execute("""
            INSERT INTO user_profile (trait, value, confidence, timestamp)
            VALUES (?, ?, ?, ?)
            """, (trait, value, 0.5, timestamp))

    conn.commit()
    conn.close()


def get_user_profile():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
    SELECT trait, value FROM user_profile
    ORDER BY confidence DESC, timestamp DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return None

    return "".join([f"- {trait}: {value}\n" for trait, value in rows])


# =============================
# PRIVATE HELPER
# =============================

def _should_store_memory(text):
    text = text.lower().strip()
    if len(text.split()) < 4:
        return False
    trivial = ["hello", "hi", "ok", "thanks", "fine", "good"]
    if text in trivial:
        return False
    return True
