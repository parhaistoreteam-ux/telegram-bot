from database import *
init_db()
import os
import sqlite3
import threading
import telebot
from telebot import types
import random
import string
from flask import Flask, request
from datetime import datetime

# ============================================================
# CONFIGURATION
# ============================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
DB_PATH = os.environ.get("SQLITE_DB", "bot.sqlite")

if not BOT_TOKEN or not WEBHOOK_URL:
    raise RuntimeError("BOT_TOKEN and WEBHOOK_URL must be set in environment variables")

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)

# ============================================================
# CONSTANTS
# ============================================================

REFERRAL_BONUS_PER_TASK = 2
GEN_TASK_REWARD = 40
OWN_TASK_REWARD = 40
FB_TASK_REWARD = 12

WITHDRAW_MIN_PKR = 200
BINANCE_PKR_PER_USD = 300
BINANCE_MIN_USD = 1

TASK_USER_PROCESSING_MINUTES = 30
WITHDRAW_PROCESSING_HOURS = 5

DB_LOCK = threading.Lock()

# ============================================================
# In-memory minimal state for composing tasks and withdraw steps
# This is small transient state only; core data persists to SQLite
# ============================================================
users_state = {}  # {uid: {state: 'awaiting_own_gmail' or withdraw steps, temp: {...}}}

# ============================================================
# DATABASE HELPERS
# ============================================================

def get_db_conn():
    # create a new connection for each thread/call
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with DB_LOCK:
        conn = get_db_conn()
        cur = conn.cursor()

        # users table
        cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            balance INTEGER NOT NULL DEFAULT 0,
            hold INTEGER NOT NULL DEFAULT 0,
            tasks_completed INTEGER NOT NULL DEFAULT 0,
            referrer INTEGER,
            referrals_count INTEGER NOT NULL DEFAULT 0,
            referral_earned INTEGER NOT NULL DEFAULT 0,
            next_task_id INTEGER NOT NULL DEFAULT 1
        )
        ''')

        # tasks table
        cur.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            task_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            email TEXT,
            password TEXT,
            fb_id TEXT,
            twofa TEXT,
            reward INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        ''')

        # withdraws table
        cur.execute('''
        CREATE TABLE IF NOT EXISTS withdraws (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            method TEXT NOT NULL,
            account_name TEXT,
            account_number TEXT,
            pkr_amount INTEGER,
            usd_amount REAL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        ''')

        conn.commit()
        conn.close()


init_db()

# ============================================================
# HELP TEXT
# ============================================================

HELP_TEXT = (
    "📘 HELP MENU\n\n"
    "🧾 TASK SYSTEM\n"
    f"• Generated Gmail – {GEN_TASK_REWARD} PKR\n"
    f"• Your Gmail – {OWN_TASK_REWARD} PKR\n"
    f"• Facebook 2FA – {FB_TASK_REWARD} PKR\n"
    f"• Review Time – Up to {TASK_USER_PROCESSING_MINUTES} minutes\n"
    f"• Referral Bonus – {REFERRAL_BONUS_PER_TASK} PKR/task\n\n"
    "💵 WITHDRAW SYSTEM\n"
    f"• Min Withdraw: {WITHDRAW_MIN_PKR} PKR\n"
    f"• Binance: {BINANCE_MIN_USD} USD (rate: {BINANCE_PKR_PER_USD} PKR)\n"
    f"• Processing Time – {WITHDRAW_PROCESSING_HOURS} hours\n\n"
    "👤 ACCOUNT\n"
    "• Balance\n"
    "• Referral Link\n"
    "• Tasks\n\n"
    "❗ Need help? Contact admin."
)

# ============================================================
# DB OPERATIONS
# ============================================================

def ensure_user_db(uid, start_referrer=None):
    with DB_LOCK:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE id = ?", (uid,))
        row = cur.fetchone()
        if not row:
            cur.execute(
                "INSERT INTO users (id, balance, hold, tasks_completed, referrer, referrals_count, referral_earned, next_task_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (uid, 0, 0, 0, start_referrer if start_referrer and start_referrer != uid else None, 0, 0, 1)
            )
            if start_referrer and start_referrer != uid:
                cur.execute("SELECT * FROM users WHERE id = ?", (start_referrer,))
                r = cur.fetchone()
                if r:
                    cur.execute("UPDATE users SET referrals_count = referrals_count + 1 WHERE id = ?", (start_referrer,))
        conn.commit()
        conn.close()


