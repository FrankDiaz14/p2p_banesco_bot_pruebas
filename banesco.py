# Archivo: banesco.py
from playwright.sync_api import sync_playwright

def revisar_banesco():
    with sync_playwright() as p:
        # Aquí inyectamos los datos del proxy venezolano (tipo Airtek)
        browser = p.chromium.launch(
            proxy={
                "server": "http://ip_del_proxy_venezolano:puerto",
                "username": "tu_usuario_proxy",
                "password": "tu_password_proxy"
            },
            headless=True # Para que corra oculto en el servidor
        )
        
        page = browser.new_page()
        page.goto("https://www.banesco.com")
        
        # --- Aquí irá el código para poner el usuario, clave y leer el saldo ---
        print("Entrando a Banesco con éxito usando IP de Venezuela...")
        
        # Cerramos el navegador al terminar
        browser.close()