"""
Módulo de Fondeo Múltiple (Matriz -> Operadoras)
Reutiliza la lógica de automatización base de Banesco.
(VERSIÓN RÁFAGA CONTINUA + MICRO-PAUSA ORGÁNICA + ETIQUETAS CORREGIDAS)
"""
import asyncio
import logging
import time
import random
import json
import os

try:
    from integrations.telegram_notifier import enviar_alerta_telegram, enviar_foto_telegram
except ImportError:
    async def enviar_alerta_telegram(msg: str):
        logging.info(f"TELEGRAM: {msg}")
    async def enviar_foto_telegram(foto: str, msg: str):
        logging.info(f"TELEGRAM FOTO: {msg}")

logger = logging.getLogger(__name__)

def verificar_freno_emergencia():
    """Revisa en tiempo real si existe el archivo de freno de emergencia."""
    if os.path.exists("data/freno_fondeo.flag"):
        return True
    try:
        if os.path.exists("data/estado_bot.json"):
            with open("data/estado_bot.json", "r", encoding="utf-8") as f:
                estado = json.load(f)
            return estado.get("detener_fondeo", False)
    except Exception: pass
    return False

def resetear_freno_emergencia():
    """Devuelve el botón a su estado normal eliminando el archivo bandera."""
    try:
        if os.path.exists("data/freno_fondeo.flag"):
            os.remove("data/freno_fondeo.flag")
            
        if os.path.exists("data/estado_bot.json"):
            with open("data/estado_bot.json", "r", encoding="utf-8") as f:
                estado = json.load(f)
            if estado.get("detener_fondeo", False):
                estado["detener_fondeo"] = False
                ruta_temp = "data/estado_bot_tmp.json"
                with open(ruta_temp, "w", encoding="utf-8") as f:
                    json.dump(estado, f, ensure_ascii=False, indent=4)
                os.replace(ruta_temp, "data/estado_bot.json")
    except Exception: pass

# 🔥 NUEVO: EL PERRO GUARDIÁN KAMIKAZE 🔥
async def perro_guardian_freno(page):
    """Vigila la bandera 2 veces por segundo. Si la detecta, MATA el navegador en pleno vuelo."""
    while True:
        if verificar_freno_emergencia():
            logger.warning("🚨 [GUARDIÁN] Guillotina detectada en pleno vuelo. Abortando motor Banesco instantáneamente...")
            try:
                # Intento fugaz de matar el token en el servidor para evitar sesiones fantasmas
                await page.goto("https://www.banesconline.com/mantis/Website/Login.aspx", timeout=1500)
            except: pass
            try:
                # Destruimos el contexto. Esto provoca un crash inmediato en transfer_banesco.py
                await page.context.close()
            except: pass
            break
        await asyncio.sleep(0.5)

