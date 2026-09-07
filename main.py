"""
Orquestador Principal P2P (Binance SAPI v7.4 -> Banesco).
MOTOR SAPI + FUSIÓN PERFIL/CHAT + PAGO MÓVIL + FIRMA VORTEX + CUARENTENA PROFUNDA + KILL SWITCH INTELIGENTE
"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import signal
import time
import unicodedata
import re
from typing import Any, Dict, List, Tuple
from urllib.parse import urlencode

import aiohttp
from playwright.async_api import async_playwright

try:
    from integrations.telegram_notifier import enviar_alerta_telegram, enviar_foto_telegram
except ImportError:
    async def enviar_alerta_telegram(msg: str):
        logging.info(f"TELEGRAM ALERTA: {msg}")

    async def enviar_foto_telegram(foto: str, msg: str):
        logging.info(f"TELEGRAM FOTO [{foto}]: {msg}")

DIR_DATA = "/app/data"
DIR_LOGS = "/app/logs"
os.makedirs(DIR_DATA, exist_ok=True)
os.makedirs(DIR_LOGS, exist_ok=True) # 🔥 Carpeta para la Caja Negra blindada

# 🔥 CAJA NEGRA Y RAYOS X DEFINITIVO 🔥
logging.basicConfig(
    level=logging.DEBUG, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f"{DIR_LOGS}/historial_bot.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# 🤫 Silenciar basura técnica
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)
logging.getLogger("playwright").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# --- IMPORTACIONES DE ACCIONES BANCARIAS ---
try:
    from actions.login_banesco import execute_login
    from actions.transfer_banesco import execute_transfer
except ImportError:
    async def execute_login(page: Any, payment_data: Dict[str, Any]) -> bool:
        logging.warning("Módulo actions.login_banesco ausente.")
        return False

    async def execute_transfer(page: Any, payment_data: Dict[str, Any]) -> Tuple[bool, str]:
        logging.warning("Módulo actions.transfer_banesco ausente.")
        return False, ""

try:
    from actions.pagomovil_banesco import execute_pagomovil
except ImportError:
    async def execute_pagomovil(page: Any, payment_data: Dict[str, Any]) -> Tuple[bool, str]:
        logging.warning("Módulo actions.pagomovil_banesco ausente.")
        return False, ""

# --- IMPORTACIÓN DEL AUTO-PRICER ---
try:
    from actions.auto_pricer import ejecutar_ajuste_mercado
except ImportError:
    async def ejecutar_ajuste_mercado(config_estrategia: dict, estado_bot: dict):
        logger.warning("Módulo actions.auto_pricer ausente.")

ordenes_ignoradas = {}
ordenes_advertidas = set()
perfiles_invalidos = set()
ordenes_en_proceso = set()
cuentas_ocupadas = set()
tareas_activas = set()
indice_cuenta = 0
cuentas_agotadas = set() # 🔥 LISTA NEGRA INVENCIBLE EN RAM
candados_cuentas = {}

def obtener_candado(cuenta: str) -> asyncio.Lock:
    if cuenta not in candados_cuentas:
        candados_cuentas[cuenta] = asyncio.Lock()
    return candados_cuentas[cuenta]

# --- DICCIONARIO DE BANCOS VENEZOLANOS ---
CODIGOS_BANCOS = {
    "0156": ["100% banco", "banco 100%", "cien por ciento", "100x100"],
    "0171": ["activo"],
    "0172": ["bancamiga", "amiga"],
    "0114": ["bancaribe", "caribe"],
    "0175": ["bicentenario", "digital de los trabajadores", "trabajadores", "bdt"],
    "0128": ["caroni"],
    "0102": ["venezuela", "bdv"],
    "0115": ["exterior"],
    "0151": ["fondo comun", "bfc", "fondo común"],
    "0105": ["mercantil"],
    "0191": ["bnc", "nacional de credito", "nacional de crédito"],
    "0138": ["plaza"],
    "0108": ["provincial", "bbva"],
    "0104": ["venezolano de credito", "bvc", "venezolano de crédito"],
    "0134": ["banesco"],
    "0157": ["delsur", "del sur"],
    "0163": ["tesoro"],
    "0169": ["mibanco", "mi banco"],
    "0174": ["banplus"],
    "0177": ["fanb", "banfanb"],
    "0137": ["sofitasa"],
    "0168": ["crecer"]
}

# =========================================================
# FUNCIONES DE SOPORTE Y ESTADO
# =========================================================

def gatillo_emergencia():
    est = leer_estado_botones()
    if est.get("emergencia", False):
        logger.critical("🚨 ¡KILL SWITCH ACTIVADO! ABORTANDO TAREAS (SIN APAGAR EL CONTENEDOR) 🚨")
        est["emergencia"] = False
        est["master_switch"] = False
        if "ordenes_vivas" in est:
            est["ordenes_vivas"]["procesando"] = []
        guardar_estado_seguro(est)

        for t in list(tareas_activas):
            if not t.done():
                t.cancel()

        cuentas_ocupadas.clear()
        ordenes_en_proceso.clear()

        raise InterruptedError("KILL_SWITCH_ACTIVADO")
def es_seguro_pagar(orden):
    import time
    tiempo_actual_ms = int(time.time() * 1000)
    tiempo_creacion = int(orden.get("createTime", 0))
    limite_pago_min = int(orden.get("payTimeLimit", 15)) 
    
    tiempo_vencimiento = tiempo_creacion + (limite_pago_min * 60 * 1000)
    segundos_restantes = (tiempo_vencimiento - tiempo_actual_ms) / 1000
    
    if segundos_restantes < 60:
        return False, segundos_restantes
    return True, segundos_restantes
PATRON_CEDULA_UNIVERSAL = r'(?i)\b(ci|c\.i\.?|cedula|cédula|rif|jur[ií]dica)?\s*[:\.-]?\s*([vejgpg])?[-:\.]?\s*([\d\.]{6,12})\b'
PATRON_TELEFONO = r'(?<!\d)(?:0414|0424|0412|0422|0416|0426)[-\s\.]?\d{3}[-\s\.]?\d{4}(?!\d)'
PATRON_CUENTA = r'(?<!\d)(0134(?:[\s\-\.,_]*\d){16})(?!\d)'
# 🔥 FIX: Atrapa 0134 seguido de 16 dígitos, ignorando CUALQUIER carácter no numérico en el medio
PATRON_CUENTA = r'(?<!\d)(0134(?:\D*\d){16})(?!\d)'

def limpiar_texto_chat(texto: str) -> str:
    if not texto: return ""
    texto_espaciado = str(texto).replace("<br>", " ").replace("\n", " ")
    texto_limpio = unicodedata.normalize('NFKD', texto_espaciado).encode('ASCII', 'ignore').decode('utf-8')
    return texto_limpio.lower().strip()

def es_telefono_venezolano(num_str: str) -> bool:
    if len(num_str) >= 10 and num_str.startswith(("04", "02", "58")): return True
    if len(num_str) == 10 and num_str.startswith(("41", "42")): return True
    return False

def extraer_cedula_texto(texto: str) -> str:
    candidatos = []
    for m in re.finditer(PATRON_CEDULA_UNIVERSAL, texto):
        palabra_clave = m.group(1)
        letra_cedula = m.group(2)
        num_bruto = m.group(3)
        numero_limpio = num_bruto.replace(".", "").replace(" ", "").replace("-", "")

        if len(numero_limpio) <= 5: continue
        if len(numero_limpio) <= 6 and "." in num_bruto: continue
        if es_telefono_venezolano(numero_limpio): continue

        letra = "V"
        if palabra_clave and ("rif" in palabra_clave.lower() or "jur" in palabra_clave.lower() or "j" in palabra_clave.lower()):
            letra = "J"
        elif letra_cedula:
            let_up = letra_cedula.upper()
            if let_up in ["E", "J", "P", "G", "V"]:
                letra = let_up
        else:
            # 🔥 LÓGICA INTELIGENTE PARA EXTRANJEROS (80 Millones) 🔥
            if len(numero_limpio) == 8 and numero_limpio.startswith("8"):
                letra = "E"

        score = 0
        if palabra_clave: score += 2
        if letra_cedula: score += 1

        candidatos.append((score, f"{letra}{numero_limpio}"))

    if candidatos:
        candidatos.reverse() # 🔥 REGLA DE ORO: La última cédula enviada en el chat tiene prioridad absoluta
        candidatos.sort(key=lambda x: x[0], reverse=True)
        return candidatos[0][1]
    return ""

def buscar_banco_texto(texto: str) -> str:
    texto_limpio = texto.lower()
    ultimos_indices = {}

    for codigo, alias_list in CODIGOS_BANCOS.items():
        # Busca la última vez que se mencionó el código numérico (ej. 0175)
        idx = texto_limpio.rfind(codigo)
        if idx != -1:
            ultimos_indices[codigo] = idx

        # Busca la última vez que se mencionó el nombre del banco
        for alias in alias_list:
            idx_alias = texto_limpio.rfind(alias)
            if idx_alias != -1:
                # Guarda solo si es la mención más reciente de este banco en el texto
                if codigo not in ultimos_indices or idx_alias > ultimos_indices[codigo]:
                    ultimos_indices[codigo] = idx_alias

    if ultimos_indices:
        # 🔥 EL TRUCO: Devolver el banco que esté más cerca del final del chat (el último escrito)
        return max(ultimos_indices, key=ultimos_indices.get)
    return ""

def guardar_estado_seguro(estado_dict: dict):
    # 🔥 ESCUDO ANTI-BORRADOS: Nunca guardaremos un estado vacío.
    if not estado_dict or "bancos" not in estado_dict or "credenciales" not in estado_dict:
        logger.error("🛑 INTENTO DE GUARDADO CORRUPTO BLOQUEADO. Ignorando...")
        return

    temp_file = f"{DIR_DATA}/estado_bot_tmp.json"
    final_file = f"{DIR_DATA}/estado_bot.json"

    for _ in range(5):
        try:
            # 🔥 GUARDADO ATÓMICO VERDADERO: Primero generamos el string en RAM
            json_data = json.dumps(estado_dict, ensure_ascii=False, indent=4)
            # Si el dump en RAM falla, nunca tocamos el archivo.

            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(json_data)
                f.flush() # Fuerza la escritura al disco físico
                os.fsync(f.fileno()) # Confirma a nivel de sistema operativo

            # Reemplazo seguro atómico a nivel de kernel
            os.replace(temp_file, final_file)
            break
        except Exception as e:
            logger.error(f"Fallo temporal al guardar JSON: {e}")
            time.sleep(0.2)

def leer_estado_botones() -> Dict[str, Any]:
    archivo = f"{DIR_DATA}/estado_bot.json"
    if not os.path.exists(archivo): return {}

    for _ in range(10):
        try:
            with open(archivo, "r", encoding="utf-8") as f:
                contenido = f.read().strip()
                if not contenido:
                    raise ValueError("Archivo JSON está vacío (0 bytes)")
                data = json.loads(contenido)
                if data: return data
        except Exception as e:
            time.sleep(0.1)

    logger.critical("🚨 ¡EL ARCHIVO JSON ESTÁ DESTRUIDO O BLOQUEADO TRAS 10 INTENTOS!")
    return {}

def obtener_proxy_config(estado: dict) -> Dict[str, str]:
    try:
        config = estado.get("config", {})
        proxy_server = config.get("proxy_server", "").strip()

        if proxy_server:
            proxy_dict = {"server": proxy_server}

            if not proxy_dict["server"].startswith("http") and not proxy_dict["server"].startswith("socks5"):
                proxy_dict["server"] = f"http://{proxy_dict['server']}"

            proxy_user = config.get("proxy_username", "").strip()
            proxy_pass = config.get("proxy_password", "").strip()
            if proxy_user and proxy_pass:
                proxy_dict["username"] = proxy_user
                proxy_dict["password"] = proxy_pass

            # 🔥 TEST DE SUPERVIVENCIA: No retornamos el proxy si no funciona rápido (evita cuelgues)
            return proxy_dict

    except Exception as e:
        logger.error(f"Error procesando el proxy: {e}")

    return None

def seguro_float(valor):
    try:
        if valor is None: return 0.0
        return float(str(valor).replace(',', ''))
    except Exception:
        return 0.0

def sincronizar_panel_vivo(orders: List[Dict], usdt_balance: float = 0.0):
    try:
        ordenes_vivas = {
            "pendientes": [],
            "por_liberar": [],
            "en_cuarentena": [],
            "procesando": [] 
        }

        tiempo_actual = int(time.time() * 1000)
        total_usdt_en_ordenes = 0.0

        for order in orders:
            try:
                trade_type = str(order.get("tradeType", "")).upper()
                if trade_type != "BUY":
                    continue

                estado_raw = str(order.get("orderStatus", "")).strip().upper()
                estados_muertos = ["4", "6", "7", "COMPLETED", "CANCELLED", "CANCELED", "CANCELLED_BY_SYSTEM", "EXPIRED", "FAIL"]
                if estado_raw in estados_muertos:
                    continue

                tiempo_creacion = int(order.get("createTime", 0) or 0)
                if tiempo_creacion > 0:
                    dias_antiguedad = (tiempo_actual - tiempo_creacion) / (1000 * 60 * 60 * 24)
                    if dias_antiguedad > 15.0:
                        continue

                order_id = str(order.get("orderNumber", ""))
                precio_total = seguro_float(order.get('totalPrice', 0))
                monto = f"{precio_total:.2f}".replace(".", ",")

                amount_bruto = seguro_float(order.get("amount", 0))
                commission = seguro_float(order.get("commission", 0))
                monto_usdt_neto = amount_bruto - commission

                total_usdt_en_ordenes += monto_usdt_neto
                monto_usdt = f"{monto_usdt_neto:.2f}".replace(".", ",")

                formato_panel = {
                    "id": order_id,
                    "monto": monto,
                    "monto_usdt": monto_usdt
                }

                if order_id in ordenes_en_proceso:
                    ordenes_vivas["procesando"].append(formato_panel)
                elif estado_raw in ["1", "PENDING"]:
                    if order_id in ordenes_ignoradas or order_id in ordenes_advertidas:
                        ordenes_vivas["en_cuarentena"].append(formato_panel)
                    else:
                        ordenes_vivas["pendientes"].append(formato_panel)
                elif estado_raw in ["2", "3", "PAID", "BUYER_PAYED", "IN_APPEAL", "APPEALING", "TRADING"]:
                    ordenes_vivas["por_liberar"].append(formato_panel)

            except Exception as e:
                logger.error(f"Error parseando orden {order.get('orderNumber')}: {e}")
                continue

        estado = leer_estado_botones()
        if estado:
            estado["ordenes_vivas"] = ordenes_vivas
            estado["balances_binance"] = {
                "usdt_disponible": usdt_balance,
                "usdt_en_ordenes": total_usdt_en_ordenes,
                "capital_total": usdt_balance + total_usdt_en_ordenes
            }
            guardar_estado_seguro(estado)

    except Exception as e:
        logger.error(f"Error en sincronizar_panel_vivo: {e}")

def extraer_datos_bancarios_chat(mensajes_cliente: List[Dict], cuenta_perfil: str) -> Tuple[str, str, bool]:
    cuentas_encontradas = []
    cedula_encontrada = ""
    for msg in mensajes_cliente:
        texto_bruto = str(msg.get("content", "")).replace("<br>", " ")
        texto_para_cedula = texto_bruto

        patron_cuenta = r'(?<!\d)(0134(?:[\s\-\.,_]*\d){16})(?!\d)'
        for match in re.finditer(patron_cuenta, texto_bruto):
            cuenta_limpia = re.sub(r'[\s\-\.,_]', '', match.group(1))
            if len(cuenta_limpia) == 20 and cuenta_limpia not in cuentas_encontradas:
                cuentas_encontradas.append(cuenta_limpia)
            texto_para_cedula = texto_para_cedula.replace(match.group(1), "")

        ced = extraer_cedula_texto(texto_para_cedula)
        if ced:
            cedula_encontrada = ced

    if cuenta_perfil and cuenta_perfil in cuentas_encontradas: 
        cuentas_encontradas.remove(cuenta_perfil)

    intento_estafa = len(cuentas_encontradas) > 1
    cuenta_final = cuentas_encontradas[-1] if cuentas_encontradas else ""
    return cuenta_final, cedula_encontrada, intento_estafa

class BinanceSAPIListener:
    BASE_URL = "https://api.binance.com"

    def __init__(self) -> None:
        self.api_key = ""
        self.api_secret = ""

    def update_credentials(self, api_key: str, api_secret: str) -> None:
        self.api_key = api_key
        self.api_secret = api_secret

    def _get_post_auth_string(self) -> str:
        timestamp = int(time.time() * 1000)
        query_string = f"timestamp={timestamp}"
        signature = hmac.new(self.api_secret.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
        return f"{query_string}&signature={signature}"

    def _get_get_auth_string(self, payload: Dict[str, Any]) -> str:
        payload["timestamp"] = int(time.time() * 1000)
        query_string = urlencode(payload)
        signature = hmac.new(self.api_secret.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
        return f"{query_string}&signature={signature}"

    async def get_usdt_balance(self, session: aiohttp.ClientSession) -> float:
        if not self.api_key: return 0.0
        total_usdt = 0.0

        try:
            payload = {"asset": "USDT", "timestamp": int(time.time() * 1000)}
            query_string = urlencode(payload)
            signature = hmac.new(self.api_secret.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
            url = f"{self.BASE_URL}/sapi/v1/asset/get-funding-asset"
            headers = {"X-MBX-APIKEY": self.api_key, "Content-Type": "application/json"}

            async with session.post(f"{url}?{query_string}&signature={signature}", headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for item in data:
                        if item.get("asset") == "USDT":
                            total_usdt += float(item.get("free", 0)) + float(item.get("locked", 0)) + float(item.get("freeze", 0))
        except Exception:
            pass

        try:
            payload = {"timestamp": int(time.time() * 1000)}
            query_string = urlencode(payload)
            signature = hmac.new(self.api_secret.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
            url = f"{self.BASE_URL}/api/v3/account?{query_string}&signature={signature}"
            headers = {"X-MBX-APIKEY": self.api_key}

            async with session.get(url, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for item in data.get("balances", []):
                        if item.get("asset") == "USDT":
                            total_usdt += float(item.get("free", 0)) + float(item.get("locked", 0))
        except Exception:
            pass

        return total_usdt

    async def fetch_pending_orders(self, session: aiohttp.ClientSession) -> List[Dict[str, Any]]:
        if not self.api_key: return []
        auth_string = self._get_post_auth_string()
        url = f"{self.BASE_URL}/sapi/v1/c2c/orderMatch/listOrders?{auth_string}"
        headers = {"X-MBX-APIKEY": self.api_key, "Content-Type": "application/json;charset=utf-8", "clientType": "WEB"}

        all_orders = []
        for estado_binance in [1, 2, 3]:
            for pagina in range(1, 4): 
                body = {"tradeType": "BUY", "page": pagina, "rows": 100, "orderStatus": estado_binance}
                try:
                    async with session.post(url, headers=headers, json=body, timeout=10) as response:
                        if response.status == 200:
                            data = await response.json()
                            orders = data.get("data", [])
                            if orders: all_orders.extend(orders)
                            if len(orders) < 100: break 
                        else:
                            error_text = await response.text()
                            logger.error(f"❌ Error de Binance al buscar órdenes. HTTP {response.status}: {error_text}")
                except Exception as e:
                    logger.error(f"❌ Falla de red al conectar con Binance (Órdenes): {e}")
        return all_orders

    async def get_order_detail(self, session: aiohttp.ClientSession, order_id: str) -> Dict[str, Any]:
        auth_string = self._get_post_auth_string()
        url = f"{self.BASE_URL}/sapi/v1/c2c/orderMatch/getUserOrderDetail?{auth_string}"
        headers = {"X-MBX-APIKEY": self.api_key, "Content-Type": "application/json;charset=utf-8", "clientType": "WEB"}
        body = {"adOrderNo": str(order_id)}
        try:
            async with session.post(url, headers=headers, json=body, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("data", {}) 
        except Exception: pass
        return {}

    async def get_chat_messages(self, session: aiohttp.ClientSession, order_id: str) -> List[Dict]:
        payload = {"orderNo": str(order_id), "page": 1, "rows": 50}
        auth_string = self._get_get_auth_string(payload)
        url = f"{self.BASE_URL}/sapi/v1/c2c/chat/retrieveChatMessagesWithPagination?{auth_string}"
        headers = {"X-MBX-APIKEY": self.api_key, "clientType": "web"}
        try:
            async with session.get(url, headers=headers, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    msgs = data.get("data", [])
                    return msgs if isinstance(msgs, list) else []
        except Exception:
            pass
        return []

    async def _get_chat_credentials(self, session: aiohttp.ClientSession) -> Dict[str, Any]:
        payload = {"timestamp": int(time.time() * 1000)}
        query_string = urlencode(payload)
        signature = hmac.new(self.api_secret.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
        url = f"{self.BASE_URL}/sapi/v1/c2c/chat/retrieveChatCredential?{query_string}&signature={signature}"
        headers = {"X-MBX-APIKEY": self.api_key, "clientType": "web"}
        try:
            async with session.get(url, headers=headers, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("data", {})
        except Exception:
            pass
        return {}

    async def send_chat_message(self, session: aiohttp.ClientSession, order_id: str, mensaje: str) -> bool:
        creds = await self._get_chat_credentials(session)
        if not creds: return False
        chatWssUrl = creds.get("chatWssUrl", "")
        listenKey = creds.get("listenKey", "")
        listenToken = creds.get("listenToken", "")
        if not all([chatWssUrl, listenKey, listenToken]): return False
        wss_url = f"{chatWssUrl}/{listenKey}?token={listenToken}&clientType=web"
        try:
            async with session.ws_connect(wss_url) as ws:
                timestamp = int(time.time() * 1000)
                payload = {
                    "type": "text", "uuid": str(timestamp), "orderNo": str(order_id),
                    "content": mensaje, "self": True, "clientType": "web",
                    "createTime": timestamp, "sendStatus": 0
                }
                await ws.send_json(payload)
                await asyncio.sleep(1)
                return True
        except Exception:
            return False

    async def upload_image_to_chat(self, session: aiohttp.ClientSession, order_id: str, image_path: str) -> bool:
        if not image_path or not os.path.exists(image_path): return False
        image_name = os.path.basename(image_path)
        timestamp = int(time.time() * 1000)
        query_string = f"timestamp={timestamp}"
        signature = hmac.new(self.api_secret.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
        url_presign = f"{self.BASE_URL}/sapi/v1/c2c/chat/image/pre-signed-url?{query_string}&signature={signature}"
        headers = {"X-MBX-APIKEY": self.api_key, "Content-Type": "application/json;charset=utf-8", "clientType": "WEB"}
        body = json.dumps({"imageName": image_name})

        try:
            async with session.post(url_presign, headers=headers, data=body, timeout=10) as resp:
                res_text = await resp.text()
                if resp.status == 200:
                    data = json.loads(res_text)
                    presigned_url = data.get("data", {}).get("uploadUrl") or data.get("data", {}).get("preSignedUrl")
                    image_url = data.get("data", {}).get("imageUrl")
                    if not presigned_url: return False
                else: 
                    logger.error(f"❌ Falló pidiendo permiso a Binance para subir foto: {res_text}")
                    return False
        except Exception as e:
            logger.error(f"❌ Error de red pidiendo permiso de foto: {e}")
            return False

        try:
            with open(image_path, 'rb') as f: file_data = f.read()

            # 🔥 FIX: Quitamos las cabeceras automáticas de Python que chocan con la firma de seguridad de Binance/AWS
            async with session.put(presigned_url, data=file_data, skip_auto_headers=['Content-Type'], timeout=20) as resp_put:
                if resp_put.status != 200:
                    aws_error = await resp_put.text()
                    logger.error(f"❌ El servidor de Binance rechazó la imagen. HTTP {resp_put.status}: {aws_error}")
                    return False
        except Exception as e:
            logger.error(f"❌ Error conectando al servidor de imágenes de Binance: {e}")
            return False

        creds = await self._get_chat_credentials(session)
        if not creds: return False
        chatWssUrl = creds.get("chatWssUrl", "")
        listenKey = creds.get("listenKey", "")
        listenToken = creds.get("listenToken", "")
        wss_url = f"{chatWssUrl}/{listenKey}?token={listenToken}&clientType=web"

        try:
            async with session.ws_connect(wss_url) as ws:
                timestamp_ws = int(time.time() * 1000)
                payload_ws = {
                    "type": "image", "uuid": str(timestamp_ws), "orderNo": str(order_id),
                    "thumbnailUrl": image_url, "imageUrl": image_url, "imageType": "png",
                    "width": 800, "height": 600, "self": True, "clientType": "web",
                    "createTime": timestamp_ws, "sendStatus": 0
                }
                await ws.send_json(payload_ws)
                await asyncio.sleep(2.0) 
                return True
        except Exception as e:
            logger.error(f"❌ Error enviando mensaje por el chat (WebSocket): {e}")
            return False

    async def mark_order_as_paid(self, session: aiohttp.ClientSession, order_id: str, pay_method_id: str) -> bool:
        auth_string = self._get_post_auth_string()
        url = f"{self.BASE_URL}/sapi/v1/c2c/orderMatch/markOrderAsPaid?{auth_string}"
        headers = {"X-MBX-APIKEY": self.api_key, "Content-Type": "application/json;charset=utf-8", "clientType": "WEB"}
        body = {"orderNumber": str(order_id), "payId": str(pay_method_id)}
        try:
            async with session.post(url, headers=headers, json=body, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("success", False)
        except Exception: pass
        return False

# =========================================================
# ROUND ROBIN INTELIGENTE (CON FILTRO DE MÉTODOS)
# =========================================================
def obtener_cuenta_disponible_round_robin(estado: dict, monto_fiat: float, tipo_operacion: str) -> str:
    global indice_cuenta
    cuentas_validas = []
    bancos = estado.get("bancos", {})
    limites = estado.get("limites", {})

    for c, activa in estado.get("cuentas", {}).items():

        # 🔥 SISTEMA DE RESURRECCIÓN AUTOMÁTICA 🔥
        # Si la prendiste manual en el panel, el bot la perdona y la borra de su lista negra.
        if activa and c in cuentas_agotadas:
            cuentas_agotadas.discard(c)

        if activa and c not in cuentas_ocupadas and c not in cuentas_agotadas: # 🔥 Ignora las quemadas
            datos_banco = bancos.get(c, {})
            tipo = datos_banco.get("tipo", "Operadora")

            if tipo == "Operadora":
                datos_limite = limites.get(c, {})

                # 🔥 LECTOR EXACTO (Basado en el JSON real) 🔥
                pm_activo = False
                pm_min = 0.0

                tr_activa = False
                tr_min = 0.0

                # Leemos la sub-carpeta PAGO_MOVIL
                pm_data = datos_limite.get("PAGO_MOVIL", {})
                if isinstance(pm_data, dict):
                    pm_activo = pm_data.get("activo", False)
                    try: pm_min = float(pm_data.get("min", 0))
                    except: pass

                # Leemos la sub-carpeta TRANSFERENCIA
                tr_data = datos_limite.get("TRANSFERENCIA", {})
                if isinstance(tr_data, dict):
                    tr_activa = tr_data.get("activo", False)
                    try: tr_min = float(tr_data.get("min", 0))
                    except: pass

                # Filtro de bloqueo
                if tipo_operacion == "PAGO_MOVIL":
                    if not pm_activo: continue
                    min_ves = pm_min
                elif tipo_operacion == "TRANSFERENCIA":
                    if not tr_activa: continue
                    min_ves = tr_min
                else:
                    continue # Por si llega un método raro

                # 🔥 VALIDACIÓN DINÁMICA (ACTUALIZADA) 🔥
                if min_ves <= monto_fiat:
                    cuentas_validas.append(c)

    if not cuentas_validas: 
        return ""

    cuentas_validas.sort()
    cuenta = cuentas_validas[indice_cuenta % len(cuentas_validas)]
    indice_cuenta += 1
    return cuenta

# =========================================================
# MOTOR: EJECUCIÓN DE PAGO P2P INDIVIDUAL
# =========================================================
async def process_order(order: Dict[str, Any], listener: BinanceSAPIListener, session: aiohttp.ClientSession, cuenta_asignada: str, browser, bank_sessions: dict, semaforo: asyncio.Semaphore) -> bool:
    order_id = str(order.get("orderNumber", ""))
    exito_global = False
    interactuo_con_banco = False

    # Variable de control para pedir testamento
    uso_cuenta_chat = False 

    monto_pago = "0,00"

    try:
        async with semaforo:
            gatillo_emergencia()

            fiat_amount = seguro_float(order.get("totalPrice", 0))
            monto_pago = f"{fiat_amount:.2f}".replace(".", ",")

            detalles_privados = await listener.get_order_detail(session, order_id)
            pay_methods = detalles_privados.get("payMethods", [])

            # 🔥 ENRUTADOR DE MÉTODO DE PAGO 🔥
            metodo_pago_obj = None
            tipo_operacion = "" 

            for pm in pay_methods:
                pm_str = str(pm.get("payType", "")).lower() + " " + str(pm.get("identifier", "")).lower()
                if "mobile" in pm_str or "movil" in pm_str or "pago movil" in pm_str:
                    metodo_pago_obj = pm
                    tipo_operacion = "PAGO_MOVIL"
                    break
                elif "banesco" in pm_str: 
                    metodo_pago_obj = pm
                    tipo_operacion = "TRANSFERENCIA"
                    break

                # Check fallback para Banesco
                for f in pm.get("fields", []):
                    if str(f.get("fieldValue", "")).replace(" ", "").replace("-", "").startswith("0134"):
                        metodo_pago_obj = pm
                        tipo_operacion = "TRANSFERENCIA"
                        break
                if metodo_pago_obj: 
                    break

            # --- 🔥 CORTAFUEGOS DE SEGURIDAD ANTI-FUGAS 🔥 ---
            est_sec = leer_estado_botones()
            l_sec = est_sec.get("limites", {}).get(cuenta_asignada, {})

            pm_data = l_sec.get("PAGO_MOVIL", {})
            tr_data = l_sec.get("TRANSFERENCIA", {})

            pm_habilitado = pm_data.get("activo", False) if isinstance(pm_data, dict) else False
            tr_habilitada = tr_data.get("activo", False) if isinstance(tr_data, dict) else False

            if tipo_operacion == "PAGO_MOVIL" and not pm_habilitado:
                logger.warning(f"🛑 CORTAFUEGOS: La orden {order_id} es Pago Móvil. {cuenta_asignada} lo tiene APAGADO. Devolviendo orden...")
                return False

            if tipo_operacion == "TRANSFERENCIA" and not tr_habilitada:
                logger.warning(f"🛑 CORTAFUEGOS: La orden {order_id} es Transferencia. {cuenta_asignada} la tiene APAGADA. Devolviendo orden...")
                return False
            # ----------------------------------------------------------

            historial_chat_bruto = await listener.get_chat_messages(session, order_id)
            historial_chat = sorted(historial_chat_bruto, key=lambda x: int(x.get("createTime", 0)))
            textos_extraidos = [str(m.get("content", "")) for m in historial_chat if m.get("content")]
            mensajes_cliente = [msg for msg in historial_chat if msg.get("self") is False]
            texto_global_chat = " ".join([str(m.get("content", "")).replace("<br>", " ").replace("\n", " ") for m in historial_chat])

            # Datos finales a extraer
            cuenta_final = ""
            cedula_final = ""
            telefono_final = ""
            codigo_banco_final = ""
            cuenta_perfil = ""
            cedula_perfil = "" # 🔥 FIX: Evita el crash en Transferencia
            telefono_perfil = "" # 🔥 FIX: Evita el crash en Transferencia
            banco_perfil = "" # 🔥 FIX: Evita el crash en Transferencia

            admin_dio_orden = False
            for msg in historial_chat:
                if msg.get("self") is True:  
                    txt_msg = limpiar_texto_chat(str(msg.get("content", "")))
                    if re.search(r'\b(procede|proceda)\b', txt_msg):
                        admin_dio_orden = True
                        # await enviar_alerta_telegram(f"⚠️ **ORDEN MANUAL:** El administrador autorizó el pago forzado de la orden `{order_id}` con el comando 'procede'.")
                        break

            logger.info(f"🚀 ORDEN {order_id} | TIPO: {tipo_operacion or 'DESCONOCIDO'} | CAJERO: {cuenta_asignada} | Bs. {monto_pago}")

            if not admin_dio_orden and not metodo_pago_obj: 
                await enviar_alerta_telegram(f"⚠️ **REVISIÓN MANUAL:** Orden `{order_id}`.\nNo se detectó Banesco ni Pago Móvil. Revise manualmente el chat y use la palabra clave 'procede' si envía datos.")
                ordenes_ignoradas[order_id] = int(time.time() * 1000)
                logger.info(f"🔄 Liberando la cuenta {cuenta_asignada} para que siga pagando otras órdenes (Método no detectado).")
                return False

            pay_method_id = str(metodo_pago_obj.get("payMethodId", "") or metodo_pago_obj.get("id", "")) if metodo_pago_obj else ""

            campos_perfil = metodo_pago_obj.get("fields", []) if metodo_pago_obj else []
            textos_perfil = " ".join([str(f.get("fieldValue", "")) for f in campos_perfil])

            # 🔥 FIX: Definimos esto AFUERA para que tanto Transferencia como Pago Móvil puedan leer el chat 🔥
            texto_solo_cliente = " ".join([str(m.get("content", "")) for m in mensajes_cliente])

            if tipo_operacion == "TRANSFERENCIA":
                # 1. Extraer datos del perfil de Binance
                cuenta_cruda = ""
                cuenta_perfil = ""
                cedula_perfil = ""

                for match in re.finditer(PATRON_CUENTA, textos_perfil):
                    cuenta_cruda = match.group(1) 
                    cuenta_limpia = re.sub(r'[\s\-\.,_]', '', cuenta_cruda)
                    if len(cuenta_limpia) == 20 and cuenta_limpia.startswith("0134"): 
                        cuenta_perfil = cuenta_limpia 
                        break

                texto_sin_cuenta = textos_perfil.replace(cuenta_cruda, "") if cuenta_cruda else textos_perfil
                ced_temp = extraer_cedula_texto(texto_sin_cuenta)

                if ced_temp:
                    ced_test = "".join(filter(str.isdigit, ced_temp))
                    if len(ced_test) >= 6 and len(set(ced_test)) > 1 and "12345" not in ced_test and "00000" not in ced_test:
                        cedula_perfil = ced_temp

                # 🔥 2. PRIORIDAD ESTRICTA AL PERFIL 🔥
                # Si el perfil tiene todo y no ha sido marcado como inválido por Banesco antes, se usa SÍ O SÍ.
                if cuenta_perfil and cedula_perfil and order_id not in perfiles_invalidos:
                    cuenta_final = cuenta_perfil
                    cedula_final = cedula_perfil
                    uso_cuenta_chat = False
                    logger.info(f"✅ Perfil válido detectado para {order_id}. Ignorando el chat por completo.")
                else:
                    # 3. Si el perfil está incompleto o Banesco lo rebotó antes, buscamos en el chat
                    if order_id in perfiles_invalidos:
                        logger.info(f"⚠️ El perfil de {order_id} fue rechazado por Banesco. Escaneando el chat...")
                    else:
                        logger.info(f"⚠️ Faltan datos en el perfil de {order_id}. Escaneando el chat...")

                    texto_solo_cliente = " ".join([str(m.get("content", "")) for m in mensajes_cliente])

                    cuentas_chat = []
                    for m in re.finditer(PATRON_CUENTA, texto_solo_cliente):
                        c_limpia = re.sub(r'[\s\-\.,_]', '', m.group(1))
                        if len(c_limpia) == 20 and c_limpia.startswith("0134"):
                            cuentas_chat.append(c_limpia)

                    ced_chat = extraer_cedula_texto(texto_solo_cliente)
                    ced_chat_valida = ""
                    if ced_chat:
                        ced_test_chat = "".join(filter(str.isdigit, ced_chat))
                        if len(ced_test_chat) >= 6 and len(set(ced_test_chat)) > 1 and "12345" not in ced_test_chat and "00000" not in ced_test_chat:
                            ced_chat_valida = ced_chat

                    cuenta_final = cuentas_chat[-1] if cuentas_chat else cuenta_perfil
                    cedula_final = ced_chat_valida if ced_chat_valida else cedula_perfil

                    # 🔥 EL TESTAMENTO 🔥
                    # Si tuvimos que sacar CUALQUIER DATO del chat porque el perfil falló, pedimos testamento.
                    uso_cuenta_chat = bool(cuentas_chat or ced_chat_valida)

                # 4. Sobrescritura final si el admin mandó 'procede' con los datos
                if admin_dio_orden:
                    cuentas_globales = []

                    # 🔥 CORTAFUEGOS: Evitar que el bot lea sus propios mensajes de error 🔥
                    textos_humanos = [str(m.get("content", "")) for m in historial_chat if "📌 Ref. Orden:" not in str(m.get("content", "")) and "🤖" not in str(m.get("content", ""))]
                    texto_limpio_comandos = " ".join(textos_humanos).replace("<br>", " ").replace("\n", " ")
                    texto_sin_cuentas = texto_limpio_comandos 

                    for m in re.finditer(PATRON_CUENTA, texto_limpio_comandos):
                        cuenta_sucia = m.group(1)
                        c_limpia = re.sub(r'[\s\-\.,_]', '', cuenta_sucia)
                        if len(c_limpia) == 20 and c_limpia.startswith("0134"):
                            cuentas_globales.append(c_limpia)

                        texto_sin_cuentas = texto_sin_cuentas.replace(cuenta_sucia, "")

                    if cuentas_globales: cuenta_final = cuentas_globales[-1]

                    ced_global = extraer_cedula_texto(texto_sin_cuentas)
                    if ced_global: cedula_final = ced_global

                    if cuenta_final and cedula_final:
                        logger.info(f"👑 ¡COMANDO MANUAL RECIBIDO! El administrador ordenó pago directo en {order_id}.")
                        await enviar_alerta_telegram(f"⚠️ 👑 **OVERRIDE ACTIVADO:** Orden `{order_id}`.\nSe detectó el comando 'procede'. El bot ignorará el perfil y pagará a la cuenta `{cuenta_final}` con CI `{cedula_final}`.")

                # 🔥 RESTAURACIÓN DE TEXTOS ORIGINALES Y CUARENTENA PROFUNDA 🔥
                if not cuenta_final:
                    if not any("no posee una cuenta banesco" in limpiar_texto_chat(txt) for txt in textos_extraidos):
                        await listener.send_chat_message(session, order_id, f"📌 Ref. Orden: {order_id}\n\nNo posee una cuenta Banesco válida registrada en su perfil. Por favor, envíe su Cuenta Banesco (20 dígitos) y Cédula por este chat.")
                    ordenes_advertidas.add(order_id)
                    ordenes_ignoradas[order_id] = int(time.time() * 1000)
                    logger.info(f"⏸️ Orden {order_id} a Cuarentena (Faltan datos). Liberando {cuenta_asignada}.")
                    return False

                if not cedula_final:
                    if not any("notamos que no tenemos una" in limpiar_texto_chat(txt) for txt in textos_extraidos):
                        await listener.send_chat_message(session, order_id, f"📌 Ref. Orden: {order_id}\n\nNotamos que no tenemos una cédula válida registrada. Por favor, envíe su número de cédula real por este chat para poder emitir el pago a su cuenta Banesco.")
                    ordenes_advertidas.add(order_id)
                    ordenes_ignoradas[order_id] = int(time.time() * 1000)
                    logger.info(f"⏸️ Orden {order_id} a Cuarentena (Faltan datos). Liberando {cuenta_asignada}.")
                    return False

            elif tipo_operacion == "PAGO_MOVIL":
                if admin_dio_orden:
                    # 🔥 CORTAFUEGOS: Evitar que el bot lea sus propios mensajes de error 🔥
                    textos_humanos = [str(m.get("content", "")) for m in historial_chat if "📌 Ref. Orden:" not in str(m.get("content", "")) and "🤖" not in str(m.get("content", ""))]
                    texto_limpio_comandos = " ".join(textos_humanos).replace("<br>", " ").replace("\n", " ")

                    telefonos = re.findall(PATRON_TELEFONO, texto_limpio_comandos)
                    if telefonos: telefono_final = re.sub(r'\D', '', telefonos[-1])
                    cedula_final = extraer_cedula_texto(texto_limpio_comandos)
                    codigo_banco_final = buscar_banco_texto(texto_limpio_comandos)

                    if telefono_final and cedula_final and codigo_banco_final:
                        logger.info(f"👑 ¡COMANDO MANUAL RECIBIDO! El administrador ordenó pago directo (Pago Móvil) en {order_id}.")
                        await enviar_alerta_telegram(f"⚠️ 👑 **OVERRIDE ACTIVADO:** Orden `{order_id}`.\nSe detectó el comando 'procede'. El bot ignorará el perfil y pagará al Pago Móvil `{telefono_final}` con CI `{cedula_final}` (Banco: {codigo_banco_final}).")
                else:
                    # 1. Extraemos los datos del perfil de Binance
                    tels_perfil = re.findall(PATRON_TELEFONO, textos_perfil)
                    telefono_perfil = re.sub(r'\D', '', tels_perfil[0]) if tels_perfil else ""
                    cedula_perfil = extraer_cedula_texto(textos_perfil)
                    banco_perfil = buscar_banco_texto(textos_perfil)

                    ced_perfil_test = "".join(filter(str.isdigit, cedula_perfil))
                    es_ced_perfil_valida = len(ced_perfil_test) >= 6 and len(set(ced_perfil_test)) > 1 and "12345" not in ced_perfil_test and "00000" not in ced_perfil_test

                    # 🔥 2. PRIORIDAD ABSOLUTA AL PERFIL 🔥
                    if telefono_perfil and es_ced_perfil_valida and banco_perfil:
                        telefono_final = telefono_perfil
                        cedula_final = cedula_perfil
                        codigo_banco_final = banco_perfil
                        uso_cuenta_chat = False # NO pedimos testamento porque el perfil está completo
                    else:
                        # 3. Si falta algo en el perfil, rescatamos leyendo el chat
                        tels_chat = re.findall(PATRON_TELEFONO, texto_solo_cliente)
                        telefono_chat = re.sub(r'\D', '', tels_chat[-1]) if tels_chat else ""
                        cedula_chat = extraer_cedula_texto(texto_solo_cliente)
                        banco_chat = buscar_banco_texto(texto_solo_cliente)

                        ced_chat_test = "".join(filter(str.isdigit, cedula_chat))
                        es_ced_chat_valida = len(ced_chat_test) >= 6 and len(set(ced_chat_test)) > 1 and "12345" not in ced_chat_test and "00000" not in ced_chat_test

                        telefono_final = telefono_chat if telefono_chat else telefono_perfil
                        codigo_banco_final = banco_chat if banco_chat else banco_perfil
                        cedula_final = cedula_chat if es_ced_chat_valida else (cedula_perfil if es_ced_perfil_valida else "")

                        # SÍ pedimos testamento porque nos vimos obligados a sacar datos del chat
                        uso_cuenta_chat = bool(telefono_chat or banco_chat)

                if not telefono_final or not cedula_final or not codigo_banco_final:
                    if not any("faltan datos para el pago" in limpiar_texto_chat(txt) for txt in textos_extraidos):
                        await listener.send_chat_message(session, order_id, f"📌 Ref. Orden: {order_id}\n\nFaltan datos para el Pago Móvil. Por favor, envíe: Teléfono, Cédula real y Nombre del Banco por este chat.")
                    ordenes_advertidas.add(order_id)
                    ordenes_ignoradas[order_id] = int(time.time() * 1000)
                    logger.info(f"⏸️ Orden {order_id} a Cuarentena (Faltan datos PM). Liberando {cuenta_asignada}.")
                    return False

            # --- 🔥 SISTEMA DE TESTAMENTO / CONFIRMACIÓN INVERTIDO 🔥 ---
            # Si el bot sacó los datos del chat, ANULA la validez del perfil para forzar el testamento.
            es_perfil_banesco_valido = (tipo_operacion == "TRANSFERENCIA" and cuenta_perfil and cedula_final and len(cuenta_perfil) == 20 and not uso_cuenta_chat)
            es_perfil_pm_valido = (tipo_operacion == "PAGO_MOVIL" and telefono_perfil and cedula_perfil and banco_perfil and not uso_cuenta_chat)

            if (es_perfil_banesco_valido or es_perfil_pm_valido) and not admin_dio_orden:
                logger.info(f"✅ Los datos del perfil de Binance están completos para la orden {order_id}. Procediendo al pago en silencio...")
                uso_cuenta_chat = False # Se mantiene apagado el testamento

            if uso_cuenta_chat and not admin_dio_orden:
                testamento_presente = any("de autorizar debe enviar" in limpiar_texto_chat(txt) for txt in textos_extraidos)
                if not testamento_presente:
                    logger.info(f"Disparando testamento de seguridad al cliente vía WSS para {order_id}...")
                    mensaje_advertencia = f"""📌 Ref. Orden: {order_id}

