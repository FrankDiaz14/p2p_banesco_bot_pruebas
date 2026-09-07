import requests

TOKEN = 8912144303:AAG05PmeCVHlOcLhWqXSrLJLY5VjStSoWRI
CHAT_ID = "6818104416"

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
payload = {
    "chat_id": CHAT_ID,
    "text": "¡Conexión exitosa! El bot de P2P ya puede hablarte."
}

print("Enviando mensaje...")
respuesta = requests.post(url, json=payload)
print(f"Estado: {respuesta.status_code}")