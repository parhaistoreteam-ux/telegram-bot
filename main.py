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
# IN-MEMORY DATA STORAGE (NOTE: persist to DB for production)
# ============================================================

users = {}  # In-memory. Persist this (Redis/Mongo/SQLite) for production.

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
# HELPERS
# ============================================================

def ensure_user(uid, start_referrer=None):
    """Ensure user record exists. NOTE: For production, persist storage."""
    if uid not in users:
        users[uid] = {
            "balance": 0,               # available balance
            "hold": 0,                  # reserved (pending) amount
            "tasks_completed": 0,
            "referrer": None,
            "referrals_count": 0,
            "referral_earned": 0,
            "current_task": None,       # temp for composing a task before 'Done'
            "tasks": [],                # list of all submitted tasks (pending/approved/rejected)
            "next_task_id": 1,          # incremental id for tasks
            "state": None,
            "withdraw_requests": []
        }

    u = users[uid]

    if start_referrer and start_referrer != uid:
        # only set referrer if not already set
        if u.get("referrer") is None:
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
# COMMANDS / SIMPLE HANDLERS
# ============================================================

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
        bot.send_message(message.chat.id, f"Admin Panel Loaded\nUsers: {len(users)}")


@bot.message_handler(commands=['help'])
def cmd_help(message):
    bot.send_message(message.chat.id, HELP_TEXT)


@bot.message_handler(func=lambda m: m.text == "❓ Help")
def button_help(message):
    bot.send_message(message.chat.id, HELP_TEXT)


# ============================================================
# TASK SELECTION CALLBACKS
# ============================================================

@bot.message_handler(func=lambda m: m.text == "📝 Tasks")
def show_tasks(message):
    ensure_user(message.chat.id)
    bot.send_message(message.chat.id, "Choose a task type:", reply_markup=tasks_menu())


