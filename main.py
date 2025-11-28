import os
import telebot
from telebot import types
import random
import string
from flask import Flask, request

# ============================================================
# CONFIGURATION
# ============================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

if not BOT_TOKEN or not WEBHOOK_URL:
    raise RuntimeError("BOT_TOKEN and WEBHOOK_URL must be set in environment variables")

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)

# ============================================================
# IN-MEMORY DATA STORAGE
# ============================================================

users = {}

# CONSTANTS
REFERRAL_BONUS_PER_TASK = 2
GEN_TASK_REWARD = 40
OWN_TASK_REWARD = 40
FB_TASK_REWARD = 12

WITHDRAW_MIN_PKR = 200
BINANCE_PKR_PER_USD = 300
BINANCE_MIN_USD = 1

TASK_USER_PROCESSING_MINUTES = 30
WITHDRAW_PROCESSING_HOURS = 5


# ============================================================
# HELPER FUNCTIONS
# ============================================================

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
        bot.send_message(
            ADMIN_CHAT_ID,
            text,
            reply_markup=markup,
            parse_mode="Markdown"
        )
    except Exception as e:
        print("Failed to notify admin:", e)


# ============================================================
# FLASK ROUTES (WEBHOOK SYSTEM)
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
# KEYBOARD BUILDERS
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
# HELP TEXT (STYLE B)
# ============================================================

HELP_TEXT = (
    "📘 HELP MENU\n\n"
    "🧾 TASK SYSTEM\n"
    f"• Generated Gmail – 40 PKR\n"
    f"• Your Gmail – 40 PKR\n"
    f"• Facebook 2FA – 12 PKR\n"
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
# /START COMMAND
# ============================================================

@bot.message_handler(commands=['start'])
def handle_start(message):
    args = message.text.split()
    ref = None

    if len(args) > 1:
        try:
            ref = int(args[1])
        except:
            pass

    ensure_user(message.chat.id, start_referrer=ref)
    bot.send_message(message.chat.id, "Welcome! Choose an option:", reply_markup=main_menu())

    if message.chat.id == ADMIN_CHAT_ID:
        bot.send_message(message.chat.id, f"Admin Panel Loaded\nUsers: {len(users)}")


# ============================================================
# /HELP COMMAND
# ============================================================

@bot.message_handler(commands=['help'])
def cmd_help(message):
    bot.send_message(message.chat.id, HELP_TEXT)


@bot.message_handler(func=lambda m: m.text == "❓ Help")
def button_help(message):
    bot.send_message(message.chat.id, HELP_TEXT)


# ============================================================
# TASK SELECTION
# ============================================================

@bot.message_handler(func=lambda m: m.text == "📝 Tasks")
def show_tasks(message):
    ensure_user(message.chat.id)
    bot.send_message(message.chat.id, "Choose a task type:", reply_markup=tasks_menu())


@bot.callback_query_handler(func=lambda call: call.data.startswith("task_") or call.data == "help")
def handle_task_choice(call):
    uid = call.message.chat.id
    ensure_user(uid)

    # GENERATED GMAIL TASK
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
            "✅ *Generated Gmail Task*\n\n"
            "Use the credentials below to create a Gmail account:\n\n"
            f"📧 {email}\n🔐 {password}\n\n"
            f"Reward: {GEN_TASK_REWARD} PKR"
        )

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Done Task", callback_data="done_task"))
        markup.add(types.InlineKeyboardButton("❌ Cancel Task", callback_data="cancel_task"))

        bot.send_message(uid, text, reply_markup=markup, parse_mode="Markdown")
        return

    # USER PROVIDES GMAIL
    if call.data == "task_own":
        users[uid]["state"] = "awaiting_own_gmail"
        bot.send_message(uid, "Send:\nemail password", parse_mode="Markdown")
        return

    # FACEBOOK TASK
    if call.data == "task_fb":
        users[uid]["state"] = "awaiting_fb_details"
        bot.send_message(uid, "Send fb_id fb_email fb_password 2fa_code", parse_mode="Markdown")
        return

    # HELP BUTTON
    if call.data == "help":
        bot.send_message(uid, HELP_TEXT)
        return


