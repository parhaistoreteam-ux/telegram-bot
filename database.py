import sqlite3
import os

DB_PATH = "data.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0,
            hold INTEGER DEFAULT 0,
            clicks INTEGER DEFAULT 0,
            invited_by INTEGER
        )
    """)
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def create_user(user_id, invited_by=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT OR IGNORE INTO users (user_id, balance, hold, clicks, invited_by) 
        VALUES (?, 0, 0, 0, ?)
    """, (user_id, invited_by))
    conn.commit()
    conn.close()

def update_balance(user_id, balance):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET balance=? WHERE user_id=?", (balance, user_id))
    conn.commit()
    conn.close()

def update_hold(user_id, hold):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET hold=? WHERE user_id=?", (hold, user_id))
    conn.commit()
    conn.close()

def update_clicks(user_id, clicks):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET clicks=? WHERE user_id=?", (clicks, user_id))
    conn.commit()
    conn.close()