def get_user_db(uid):
    with DB_LOCK:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE id = ?", (uid,))
        r = cur.fetchone()
        conn.close()
        return r


def update_user_balance(uid, delta_balance=0, delta_hold=0, inc_tasks_completed=0):
    with DB_LOCK:
        conn = get_db_conn()
        cur = conn.cursor()
        if delta_balance != 0:
            cur.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (delta_balance, uid))
        if delta_hold != 0:
            cur.execute("UPDATE users SET hold = hold + ? WHERE id = ?", (delta_hold, uid))
        if inc_tasks_completed:
            cur.execute("UPDATE users SET tasks_completed = tasks_completed + ? WHERE id = ?", (inc_tasks_completed, uid))
        conn.commit()
        conn.close()


def get_and_inc_next_task_id(uid):
    with DB_LOCK:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT next_task_id FROM users WHERE id = ?", (uid,))
        row = cur.fetchone()
        if not row:
            ensure_user_db(uid)
            cur.execute("SELECT next_task_id FROM users WHERE id = ?", (uid,))
            row = cur.fetchone()
        task_id = row['next_task_id']
        cur.execute("UPDATE users SET next_task_id = next_task_id + 1 WHERE id = ?", (uid,))
        conn.commit()
        conn.close()
        return task_id

# ============================================================
# ADMIN NOTIFY
# ============================================================

def admin_notify(text, markup=None):
    try:
        bot.send_message(ADMIN_CHAT_ID, text, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        print("Failed to notify admin:", e)

# ============================================================
# FLASK ROUTES (WEBHOOK)
# ============================================================

@app.route('/')
def home():
    return "Bot is running!", 200


@app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
def webhook_receiver():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200


@app.route('/setwebhook')
def set_webhook():
    bot.delete_webhook()
    url = f"{WEBHOOK_URL}/webhook/{BOT_TOKEN}"
    result = bot.set_webhook(url=url)
    return f"Webhook set: {result} → {url}"

# ============================================================
# KEYBOARDS
# ============================================================

def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("📝 Tasks", "💼 Balance")
    markup.row("💰 Withdraw", "🔗 Referral Link")
    markup.row("❓ Help")
    return markup


def tasks_menu():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("1️⃣ Generated Gmail (40 PKR)", callback_data="task_gen"))
    markup.add(types.InlineKeyboardButton("2️⃣ Provide your Gmail (40 PKR)", callback_data="task_own"))
    markup.add(types.InlineKeyboardButton("3️⃣ Facebook 2FA (12 PKR)", callback_data="task_fb"))
    markup.add(types.InlineKeyboardButton("❓ Help", callback_data="help"))
    return markup


def withdraw_methods_markup():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Easypaisa (PKR)", callback_data="wd_easypaisa"))
    markup.add(types.InlineKeyboardButton("JazzCash (PKR)", callback_data="wd_jazzcash"))
    markup.add(types.InlineKeyboardButton("Bank (PKR)", callback_data="wd_bank"))
    markup.add(types.InlineKeyboardButton("Binance (USD)", callback_data="wd_binance"))
    return markup

# ============================================================
# Small helper: generate a random email + password
# ============================================================
def generate_email():
    local = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    # use example.com to avoid implying we actually create real gmail addresses
    email = f"{local}@example.com"
    password = ''.join(random.choices(string.ascii_letters + string.digits + "!@#$%^&*-_", k=12))
    return email, password

# ============================================================
# BOT COMMANDS & HANDLERS
# ============================================================

@bot.message_handler(commands=['start'])
def handle_start(message):
    args = (message.text or "").split()
    ref = None

    if len(args) > 1:
        try:
            ref = int(args[1])
        except:
            ref = None

    ensure_user_db(message.chat.id, start_referrer=ref)
    bot.send_message(message.chat.id, "Welcome! Choose an option:", reply_markup=main_menu())

    if message.chat.id == ADMIN_CHAT_ID:
        # show counts (example admin notice)
        with DB_LOCK:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) as c FROM users")
            total = cur.fetchone()['c']
            conn.close()
        bot.send_message(message.chat.id, f"Admin Panel Loaded — {total} users")


