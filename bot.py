import json
import os
import sys
import time
from datetime import datetime
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests

# Set console encoding to UTF-8 for Windows
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

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
        except Exception as e:
            print(f"⚠️ config.json পড়তে সমস্যা হয়েছে: {e}")
            
    # Environment variables override file config (useful for Render deployment)
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

# Global state
current_link_state = None  # True for ON, False for OFF, None for Unknown
last_check_time = None
last_status_message = "শুরু হয়নি"

def send_telegram_message(text: str):
    token = config.get("BOT_TOKEN", "").strip()
    chat_id = config.get("CHAT_ID", "").strip()
    
    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("❌ Telegram BOT_TOKEN কনফিগার করা হয়নি!")
        return False
        
    if not chat_id or chat_id == "YOUR_TELEGRAM_GROUP_CHAT_ID_HERE":
        print("❌ Telegram CHAT_ID কনফিগার করা হয়নি!")
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
            print(f"📨 [Telegram Sent] মেসেজ সফলভাবে গ্রুপে পাঠানো হয়েছে।")
            return True
        else:
            print(f"❌ [Telegram Error] {res_data.get('description')}")
            return False
    except Exception as e:
        print(f"❌ [Telegram Exception] মেসেজ পাঠাতে ব্যর্থ: {e}")
        return False

def check_link_status():
    """
    Checks if the link is ON or OFF.
    Returns:
        (is_online: bool, reason: str)
    """
    global last_check_time, last_status_message
    last_check_time = datetime.now().strftime("%I:%M:%S %p")
    
    # 1. Primary check via API endpoint (/api/info)
    api_url = config.get("API_URL", "http://skysysx.net/api/info")
    try:
        r = requests.get(api_url, timeout=8)
        if r.status_code == 200:
            data = r.json()
            is_push_locked = bool(data.get("push_locked", False))
            is_api_offline = bool(data.get("api_offline_locked", False))
            webhook_fail = (data.get("webhook_status") == "fail")
            
            is_locked = is_push_locked or is_api_offline or webhook_fail
            
            if is_locked:
                reason_list = []
                if is_api_offline:
                    reason_list.append("Buyer API Offline")
                if webhook_fail:
                    reason_list.append("Webhook Fail")
                if is_push_locked:
                    reason_list.append("Push Locked")
                reason = ", ".join(reason_list) if reason_list else "Locked"
                last_status_message = f"OFF ({reason})"
                return False, reason
            else:
                last_status_message = "ON (Active)"
                return True, "Active"
    except Exception as err:
        pass

    # 2. Fallback check via direct HTML fetch of target URL
    target_url = config.get("TARGET_URL", "http://skysysx.net/e/boss")
    try:
        r = requests.get(target_url, timeout=10)
        content = r.text
        if "Buyer API Offline" in content or "买家 API 已离线" in content or "Submissions are locked" in content:
            last_status_message = "OFF (Buyer API Offline)"
            return False, "Buyer API Offline"
        elif "Input (one per line)" in content or "Endpoint: boss" in content:
            last_status_message = "ON (Active)"
            return True, "Active"
    except Exception as e:
        pass

    return None, "Error connecting to server"

