import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests

# Windows কনসোলের জন্য UTF-8 নিশ্চিত করা
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# বাংলাদেশ টাইমজোন (UTC+6)
BD_TZ = timezone(timedelta(hours=6))

def get_bd_time():
    """বাংলাদেশ সময় রিটার্ন করে"""
    return datetime.now(BD_TZ)

def get_bd_time_str(include_seconds=True):
    """বাংলাদেশ সময়ের সুন্দর ফরম্যাট রিটার্ন করে"""
    fmt = "%I:%M:%S %p" if include_seconds else "%I:%M %p"
    return get_bd_time().strftime(fmt)

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
CHATS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "registered_chats.json")

def load_config():
    default_config = {
        "BOT_TOKEN": os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_HERE"),
        "CHAT_ID": os.getenv("CHAT_ID", "-1003560158316"),
        "CHECK_INTERVAL": int(os.getenv("CHECK_INTERVAL", "10")),
        "TARGET_URL": os.getenv("TARGET_URL", "http://skysysx.net/e/boss"),
        "API_URL": os.getenv("API_URL", "http://skysysx.net/api/info")
    }
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                file_cfg = json.load(f)
                default_config.update(file_cfg)
        except Exception:
            pass
            
    # Render বা সার্ভারের এনভায়রনমেন্ট ভেরিয়েবল
    if os.getenv("BOT_TOKEN"):
        default_config["BOT_TOKEN"] = os.getenv("BOT_TOKEN")
    if os.getenv("CHAT_ID"):
        default_config["CHAT_ID"] = os.getenv("CHAT_ID")
    if os.getenv("CHECK_INTERVAL"):
        default_config["CHECK_INTERVAL"] = int(os.getenv("CHECK_INTERVAL"))
    if os.getenv("TARGET_URL"):
        default_config["TARGET_URL"] = os.getenv("TARGET_URL")
    if os.getenv("API_URL"):
        default_config["API_URL"] = os.getenv("API_URL")

    return default_config

config = load_config()

# নিবন্ধিত চ্যাট/গ্রুপ আইডি সংরক্ষণ ও লোড করার ব্যবস্থা
registered_chats = set()

def sanitize_chat_id(cid):
    cid = str(cid).strip()
    if cid.startswith("100") and len(cid) >= 12:
        cid = "-" + cid
    return cid

