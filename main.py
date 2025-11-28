# ---------------- FIXED VERSION START ----------------

import os
import telebot
from telebot import types
import random
import string
from flask import Flask, request

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

if not BOT_TOKEN or not WEBHOOK_URL:
    raise RuntimeError("BOT_TOKEN and WEBHOOK_URL must be set")

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)

users = {}

REFERRAL_BONUS_PER_TASK = 2
GEN_TASK_REWARD = 40
OWN_TASK_REWARD = 40
FB_TASK_REWARD = 12
WITHDRAW_MIN_PKR = 200
BINANCE_PKR_PER_USD = 300
BINANCE_MIN_USD = 1
TASK_USER_PROCESSING_MINUTES = 30
WITHDRAW_PROCESSING_HOURS = 5


def ensure_user(uid, start_referrer=None):
    if uid not in users:
        users[uid] = {
            "balance": 0,
            "hold": 0,
            "tasks_completed": 0,
            "referrer": None,
            "referrals_count": 0,
            "referral_earned": 0,
            "current_task": None,
            "state": None,
            "withdraw_requests": []
        }
        if start_referrer and start_referrer != uid:
            users[uid]["referrer"] = start_referrer
            if start_referrer in users:
                users[start_referrer]["referrals_count"] += 1
    return users[uid]


def generate_email():
    username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    return f"{username}@gmail.com", password


def admin_notify(text, markup=None):
    try:
        bot.send_message(ADMIN_CHAT_ID, text, reply_markup=markup, parse_mode="Markdown")
    except:
        pass


@app.route('/')
def home():
    return "Bot running!", 200


@app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
def webhook_receiver():
    update = telebot.types.Update.de_json(request.data.decode("utf-8"))
    bot.process_new_updates([update])
    return "OK", 200


@app.route('/setwebhook')
def set_webhook():
    bot.delete_webhook()
    url = f"{WEBHOOK_URL}/webhook/{BOT_TOKEN}"
    bot.set_webhook(url=url)
    return f"Webhook set to {url}"


def main_menu():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.row("📝 Tasks", "💼 Balance")
    m.row("💰 Withdraw", "🔗 Referral Link")
    m.row("❓ Help")
    return m


def tasks_menu():
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("1️⃣ Generated Gmail (40 PKR)", callback_data="task_gen"))
    m.add(types.InlineKeyboardButton("2️⃣ Provide your Gmail (40 PKR)", callback_data="task_own"))
    m.add(types.InlineKeyboardButton("3️⃣ Facebook 2FA (12 PKR)", callback_data="task_fb"))
    m.add(types.InlineKeyboardButton("❓ Help", callback_data="help"))
    return m


def withdraw_methods_markup():
    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("Easypaisa", callback_data="wd_easypaisa"))
    m.add(types.InlineKeyboardButton("JazzCash", callback_data="wd_jazzcash"))
    m.add(types.InlineKeyboardButton("Bank", callback_data="wd_bank"))
    m.add(types.InlineKeyboardButton("Binance (USD)", callback_data="wd_binance"))
    return m


HELP_TEXT = (
    f"📘 HELP MENU\n\n"
    "🧾 TASK TYPES:\n"
    f"• Generated Gmail – {GEN_TASK_REWARD} PKR\n"
    f"• Provide Your Gmail – {OWN_TASK_REWARD} PKR\n"
    f"• Facebook 2FA – {FB_TASK_REWARD} PKR\n"
    f"• Review Time – {TASK_USER_PROCESSING_MINUTES} minutes\n"
    f"• Referral Bonus – {REFERRAL_BONUS_PER_TASK} PKR\n\n"
    "💵 WITHDRAW RULES:\n"
    f"• Minimum PKR – {WITHDRAW_MIN_PKR}\n"
    f"• Binance – {BINANCE_MIN_USD} USD minimum\n"
    f"• Processing – {WITHDRAW_PROCESSING_HOURS} hours\n"
)


@bot.message_handler(commands=['start'])
def start_cmd(msg):
    uid = msg.chat.id
    ref = None
    parts = msg.text.split()

    if len(parts) > 1:
        try:
            ref = int(parts[1])
        except:
            pass

    ensure_user(uid, ref)
    bot.send_message(uid, "Welcome! Choose an option:", reply_markup=main_menu())


@bot.message_handler(commands=['help'])
@bot.message_handler(func=lambda m: m.text == "❓ Help")
def help_cmd(msg):
    bot.send_message(msg.chat.id, HELP_TEXT)


@bot.message_handler(func=lambda m: m.text == "📝 Tasks")
def tasks_cmd(msg):
    bot.send_message(msg.chat.id, "Choose a task:", reply_markup=tasks_menu())


@bot.message_handler(func=lambda m: True)
def text_handler(msg):
    uid = msg.chat.id
    ensure_user(uid)
    u = users[uid]
    text = msg.text.strip().lower()

    # BALANCE
    if "balance" in text:
        bot.send_message(uid, f"Balance: {u['balance']} PKR\nHold: {u['hold']} PKR")
        return

    # WITH