# ============================================================
# MAIN MESSAGE HANDLER
# ============================================================

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    uid = message.chat.id
    ensure_user(uid)
    u = users[uid]

    text = (message.text or "").strip().lower()

    # MENU: BALANCE
    if text in ["💼 balance", "balance"]:
        bot.send_message(uid, f"💼 Balance: {u['balance']} PKR\n🔒 Hold: {u['hold']} PKR\n")
        return

    # MENU: WITHDRAW
    if text in ["💰 withdraw", "withdraw"]:
        u["state"] = None
        bot.send_message(uid, "Select withdrawal method:", reply_markup=withdraw_methods_markup())
        return

    # MENU: TASKS
    if text in ["📝 tasks", "tasks"]:
        bot.send_message(uid, "Choose a task:", reply_markup=tasks_menu())
        return

    # MENU: REFERRAL
    if text in ["🔗 referral link", "referral", "/referral"]:
        username = bot.get_me().username
        link = f"https://t.me/{username}?start={uid}"
        bot.send_message(uid, f"Your Referral Link:\n{link}")
        return

    # HELP
    if text in ["❓ help", "/help", "help"]:
        bot.send_message(uid, HELP_TEXT)
        return

    # ======================================================
    # WITHDRAW AMOUNT INPUT
    # ======================================================
    if u["state"] and u["state"].startswith("awaiting_withdraw_"):
        method = u["state"].split("_", 2)[2]

        try:
            amt = float(message.text)
        except:
            bot.send_message(uid, "❌ Invalid amount.")
            return

        # Binance USD withdraw
        if method == "binance":
            if amt < BINANCE_MIN_USD:
                bot.send_message(uid, f"Minimum is {BINANCE_MIN_USD} USD")
                return

            required_pkr = amt * BINANCE_PKR_PER_USD

            if u["balance"] < required_pkr:
                bot.send_message(uid, f"Not enough balance.")
                return

            u["withdraw_temp"] = {
                "method": method,
                "usd_amount": amt,
                "pkr_amount": int(required_pkr)
            }
            u["state"] = "awaiting_withdraw_account_binance"
            bot.send_message(uid, "Send Binance account email/ID:")
            return

        # Normal PKR withdraw
        if amt < WITHDRAW_MIN_PKR:
            bot.send_message(uid, f"Minimum is {WITHDRAW_MIN_PKR} PKR")
            return

        if u["balance"] < amt:
            bot.send_message(uid, "Insufficient balance.")
            return

        u["withdraw_temp"] = {
            "method": method,
            "pkr_amount": int(amt)
        }
        u["state"] = f"awaiting_withdraw_account_{method}"
        bot.send_message(uid, "Send account number:")
        return

    # ======================================================
    # WITHDRAW ACCOUNT INFO
    # ======================================================
    if u["state"] and u["state"].startswith("awaiting_withdraw_account_"):
        temp = u.get("withdraw_temp", {})
        account = message.text

        temp["account_info"] = account
        req = {
            "user_id": uid,
            "method": temp["method"],
            "pkr_amount": temp.get("pkr_amount"),
            "usd_amount": temp.get("usd_amount"),
            "account_info": account,
            "status": "pending"
        }

        u["withdraw_requests"].append(req)

        # HOLD BALANCE
        hold = temp.get("pkr_amount", 0)
        u["balance"] -= hold
        u["hold"] += hold

        # Notify admin
        admin_markup = types.InlineKeyboardMarkup()
        idx = len(u["withdraw_requests"]) - 1
        admin_markup.add(
            types.InlineKeyboardButton("Approve", callback_data=f"approve_wd_{idx}_{uid}"),
            types.InlineKeyboardButton("Reject", callback_data=f"reject_wd_{idx}_{uid}")
        )

        admin_notify(
            f"💸 Withdraw Request\nUser: {uid}\nAmount: {hold} PKR\nAccount: {account}",
            admin_markup
        )

        bot.send_message(uid, "Withdraw request submitted.")
        u["state"] = None
        u.pop("withdraw_temp", None)
        return

    # ======================================================
    # TASK INPUTS
    # ======================================================
    if u["state"] == "awaiting_own_gmail":
        parts = message.text.split()
        if len(parts) < 2:
            bot.send_message(uid, "Send: email password")
            return

        users[uid]["current_task"] = {
            "type": "own",
            "email": parts[0],
            "password": " ".join(parts[1:]),
            "reward": OWN_TASK_REWARD,
            "status": "pending"
        }

        u["state"] = None

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Done", callback_data="done_task"))
        markup.add(types.InlineKeyboardButton("Cancel", callback_data="cancel_task"))

        bot.send_message(uid, "Credentials saved.", reply_markup=markup)
        return

    if u["state"] == "awaiting_fb_details":
        parts = message.text.split()
        if len(parts) < 4:
            bot.send_message(uid, "Send: fb_id fb_email fb_password 2fa")
            return

        users[uid]["current_task"] = {
            "type": "facebook",
            "fb_id": parts[0],
            "email": parts[1],
            "password": parts[2],
            "2fa": parts[3],
            "reward": FB_TASK_REWARD,
            "status": "pending"
        }

        u["state"] = None

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Done", callback_data="done_task"))
        markup.add(types.InlineKeyboardButton("Cancel", callback_data="cancel_task"))

        bot.send_message(uid, "Facebook info saved.", reply_markup=markup)
        return

    # FALLBACK
    bot.send_message(uid, "Use menu options.", reply_markup=main_menu())


