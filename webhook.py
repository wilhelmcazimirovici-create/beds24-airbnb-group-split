from flask import Flask, request, jsonify
import requests
import os
from datetime import datetime

app = Flask(__name__)

# ===================== CONFIGURAȚIE (toate se setează în Render) =====================
API_KEY = os.getenv('BEDS24_API_KEY')
PROP_KEY = os.getenv('BEDS24_PROP_KEY')
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', 'schimbati_acesta_cu_un_string_lung')

# <<< NOU: ID-urile camerelor se pun ca string separat prin virgulă >>>
# Exemplu: 82581,82582,82583,82584,82585,82586,82587,82588,82589,82590,82591,82592
DORM_ROOM_IDS_STR = os.getenv('DORM_ROOM_IDS', '')
DORM_ROOM_IDS = [int(x.strip()) for x in DORM_ROOM_IDS_STR.split(',') if x.strip().isdigit()]

def log(message):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")

def get_booking_details(book_id):
    payload = {
        "authentication": {"apiKey": API_KEY, "propKey": PROP_KEY},
        "bookId": book_id,
        "includeInfoItems": True
    }
    r = requests.post("https://api.beds24.com/json/getBookings", json=payload)
    data = r.json()
    return data.get('bookings', [None])[0]

def set_info_code(book_id, code, text):
    payload = {
        "authentication": {"apiKey": API_KEY, "propKey": PROP_KEY},
        "bookId": book_id,
        "infoItems": [{"code": code, "text": text}]
    }
    requests.post("https://api.beds24.com/json/setBooking", json=payload)

@app.route('/beds24-webhook', methods=['POST'])
def beds24_webhook():
    secret = request.args.get('secret') or request.headers.get('X-Webhook-Secret')
    if secret != WEBHOOK_SECRET:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    booking = data if isinstance(data, dict) else data.get('booking', data)

    book_id = booking.get('bookId') or booking.get('id')
    if not book_id:
        return jsonify({"status": "ignored"}), 200

    source = (booking.get('channel', '') or booking.get('source', '') or '').lower()
    num_guests = int(booking.get('numAdult', 0)) + int(booking.get('numChild', 0)) + int(booking.get('numInfant', 0))
    room_id = str(booking.get('roomId', ''))

    already_processed = any(item.get('code') == 'AUTO_GROUP_SPLIT_DONE' 
                            for item in booking.get('infoItems', []))

    if ('airbnb' in source and num_guests > 1 and 
        room_id in [str(x) for x in DORM_ROOM_IDS] and not already_processed):

        log(f"DETECTAT group booking Airbnb #{book_id} ({num_guests} oaspeți) → split + alocare paturi")
        split_airbnb_group(booking)
    else:
        log(f"Ignorat booking #{book_id}")

    return jsonify({"status": "processed"}), 200

def split_airbnb_group(master_booking):
    book_id = master_booking.get('bookId') or master_booking.get('id')
    total_guests = int(master_booking.get('numAdult', 0)) + int(master_booking.get('numChild', 0))
    main_guest = master_booking.get('guestName', 'Guest')
    date_from = master_booking['dateFrom']
    date_to = master_booking['dateTo']
    room_id = master_booking.get('roomId')

    for i in range(1, total_guests):
        child = {
            "masterId": book_id,
            "roomId": room_id,
            "numAdult": 1,
            "numChild": 0,
            "dateFrom": date_from,
            "dateTo": date_to,
            "guestName": f"{main_guest} - Pat {i+1}",
            "status": "1",
            "assignBooking": True
        }

        payload = {
            "authentication": {"apiKey": API_KEY, "propKey": PROP_KEY},
            "array": [child]
        }
        r = requests.post("https://api.beds24.com/json/setBooking", json=payload)
        result = r.json()

        if result.get('success'):
            new_book_id = result.get('bookId') or result.get('bookings', [{}])[0].get('bookId')
            if new_book_id:
                details = get_booking_details(new_book_id)
                if details:
                    unit_name = details.get('unitName') or f"Pat {i+1}"
                    set_info_code(new_book_id, "ASSIGNED_BED", unit_name)
                    log(f"   ✓ Oaspete {i+1} → {unit_name} (salvat în ASSIGNED_BED)")

    set_info_code(book_id, "AUTO_GROUP_SPLIT_DONE", "Yes")
    log(f"✓ Split complet pentru booking {book_id} – {total_guests} oaspeți cu paturi afișate")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
