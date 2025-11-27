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
# Structure:
# users[user_id] = {
#   balance, hold, tasks_completed, referrer, referrals_count,
#   current_task, state, withdraw_requests:[], referral_code
# }
# ------------------------------
users = {}

# Constants
REFERRAL_BONUS_PER_TASK = 2      # 2 PKR per approved task for referrer
GEN_TASK_REWARD = 40             # 1st task type reward (generated gmail)
OWN_TASK_REWARD = 40             # 2nd task type reward (user-provided)
FB_TASK_REWARD = 12              # 3rd task type reward (facebook 2fa)
WITHDRAW_MIN_PKR = 200
BINANCE_PKR_PER_USD = 300        # 300 PKR = 1 USD
BINANCE_MIN_USD = 1
WITHDRAW_PROCESSING_HOURS = 5
TASK_USER_PROCESSING_MINUTES = 30

# ------------------------------
# Small helpers
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
        # set referrer if provided and not self
        if start_referrer and start_referrer != uid:
            u["referrer"] = start_referrer
            # increment referrer's referrals_count
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
# Flask routes (webhook)
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
# Keyboards and menus
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
# Handlers: start (with optional referral id)
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
    bot.send_message(
        message.chat.id,
        "Welcome! Choose an option:",
        reply_markup=main_menu()
    )
    # if admin, show admin quick info
    if message.chat.id == ADMIN_CHAT_ID:
        bot.send_message(message.chat.id, f"Admin menu: Users: {len(users)}")

# ------------------------------
# Tasks entry
# ------------------------------
@bot.message_handler(func=lambda msg: msg.text == "📝 Tasks")
def show_tasks(message):
    ensure_user(message.chat.id)
    bot.send_message(message.chat.id, "Choose a task type:", reply_markup=tasks_menu())

# When user chooses an inline button for task
@bot.callback_query_handler(func=lambda call: call.data.startswith("task_"))
def handle_task_choice(call):
    uid = call.message.chat.id
    ensure_user(uid)
    if call.data == "task_gen":
        # generate email and store as current task
        email, password = generate_email()
        users[uid]["current_task"] = {
            "type": "generated",
            "email": email,
            "password": password,
            "reward": GEN_TASK_REWARD,
            "status": "pending"
        }
        text = f"✅ *Generated Gmail Task*\n\nPlease create a Gmail using the credentials below on your device. After creating, return here and press *Done Task*.\n\n📧 Gmail: `{email}`\n🔐 Password: `{password}`\n\nReward: {GEN_TASK_REWARD} PKR"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Done Task", callback_data="done_task"))
        markup.add(types.InlineKeyboardButton("❌ Cancel Task", callback_data="cancel_task"))
        bot.send_message(uid, text, reply_markup=markup, parse_mode="Markdown")
    elif call.data == "task_own":
        # prompt user to send their gmail & password
        users[uid]["state"] = "awaiting_own_gmail"
        bot.send_message(uid, "Please send your Gmail and password in the following format (all in one message):\n\n`email@example.com password123`", parse_mode="Markdown")
    elif call.data == "task_fb":
        users[uid]["state"] = "awaiting_fb_details"
        bot.send_message(uid, "Please send your Facebook details in one message in this exact format:\n\n`fb_id fb_email fb_password 2fa_code`\n\nExample:\n`1234567890 me@mail.com mypass 123456`")

