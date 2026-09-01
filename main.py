import os
import re
import threading
import time
import requests
from datetime import datetime
from groq import Groq
from flask import Flask
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- FLASK SERVER ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Radio Contest Bot (Optimized & Local) is RUNNING!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- CONFIGURATION ---
raw_keys = os.environ.get("GROQ_API_KEYS", "")
GROQ_KEYS = [k.strip() for k in raw_keys.split(",") if k.strip()]

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

STATIONS = {
    "Plus 102.6": "https://eco.onestreaming.com/proxy/plusradio/stream",
    "Cosmoradio 95.1": "https://eco.onestreaming.com/proxy/cosmoradio/stream",
    "89 Rainbow": "https://stream.radiojar.com/083wqknmsuhvv"
}

KEYWORDS = ["διαγωνισμ", "δωρ", "κερδ", "στειλ", "sms", "viber", "κληρωσ", "προσκλησ", "τηλεφων", "μηνυμ", "παρτ", "καλεσ"]

key_index = 0
key_lock = threading.Lock()

def get_groq_client():
    global key_index
    if not GROQ_KEYS:
        return None
    with key_lock:
        current_key = GROQ_KEYS[key_index]
        key_index = (key_index + 1) % len(GROQ_KEYS)
    return Groq(api_key=current_key)

def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Σφάλμα Telegram: {e}")

def highlight_keywords(text, keywords):
    """ Υπογραμμίζει (με bold) ολόκληρες τις λέξεις που περιέχουν τα keywords """
    words = text.split()
    highlighted_words = []
    
    for word in words:
        clean_word = word.lower()
        matched = False
        for kw in keywords:
            if kw in clean_word:
                matched = True
                break
        if matched:
            highlighted_words.append(f"*{word}*")
        else:
            highlighted_words.append(word)
            
    return " ".join(highlighted_words)

def transcribe_audio_with_retry(file_path):
    if not GROQ_KEYS:
        return ""

    whisper_prompt = "Ραδιοφωνικός διαγωνισμός, δώρα, SMS, Viber, τηλέφωνο, κλήρωση, Plus Radio, Cosmoradio, στείλτε μήνυμα."

    for _ in range(len(GROQ_KEYS)):
        client = get_groq_client()
        try:
            with open(file_path, "rb") as file:
                transcription = client.audio.transcriptions.create(
                    file=(os.path.basename(file_path), file.read()),
                    model="whisper-large-v3",
                    response_format="text",
                    language="el",
                    prompt=whisper_prompt
                )
                text = transcription.strip()
                # Καθαρισμός των ψεύτικων υποτίτλων AUTHORWAVE
                text = text.replace("Υπότιτλοι AUTHORWAVE", "").replace("AUTHORWAVE", "").strip()
                return text
        except Exception as e:
            print(f"Groq Key Error: {e}. Δοκιμή με επόμενο Key...")
            continue
            
    return ""

def monitor_station(station_name, stream_url, chunk_duration=30):
    print(f"[{station_name}] Εκκίνηση παρακολούθησης...")
    previous_text = ""

    while True:
        temp_filename = f"temp_{station_name.replace(' ', '_')}.mp3"
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(stream_url, stream=True, timeout=8, headers=headers, verify=False)
            audio_bytes = b""
            start_time = time.time()
            
            for chunk in response.iter_content(chunk_size=4096):
                audio_bytes += chunk
                if time.time() - start_time >= chunk_duration:
                    break
            
            with open(temp_filename, "wb") as f:
                f.write(audio_bytes)

            current_text = transcribe_audio_with_retry(temp_filename)
            timestamp = datetime.now().strftime('%H:%M:%S')

            if current_text:
                print(f"💓 [{timestamp}] [{station_name}] Ακούστηκε: \"{current_text[:60]}...\"")
                
                full_context = f"{previous_text} {current_text}".strip()
                found_keywords = [kw for kw in KEYWORDS if kw in current_text.lower()]
                
                if found_keywords:
                    # Υπογράμμιση (bolding) των keywords μέσα στο πλήρες κείμενο
                    formatted_text = highlight_keywords(full_context, found_keywords)
                    
                    alert_msg = (
                        f"🚨 *ΕΝΤΟΠΙΣΤΗΚΕ ΔΙΑΓΩΝΙΣΜΟΣ!* 🚨\n\n"
                        f"📻 *Σταθμός:* {station_name}\n"
                        f"🔑 *Keywords:* {', '.join(found_keywords)}\n\n"
                        f"💬 *Πλήρες Κείμενο:*\n_{formatted_text}_"
                    )
                    send_telegram_alert(alert_msg)

                previous_text = current_text
            else:
                previous_text = ""
                print(f"💓 [{timestamp}] [{station_name}] Μουσική / Ησυχία")

        except Exception as e:
            print(f"[{station_name}] Σφάλμα: {e}")
            time.sleep(3)
        finally:
            if os.path.exists(temp_filename):
                os.remove(temp_filename)

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    time.sleep(2)
    send_telegram_alert("🚀 *Radio Bot Updated!*")

    for name, url in STATIONS.items():
        t = threading.Thread(target=monitor_station, args=(name, url), daemon=True)
        t.start()

    while True:
        time.sleep(1)
