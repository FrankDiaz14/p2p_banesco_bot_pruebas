"""
Módulo Exclusivo de Transferencias Banesco.
(CAZADOR DINÁMICO v3 + CLICS JS BLINDADOS + RE-CLICKER DE EMERGENCIA + DETECTOR DE DATOS INVÁLIDOS + LIMPIEZA DE RECIBO)
"""

import asyncio
import logging
import time
import os
import re
import json
import random  # 🔥 NUEVO: ADN Humano para clics y tecleos
from typing import Tuple
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError
from integrations.otp_reader import OTPReader
from integrations.telegram_notifier import enviar_alerta_telegram, enviar_foto_telegram

logger = logging.getLogger(__name__)

# --- MEMORIA RAM GLOBAL ---
CACHE_OTP_SESIONES = {}

def actualizar_saldo_json(cuenta: str, saldo: float):
    """Guarda el último saldo extraído en el archivo maestro para que el panel lo muestre."""
    ruta = "data/estado_bot.json"
    if not os.path.exists(ruta):
        return

    # 🔥 FIX: Bucle de 3 intentos para evitar WinError 32 y WinError 5 por concurrencia
    for intento in range(3):
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                est = json.load(f)
            
            if "saldos" not in est:
                est["saldos"] = {}
            est["saldos"][cuenta] = saldo
            
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump(est, f, ensure_ascii=False, indent=4)
            break  # Si el guardado fue exitoso, sale del bucle
        
        except Exception as e:
            if intento == 2:
                logger.error(f"Error definitivo actualizando saldo en JSON tras 3 intentos: {e}")
            else:
                time.sleep(0.1) # Espera 100ms antes de intentar de nuevo si el archivo está bloqueado

async def find_element_in_frames(page: Page, selector: str, timeout: int = 25000):
    start_time = time.time()
    while (time.time() - start_time) < (timeout / 1000.0):
        try:
            for frame in page.frames:
                loc = frame.locator(selector).first
                if await loc.is_visible():
                    return loc
        except Exception:
            pass
        await asyncio.sleep(0.1)
    raise PlaywrightTimeoutError(f"Timeout: Elemento {selector} no encontrado.")

async def organic_mouse_move_and_click(page: Page, selector: str) -> None:
    # 🔥 DESTRUCTOR DE POPUPS GLOBAL: Borra cualquier ventana atravesada (swal2) antes de hacer clic
    try:
        await page.evaluate("document.querySelectorAll('.swal2-container, .modal, .modal-backdrop, .ui-widget-overlay').forEach(e => e.remove());")
    except: pass

    target_locator = await find_element_in_frames(page, selector)
    
    # 🔥 ADN HUMANO: Pausa milimétrica al azar (entre 0.05 y 0.2 segundos)
    await asyncio.sleep(random.uniform(0.05, 0.2)) 
    
    # 🔥 Inyección JS Brutal (Asegura el clic aunque la UI de Banesco tenga lag)
    try:
        await target_locator.evaluate("(nodo) => nodo.click()")
    except:
        await target_locator.hover()
        await asyncio.sleep(0.2)
        await target_locator.click(force=True, delay=random.randint(50, 150))

async def type_organically(page: Page, selector: str, text: str) -> None:
    # Destruir popups por si acaso
    try: await page.evaluate("document.querySelectorAll('.swal2-container, .modal').forEach(e => e.remove());")
    except: pass

    target_locator = await find_element_in_frames(page, selector)
    try:
        await target_locator.click(force=True)
        await target_locator.clear()
        
        # 🔥 ADN HUMANO: Escribe a una velocidad ligeramente distinta en cada letra
        retraso_humano = random.randint(10, 45) 
        await target_locator.press_sequentially(text, delay=retraso_humano)
    except Exception:
        pass

    await target_locator.evaluate(f"""(nodo) => {{
        nodo.focus();
        nodo.value = '{text}';
        nodo.dispatchEvent(new Event('input', {{ bubbles: true }}));
        nodo.dispatchEvent(new Event('change', {{ bubbles: true }}));
        nodo.blur();
    }}""")