# ------------------------------
# Handle text inputs for states (own gmail / fb / withdraw amounts)
# ------------------------------
@bot.message_handler(func=lambda m: True)
def handle_text(message):
    uid = message.chat.id
    ensure_user(uid)
    u = users[uid]
    state = u.get("state")

    # Withdraw amount input
    if state and state.startswith("awaiting_withdraw_"):
        method = state.split("_", 2)[2]  # e.g. awaiting_withdraw_easypaisa
        text = message.text.strip()
        # parse number
        try:
            amt = float(text)
        except:
            bot.send_message(uid, "Invalid amount. Please enter a numeric value.")
            return
        if method == "binance":
            # amt is USD
            if amt < BINANCE_MIN_USD:
                bot.send_message(uid, f"Minimum for Binance is {BINANCE_MIN_USD} USD.")
                return
            required_pkr = int(amt * BINANCE_PKR_PER_USD)
            if u["balance"] < required_pkr:
                bot.send_message(uid, f"Insufficient balance. You need {required_pkr} PKR (which equals {amt} USD) but you have {u['balance']} PKR.")
                return
            # collect account info next
            u["state"] = f"awaiting_withdraw_account_binance"
            u["withdraw_temp"] = {"method": "binance", "usd_amount": amt, "pkr_amount": required_pkr}
            bot.send_message(uid, "Enter your Binance account email or ID where we should send USD:")
            return
        else:
            # PKR method
            if amt < WITHDRAW_MIN_PKR:
                bot.send_message(uid, f"Minimum withdraw for PKR methods is {WITHDRAW_MIN_PKR} PKR.")
                return
            if u["balance"] < amt:
                bot.send_message(uid, f"Insufficient balance. You have {u['balance']} PKR.")
                return
            u["state"] = f"awaiting_withdraw_account_{method}"
            u["withdraw_temp"] = {"method": method, "pkr_amount": int(amt)}
            bot.send_message(uid, f"Enter your {method} account details (number/email) for withdrawal:")
            return

    # Withdraw account input
    if state and state.startswith("awaiting_withdraw_account_"):
        temp = u.get("withdraw_temp", {})
        account_info = message.text.strip()
        temp["account_info"] = account_info
        # create withdraw request
        req = {
            "user_id": uid,
            "method": temp["method"],
            "pkr_amount": temp.get("pkr_amount"),
            "usd_amount": temp.get("usd_amount"),
            "account_info": temp["account_info"],
            "status": "pending"
        }
        u["withdraw_requests"].append(req)
        # put money on hold
        if req["method"] == "binance":
            # deduct PKR equivalent from balance into hold
            pkr = temp["pkr_amount"]
            u["balance"] -= pkr
            u["hold"] += pkr
            admin_text = f"💸 *Withdraw Request (Binance)*\nUser: `{uid}`\nUSD: {req['usd_amount']}\nPKR held: {pkr}\nAccount: {account_info}\nProcessing time: {WITHDRAW_PROCESSING_HOURS} hours"
        else:
            pkr = temp["pkr_amount"]
            u["balance"] -= pkr
            u["hold"] += pkr
            admin_text = f"💸 *Withdraw Request ({temp['method'].title()})*\nUser: `{uid}`\nAmount: {pkr} PKR\nAccount: {account_info}\nProcessing time: {WITHDRAW_PROCESSING_HOURS} hours"
        # notify admin with approve/reject buttons
        admin_markup = types.InlineKeyboardMarkup()
        admin_markup.add(types.InlineKeyboardButton("✅ Approve Withdraw", callback_data=f"approve_wd_{len(u['withdraw_requests'])-1}_{uid}"))
        admin_markup.add(types.InlineKeyboardButton("❌ Reject Withdraw", callback_data=f"reject_wd_{len(u['withdraw_requests'])-1}_{uid}"))
        admin_notify(admin_text, markup=admin_markup)
        bot.send_message(uid, f"✅ Withdraw request received. It will be processed in {WITHDRAW_PROCESSING_HOURS} hours.")
        # cleanup
        u["state"] = None
        u.pop("withdraw_temp", None)
        return

    # Own gmail task (user provides credentials)
    if state == "awaiting_own_gmail":
        text = message.text.strip()
        parts = text.split()
        if len(parts) < 2:
            bot.send_message(uid, "Invalid format. Send: `email password`", parse_mode="Markdown")
            return
        email = parts[0]
        password = " ".join(parts[1:])
        users[uid]["current_task"] = {
            "type": "own",
            "email": email,
            "password": password,
            "reward": OWN_TASK_REWARD,
            "status": "pending"
        }
        users[uid]["state"] = None
        # send Done/Cancel buttons
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Done Task", callback_data="done_task"))
        markup.add(types.InlineKeyboardButton("❌ Cancel Task", callback_data="cancel_task"))
        bot.send_message(uid, f"Your Gmail credentials stored.\nEmail: `{email}`\nPassword: `{password}`\nPress Done when you are ready.", parse_mode="Markdown", reply_markup=markup)
        return

    # FB details
    if state == "awaiting_fb_details":
        text = message.text.strip()
        parts = text.split()
        if len(parts) < 4:
            bot.send_message(uid, "Invalid format. Send: `fb_id fb_email fb_password 2fa_code`")
            return
        fb_id = parts[0]
        fb_email = parts[1]
        fb_password = parts[2]
        fb_2fa = parts[3]
        users[uid]["current_task"] = {
            "type": "facebook",
            "fb_id": fb_id,
            "email": fb_email,
            "password": fb_password,
            "2fa": fb_2fa,
            "reward": FB_TASK_REWARD,
            "status": "pending"
        }
        users[uid]["state"] = None
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Done Task", callback_data="done_task"))
        markup.add(types.InlineKeyboardButton("❌ Cancel Task", callback_data="cancel_task"))
        bot.send_message(uid, f"Facebook info received. Press Done when ready.", reply_markup=markup)
        return

    # Catch-all: main menu message handling
    text_lower = message.text.strip().lower()
    if text_lower == "💼 balance" or text_lower == "balance":
        u = users.get(uid, {})
        bot.send_message(uid, f"💼 Balance: {u.get('balance',0)} PKR\n🔒 Hold: {u.get('hold',0)} PKR\n✅ Tasks Completed: {u.get('tasks_completed',0)}")
        return
    if text_lower == "💰 withdraw" or text_lower == "withdraw":
        # show withdraw methods
        users[uid]["state"] = None
        bot.send_message(uid, "Choose withdrawal method:", reply_markup=withdraw_methods_markup())
        return
    if text_lower.startswith("/referral") or text_lower == "🔗 referral link" or text_lower.startswith("referral"):
        # show referral link
        ensure_user(uid)
        link = f"https://t.me/{bot.get_me().username}?start={uid}"
        bot.send_message(uid, f"Share this link. You get {REFERRAL_BONUS_PER_TASK} PKR for each approved task from your referrals.\n\n{link}")
        return

    # if nothing matched
    bot.send_message(uid, "I didn't understand that. Use the menu or press /start.", reply_markup=main_menu())