async def ejecutar_fondeo_multiple(page, cuenta_origen: str, destinos: dict, payment_data: dict):
    """
    Ejecuta múltiples transferencias desde la Matriz hacia las cuentas destino.
    """
    logger.info(f"🏦 Iniciando Fondeo Múltiple desde {cuenta_origen}. Destinos a recargar: {len(destinos)}")
    await enviar_alerta_telegram(f"🚀 **INICIANDO FONDEO MÚLTIPLE**\nEmisor: `{cuenta_origen}`\nCuentas a recargar: {len(destinos)}")

    # 🔥 LANZAMOS AL GUARDIÁN A VIGILAR EN PARALELO AL FONDEO 🔥
    tarea_guardian = asyncio.create_task(perro_guardian_freno(page))
    
    total_destinos = len(destinos)
    contador = 0
    fondeo_abortado = False
    
    from actions.transfer_banesco import execute_transfer

    try:
        for alias, datos_destino in destinos.items():
            if verificar_freno_emergencia():
                fondeo_abortado = True
                break
                
            contador += 1
            monto = datos_destino.get("monto", "0")
            cuenta = datos_destino.get("cuenta", "")
            cedula = datos_destino.get("cedula", "")
            tipo_doc = datos_destino.get("tipo_doc", "V")
            
            logger.info(f"[{contador}/{total_destinos}] Fondeando a {alias} ({cuenta}) -> {monto} Bs")
            
            datos_transferencia = payment_data.copy() if payment_data else {}
            datos_transferencia["account_number"] = cuenta
            datos_transferencia["identity_doc"] = f"{tipo_doc}{cedula}"
            datos_transferencia["amount"] = str(monto).replace(".", ",")
            datos_transferencia["order_id"] = "FONDEO_MATRIZ"

            try:
                resultado = await execute_transfer(page, datos_transferencia)
                if resultado is None:
                    success, ruta_recibo = True, None
                elif isinstance(resultado, tuple):
                    success, ruta_recibo = resultado
                else:
                    success, ruta_recibo = resultado, None

                if success:
                    logger.info(f"✅ Fondeo a {alias} EXITOSO. Disparando foto en segundo plano...")
                    if ruta_recibo:
                        asyncio.create_task(enviar_foto_telegram(ruta_recibo, f"✅ **FONDEO EXITOSO**\nDestino: {alias}\nMonto: {monto} Bs"))
                    else:
                        asyncio.create_task(enviar_alerta_telegram(f"✅ **FONDEO EXITOSO**\nDestino: {alias}\nMonto: {monto} Bs"))
                else:
                    logger.error(f"❌ Falló el fondeo a {alias}.")
                    asyncio.create_task(enviar_alerta_telegram(f"❌ **FALLÓ EL FONDEO** a {alias}."))
                    
            except Exception as e:
                if verificar_freno_emergencia():
                    logger.warning("Crash interceptado: El navegador fue destruido por el Perro Guardián.")
                    fondeo_abortado = True
                    break
                else:
                    logger.error(f"Error crítico enviando a {alias}: {e}")
                    asyncio.create_task(enviar_alerta_telegram(f"🚨 **ERROR CRÍTICO fondeando a {alias}:** {e}"))

            # MICRO-PAUSA ORGÁNICA (El guardián vigila durante la espera)
            if contador < total_destinos:
                tiempo_descanso = random.randint(3, 7)
                logger.info(f"⏳ Recarga completada. Avanzando al siguiente destino en {tiempo_descanso}s...")
                for _ in range(tiempo_descanso * 2):
                    if verificar_freno_emergencia():
                        fondeo_abortado = True
                        break
                    await asyncio.sleep(0.5)
            
            if fondeo_abortado:
                break
    finally:
        # Apagamos al guardián si el ciclo terminó de forma natural
        if not tarea_guardian.done():
            tarea_guardian.cancel()

    if fondeo_abortado or verificar_freno_emergencia():
        msg_abort = f"🛑 **FONDEO MATRIZ ABORTADO (CORTE INMEDIATO)**\nEl proceso desde `{cuenta_origen}` fue fulminado a petición del operador."
        logger.warning("Fondeo interrumpido. Redirigiendo a limpieza...")
        await enviar_alerta_telegram(msg_abort)
    else:
        logger.info("🏁 Proceso de Fondeo Múltiple Finalizado. Iniciando protocolo de cierre seguro...")
        await enviar_alerta_telegram(f"🏁 **FONDEO MÚLTIPLE FINALIZADO**\nTodas las transferencias programadas desde `{cuenta_origen}` han sido procesadas.")

    # 🔥 PROTOCOLO DE CIERRE DE SESIÓN (ATAQUE DIRECTO AL SERVIDOR) 🔥
    try:
        logger.info("🚪 Destruyendo sesión activa en los servidores de Banesco...")
        try:
            await page.evaluate("window.top.location.href = 'https://www.banesconline.com/mantis/Website/Login.aspx';")
        except:
            await page.goto("https://www.banesconline.com/mantis/Website/Login.aspx", timeout=4000)
            
        await asyncio.sleep(1.5)
        logger.info("✅ Sesión cerrada y token invalidado con éxito.")
    except Exception as e:
        pass
        
    logger.info(f"🔥 QUEMANDO NAVEGADOR Y CONTEXTO DE {cuenta_origen} PARA LIBERAR RAM 🔥")
    try:
        await page.context.close()
    except: pass

    # 🔥 EL BOT DEVUELVE EL PANEL A LA NORMALIDAD AL MORIR 🔥
    try:
        if os.path.exists("data/estado_bot.json"):
            with open("data/estado_bot.json", "r", encoding="utf-8") as f:
                estado = json.load(f)
            estado["cola_fondeo"] = []
            estado["detener_fondeo"] = False
            ruta_temp = "data/estado_bot_tmp.json"
            with open(ruta_temp, "w", encoding="utf-8") as f:
                json.dump(estado, f, ensure_ascii=False, indent=4)
            os.replace(ruta_temp, "data/estado_bot.json")
            logger.info("✅ Panel de control liberado y listo para nuevas órdenes.")
    except Exception as e:
        logger.error(f"No se pudo limpiar la cola en el panel: {e}")