def load_registered_chats():
    global registered_chats
    cfg_chat = config.get("CHAT_ID", "").strip()
    if cfg_chat and cfg_chat != "YOUR_TELEGRAM_GROUP_CHAT_ID_HERE":
        registered_chats.add(sanitize_chat_id(cfg_chat))
        
    if os.path.exists(CHATS_FILE):
        try:
            with open(CHATS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for cid in data:
                    clean_id = sanitize_chat_id(cid)
                    if clean_id:
                        registered_chats.add(clean_id)
        except Exception:
            pass
    # Remove any un-sanitized IDs if sanitized version exists
    clean_set = set()
    for c in registered_chats:
        clean_set.add(sanitize_chat_id(c))
    registered_chats = clean_set

def save_registered_chat(chat_id):
    global registered_chats
    chat_id_str = sanitize_chat_id(chat_id)
    if chat_id_str and chat_id_str not in registered_chats:
        registered_chats.add(chat_id_str)
        try:
            with open(CHATS_FILE, "w", encoding="utf-8") as f:
                json.dump(list(registered_chats), f)
            print(f"[{get_bd_time_str()}] 📌 নতুন গ্রুপ/চ্যাট আইডি নিবন্ধিত হয়েছে: {chat_id_str}")
        except Exception:
            pass

load_registered_chats()

# গ্লোবাল স্ট্যাটাস ও লগ ভেরিয়েবল
current_link_state = None  # True = চালু, False = বন্ধ
last_check_time = None
last_delivery_status = "এখনো কোনো মেসেজ পাঠানো হয়নি"
recent_logs = []

def add_log(msg):
    global recent_logs
    entry = f"[{get_bd_time_str()}] {msg}"
    recent_logs.append(entry)
    if len(recent_logs) > 25:
        recent_logs.pop(0)
    print(entry)

def send_telegram_message(text: str) -> bool:
    """
    নিবন্ধিত সকল গ্রুপ ও চ্যাটে মেসেজ পাঠায়।
    কমপক্ষে একটি চ্যাটে সফল হলে True রিটার্ন করে।
    """
    global last_delivery_status
    token = config.get("BOT_TOKEN", "").strip()
    
    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        msg = "❌ টেলিগ্রাম বট টোকেন (BOT_TOKEN) দেওয়া হয়নি!"
        last_delivery_status = msg
        add_log(msg)
        return False

    targets = set(registered_chats)
    cfg_chat = config.get("CHAT_ID", "").strip()
    if cfg_chat and cfg_chat != "YOUR_TELEGRAM_GROUP_CHAT_ID_HERE":
        targets.add(cfg_chat)

    if not targets:
        msg = "⚠️ কোনো গ্রুপ বা চ্যাট আইডি নিবন্ধিত নেই! গ্রুপে /setgroup বা /status লিখুন।"
        last_delivery_status = msg
        add_log(msg)
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    any_success = False
    errors = []

    for target_id in targets:
        payload = {
            "chat_id": target_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }
        try:
            res = requests.post(url, json=payload, timeout=10)
            res_data = res.json()
            if res_data.get("ok"):
                any_success = True
                add_log(f"📨 মেসেজ সফলভাবে পাঠানো হয়েছে (চ্যাট: {target_id})")
            else:
                desc = res_data.get('description', 'Unknown error')
                err = f"চ্যাট {target_id}-এ পাঠাতে ব্যর্থ: {desc}"
                errors.append(err)
                add_log(f"❌ {err}")
        except Exception as e:
            err = f"চ্যাট {target_id}-এ কানেকশন এরর: {e}"
            errors.append(err)
            add_log(f"❌ {err}")

    if any_success:
        last_delivery_status = f"✅ সর্বশেষ মেসেজ সফলভাবে পাঠানো হয়েছে ({get_bd_time_str()})"
        return True
    else:
        last_delivery_status = f"❌ মেসেজ পাঠানো ব্যর্থ: {'; '.join(errors)}"
        return False

def check_link_status():
    """
    লিংক চালু নাকি বন্ধ তা পরীক্ষা করে।
    রিটার্ন করে: True (চালু) অথবা False (বন্ধ) অথবা None (কানেকশন সমস্যা)
    """
    global last_check_time
    last_check_time = get_bd_time_str(include_seconds=True)
    
    # ১. বায়ার ব্যাকএন্ড এপিআই চেক
    api_url = config.get("API_URL", "http://skysysx.net/api/info")
    try:
        r = requests.get(api_url, timeout=8)
        if r.status_code == 200:
            data = r.json()
            is_push_locked = bool(data.get("push_locked", False))
            is_api_offline = bool(data.get("api_offline_locked", False))
            webhook_fail = (data.get("webhook_status") == "fail")
            
            # কোনো একটি লক থাকলে বা অফলাইন থাকলে বন্ধ
            if is_push_locked or is_api_offline or webhook_fail:
                return False
            else:
                return True
    except Exception:
        pass

    # ২. সরাসরি পেজ থেকে বিকল্প চেক
    target_url = config.get("TARGET_URL", "http://skysysx.net/e/boss")
    try:
        r = requests.get(target_url, timeout=10)
        content = r.text
        if "Buyer API Offline" in content or "买家 API 已离线" in content or "Submissions are locked" in content:
            return False
        elif "Input (one per line)" in content or "Endpoint: boss" in content:
            return True
    except Exception:
        pass

    return None

# --- রেন্ডার ২৪/৭ সচল রাখার জন্য ওয়েব ড্যাশবোর্ড ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        
        status_text = "🟢 লিংক চালু আছে" if current_link_state else "🔴 লিংক বন্ধ আছে"
        badge_class = "on" if current_link_state else "off"
        chats_display = ", ".join(registered_chats) if registered_chats else "কোনো গ্রুপ যুক্ত নেই (গ্রুপে /setgroup লিখুন)"
        
        log_html = "".join([f"<li>{item}</li>" for item in reversed(recent_logs[-12:])])
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>বায়ার লিংক মনিটর ড্যাশবোর্ড</title>
            <meta http-equiv="refresh" content="10">
            <style>
                body {{ font-family: 'Segoe UI', Arial, sans-serif; text-align: center; padding: 30px 10px; background: #0f172a; color: #fff; }}
                .card {{ background: #1e293b; display: inline-block; padding: 30px; border-radius: 16px; box-shadow: 0 10px 25px rgba(0,0,0,0.4); max-width: 580px; text-align: left; }}
                .center {{ text-align: center; }}
                .badge {{ font-size: 22px; font-weight: bold; padding: 12px 24px; border-radius: 10px; margin: 15px 0; display: inline-block; }}
                .on {{ background: #10b981; color: white; }}
                .off {{ background: #ef4444; color: white; }}
                .info-box {{ background: #0f172a; padding: 12px 16px; border-radius: 8px; margin: 10px 0; font-size: 14px; line-height: 1.6; word-break: break-all; }}
                .logs {{ background: #090d16; padding: 12px; border-radius: 8px; font-family: monospace; font-size: 12px; max-height: 180px; overflow-y: auto; color: #38bdf8; }}
                ul {{ margin: 0; padding-left: 20px; }}
                li {{ margin-bottom: 4px; }}
            </style>
        </head>
        <body>
            <div class="card">
                <div class="center">
                    <h2 style="margin: 0;">🤖 বায়ার লিংক মনিটর বট</h2>
                    <div class="badge {badge_class}">{status_text}</div>
                </div>
                
                <div class="info-box">
                    <div>🎯 <b>টার্গেট লিংক:</b> <code>{config.get('TARGET_URL')}</code></div>
                    <div>⏰ <b>সর্বশেষ চেক:</b> <strong>{last_check_time or 'অপেক্ষমান'}</strong></div>
                    <div>👥 <b>নিবন্ধিত গ্রুপ/চ্যাট আইডি:</b> <code>{chats_display}</code></div>
                    <div>📨 <b>ডেলিভারি স্ট্যাটাস:</b> {last_delivery_status}</div>
                </div>

                <h4 style="margin: 15px 0 8px 0; color: #94a3b8;">📋 লাইভ অ্যাক্টিভিটি লগ:</h4>
                <div class="logs">
                    <ul>{log_html or '<li>অপেক্ষা করা হচ্ছে...</li>'}</ul>
                </div>
            </div>
        </body>
        </html>
        """
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        return

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# --- টেলিগ্রাম কমান্ড ও অটো-গ্রুপ ডিটেকশন হ্যান্ডলার ---
def telegram_command_listener():
    token = config.get("BOT_TOKEN", "").strip()
    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        return
        
    offset = 0
    poll_url = f"https://api.telegram.org/bot{token}/getUpdates"
    send_url = f"https://api.telegram.org/bot{token}/sendMessage"

    add_log("📡 টেলিগ্রাম কমান্ড লিসেনার সক্রিয় হয়েছে...")

    while True:
        try:
            r = requests.get(poll_url, params={"offset": offset, "timeout": 10}, timeout=15)
            data = r.json()
            if data.get("ok"):
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    
                    # কোনো গ্রুপে বট অ্যাড হলে বা মেসেজ আসলে অটো চ্যাট আইডি সেভ করা
                    msg = update.get("message") or update.get("channel_post") or update.get("my_chat_member")
                    if not msg:
                        continue
                        
                    chat = msg.get("chat", {})
                    chat_id = chat.get("id")
                    
                    if chat_id:
                        # অটো রেজিস্টার করে নেওয়া
                        save_registered_chat(chat_id)

                    text = msg.get("text", "").strip()
                    if not text or not chat_id:
                        continue

                    clean_text = text.lower().split('@')[0].strip()

                    # গ্রুপ সেট করার কমান্ড
                    if clean_text in ["/setgroup", "/register", "/start"]:
                        save_registered_chat(chat_id)
                        reply = (
                            "✅ <b>এই গ্রুপটি সফলভাবে নিবন্ধিত হয়েছে!</b>\n\n"
                            "এখন থেকে বায়ারের লিংক চালু বা বন্ধ হওয়া মাত্রই এই গ্রুপে স্বয়ংক্রিয় নোটিফিকেশন আসবে।"
                        )
                        requests.post(send_url, json={"chat_id": chat_id, "text": reply, "parse_mode": "HTML"}, timeout=5)
                        
                        # রেজিস্টার হওয়ার সাথে সাথে লিংক যদি অন থাকে, তৎক্ষণাৎ অ্যালার্ট দেওয়া
                        live_status = check_link_status()
                        if live_status is True:
                            msg_on = (
                                f"🟢 <b>লিংক চালু রয়েছে! 🔥🚀</b>\n"
                                f"সবাই পুরো দমে কাজ করতে পারেন।\n\n"
                                f"🔗 <b>লিংক:</b> {config.get('TARGET_URL')}\n"
                                f"⏰ <b>সময়:</b> {get_bd_time_str(include_seconds=False)}"
                            )
                            requests.post(send_url, json={"chat_id": chat_id, "text": msg_on, "parse_mode": "HTML"}, timeout=5)

                    # ম্যানুয়াল স্ট্যাটাস চেক (/status, /check)
                    elif clean_text in ["/status", "/check", "/link", "status", "check"]:
                        #注意: লাইভ স্ট্যাটাস চেক করে শুধু উত্তর দিবে, মূল মনিটরের বর্তমান স্টেট পরিবর্তন করবে না!
                        live_status = check_link_status()
                        time_str = get_bd_time_str(include_seconds=False)

                        if live_status is True:
                            reply = (
                                f"🟢 <b>লিংক চালু রয়েছে! 🔥🚀</b>\n"
                                f"সবাই পুরো দমে কাজ করতে পারেন।\n\n"
                                f"🔗 <b>লিংক:</b> {config.get('TARGET_URL')}\n"
                                f"⏰ <b>সময়:</b> {time_str}"
                            )
                        else:
                            reply = (
                                f"🔴 <b>আজকের মতো লিংক অফ! ⚠️😴</b>\n"
                                f"আবার অন হলে গ্রুপে জানানো হবে।\n\n"
                                f"⏰ <b>সময়:</b> {time_str}"
                            )
                        requests.post(send_url, json={"chat_id": chat_id, "text": reply, "parse_mode": "HTML"}, timeout=5)

                    elif clean_text in ["/ping", "ping"]:
                        requests.post(send_url, json={"chat_id": chat_id, "text": "⚡ বট সক্রিয় আছে এবং লিংক মনিটর করছে।"}, timeout=5)

                    elif clean_text in ["/help", "help"]:
                        help_text = (
                            "👋 <b>বায়ার লিংক মনিটর বট</b>\n\n"
                            "📌 <b>কমান্ডসমূহ:</b>\n"
                            "• <code>/setgroup</code> - এই গ্রুপে অটো নোটিফিকেশন সেট করতে\n"
                            "• <code>/status</code> - লিংকের বর্তমান অবস্থা জানতে\n"
                            "• <code>/ping</code> - বট সচল আছে কিনা দেখতে"
                        )
                        requests.post(send_url, json={"chat_id": chat_id, "text": help_text, "parse_mode": "HTML"}, timeout=5)
        except Exception:
            pass
        time.sleep(2)

def monitor_loop():
    global current_link_state
    
    interval = config.get("CHECK_INTERVAL", 10)
    target_url = config.get("TARGET_URL", "http://skysysx.net/e/boss")

    def get_msg_on():
        return (
            f"🟢 <b>লিংক চালু রয়েছে! 🔥🚀</b>\n"
            f"সবাই পুরো দমে কাজ করতে পারেন।\n\n"
            f"🔗 <b>লিংক:</b> {target_url}\n"
            f"⏰ <b>সময়:</b> {get_bd_time_str(include_seconds=False)}"
        )

    def get_msg_off():
        return (
            f"🔴 <b>আজকের মতো লিংক অফ! ⚠️😴</b>\n"
            f"আবার অন হলে গ্রুপে জানানো হবে।\n\n"
            f"⏰ <b>সময়:</b> {get_bd_time_str(include_seconds=False)}"
        )

    add_log(f"🚀 মনিটরিং শুরু: প্রতি {interval} সেকেন্ড পরপর লিংক চেক হবে")

    # প্রাথমিক অবস্থা ও বট চালু হওয়ামাত্রই গ্রুপে তাৎক্ষণিক মেসেজ পাঠানো
    initial_status = check_link_status()
    initial_text = "🟢 চালু" if initial_status else "🔴 বন্ধ"
    add_log(f"প্রাথমিক অবস্থা: {initial_text}")

    startup_msg = get_msg_on() if initial_status is True else get_msg_off()
    add_log(f"বট চালু হয়েছে! গ্রুপে অটোমেটিক মেসেজ পাঠানো হচ্ছে...")
    if send_telegram_message(startup_msg):
        current_link_state = initial_status
    else:
        current_link_state = None  # পাঠানো না গেলে যাতে লুপে পুনরায় পাঠানোর চেষ্টা করে

    while True:
        try:
            status = check_link_status()

            if status is not None:
                # অবস্থা পরিবর্তিত হলে (বন্ধ থেকে চালু অথবা চালু থেকে বন্ধ)
                if status != current_link_state:
                    if status is True:
                        add_log("🟢 লিংক অন হয়েছে! গ্রুপে মেসেজ পাঠানো হচ্ছে...")
                        success = send_telegram_message(get_msg_on())
                    else:
                        add_log("🔴 লিংক অফ হয়েছে! গ্রুপে মেসেজ পাঠানো হচ্ছে...")
                        success = send_telegram_message(get_msg_off())
                    
                    # শুধুমাত্র মেসেজ পাঠানো সফল হলে স্ট্যাটাস আপডেট হবে, যাতে ব্যর্থ হলে মিস না হয়
                    if success:
                        current_link_state = status
                    else:
                        add_log("⚠️ নোটিফিকেশন পাঠাতে ব্যর্থ হওয়ায় পুনরায় চেষ্টা করা হবে...")
                else:
                    # অবস্থা একই রয়েছে
                    pass
            else:
                add_log("⚠️ বায়ার সার্ভারের সাথে সংযোগ করা যায়নি")

        except Exception as e:
            add_log(f"⚠️ মনিটরিং এরর: {e}")

        time.sleep(interval)

def main():
    # ১. ব্যাকগ্রাউন্ড ওয়েব সার্ভার (রেন্ডারের জন্য)
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    # ২. টেলিগ্রাম কমান্ড হ্যান্ডলার ও অটো-গ্রুপ ক্যাচার
    cmd_thread = threading.Thread(target=telegram_command_listener, daemon=True)
    cmd_thread.start()

    # ৩. মূল মনিটরিং লুপ
    monitor_loop()

if __name__ == "__main__":
    main()