@bot.message_handler(commands=['help'])
def cmd_help(message):
    bot.send_message(message.chat.id, HELP_TEXT)


@bot.message_handler(commands=['pending'])
def cmd_pending(message):
    # admin-only: show pending tasks and withdraws
    if message.chat.id != ADMIN_CHAT_ID:
        bot.reply_to(message, "You are not authorized to use this command.")
        return

    with DB_LOCK:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM tasks WHERE status = 'pending_admin'")
        tasks = cur.fetchall()
        cur.execute("SELECT * FROM withdraws WHERE status = 'pending'")
        wds = cur.fetchall()
        conn.close()

    msg = (
        f"📌 Pending Tasks: {len(tasks)}\n"
        f"📌 Pending Withdrawals: {len(wds)}\n\n"
    )

    for t in tasks[:30]:
        msg += (
            f"TaskID: `{t['task_id']}`  "
            f"User: `{t['user_id']}`  "
            f"Reward: `{t['reward']}`  "
            f"Type: `{t['type']}`\n"
        )

    msg += "\n"

    for w in wds[:30]:
        msg += (
            f"WDID: `{w['id']}`  "
            f"User: `{w['user_id']}`  "
            f"Amount(PKR): `{w['pkr_amount']}`  "
            f"Method: `{w['method']}`\n"
        )

    bot.send_message(ADMIN_CHAT_ID, msg)

# text / command handlers for help/menu
@bot.message_handler(func=lambda m: m.text == "❓ Help")
def button_help(message):
    bot.send_message(message.chat.id, HELP_TEXT)


@bot.message_handler(func=lambda m: m.text == "📝 Tasks")
def show_tasks(message):
    ensure_user_db(message.chat.id)
    bot.send_message(message.chat.id, "Choose a task type:", reply_markup=tasks_menu())

