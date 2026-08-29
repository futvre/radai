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

# --- FLASK SERVER ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Radio Contest Bot is Running 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- API KEYS ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

STATIONS = {
    "Plus 102.6": "https://eco.onestreaming.com/proxy/plusradio/stream",
    "Cosmoradio 95.1": "https://eco.onestreaming.com/proxy/cosmoradio/stream"
}

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

def transcribe_audio(file_path):
    text = ""
    # 1. Δοκιμή με Groq Whisper
    if groq_client:
        try:
            with open(file_path, "rb") as file:
                transcription = groq_client.audio.transcriptions.create(
                    file=(os.path.basename(file_path), file.read()),
                    model="whisper-large-v3",
                    response_format="text",
                    language="el"
                )
                text = transcription.strip()
                if text:
                    return text
        except Exception as e:
            print(f"Groq Error/Limit, αλλαγή σε Gemini: {e}")

    # 2. Fallback σε Gemini 3.6 Flash αν εξαντληθεί το Groq (429)
    if gemini_client:
        try:
            uploaded_file = gemini_client.files.upload(file=file_path)
            response = gemini_client.models.generate_content(
                model='gemini-3.6-flash',  # <-- ΕΝΗΜΕΡΩΜΕΝΟ ΜΟΝΤΕΛΟ
                contents=['Απομαγνητοφώνησε ακριβώς τον ελληνικό ήχο:', uploaded_file]
            )
            text = response.text.strip() if response.text else ""
            gemini_client.files.delete(name=uploaded_file.name)
        except Exception as e:
            print(f"Gemini Transcription Error: {e}")

    return text


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
            model='gemini-3.6-flash',  # <-- ΕΝΗΜΕΡΩΜΕΝΟ ΜΟΝΤΕΛΟ
            contents=prompt,
            config={'response_mime_type': 'application/json'}
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"Σφάλμα Gemini Verification: {e}")
        return {"is_active_contest": True, "action_type": "UNKNOWN", "instructions": "Εντοπίστηκε λέξη-κλειδί"}

        
def monitor_station(station_name, stream_url, chunk_duration=35):
    print(f"[{station_name}] Εκκίνηση παρακολούθησης...")
    while True:
        temp_filename = f"temp_{station_name.replace(' ', '_')}.mp3"
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(stream_url, stream=True, timeout=10, headers=headers, verify=False)
            audio_bytes = b""
            start_time = time.time()
            
            for chunk in response.iter_content(chunk_size=4096):
                audio_bytes += chunk
                if time.time() - start_time >= chunk_duration:
                    break
            
            with open(temp_filename, "wb") as f:
                f.write(audio_bytes)

            # Απομαγνητοφώνηση με Groq / Gemini Fallback
            text = transcribe_audio(temp_filename)

            if text:
                print(f"💓 [{timestamp}] [{station_name}] Ακούστηκε: \"{text[:70]}...\"")
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
        finally:
            # Διαγραφή του τοπικού mp3 για να μην γεμίζει ο δίσκος
            if os.path.exists(temp_filename):
                os.remove(temp_filename)

if __name__ == "__main__":
    #send_telegram_alert("🤖 Το Radio Bot ξεκίνησε και παρακολουθεί κανονικά!")

    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    for name, url in STATIONS.items():
        t = threading.Thread(target=monitor_station, args=(name, url))
        t.daemon = True
        t.start()

    while True:
        time.sleep(1)