@bot.callback_query_handler(func=lambda call: call.data.startswith("task_") or call.data == "help")
def handle_task_choice(call):
    uid = call.message.chat.id
    ensure_user(uid)

    # GENERATED GMAIL TASK - create a temporary current_task ready to be submitted
    if call.data == "task_gen":
        email, password = generate_email()
        users[uid]["current_task"] = {
            "type": "generated",
            "email": email,
            "password": password,
            "reward": GEN_TASK_REWARD,
            "status": "draft"   # draft until user presses Done
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
        bot.send_message(uid, "Send: fb_id fb_email fb_password 2fa_code", parse_mode="Markdown")
        return

    # HELP BUTTON
    if call.data == "help":
        bot.send_message(uid, HELP_TEXT)
        return


# ============================================================
# TEXT MESSAGE HANDLER (MAIN)
# ============================================================

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    uid = message.chat.id
    ensure_user(uid)
    u = users[uid]

    text = (message.text or "").strip()

    # MENU: BALANCE
    if text.lower() in ["💼 balance", "balance"]:
        bot.send_message(uid, f"💼 Balance: {u['balance']} PKR\n🔒 Hold: {u['hold']} PKR\n"
                              f"📥 Pending Tasks: {len([t for t in u['tasks'] if t.get('status') == 'pending_admin'])}")
        return

    # MENU: WITHDRAW (start)
    if text.lower() in ["💰 withdraw", "withdraw"]:
        u["state"] = None
        bot.send_message(uid, "Select withdrawal method:", reply_markup=withdraw_methods_markup())
        return

    # MENU: TASKS
    if text.lower() in ["📝 tasks", "tasks"]:
        bot.send_message(uid, "Choose a task:", reply_markup=tasks_menu())
        return

    # MENU: REFERRAL
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

    # ----------------------------------------------------
    # WITHDRAW: awaiting_withdraw_<method> -> user entered amount
    # ----------------------------------------------------
    if u["state"] and u["state"].startswith("awaiting_withdraw_"):
        method = u["state"].split("_", 2)[2]

        try:
            amt = float(message.text)
        except:
            bot.send_message(uid, "❌ Invalid amount. Send a number (e.g. 500).")
            return

        # BINANCE (USD)
        if method == "binance":
            if amt < BINANCE_MIN_USD:
                bot.send_message(uid, f"Minimum is {BINANCE_MIN_USD} USD")
                return

            required_pkr = int(amt * BINANCE_PKR_PER_USD)

            if u["balance"] < required_pkr:
                bot.send_message(uid, f"❌ Not enough balance. You need {required_pkr} PKR.")
                return

            u["withdraw_temp"] = {
                "method": method,
                "usd_amount": amt,
                "pkr_amount": required_pkr
            }

        else:
            # PKR withdraw methods
            if amt < WITHDRAW_MIN_PKR:
                bot.send_message(uid, f"Minimum is {WITHDRAW_MIN_PKR} PKR")
                return

            if u["balance"] < amt:
                bot.send_message(uid, "❌ Insufficient balance.")
                return

            u["withdraw_temp"] = {
                "method": method,
                "pkr_amount": int(amt)
            }

        # Next step: ask for account holder name
        u["state"] = f"awaiting_account_name_{method}"
        bot.send_message(uid, "✔ Send Account Holder Name:")
        return

    # ----------------------------------------------------
    # WITHDRAW: awaiting_account_name_<method>
    # ----------------------------------------------------
    if u["state"] and u["state"].startswith("awaiting_account_name_"):
        method = u["state"].split("_", 3)[3]

        if "withdraw_temp" not in u:
            bot.send_message(uid, "❌ Error: No withdraw in progress. Start again.")
            u["state"] = None
            return

        u["withdraw_temp"]["account_name"] = message.text.strip()
        u["state"] = f"awaiting_account_number_{method}"
        bot.send_message(uid, "✔ Now send Account Number:")
        return

    # ----------------------------------------------------
    # WITHDRAW: awaiting_account_number_<method> -> finalize
    # ----------------------------------------------------
    if u["state"] and u["state"].startswith("awaiting_account_number_"):
        method = u["state"].split("_", 3)[3]
        temp = u.get("withdraw_temp", None)

        if not temp:
            bot.send_message(uid, "❌ Error: No withdraw temp found. Start again.")
            u["state"] = None
            return

        temp["account_number"] = message.text.strip()

        # Build request object
        req = {
            "user_id": uid,
            "method": temp["method"],
            "account_name": temp.get("account_name"),
            "account_number": temp.get("account_number"),
            "pkr_amount": temp.get("pkr_amount"),
            "usd_amount": temp.get("usd_amount"),
            "status": "pending"
        }

        # Append request
        u["withdraw_requests"].append(req)

        # Hold funds
        hold = req.get("pkr_amount", 0)
        # Safety: don't let balance go negative
        if hold > u["balance"]:
            bot.send_message(uid, "❌ Unexpected error: insufficient balance.")
            u["state"] = None
            u.pop("withdraw_temp", None)
            return

        u["balance"] -= hold
        u["hold"] += hold

        # Notify admin with approve/reject buttons
        admin_markup = types.InlineKeyboardMarkup()
        idx = len(u["withdraw_requests"]) - 1
        admin_markup.add(
            types.InlineKeyboardButton("Approve", callback_data=f"approve_wd_{idx}_{uid}"),
            types.InlineKeyboardButton("Reject", callback_data=f"reject_wd_{idx}_{uid}")
        )

        # Compose admin message
        admin_text = (
            f"💸 *New Withdraw Request*\n"
            f"User: `{uid}`\n"
            f"Method: *{temp['method']}*\n"
            f"Account Name: `{temp.get('account_name')}`\n"
            f"Account Number: `{temp.get('account_number')}`\n"
            f"Amount (PKR): `{req.get('pkr_amount')}`\n"
            f"Amount (USD): `{req.get('usd_amount')}`\n"
            f"Processing Time: {WITHDRAW_PROCESSING_HOURS} hours\n"
        )

        admin_notify(admin_text, admin_markup)

        bot.send_message(uid, f"⏳ Your withdraw request is under review. Processing time: {WITHDRAW_PROCESSING_HOURS} hours.")
        u["state"] = None
        u.pop("withdraw_temp", None)
        return

    # ======================================================
    # TASK INPUTS (own gmail / fb)
    # ======================================================

    if u["state"] == "awaiting_own_gmail":
        parts = message.text.split()
        if len(parts) < 2:
            bot.send_message(uid, "Send: email password")
            return

        # Save as temporary current task (user must press Done to submit)
        users[uid]["current_task"] = {
            "type": "own",
            "email": parts[0],
            "password": " ".join(parts[1:]),
            "reward": OWN_TASK_REWARD,
            "status": "draft"
        }

        u["state"] = None

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Done", callback_data="done_task"))
        markup.add(types.InlineKeyboardButton("Cancel", callback_data="cancel_task"))

        bot.send_message(uid, "Credentials saved. Press *Done* when finished.", reply_markup=markup, parse_mode="Markdown")
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
            "status": "draft"
        }

        u["state"] = None

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Done", callback_data="done_task"))
        markup.add(types.InlineKeyboardButton("Cancel", callback_data="cancel_task"))

        bot.send_message(uid, "Facebook info saved. Press *Done* when finished.", reply_markup=markup)
        return

    # FALLBACK
    bot.send_message(uid, "Use menu options.", reply_markup=main_menu())


