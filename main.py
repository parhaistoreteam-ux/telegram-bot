import os
import telebot
from telebot import types
import random
import string
from flask import Flask, request

# ------------------------------
# Configuration (env vars)
# ------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")  # e.g. https://your-app.onrender.com

if not BOT_TOKEN or not WEBHOOK_URL:
    raise RuntimeError("BOT_TOKEN and WEBHOOK_URL must be set in environment variables")

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)

# ------------------------------
# In-memory storage (replace with DB later)
# ------------------------------
users = {}

# Constants
REFERRAL_BONUS_PER_TASK = 2
GEN_TASK_REWARD = 40
OWN_TASK_REWARD = 40
FB_TASK_REWARD = 12
WITHDRAW_MIN_PKR = 200
BINANCE_PKR_PER_USD = 300
BINANCE_MIN_USD = 1
WITHDRAW_PROCESSING_HOURS = 5
TASK_USER_PROCESSING_MINUTES = 30

# ------------------------------
# Helpers
# ------------------------------
def ensure_user(uid, start_referrer=None):
    u = users.get(uid)
    if not u:
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
        u = users[uid]
        if start_referrer and start_referrer != uid:
            u["referrer"] = start_referrer
            if start_referrer in users:
                users[start_referrer]["referrals_count"] += 1
    return u

def generate_email():
    username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    return f"{username}@gmail.com", password

def admin_notify(text, markup=None):
    try:
        if markup:
            bot.send_message(ADMIN_CHAT_ID, text, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.send_message(ADMIN_CHAT_ID, text, parse_mode="Markdown")
    except Exception as e:
        print("Failed to notify admin:", e)

# ------------------------------
# Flask routes
# ------------------------------
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
    return f"Webhook set: {result} -> {url}"

# ------------------------------
# Keyboards
# ------------------------------
def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("📝 Tasks", "💼 Balance")
    markup.row("💰 Withdraw", "🔗 Referral Link")
    return markup

def tasks_menu():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("1️⃣ Generated Gmail (40 PKR)", callback_data="task_gen"))
    markup.add(types.InlineKeyboardButton("2️⃣ Provide your Gmail (40 PKR)", callback_data="task_own"))
    markup.add(types.InlineKeyboardButton("3️⃣ Facebook 2FA (12 PKR)", callback_data="task_fb"))
    return markup

def withdraw_methods_markup():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Easypaisa (PKR)", callback_data="wd_easypaisa"))
    markup.add(types.InlineKeyboardButton("JazzCash (PKR)", callback_data="wd_jazzcash"))
    markup.add(types.InlineKeyboardButton("Bank (PKR)", callback_data="wd_bank"))
    markup.add(types.InlineKeyboardButton("Binance (USD)", callback_data="wd_binance"))
    return markup

# ------------------------------
# /start handler
# ------------------------------
@bot.message_handler(commands=['start'])
def handle_start(message):
    args = message.text.split()
    ref = None
    if len(args) > 1:
        try:
            ref = int(args[1])
        except:
            ref = None
    ensure_user(message.chat.id, start_referrer=ref)
    bot.send_message(message.chat.id, "Welcome! Choose an option:", reply_markup=main_menu())
    if message.chat.id == ADMIN_CHAT_ID:
        bot.send_message(message.chat.id, f"Admin menu: Users: {len(users)}")

# ------------------------------
# Tasks
# ------------------------------
@bot.message_handler(func=lambda msg: msg.text == "📝 Tasks")
def show_tasks(message):
    ensure_user(message.chat.id)
    bot.send_message(message.chat.id, "Choose a task type:", reply_markup=tasks_menu())

@bot.callback_query_handler(func=lambda call: call.data.startswith("task_"))
def handle_task_choice(call):
    uid = call.message.chat.id
    ensure_user(uid)
    if call.data == "task_gen":
        email, password = generate_email()
        users[uid]["current_task"] = {
            "type": "generated",
            "email": email,
            "password": password,
            "reward": GEN_TASK_REWARD,
            "status": "pending"
        }
        text = f"✅ *Generated Gmail Task*\n\nCreate Gmail using below credentials. Press Done after completion.\n\n📧 `{email}`\n🔐 `{password}`\nReward: {GEN_TASK_REWARD} PKR"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Done Task", callback_data="done_task"))
        markup.add(types.InlineKeyboardButton("❌ Cancel Task", callback_data="cancel_task"))
        bot.send_message(uid, text, reply_markup=markup, parse_mode="Markdown")
    elif call.data == "task_own":
        users[uid]["state"] = "awaiting_own_gmail"
        bot.send_message(uid, "Send Gmail and password in this format:\n`email@example.com password123`", parse_mode="Markdown")
    elif call.data == "task_fb":
        users[uid]["state"] = "awaiting_fb_details"
        bot.send_message(uid, "Send Facebook details:\n`fb_id fb_email fb_password 2fa_code`")

