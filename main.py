import os
import telebot
from telebot import types
import random
import string
from flask import Flask, request

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))

WEBHOOK_URL = os.environ.get("WEBHOOK_URL")  # example: https://your-app.onrender.com/webhook

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)

users = {}

def generate_email():
    username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    return f"{username}@gmail.com", password


# ==========================================
# HOME ROUTE
# ==========================================
@app.route('/')
def home():
    return "Bot is running!", 200


# ==========================================
# WEBHOOK RECEIVER
# ==========================================
@app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200


# ==========================================
# SET WEBHOOK MANUALLY
# ==========================================
@app.route('/setwebhook')
def set_webhook():
    result = bot.set_webhook(url=f"{WEBHOOK_URL}/webhook/{BOT_TOKEN}")
    return f"Webhook set: {result}"


# ==========================================
# BOT HANDLERS
# ==========================================
@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    if chat_id not in users:
        users[chat_id] = {"balance": 0, "hold": 0, "tasks_completed": 0}

    menu = types.ReplyKeyboardMarkup(resize_keyboard=True)
    menu.row("📝 Task", "💼 Balance")
    menu.row("💰 Withdraw", "🔗 Referral Link")

    bot.send_message(chat_id, "Welcome! Choose an option:", reply_markup=menu)


@bot.message_handler(func=lambda msg: msg.text == "📝 Task")
def task(message):
    chat_id = message.chat.id

    if chat_id not in users:
        users[chat_id] = {"balance": 0, "hold": 0, "tasks_completed": 0}

    email, password = generate_email()

    users[chat_id]["current_task"] = {
        "email": email,
        "password": password,
        "reward": 40
    }

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Done Task", callback_data="done_task"))
    markup.add(types.InlineKeyboardButton("❌ Cancel Task", callback_data="cancel_task"))

    bot.send_message(
        chat_id,
        f"Task Gmail: {email}\nPassword: {password}",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    chat_id = call.message.chat.id

    if call.data == "done_task":
        task = users[chat_id].get("current_task")
        if task:
            admin_markup = types.InlineKeyboardMarkup()
            admin_markup.add(
                types.InlineKeyboardButton("Approve", callback_data=f"approve_{chat_id}"),
                types.InlineKeyboardButton("Reject", callback_data=f"reject_{chat_id}")
            )

            bot.send_message(
                ADMIN_CHAT_ID,
                f"User {chat_id} submitted task:\nEmail: {task['email']}\nPassword: {task['password']}",
                reply_markup=admin_markup
            )

    elif call.data.startswith("approve_"):
        uid = int(call.data.split("_")[1])
        reward = users[uid]["current_task"]["reward"]
        users[uid]["balance"] += reward
        users[uid].pop("current_task", None)
        bot.send_message(uid, f"Approved. +{reward} PKR")

    elif call.data.startswith("reject_"):
        uid = int(call.data.split("_")[1])
        users[uid].pop("current_task", None)
        bot.send_message(uid, "Rejected.")

    elif call.data == "cancel_task":
        users[chat_id].pop("current_task", None)
        bot.send_message(chat_id, "Task canceled.")


@bot.message_handler(func=lambda msg: msg.text == "💼 Balance")
def balance(message):
    u = users.get(message.chat.id, {})
    bot.send_message(message.chat.id, str(u))


# ==========================================
# NO POLLING — Render uses Gunicorn
# ==========================================
if __name__ == "__main__":
    pass
