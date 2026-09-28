import os
import sqlite3
from datetime import datetime, timezone
from config import DATABASE_PATH


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def get_connection():
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER,
            receiver_email TEXT NOT NULL,
            receiver_name TEXT,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            folder TEXT NOT NULL DEFAULT 'INBOX',
            is_read INTEGER NOT NULL DEFAULT 0,
            retry_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            processed_at TEXT,
            worker_name TEXT,
            FOREIGN KEY(sender_id) REFERENCES users(id),
            FOREIGN KEY(receiver_id) REFERENCES users(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            filepath TEXT NOT NULL,
            FOREIGN KEY(email_id) REFERENCES emails(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_name TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'OFFLINE',
            processed_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            last_seen TEXT
        )
    """)
    connection.commit()
    connection.close()


def create_user(name, email, password_hash):
    connection = get_connection()
    try:
        cursor = connection.execute(
            "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (name, email.lower(), password_hash, now())
        )
        connection.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        connection.close()


def get_user_by_email(email):
    connection = get_connection()
    row = connection.execute(
        "SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email.lower(),)
    ).fetchone()
    connection.close()
    return row


def get_user_by_id(user_id):
    connection = get_connection()
    row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    connection.close()
    return row


def create_email(sender_id, receiver_id, receiver_email, receiver_name, subject, body):
    connection = get_connection()
    cursor = connection.execute("""
        INSERT INTO emails
        (sender_id, receiver_id, receiver_email, receiver_name, subject, body,
         status, folder, is_read, retry_count, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'PENDING', 'INBOX', 0, 0, ?)
    """, (sender_id, receiver_id, receiver_email.lower(), receiver_name, subject, body, now()))
    connection.commit()
    email_id = cursor.lastrowid
    connection.close()
    return email_id


def add_attachment(email_id, filename, filepath):
    connection = get_connection()
    connection.execute(
        "INSERT INTO attachments (email_id, filename, filepath) VALUES (?, ?, ?)",
        (email_id, filename, filepath)
    )
    connection.commit()
    connection.close()


def get_email(email_id):
    connection = get_connection()
    row = connection.execute("""
        SELECT e.*,
               s.name AS sender_name, s.email AS sender_email,
               COALESCE(r.name, e.receiver_name, e.receiver_email) AS receiver_display_name,
               e.receiver_email AS receiver_email_final
        FROM emails e
        JOIN users s ON s.id = e.sender_id
        LEFT JOIN users r ON r.id = e.receiver_id
        WHERE e.id = ?
    """, (email_id,)).fetchone()
    connection.close()
    return row


def get_attachments(email_id):
    connection = get_connection()
    rows = connection.execute("SELECT * FROM attachments WHERE email_id = ?", (email_id,)).fetchall()
    connection.close()
    return rows


def mark_email_read(email_id, user_id, read_value):
    connection = get_connection()
    connection.execute("UPDATE emails SET is_read = ? WHERE id = ? AND receiver_id = ?",
                       (1 if read_value else 0, email_id, user_id))
    connection.commit()
    connection.close()


def set_folder(email_id, user_id, folder):
    connection = get_connection()
    connection.execute("UPDATE emails SET folder = ? WHERE id = ? AND receiver_id = ?",
                       (folder, email_id, user_id))
    connection.commit()
    connection.close()


def delete_email_permanently(email_id, user_id):
    connection = get_connection()
    connection.execute("DELETE FROM emails WHERE id = ? AND receiver_id = ?", (email_id, user_id))
    connection.commit()
    connection.close()


def get_inbox(user_id):
    connection = get_connection()
    rows = connection.execute("""
        SELECT e.*, s.name AS sender_name, s.email AS sender_email
        FROM emails e
        JOIN users s ON s.id = e.sender_id
        WHERE e.receiver_id = ? AND e.folder = 'INBOX' AND e.status = 'SENT'
        ORDER BY e.id DESC
    """, (user_id,)).fetchall()
    connection.close()
    return rows


def get_folder(user_id, folder):
    connection = get_connection()
    rows = connection.execute("""
        SELECT e.*, s.name AS sender_name, s.email AS sender_email
        FROM emails e
        JOIN users s ON s.id = e.sender_id
        WHERE e.receiver_id = ? AND e.folder = ?
        ORDER BY e.id DESC
    """, (user_id, folder)).fetchall()
    connection.close()
    return rows


def get_sent(user_id):
    connection = get_connection()
    rows = connection.execute("""
        SELECT e.*, COALESCE(e.receiver_name, e.receiver_email) AS receiver_display_name
        FROM emails e
        WHERE e.sender_id = ?
        ORDER BY e.id DESC
    """, (user_id,)).fetchall()
    connection.close()
    return rows


def search_emails(user_id, query):
    like = "%" + query + "%"
    connection = get_connection()
    rows = connection.execute("""
        SELECT e.*, s.name AS sender_name, s.email AS sender_email
        FROM emails e
        JOIN users s ON s.id = e.sender_id
        WHERE e.receiver_id = ? AND e.folder NOT IN ('TRASH') AND e.status = 'SENT'
          AND (s.name LIKE ? OR s.email LIKE ? OR e.subject LIKE ? OR e.body LIKE ?)
        ORDER BY e.id DESC
    """, (user_id, like, like, like, like)).fetchall()
    connection.close()
    return rows


def update_email_processing(email_id, worker_name):
    connection = get_connection()
    connection.execute("UPDATE emails SET status = 'PROCESSING', worker_name = ? WHERE id = ?",
                       (worker_name, email_id))
    connection.commit()
    connection.close()


def get_retry_count(email_id):
    connection = get_connection()
    row = connection.execute("SELECT retry_count FROM emails WHERE id = ?", (email_id,)).fetchone()
    connection.close()
    return row["retry_count"] if row else 0


def mark_email_retry(email_id):
    connection = get_connection()
    connection.execute("UPDATE emails SET retry_count = retry_count + 1, status = 'PENDING' WHERE id = ?", (email_id,))
    connection.commit()
    connection.close()


def mark_email_sent(email_id, folder):
    connection = get_connection()
    connection.execute("UPDATE emails SET status = 'SENT', folder = ?, processed_at = ? WHERE id = ?",
                       (folder, now(), email_id))
    connection.commit()
    connection.close()


def mark_email_failed(email_id):
    connection = get_connection()
    connection.execute("UPDATE emails SET status = 'FAILED', processed_at = ? WHERE id = ?", (now(), email_id))
    connection.commit()
    connection.close()


def register_worker(worker_name):
    connection = get_connection()
    connection.execute("""
        INSERT INTO workers (worker_name, status, last_seen) VALUES (?, 'ONLINE', ?)
        ON CONFLICT(worker_name) DO UPDATE SET status='ONLINE', last_seen=excluded.last_seen
    """, (worker_name, now()))
    connection.commit()
    connection.close()


def heartbeat_worker(worker_name):
    connection = get_connection()
    connection.execute("UPDATE workers SET status='ONLINE', last_seen=? WHERE worker_name=?",
                       (now(), worker_name))
    connection.commit()
    connection.close()


def worker_processed(worker_name):
    connection = get_connection()
    connection.execute("""
        UPDATE workers SET processed_count=processed_count+1, last_seen=?, status='ONLINE'
        WHERE worker_name=?
    """, (now(), worker_name))
    connection.commit()
    connection.close()


def worker_failed(worker_name):
    connection = get_connection()
    connection.execute("""
        UPDATE workers SET failed_count=failed_count+1, last_seen=?, status='ONLINE'
        WHERE worker_name=?
    """, (now(), worker_name))
    connection.commit()
    connection.close()


def get_workers():
    connection = get_connection()
    rows = connection.execute("SELECT * FROM workers ORDER BY id").fetchall()
    connection.close()
    return rows


def get_stats():
    connection = get_connection()
    total_users = connection.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    total_emails = connection.execute("SELECT COUNT(*) c FROM emails").fetchone()["c"]
    pending = connection.execute("SELECT COUNT(*) c FROM emails WHERE status IN ('PENDING','PROCESSING')").fetchone()["c"]
    sent = connection.execute("SELECT COUNT(*) c FROM emails WHERE status='SENT'").fetchone()["c"]
    failed = connection.execute("SELECT COUNT(*) c FROM emails WHERE status='FAILED'").fetchone()["c"]
    spam = connection.execute("SELECT COUNT(*) c FROM emails WHERE folder='SPAM'").fetchone()["c"]
    connection.close()
    return {"users": total_users, "emails": total_emails, "pending": pending, "sent": sent, "failed": failed, "spam": spam}


def get_recent_jobs(limit=15):
    connection = get_connection()
    rows = connection.execute("""
        SELECT e.id, e.status, e.subject, e.created_at, e.worker_name,
               s.email AS sender_email, e.receiver_email AS receiver_email
        FROM emails e JOIN users s ON s.id=e.sender_id
        ORDER BY e.id DESC LIMIT ?
    """, (limit,)).fetchall()
    connection.close()
    return rows