# --- Web Server for 24/7 Hosting (Render & UptimeRobot) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        status_text = "🟢 ON (সক্রিয়)" if current_link_state else "🔴 OFF (বন্ধ)"
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Telegram Link Monitor</title>
            <meta http-equiv="refresh" content="10">
            <style>
                body {{ font-family: Arial, sans-serif; text-align: center; padding-top: 50px; background: #121820; color: #fff; }}
                .card {{ background: #1d2633; display: inline-block; padding: 30px; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.5); }}
                .badge {{ font-size: 24px; font-weight: bold; padding: 10px 20px; border-radius: 8px; margin: 15px 0; display: inline-block; }}
                .on {{ background: #10b981; color: white; }}
                .off {{ background: #ef4444; color: white; }}
            </style>
        </head>
        <body>
            <div class="card">
                <h2>🤖 Telegram Link Monitor Bot</h2>
                <p>Target: <code>{config.get('TARGET_URL')}</code></p>
                <div class="badge {'on' if current_link_state else 'off'}">{status_text}</div>
                <p>Status Detail: <strong>{last_status_message}</strong></p>
                <p>Last Checked: {last_check_time or 'N/A'}</p>
                <p style="color: #94a3b8; font-size: 13px;">Render 24/7 Healthcheck Active ✅</p>
            </div>
        </body>
        </html>
        """
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        # Silence standard HTTP access logging to keep console clean
        return

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"🌐 [Web Server] হেলথ-চেক সার্ভার পোর্ট {port} এ চলছে...")
    server.serve_forever()

# --- Telegram Command Polling (Handles /status, /ping, etc.) ---
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

                    if text.startswith("/status"):
                        state_str = "🟢 <b>চালু (ON)</b>" if current_link_state else "🔴 <b>বন্ধ (OFF)</b>"
                        reply = (
                            f"📊 <b>লিংক স্ট্যাটাস রিপোর্ট</b>\n\n"
                            f"বর্তমান অবস্থা: {state_str}\n"
                            f"বিস্তারিত: {last_status_message}\n"
                            f"সর্বশেষ চেক: {last_check_time}\n"
                            f"লিংক: {config.get('TARGET_URL')}"
                        )
                        requests.post(send_url, json={"chat_id": chat_id, "text": reply, "parse_mode": "HTML"}, timeout=5)

                    elif text.startswith("/ping"):
                        requests.post(send_url, json={"chat_id": chat_id, "text": "🏓 Pong! বট পুরোপুরি সক্রিয় এবং লিংক মনিটর করছে।"}, timeout=5)

                    elif text.startswith("/start") or text.startswith("/help"):
                        help_text = (
                            "👋 <b>লিংক মনিটর বটের স্বাগতম!</b>\n\n"
                            "এই বটটি প্রতি ১০ সেকেন্ড পরপর বায়ারের লিংক মনিটর করে এবং লিংক অন/অফ হওয়ার সাথে সাথে নোটিফিকেশন পাঠায়।\n\n"
                            "কমান্ডসমূহ:\n"
                            "/status - বর্তমান লিংকের অবস্থা জানতে\n"
                            "/ping - বট জীবিত আছে কিনা পরীক্ষা করতে\n"
                            "/help - সাহায্য পেতে"
                        )
                        requests.post(send_url, json={"chat_id": chat_id, "text": help_text, "parse_mode": "HTML"}, timeout=5)
        except Exception:
            pass
        time.sleep(2)

def monitor_loop():
    global current_link_state
    
    interval = config.get("CHECK_INTERVAL", 10)
    target_url = config.get("TARGET_URL", "http://skysysx.net/e/boss")

    # Messages requested by user
    MSG_ON = (
        f"🟢 <b>লিংক চালু রয়েছে! 🔥🚀 সবাই পুরো দমে কাজ করুন।</b>\n\n"
        f"🔗 <b>লিংক:</b> {target_url}"
    )
    MSG_OFF = (
        f"🔴 <b>আজকের মতো লিংক অফ! ⚠️😴 আবার অন হলে জানানো হবে।</b>"
    )

    print("=" * 60)
    print("🚀 টেলিগ্রাম লিংক মনিটর বট চালু হয়েছে!")
    print(f"🎯 টার্গেট লিংক: {target_url}")
    print(f"⏱️ চেক ব্যবধান: প্রতি {interval} সেকেন্ড")
    print("=" * 60)

    # Initial check
    status, reason = check_link_status()
    current_link_state = status
    print(f"[{datetime.now().strftime('%H:%M:%S')}] প্রাথমিক স্ট্যাটাস: {'🟢 ON' if status else '🔴 OFF'} ({reason})")

    while True:
        try:
            status, reason = check_link_status()
            timestamp = datetime.now().strftime("%H:%M:%S")

            if status is not None:
                # If status changed
                if status != current_link_state:
                    if status is True:
                        print(f"[{timestamp}] 🟢 পরিবর্তন সনাক্ত: OFF ➔ ON! অ্যালার্ট পাঠানো হচ্ছে...")
                        send_telegram_message(MSG_ON)
                    else:
                        print(f"[{timestamp}] 🔴 পরিবর্তন সনাক্ত: ON ➔ OFF! অ্যালার্ট পাঠানো হচ্ছে...")
                        send_telegram_message(MSG_OFF)
                    
                    current_link_state = status
                else:
                    # Print heartbeat to console every check
                    stat_icon = "🟢 ON" if status else "🔴 OFF"
                    print(f"[{timestamp}] লিংক চেক: {stat_icon} ({reason})")
            else:
                print(f"[{timestamp}] ⚠️ সার্ভারের সাথে সংযোগ করা যাচ্ছে না ({reason})")

        except Exception as e:
            print(f"⚠️ মনিটরিং এরর: {e}")

        time.sleep(interval)

def main():
    # 1. Start Web Server in background thread (for Render / UptimeRobot)
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    # 2. Start Telegram Command Listener in background thread
    cmd_thread = threading.Thread(target=telegram_command_listener, daemon=True)
    cmd_thread.start()

    # 3. Start Main Monitoring Loop in main thread
    monitor_loop()

if __name__ == "__main__":
    main()
