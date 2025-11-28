import os
import telebot
from telebot import types
import random
import string
from flask import Flask, request

# ------------------------------
# Configuration
# ------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

if not BOT_TOKEN or not WEBHOOK_URL:
    raise RuntimeError("BOT_TOKEN and WEBHOOK_URL must be set in environment variables")

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)

# ------------------------------
# In-memory storage
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
TASK_USER_PROCESSING_MINUTES = 30
WITHDRAW_PROCESSING_HOURS = 5

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
# Keyboards
# ------------------------------
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
    # Add help inside tasks if user wants contextual help
    markup.add(types.InlineKeyboardButton("❓ Help", callback_data="help"))
    return markup

def withdraw_methods_markup():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Easypaisa (PKR)", callback_data="wd_easypaisa"))
    markup.add(types.InlineKeyboardButton("JazzCash (PKR)", callback_data="wd_jazzcash"))
    markup.add(types.InlineKeyboardButton("Bank (PKR)", callback_data="wd_bank"))
    markup.add(types.InlineKeyboardButton("Binance (USD)", callback_data="wd_binance"))
    return markup

# ------------------------------
# Help text (Style B - Premium)
# ------------------------------
HELP_TEXT = (
    "📘 HELP MENU\n\n"
    "🧾 TASK SYSTEM\n"
    "• Generated Gmail – 40 PKR (we provide credentials)\n"
    "• Your Gmail – 40 PKR (you send credentials)\n"
    "• Facebook 2FA – 12 PKR (fb_id email password 2fa)\n"
    f"• Review Time – Up to {TASK_USER_PROCESSING_MINUTES} minutes (admin can approve earlier)\n"
    f"• Referral Bonus – {REFERRAL_BONUS_PER_TASK} PKR per approved task\n\n"
    "💵 WITHDRAW SYSTEM\n"
    f"• Easypaisa / JazzCash / Bank – Min {WITHDRAW_MIN_PKR} PKR\n"
    f"• Binance – Min {BINANCE_MIN_USD} USD (rate {BINANCE_PKR_PER_USD} PKR = 1 USD)\n"
    f"• Processing Time – {WITHDRAW_PROCESSING_HOURS} hours (admin manual)\n\n"
    "👤 ACCOUNT\n"
    "• 💼 Balance – Check balance\n"
    "• 🔗 Referral Link – Share to earn\n"
    "• 📝 Tasks – Task options\n\n"
    "❗ Need help? Contact admin."
)

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
# /help handler (and Help button)
# ------------------------------
@bot.message_handler(commands=['help'])
def cmd_help(message):
    bot.send_message(message.chat.id, HELP_TEXT)

# Also handle Help button text
@bot.message_handler(func=lambda m: m.text == "❓ Help")
def button_help(message):
    bot.send_message(message.chat.id, HELP_TEXT)

# ------------------------------
# Tasks handler
# ------------------------------
@bot.message_handler(func=lambda msg: msg.text == "📝 Tasks")
def show_tasks(message):
    ensure_user(message.chat.id)
    bot.send_message(message.chat.id, "Choose a task type:", reply_markup=tasks_menu())