# ============================================================
# MAIN TEXT HANDLER
# ============================================================

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    uid = message.chat.id
    ensure_user_db(uid)
    user_row = get_user_db(uid)
    text = (message.text or "").strip()

    # BALANCE
    if text.lower() in ["💼 balance", "balance"]:
        user_row = get_user_db(uid)
        msg = f"💼 Balance: {user_row['balance']} PKR\n🔒 Hold: {user_row['hold']} PKR"
        bot.send_message(uid, msg)
        return

    # WITHDRAW
    if text.lower() in ["💰 withdraw", "withdraw"]:
        users_state.pop(uid, None)
        users_state[uid] = {'state': None}
        bot.send_message(uid, "Select withdrawal method:", reply_markup=withdraw_methods_markup())
        return

    # TASKS
    if text.lower() in ["📝 tasks", "tasks"]:
        bot.send_message(uid, "Choose a task:", reply_markup=tasks_menu())
        return

    # REFERRAL
    if text.lower() in ["🔗 referral link", "referral", "/referral"]:
        try:
            username = bot.get_me().username
            link = f"https://t.me/{username}?start={uid}"
        except Exception:
            link = f"t.me/<bot_username>?start={uid}"
        bot.send_message(uid, f"Your Referral Link:\n{link}")
        return

    # HELP
    if text.lower() in ["❓ help", "/help", "help"]:
        bot.send_message(uid, HELP_TEXT)
        return

    # Handle withdraw steps in users_state
    state = users_state.get(uid, {})
    if state and state.get('state') and state['state'].startswith('awaiting_withdraw_'):
        method = state['state'].split('_', 2)[2]
        try:
            amt = float(text)
        except:
            bot.send_message(uid, "❌ Invalid amount. Send a number (e.g. 500).")
            return

        if method == 'binance':
            if amt < BINANCE_MIN_USD:
                bot.send_message(uid, f"Minimum is {BINANCE_MIN_USD} USD")
                return
            required_pkr = int(amt * BINANCE_PKR_PER_USD)
            user_row = get_user_db(uid)
            if not user_row or user_row['balance'] < required_pkr:
                bot.send_message(uid, f"❌ Not enough balance. You need {required_pkr} PKR.")
                return
            state['temp'] = {'method': method, 'usd_amount': amt, 'pkr_amount': required_pkr}
        else:
            if amt < WITHDRAW_MIN_PKR:
                bot.send_message(uid, f"Minimum is {WITHDRAW_MIN_PKR} PKR")
                return
            user_row = get_user_db(uid)
            if not user_row or user_row['balance'] < amt:
                bot.send_message(uid, "❌ Insufficient balance.")
                return
            state['temp'] = {'method': method, 'pkr_amount': int(amt)}

        state['state'] = f"awaiting_account_name_{method}"
        users_state[uid] = state
        bot.send_message(uid, "✔ Send Account Holder Name:")
        return

    if state and state.get('state') and state['state'].startswith('awaiting_account_name_'):
        method = state['state'].split('_', 3)[3]
        if 'temp' not in state:
            bot.send_message(uid, "❌ Error: No withdraw in progress. Start again.")
            users_state.pop(uid, None)
            return
        state['temp']['account_name'] = text
        state['state'] = f"awaiting_account_number_{method}"
        users_state[uid] = state
        bot.send_message(uid, "✔ Now send Account Number:")
        return

    if state and state.get('state') and state['state'].startswith('awaiting_account_number_'):
        method = state['state'].split('_', 3)[3]
        temp = state.get('temp')
        if not temp:
            bot.send_message(uid, "❌ Error: No withdraw temp found. Start again.")
            users_state.pop(uid, None)
            return
        temp['account_number'] = text

        # create withdraw row in DB
        with DB_LOCK:
            conn = get_db_conn()
            cur = conn.cursor()
            now = datetime.utcnow().isoformat()
            cur.execute(
                "INSERT INTO withdraws (user_id, method, account_name, account_number, pkr_amount, usd_amount, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (uid, temp.get('method'), temp.get('account_name'), temp.get('account_number'), temp.get('pkr_amount'), temp.get('usd_amount'), 'pending', now)
            )
            wd_id = cur.lastrowid
            pkr_hold = temp.get('pkr_amount', 0)
            cur.execute("SELECT balance, hold FROM users WHERE id = ?", (uid,))
            ur = cur.fetchone()
            if not ur or ur['balance'] < pkr_hold:
                conn.rollback()
                conn.close()
                bot.send_message(uid, "❌ Unexpected error: insufficient balance.")
                users_state.pop(uid, None)
                return
            cur.execute("UPDATE users SET balance = balance - ?, hold = hold + ? WHERE id = ?", (pkr_hold, pkr_hold, uid))
            conn.commit()
            conn.close()

        # notify admin
        admin_markup = types.InlineKeyboardMarkup()
        admin_markup.add(
            types.InlineKeyboardButton("Approve", callback_data=f"approve_wd_{wd_id}"),
            types.InlineKeyboardButton("Reject", callback_data=f"reject_wd_{wd_id}")
        )

        admin_text = (
            f"💸 *New Withdraw Request*\n"
            f"WDID: `{wd_id}`\n"
            f"User: `{uid}`\n"
            f"Method: *{temp.get('method')}*\n"
            f"Account Name: `{temp.get('account_name')}`\n"
            f"Account Number: `{temp.get('account_number')}`\n"
            f"Amount (PKR): `{temp.get('pkr_amount')}`\n"
            f"Amount (USD): `{temp.get('usd_amount')}`\n"
            f"Processing Time: {WITHDRAW_PROCESSING_HOURS} hours\n"
        )

        admin_notify(admin_text, admin_markup)
        bot.send_message(uid, f"⏳ Your withdraw request is under review. Processing time: {WITHDRAW_PROCESSING_HOURS} hours.")
        users_state.pop(uid, None)
        return

    # TASK INPUTS (own gmail / fb) - storing as draft then submit
    if state and state.get('state') == 'awaiting_own_gmail':
        parts = text.split()
        if len(parts) < 2:
            bot.send_message(uid, "Send: email password")
            return
        task_id = get_and_inc_next_task_id(uid)
        now = datetime.utcnow().isoformat()
        with DB_LOCK:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO tasks (user_id, task_id, type, email, password, reward, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (uid, task_id, 'own', parts[0], ' '.join(parts[1:]), OWN_TASK_REWARD, 'draft', now)
            )
            conn.commit()
            conn.close()

        users_state.pop(uid, None)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Done", callback_data=f"done_task_{uid}_{task_id}"))
        markup.add(types.InlineKeyboardButton("Cancel", callback_data=f"cancel_task_{uid}_{task_id}"))
        bot.send_message(uid, "Credentials saved. Press *Done* when finished.", reply_markup=markup, parse_mode="Markdown")
        return

    if state and state.get('state') == 'awaiting_fb_details':
        parts = text.split()
        if len(parts) < 4:
            bot.send_message(uid, "Send: fb_id fb_email fb_password 2fa")
            return
        task_id = get_and_inc_next_task_id(uid)
        now = datetime.utcnow().isoformat()
        with DB_LOCK:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO tasks (user_id, task_id, type, fb_id, email, password, twofa, reward, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uid, task_id, 'facebook', parts[0], parts[1], parts[2], parts[3], FB_TASK_REWARD, 'draft', now)
            )
            conn.commit()
            conn.close()

        users_state.pop(uid, None)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Done", callback_data=f"done_task_{uid}_{task_id}"))
        markup.add(types.InlineKeyboardButton("Cancel", callback_data=f"cancel_task_{uid}_{task_id}"))
        bot.send_message(uid, "Facebook info saved. Press *Done* when finished.", reply_markup=markup)
        return

    # FALLBACK
    bot.send_message(uid, "Use menu options.", reply_markup=main_menu())