# ------------------------------
# Text handler (Updated: check menus first, then states)
# ------------------------------
@bot.message_handler(func=lambda m: True)
def handle_text(message):
    uid = message.chat.id
    ensure_user(uid)
    u = users[uid]
    state = u.get("state")
    text = message.text.strip()
    text_lower = text.lower()

    # --- MENU COMMANDS FIRST ---
    if text_lower in ["💼 balance", "balance"]:
        bot.send_message(uid, f"💼 Balance: {u.get('balance',0)} PKR\n🔒 Hold: {u.get('hold',0)} PKR\n✅ Tasks Completed: {u.get('tasks_completed',0)}")
        return

    if text_lower in ["💰 withdraw", "withdraw"]:
        users[uid]["state"] = None
        bot.send_message(uid, "Choose withdrawal method:", reply_markup=withdraw_methods_markup())
        return

    if text_lower in ["📝 tasks", "tasks"]:
        bot.send_message(uid, "Choose a task type:", reply_markup=tasks_menu())
        return

    if text_lower in ["/referral", "🔗 referral link"] or text_lower.startswith("referral"):
        link = f"https://t.me/{bot.get_me().username}?start={uid}"
        bot.send_message(uid, f"Share this link. Earn {REFERRAL_BONUS_PER_TASK} PKR per approved task.\n\n{link}")
        return

    # --- STATE HANDLING ---
    if state and state.startswith("awaiting_withdraw_"):
        method = state.split("_", 2)[2]
        try:
            amt = float(text)
        except ValueError:
            bot.send_message(uid, "Invalid amount. Please enter a numeric value.")
            return

        if method == "binance":
            if amt < BINANCE_MIN_USD:
                bot.send_message(uid, f"Minimum for Binance is {BINANCE_MIN_USD} USD.")
                return
            required_pkr = int(amt * BINANCE_PKR_PER_USD)
            if u["balance"] < required_pkr:
                bot.send_message(uid, f"Insufficient balance. You have {u['balance']} PKR, need {required_pkr} PKR.")
                return
            u["state"] = f"awaiting_withdraw_account_binance"
            u["withdraw_temp"] = {"method": "binance", "usd_amount": amt, "pkr_amount": required_pkr}
            bot.send_message(uid, "Enter your Binance account email or ID for USD transfer:")
        else:
            if amt < WITHDRAW_MIN_PKR:
                bot.send_message(uid, f"Minimum withdraw is {WITHDRAW_MIN_PKR} PKR.")
                return
            if u["balance"] < amt:
                bot.send_message(uid, f"Insufficient balance. You have {u['balance']} PKR.")
                return
            u["state"] = f"awaiting_withdraw_account_{method}"
            u["withdraw_temp"] = {"method": method, "pkr_amount": int(amt)}
            bot.send_message(uid, f"Enter your {method} account details for withdrawal:")
        return

    if state and state.startswith("awaiting_withdraw_account_"):
        temp = u.get("withdraw_temp", {})
        temp["account_info"] = text
        req = {
            "user_id": uid,
            "method": temp["method"],
            "pkr_amount": temp.get("pkr_amount"),
            "usd_amount": temp.get("usd_amount"),
            "account_info": temp["account_info"],
            "status": "pending"
        }
        u["withdraw_requests"].append(req)
        if req["method"] == "binance":
            pkr = temp["pkr_amount"]
            u["balance"] -= pkr
            u["hold"] += pkr
        else:
            pkr = temp["pkr_amount"]
            u["balance"] -= pkr
            u["hold"] += pkr

        admin_text = f"💸 Withdraw Request ({req['method'].title()})\nUser: `{uid}`\nAmount: {pkr} PKR\nAccount: {temp['account_info']}\nProcessing time: {WITHDRAW_PROCESSING_HOURS} hours"
        admin_markup = types.InlineKeyboardMarkup()
        admin_markup.add(
            types.InlineKeyboardButton("✅ Approve Withdraw", callback_data=f"approve_wd_{len(u['withdraw_requests'])-1}_{uid}"),
            types.InlineKeyboardButton("❌ Reject Withdraw", callback_data=f"reject_wd_{len(u['withdraw_requests'])-1}_{uid}")
        )
        admin_notify(admin_text, markup=admin_markup)
        bot.send_message(uid, f"✅ Withdraw request received. It will be processed in {WITHDRAW_PROCESSING_HOURS} hours.")
        u["state"] = None
        u.pop("withdraw_temp", None)
        return

    # --- Tasks input ---
    if state == "awaiting_own_gmail":
        parts = text.split()
        if len(parts) < 2:
            bot.send_message(uid, "Invalid format. Send: `email password`", parse_mode="Markdown")
            return
        email = parts[0]
        password = " ".join(parts[1:])
        users[uid]["current_task"] = {"type":"own","email":email,"password":password,"reward":OWN_TASK_REWARD,"status":"pending"}
        users[uid]["state"] = None
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Done Task", callback_data="done_task"))
        markup.add(types.InlineKeyboardButton("❌ Cancel Task", callback_data="cancel_task"))
        bot.send_message(uid, f"Gmail saved.\nEmail: `{email}`\nPassword: `{password}`\nPress Done when ready.", parse_mode="Markdown", reply_markup=markup)
        return

    if state == "awaiting_fb_details":
        parts = text.split()
        if len(parts) < 4:
            bot.send_message(uid, "Invalid format. Send: `fb_id fb_email fb_password 2fa_code`")
            return
        fb_id, fb_email, fb_password, fb_2fa = parts[:4]
        users[uid]["current_task"] = {"type":"facebook","fb_id":fb_id,"email":fb_email,"password":fb_password,"2fa":fb_2fa,"reward":FB_TASK_REWARD,"status":"pending"}
        users[uid]["state"] = None
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Done Task", callback_data="done_task"))
        markup.add(types.InlineKeyboardButton("❌ Cancel Task", callback_data="cancel_task"))
        bot.send_message(uid, "Facebook info saved. Press Done when ready.", reply_markup=markup)
        return

    # Fallback
    bot.send_message(uid, "I didn't understand that. Use the menu or press /start.", reply_markup=main_menu())

