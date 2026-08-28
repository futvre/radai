import os
import json
import threading
import time
import requests
from google import genai
from groq import Groq
from flask import Flask
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- FLASK SERVER (Για να κρατάει το Render το Web Service ενεργό) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Radio Contest Bot is Running 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- ΡΥΘΜΙΣΕΙΣ API KEYS ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

STATIONS = {
    "Plus 102.6": "https://eco.onestreaming.com/proxy/plusradio/stream",
    "Cosmoradio 95.1": "https://eco.onestreaming.com/proxy/cosmoradio/stream"
}

# Αρχικοποίηση πελατών API
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

KEYWORDS = ["διαγωνισμ", "δώρο", "κέρδισε", "κερδίστε", "στείλτε", "sms", "viber", "πρόσκληση"]

def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Σφάλμα: Δεν έχουν οριστεί τα Telegram Keys.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Σφάλμα Telegram: {e}")

def verify_contest(text, station_name):
    if not gemini_client:
        return {"is_active_contest": False}
        
    prompt = f"""
    Εξέτασε αν το παρακάτω κείμενο από τον ραδιοφωνικό σταθμό '{station_name}' ανακοινώνει έναν ενεργό διαγωνισμό αυτή τη στιγμή.
    Κείμενο: "{text}"
    Επίστρεψε ΑΠΟΚΛΕΙΣΤΙΚΑ JSON:
    {{
        "is_active_contest": boolean,
        "action_type": "SMS" | "VIBER" | "PHONE" | "FORM" | "UNKNOWN",
        "instructions": "string",
        "confidence": float
    }}
    """
    try:
        response = gemini_client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt,
            config={'response_mime_type': 'application/json'}
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"Σφάλμα Gemini: {e}")
        return {"is_active_contest": False}

def monitor_station(station_name, stream_url, chunk_duration=12):
    print(f"[{station_name}] Εκκίνηση παρακολούθησης...")
    while True:
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(stream_url, stream=True, timeout=10, headers=headers, verify=False)
            audio_bytes = b""
            start_time = time.time()
            for chunk in response.iter_content(chunk_size=4096):
                audio_bytes += chunk
                if time.time() - start_time >= chunk_duration:
                    break
            
            temp_filename = f"temp_{station_name.replace(' ', '_')}.mp3"
            with open(temp_filename, "wb") as f:
                f.write(audio_bytes)

            if groq_client:
                with open(temp_filename, "rb") as file:
                    transcription = groq_client.audio.transcriptions.create(
                        file=(temp_filename, file.read()),
                        model="whisper-large-v3",
                        response_format="text",
                        language="el"
                    )
                text = transcription.strip()
            else:
                text = ""

            if text:
                text_lower = text.lower()
                found_keywords = [kw for kw in KEYWORDS if kw in text_lower]
                
                if found_keywords:
                    verification = verify_contest(text, station_name)
                    if verification.get("is_active_contest") and verification.get("confidence", 0) > 0.7:
                        alert_msg = (
                            f"🚨 *ΕΝΤΟΠΙΣΤΗΚΕ ΔΙΑΓΩΝΙΣΜΟΣ!* 🚨\n\n"
                            f"📻 *Σταθμός:* {station_name}\n"
                            f"📲 *Τύπος:* {verification.get('action_type')}\n"
                            f"📝 *Οδηγίες:* {verification.get('instructions')}\n"
                            f"💬 *Κείμενο:* _{text}_"
                        )
                        send_telegram_alert(alert_msg)
        except Exception as e:
            print(f"[{station_name}] Σφάλμα: {e}")
            time.sleep(5)

if __name__ == "__main__":
    send_telegram_alert("🤖 Το Radio Bot ξεκίνησε και παρακολουθεί κανονικά!")

    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    for name, url in STATIONS.items():
        t = threading.Thread(target=monitor_station, args=(name, url))
        t.daemon = True
        t.start()

    while True:
        time.sleep(1)