# ============================================================
# CALLBACKS (ADMIN + TASK SUBMIT)
# ============================================================

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    data = call.data
    uid = call.message.chat.id
    ensure_user(uid)

    # --------------------------
    # START WITHDRAWAL PROCESS
    # --------------------------
    if data.startswith("wd_"):
        method = data.split("_", 1)[1]
        users[uid]["state"] = f"awaiting_withdraw_{method}"
        bot.answer_callback_query(call.id)

        if method == "binance":
            bot.send_message(uid, "Enter amount in USD:")
        else:
            bot.send_message(uid, "Enter amount in PKR:")
        return

    # --------------------------
    # TASK DONE / CANCEL
    # --------------------------
    if data == "done_task":
        task = users[uid]["current_task"]
        if not task:
            return bot.answer_callback_query(call.id, "No active task.")

        reward = task["reward"]

        users[uid]["hold"] += reward  
        task["status"] = "pending_admin"

        bot.answer_callback_query(call.id)
        bot.send_message(uid, "Task submitted. Admin reviewing.")

        # Admin panel
        admin_markup = types.InlineKeyboardMarkup()
        admin_markup.add(
            types.InlineKeyboardButton("Approve", callback_data=f"approve_task_{uid}"),
            types.InlineKeyboardButton("Reject", callback_data=f"reject_task_{uid}")
        )

        admin_notify("New task submitted.", admin_markup)
        return

    if data == "cancel_task":
        users[uid]["current_task"] = None
        users[uid]["state"] = None
        bot.answer_callback_query(call.id, "Canceled.")
        bot.send_message(uid, "Task canceled.", reply_markup=main_menu())
        return

    # --------------------------
    # ADMIN: APPROVE TASK
    # --------------------------
    if data.startswith("approve_task_") and uid == ADMIN_CHAT_ID:
        target = int(data.split("_")[-1])
        task = users[target]["current_task"]

        reward = task["reward"]
        users[target]["hold"] -= reward
        users[target]["balance"] += reward
        users[target]["tasks_completed"] += 1

        users[target]["current_task"] = None

        bot.answer_callback_query(call.id)
        bot.send_message(target, f"Task approved! +{reward} PKR")
        bot.send_message(ADMIN_CHAT_ID, f"Approved task for {target}")

        # Referral bonus
        ref = users[target]["referrer"]
        if ref in users:
            users[ref]["balance"] += REFERRAL_BONUS_PER_TASK
            users[ref]["referral_earned"] += REFERRAL_BONUS_PER_TASK
            bot.send_message(ref, "Referral bonus added!")
        return

    # --------------------------
    # ADMIN: REJECT TASK
    # --------------------------
    if data.startswith("reject_task_") and uid == ADMIN_CHAT_ID:
        target = int(data.split("_")[-1])

        task = users[target]["current_task"]
        reward = task["reward"]

        users[target]["hold"] -= reward
        users[target]["current_task"] = None

        bot.answer_callback_query(call.id)
        bot.send_message(target, "Task rejected.")
        bot.send_message(ADMIN_CHAT_ID, f"Rejected task for {target}")
        return

    # --------------------------
    # ADMIN: WITHDRAW APPROVE
    # --------------------------
    if data.startswith("approve_wd_") and uid == ADMIN_CHAT_ID:
        _, _, idx, target = data.split("_")
        idx = int(idx)
        target = int(target)

        req = users[target]["withdraw_requests"][idx]
        req["status"] = "approved"

        amount = req.get("pkr_amount", 0)
        users[target]["hold"] -= amount

        bot.answer_callback_query(call.id)
        bot.send_message(target, f"Withdraw approved: {amount} PKR")
        bot.send_message(ADMIN_CHAT_ID, f"Approved withdraw for {target}")
        return

    # --------------------------
    # ADMIN: WITHDRAW REJECT
    # --------------------------
    if data.startswith("reject_wd_") and uid == ADMIN_CHAT_ID:
        _, _, idx, target = data.split("_")
        idx = int(idx)
        target = int(target)

        req = users[target]["withdraw_requests"][idx]
        req["status"] = "rejected"

        amount = req.get("pkr_amount", 0)
        users[target]["hold"] -= amount
        users[target]["balance"] += amount

        bot.answer_callback_query(call.id)
        bot.send_message(target, f"Withdraw rejected. {amount} refunded.")
        bot.send_message(ADMIN_CHAT_ID, f"Rejected withdraw for {target}")
        return

    bot.answer_callback_query(call.id)


# ============================================================
# RUN FLASK SERVER
# ============================================================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
