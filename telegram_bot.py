"""
Telegram DevOps Bot — بوت تليجرام الذكي لإدارة السيرفر
حماية مشددة: مسموح فقط للمستخدم @Yahya_el_hamzawy
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import os
import json
import queue
import threading
import time
import telebot
from telebot import types as tele_types
from dotenv import load_dotenv

from ssh_manager import SSHManager
from agent import ServerAgent, get_or_create_agent_session, reset_session_by_id, get_session_info, load_settings, save_settings

load_dotenv()

# Configuration
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USERNAME = os.getenv("TELEGRAM_ALLOWED_USER", "Yahya_el_hamzawy").lower().replace("@", "")

AUTH_FILE = os.path.join(os.path.dirname(__file__), ".telegram_auth.json")
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), ".saved_ssh.json")

# Shared SSH instance (can be injected from app.py or initialized locally)
bot_ssh = SSHManager()
active_agent = None

# Initialize bot
if not BOT_TOKEN or BOT_TOKEN.startswith("your_"):
    bot = None
    print("[Telegram Bot] Warning: TELEGRAM_BOT_TOKEN is missing or not set in .env")
else:
    bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")


def get_authorized_user_id():
    """Load cached numeric user ID if previously saved."""
    if os.path.exists(AUTH_FILE):
        try:
            with open(AUTH_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("user_id")
        except Exception:
            pass
    return None


def save_authorized_user_id(user_id):
    """Persist numeric user ID once verified."""
    try:
        with open(AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump({"user_id": user_id, "username": ALLOWED_USERNAME}, f)
    except Exception:
        pass


def save_ssh_credentials(host, user, password, sudo_password="", port=22):
    """Save server connection parameters locally for bot auto-reconnection."""
    try:
        with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "host": host,
                "user": user,
                "password": password,
                "sudo_password": sudo_password,
                "port": port
            }, f)
    except Exception:
        pass


def load_ssh_credentials():
    """Load saved SSH parameters if available."""
    if os.path.exists(CREDENTIALS_FILE):
        try:
            with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def is_user_authorized(from_user) -> bool:
    """Verify that the sender is exclusively Yahya_el_hamzawy."""
    username = (from_user.username or "").lower()
    saved_id = get_authorized_user_id()

    if username == ALLOWED_USERNAME.lower():
        if saved_id != from_user.id:
            save_authorized_user_id(from_user.id)
        return True

    if saved_id and from_user.id == saved_id:
        return True

    return False


def notify_unauthorized_access(from_user):
    """Log and alert when an unauthorized user attempts to access the bot."""
    info = f"ID: {from_user.id}, Username: @{from_user.username}, Name: {from_user.first_name} {from_user.last_name or ''}"
    print(f"[SECURITY ALERT] Unauthorized access attempt: {info}")

    saved_id = get_authorized_user_id()
    if bot and saved_id:
        try:
            alert_msg = (
                f"🚨 <b>تنبيه أمني:</b> حاول مستخدم غير مصرح له الدخول للبوت!\n"
                f"👤 <b>الاسم:</b> {from_user.first_name} {from_user.last_name or ''}\n"
                f"🔗 <b>اليوزر:</b> @{from_user.username or 'بدون'}\n"
                f"🆔 <b>User ID:</b> <code>{from_user.id}</code>\n"
                f"⛔ تم رفض وصوله تلقائياً."
            )
            bot.send_message(saved_id, alert_msg)
        except Exception:
            pass


def ensure_ssh_connected() -> bool:
    """Check connection or attempt auto-reconnect using saved credentials."""
    global bot_ssh
    if bot_ssh.is_connected():
        return True

    creds = load_ssh_credentials()
    if creds:
        res = bot_ssh.connect(
            hostname=creds["host"],
            username=creds["user"],
            password=creds["password"],
            port=creds.get("port", 22),
            sudo_password=creds.get("sudo_password")
        )
        return res["success"]

    return False


# User preferences (e.g. web search toggle per chat)
_user_search_pref = {}

def is_web_search_enabled(chat_id) -> bool:
    """Check if web search is enabled for this chat (default: True)."""
    return _user_search_pref.get(str(chat_id), True)

def set_web_search_enabled(chat_id, enabled: bool):
    """Update web search preference for this chat."""
    _user_search_pref[str(chat_id)] = enabled


# Build Main Interactive Keyboard
def build_main_keyboard(chat_id=None):
    keyboard = tele_types.InlineKeyboardMarkup(row_width=2)
    b1 = tele_types.InlineKeyboardButton("🐳 فحص Docker", callback_data="btn_docker")
    b2 = tele_types.InlineKeyboardButton("🩺 فحص شامل (Doctor)", callback_data="btn_doctor")
    b3 = tele_types.InlineKeyboardButton("💾 استهلاك الهارد والرام", callback_data="btn_resources")
    b4 = tele_types.InlineKeyboardButton("⚙️ خدمات النظام", callback_data="btn_services")
    b5 = tele_types.InlineKeyboardButton("📜 سجل الأخطاء (Logs)", callback_data="btn_logs")
    b6 = tele_types.InlineKeyboardButton("🔄 حالة السيرفر", callback_data="btn_status")

    search_state = "مُفعّل ✅" if (chat_id is None or is_web_search_enabled(chat_id)) else "مُعطّل ❌"
    b_search = tele_types.InlineKeyboardButton(f"🌐 بحث الويب: {search_state}", callback_data="btn_toggle_search")
    b_new = tele_types.InlineKeyboardButton("🧹 جلسة جديدة", callback_data="btn_new_session")

    keyboard.add(b1, b2)
    keyboard.add(b3, b4)
    keyboard.add(b5, b6)
    keyboard.add(b_search, b_new)
    return keyboard


if bot:
    # -------------------------------------------------------------
    # Command: /new or /reset (Clear Session Memory)
    # -------------------------------------------------------------
    @bot.message_handler(commands=["new", "reset"])
    def cmd_reset_session(message):
        if not is_user_authorized(message.from_user):
            notify_unauthorized_access(message.from_user)
            bot.reply_to(message, "⛔ غير مصرح لك.")
            return

        session_id = f"tg_{message.chat.id}"
        reset_session_by_id(session_id)
        bot.reply_to(
            message,
            "🧹 <b>تم بدء جلسة جديدة ومسح ذاكرة المحادثات السابقة بنجاح!</b>\n"
            "الوكيل الآن جاهز لتلقي أي استفسار أو مهمة جديدة.",
            parse_mode="HTML",
            reply_markup=build_main_keyboard(message.chat.id)
        )


    # -------------------------------------------------------------
    # Command: /search [on|off] (Toggle Live Web Search)
    # -------------------------------------------------------------
    @bot.message_handler(commands=["search"])
    def cmd_toggle_search(message):
        if not is_user_authorized(message.from_user):
            notify_unauthorized_access(message.from_user)
            bot.reply_to(message, "⛔ غير مصرح لك.")
            return

        parts = message.text.strip().split()
        if len(parts) > 1:
            arg = parts[1].lower()
            if arg in ("on", "enable", "1", "true", "نعم", "تفعيل"):
                set_web_search_enabled(message.chat.id, True)
            elif arg in ("off", "disable", "0", "false", "لا", "تعطيل"):
                set_web_search_enabled(message.chat.id, False)
        else:
            # Toggle
            current = is_web_search_enabled(message.chat.id)
            set_web_search_enabled(message.chat.id, not current)

        now_enabled = is_web_search_enabled(message.chat.id)
        state_txt = "مُفعّل ✅" if now_enabled else "مُعطّل ❌"
        bot.reply_to(
            message,
            f"🌐 <b>حالة البحث في الويب (Web Search):</b> {state_txt}\n\n"
            f"عند التفعيل، يستطيع الوكيل البحث المباشر على الإنترنت للتحقق من أخطاء السيرفر وتوثيق الحزم وحاويات Docker.",
            parse_mode="HTML",
            reply_markup=build_main_keyboard(message.chat.id)
        )


    # -------------------------------------------------------------
    # Command: /start
    # -------------------------------------------------------------
    @bot.message_handler(commands=["start"])
    def cmd_start(message):
        if not is_user_authorized(message.from_user):
            notify_unauthorized_access(message.from_user)
            bot.reply_to(message, "⛔ <b>عذراً، هذا البوت خاص وغير مصرح لك باستخدامه نهائياً.</b>")
            return

        connected = ensure_ssh_connected()
        status_text = f"🟢 <b>متصل بـ:</b> <code>{bot_ssh.username}@{bot_ssh.hostname}</code>" if connected else "🔴 <b>السيرفر غير متصل</b> (استخدم /connect للاتصال أو اتصل من الويب)"

        search_state = "مُفعّل ✅" if is_web_search_enabled(message.chat.id) else "مُعطّل ❌"

        welcome = (
            f"👋 <b>أهلاً بك يا باشمهندس يحيى في المساعد الذكي لإدارة السيرفر (AI DevOps Bot)! ⚡</b>\n\n"
            f"{status_text}\n"
            f"🌐 <b>البحث في الويب:</b> {search_state}\n\n"
            f"💡 <b>كيفية الاستخدام:</b>\n"
            f"• اضغط على الأزرار السريعة بالأسفل للفحص الفوري.\n"
            f"• أو اكتب أي سؤال بالعامية (مثل: <i>'الدوكر شغال؟'</i> أو <i>'اعمل ريستارت لحاوية Rio Chat'</i>).\n"
            f"• <b>الذاكرة الذكية:</b> البوت يتذكر سياق كلامك السابق في نفس الجلسة!\n"
            f"• للتبديل بين تفعيل وتعطيل بحث الويب أرسل: <code>/search</code>\n"
            f"• لبدء جلسة جديدة ومسح الذاكرة السابقة أرسل: <code>/new</code>\n"
            f"• لتنفيذ أمر Bash مباشر اكتب: <code>/cmd &lt;الأمر&gt;</code>\n"
        )
        bot.send_message(message.chat.id, welcome, reply_markup=build_main_keyboard(message.chat.id))


    # -------------------------------------------------------------
    # Command: /connect <host> <user> <pass> [sudo] [port]
    # -------------------------------------------------------------
    @bot.message_handler(commands=["connect"])
    def cmd_connect(message):
        if not is_user_authorized(message.from_user):
            notify_unauthorized_access(message.from_user)
            bot.reply_to(message, "⛔ غير مصرح لك.")
            return

        parts = message.text.split()
        if len(parts) < 4:
            help_txt = (
                "📌 <b>صيغة أمر الاتصال:</b>\n"
                "<code>/connect &lt;Host/IP&gt; &lt;Username&gt; &lt;Password&gt; [SudoPassword] [Port]</code>\n\n"
                "<b>مثال:</b>\n"
                "<code>/connect 192.168.100.4 yy MyPass123 MyPass123 22</code>"
            )
            bot.reply_to(message, help_txt)
            return

        host = parts[1].strip()
        user = parts[2].strip()
        password = parts[3].strip()
        sudo_pass = parts[4].strip() if len(parts) > 4 else ""
        port = int(parts[5]) if len(parts) > 5 else 22

        msg = bot.reply_to(message, "⏳ <b>جاري الاتصال بالسيرفر عبر SSH...</b>")

        res = bot_ssh.connect(host, user, password, port, sudo_pass if sudo_pass else None)
        if res["success"]:
            save_ssh_credentials(host, user, password, sudo_pass, port)
            bot.edit_message_text(
                f"✅ <b>تم الاتصال بالسيرفر بنجاح!</b>\n💻 <code>{user}@{host}:{port}</code>",
                message.chat.id,
                msg.message_id
            )
        else:
            bot.edit_message_text(
                f"❌ <b>فشل الاتصال:</b>\n<code>{res['message']}</code>",
                message.chat.id,
                msg.message_id
            )


    # -------------------------------------------------------------
    # Command: /cmd <command> (Direct Bash execution)
    # -------------------------------------------------------------
    @bot.message_handler(commands=["cmd"])
    def cmd_execute(message):
        if not is_user_authorized(message.from_user):
            notify_unauthorized_access(message.from_user)
            bot.reply_to(message, "⛔ غير مصرح لك.")
            return

        if not ensure_ssh_connected():
            bot.reply_to(message, "🔴 <b>السيرفر غير متصل حالياً.</b> يرجى الاتصال عبر /connect أولاً.")
            return

        raw_cmd = message.text.replace("/cmd", "", 1).strip()
        if not raw_cmd:
            bot.reply_to(message, "اكتب الأمر بعد /cmd، مثال: <code>/cmd docker ps</code>")
            return

        status_msg = bot.reply_to(message, f"⚙️ <b>جاري تنفيذ:</b> <code>{raw_cmd}</code>...")

        is_sudo = raw_cmd.startswith("sudo ")
        actual_cmd = raw_cmd[5:].strip() if is_sudo else raw_cmd

        if is_sudo:
            res = bot_ssh.execute_sudo_command(actual_cmd)
        else:
            res = bot_ssh.execute_command(raw_cmd)

        out = (res["stdout"] or "").strip()
        err = (res["stderr"] or "").strip()
        disp_path = res.get("display_path") or bot_ssh.get_display_path()

        reply_parts = [
            f"💻 <b>الأمر:</b> <code>{raw_cmd}</code>",
            f"📁 <b>المسار الحالي:</b> <code>{disp_path}</code>"
        ]
        if out:
            reply_parts.append(f"📋 <b>المخرجات:</b>\n<pre>{telebot.formatting.escape_html(out[:3500])}</pre>")
        if err:
            reply_parts.append(f"⚠️ <b>تنبيه / أخطاء:</b>\n<pre>{telebot.formatting.escape_html(err[:1500])}</pre>")
        if not out and not err:
            reply_parts.append("✅ <i>تم التنفيذ بنجاح بدون مخرجات نصية.</i>")

        reply_parts.append(f"🏁 <b>Exit Code:</b> <code>{res['exit_code']}</code>")

        bot.edit_message_text(
            "\n\n".join(reply_parts),
            message.chat.id,
            status_msg.message_id
        )


    # -------------------------------------------------------------
    # Command: /stop
    # -------------------------------------------------------------
    @bot.message_handler(commands=["stop"])
    def cmd_stop(message):
        if not is_user_authorized(message.from_user):
            return

        global active_agent
        if active_agent:
            active_agent.stop()
            active_agent = None
            bot.reply_to(message, "⏹ <b>تم إيقاف مهمة الذكاء الاصطناعي بنجاح.</b>")
        else:
            bot.reply_to(message, "💡 لا توجد أي مهمة نشطة حالياً.")


    # -------------------------------------------------------------
    # Command: /steps [number] (Check or update max agent steps)
    # -------------------------------------------------------------
    @bot.message_handler(commands=["steps"])
    def cmd_steps(message):
        if not is_user_authorized(message.from_user):
            notify_unauthorized_access(message.from_user)
            bot.reply_to(message, "⛔ غير مصرح لك.")
            return

        parts = message.text.split()
        if len(parts) == 1:
            curr = load_settings().get("max_steps", 20)
            bot.reply_to(
                message,
                f"⚙️ <b>الحد الأقصى الحالي للخطوات:</b> <code>{curr} خطوة</code>\n"
                f"<i>(القيمة الافتراضية: 20 خطوة)</i>\n\n"
                f"لتغيير العدد أرسل: <code>/steps &lt;العدد من 5 إلى 100&gt;</code>\n"
                f"مثال: <code>/steps 35</code>"
            )
            return

        try:
            val = int(parts[1])
            if val < 5 or val > 100:
                bot.reply_to(message, "⚠️ يرجى إدخال عدد خطوات بين 5 و 100.")
                return
            save_settings({"max_steps": val})
            bot.reply_to(message, f"✅ <b>تم تحديث الحد الأقصى للخطوات بنجاح إلى:</b> <code>{val} خطوة</code> 🎯")
        except ValueError:
            bot.reply_to(message, "⚠️ صيغة غير صحيحة. مثال: <code>/steps 35</code>")


    # -------------------------------------------------------------
    # Inline Callback Query Handler (Buttons)
    # -------------------------------------------------------------
    @bot.callback_query_handler(func=lambda call: True)
    def handle_callback(call):
        if not is_user_authorized(call.from_user):
            bot.answer_callback_query(call.id, "⛔ غير مصرح لك.", show_alert=True)
            return

        bot.answer_callback_query(call.id)

        if not ensure_ssh_connected():
            bot.send_message(call.message.chat.id, "🔴 <b>السيرفر غير متصل حالياً.</b> يرجى استخدام /connect أولاً.")
            return

        data = call.data

        if data == "btn_docker":
            bot.send_message(call.message.chat.id, "🐳 <b>جاري فحص حاويات Docker...</b>")
            res = bot_ssh.execute_command("docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'")
            if res["stdout"]:
                bot.send_message(call.message.chat.id, f"🐳 <b>قائمة الحاويات:</b>\n<pre>{telebot.formatting.escape_html(res['stdout'][:3800])}</pre>")
            else:
                bot.send_message(call.message.chat.id, f"⚠️ لم يتم العثور على حاويات أو حدث خطأ:\n<code>{res['stderr']}</code>")

        elif data == "btn_resources":
            bot.send_message(call.message.chat.id, "📊 <b>جاري فحص استهلاك الرام والهارد...</b>")
            disk = bot_ssh.execute_command("df -h /")["stdout"]
            mem = bot_ssh.execute_command("free -h")["stdout"]
            uptime = bot_ssh.execute_command("uptime -p")["stdout"]
            msg = (
                f"⏱ <b>وقت تشغيل السيرفر:</b> {uptime}\n\n"
                f"💾 <b>مساحة الهارد:</b>\n<pre>{telebot.formatting.escape_html(disk)}</pre>\n"
                f"🧠 <b>استهلاك الذاكرة (RAM):</b>\n<pre>{telebot.formatting.escape_html(mem)}</pre>"
            )
            bot.send_message(call.message.chat.id, msg)

        elif data == "btn_services":
            bot.send_message(call.message.chat.id, "⚙️ <b>جاري فحص الخدمات...</b>")
            res = bot_ssh.execute_command("systemctl --failed --no-pager")
            out = res["stdout"].strip()
            bot.send_message(call.message.chat.id, f"⚙️ <b>الخدمات المتوقفة أو المعطلة:</b>\n<pre>{telebot.formatting.escape_html(out[:3500])}</pre>")

        elif data == "btn_logs":
            bot.send_message(call.message.chat.id, "📜 <b>جاري قراءة آخر سجلات أخطاء النظام...</b>")
            res = bot_ssh.execute_command("journalctl -p 3 -xb -n 25 --no-pager")
            out = res["stdout"].strip() or "لا توجد أخطاء حرجة مسجلة حديثاً."
            bot.send_message(call.message.chat.id, f"📜 <b>آخر أخطاء النظام:</b>\n<pre>{telebot.formatting.escape_html(out[:3500])}</pre>")

        elif data == "btn_status":
            uptime = bot_ssh.execute_command("uptime")["stdout"].strip()
            containers = bot_ssh.execute_command("docker ps -q | wc -l")["stdout"].strip()
            bot.send_message(
                call.message.chat.id,
                f"🟢 <b>حالة السيرفر:</b>\n"
                f"💻 <code>{bot_ssh.username}@{bot_ssh.hostname}</code>\n"
                f"⏱ <b>Uptime:</b> <code>{uptime}</code>\n"
                f"🐳 <b>الحاويات النشطة:</b> <code>{containers} حاوية</code>",
                reply_markup=build_main_keyboard()
            )

        elif data == "btn_doctor":
            trigger_ai_mission(call.message.chat.id, "قم بعمل فحص شامل للسيرفر: حالة الدوكر، الخدمات، استهلاك الرام والهارد، ولخص أهم المشاكل أو النقاط المطلوبة.")

        elif data == "btn_toggle_search":
            current = is_web_search_enabled(call.message.chat.id)
            set_web_search_enabled(call.message.chat.id, not current)
            now_enabled = is_web_search_enabled(call.message.chat.id)
            state_txt = "مُفعّل ✅" if now_enabled else "مُعطّل ❌"
            bot.answer_callback_query(call.id, f"البحث في الويب أصبح: {state_txt}")
            try:
                bot.edit_message_reply_markup(
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=build_main_keyboard(call.message.chat.id)
                )
            except Exception:
                pass

        elif data == "btn_new_session":
            session_id = f"tg_{call.message.chat.id}"
            reset_session_by_id(session_id)
            bot.send_message(
                call.message.chat.id,
                "🧹 <b>تم بدء جلسة جديدة ومسح ذاكرة المحادثات السابقة بنجاح!</b>\n"
                "الوكيل الآن جاهز لتلقي أي استفسار أو مهمة جديدة.",
                reply_markup=build_main_keyboard(call.message.chat.id)
            )


    # -------------------------------------------------------------
    # Natural Language Text Handler (AI Agent)
    # -------------------------------------------------------------
    @bot.message_handler(func=lambda msg: True, content_types=["text"])
    def handle_natural_language(message):
        if not is_user_authorized(message.from_user):
            notify_unauthorized_access(message.from_user)
            bot.reply_to(message, "⛔ <b>عذراً، هذا البوت خاص وغير مصرح لك باستخدامه نهائياً.</b>")
            return

        if not ensure_ssh_connected():
            bot.reply_to(message, "🔴 <b>السيرفر غير متصل حالياً.</b> يرجى استخدام /connect للاتصال أولاً.")
            return

        goal = message.text.strip()
        if not goal:
            return

        trigger_ai_mission(message.chat.id, goal)


def trigger_ai_mission(chat_id, goal: str):
    """Runs the AI Agent for a given goal in a persistent conversational session and sends live updates to Telegram."""
    global active_agent, bot_ssh

    session_id = f"tg_{chat_id}"
    max_steps = load_settings().get("max_steps", 20)
    agent = get_or_create_agent_session(session_id, bot_ssh, max_steps=max_steps)
    turn_num = agent.get_turn_count() + 1
    session_badge = f"💬 (متابعة المحادثة #{turn_num})" if turn_num > 1 else "🆕 (جلسة جديدة)"
    search_enabled = is_web_search_enabled(chat_id)
    search_badge = " [🌐 بحث الويب مُفعّل]" if search_enabled else ""

    status_msg = bot.send_message(
        chat_id,
        f"🤖 <b>مهمة الذكاء الاصطناعي {session_badge}{search_badge}:</b>\n<i>\"{telebot.formatting.escape_html(goal)}\"</i>\n\n"
        f"🧠 جاري التحليل واسترجاع سياق الجلسة...",
        parse_mode="HTML"
    )

    def run_mission():
        global active_agent
        try:
            active_agent = agent
            active_agent.run_in_background(goal, enable_web_search=search_enabled, max_steps=max_steps)

            last_edit_time = 0
            current_status = "جاري الفحص..."
            completed_steps = []

            while True:
                try:
                    event = active_agent.event_queue.get(timeout=90)
                    etype = event["type"]
                    edata = event["data"]

                    if etype == "thinking":
                        current_status = edata.get("message", "")[:150]
                    elif etype == "search":
                        s_query = edata.get("query", "")
                        s_status = edata.get("status", "")
                        if s_status == "searching":
                            current_status = f"🌐 يبحث في الويب عن: <i>{telebot.formatting.escape_html(s_query[:40])}</i>"
                            completed_steps.append(f"🌐 <code>بحث: {telebot.formatting.escape_html(s_query)}</code>")
                        elif s_status == "done":
                            current_status = f"🌐 وجد {edata.get('count', 0)} نتائج من محرك البحث"
                    elif etype == "command":
                        cmd = edata.get("command", "")
                        completed_steps.append(f"⚙️ <code>{telebot.formatting.escape_html(cmd)}</code>")
                        current_status = f"ينفذ: <code>{telebot.formatting.escape_html(cmd[:40])}</code>"
                    elif etype == "done":
                        final_msg = edata.get("message", "تم إنجاز المهمة بنجاح.")
                        
                        report = (
                            f"✅ <b>تم إنجاز المهمة بنجاح! 🎯</b> {session_badge}\n\n"
                            f"<b>الهدف:</b> <i>{telebot.formatting.escape_html(goal)}</i>\n\n"
                            f"📊 <b>التقرير والنتيجة:</b>\n"
                            f"{telebot.formatting.escape_html(final_msg)}\n"
                        )
                        if completed_steps:
                            report += f"\n📜 <b>الأوامر المنفذة:</b>\n" + "\n".join(completed_steps[-5:])

                        report += f"\n\n💡 <i>المحادثة مستمرة بنفس السياق. لبدء جلسة جديدة أرسل /new</i>"

                        bot.send_message(chat_id, report, reply_markup=build_main_keyboard(chat_id))
                        break

                    elif etype == "error":
                        bot.send_message(chat_id, f"❌ <b>حدث خطأ أثناء التنفيذ:</b>\n<code>{edata.get('message', '')}</code>")
                        break

                    elif etype == "end":
                        break

                    # Update status message at most once every 3 seconds to respect Telegram rate limits
                    now = time.time()
                    if now - last_edit_time > 3.5:
                        try:
                            update_text = (
                                f"🤖 <b>المهمة قيد التنفيذ:</b>\n<i>\"{telebot.formatting.escape_html(goal)}\"</i>\n\n"
                                f"⚡ <b>الحالة:</b> {current_status}\n"
                            )
                            if completed_steps:
                                update_text += "\n" + "\n".join(completed_steps[-3:])

                            bot.edit_message_text(update_text, chat_id, status_msg.message_id)
                            last_edit_time = now
                        except Exception:
                            pass

                except queue.Empty:
                    pass
                except Exception as e:
                    print(f"[Telegram Bot Mission Error] {e}")
                    break

        except Exception as err:
            bot.send_message(chat_id, f"❌ <b>فشل تشغيل الذكاء الاصطناعي:</b>\n<code>{err}</code>")
        finally:
            active_agent = None

    threading.Thread(target=run_mission, daemon=True).start()


def start_bot_background(shared_ssh=None):
    """Starts the telegram bot in a background daemon thread."""
    global bot_ssh
    if shared_ssh:
        bot_ssh = shared_ssh

    if not bot:
        print("[Telegram Bot] Bot is not configured, skipping background start.")
        return None

    def polling_loop():
        print(f"[Telegram Bot] Starting polling for @{ALLOWED_USERNAME}...")
        while True:
            try:
                bot.infinity_polling(timeout=30, long_polling_timeout=25)
            except Exception as e:
                print(f"[Telegram Bot Polling Error] {e}. Retrying in 5 seconds...")
                time.sleep(5)

    thread = threading.Thread(target=polling_loop, daemon=True, name="TelegramBotThread")
    thread.start()
    return thread


if __name__ == "__main__":
    if not bot:
        print("Error: TELEGRAM_BOT_TOKEN is not set.")
    else:
        print("=" * 60)
        print("🤖 AI DevOps Telegram Bot")
        print(f"🔒 Security: Allowed user ONLY: @{ALLOWED_USERNAME}")
        print("=" * 60)
        bot.infinity_polling()