@bot.callback_query_handler(func=lambda call: call.data.startswith("task_") or call.data == "help")
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
        text = (
            f"✅ *Generated Gmail Task*\n\n"
            "Create a Gmail using the credentials below on your device. After creating, return and press *Done Task*.\n\n"
            f"📧 `{email}`\n🔐 `{password}`\n\n"
            f"Reward: {GEN_TASK_REWARD} PKR"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Done Task", callback_data="done_task"))
        markup.add(types.InlineKeyboardButton("❌ Cancel Task", callback_data="cancel_task"))
        bot.send_message(uid, text, reply_markup=markup, parse_mode="Markdown")
    elif call.data == "task_own":
        users[uid]["state"] = "awaiting_own_gmail"
        bot.send_message(uid, "Please send your Gmail and password in one message using this format:\n`email@example.com password123`", parse_mode="Markdown")
    elif call.data == "task_fb":
        users[uid]["state"] = "awaiting_fb_details"
        bot.send_message(uid, "Please send your Facebook details in one message in this exact format:\n`fb_id fb_email fb_password 2fa_code`", parse_mode="Markdown")
    elif call.data == "help":
        bot.send_message(uid, HELP_TEXT)

# ------------------------------
# Text handler (menus first, then states)
# ------------------------------
@bot.message_handler(func=lambda m: True)
def handle_text(message):
    uid = message.chat.id
    ensure_user(uid)
    u = users[uid]
    state = u.get("state")
    text = (message.text or "").strip()
    text_lower = text.lower()

    # --- MENU COMMANDS FIRST ---
    if text_lower in ["💼 balance", "balance"]:
        bot.send_message(uid, f"💼 Balance: {u.get('balance',0)} PKR\n🔒 Hold: {u.get('hold',0)} PKR\n✅ Tasks Completed: {u.get('tasks_completed',0)}")
        return

    if text_lower in ["💰 withdraw", "withdraw"]:
        u["state"] = None
        bot.send_message(uid, "Choose withdrawal method:", reply_markup=withdraw_methods_markup())
        return

    if text_lower in ["📝 tasks", "tasks"]:
        bot.send_message(uid, "Choose a task type:", reply_markup=tasks_menu())
        return

    if text_lower in ["/referral", "🔗 referral link"] or text_lower.startswith("referral"):
        ensure_user(uid)
        try:
            username = bot.get_me().username
        except Exception:
            username = "this_bot"
        link = f"https://t.me/{username}?start={uid}"
        bot.send_message(uid, f"Share this link. You get {REFERRAL_BONUS_PER_TASK} PKR for each approved task from your referrals.\n\n{link}")
        return

    if text_lower in ["/help", "help", "❓ help"]:
        bot.send_message(uid, HELP_TEXT)
        return

    # --- STATE HANDLING (withdraw amount) ---
    if state and state.startswith("awaiting_withdraw_"):
        method = state.split("_", 2)[2]
        try:
            amt = float(text)
        except:
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
            u["withdraw_temp"] = {"method":"binance","usd_amount":amt,"pkr_amount":required_pkr}
            bot.send_message(uid, "Enter your Binance account email or ID for USD transfer:")
        else:
            if amt < WITHDRAW_MIN_PKR:
                bot.send_message(uid, f"Minimum withdraw is {WITHDRAW_MIN_PKR} PKR.")
                return
            if u["balance"] < amt:
                bot.send_message(uid, f"Insufficient balance. You have {u['balance']} PKR.")
                return
            u["state"] = f"awaiting_withdraw_account_{method}"
            u["withdraw_temp"] = {"method":method,"pkr_amount":int(amt)}
            bot.send_message(uid, f"Enter your {method} account details (number/email) for withdrawal:")
        return

    # --- Withdraw account input ---
    if state and state.startswith("awaiting_withdraw_account_"):
        temp = u.get("withdraw_temp", {})
        account_info = text
        temp["account_info"] = account_info
        req = {
            "user_id": uid,
            "method": temp.get("method"),
            "pkr_amount": temp.get("pkr_amount"),
            "usd_amount": temp.get("usd_amount"),
            "account_info": temp.get("account_info"),
            "status": "pending"
        }
        u["withdraw_requests"].append(req)
        # put money on hold
        pkr = temp.get("pkr_amount", 0) or 0
        u["balance"] -= pkr
        u["hold"] += pkr

        admin_text = f"💸 *Withdraw Request ({req['method'].title()})*\nUser: `{uid}`\nAmount: {pkr} PKR\nAccount: {temp['account_info']}\nProcessing: {WITHDRAW_PROCESSING_HOURS} hours"
        admin_markup = types.InlineKeyboardMarkup()
        admin_markup.add(types.InlineKeyboardButton("✅ Approve Withdraw", callback_data=f"approve_wd_{len(u['withdraw_requests'])-1}_{uid}"))
        admin_markup.add(types.InlineKeyboardButton("❌ Reject Withdraw", callback_data=f"reject_wd_{len(u['withdraw_requests'])-1}_{uid}"))
        admin_notify(admin_text, markup=admin_markup)

        bot.send_message(uid, f"✅ Withdraw request received. It will be processed (approx {WITHDRAW_PROCESSING_HOURS} hours).")
        u["state"] = None
        u.pop("withdraw_temp", None)
        return

    # --- Tasks input states ---
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
        bot.send_message(uid, f"Your Gmail credentials saved.\nEmail: `{email}`\nPassword: `{password}`\nPress Done when ready.", parse_mode="Markdown", reply_markup=markup)
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
# Callback handler (withdraw buttons, tasks, admin)
# ------------------------------
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    data = call.data
    caller_chat_id = call.message.chat.id
    ensure_user(caller_chat_id)

    # ---------- Withdraw method selection ----------
    if data.startswith("wd_"):
        method = data.split("_", 1)[1]  # easypaisa, jazzcash, bank, binance
        users[caller_chat_id]["state"] = f"awaiting_withdraw_{method}"
        bot.answer_callback_query(call.id)
        if method == "binance":
            bot.send_message(caller_chat_id, f"Enter the amount in USD you want to withdraw (min {BINANCE_MIN_USD} USD):")
        else:
            bot.send_message(caller_chat_id, f"Enter the amount in PKR you want to withdraw (min {WITHDRAW_MIN_PKR} PKR):")
        return

    # ---------- Tasks ----------
    if data == "done_task":
        task = users[caller_chat_id].get("current_task")
        if not task:
            bot.answer_callback_query(call.id, "No active task!")
            return
        reward = task["reward"]
        users[caller_chat_id]["hold"] += reward
        task["status"] = "pending_admin"
        bot.answer_callback_query(call.id, f"Task submitted! It will be reviewed (up to {TASK_USER_PROCESSING_MINUTES} minutes).")
        bot.send_message(caller_chat_id, f"⏳ Your task has been submitted!\n\n⏱ Review Time: Up to {TASK_USER_PROCESSING_MINUTES} minutes\n📌 You will be notified once admin approves or rejects.")
        admin_markup = types.InlineKeyboardMarkup()
        admin_markup.add(types.InlineKeyboardButton("✅ Approve Task", callback_data=f"approve_task_{caller_chat_id}"))
        admin_markup.add(types.InlineKeyboardButton("❌ Reject Task", callback_data=f"reject_task_{caller_chat_id}"))
        t = task
        if t["type"] == "generated":
            admin_text = f"📝 *Task Submitted (Generated Gmail)*\nUser: `{caller_chat_id}`\nEmail: `{t['email']}`\nPassword: `{t['password']}`\nReward: {reward} PKR"
        elif t["type"] == "own":
            admin_text = f"📝 *Task Submitted (User Gmail)*\nUser: `{caller_chat_id}`\nEmail: `{t['email']}`\nPassword: `{t['password']}`\nReward: {reward} PKR"
        else:
            admin_text = (
                f"📝 *Task Submitted (Facebook 2FA)*\nUser: `{caller_chat_id}`\nFB ID: `{t.get('fb_id')}`\n"
                f"Email: `{t.get('email')}`\nPassword: `{t.get('password')}`\n2FA: `{t.get('2fa')}`\nReward: {reward} PKR"
            )
        admin_notify(admin_text, markup=admin_markup)
        return

    if data == "cancel_task":
        if users[caller_chat_id].get("current_task"):
            users[caller_chat_id]["current_task"] = None
            users[caller_chat_id]["state"] = None
            bot.answer_callback_query(call.id, "Task canceled.")
            bot.send_message(caller_chat_id, "Task canceled.", reply_markup=main_menu())
        else:
            bot.answer_callback_query(call.id, "No task to cancel.")
        return

    # ---------- Admin approve/reject tasks ----------
    # Only admin chat should be able to trigger these
    if data.startswith("approve_task_") and caller_chat_id == ADMIN_CHAT_ID:
        try:
            target_uid = int(data.split("_")[-1])
        except:
            bot.answer_callback_query(call.id, "Invalid target id.")
            return
        task = users.get(target_uid, {}).get("current_task")
        if not task:
            bot.answer_callback_query(call.id, "No task found for this user.")
            return
        reward = task["reward"]
        # move from hold to balance immediately
        users[target_uid]["hold"] -= reward
        users[target_uid]["balance"] += reward
        users[target_uid]["tasks_completed"] += 1
        task["status"] = "approved"
        users[target_uid]["current_task"] = None
        # immediate notification to user
        try:
            bot.send_message(target_uid, f"✅ Your task was approved! {reward} PKR has been added to your balance.")
        except Exception as e:
            print("Error sending approval message to user:", e)
        bot.answer_callback_query(call.id, "Task approved.")
        bot.send_message(ADMIN_CHAT_ID, f"✔ Approved task for user {target_uid}")
        # referral bonus
        ref = users[target_uid].get("referrer")
        if ref and ref in users:
            users[ref]["balance"] += REFERRAL_BONUS_PER_TASK
            users[ref]["referral_earned"] += REFERRAL_BONUS_PER_TASK
            try:
                bot.send_message(ref, f"🎉 You earned {REFERRAL_BONUS_PER_TASK} PKR from your referral's approved task (user {target_uid}).")
            except Exception:
                pass
        return

    if data.startswith("reject_task_") and caller_chat_id == ADMIN_CHAT_ID:
        try:
            target_uid = int(data.split("_")[-1])
        except:
            bot.answer_callback_query(call.id, "Invalid target id.")
            return
        task = users.get(target_uid, {}).get("current_task")
        if task:
            reward = task["reward"]
            users[target_uid]["hold"] -= reward
            users[target_uid]["current_task"] = None
            task["status"] = "rejected"
            try:
                bot.send_message(target_uid, "❌ Your task was rejected by admin. Please try again.")
            except Exception:
                pass
            bot.answer_callback_query(call.id, "Task rejected.")
            bot.send_message(ADMIN_CHAT_ID, f"✖ Rejected task for user {target_uid}")
        else:
            bot.answer_callback_query(call.id, "No task found.")
        return

    # ---------- Admin approve/reject withdraw ----------
    if data.startswith("approve_wd_") and caller_chat_id == ADMIN_CHAT_ID:
        parts = data.split("_")
        if len(parts) < 4:
            bot.answer_callback_query(call.id, "Invalid withdraw data.")
            return
        idx = int(parts[2])
        target_uid = int(parts[3])
        req = users[target_uid]["withdraw_requests"][idx]
        req["status"] = "approved"
        pkr = req.get("pkr_amount", 0) or 0
        users[target_uid]["hold"] -= pkr
        try:
            bot.send_message(target_uid, f"✅ Your withdrawal of {pkr} PKR ({req['method']}) has been approved. Processing time: {WITHDRAW_PROCESSING_HOURS} hours.")
        except Exception:
            pass
        bot.answer_callback_query(call.id, "Withdraw approved.")
        bot.send_message(ADMIN_CHAT_ID, f"✔ Approved withdraw for user {target_uid}")
        return

    if data.startswith("reject_wd_") and caller_chat_id == ADMIN_CHAT_ID:
        parts = data.split("_")
        if len(parts) < 4:
            bot.answer_callback_query(call.id, "Invalid withdraw data.")
            return
        idx = int(parts[2])
        target_uid = int(parts[3])
        req = users[target_uid]["withdraw_requests"][idx]
        req["status"] = "rejected"
        pkr = req.get("pkr_amount", 0) or 0
        users[target_uid]["hold"] -= pkr
        users[target_uid]["balance"] += pkr
        try:
            bot.send_message(target_uid, f"❌ Your withdrawal was rejected. {pkr} PKR has been refunded to your balance.")
        except Exception:
            pass
        bot.answer_callback_query(call.id, "Withdraw rejected and refunded.")
        bot.send_message(ADMIN_CHAT_ID, f"✖ Rejected withdraw for user {target_uid}")
        return

    # default
    bot.answer_callback_query(call.id, "Action received.")

# ------------------------------
# Run Flask (Gunicorn will use app)
# ------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