# ============================================================
# CALLBACKS: withdraw selection, task done/cancel, admin approvals
# ============================================================

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    data = call.data
    uid = call.message.chat.id
    ensure_user(uid)

    # --------------------------
    # USER SELECTS WITHDRAW METHOD
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
    # TASK DONE / CANCEL (USER)
    # --------------------------
    if data == "done_task":
        u = users[uid]
        task = u.get("current_task")
        if not task:
            return bot.answer_callback_query(call.id, "No active task to submit.")

        reward = int(task.get("reward", 0))

        # Create persistent task entry with unique id
        task_id = u["next_task_id"]
        u["next_task_id"] += 1

        task_entry = {
            "id": task_id,
            "type": task.get("type"),
            # copy fields depending on type
            "email": task.get("email"),
            "password": task.get("password"),
            "fb_id": task.get("fb_id"),
            "2fa": task.get("2fa"),
            "reward": reward,
            "status": "pending_admin"
        }

        # Append to user's tasks list
        u["tasks"].append(task_entry)

        # Reserve funds in hold (task reward reserved until admin approves)
        u["hold"] += reward

        # clear temporary current_task so user can create another
        u["current_task"] = None

        bot.answer_callback_query(call.id)
        bot.send_message(uid, "⏳ Task submitted. Admin reviewing. You can do other tasks while this is pending.")

        # SEND FULL TASK INFO TO ADMIN with task id (so admin can approve specific task)
        details = "📥 *New Task Submitted*\n"
        details += f"👤 User: `{uid}`\n"
        details += f"💰 Reward: {reward} PKR\n"
        details += f"📌 Type: *{task_entry['type']}*\n"
        details += f"🔢 TaskID: `{task_id}`\n\n"

        if task_entry["type"] == "generated":
            details += f"Email: `{task_entry.get('email')}`\nPassword: `{task_entry.get('password')}`\n"

        elif task_entry["type"] == "own":
            details += f"Email: `{task_entry.get('email')}`\nPassword: `{task_entry.get('password')}`\n"

        elif task_entry["type"] == "facebook":
            details += f"FB ID: `{task_entry.get('fb_id')}`\n"
            details += f"Email: `{task_entry.get('email')}`\n"
            details += f"Password: `{task_entry.get('password')}`\n"
            details += f"2FA: `{task_entry.get('2fa')}`\n"

        admin_markup = types.InlineKeyboardMarkup()
        # Include user and task id so admin action can find the exact task
        admin_markup.add(
            types.InlineKeyboardButton("Approve", callback_data=f"approve_task_{uid}_{task_id}"),
            types.InlineKeyboardButton("Reject", callback_data=f"reject_task_{uid}_{task_id}")
        )

        admin_notify(details, admin_markup)
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
        # format: approve_task_<target>_<task_id>
        parts = data.split("_")
        if len(parts) < 4:
            bot.answer_callback_query(call.id, "Invalid callback data.")
            return
        try:
            target = int(parts[2])
            task_id = int(parts[3])
        except:
            bot.answer_callback_query(call.id, "Invalid indices.")
            return

        if target not in users:
            bot.answer_callback_query(call.id, "User not found.")
            return

        user_obj = users[target]
        # find task by id
        task = next((t for t in user_obj["tasks"] if t["id"] == task_id), None)
        if not task:
            bot.answer_callback_query(call.id, "Task not found.")
            return

        if task.get("status") == "approved":
            bot.answer_callback_query(call.id, "Already approved.")
            return

        reward = int(task.get("reward", 0))

        # Safeguard: ensure hold has enough; if not, correct it
        if user_obj["hold"] < reward:
            # If hold is missing (bug/accidental), attempt to avoid negative hold
            diff = reward - user_obj["hold"]
            # don't attempt auto-deduct user's balance here; just set hold to 0 and credit balance with reward
            user_obj["hold"] = 0
        else:
            user_obj["hold"] -= reward

        user_obj["balance"] += reward
        task["status"] = "approved"
        user_obj["tasks_completed"] += 1

        bot.answer_callback_query(call.id)
        bot.send_message(target, f"✅ Task approved! +{reward} PKR")
        bot.send_message(ADMIN_CHAT_ID, f"Approved task {task_id} for {target}")

        # Referral bonus
        ref = user_obj.get("referrer")
        if ref and ref in users:
            users[ref]["balance"] += REFERRAL_BONUS_PER_TASK
            users[ref]["referral_earned"] += REFERRAL_BONUS_PER_TASK
            bot.send_message(ref, f"🎉 Referral bonus added! +{REFERRAL_BONUS_PER_TASK} PKR")
        return

    # --------------------------
    # ADMIN: REJECT TASK
    # --------------------------
    if data.startswith("reject_task_") and uid == ADMIN_CHAT_ID:
        # format: reject_task_<target>_<task_id>
        parts = data.split("_")
        if len(parts) < 4:
            bot.answer_callback_query(call.id, "Invalid callback data.")
            return
        try:
            target = int(parts[2])
            task_id = int(parts[3])
        except:
            bot.answer_callback_query(call.id, "Invalid indices.")
            return

        if target not in users:
            bot.answer_callback_query(call.id, "User not found.")
            return

        user_obj = users[target]
        task = next((t for t in user_obj["tasks"] if t["id"] == task_id), None)
        if not task:
            bot.answer_callback_query(call.id, "Task not found.")
            return

        if task.get("status") == "rejected":
            bot.answer_callback_query(call.id, "Already rejected.")
            return

        reward = int(task.get("reward", 0))

        # release hold (if hold contains the reserved reward)
        if user_obj["hold"] >= reward:
            user_obj["hold"] -= reward
        else:
            # held amount missing (shouldn't happen), just set hold=0
            user_obj["hold"] = max(0, user_obj["hold"])

        task["status"] = "rejected"

        bot.answer_callback_query(call.id)
        bot.send_message(target, f"❌ Task rejected.")
        bot.send_message(ADMIN_CHAT_ID, f"Rejected task {task_id} for {target}")
        return

    # --------------------------
    # ADMIN: WITHDRAW APPROVE
    # --------------------------
    if data.startswith("approve_wd_") and uid == ADMIN_CHAT_ID:
        parts = data.split("_")
        # expected: ["approve","wd","<idx>","<target>"]
        if len(parts) < 4:
            bot.answer_callback_query(call.id, "Invalid callback data.")
            return
        try:
            idx = int(parts[2])
            target = int(parts[3])
        except:
            bot.answer_callback_query(call.id, "Invalid indices.")
            return

        if target not in users:
            bot.answer_callback_query(call.id, "User not found.")
            return

        user_obj = users[target]
        if idx < 0 or idx >= len(user_obj["withdraw_requests"]):
            bot.answer_callback_query(call.id, "Request not found.")
            return

        req = user_obj["withdraw_requests"][idx]
        if req.get("status") == "approved":
            bot.answer_callback_query(call.id, "Already approved.")
            return

        req["status"] = "approved"

        amount = req.get("pkr_amount", 0)

        # hold was already reserved (balance was already reduced when user submitted),
        # on approve we simply reduce the hold
        if user_obj["hold"] >= amount:
            user_obj["hold"] -= amount
        else:
            # safety: don't make hold negative
            user_obj["hold"] = 0

        bot.answer_callback_query(call.id)
        bot.send_message(target, f"✅ Withdraw approved: {amount} PKR")
        bot.send_message(ADMIN_CHAT_ID, f"Approved withdraw for {target}")
        return

    # --------------------------
    # ADMIN: WITHDRAW REJECT
    # --------------------------
    if data.startswith("reject_wd_") and uid == ADMIN_CHAT_ID:
        parts = data.split("_")
        if len(parts) < 4:
            bot.answer_callback_query(call.id, "Invalid callback data.")
            return
        try:
            idx = int(parts[2])
            target = int(parts[3])
        except:
            bot.answer_callback_query(call.id, "Invalid indices.")
            return

        if target not in users:
            bot.answer_callback_query(call.id, "User not found.")
            return

        user_obj = users[target]
        if idx < 0 or idx >= len(user_obj["withdraw_requests"]):
            bot.answer_callback_query(call.id, "Request not found.")
            return

        req = user_obj["withdraw_requests"][idx]
        if req.get("status") == "rejected":
            bot.answer_callback_query(call.id, "Already rejected.")
            return

        req["status"] = "rejected"

        amount = req.get("pkr_amount", 0)

        # refund
        # ensure we don't create negative hold
        if user_obj["hold"] >= amount:
            user_obj["hold"] -= amount
        else:
            # if hold smaller than amount (shouldn't happen), set hold to 0
            user_obj["hold"] = 0

        user_obj["balance"] += amount

        bot.answer_callback_query(call.id)
        bot.send_message(target, f"❌ Withdraw rejected. {amount} PKR refunded.")
        bot.send_message(ADMIN_CHAT_ID, f"Rejected withdraw for {target}")
        return

    # default answer
    bot.answer_callback_query(call.id)


# ============================================================
# RUN FLASK SERVER
# ============================================================

if __name__ == "__main__":
    # Helpful startup print
    print("Starting bot... Ensure BOT_TOKEN, ADMIN_CHAT_ID, WEBHOOK_URL are set.")
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