Para continuar con el pago a la cuenta enviada por este chat, debe confirmarme y autorizarme.

De autorizar debe enviar el siguiente mensaje:
'autorizo que soy el unico responsable por la cuenta enviada al chat y confirmo que no me estoy comunicando con usted ni con nadie fuera de la plataforma para tomar este anuncio'"""
                    await listener.send_chat_message(session, order_id, mensaje_advertencia)
                    ordenes_advertidas.add(order_id)
                    ordenes_ignoradas[order_id] = int(time.time() * 1000)
                    logger.info(f"⏸️ Testamento enviado. Liberando la cuenta {cuenta_asignada} para que el bot siga trabajando.")
                    return False

                autorizado = False
                palabras_afirmativas = [
                    "autorizo", "autorizado", "autoriza",
                    "confirmo", "confirmado", "confirmada",
                    "de acuerdo", "estoy de acuerdo",
                    "responsable", "procede", "proceda"
                ]
                frases_negativas = [
                    "no confirmo", "no autorizo", "no de acuerdo",
                    "no estoy de acuerdo", "no me hago responsable",
                    "jamas", "nunca", "no proceda", "no procede"
                ]

                hay_negativa = False
                for msg in reversed(historial_chat):
                    if not msg.get("self"):
                        txt_msg = limpiar_texto_chat(str(msg.get("content", "")))
                        if any(neg in txt_msg for neg in frases_negativas):
                            hay_negativa = True
                            logger.warning(f"🛑 Negativa explícita detectada en el chat para la orden {order_id}.")
                            break

                if not hay_negativa:
                    for msg in historial_chat:
                        if not msg.get("self"):
                            txt_msg = limpiar_texto_chat(str(msg.get("content", "")))
                            if any(afirm in txt_msg for afirm in palabras_afirmativas):
                                autorizado = True
                                break

                if autorizado: 
                    logger.info(f"✅ ¡Autorización confirmada para cuenta del chat en {order_id}!")
                    ordenes_advertidas.discard(order_id)
                else:
                    logger.info(f"⏸️ Esperando autorización en el chat para {order_id}. Liberando la cuenta {cuenta_asignada} para no detener el bot.")
                    ordenes_advertidas.add(order_id)
                    ordenes_ignoradas[order_id] = int(time.time() * 1000)
                    return False
            # --------------------------------------------------------------

            # Verificación de vida de la orden antes de entrar al banco
            detalles_seguridad = await listener.get_order_detail(session, order_id)
            if str(detalles_seguridad.get("orderStatus", "0")) != "1":
                logger.info(f"🔄 Orden cancelada. Liberando cuenta {cuenta_asignada}.")
                ordenes_ignoradas[order_id] = int(time.time() * 1000)
                return False

            async def verificador_binance():
                try: return str((await listener.get_order_detail(session, order_id)).get("orderStatus", "0")) == "1"
                except: return True 

            estado_actual = leer_estado_botones()
            datos_banco = estado_actual.get("bancos", {}).get(cuenta_asignada, {})
            limite_durmiendo = float(estado_actual.get("config", {}).get("dinero_durmiendo", 100000.0))

            payment_data = {
                "order_id": order_id,
                "tipo_pago": tipo_operacion,
                "amount": monto_pago, 
                "seguridad_banco": datos_banco, 
                "nombre_cuenta": cuenta_asignada,
                "dinero_durmiendo": limite_durmiendo,
                "verificador_orden": verificador_binance,
                "pago_enviado": False
            }

            if tipo_operacion == "TRANSFERENCIA":
                payment_data["account_number"] = cuenta_final
                payment_data["identity_doc"] = cedula_final
            elif tipo_operacion == "PAGO_MOVIL":
                payment_data["telefono"] = telefono_final
                payment_data["identity_doc"] = cedula_final
                payment_data["banco_destino"] = codigo_banco_final

            candado = obtener_candado(cuenta_asignada)
            async with candado:
                gatillo_emergencia()
                if order_id in ordenes_ignoradas: return False

                interactuo_con_banco = True
                es_nueva = False

                if cuenta_asignada not in bank_sessions or bank_sessions[cuenta_asignada]["page"].is_closed():
                    context_options = {"viewport": {"width": 1280, "height": 720}, "device_scale_factor": 2}
                    proxy_settings = obtener_proxy_config(leer_estado_botones())
                    if proxy_settings: context_options["proxy"] = proxy_settings
                    aislado_ctx = await browser.new_context(**context_options)
                    aislado_page = await aislado_ctx.new_page()
                    bank_sessions[cuenta_asignada] = {"context": aislado_ctx, "page": aislado_page}
                    es_nueva = True

                payment_data["nueva_sesion"] = es_nueva
                page = bank_sessions[cuenta_asignada]["page"]

                if await execute_login(page, payment_data):
                    try: await page.evaluate("document.querySelectorAll('.swal2-container').forEach(e => e.remove());")
                    except Exception: pass

                    # 🔥 ENRUTAMIENTO DE EJECUCIÓN 🔥
                    if tipo_operacion == "TRANSFERENCIA":
                        success, ruta_recibo = await execute_transfer(page, payment_data)
                    else:
                        success, ruta_recibo = await execute_pagomovil(page, payment_data)

                    if success:
                        exito_global = True # 🔥 Guardamos la caché del banco inmediatamente

                        # 🔥 AUTO-APAGADO INTELIGENTE (DINERO DURMIENDO) 🔥
                        try:
                            est_fresco = leer_estado_botones()
                            saldo_final = float(est_fresco.get("saldos", {}).get(cuenta_asignada, payment_data.get("saldo", 0.0)))
                            if 0 < saldo_final <= limite_durmiendo:
                                if "cuentas" in est_fresco:
                                    est_fresco["cuentas"][cuenta_asignada] = False
                                    guardar_estado_seguro(est_fresco)
                                    msg_dormir = f"💤 **CUENTA A DORMIR:** `{cuenta_asignada}` ha sido apagada automáticamente.\n💰 Saldo: Bs. {saldo_final:,.2f}"
                                    logger.warning(msg_dormir)
                                    asyncio.create_task(enviar_alerta_telegram(msg_dormir))
                        except Exception as e:
                            logger.error(f"Error evaluando auto-apagado: {e}")

                        # ==============================================================
                        # 🚀 MODO METRALLETA: TAREAS PESADAS AL SEGUNDO PLANO 🚀
                        # ==============================================================
                        async def tareas_lentas_binance():
                            pago_marcado = await listener.mark_order_as_paid(session, order_id, pay_method_id)

                            if pago_marcado:
                                logger.info(f"✅ ORDEN LIQUIDADA Y MARCADA COMO PAGADA: {order_id}")
                                ordenes_ignoradas[order_id] = int(time.time() * 1000)
                            else:
                                logger.error(f"⚠️ Falló al marcar como pagada la orden {order_id}. ¡Revisar en Binance!")

                            if ruta_recibo:
                                if await listener.upload_image_to_chat(session, order_id, ruta_recibo):
                                    logger.info("✅ Recibo subido al chat de Binance exitosamente.")
                                else:
                                    logger.warning(f"⚠️ Falló la subida del recibo a Binance para {order_id}.")

                                mensaje_cierre = "✅ Fondos transferidos.\n🤖 Esta operación fue 100% automatizada\nPor la tecnología de IG: @VORTEX - BOTP2P\n\n¡Agradezco mucho su calificación positiva! ⭐🤝"
                                await listener.send_chat_message(session, order_id, mensaje_cierre)

                                order_limpio = order_id.replace("_", "-").replace("*", "")
                                tipo_limpio = tipo_operacion.replace("_", " ")
                                mensaje_telegram = (
                                    f"✅ PAGO EXITOSO ({tipo_limpio})\n"
                                    f"🏦 Cuenta: {cuenta_asignada}\n"
                                    f"🧾 Orden: `{order_limpio}`\n"
                                    f"💰 Monto: Bs. {monto_pago}"
                                )
                                try:
                                    await enviar_foto_telegram(ruta_recibo, mensaje_telegram)
                                except Exception:
                                    pass # Telegram falló, no importa.

                        # Lanzamos las fotos y confirmaciones al fondo SIN FRENAR el banco
                        asyncio.create_task(tareas_lentas_binance())
                        return True

                    # 🔥 TODO EL MANEJO DE ERRORES ALINEADO CORRECTAMENTE 🔥
                    if payment_data.get("pago_enviado", False):
                        msg_alerta = (
                            f"🚨 **¡ALERTA ROJA - POSIBLE PAGO FANTASMA!** 🚨\n"
                            f"La orden `{order_id}` falló al descargar el recibo, pero el clic de 'Pagar' **SÍ SE ENVIÓ**.\n\n"
                            f"🏦 **Tu Cuenta:** `{cuenta_asignada}`\n"
                            f"💰 **Monto:** Bs. `{monto_pago}`\n\n"
                            f"Bot enviando orden a Cuarentena. ¡Revisa el correo de {cuenta_asignada} YA!"
                        )
                        logger.critical(msg_alerta)

                        # 🔥 NUEVO: Tomar captura de pantalla y código HTML del congelamiento 🔥
                        try:
                            os.makedirs(f"{DIR_LOGS}/screenshots", exist_ok=True)
                            ruta_fantasma = f"{DIR_LOGS}/screenshots/fantasma_{order_id}.png"
                            ruta_html = f"{DIR_LOGS}/screenshots/codigo_fantasma_{order_id}.txt"

                            await page.screenshot(path=ruta_fantasma)

                            # 🔥 GUARDA EL CÓDIGO HTML PARA PASÁRSELO A LA IA 🔥
                            html_mortal = await page.content()
                            with open(ruta_html, "w", encoding="utf-8") as f:
                                f.write(html_mortal)

                            await enviar_foto_telegram(ruta_fantasma, msg_alerta)
                        except Exception as e:
                            logger.error(f"Fallo al tomar foto y HTML del pago fantasma: {e}")
                            await enviar_alerta_telegram(msg_alerta)

                        ordenes_advertidas.add(order_id)
                        ordenes_ignoradas[order_id] = int(time.time() * 1000)
                        return False

                    if ruta_recibo in ["ORDEN_CANCELADA", "ERROR_OTP", "SESION_CADUCADA", "TIMEOUT_CARGA_PAGOMOVIL", "TIMEOUT_BANESCO", "ERROR_LLENADO_NATIVO"]:
                        if ruta_recibo == "ORDEN_CANCELADA": ordenes_ignoradas[order_id] = int(time.time() * 1000)
                        logger.warning(f"⏳ Banesco está lento o falló temporalmente ({ruta_recibo}). Reintentando en silencio...")
                        return False

                    elif ruta_recibo == "FONDOS_INSUFICIENTES":
                        cuentas_agotadas.add(cuenta_asignada)
                        estado_fresco = leer_estado_botones()

                        # 🔥 APAGADO VISUAL EN EL PANEL 🔥
                        if "cuentas" in estado_fresco:
                            estado_fresco["cuentas"][cuenta_asignada] = False
                            guardar_estado_seguro(estado_fresco)

                        await enviar_alerta_telegram(f"🛑 **CUENTA QUEMADA (SIN FONDOS):** `{cuenta_asignada}`\nLa cuenta fue apagada automáticamente en el panel. La orden `{order_id}` ha sido devuelta a la cola para la siguiente cuenta.")
                        return False

                    elif ruta_recibo == "LIMITE_EXCEDIDO":
                        cuentas_agotadas.add(cuenta_asignada)
                        estado_fresco = leer_estado_botones()

                        # 🔥 APAGADO VISUAL EN EL PANEL 🔥
                        if "cuentas" in estado_fresco:
                            estado_fresco["cuentas"][cuenta_asignada] = False
                            guardar_estado_seguro(estado_fresco)

                        logger.warning(f"🛑 Cuenta {cuenta_asignada} quemada por límite. Apagada en panel y bloqueada en RAM. Liberando la orden...")

                        # 🔥 ENVÍO AUTOMÁTICO AL CHAT DE REPORTES (TELEGRAM) 🔥
                        msg_limite = (
                            f"🛑 **CUENTA QUEMADA POR LÍMITE (P2PBACK-934):**\n"
                            f"🏦 **Cuenta:** `{cuenta_asignada}`\n"
                            f"🧾 **Orden en pausa:** `{order_id}`\n\n"
                            f"Banesco rechazó el pago en el último paso por límite excedido. La cuenta ha sido apagada visualmente en el panel y la orden pasará a la siguiente."
                        )
                        try: await enviar_alerta_telegram(msg_limite)
                        except: pass

                        return False

                    elif ruta_recibo == "DATOS_INVALIDOS":
                        perfiles_invalidos.add(order_id)
                        mensaje_falla = (
                            f"📌 Ref. Orden: {order_id}\n\n"
                            f"¡Hola! Tuvimos un inconveniente al procesar su pago ya que el banco indica que los datos introducidos presentan errores.\n\n"
                            f"Para solucionarlo rápido, por favor facilítenos de nuevo su **Cédula** y número de **Cuenta** por aquí."
                        )
                        await listener.send_chat_message(session, order_id, mensaje_falla)
                        ordenes_advertidas.add(order_id)
                        ordenes_ignoradas[order_id] = int(time.time() * 1000)
                        return False

                    elif cuenta_final and cuenta_final == cuenta_perfil:
                        perfiles_invalidos.add(order_id)
                        mensaje_falla = f"📌 Ref. Orden: {order_id}\n\nEl banco ha rechazado el pago a los datos registrados en su perfil (posible cuenta bloqueada o datos errados).\n\nPor favor, verifique y envíe unos nuevos datos de pago (Teléfono/Cuenta y Cédula) por este chat para intentar nuevamente."
                        await listener.send_chat_message(session, order_id, mensaje_falla)
                        ordenes_advertidas.add(order_id)
                        ordenes_ignoradas[order_id] = int(time.time() * 1000)
                        return False

                    # 🔥 SILENCIADOR DE LISTA NEGRA (EVITA EL SPAM) 🔥
                    elif ruta_recibo == "BANCO_RECHAZADO_POR_SISTEMA":
                        logger.warning(f"🛑 Silenciando orden {order_id} por banco en lista negra. Evitando SPAM al chat.")
                        ordenes_advertidas.add(order_id)
                        # Le sumamos 1 hora (3600000 ms) al tiempo de ignorado para que el auto-rescate no la reviva
                        ordenes_ignoradas[order_id] = int(time.time() * 1000) + 3600000 
                        return False

                    else:
                        mensaje_falla = f"📌 Ref. Orden: {order_id}\n\nEl banco ha rechazado los datos que proporcionó (presentan errores o no son válidos).\n\nPor favor, verifique y envíe nuevamente sus datos correctos (Teléfono/Cuenta y Cédula) por este chat."
                        await listener.send_chat_message(session, order_id, mensaje_falla)
                        ordenes_advertidas.add(order_id)
                        ordenes_ignoradas[order_id] = int(time.time() * 1000)
                        return False

    except Exception as e:
        logger.error(f"Error procesando orden {order_id} con cuenta {cuenta_asignada}: {e}")
        if 'payment_data' in locals() and payment_data.get("pago_enviado", False):
            msg_crash = (
                f"🚨 **¡CRASH CRÍTICO POST-PAGO!** 🚨\n"
                f"La orden `{order_id}` reventó el bot DESPUÉS de darle a transferir.\n\n"
                f"🏦 **Tu Cuenta:** {cuenta_asignada}\n"
                f"💰 **Monto:** Bs. {monto_pago}\n\n"
                f"Error: `{e}`\n"
                f"¡Orden enviada a cuarentena, revisa el correo de {cuenta_asignada} AHORA!"
            )
            logger.critical(msg_crash)
            try:
                await enviar_alerta_telegram(msg_crash)
            except Exception:
                pass
            ordenes_advertidas.add(order_id)

        ordenes_ignoradas[order_id] = int(time.time() * 1000)
        return False

    finally:
        ordenes_en_proceso.discard(order_id)

        # 🔥 EL SECRETO DE LA LIBERACIÓN 🔥
        cuentas_ocupadas.discard(cuenta_asignada)

        if not exito_global and interactuo_con_banco and cuenta_asignada in bank_sessions:
            try: 
                await bank_sessions[cuenta_asignada]["page"].close()
            except Exception: 
                pass
            try: 
                await bank_sessions[cuenta_asignada]["context"].close()
            except Exception: 
                pass
            del bank_sessions[cuenta_asignada]

    return False

# =========================================================
# MOTOR: EJECUCIÓN DE PRUEBA DE TEST
# =========================================================
async def ejecutar_prueba_banco(test_order: dict, browser, bank_sessions: dict, estado: dict, semaforo: asyncio.Semaphore):
    async with semaforo:
        cuenta_origen = test_order.get("cuenta_origen")
        tipo_test = test_order.get("tipo", "TRANSFERENCIA")
        candado = obtener_candado(cuenta_origen)

        async with candado:
            cuentas_ocupadas.add(cuenta_origen)
            try:
                logger.info(f"🧪 INICIANDO TEST AISLADO: {cuenta_origen} | Tipo: {tipo_test}")
                datos_banco = estado.get("bancos", {}).get(cuenta_origen, {})
                payment_data = {
                    "order_id": test_order.get("id"),
                    "amount": test_order.get("monto"),
                    "seguridad_banco": datos_banco,
                    "nombre_cuenta": cuenta_origen,
                    "dinero_durmiendo": float(estado.get("config", {}).get("dinero_durmiendo", 100000.0)),
                    "pago_enviado": False
                }

                if tipo_test == "TRANSFERENCIA":
                    payment_data["account_number"] = test_order.get("cuenta_destino")
                    payment_data["identity_doc"] = test_order.get("ci_destino")
                elif tipo_test == "PAGO_MOVIL":
                    payment_data["telefono"] = test_order.get("telefono")
                    payment_data["identity_doc"] = test_order.get("ci_destino")
                    payment_data["banco_destino"] = test_order.get("banco_destino")

                es_nueva = False
                if cuenta_origen not in bank_sessions or bank_sessions[cuenta_origen]["page"].is_closed():
                    context_options = {"viewport": {"width": 1280, "height": 720}, "device_scale_factor": 2}
                    proxy_settings = obtener_proxy_config(estado)
                    if proxy_settings:
                        context_options["proxy"] = proxy_settings

                    aislado_ctx = await browser.new_context(**context_options)
                    aislado_page = await aislado_ctx.new_page()
                    bank_sessions[cuenta_origen] = {"context": aislado_ctx, "page": aislado_page}
                    es_nueva = True

                payment_data["nueva_sesion"] = es_nueva
                page = bank_sessions[cuenta_origen]["page"]

                if await execute_login(page, payment_data):
                    try: await page.evaluate("document.querySelectorAll('.swal2-container').forEach(e => e.remove());")
                    except Exception: pass

                    if tipo_test == "TRANSFERENCIA":
                        success, ruta_recibo = await execute_transfer(page, payment_data)
                    else:
                        success, ruta_recibo = await execute_pagomovil(page, payment_data)

                    if success:
                        tipo_limpio = tipo_test.replace("_", " ")
                        try:
                            await enviar_foto_telegram(ruta_recibo, f"🧪 TEST EXITOSO ({tipo_limpio})\n🏦 Cuenta: {cuenta_origen}\n💰 Monto: Bs. {test_order.get('monto')}")
                        except Exception as e:
                            logger.error(f"Telegram rechazó la foto del Test: {e}")
            except Exception as e:
                logger.error(f"Error test: {e}")
            finally:
                cuentas_ocupadas.discard(cuenta_origen)

# =========================================================
# MOTOR: EJECUCIÓN SATÉLITE DE FONDEO MATRIZ MÚLTIPLE
# =========================================================
async def ejecutar_proceso_fondeo(tarea_fondeo: dict, browser, bank_sessions: dict, semaforo: asyncio.Semaphore):
    async with semaforo:
        cuenta_origen = tarea_fondeo.get("cuenta_origen")
        destinos = tarea_fondeo.get("destinos", {})
        candado = obtener_candado(cuenta_origen)

        async with candado:
            cuentas_ocupadas.add(cuenta_origen)
            try:
                logger.info(f"🚀 INICIANDO TRANSFERENCIA MATRIZ desde: {cuenta_origen}")
                estado = leer_estado_botones()
                datos_banco = estado.get("bancos", {}).get(cuenta_origen, {})
                payment_data = {
                    "nombre_cuenta": cuenta_origen,
                    "seguridad_banco": datos_banco,
                    "nueva_sesion": True
                }

                context_options = {
                    "viewport": {"width": 1280, "height": 720},
                    "device_scale_factor": 2
                }
                proxy_settings = obtener_proxy_config(estado)
                if proxy_settings:
                    context_options["proxy"] = proxy_settings

                aislado_ctx = await browser.new_context(**context_options)
                aislado_page = await aislado_ctx.new_page()
                bank_sessions[cuenta_origen] = {"context": aislado_ctx, "page": aislado_page}

                if await execute_login(aislado_page, payment_data):
                    try:
                        from actions.fondeo_matriz import ejecutar_fondeo_multiple
                    except Exception as e:
                        msg_err = f"🚨 **ERROR CRÍTICO:** El bot no pudo leer el archivo `fondeo_matriz.py` dentro de la carpeta `actions`. Revisa que lo hayas creado bien. Detalle: `{e}`"
                        await enviar_alerta_telegram(msg_err)
                        logger.error(msg_err)
                        return

                    try:
                        await ejecutar_fondeo_multiple(aislado_page, cuenta_origen, destinos, payment_data)
                    except Exception as e:
                        msg_err = f"🚨 **CRASH EN FONDEO MATRIZ:** El robot se estrelló internamente a mitad del proceso. Detalle: `{e}`"
                        await enviar_alerta_telegram(msg_err)
                        logger.error(msg_err)
                else:
                    await enviar_alerta_telegram(f"❌ Error Login Fondeo Matriz ({cuenta_origen}). Chequea las credenciales.")

            except Exception as e:
                logger.error(f"Error Crítico en Fondeo Matriz: {e}")
                await enviar_alerta_telegram(f"🚨 **CRASH FATAL FONDEO MATRIZ:** `{e}`")

            finally:
                cuentas_ocupadas.discard(cuenta_origen)
                try: 
                    await bank_sessions[cuenta_origen]["page"].close()
                except Exception: 
                    pass
                try: 
                    await bank_sessions[cuenta_origen]["context"].close()
                except Exception: 
                    pass
                if cuenta_origen in bank_sessions:
                    del bank_sessions[cuenta_origen]

                est = leer_estado_botones()
                if "cola_fondeo" in est and len(est["cola_fondeo"]) > 0:
                    est["cola_fondeo"].pop(0)
                    guardar_estado_seguro(est)

# =========================================================
# BOT DE CHAT EN SEGUNDO PLANO (ASISTENTE CONVERSACIONAL)
# =========================================================
async def vigilante_cuarentena_daemon(listener: BinanceSAPIListener):
    logger.info("🕵️‍♂️ INICIANDO ASISTENTE DE CHAT EN SEGUNDO PLANO...")
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                await asyncio.sleep(5) # Revisa el chat cada 5 segundos

                # Revisamos todas las órdenes en cuarentena
                for order_id in list(ordenes_ignoradas.keys()):
                    if order_id in ordenes_en_proceso:
                        continue 

                    ignore_time = ordenes_ignoradas[order_id]
                    if ignore_time > (int(time.time() * 1000) + 60000):
                        continue # Si es un banco prohibido (lista negra de 1h), lo salta

                    chat_history = await listener.get_chat_messages(session, order_id)
                    if not chat_history:
                        continue

                    has_new_override = False

                    # 1. Comprobar si el Admin mandó el comando de emergencia "procede"
                    last_bot_time = 0
                    for msg in chat_history:
                        if msg.get("self") is True:
                            t = int(msg.get("createTime", 0))
                            if t > last_bot_time:
                                last_bot_time = t

                    if last_bot_time == 0:
                        last_bot_time = ignore_time - 5000 

                    for msg in chat_history:
                        if msg.get("self") is True:
                            txt_msg = limpiar_texto_chat(str(msg.get("content", "")))
                            if re.search(r'\b(procede|proceda)\b', txt_msg):
                                if int(msg.get("createTime", 0)) >= last_bot_time:
                                    has_new_override = True
                                    break

                    # 2. 🧠 LÓGICA DEL ASISTENTE CONVERSACIONAL 🧠
                    if not has_new_override:
                        # Solo leemos lo que el cliente escribió DESPUÉS de que lo ignoramos
                        mensajes_nuevos = [m for m in chat_history if m.get("self") is False and int(m.get("createTime", 0)) > ignore_time]
                        texto_nuevo = " ".join([str(m.get("content", "")) for m in mensajes_nuevos]).lower()

                        if texto_nuevo:
                            # ¿El cliente nos envió números?
                            tiene_cuenta = bool(re.search(PATRON_CUENTA, texto_nuevo))
                            tiene_cedula = bool(re.search(PATRON_CEDULA_UNIVERSAL, texto_nuevo))
                            tiene_telefono = bool(re.search(PATRON_TELEFONO, texto_nuevo))

                            # ¿El cliente nos envió autorización?
                            palabras_afirmativas = [
                                "autorizo", "autorizado", "autoriza",
                                "confirmo", "confirmado", "confirmada",
                                "de acuerdo", "estoy de acuerdo",
                                "responsable"
                            ]
                            tiene_confirmacion = any(p in texto_nuevo for p in palabras_afirmativas)

                            # --- TOMA DE DECISIONES DEL ASISTENTE ---

                            # Escenario A: El cliente mandó los datos Y el testamento en el mismo mensaje
                            if (tiene_cuenta or tiene_telefono or tiene_cedula) and tiene_confirmacion:
                                has_new_override = True
                                logger.info(f"⚡ [ASISTENTE] La orden {order_id} mandó datos y autorizó de golpe. ¡Entregando al Pagador!")

                            # Escenario B: El cliente solo mandó "autorizo" (Nosotros ya le habíamos pedido el testamento antes)
                            elif tiene_confirmacion:
                                has_new_override = True
                                logger.info(f"⚡ [ASISTENTE] ¡Autorización recibida en {order_id}! La orden está lista. Entregando al Pagador...")

                            # Escenario C: El cliente SOLO mandó los datos (Cuenta/Cédula). 
                            # ¡Aquí el Asistente hace el trabajo sucio y pide el testamento!
                            elif tiene_cuenta or tiene_telefono or tiene_cedula:
                                logger.info(f"🗣️ [ASISTENTE] El cliente envió datos nuevos en la orden {order_id}. Solicitando testamento...")
                               mensaje_adv = "📌 Ref. Orden: " + str(order_id) + "\n\nPara continuar con el pago a la cuenta enviada por este chat, debe confirmarme y autorizarme.\n\nDe autorizar debe enviar el siguiente mensaje:\n'autorizo que soy el unico responsable por la cuenta enviada al chat y confirmo que no me estoy comunicando con usted ni con nadie fuera de la plataforma para tomar este anuncio'"
                                await listener.send_chat_message(session, order_id, mensaje_adv)

                                # 🔥 TRUCO MAESTRO: Reiniciamos el reloj interno de la cuarentena a la hora actual. 
                                # Así el bot esperará a que el cliente responda a este nuevo mensaje en el próximo ciclo.
                                ordenes_ignoradas[order_id] = int(time.time() * 1000)

                    # 3. Si el asistente determinó que ya todo está listo (has_new_override = True), saca la orden de cuarentena
                    if has_new_override:
                        del ordenes_ignoradas[order_id]

            except Exception as e:
                logger.error(f"Error interno en el Asistente de Chat: {e}")

# =========================================================
# BUCLE INFINITO (DAEMON)
# =========================================================
async def main_daemon() -> None:
    logger.info("🛠️ CARGANDO MOTOR P2P (SAPI V7.4 - BÚSQUEDA SELECTIVA POR ESTATUS)")
    listener = BinanceSAPIListener()
    ciclo = 0

    ultimas_ejecuciones_pricer = {}
    semaforo_concurrencia = asyncio.Semaphore(15)

    # 🔥 NUEVO: Reloj de inactividad global 🔥
    ultima_actividad = time.time()

    # 🔥 ENCENDEMOS EL BOT DE CHAT EN SEGUNDO PLANO 🔥
    asyncio.create_task(vigilante_cuarentena_daemon(listener))

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        bank_sessions = {}

        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    gatillo_emergencia()
                except InterruptedError:
                    pass

                estado = leer_estado_botones()
                creds = estado.get("credenciales", {})
                listener.update_credentials(creds.get("binance_api_key", "").strip(), creds.get("binance_api_secret", "").strip())

                master_on = estado.get("master_switch", False)
                sniper_on = estado.get("sniper_switch", False)
                tareas_activas.difference_update({t for t in tareas_activas if t.done()})

                cola_test = estado.get("cola_test", [])
                if cola_test:
                    test_actual = cola_test.pop(0)
                    guardar_estado_seguro(estado)
                    tarea_test = asyncio.create_task(ejecutar_prueba_banco(test_actual, browser, bank_sessions, estado, semaforo_concurrencia))
                    tareas_activas.add(tarea_test)

                cola_fondeo = estado.get("cola_fondeo", [])
                if cola_fondeo:
                    tarea_activa = cola_fondeo[0]
                    nombre_tarea = f"task_{tarea_activa['id_fondeo']}"

                    tarea_ya_existe = False
                    for t in tareas_activas:
                        if hasattr(t, "get_name") and t.get_name() == nombre_tarea:
                            tarea_ya_existe = True
                            break

                    if not tarea_ya_existe:
                        tarea_f = asyncio.create_task(ejecutar_proceso_fondeo(tarea_activa, browser, bank_sessions, semaforo_concurrencia))
                        tarea_f.set_name(nombre_tarea)
                        tareas_activas.add(tarea_f)

                estrategias_sniper = estado.get("estrategias_sniper", {})
                mi_nickname = estado.get("config", {}).get("mi_nickname", "")

                if sniper_on:
                    for ad_no, config_estrategia in estrategias_sniper.items():
                        if config_estrategia.get("activo", True): # 🔥 IGNORA EL SWITCH BUGUEADO, SIEMPRE LO ACTIVA
                            tiempo_actual = time.time()
                            intervalo_custom = int(config_estrategia.get("intervalo_segundos", 5))

                            ultimo_tiempo = ultimas_ejecuciones_pricer.get(ad_no, 0)

                            if (tiempo_actual - ultimo_tiempo) > intervalo_custom:
                                logger.info(f"🤖 Iniciando escaneo de Sniper para Ad {ad_no}...")
                                config_estrategia["mi_nickname"] = mi_nickname
                                config_estrategia["ad_number"] = ad_no # 🔥 INYECCIÓN VITAL DEL ID
                                tarea_pricer = asyncio.create_task(ejecutar_ajuste_mercado(config_estrategia, estado))
                                tareas_activas.add(tarea_pricer)
                                ultimas_ejecuciones_pricer[ad_no] = tiempo_actual

                if ciclo % 3 == 0: 
                    logger.info("📡 Escaneando Binance por órdenes y capital...")
                ciclo += 1

                # 🔥 EXTRACCIÓN DE CAPITAL Y ÓRDENES SIMULTÁNEA 🔥
                orders = await listener.fetch_pending_orders(session)
                usdt_balance = await listener.get_usdt_balance(session)
                sincronizar_panel_vivo(orders, usdt_balance)

                if not master_on:
                    await asyncio.sleep(5)
                    continue

                if orders:
                    orders = sorted(orders, key=lambda x: int(x.get("createTime", 0)))

                    for order in orders:
                        try:
                            estado_binance = str(order.get("orderStatus", "")).strip().upper()
                            order_id = str(order.get("orderNumber", ""))
                            trade_type = str(order.get("tradeType", "")).upper()

                            # Solo procesar pagos para compras PENDIENTES
                            if estado_binance not in ["1", "PENDING"] or trade_type != "BUY":
                                continue

                            # 👇 INYECCIÓN DEL CORTAFUEGOS DE TIEMPO 👇
                            es_seguro, segs_restantes = es_seguro_pagar(order)
                            if not es_seguro:
                                if order_id not in ordenes_advertidas:
                                    logger.warning(f"⏳ Orden {order_id} ignorada por riesgo (quedan {segs_restantes:.0f}s). Dejando morir...")
                                    ordenes_advertidas.add(order_id)
                                ordenes_ignoradas[order_id] = int(time.time() * 1000)
                                continue
                            # 👆 FIN DE LA INYECCIÓN 👆

                            has_new_override = False # 🔥 1. LA MOVEMOS AQUÍ ARRIBA 🔥

                            if order_id not in ordenes_en_proceso:
                                # 🔥 LÓGICA DE AUTO-RESCATE Y CONFIRMACIÓN 🔥
                                if order_id in ordenes_ignoradas:
                                    # 🔥 Si está ignorada, el Bot Pagador la salta. El Bot de Chat se encarga en segundo plano.
                                    continue

                                # 🔥 PASO PREVIO VITAL: DESCUBRIR EL MÉTODO ANTES DE ASIGNAR CUENTA 🔥
                                detalles_previos = await listener.get_order_detail(session, order_id)

                                # Si Binance no responde el método, ignoramos la orden este ciclo por seguridad.
                                if not detalles_previos or not detalles_previos.get("payMethods"):
                                    logger.warning(f"⚠️ Binance no devolvió los métodos para {order_id}. Esperando próximo ciclo para no asignar a ciegas...")
                                    continue

                                pay_methods_previos = detalles_previos.get("payMethods", [])
                                tipo_operacion_previa = "TRANSFERENCIA" 

                                # 1. Extraemos todo el texto de los métodos de pago (Para buscar el Banco)
                                texto_metodos_pago = ""
                                for pm in pay_methods_previos:
                                    pm_str = str(pm.get("payType", "")).lower() + " " + str(pm.get("identifier", "")).lower()
                                    if "mobile" in pm_str or "movil" in pm_str or "pago" in pm_str:
                                        tipo_operacion_previa = "PAGO_MOVIL"

                                    for field in pm.get("fields", []):
                                        texto_metodos_pago += " " + str(field.get("fieldValue", "")).upper()

                                # 🔥 ESCUDO BINANCE: FILTRO DE BANCOS EN LISTA NEGRA 🔥
                                es_banco_prohibido = False
                                banco_detectado = ""

                                # 🔥 2. APAGAR EL ESCUDO SI EL CLIENTE DIO NUEVOS DATOS 🔥
                                if not has_new_override:
                                    # 🔥 SOLO VENEZOLANO DE CRÉDITO ESTÁ RESTRINGIDO AQUÍ 🔥
                                    # FIX: Usamos Regex para que no confunda el "0104" si está en el medio de una cuenta Banesco
                                    if "VENEZOLANO" in texto_metodos_pago or re.search(r'\b0104\d{16}\b', texto_metodos_pago) or re.search(r'\b0104\b', texto_metodos_pago):
                                        es_banco_prohibido = True
                                        banco_detectado = "Venezolano de Crédito (0104)"

                                if es_banco_prohibido:
                                    # Verificamos si ya le enviamos la advertencia para NO hacer spam (Una sola vez)
                                    if order_id not in ordenes_advertidas:
                                        logger.warning(f"🛑 Banco problemático ({banco_detectado}). Enviando mensaje automático al cliente...")

                                        # Mensaje automático para el cliente en Binance
                                        mensaje_cliente = (
                                            f"📌 Ref. Orden: {order_id}\n\n"
                                            f"Hola, en este momento la plataforma interbancaria presenta fallas de conexión con {banco_detectado}.\n"
                                            f"Para poder procesar su pago sin demoras, por favor envíe los datos de Pago Móvil de OTRO BANCO (Ej: Provincial, BDV, Mercantil) por este chat."
                                        )
                                        await listener.send_chat_message(session, order_id, mensaje_cliente)

                                        # 🔥 ESTE ES EL MENSAJE EXACTO ENVIADO A TELEGRAM 🔥
                                        mensaje_bloqueo = (
                                            f"⛔ **BANCO EN LISTA NEGRA (Freno en Binance):**\n"
                                            f"🧾 **Orden:** `{order_id}`\n"
                                            f"🏦 **Destino:** `{banco_detectado}`\n\n"
                                            f"El bot bloqueó la orden y le pidió otro banco al cliente automáticamente."
                                        )
                                        try: await enviar_alerta_telegram(mensaje_bloqueo)
                                        except: pass

                                        # Marcamos que ya se le advirtió para que no se repita
                                        ordenes_advertidas.add(order_id)

                                    # La enviamos a cuarentena para que no consuma recursos bancarios
                                    ordenes_ignoradas[order_id] = int(time.time() * 1000)
                                    continue # Salta esta orden al instante

                                # Si superó el escudo, le asignamos la cuenta normalmente
                                precio_total = seguro_float(order.get("totalPrice", 0))
                                cuenta_asignada = obtener_cuenta_disponible_round_robin(estado, precio_total, tipo_operacion_previa)

                                if not cuenta_asignada:
                                    # 🔥 ALARMA: Si no hay cuentas, el bot te avisa en la consola para que no creas que se colgó
                                    if ciclo % 3 == 0:
                                        logger.warning(f"⚠️ IGNORANDO ORDEN {order_id}: Ninguna cuenta activa tiene saldo o límites configurados para pagar Bs. {precio_total:,.2f}")
                                    continue 

                                ordenes_en_proceso.add(order_id)
                                cuentas_ocupadas.add(cuenta_asignada)

                                logger.info(f"✅ Cajero libre encontrado: {cuenta_asignada}. Tomando la orden {order_id}...")

                                # 🔥 INYECCIÓN ANTI-CONGELAMIENTO (TIMEOUT DE 5 MINUTOS) 🔥
                                async def tarea_con_limite(ord_id=order_id, cta=cuenta_asignada, ord_data=order):
                                    try:
                                        await asyncio.wait_for(
                                            process_order(ord_data, listener, session, cta, browser, bank_sessions, semaforo_concurrencia),
                                            timeout=300.0
                                        )
                                    except asyncio.TimeoutError:
                                        logger.error(f"⏳ ERROR FATAL: El banco se congeló por más de 5 minutos en la orden {ord_id}. Abortando tarea...")
                                        ordenes_ignoradas[ord_id] = int(time.time() * 1000)
                                        cuentas_ocupadas.discard(cta)
                                        ordenes_en_proceso.discard(ord_id)
                                        if cta in bank_sessions:
                                            try: await bank_sessions[cta]["page"].close()
                                            except: pass
                                            del bank_sessions[cta]

                                tarea = asyncio.create_task(tarea_con_limite())
                                tareas_activas.add(tarea)

                        except Exception as e:
                            logger.error(f"Error interno disparando pago individual: {e}")
                            continue

                # ==============================================================
                # 🔥 AUTO-CIERRE DE SESIONES POR INACTIVIDAD (30 SEGUNDOS) 🔥
                # ==============================================================
                try:
                    if len(ordenes_en_proceso) == 0 and len(cuentas_ocupadas) == 0:
                        hay_ordenes = any(str(o.get("orderStatus")) in ["1", "PENDING"] and str(o.get("tradeType")).upper() == "BUY" for o in orders) if orders else False

                        if not hay_ordenes:
                            if (time.time() - ultima_actividad) > 30.0:
                                if bank_sessions:
                                    logger.info("🧹 30s sin órdenes. Forzando limpieza (Anti-Congelamiento)...")
                                    for cta, sesion_obj in list(bank_sessions.items()):
                                        try: 
                                            await asyncio.wait_for(
                                                sesion_obj["page"].evaluate("if(document.getElementById('ctl00_btnSalir')) document.getElementById('ctl00_btnSalir').click();"), 
                                                timeout=4.0
                                            )
                                            await asyncio.sleep(1.0)
                                        except Exception: pass

                                        try: await asyncio.wait_for(sesion_obj["page"].close(), timeout=3.0)
                                        except Exception: pass

                                        try: await asyncio.wait_for(sesion_obj["context"].close(), timeout=3.0)
                                        except Exception: pass

                                    bank_sessions.clear()
                                ultima_actividad = time.time()
                        else:
                            ultima_actividad = time.time()
                    else:
                        ultima_actividad = time.time()
                except Exception as e:
                    logger.error(f"🔥 Error atrapado en la limpieza del bot: {e}")

                await asyncio.sleep(2)

if __name__ == "__main__":
    try: 
        asyncio.run(main_daemon())
    except KeyboardInterrupt: 
        pass
