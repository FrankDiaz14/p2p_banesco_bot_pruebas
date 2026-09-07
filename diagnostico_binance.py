import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from dotenv import load_dotenv

def diagnosticar_orden():
    print("=== INICIANDO LECTURA CRUDA DE BINANCE ===")
    load_dotenv()
    api_key = os.getenv("BINANCE_API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET")

    if not api_key or not api_secret:
        print("❌ Faltan las API Keys en el archivo .env")
        return

    base_url = "https://api.binance.com"
    endpoint = "/sapi/v1/c2c/orderMatch/listUserOrderHistory"
    
    params = {
        "tradeType": "BUY",
        "timestamp": int(time.time() * 1000)
    }
    
    query_string = urlencode(params)
    signature = hmac.new(api_secret.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
    
    url = f"{base_url}{endpoint}?{query_string}&signature={signature}"
    headers = {"X-MBX-APIKEY": api_key}
    
    try:
        response = requests.get(url, headers=headers)
        datos = response.json()
        
        ordenes = datos.get('data', [])
        
        # Filtramos para buscar órdenes pendientes (puedes quitar el if si no sale nada)
        pendientes = [o for o in ordenes if o.get('orderStatus') == 'PENDING']
        
        if not pendientes:
            print("No se encontraron órdenes PENDING. Imprimiendo la última orden registrada para analizar:")
            if ordenes:
                pendientes = [ordenes[0]]
            else:
                print("No hay historial de órdenes.")
                return

        for orden in pendientes:
            print("\n-------------------------------------------------")
            print(f"👤 Contraparte: {orden.get('counterPartNickName')}")
            print(f"💵 Monto: {orden.get('amount')} {orden.get('fiat')}")
            print("\n🔍 DATOS DE PAGO CRUDOS (ESTO ES LO QUE NECESITAMOS VER):")
            
            # Aquí imprimimos TODO lo que Binance manda sobre los métodos de pago
            metodos = orden.get('payMethods', [])
            for i, metodo in enumerate(metodos):
                print(f"\n[Método {i+1}]:")
                for clave, valor in metodo.items():
                    print(f"  {clave}: {valor}")
                    
    except Exception as e:
        print(f"Error de conexión: {e}")

if __name__ == "__main__":
    diagnosticar_orden()