# ============================================================
# CALLBACKS: single handler for all callbacks
# ============================================================

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    data = call.data or ""
    caller = call.from_user.id if call.from_user else (call.message.chat.id if call.message else None)

    # TASK menu (user asking for tasks)
    if data == "task_gen" and caller != ADMIN_CHAT_ID:
        uid = caller
        ensure_user_db(uid)
        email, password = generate_email()
        task_id = get_and_inc_next_task_id(uid)
        created_at = datetime.utcnow().isoformat()
        with DB_LOCK:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO tasks (user_id, task_id, type, email, password, reward, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (uid, task_id, 'generated', email, password, GEN_TASK_REWARD, 'draft', created_at)
            )
            conn.commit()
            conn.close()

        text = (
            "✅ *Generated Gmail Task*\n\n"
            "Use the credentials below to create a Gmail account:\n\n"
            f"📧 `{email}`\n"
            f"🔐 `{password}`\n\n"
            f"Reward: {GEN_TASK_REWARD} PKR\n\n"
            "Press *Done* when you finish to submit this task for review."
        )

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Done Task", callback_data=f"done_task_{uid}_{task_id}"))
        markup.add(types.InlineKeyboardButton("❌ Cancel Task", callback_data=f"cancel_task_{uid}_{task_id}"))
        bot.answer_callback_query(call.id)
        bot.send_message(uid, text, reply_markup=markup, parse_mode="Markdown")
        return

    if data == "task_own" and caller != ADMIN_CHAT_ID:
        uid = caller
        ensure_user_db(uid)
        users_state[uid] = {'state': 'awaiting_own_gmail'}
        bot.answer_callback_query(call.id)
        bot.send_message(uid, "Send:\nemail password", parse_mode="Markdown")
        return

    if data == "task_fb" and caller != ADMIN_CHAT_ID:
        uid = caller
        ensure_user_db(uid)
        users_state[uid] = {'state': 'awaiting_fb_details'}
        bot.answer_callback_query(call.id)
        bot.send_message(uid, "Send: fb_id fb_email fb_password 2fa_code", parse_mode="Markdown")
        return

    if data == "help":
        bot.answer_callback_query(call.id)
        bot.send_message(caller, HELP_TEXT)
        return

    # USER selects withdraw method (callback data: wd_<method>)
    if data.startswith("wd_") and caller is not None and caller != ADMIN_CHAT_ID:
        method = data.split("_", 1)[1]
        users_state[caller] = {'state': f'awaiting_withdraw_{method}'}
        bot.answer_callback_query(call.id)
        if method == 'binance':
            bot.send_message(caller, "Enter amount in USD:")
        else:
            bot.send_message(caller, "Enter amount in PKR:")
        return

    # USER: Done task -> change draft -> pending_admin and notify admin
    if data.startswith("done_task_"):
        parts = data.split("_")
        # format: done_task_<uid>_<task_id>
        try:
            target = int(parts[2])
            task_id = int(parts[3])
        except Exception:
            bot.answer_callback_query(call.id, "Invalid data.")
            return

        with DB_LOCK:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute("SELECT * FROM tasks WHERE user_id = ? AND task_id = ? AND status = 'draft'", (target, task_id))
            t = cur.fetchone()
            if not t:
                conn.close()
                bot.answer_callback_query(call.id, "Task not found or already submitted.")
                return
            cur.execute("UPDATE tasks SET status = 'pending_admin' WHERE id = ?", (t['id'],))
            conn.commit()
            cur.execute("SELECT * FROM tasks WHERE id = ?", (t['id'],))
            t2 = cur.fetchone()
            conn.close()

        bot.answer_callback_query(call.id)
        bot.send_message(target, "⏳ Task submitted. Admin reviewing. You can do other tasks while this is pending.")

        details = (
            "📥 *New Task Submitted*\n"
            f"👤 User: `{target}`\n"
            f"💰 Reward: `{t2['reward']}` PKR\n"
            f"📌 Type: *{t2['type']}*\n"
            f"🔢 TaskID: `{t2['task_id']}`\n\n"
        )
        if t2['type'] in ('generated', 'own'):
            details += f"Email: `{t2['email']}`\nPassword: `{t2['password']}`\n"
        elif t2['type'] == 'facebook':
            details += (
                f"FB ID: `{t2['fb_id']}`\n"
                f"Email: `{t2['email']}`\n"
                f"Password: `{t2['password']}`\n"
                f"2FA: `{t2['twofa']}`\n"
            )

        admin_markup = types.InlineKeyboardMarkup()
        admin_markup.add(
            types.InlineKeyboardButton("Approve", callback_data=f"approve_task_{t2['id']}"),
            types.InlineKeyboardButton("Reject", callback_data=f"reject_task_{t2['id']}")
        )
        admin_notify(details, admin_markup)
        return

    # USER: Cancel draft task
    if data.startswith("cancel_task_"):
        parts = data.split("_")
        try:
            target = int(parts[2])
            task_id = int(parts[3])
        except Exception:
            bot.answer_callback_query(call.id, "Invalid data.")
            return
        with DB_LOCK:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute("SELECT * FROM tasks WHERE user_id = ? AND task_id = ? AND status = 'draft'", (target, task_id))
            t = cur.fetchone()
            if t:
                cur.execute("DELETE FROM tasks WHERE id = ?", (t['id'],))
                conn.commit()
            conn.close()
        bot.answer_callback_query(call.id, "Canceled.")
        bot.send_message(target, "Task canceled.", reply_markup=main_menu())
        return

    # ADMIN: Approve task
    if data.startswith("approve_task_") and caller == ADMIN_CHAT_ID:
        parts = data.split("_")
        try:
            db_task_id = int(parts[2])
        except Exception:
            bot.answer_callback_query(call.id, "Invalid data.")
            return

        with DB_LOCK:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute("SELECT * FROM tasks WHERE id = ?", (db_task_id,))
            t = cur.fetchone()
            if not t:
                conn.close()
                bot.answer_callback_query(call.id, "Task not found.")
                return
            if t['status'] == 'approved':
                conn.close()
                bot.answer_callback_query(call.id, "Already approved.")
                return

            cur.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (t['reward'], t['user_id']))
            cur.execute("UPDATE tasks SET status = 'approved' WHERE id = ?", (db_task_id,))
            cur.execute("UPDATE users SET tasks_completed = tasks_completed + 1 WHERE id = ?", (t['user_id'],))
            cur.execute("SELECT referrer FROM users WHERE id = ?", (t['user_id'],))
            r = cur.fetchone()
            if r and r['referrer']:
                refid = r['referrer']
                cur.execute("UPDATE users SET balance = balance + ?, referral_earned = referral_earned + ? WHERE id = ?", (REFERRAL_BONUS_PER_TASK, REFERRAL_BONUS_PER_TASK, refid))
            conn.commit()
            cur.execute("SELECT balance FROM users WHERE id = ?", (t['user_id'],))
            ur = cur.fetchone()
            conn.close()

        bot.answer_callback_query(call.id)
        bot.send_message(t['user_id'], f"✅ Task approved! +{t['reward']} PKR")
        bot.send_message(ADMIN_CHAT_ID, f"Approved task {t['task_id']} for {t['user_id']}")
        return

    # ADMIN: Reject task
    if data.startswith("reject_task_") and caller == ADMIN_CHAT_ID:
        parts = data.split("_")
        try:
            db_task_id = int(parts[2])
        except Exception:
            bot.answer_callback_query(call.id, "Invalid data.")
            return

        with DB_LOCK:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute("SELECT * FROM tasks WHERE id = ?", (db_task_id,))
            t = cur.fetchone()
            if not t:
                conn.close()
                bot.answer_callback_query(call.id, "Task not found.")
                return
            if t['status'] == 'rejected':
                conn.close()
                bot.answer_callback_query(call.id, "Already rejected.")
                return
            cur.execute("UPDATE tasks SET status = 'rejected' WHERE id = ?", (db_task_id,))
            conn.commit()
            conn.close()

        bot.answer_callback_query(call.id)
        bot.send_message(t['user_id'], f"❌ Task rejected.")
        bot.send_message(ADMIN_CHAT_ID, f"Rejected task {t['task_id']} for {t['user_id']}")
        return

    # ADMIN: Approve withdraw
    if data.startswith("approve_wd_") and caller == ADMIN_CHAT_ID:
        parts = data.split("_")
        try:
            wd_id = int(parts[2])
        except Exception:
            bot.answer_callback_query(call.id, "Invalid data.")
            return
        with DB_LOCK:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute("SELECT * FROM withdraws WHERE id = ?", (wd_id,))
            w = cur.fetchone()
            if not w:
                conn.close()
                bot.answer_callback_query(call.id, "Withdraw not found.")
                return
            if w['status'] == 'approved':
                conn.close()
                bot.answer_callback_query(call.id, "Already approved.")
                return
            cur.execute("UPDATE withdraws SET status = 'approved' WHERE id = ?", (wd_id,))
            p = w['pkr_amount'] if w['pkr_amount'] else 0
            cur.execute("UPDATE users SET hold = hold - ? WHERE id = ?", (p, w['user_id']))
            conn.commit()
            conn.close()
        bot.answer_callback_query(call.id)
        bot.send_message(w['user_id'], f"✅ Withdraw approved: {w['pkr_amount']} PKR")
        bot.send_message(ADMIN_CHAT_ID, f"Approved withdraw {wd_id} for {w['user_id']}")
        return

    # ADMIN: Reject withdraw
    if data.startswith("reject_wd_") and caller == ADMIN_CHAT_ID:
        parts = data.split("_")
        try:
            wd_id = int(parts[2])
        except Exception:
            bot.answer_callback_query(call.id, "Invalid data.")
            return
        with DB_LOCK:
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute("SELECT * FROM withdraws WHERE id = ?", (wd_id,))
            w = cur.fetchone()
            if not w:
                conn.close()
                bot.answer_callback_query(call.id, "Withdraw not found.")
                return
            if w['status'] == 'rejected':
                conn.close()
                bot.answer_callback_query(call.id, "Already rejected.")
                return
            p = w['pkr_amount'] if w['pkr_amount'] else 0
            cur.execute("UPDATE users SET hold = hold - ?, balance = balance + ? WHERE id = ?", (p, p, w['user_id']))
            cur.execute("UPDATE withdraws SET status = 'rejected' WHERE id = ?", (wd_id,))
            conn.commit()
            conn.close()
        bot.answer_callback_query(call.id)
        bot.send_message(w['user_id'], f"❌ Withdraw rejected. {p} PKR refunded.")
        bot.send_message(ADMIN_CHAT_ID, f"Rejected withdraw {wd_id} for {w['user_id']}")
        return

    # default: just acknowledge
    bot.answer_callback_query(call.id)

# ============================================================
# RUN FLASK SERVER
# ============================================================

if __name__ == "__main__":
    print("Starting SQLite-backed bot... Ensure BOT_TOKEN, ADMIN_CHAT_ID, WEBHOOK_URL set.")
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