async def execute_transfer(page: Page, payment_data: dict) -> Tuple[bool, str]:
    # 🔥 FILTRO ANTI-3-DECIMALES DE BINANCE (CORREGIDO) 🔥
    monto_crudo = str(payment_data.get("amount", "0")).replace(",", ".")
    if "." in monto_crudo:
        partes = monto_crudo.split(".")
        if len(partes[1]) > 2:
            monto_crudo = f"{partes[0]}.{partes[1][:2]}" 
    payment_data["amount"] = monto_crudo.replace(".", ",")

    ruta_captura_final = ""
    cuenta_nombre = str(payment_data.get("nombre_cuenta", "Desconocida"))
    order_id = str(payment_data.get("order_id", "N/A"))

    if payment_data.get("nueva_sesion"):
        CACHE_OTP_SESIONES.pop(cuenta_nombre, None)
        logger.info(f"🧹 Nueva sesión detectada para {cuenta_nombre}. Caché de OTP limpiado. Se requerirá buscar uno nuevo.")

    try:
        logger.info("--- INICIANDO MÓDULO DE PAGO ---")
        if "FONDEO" not in order_id:
            await enviar_alerta_telegram(f"💸 **Fase 5:** Banesco listo (`{cuenta_nombre}`). Validando datos para orden `{order_id}`...")

        cuenta_raw = payment_data.get("account_number", "")
        cuenta = "".join(filter(str.isdigit, cuenta_raw))

        logger.info(f"Validando número de cuenta destino: {cuenta}")
        if not cuenta.startswith("0134") or len(cuenta) != 20:
            error_msg = (
                f"❌ **ERROR EN TRANSFERENCIA (Validación):**\n"
                f"🏦 **Cuenta Origen:** `{cuenta_nombre}`\n"
                f"🧾 **Orden:** `{order_id}`\n\n"
                f"El número `{cuenta_raw}` no cumple con el formato requerido."
            )
            logger.error(error_msg)
            await enviar_alerta_telegram(error_msg)
            return False, ""

        logger.info("✅ Cuenta Banesco validada correctamente.")
        # await asyncio.sleep(3)  <-- Eliminado, avance inmediato

        try:
            logger.info("Buscando si hay ventanas molestas post-login o sesión caducada...")
            try: 
                # 🔥 DESTRUCTOR INICIAL
                await page.evaluate("document.querySelectorAll('.modal, #customModal, .modal-backdrop, .ui-widget-overlay, .swal2-container').forEach(e => e.remove());")
            except: pass

            for frame in page.frames:
                try:
                    # 🔥 REDUCIDO A 50ms: Si no lo ve al instante, avanza rápido 🔥
                    if await frame.locator("text=/No se ha detectado actividad/i").is_visible(timeout=50) or \
                       await frame.locator("text=/su sesión se ha cerrado/i").is_visible(timeout=50):
                        logger.warning("🚨 Banesco cerró la sesión por inactividad.")
                        return False, "SESION_CADUCADA"
                except: pass

                try:
                    btn_cerrar = frame.locator("button:has-text('Cerrar'), button:has-text('Cancelar'), button:has-text('Omitir')").first
                    if await btn_cerrar.is_visible(timeout=50):
                        await btn_cerrar.click(force=True)
                        logger.info("Anuncio de Banesco cerrado exitosamente.")
                        await asyncio.sleep(0.5)
                except: pass
        except Exception:
            pass 

        logger.info("Abriendo menú de Transferencias (#m_1)...")
        await organic_mouse_move_and_click(page, "#m_1")
        await asyncio.sleep(0.2) # Micro-pausa para que arranque la animación

        logger.info("Buscando submenú 'Terceros en Banesco'...")
        menu_clicado = False
        start_time = time.time()
        while (time.time() - start_time) < 15.0:
            try:
                for frame in page.frames:
                    enlace = frame.locator("a", has_text="Terceros en Banesco").first
                    if await enlace.is_visible(timeout=50): # Visión láser de 50ms
                        await enlace.evaluate("(nodo) => nodo.click()")
                        menu_clicado = True
                        break
            except Exception:
                pass
            if menu_clicado:
                break
            await asyncio.sleep(0.1) # 🔥 EL SECRETO: Míralo 10 veces por segundo, no te duermas 1 segundo

        if not menu_clicado:
            logger.error("Timeout: No se pudo desplegar ni hacer clic en 'Terceros en Banesco'.")
            return False, ""

        logger.info("Seleccionando cuenta de origen...")
        dropdown_origen = await find_element_in_frames(page, "#ctl00_cp_wz_ddlCuentaDebitar", timeout=35000)
        await dropdown_origen.select_option(index=1)

        raw_monto = str(payment_data.get("amount", "0")).strip()
        monto_str = ''.join(c for c in raw_monto if c.isdigit() or c in '.,')
        
        if "," in monto_str and "." in monto_str:
            if monto_str.rfind(",") > monto_str.rfind("."):
                monto_str = monto_str.replace(".", "").replace(",", ".")
            else:
                monto_str = monto_str.replace(",", "")
        else:
            if monto_str.count(".") > 1:
                partes = monto_str.rsplit(".", 1)
                monto_str = partes[0].replace(".", "") + "." + partes[1]
            elif monto_str.count(",") > 1:
                partes = monto_str.rsplit(",", 1)
                monto_str = partes[0].replace(",", "") + "." + partes[1]
            elif "," in monto_str:
                monto_str = monto_str.replace(",", ".")
                
        try:
            monto_orden_float = float(monto_str)
        except ValueError:
            monto_orden_float = 0.0

        try:
            logger.info("⏳ Cazando saldo disponible dinámicamente...")
            saldo_actual = 0.0
            tiempo_saldo = time.time()
            
            # 🔥 CAZADOR DE SALDO: Espera hasta 6s, pero avanza apenas el saldo sea > 0 🔥
            while (time.time() - tiempo_saldo) < 6.0:
                for frame in page.frames:
                    try:
                        texto_completo = await frame.evaluate("() => document.body ? document.body.innerText : ''")
                        match_saldo = re.search(r'Saldo Disponible:\s*([\d\.]+,\d{2})', texto_completo, re.IGNORECASE)
                        if match_saldo:
                            saldo_str = match_saldo.group(1).replace('.', '').replace(',', '.')
                            saldo_temp = float(saldo_str)
                            if saldo_temp > 0:
                                saldo_actual = saldo_temp
                                break
                    except: pass
                if saldo_actual > 0:
                    break
                await asyncio.sleep(0.1)

            actualizar_saldo_json(cuenta_nombre, saldo_actual)

            if saldo_actual > 0:
                dinero_durmiendo = float(payment_data.get("dinero_durmiendo", 0.0))
                logger.info(f"💰 Auditoría - Saldo detectado: Bs. {saldo_actual} | Orden: Bs. {monto_orden_float} | Durmiendo: Bs. {dinero_durmiendo}")

                if saldo_actual < monto_orden_float:
                    error_msg = (
                        f"⛔ **FONDOS INSUFICIENTES PARA LA ORDEN:**\n"
                        f"🏦 **Cuenta:** `{cuenta_nombre}`\n"
                        f"💵 **Saldo actual:** Bs. {saldo_actual:,.2f}\n"
                        f"📉 **Monto a pagar:** Bs. {monto_orden_float:,.2f}\n\n"
                        f"La cuenta no tiene saldo para cubrir este pago. Abortando transferencia."
                    )
                    logger.critical(f"La cuenta {cuenta_nombre} no puede cubrir el monto.")
                    await enviar_alerta_telegram(error_msg)
                    return False, "FONDOS_INSUFICIENTES"

                elif (saldo_actual - monto_orden_float) < dinero_durmiendo:
                    logger.warning(f"La cuenta {cuenta_nombre} pagará esta orden, pero quedará con Bs. {(saldo_actual - monto_orden_float):,.2f}. Se marcará para auto-apagado.")
                    payment_data["apagar_cuenta_despues"] = True 
            else:
                logger.warning("No se pudo extraer el saldo visualmente, el bot intentará continuar a ciegas.")
        except Exception as e:
            logger.warning(f"Error en auditoría de fondos: {e}")

        logger.info("Inyectando datos del beneficiario...")
        cedula = payment_data.get("identity_doc", "").replace("-", "").replace(" ", "")
        
        monto = f"{monto_orden_float:.2f}".replace(".", ",") 

        tipo_doc = "V"
        if cedula[0].isalpha():
            tipo_doc = cedula[0].upper()
            cedula = cedula[1:]

        await type_organically(page, "#ctl00_cp_wz_txtCuentaTransferir", cuenta)
        loc_tipo = await find_element_in_frames(page, "#ctl00_cp_wz_ddlNac")
        await loc_tipo.select_option(value=tipo_doc)
        await type_organically(page, "#ctl00_cp_wz_txtCedula", cedula)
        await type_organically(page, "#ctl00_cp_wz_txtMonto", monto)
        await type_organically(page, "#ctl00_cp_wz_txtConcepto", "Pago")
        await asyncio.sleep(0.5)

        mensaje_banco_alert = ""
        async def on_dialog(dialog):
            nonlocal mensaje_banco_alert
            mensaje_banco_alert = dialog.message
            logger.warning(f"Banesco lanzó popup nativo Javascript: {dialog.message}")
            await dialog.accept()

        page.on("dialog", on_dialog)

        logger.info("Avanzando a la pantalla de resumen...")

        verificador = payment_data.get("verificador_orden")
        if verificador:
            logger.info("🔒 Auditoría Binance: Comprobando que la orden siga activa antes de confirmar...")
            if not await verificador():
                return False, "ORDEN_CANCELADA"

        await organic_mouse_move_and_click(page, "#ctl00_cp_wz_StartNavigationTemplateContainerID_btnNext")

        btn_confirmar = None
        error_especifico = None
        recibo_anticipado = False
        salto_directo_otp = False

        # --- CAZADOR DINÁMICO v3 ---
        logger.info("Vigilando: Popup de confirmación, pantalla OTP, pantallas intermedias o errores de datos...")
        tiempo_inicio = time.time()
        while (time.time() - tiempo_inicio) < 20.0: 
            if mensaje_banco_alert:
                break 

            try:
                for frame in page.frames:
                    texto_frame = await frame.evaluate("() => { if(!document.body) return ''; let t=document.body.innerText; document.querySelectorAll('input').forEach(i=>t+=' '+(i.value||'')); return t; }")
                    texto_up = texto_frame.upper()

                    # 🔥 NUEVO NIVEL DE PROTECCIÓN: DATOS INVÁLIDOS EN FORMULARIO 🔥
                    if "PRESENTAN ERRORES" in texto_up or "VERIFIQUE EL NÚMERO" in texto_up:
                        error_especifico = "DATOS_INVALIDOS"
                        break
                    
                    # 🔥 Escáner secundario directo al HTML (Corte ultra-rápido de 50ms)
                    try:
                        if await frame.locator("text=/presentan errores/i").is_visible(timeout=50) or \
                           await frame.locator("text=/verifique el/i").is_visible(timeout=50):
                            error_especifico = "DATOS_INVALIDOS"
                            break
                    except: pass

                    # NIVEL 1: ATAJO INTELIGENTE (Pantalla de OTP directa)
                    input_otp_check = frame.locator("#ctl00_cp_wz_validarCoe_wzCoeOtp_txtCoeOtp").first
                    if await input_otp_check.is_visible(timeout=100):
                        logger.info("✅ Pantalla de OTP cargada (Casilla detectada). Avanzando a inyección...")
                        salto_directo_otp = True
                        btn_confirmar = "OMITIR"
                        break

                    # NIVEL 2: DETECTOR DE BANESCO EXPRÉS (Recibo directo sin clave)
                    if "OPERACIÓN EXITOSA" in texto_up and ("RECIBO" in texto_up or "TRANSFERENCIA" in texto_up):
                        recibo_anticipado = True
                        break

                    # NIVEL 3: PANTALLA PREVIA AL OTP (Resumen clásico)
                    btn = frame.locator("#ctl00_cp_wz_StepNavigationTemplateContainerID_btnNext").first
                    if await btn.is_visible(timeout=100):
                        btn_confirmar = btn
                        break

                    # NIVEL 4: PANTALLA INTERMEDIA ("Consulte su correo" / Sobre verde)
                    aviso_txt = frame.locator("text=/Consulte en su correo/i").first
                    if await aviso_txt.is_visible(timeout=100) or ("CONSULTE EN SU CORREO" in texto_up):
                        logger.info("✅ Detectada pantalla intermedia de Aviso OTP (Sobre Verde).")
                        # 🔥 FIX ULTRA-RÁPIDO: Usamos siempre Bypass JS porque Banesco oculta botones falsos
                        btn_confirmar = "JS_BYPASS_AVISO"
                        break

                    # NIVEL 5: DESTRUCTOR DE ADVERTENCIAS Y VALIDADOR DE NOMBRE FASE 1
                    if await frame.locator("text=/CONFIRMACI/i").is_visible(timeout=100) or \
                       await frame.locator("text=/seguro de realizar esta operaci/i").is_visible(timeout=100) or \
                       "VALIDACIÓN EN UN LAPSO" in texto_up or \
                       "DESEA CONTINUAR" in texto_up or \
                       "EQUIPO QUE HABITUALMENTE" in texto_up:
                        
                        # 🔥 ALARMA: ¿HAY UN ERROR ROJO DETRÁS DEL POPUP?
                        if "PRESENTAN ERRORES" in texto_up or "VERIFIQUE EL NÚMERO" in texto_up:
                            logger.error("❌ Error de datos detectado detrás del popup de Banesco.")
                            error_especifico = "DATOS_INVALIDOS"
                            break

                        # 🔥 DETECTOR DE TITULAR FANTASMA: Si falta el nombre y salta directo a la Cédula (Ej: V000...)
                        if re.search(r'TRANSFERENCIA A:[\s\n]*[VEJPG][\s\-]*\d{5,}', texto_up):
                            logger.error("❌ El popup de confirmación NO tiene nombre de titular. Cédula o cuenta inválida.")
                            error_especifico = "DATOS_INVALIDOS"
                            break

                        logger.info("✅ Advertencia de Banesco detectada (Titular Validado). Aceptando...")
                        await frame.evaluate("""() => {
                            let btns = Array.from(document.querySelectorAll('input, button, a'));
                            let aceptarBtns = btns.filter(b => {
                                let v = (b.value || "").trim().toLowerCase();
                                let t = (b.innerText || "").trim().toLowerCase();
                                return (v === 'aceptar' || t === 'aceptar') && b.offsetWidth > 0 && b.offsetHeight > 0;
                            });
                            if(aceptarBtns.length > 0) aceptarBtns[aceptarBtns.length - 1].click();
                        }""")
                        
                        try:
                            btn_nativo = frame.locator("input[value='Aceptar'], button:has-text('Aceptar')").last
                            if await btn_nativo.is_visible(timeout=500):
                                await btn_nativo.click(force=True)
                        except: pass
                        
                        await asyncio.sleep(2.0)
                        continue 

                    # NIVEL 6: ERROR DE FONDOS
                    if await frame.locator("text='El monto a transferir no puede ser mayor'").is_visible(timeout=100):
                        error_especifico = "FONDOS"
                        break
            except: pass

            if btn_confirmar or error_especifico or recibo_anticipado or salto_directo_otp:
                break
            await asyncio.sleep(1)

        try:
            page.remove_listener("dialog", on_dialog)
        except Exception:
            pass

        if error_especifico == "FONDOS":
            logger.critical(f"La cuenta {cuenta_nombre} rebotó por fondos insuficientes (Alerta roja nativa).")
            os.makedirs("logs/screenshots", exist_ok=True)
            ruta_error_fondos = f"logs/screenshots/fondos_insuficientes_{int(time.time())}.png"
            await page.screenshot(path=ruta_error_fondos, full_page=True)
            mensaje_fondos = (
                f"⛔ **FONDOS INSUFICIENTES (Banesco Rojo):**\n"
                f"🏦 **Cuenta:** `{cuenta_nombre}`\n"
                f"🧾 **Orden:** `{order_id}`\n\n"
                f"El banco rechazó la operación porque el monto supera el saldo disponible. La cuenta se desactivará."
            )
            await enviar_foto_telegram(ruta_error_fondos, mensaje_fondos)
            return False, "FONDOS_INSUFICIENTES"

        # 🔥 MANEJO DEL ERROR DE DATOS INVÁLIDOS (RESCATE RÁPIDO) 🔥
        if error_especifico == "DATOS_INVALIDOS":
            logger.error("❌ Banesco rechazó los datos en el formulario principal (Cédula o Cuenta).")
            os.makedirs("logs/screenshots", exist_ok=True)
            ruta_error_datos = f"logs/screenshots/error_datos_{int(time.time())}.png"
            
            # 1. TOMA LA FOTO PRIMERO (Evidencia intacta)
            await page.screenshot(path=ruta_error_datos, full_page=True)
            
            # 2. LUEGO DA CLIC EN "REGRESAR" (Para limpiar la pantalla de Banesco)
            try:
                for f in page.frames:
                    await f.evaluate("let b = Array.from(document.querySelectorAll('input, button')).find(x => (x.value||'').toLowerCase().includes('regresar') || (x.innerText||'').toLowerCase().includes('regresar')); if(b) b.click();")
            except: pass
            await asyncio.sleep(1) # Mini pausa para que Banesco reaccione al clic

            mensaje_datos = (
                f"⚠️ **DATOS INCORRECTOS:**\n"
                f"🏦 **Cajero:** `{cuenta_nombre}`\n"
                f"🧾 **Orden:** `{order_id}`"
            )
            await enviar_foto_telegram(ruta_error_datos, mensaje_datos)
            return False, "DATOS_INVALIDOS"

        if mensaje_banco_alert:
            error_msg = (
                f"❌ **ERROR DE BANESCO (Datos Rechazados):**\n"
                f"🏦 **Cuenta:** `{cuenta_nombre}`\n"
                f"🧾 **Orden:** `{order_id}`\n\n"
                f"El banco rechazó los datos e impidió continuar. Mensaje exacto de Banesco:\n"
                f"💬 *\"{mensaje_banco_alert}\"*"
            )
            logger.error(f"Transferencia abortada por alerta del banco: {mensaje_banco_alert}")
            os.makedirs("logs/screenshots", exist_ok=True)
            ruta_error = f"logs/screenshots/alerta_banco_{int(time.time())}.png"
            await page.screenshot(path=ruta_error, full_page=True)
            await enviar_foto_telegram(ruta_error, error_msg)
            return False, ""

        if not btn_confirmar and not recibo_anticipado and not salto_directo_otp:
            logger.error(f"❌ Banesco no avanzó del Paso 1 (Timeout). Tomando captura...")
            os.makedirs("logs/screenshots", exist_ok=True)
            ts = int(time.time())
            ruta_error_paso1 = f"logs/screenshots/error_paso1_{ts}.png"
            await page.screenshot(path=ruta_error_paso1, full_page=True)
            
            # 🔥 EXTRACTOR HTML (Temporal) 🔥
            try:
                with open(f"logs/screenshots/error_paso1_{ts}.html", "w", encoding="utf-8") as f:
                    f.write(await page.content())
            except: pass

            return False, ""

        try:
            btn_alerta = await find_element_in_frames(page, "button.swal2-confirm", timeout=2000)
            if btn_alerta:
                await btn_alerta.click(force=True)
                await asyncio.sleep(2)
        except Exception:
            pass

        intentos_otp = 0
        max_intentos = 2 
        fase_post_confirmacion = None

        if recibo_anticipado:
            logger.info("⚡ BANESCO EXPRÉS: El banco liquidó el pago inmediatamente sin pedir confirmación ni OTP.")
            fase_post_confirmacion = "recibo"
            intentos_otp = max_intentos

        while intentos_otp < max_intentos:
            intentos_otp += 1

            logger.info(f"⚡ {cuenta_nombre} procesando Fase de Seguridad INDEPENDIENTE (Intento OTP {intentos_otp}/{max_intentos})...")

            if intentos_otp == 1:
                if btn_confirmar == "OMITIR":
                    logger.info(f"🟢 Banesco saltó el resumen. Omitiendo clic de confirmación para {cuenta_nombre}...")
                elif btn_confirmar == "JS_BYPASS_AVISO":
                    logger.info(f"🟢 Inyectando clic JS para salir de la pantalla verde de aviso en {cuenta_nombre}...")
                    try:
                        for frame in page.frames:
                            await frame.evaluate("""() => {
                                let btns = Array.from(document.querySelectorAll('input, button, a'));
                                let aceptarBtns = btns.filter(b => {
                                    let v = (b.value || "").trim().toLowerCase();
                                    let t = (b.innerText || "").trim().toLowerCase();
                                    return (v === 'aceptar' || t === 'aceptar') && b.offsetWidth > 0 && b.offsetHeight > 0;
                                });
                                if(aceptarBtns.length > 0) aceptarBtns[aceptarBtns.length - 1].click();
                            }""")
                    except: pass
                    await asyncio.sleep(0.5)
                else:
                    logger.info(f"🟢 Presionando botón final de confirmación (Aceptar) para {cuenta_nombre}...")
                    
                    # 🔥 CLIC JAVASCRIPT BLINDADO (Evita fallos por lag visual de Banesco) 🔥
                    try: 
                        await btn_confirmar.evaluate("(nodo) => nodo.click()")
                    except Exception as e: 
                        logger.warning(f"Fallo clic JS, usando fallback de Playwright: {e}")
                        try: await btn_confirmar.click(force=True)
                        except: pass
                    await asyncio.sleep(2.0)
            else:
                logger.info(f"🟢 Reintentando inyección de clave en la misma pantalla para {cuenta_nombre}...")

            fase_post_confirmacion = None
            sel_otp = "#ctl00_cp_wz_validarCoe_wzCoeOtp_txtCoeOtp"

            # ⏳ Aumentamos a 30 Segundos para darle más margen de carga a Banesco
            tiempo_espera = time.time()
            while (time.time() - tiempo_espera) < 45.0:
                for frame in page.frames:
                    try:
                        # 🔥 RE-CLICKER DE EMERGENCIA (Si a Banesco "se le olvida" avanzar de pantalla) 🔥
                        if intentos_otp == 1 and btn_confirmar not in ["OMITIR", "JS_BYPASS_AVISO"]:
                            btn_reintentar = frame.locator("#ctl00_cp_wz_StepNavigationTemplateContainerID_btnNext").first
                            if await btn_reintentar.is_visible(timeout=50):
                                logger.warning(f"⚠️ El bot sigue atrapado en la pantalla resumen de {cuenta_nombre}. Re-inyectando clic a 'Aceptar'...")
                                await btn_reintentar.evaluate("(nodo) => nodo.click()")
                                await asyncio.sleep(1.5)

                        texto_frame = await frame.evaluate("() => { if(!document.body) return ''; let t=document.body.innerText; document.querySelectorAll('input').forEach(i=>t+=' '+(i.value||'')); return t; }")
                        texto_up = texto_frame.upper()

                        # DESTRUCTOR DE ADVERTENCIAS EN FASE 2
                        if "VALIDACIÓN EN UN LAPSO" in texto_up or "DESEA CONTINUAR" in texto_up or "EQUIPO QUE HABITUALMENTE" in texto_up:
                            logger.info("✅ Advertencia atravesada detectada en Fase OTP. Destruyendo obstáculo...")
                            await frame.evaluate("""() => {
                                let btns = Array.from(document.querySelectorAll('input, button, a'));
                                let aceptarBtns = btns.filter(b => {
                                    let v = (b.value || "").trim().toLowerCase();
                                    let t = (b.innerText || "").trim().toLowerCase();
                                    return (v === 'aceptar' || t === 'aceptar') && b.offsetWidth > 0 && b.offsetHeight > 0;
                                });
                                if(aceptarBtns.length > 0) aceptarBtns[aceptarBtns.length - 1].click();
                            }""")
                            try:
                                btn_nativo = frame.locator("input[value='Aceptar'], button:has-text('Aceptar')").last
                                if await btn_nativo.is_visible(timeout=500):
                                    await btn_nativo.click(force=True)
                            except: pass
                            await asyncio.sleep(2.0)
                            continue 

                        btn_enviar_otp = frame.locator("#ctl00_cp_wz_validarCoe_wzCoeOtp_StepNavigationTemplateContainerID_btnNext").first
                        input_otp = frame.locator(sel_otp).first

                        if await btn_enviar_otp.is_visible():
                            await btn_enviar_otp.click(force=True)
                            await asyncio.sleep(1)

                        if await input_otp.is_visible():
                            fase_post_confirmacion = "otp"
                            break

                        if "OPERACIÓN EXITOSA" in texto_up and ("RECIBO" in texto_up or "TRANSFERENCIA" in texto_up):
                            fase_post_confirmacion = "recibo"
                            break
                    except Exception:
                        pass
                if fase_post_confirmacion:
                    break
                await asyncio.sleep(0.5)

            if not fase_post_confirmacion:
                logger.error("No se detectó ni la pantalla de OTP ni el recibo tras 30 segundos.")
                os.makedirs("logs/screenshots", exist_ok=True)
                ts = int(time.time())
                ruta_error = f"logs/screenshots/error_timeout_otp_{ts}.png"
                await page.screenshot(path=ruta_error, full_page=True)
                
                # 🔥 EXTRACTOR HTML (Temporal) 🔥
                try:
                    with open(f"logs/screenshots/error_timeout_otp_{ts}.html", "w", encoding="utf-8") as f:
                        f.write(await page.content())
                except: pass

                mensaje_error = (
                    f"❌ **ERROR EN TRANSFERENCIA (Timeout de Banesco):**\n"
                    f"🏦 **Cuenta:** `{cuenta_nombre}`\n"
                    f"🧾 **Orden:** `{order_id}`\n\n"
                    f"El bot presionó Aceptar, pero Banesco se quedó congelado cargando. Nunca apareció la casilla para introducir la clave dinámica (OTP)."
                )
                await enviar_foto_telegram(ruta_error, mensaje_error)
                return False, "TIMEOUT_BANESCO"  # 🔥 ANTES ESTABA VACÍO ("")

            if fase_post_confirmacion == "otp":
                codigo_otp = CACHE_OTP_SESIONES.get(cuenta_nombre)

                if codigo_otp:
                    logger.info(f"⚡ MODO RÁFAGA: Reutilizando OTP de esta sesión activo en memoria ({codigo_otp})...")
                    if "FONDEO" not in order_id and intentos_otp == 1:
                        await enviar_alerta_telegram(f"⚡ **Fase 6 Ráfaga:** Usando Clave de Operaciones Especiales en memoria (`{codigo_otp}`)...")
                else:
                    logger.info("El banco solicitó OTP y no hay uno en memoria. Entrando al correo sin hacer fila...")
                    if intentos_otp == 1 and "FONDEO" not in order_id:
                        await enviar_alerta_telegram("⏳ **Fase 6:** Banesco solicita Clave de Operaciones Especiales (OTP). Interceptando correo...")
                    elif intentos_otp > 1 and "FONDEO" not in order_id:
                        await enviar_alerta_telegram(f"🔄 **Reintento en Caliente:** Banesco rechazó la clave anterior. Leyendo Gmail en busca de un correo nuevo...")

                    email_aislado = payment_data.get("seguridad_banco", {}).get("correo", "")
                    clave_aislada = payment_data.get("seguridad_banco", {}).get("clave_correo", "")

                    otp_reader = OTPReader(email_aislado, clave_aislada)
                    
                    # 🔥 FIX: Pausa táctica OBLIGATORIA para darle tiempo al servidor de Banesco
                    if intentos_otp == 1:
                        logger.info("⏳ Dando 4 segundos de ventaja a Banesco para que el correo nuevo llegue a la bandeja...")
                        await asyncio.sleep(4.5)
                    else:
                        logger.info("⏳ Reintento: Esperando 4 segundos adicionales por si el correo viene con retraso severo...")
                        await asyncio.sleep(4)

                    codigo_otp = await asyncio.to_thread(otp_reader.get_otp, sender_address="notificacion@banesco.com", timeout=180)

                    if not codigo_otp:
                        logger.error("Se agotó el tiempo de espera para el OTP.")
                        return False, ""

                    logger.info(f"¡OTP Capturado ({codigo_otp})! Guardando en Memoria RAM de la cuenta '{cuenta_nombre}'...")
                    CACHE_OTP_SESIONES[cuenta_nombre] = codigo_otp
                    if "FONDEO" not in order_id:
                        if intentos_otp == 1:
                            await enviar_alerta_telegram(f"🔓 **Fase 7:** ¡Código Capturado! (`{codigo_otp}`). Guardado en memoria y ejecutando pago...")
                        else:
                            await enviar_alerta_telegram(f"🔓 **Fase 7 Reintento:** ¡Nueva clave detectada! (`{codigo_otp}`). Inyectando inmediatamente...")

                if verificador:
                    logger.info("🔒 Auditoría Binance Final: Comprobando orden antes de inyectar y quemar la clave dinámica...")
                    if not await verificador():
                        return False, "ORDEN_CANCELADA"

                # 🔥 TIPEO FLASH Y DESTRUCTOR DE BOTÓN GRIS 🔥
                await type_organically(page, sel_otp, codigo_otp)
                
                # Despierta el botón gris enviando una señal de teclado virtual a Banesco
                try:
                    for frame in page.frames:
                        await frame.evaluate(f"let e = document.querySelector('{sel_otp}'); if(e) e.dispatchEvent(new Event('keyup', {{ bubbles: true }}));")
                except: pass

                # 🔥🔥 INYECCIÓN: LA BANDERA ANTI-DOBLE-GASTO 🔥🔥
                logger.info("🔥 INYECTANDO BANDERA ANTI-DOBLE-GASTO: El clic definitivo está por ocurrir...")
                payment_data["pago_enviado"] = True

                try:
                    await page.evaluate("""
                        let btn = document.querySelector("#ctl00_cp_wz_FinishNavigationTemplateContainerID_btnFinishComp") || 
                                  document.querySelector("input[value='Aceptar']") || 
                                  document.querySelector("button:has-text('Aceptar')");
                        if(btn) btn.click();
                    """)
                except:
                    await organic_mouse_move_and_click(page, "#ctl00_cp_wz_FinishNavigationTemplateContainerID_btnFinishComp")

            else:
                logger.info("¡El banco NO solicitó OTP! Procesando recibo directo...")
                if "FONDEO" not in order_id:
                    await enviar_alerta_telegram("⚡ **Fase 6:** Banesco procesó el pago directo (Sin solicitar Clave Dinámica).")

            logger.info(f"🔴 {cuenta_nombre} ha terminado su ciclo de inyección. Validando resultados...")

            logger.info("Buscando recibo de operación exitosa o errores de clave con escáner JS...")
            tiempo_recibo = time.time()
            necesita_reintento = False

            while (time.time() - tiempo_recibo) < 60.0:
                for frame in page.frames:
                    try:
                        texto_frame = await frame.evaluate("() => { if(!document.body) return ''; let t=document.body.innerText; document.querySelectorAll('input').forEach(i=>t+=' '+(i.value||'')); return t; }")
                        if not texto_frame or len(texto_frame) < 10:
                            continue
                            
                        texto_up = texto_frame.upper()

                        if "SUSPENDIDA" in texto_up or "TEMPORALMENTE SUSPENDIDA" in texto_up:
                            logger.critical(f"🚨 CLAVE SUSPENDIDA EN {cuenta_nombre}. Abortando para no empeorar el bloqueo.")
                            payment_data["pago_enviado"] = False # 🔥 APAGAR BANDERA ANTI-DOBLE GASTO
                            CACHE_OTP_SESIONES.pop(cuenta_nombre, None)
                            os.makedirs("logs/screenshots", exist_ok=True)
                            ruta_error_otp = f"logs/screenshots/clave_suspendida_{int(time.time())}.png"
                            await page.screenshot(path=ruta_error_otp, full_page=True)
                            mensaje_error_otp = (
                                f"❌ **CLAVE SUSPENDIDA (Bloqueo Banesco):**\n"
                                f"🏦 **Cuenta:** `{cuenta_nombre}`\n"
                                f"🧾 **Orden:** `{order_id}`\n\n"
                                f"Banesco ha suspendido temporalmente la Clave de Operaciones Especiales de esta cuenta por intentos fallidos. Deberás esperar el tiempo indicado por el banco."
                            )
                            await enviar_foto_telegram(ruta_error_otp, mensaje_error_otp)
                            return False, "ERROR_OTP"

                        # 🔥 FIX DEL CACHÉ ENVENENADO (Falla rápido, destruye la clave y prepara reintento) 🔥
                        elif "ERRÓNEAMENTE" in texto_up or "INCORRECTAMENTE" in texto_up or "INCORRECTA" in texto_up or "EXISTEN ERRORES/ALERTAS" in texto_up or "VERIFIQUE LA(S) SIGUIENTE(S)" in texto_up or "OBSERVACION(ES)" in texto_up or "OBSERVACIÓN(ES)" in texto_up:
                            logger.warning(f"🚨 BANESCO RECHAZÓ EL INTENTO DE OTP (Clave errónea o vieja). Destruyendo caché y preparando reintento en caliente.")
                            
                            payment_data["pago_enviado"] = False # 🔥 APAGAR BANDERA ANTI-DOBLE GASTO
                            CACHE_OTP_SESIONES.pop(cuenta_nombre, None) 
                            necesita_reintento = True
                            break 

                        elif "OPERACIÓN EXITOSA" in texto_up or "RECIBO" in texto_up or "N° DE REFERENCIA" in texto_up or "NÚMERO DE REFERENCIA" in texto_up:
                            logger.info("✅ ¡Recibo detectado directamente del motor del navegador!")

                            logger.info("🔍 Ejecutando Auditoría de Seguridad: Verificando cuenta de destino en el recibo...")
                            texto_solo_numeros = re.sub(r'\D', '', texto_frame)
                            
                            # 🔥 FIX: Verificamos solo los últimos 10 dígitos (el serial único) 
                            # para evitar que guiones, asteriscos o espacios de Banesco rompan el match de los 20.
                            serial_cuenta_final = cuenta[-10:] if len(cuenta) >= 10 else cuenta

                            if serial_cuenta_final not in texto_solo_numeros and "TRANSFERENCIA A TERCEROS A OTROS BANCOS" not in texto_up:
                                logger.critical(f"🚨 ¡ALARMA DE RECIBO FANTASMA! La terminación {serial_cuenta_final} no aparece en el comprobante final.")
                                os.makedirs("logs/screenshots", exist_ok=True)
                                ts = int(time.time())
                                ruta_error_fantasma = f"logs/screenshots/fantasma_interceptado_{ts}.png"
                                await page.screenshot(path=ruta_error_fantasma, full_page=True)
                                
                                try:
                                    with open(f"logs/screenshots/fantasma_interceptado_{ts}.html", "w", encoding="utf-8") as f:
                                        f.write(await page.content())
                                except: pass

                                try:
                                    await frame.locator("form").first.screenshot(path=ruta_error_fantasma)
                                except:
                                    await page.screenshot(path=ruta_error_fantasma, full_page=True)
                                mensaje_fantasma = (
                                    f"🚨 **¡DOBLE CHEQUEO SALVÓ LA ORDEN!** 🚨\n"
                                    f"🏦 **Cuenta de Origen:** `{cuenta_nombre}`\n"
                                    f"🧾 **Orden Binance:** `{order_id}`\n\n"
                                    f"Banesco generó un recibo cruzado (o el número cargó con formato raro). El bot abortó la subida por precaución.\n"
                                    f"💾 Código fuente extraído para análisis."
                                )
                                await enviar_foto_telegram(ruta_error_fantasma, mensaje_fantasma)
                                return False, ""

                            logger.info("✅ Auditoría superada: La cuenta de destino coincide con el recibo actual.")

                            match = re.search(r'RECIBO[^\d]*(\d{8,15})', texto_frame, re.IGNORECASE)
                            if not match:
                                match = re.search(r'Referencia:[^\d]*(\d{8,15})', texto_frame, re.IGNORECASE)
                            ref = match.group(1) if match else f"EXITO_{int(time.time())}"

                            os.makedirs("comprobantes", exist_ok=True)
                            ruta_captura_final = f"comprobantes/recibo_{ref}.png"
                            
                            try:
                                await frame.locator("form").first.screenshot(path=ruta_captura_final)
                            except:
                                await page.screenshot(path=ruta_captura_final) # 🔥 Sin full_page para ahorrar RAM y Segundos
                                
                            logger.info(f">>> TRANSFERENCIA LIQUIDADA. Referencia: {ref} <<<")

                            # Añadir este bloque para que Telegram avise de los Fondeos
                            if "FONDEO" in order_id:
                                mensaje_fondeo = f"✅ **FONDEO EXITOSO:** Se transfirieron Bs. {monto_orden_float:,.2f} a la cuenta {cuenta_nombre}. Ref: {ref}"
                                await enviar_foto_telegram(ruta_captura_final, mensaje_fondeo)

                            if saldo_actual > 0:
                                saldo_post_pago = round(saldo_actual - monto_orden_float, 2)
                                actualizar_saldo_json(cuenta_nombre, saldo_post_pago)
                                logger.info(f"💳 Saldo descontado y actualizado en panel a: Bs. {saldo_post_pago:,.2f}")

                            logger.info("🧹 Cerrando recibo de forma ultra-rápida...")
                            try:
                                await frame.evaluate("""() => {
                                    let btn = Array.from(document.querySelectorAll('input, button')).find(b => {
                                        let v = (b.value || b.innerText || "").toUpperCase();
                                        return v.includes('ACEPTAR') || v.includes('INICIO');
                                    });
                                    if(btn) btn.click();
                                }""")
                            except: pass

                            # 🔥 FIX: Volvemos directamente al inicio sin hacer F5 completo (Ahorra 10 segundos)
                            logger.info("🚀 Retornando al inicio instantáneamente...")
                            try:
                                await frame.evaluate("""() => {
                                    let casita = Array.from(document.querySelectorAll('img')).find(img => img.src.toLowerCase().includes('home') || img.src.toLowerCase().includes('inicio'));
                                    if(casita && casita.parentElement) casita.parentElement.click();
                                }""")
                            except: pass
                            
                            await asyncio.sleep(0.5)
                            return True, ruta_captura_final
                    except Exception:
                        pass

                if necesita_reintento:
                    break 

                await asyncio.sleep(0.5)

            if necesita_reintento:
                if intentos_otp < max_intentos:
                    logger.info("🔁 Iniciando reintento en caliente para buscar un nuevo correo OTP...")
                    continue 
                else:
                    logger.error("Se agotaron los reintentos de OTP en caliente.")
                    os.makedirs("logs/screenshots", exist_ok=True)
                    ruta_error_otp = f"logs/screenshots/error_otp_invalido_{int(time.time())}.png"
                    await page.screenshot(path=ruta_error_otp, full_page=True)
                    
                    mensaje_error_otp = (
                        f"⚠️ **RESETEO DE SESIÓN (Clave Expirada o Errónea):**\n"
                        f"🏦 **Cuenta:** `{cuenta_nombre}`\n"
                        f"🧾 **Orden:** `{order_id}`\n\n"
                        f"Banesco rechazó la Clave OTP múltiples veces. El bot cerrará la sesión actual para pedir una nueva desde cero y evitar un bloqueo de seguridad."
                    )
                    await enviar_foto_telegram(ruta_error_otp, mensaje_error_otp)
                    return False, "ERROR_OTP" 

        logger.error("No se encontró el texto 'Operación Exitosa.' ni alerta de error tras 60 segundos.")
        os.makedirs("logs/screenshots", exist_ok=True)
        ruta_error = f"logs/screenshots/error_timeout_{int(time.time())}.png"
        await page.screenshot(path=ruta_error, full_page=True)

        mensaje_error = (
            f"❌ **ERROR EN TRANSFERENCIA (Timeout Final):**\n"
            f"🏦 **Cuenta:** `{cuenta_nombre}`\n"
            f"🧾 **Orden:** `{order_id}`\n\n"
            f"El banco no mostró el recibo de éxito tras ingresar el OTP y se agotó el tiempo de espera."
        )
        await enviar_foto_telegram(ruta_error, mensaje_error)
        return False, "TIMEOUT_BANESCO"  # 🔥 ANTES ESTABA VACÍO ("")

    except Exception as e:
        logger.error(f"Fallo durante el proceso de transferencia: {e}")
        try:
            for frame in page.frames:
                if await frame.locator("text=/No se ha detectado actividad/i").is_visible(timeout=500) or \
                   await frame.locator("text=/su sesión se ha cerrado/i").is_visible(timeout=500):
                    logger.warning("🚨 Sesión caducada detectada después de un fallo de espera.")
                    return False, "SESION_CADUCADA"
        except: pass

        try:
            os.makedirs("logs/screenshots", exist_ok=True)
            ts = int(time.time())
            ruta_error = f"logs/screenshots/crash_transfer_{ts}.png"
            await page.screenshot(path=ruta_error, full_page=True)

            # 🔥 EXTRACTOR HTML (Temporal) 🔥
            try:
                with open(f"logs/screenshots/crash_transfer_{ts}.html", "w", encoding="utf-8") as f:
                    f.write(await page.content())
            except: pass

            e_limpio = str(e).replace("_", "\\_").replace("#", "\\#").replace("[", "\\[").replace("]", "\\]")
            if len(e_limpio) > 500:
                e_limpio = e_limpio[:500] + "... [ERROR TRUNCADO POR EXCESO DE TEXTO]"

            mensaje_error = (
                f"🚨 **CRASH EN TRANSFERENCIA:**\n"
                f"🏦 **Cuenta:** `{cuenta_nombre}`\n"
                f"🧾 **Orden:** `{order_id}`\n\n"
                f"Ocurrió un error inesperado:\n`{e_limpio}`"
            )
            await enviar_foto_telegram(ruta_error, mensaje_error)
        except Exception as tel_err:
            logger.error(f"Fallo crítico al intentar notificar a Telegram: {tel_err}")
        return False, ""