# ------------------------------
# Callback handler for done/cancel and admin approve/reject
# ------------------------------
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    data = call.data
    uid = call.message.chat.id
    ensure_user(uid)
    # User actions
    if data == "done_task":
        task = users[uid].get("current_task")
        if not task:
            bot.answer_callback_query(call.id, "No active task!")
            return
        # Put reward on hold and notify admin
        reward = task["reward"]
        users[uid]["hold"] += reward
        task["status"] = "pending_admin"
        # send immediate processing message of 30 minutes
        bot.answer_callback_query(call.id, "Task submitted. Processing (about 30 minutes).")
        bot.send_message(uid, f"⏳ Your task is submitted and will be processed (approx {TASK_USER_PROCESSING_MINUTES} minutes). You will be notified when admin approves or rejects.")
        # notify admin with details + approve/reject buttons
        admin_markup = types.InlineKeyboardMarkup()
        admin_markup.add(
            types.InlineKeyboardButton("✅ Approve Task", callback_data=f"approve_task_{uid}"),
            types.InlineKeyboardButton("❌ Reject Task", callback_data=f"reject_task_{uid}")
        )
        # Build admin text including task details
        if task["type"] == "generated":
            admin_text = f"📝 *Task Submitted (Generated Gmail)*\nUser: `{uid}`\nEmail: `{task['email']}`\nPassword: `{task['password']}`\nReward: {reward} PKR"
        elif task["type"] == "own":
            admin_text = f"📝 *Task Submitted (User's Gmail)*\nUser: `{uid}`\nEmail: `{task['email']}`\nPassword: `{task['password']}`\nReward: {reward} PKR"
        else:
            admin_text = f"📝 *Task Submitted (Facebook 2FA)*\nUser: `{uid}`\nFB ID: `{task.get('fb_id')}`\nEmail: `{task.get('email')}`\nPassword: `{task.get('password')}`\n2FA: `{task.get('2fa')}`\nReward: {reward} PKR"
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

    # Admin actions: approve/reject task
    if data.startswith("approve_task_") and call.message.chat.id == ADMIN_CHAT_ID:
        target_uid = int(data.split("_")[-1])
        t = users[target_uid].get("current_task")
        if not t:
            bot.answer_callback_query(call.id, "No task found for this user.")
            return
        reward = t["reward"]
        # move from hold to balance
        users[target_uid]["hold"] -= reward
        users[target_uid]["balance"] += reward
        users[target_uid]["tasks_completed"] += 1
        t["status"] = "approved"
        users[target_uid]["current_task"] = None
        bot.answer_callback_query(call.id, "Approved.")
        bot.send_message(target_uid, f"✅ Your task was approved. {reward} PKR has been added to your balance.")
        bot.send_message(ADMIN_CHAT_ID, f"✔ Approved task for user {target_uid}")
        # referral bonus
        ref = users[target_uid].get("referrer")
        if ref and ref in users:
            users[ref]["balance"] += REFERRAL_BONUS_PER_TASK
            users[ref]["referral_earned"] += REFERRAL_BONUS_PER_TASK
            bot.send_message(ref, f"🎉 You earned {REFERRAL_BONUS_PER_TASK} PKR from your referral's approved task (user {target_uid}).")
        return

    if data.startswith("reject_task_") and call.message.chat.id == ADMIN_CHAT_ID:
        target_uid = int(data.split("_")[-1])
        t = users[target_uid].get("current_task")
        if not t:
            bot.answer_callback_query(call.id, "No task found.")
            return
        reward = t["reward"]
        # remove hold and don't add to balance (refund not given)
        users[target_uid]["hold"] -= reward
        users[target_uid]["current_task"] = None
        t["status"] = "rejected"
        bot.answer_callback_query(call.id, "Rejected.")
        bot.send_message(target_uid, f"❌ Your task was rejected by admin. Please try again.")
        bot.send_message(ADMIN_CHAT_ID, f"✖ Rejected task for user {target_uid}")
        return

    # Withdraw approve/reject (admin)
    if data.startswith("approve_wd_") and call.message.chat.id == ADMIN_CHAT_ID:
        parts = data.split("_")
        idx = int(parts[2])
        target_uid = int(parts[3])
        req = users[target_uid]["withdraw_requests"][idx]
        # mark approved
        req["status"] = "approved"
        # admin must perform the payout externally; we just update hold
        if req["method"] == "binance":
            pkr = req["pkr_amount"]
            users[target_uid]["hold"] -= pkr
            # nothing added to balance (already deducted when request made)
            bot.send_message(target_uid, f"✅ Your Binance withdrawal of {req['usd_amount']} USD has been approved and will be processed. Processing time: {WITHDRAW_PROCESSING_HOURS} hours.")
        else:
            pkr = req["pkr_amount"]
            users[target_uid]["hold"] -= pkr
            bot.send_message(target_uid, f"✅ Your withdrawal of {pkr} PKR ({req['method']}) has been approved and will be processed. Processing time: {WITHDRAW_PROCESSING_HOURS} hours.")
        bot.answer_callback_query(call.id, "Withdraw approved.")
        bot.send_message(ADMIN_CHAT_ID, f"✔ Approved withdraw for user {target_uid}")
        return

    if data.startswith("reject_wd_") and call.message.chat.id == ADMIN_CHAT_ID:
        parts = data.split("_")
        idx = int(parts[2])
        target_uid = int(parts[3])
        req = users[target_uid]["withdraw_requests"][idx]
        req["status"] = "rejected"
        # refund hold back to balance
        if req["method"] == "binance":
            pkr = req["pkr_amount"]
        else:
            pkr = req["pkr_amount"]
        users[target_uid]["hold"] -= pkr
        users[target_uid]["balance"] += pkr
        bot.answer_callback_query(call.id, "Withdraw rejected and refunded.")
        bot.send_message(target_uid, f"❌ Your withdrawal request was rejected. {pkr} PKR has been refunded to your balance.")
        bot.send_message(ADMIN_CHAT_ID, f"✖ Rejected withdraw for user {target_uid}")
        return

    # If tiggered by withdraw method selection from user keyboard
    if data.startswith("wd_"):
        # user selected a method
        method = data.split("_",1)[1]  # e.g. easypaisa, jazzcash, bank, binance
        users[uid]["state"] = f"awaiting_withdraw_{method}"
        if method == "binance":
            bot.answer_callback_query(call.id, "Enter the USD amount you want to withdraw (minimum 1 USD).")
            bot.send_message(uid, "Enter the USD amount you want to withdraw (for example: 1 or 2.5):")
        else:
            bot.answer_callback_query(call.id, f"Enter the amount in PKR (minimum {WITHDRAW_MIN_PKR} PKR).")
            bot.send_message(uid, f"Enter the amount in PKR (minimum {WITHDRAW_MIN_PKR}):")
        return

    # default fallback
    bot.answer_callback_query(call.id, "Action received.")

# ------------------------------
# End of file — no polling (Gunicorn will run Flask app)
# ------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
