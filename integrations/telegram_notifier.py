"""
Módulo de Notificaciones de Telegram.
(Lectura directa desde base de datos local para evitar desincronización)
"""
import os
import json
import aiohttp
import logging

logger = logging.getLogger(__name__)
ESTADO_FILE = "data/estado_bot.json"

def _obtener_credenciales(mensaje: str):
    try:
        with open(ESTADO_FILE, "r", encoding="utf-8") as f: # 🔥 AQUÍ ESTÁ LA MAGIA (encoding="utf-8")
            estado = json.load(f)
            creds = estado.get("credenciales", {})
            bot_token = creds.get("telegram_bot_token", "").strip()
            
            msg_lower = mensaje.lower()
            # Enrutamiento Inteligente: Agregamos ⚠️, revisión, advertencia, alerta, etc.
            if ("🚨" in mensaje or "❌" in mensaje or "⚠️" in mensaje or 
                "error" in msg_lower or "falló" in msg_lower or 
                "revisión" in msg_lower or "revision" in msg_lower or 
                "advertencia" in msg_lower or "alerta" in msg_lower or
                "cancelada" in msg_lower or "abortado" in msg_lower):
                chat_id = creds.get("telegram_chat_id_errores", "").strip()
            else:
                chat_id = creds.get("telegram_chat_id_exitos", "").strip()
                
            return bot_token, chat_id
    except Exception as e:
        logger.error(f"Error interno leyendo JSON para Telegram: {e}")
        return "", ""

async def enviar_alerta_telegram(mensaje: str) -> bool:
    bot_token, chat_id = _obtener_credenciales(mensaje)
    
    if not bot_token or not chat_id:
        logger.warning(f"⚠️ Telegram silenciado: Faltan credenciales en la Configuración del Panel. Mensaje ignorado: {mensaje[:30]}...")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": mensaje, "parse_mode": "Markdown"}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=15) as response:
                if response.status != 200:
                    err = await response.text()
                    logger.error(f"❌ API de Telegram rechazó el mensaje: {err}")
                return response.status == 200
    except Exception as e:
        logger.error(f"❌ Fallo de conexión enviando alerta a Telegram: {e}")
        return False

async def enviar_foto_telegram(ruta_foto: str, mensaje: str) -> bool:
    bot_token, chat_id = _obtener_credenciales(mensaje)
    
    if not bot_token or not chat_id:
        logger.warning("⚠️ Telegram silenciado: Faltan credenciales en la Configuración del Panel.")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    
    try:
        async with aiohttp.ClientSession() as session:
            with open(ruta_foto, "rb") as f:
                form = aiohttp.FormData()
                form.add_field("chat_id", chat_id)
                form.add_field("caption", mensaje)
                form.add_field("parse_mode", "Markdown")
                form.add_field("photo", f)
                
                async with session.post(url, data=form, timeout=30) as response:
                    if response.status != 200:
                        err = await response.text()
                        logger.error(f"❌ API de Telegram rechazó la foto: {err}")
                    return response.status == 200
    except Exception as e:
        logger.error(f"❌ Fallo de conexión enviando foto a Telegram: {e}")
        return False
