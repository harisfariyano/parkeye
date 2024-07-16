import requests
import base64

# Ganti dengan kredensial Vonage API Anda
VONAGE_API_KEY = 'c5a8dd17'
VONAGE_API_SECRET = 'RZYgoE91xyGjh23v'
VONAGE_WHATSAPP_NUMBER = '14157386102'  # Nomor WhatsApp yang terdaftar di Vonage

def send_whatsapp_message(to_number, message):
    url = "https://messages-sandbox.nexmo.com/v1/messages"
    
    # Membuat header otorisasi Basic dengan base64 encoding
    auth_string = f"{VONAGE_API_KEY}:{VONAGE_API_SECRET}"
    b64_auth_string = base64.b64encode(auth_string.encode()).decode()
    
    headers = {
        'Authorization': f'Basic {b64_auth_string}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    payload = {
        "from": VONAGE_WHATSAPP_NUMBER,
        "to": to_number,
        "message_type": "text",
        "text": message,
        "channel": "whatsapp"
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()  # Raise HTTPError for bad responses
        print(f"WhatsApp Gateway Response: {response.json()}")  # Logging
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Exception when sending WhatsApp message: {e}")  # Logging
        return {"error": str(e)}
