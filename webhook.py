from flask import Flask, request, jsonify
import requests
import os
import json
from datetime import datetime

app = Flask(__name__)

# ===================== CONFIGURAȚIE (se setează în mediul de deploy) =====================
API_KEY = os.getenv('BEDS24_API_KEY')          # obligatoriu
PROP_KEY = os.getenv('BEDS24_PROP_KEY')        # obligatoriu
DORM_ROOM_ID = int(os.getenv('DORM_ROOM_ID', '0'))  # ID-ul dormitorului DORM A din Beds24
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', 'schimbati_acesta_cu_un_string_lung_si_aleator')  # securitate

def log(message):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")

@app.route('/beds24-webhook', methods=['POST'])
def beds24_webhook():
    # Securitate simplă (secret în URL sau header)
    secret = request.args.get('secret') or request.headers.get('X-Webhook-Secret')
    if secret != WEBHOOK_SECRET:
        log("Tentativă acces neautorizat")
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    log(f"Webhook primit: {json.dumps(data, indent=2)[:500]}...")  # log limitat

    # Beds24 V2 trimite booking-ul complet în body
    booking = data if isinstance(data, dict) else data.get('booking', data)

    book_id = booking.get('bookId') or booking.get('id')
    if not book_id:
        return jsonify({"status": "ignored"}), 200

    # Detectare Airbnb group booking
    source = (booking.get('channel', '') or booking.get('source', '') or '').lower()
    num_guests = int(booking.get('numAdult', 0)) + int(booking.get('numChild', 0)) + int(booking.get('numInfant', 0))
    room_id = booking.get('roomId')

    already_processed = any(item.get('code') == 'AUTO_GROUP_SPLIT_DONE' 
                            for item in booking.get('infoItems', []))

    if ('airbnb' in source and 
        num_guests > 1 and 
        str(room_id) == str(DORM_ROOM_ID) and 
        not already_processed):

        log(f"DETECTAT group booking Airbnb #{book_id} ({num_guests} oaspeți) → se face split automat")
        split_airbnb_group(booking)
    else:
        log(f"Ignorat booking #{book_id} (nu este group Airbnb)")

    return jsonify({"status": "processed"}), 200

def split_airbnb_group(master_booking):
    book_id = master_booking['bookId'] if 'bookId' in master_booking else master_booking['id']
    total_guests = int(master_booking.get('numAdult', 0)) + int(master_booking.get('numChild', 0))
    main_guest = master_booking.get('guestName', 'Guest')
    date_from = master_booking['dateFrom']
    date_to = master_booking['dateTo']

    child_bookings = []
    for i in range(1, total_guests):  # primul rămâne master
        child = {
            "masterId": book_id,
            "roomId": DORM_ROOM_ID,
            "numAdult": 1,
            "numChild": 0,
            "dateFrom": date_from,
            "dateTo": date_to,
            "guestName": f"{main_guest} - Pat {i+1}",
            "status": "1",           # confirmed
            "assignBooking": True    # alocare automată pe pat
        }
        child_bookings.append(child)

    # Creare child bookings
    payload = {
        "authentication": {"apiKey": API_KEY, "propKey": PROP_KEY},
        "array": child_bookings
    }

    r = requests.post("https://api.beds24.com/json/setBooking", json=payload)
    result = r.json()

    if result.get('success'):
        # Marchează master-ul ca procesat
        mark = {
            "authentication": {"apiKey": API_KEY, "propKey": PROP_KEY},
            "bookId": book_id,
            "infoItems": [{"code": "AUTO_GROUP_SPLIT_DONE", "text": "Yes"}]
        }
        requests.post("https://api.beds24.com/json/setBooking", json=mark)
        log(f"✓ Split reușit pentru booking {book_id} – {total_guests} paturi alocate automat!")
    else:
        log(f"✗ Eroare split: {result.get('error')}")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)