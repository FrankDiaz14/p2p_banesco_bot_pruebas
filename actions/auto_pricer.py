"""
Módulo de Auto-Ajuste de Precios P2P (Auto-Pricer / Sniper).
(VERSIÓN V21 ULTRASMART: AUTO-DETECTA BUY/SELL + TRADUCTOR DE COMAS VENEZOLANO)
"""
import asyncio
import hashlib
import hmac
import json
import logging
import time
import os
import math
from typing import Dict, Any, List
import aiohttp

try:
    from integrations.telegram_notifier import enviar_alerta_telegram
except ImportError:
    async def enviar_alerta_telegram(msg: str):
        logging.info(f"TELEGRAM: {msg}")

logger = logging.getLogger(__name__)

class P2PAutoPricer:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.binance.com"
        self.bapi_search_url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"

    def _get_signature(self, query_string: str) -> str:
        return hmac.new(self.api_secret.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()

    async def obtener_balance_fondos_usdt(self, session: aiohttp.ClientSession) -> float:
        timestamp = int(time.time() * 1000)
        query_string = f"asset=USDT&timestamp={timestamp}"
        signature = self._get_signature(query_string)
        url = f"{self.base_url}/sapi/v3/asset/getUserAsset?{query_string}&signature={signature}"
        headers = {"X-MBX-APIKEY": self.api_key}
        try:
            async with session.post(url, headers=headers, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    if isinstance(data, list):
                        for item in data:
                            if item.get("asset") == "USDT": return float(item.get("free", 0.0))
        except: pass
        return -1.0

    async def obtener_mi_anuncio_sapi(self, session: aiohttp.ClientSession, ad_number: str) -> dict:
        timestamp = int(time.time() * 1000)
        query_string = f"timestamp={timestamp}"
        signature = self._get_signature(query_string)
        url = f"{self.base_url}/sapi/v1/c2c/ads/listWithPagination?{query_string}&signature={signature}"
        headers = {"X-MBX-APIKEY": self.api_key, "Content-Type": "application/json"}
        payload = {"page": 1, "rows": 50}
        try:
            async with session.post(url, headers=headers, json=payload, timeout=10) as response:
                if response.status == 200:
                    res = await response.json()
                    for ad in res.get("data", []):
                        if str(ad.get("advNo")) == str(ad_number):
                            return ad
        except Exception as e:
            logger.error(f"Error consultando anuncio privado en SAPI: {e}")
        return {}

    async def obtener_libro_ordenes(self, session: aiohttp.ClientSession, trade_type: str, trans_amount: float = 0.0, fiat: str = "VES", asset: str = "USDT", pay_types: Any = None) -> List[Dict]:
        search_type = "SELL" if trade_type.upper() == "BUY" else "BUY"
        payload = {"page": 1, "rows": 20, "asset": asset, "tradeType": search_type, "fiat": fiat, "publisherType": "merchant"}
        
        if trans_amount > 0:
            if trans_amount.is_integer(): payload["transAmount"] = str(int(trans_amount))
            else: payload["transAmount"] = str(trans_amount)
        
        final_pay_types = []
        if pay_types:
            if isinstance(pay_types, str):
                clean_str = pay_types.strip().lower()
                if clean_str not in ["todos", "all", "cualquiera", "[]", "", "any", "none"]:
                    if pay_types.startswith("["):
                        try: final_pay_types = json.loads(pay_types.replace("'", '"'))
                        except: final_pay_types = [pay_types.strip("[]'\" ")]
                    else: final_pay_types = [pay_types]
            elif isinstance(pay_types, list):
                if len(pay_types) > 0 and str(pay_types[0]).strip().lower() not in ["todos", "all", "cualquiera"]:
                    final_pay_types = pay_types
        if final_pay_types: payload["payTypes"] = final_pay_types

        headers_disfraz = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Content-Type": "application/json"
        }
        try:
            async with session.post(self.bapi_search_url, json=payload, headers=headers_disfraz, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("data", [])
        except Exception as e: logger.error(f"Error escaneando tabla: {e}")
        return []

    async def actualizar_precio_anuncio(self, session: aiohttp.ClientSession, ad_number: str, nuevo_precio: float, trade_type: str, cookie: str = "", csrf: str = "", limite_min: float = 0.0, limite_max: float = 0.0, cantidad_usdt: float = 0.0) -> bool:
        timestamp = int(time.time() * 1000)
        precio_float = float(f"{nuevo_precio:.3f}") 
        query_string = f"timestamp={timestamp}"
        signature = self._get_signature(query_string)
        url_sapi = f"{self.base_url}/sapi/v1/c2c/ads/update?{query_string}&signature={signature}"
        headers_sapi = {"X-MBX-APIKEY": self.api_key, "Content-Type": "application/json;charset=utf-8", "clientType": "WEB"}
        payload_json = {"advNo": str(ad_number), "asset": "USDT", "fiatUnit": "VES", "tradeType": trade_type.upper(), "price": precio_float, "updateMode": "selective"}

        if limite_min > 0: payload_json["minSingleTransAmount"] = float(f"{limite_min:.2f}")
        if limite_max > 0:
            if cantidad_usdt > 0:
                safe_max = min(limite_max, float(precio_float * cantidad_usdt))
                if safe_max < limite_min: safe_max = limite_min
                payload_json["maxSingleTransAmount"] = math.floor(safe_max * 100) / 100.0
            else: payload_json["maxSingleTransAmount"] = float(f"{limite_max:.2f}")

        sapi_exitoso = False
        try:
            async with session.post(url_sapi, headers=headers_sapi, json=payload_json, timeout=10) as response:
                if response.status == 200:
                    resp_json = await response.json()
                    if resp_json.get("success") or str(resp_json.get("code")) == "000000":
                        logger.info("✅ SAPI: Precio actualizado exitosamente.")
                        sapi_exitoso = True
                        return True
                    else: logger.warning(f"⚠️ SAPI falló: {resp_json.get('message')}")
        except Exception as e: logger.error(f"⚠️ Error SAPI: {e}")

        if not sapi_exitoso and cookie and csrf:
            url_bapi = "https://p2p.binance.com/bapi/c2c/v1/private/c2c/adv/update-price"
            headers_bapi = {"cookie": cookie, "csrftoken": csrf, "clienttype": "web", "content-type": "application/json"}
            payload_bapi = {"advNo": str(ad_number), "price": str(precio_float)}
            try:
                async with session.post(url_bapi, headers=headers_bapi, json=payload_bapi, timeout=10) as response_bapi:
                    if response_bapi.status == 200:
                        data = await response_bapi.json()
                        if data.get("success") or str(data.get("code")) == "000000": return True
            except Exception as e_bapi: pass
        return False

async def ejecutar_ajuste_mercado(config_estrategia: dict, estado_bot: dict):
    try:
        creds = estado_bot.get("credenciales", {})
        api_key = creds.get("binance_api_key", "")
        api_secret = creds.get("binance_api_secret", "")
        cookie = creds.get("binance_cookie", "")
        csrf = creds.get("binance_csrf", "")

        if not api_key or not api_secret: return

        pricer = P2PAutoPricer(api_key, api_secret)
        ad_number = config_estrategia.get("ad_number")
        
        if not ad_number:
            logger.error("❌ El motor Sniper no recibió el ID del anuncio. Revisa main.py.")
            return

        # 🔥 TRADUCTOR NUMÉRICO: Convierte "50000,00" a 50000.0 sin romper Python 🔥
        def safe_float(valor, default=0.0):
            if valor is None or str(valor).strip() == "": return default
            v = str(valor).strip()
            if "," in v and "." in v:
                if v.rfind(",") > v.rfind("."): v = v.replace(".", "").replace(",", ".")
                else: v = v.replace(",", "")
            elif "," in v: v = v.replace(",", ".")
            try: return float(v)
            except: return default

        precio_actual_bot = safe_float(config_estrategia.get("precio_actual", 0.0))
        filtro_minimo_bs = safe_float(config_estrategia.get("volumen_minimo", config_estrategia.get("monto_simulacion", 30000.0)))
        limite_techo = safe_float(config_estrategia.get("precio_maximo", config_estrategia.get("freno_techo", 999.0))) 
        limite_suelo = safe_float(config_estrategia.get("precio_minimo", config_estrategia.get("freno_suelo", 0.0)))   
        posicion_objetivo = int(safe_float(config_estrategia.get("posicion_objetivo", config_estrategia.get("posicion_tabla", 1))))
        
        pay_types_filtrados = config_estrategia.get("pay_types", config_estrategia.get("banco", []))
        if isinstance(pay_types_filtrados, str): pay_types_filtrados = [pay_types_filtrados]

        margen_victoria = safe_float(config_estrategia.get("margen_victoria", config_estrategia.get("margen_mejora", 0.01)))
        tope_salto = safe_float(config_estrategia.get("tope_salto", config_estrategia.get("freno_salto", 0.0)))

        limite_min_bs = safe_float(config_estrategia.get("limite_min_bs", 0.0))
        limite_max_bs = safe_float(config_estrategia.get("limite_max_bs", 0.0))
        cantidad_usdt_raw = str(config_estrategia.get("cantidad_usdt", "MAX")).strip().upper()

        async with aiohttp.ClientSession() as session:
            
            # 🔥 1. DETECTAR EL TIPO DE ANUNCIO REAL DESDE BINANCE 🔥
            mi_ad_info = await pricer.obtener_mi_anuncio_sapi(session, ad_number)
            if not mi_ad_info:
                logger.warning(f"⚠️ Sniper: No se encontró el anuncio {ad_number} en Binance. ¿Está cerrado?")
                return
            
            trade_type = str(mi_ad_info.get("tradeType", "BUY")).upper()
            
            # 🔥 2. LEER COMPETIDORES 🔥
            competidores = await pricer.obtener_libro_ordenes(session, trade_type, trans_amount=filtro_minimo_bs, pay_types=pay_types_filtrados)
            if not competidores: return

            precios_crudos = []
            mi_nickname = config_estrategia.get("mi_nickname", "").strip().lower()

            for comp in competidores:
                if str(comp.get("adv", {}).get("advNo")) == str(ad_number): continue
                if mi_nickname and comp.get("advertiser", {}).get("nickName", "").strip().lower() == mi_nickname: continue
                precios_crudos.append(float(comp.get("adv", {}).get("price", 0.0)))

            cantidad_usdt_float = float(mi_ad_info.get("surplusAmount", mi_ad_info.get("tradableQuantity", 0.0)))
            if cantidad_usdt_raw not in ["", "0", "MAX"]:
                try: cantidad_usdt_float = float(cantidad_usdt_raw.replace(",", "."))
                except: pass

            if not precios_crudos: return

            precios_unicos = list(set(precios_crudos))
            if trade_type == "BUY": precios_unicos.sort(reverse=True) 
            else: precios_unicos.sort() 

            precios_saneados = []
            encontro_peloton = False
            
            for idx in range(len(precios_unicos)):
                candidato = precios_unicos[idx]
                if tope_salto > 0.0 and not encontro_peloton and idx < len(precios_unicos) - 1:
                    precio_siguiente = precios_unicos[idx + 1]
                    if trade_type == "BUY" and (candidato - precio_siguiente) > tope_salto: continue
                    if trade_type == "SELL" and (precio_siguiente - candidato) > tope_salto: continue
                    encontro_peloton = True
                precios_saneados.append(candidato)

            if not precios_saneados: precios_saneados = precios_unicos

            indice_rival_real = min(posicion_objetivo - 1, len(precios_saneados) - 1)
            competidor_objetivo = precios_saneados[indice_rival_real]

            nuevo_precio = precio_actual_bot
            necesita_ajuste = False

            if trade_type == "BUY":
                precio_ideal = competidor_objetivo + margen_victoria
                if indice_rival_real > 0 and precio_ideal >= precios_saneados[indice_rival_real - 1]:
                    precio_ideal = precios_saneados[indice_rival_real - 1] - 0.001
                if abs(precio_actual_bot - precio_ideal) > 0.0005: 
                    nuevo_precio = precio_ideal
                    necesita_ajuste = True
                if nuevo_precio > limite_techo:
                    nuevo_precio = limite_techo
                    necesita_ajuste = abs(precio_actual_bot - limite_techo) > 0.0005

            elif trade_type == "SELL":
                precio_ideal = competidor_objetivo - margen_victoria
                if indice_rival_real > 0 and precio_ideal <= precios_saneados[indice_rival_real - 1]:
                    precio_ideal = precios_saneados[indice_rival_real - 1] + 0.001
                if abs(precio_actual_bot - precio_ideal) > 0.0005:
                    nuevo_precio = precio_ideal
                    necesita_ajuste = True
                if nuevo_precio < limite_suelo:
                    nuevo_precio = limite_suelo
                    necesita_ajuste = abs(precio_actual_bot - limite_suelo) > 0.0005

            limites_modificados = False
            last_qty = float(config_estrategia.get("last_qty", 0.0))
            last_min = float(config_estrategia.get("last_min", 0.0))
            last_max = float(config_estrategia.get("last_max", 0.0))

            if cantidad_usdt_float > 0 and abs(last_qty - cantidad_usdt_float) > 0.1: limites_modificados = True
            if limite_min_bs > 0 and abs(last_min - limite_min_bs) > 0.1: limites_modificados = True
            if limite_max_bs > 0 and abs(last_max - limite_max_bs) > 0.1: limites_modificados = True

            if necesita_ajuste or limites_modificados:
                exito = await pricer.actualizar_precio_anuncio(session, ad_number, nuevo_precio, trade_type, cookie, csrf, limite_min_bs, limite_max_bs, cantidad_usdt_float)

                if exito:
                    try:
                        if os.path.exists("data/estado_bot.json"):
                            with open("data/estado_bot.json", "r", encoding="utf-8") as f: estado_fresco = json.load(f)
                            if "config_auto_pricer" not in estado_fresco: estado_fresco["config_auto_pricer"] = {}
                            estado_fresco["config_auto_pricer"]["precio_actual"] = float(f"{nuevo_precio:.3f}")
                            
                            if "estrategias_sniper" not in estado_fresco: estado_fresco["estrategias_sniper"] = {}
                            if ad_number not in estado_fresco["estrategias_sniper"]: estado_fresco["estrategias_sniper"][ad_number] = {}
                            estado_fresco["estrategias_sniper"][ad_number]["precio_actual"] = float(f"{nuevo_precio:.3f}")
                            estado_fresco["estrategias_sniper"][ad_number]["last_qty"] = float(cantidad_usdt_float)
                            estado_fresco["estrategias_sniper"][ad_number]["last_min"] = float(limite_min_bs)
                            estado_fresco["estrategias_sniper"][ad_number]["last_max"] = float(limite_max_bs)

                            with open("data/estado_bot_tmp.json", "w", encoding="utf-8") as f: json.dump(estado_fresco, f, ensure_ascii=False, indent=4)
                            os.replace("data/estado_bot_tmp.json", "data/estado_bot.json")
                    except Exception as e_save: logger.error(f"Fallo guardado: {e_save}")
    except Exception as e:
        logger.error(f"🚨 Error crítico: {e}")