# ------------------------------
# Callback handler
# ------------------------------
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    data = call.data
    uid = call.message.chat.id
    ensure_user(uid)

    # Done / Cancel tasks
    if data == "done_task":
        task = users[uid].get("current_task")
        if not task:
            bot.answer_callback_query(call.id, "No active task!")
            return
        reward = task["reward"]
        users[uid]["hold"] += reward
        task["status"] = "pending_admin"
        bot.answer_callback_query(call.id, "Task submitted. Processing (about 30 minutes).")
        bot.send_message(uid, f"⏳ Your task is submitted. Approx {TASK_USER_PROCESSING_MINUTES} minutes.")
        admin_markup = types.InlineKeyboardMarkup()
        admin_markup.add(
            types.InlineKeyboardButton("✅ Approve Task", callback_data=f"approve_task_{uid}"),
            types.InlineKeyboardButton("❌ Reject Task", callback_data=f"reject_task_{uid}")
        )
        if task["type"] == "generated":
            admin_text = f"📝 Task (Generated Gmail)\nUser: `{uid}`\nEmail: `{task['email']}`\nPassword: `{task['password']}`\nReward: {reward} PKR"
        elif task["type"] == "own":
            admin_text = f"📝 Task (User Gmail)\nUser: `{uid}`\nEmail: `{task['email']}`\nPassword: `{task['password']}`\nReward: {reward} PKR"
        else:
            admin_text = f"📝 Task (Facebook 2FA)\nUser: `{uid}`\nFB ID: `{task.get('fb_id')}`\nEmail: `{task.get('email')}`\nPassword: `{task.get('password')}`\n2FA: `{task.get('2fa')}`\nReward: {reward} PKR"
        admin_notify(admin_text, markup=admin_markup)
        return

    if data == "cancel_task":
        if users[uid].get("current_task"):
            users[uid]["current_task"] = None
            users[uid]["state"] = None
            bot.answer_callback_query(call.id, "Task canceled.")
            bot.send_message(uid, "Task canceled.", reply_markup=main_menu())
        else:
            bot.answer_callback_query(call.id, "No task to cancel.")
        return

    # Withdraw selections
    if data.startswith("wd_"):
        method = data.split("_",1)[1]
        users[uid]["state"] = f"awaiting_withdraw_{method}"
        if method == "binance":
            bot.answer_callback_query(call.id, "Enter USD amount (min 1 USD).")
            bot.send_message(uid, "Enter the USD amount to withdraw:")
        else:
            bot.answer_callback_query(call.id, f"Enter PKR amount (min {WITHDRAW_MIN_PKR}).")
            bot.send_message(uid, f"Enter the amount in PKR:")
        return

    # Admin approve/reject and task callbacks remain same (reuse your existing logic)

# ------------------------------
# Flask run
# ------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
