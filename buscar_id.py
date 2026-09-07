import requests

print("=== BUSCADOR DE CHAT ID DE TELEGRAM ===")
token = input("Pega tu Token aquí (y presiona Enter): ").strip()

url = f"https://api.telegram.org/bot{token}/getUpdates"

print("\nConectando con Telegram...")
respuesta = requests.get(url)
datos = respuesta.json()

if not datos.get("ok"):
    print(f"\n[ERROR 401] Telegram dice: {datos.get('description')}")
    print("Esto significa que el Token que pegaste no es válido o fue revocado.")
else:
    resultados = datos.get("result", [])
    if not resultados:
        print("\n[CASI LISTO] El Token es correcto, pero el bot no tiene mensajes.")
        print("Ve a Telegram, escríbele la palabra 'Hola' a tu bot, y vuelve a correr este programa.")
    else:
        try:
            chat_id = resultados[-1]["message"]["chat"]["id"]
            print(f"\n¡ÉXITO TOTAL! Tu Chat ID es: {chat_id}")
            print("Copia ese número y ponlo en tu archivo .env")
        except KeyError:
            print("\nEl bot recibió una actualización, pero no fue un mensaje directo.")
            print("Escríbele 'Hola' normalmente en el chat y vuelve a intentar.")