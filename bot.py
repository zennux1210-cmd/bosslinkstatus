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

def load_config():
    default_config = {
        "BOT_TOKEN": os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_HERE"),
        "CHAT_ID": os.getenv("CHAT_ID", "YOUR_TELEGRAM_GROUP_CHAT_ID_HERE"),
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

# গ্লোবাল স্ট্যাটাস ভেরিয়েবল
current_link_state = None  # True = চালু, False = বন্ধ
last_check_time = None

def send_telegram_message(text: str):
    token = config.get("BOT_TOKEN", "").strip()
    chat_id = config.get("CHAT_ID", "").strip()
    
    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("❌ টেলিগ্রাম বট টোকেন দেওয়া হয়নি!")
        return False
        
    if not chat_id or chat_id == "YOUR_TELEGRAM_GROUP_CHAT_ID_HERE":
        print("❌ টেলিগ্রাম চ্যাট আইডি দেওয়া হয়নি!")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    
    try:
        res = requests.post(url, json=payload, timeout=10)
        res_data = res.json()
        if res_data.get("ok"):
            print(f"[{get_bd_time_str()}] 📨 গ্রুপে মেসেজ পাঠানো হয়েছে।")
            return True
        else:
            print(f"[{get_bd_time_str()}] ❌ টেলিগ্রাম এরর: {res_data.get('description')}")
            return False
    except Exception as e:
        print(f"[{get_bd_time_str()}] ❌ মেসেজ পাঠাতে সমস্যা হয়েছে: {e}")
        return False

def check_link_status():
    """
    লিংক চালু নাকি বন্ধ তা পরীক্ষা করে।
    রিটার্ন করে: True (চালু) অথবা False (বন্ধ)
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

# --- রেন্ডার ২৪/৭ সচল রাখার জন্য ওয়েব পেজ ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        status_text = "🟢 লিংক চালু আছে" if current_link_state else "🔴 লিংক বন্ধ আছে"
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>লিংক মনিটর বট</title>
            <meta http-equiv="refresh" content="10">
            <style>
                body {{ font-family: 'Segoe UI', Arial, sans-serif; text-align: center; padding-top: 50px; background: #0f172a; color: #fff; }}
                .card {{ background: #1e293b; display: inline-block; padding: 35px; border-radius: 16px; box-shadow: 0 10px 25px rgba(0,0,0,0.4); max-width: 450px; }}
                .badge {{ font-size: 22px; font-weight: bold; padding: 12px 24px; border-radius: 10px; margin: 20px 0; display: inline-block; }}
                .on {{ background: #10b981; color: white; }}
                .off {{ background: #ef4444; color: white; }}
                .time {{ color: #94a3b8; font-size: 15px; margin-top: 10px; }}
            </style>
        </head>
        <body>
            <div class="card">
                <h2>🤖 বায়ার লিংক মনিটর</h2>
                <div class="badge {'on' if current_link_state else 'off'}">{status_text}</div>
                <div class="time">সর্বশেষ চেক: <strong>{last_check_time or 'অপেক্ষমান'}</strong></div>
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

# --- ম্যানুয়াল কমান্ড হ্যান্ডলার (/status, /check) ---
def telegram_command_listener():
    token = config.get("BOT_TOKEN", "").strip()
    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        return
        
    offset = 0
    poll_url = f"https://api.telegram.org/bot{token}/getUpdates"
    send_url = f"https://api.telegram.org/bot{token}/sendMessage"

    while True:
        try:
            r = requests.get(poll_url, params={"offset": offset, "timeout": 10}, timeout=15)
            data = r.json()
            if data.get("ok"):
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message")
                    if not msg:
                        continue
                    text = msg.get("text", "").strip()
                    chat = msg.get("chat", {})
                    chat_id = chat.get("id")

                    if not text or not chat_id:
                        continue

                    clean_text = text.lower().split('@')[0].strip()

                    # ম্যানুয়াল স্ট্যাটাস চেক
                    if clean_text in ["/status", "/check", "/link", "status", "check"]:
                        live_status = check_link_status()
                        current_link_state = live_status
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

                    elif clean_text in ["/start", "/help", "help"]:
                        help_text = (
                            "👋 <b>বায়ার লিংক মনিটর বট</b>\n\n"
                            "এই বটটি প্রতি ১০ সেকেন্ড পরপর বায়ারের লিংক স্বয়ংক্রিয়ভাবে পরীক্ষা করে এবং চালু বা বন্ধ হলে নোটিফিকেশন পাঠায়।\n\n"
                            "📌 <b>কমান্ড:</b>\n"
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

    # নোটিফিকেশন মেসেজ
    def get_msg_on():
        return (
            f"🟢 <b>লিংক চালু রয়েছে! 🔥🚀 সবাই পুরো দমে কাজ করুন।</b>\n\n"
            f"🔗 <b>লিংক:</b> {target_url}\n"
            f"⏰ <b>সময়:</b> {get_bd_time_str(include_seconds=False)}"
        )

    def get_msg_off():
        return (
            f"🔴 <b>আজকের মতো লিংক অফ! ⚠️😴 আবার অন হলে জানানো হবে।</b>\n\n"
            f"⏰ <b>সময়:</b> {get_bd_time_str(include_seconds=False)}"
        )

    print("=" * 60)
    print("🚀 টেলিগ্রাম লিংক মনিটর বট চালু হয়েছে!")
    print(f"🎯 টার্গেট লিংক: {target_url}")
    print(f"⏱️ চেক ইন্টারভাল: প্রতি {interval} সেকেন্ড")
    print(f"🇧🇩 বর্তমান বাংলাদেশ সময়: {get_bd_time_str()}")
    print("=" * 60)

    # শুরুর প্রাথমিক চেক
    initial_status = check_link_status()
    current_link_state = initial_status
    initial_text = "🟢 চালু" if initial_status else "🔴 বন্ধ"
    print(f"[{get_bd_time_str()}] প্রাথমিক অবস্থা: {initial_text}")

    while True:
        try:
            status = check_link_status()
            bd_now = get_bd_time_str()

            if status is not None:
                # অবস্থা পরিবর্তিত হলে (বন্ধ থেকে চালু অথবা চালু থেকে বন্ধ)
                if status != current_link_state:
                    if status is True:
                        print(f"[{bd_now}] 🟢 লিংক চালু হয়েছে! গ্রুপে মেসেজ পাঠানো হচ্ছে...")
                        send_telegram_message(get_msg_on())
                    else:
                        print(f"[{bd_now}] 🔴 লিংক বন্ধ হয়েছে! গ্রুপে মেসেজ পাঠানো হচ্ছে...")
                        send_telegram_message(get_msg_off())
                    
                    current_link_state = status
                else:
                    stat_icon = "🟢 চালু" if status else "🔴 বন্ধ"
                    print(f"[{bd_now}] লিংক চেক: {stat_icon}")
            else:
                print(f"[{bd_now}] ⚠️ সার্ভার রেসপন্স করছে না")

        except Exception as e:
            print(f"[{get_bd_time_str()}] ⚠️ এরর: {e}")

        time.sleep(interval)

def main():
    # ১. ব্যাকগ্রাউন্ড ওয়েব সার্ভার (রেন্ডারের জন্য)
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    # ২. টেলিগ্রাম কমান্ড হ্যান্ডলার
    cmd_thread = threading.Thread(target=telegram_command_listener, daemon=True)
    cmd_thread.start()

    # ৩. মূল মনিটরিং লুপ
    monitor_loop()

if __name__ == "__main__":
    main()
