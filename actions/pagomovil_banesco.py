"""
RPA: Ejecución de Pago Móvil INFINITO en BanescOnline
(MODO NATIVO PAGO MÓVIL + AUDITORÍA DE SALDO + RAM SYNC)
"""
import asyncio
import os
import time
import logging
import imaplib
import email
import re
import json
from typing import Dict, Any, Tuple

logger = logging.getLogger(__name__)

try:
    from integrations.telegram_notifier import enviar_alerta_telegram, enviar_foto_telegram
except ImportError:
    async def enviar_alerta_telegram(msg: str):
        logger.info(f"TELEGRAM ALERTA: {msg}")
    async def enviar_foto_telegram(foto: str, msg: str):
        logger.info(f"TELEGRAM FOTO [{foto}]: {msg}")

CACHE_OTP_SESIONES = {}

# --- MEMORIA RAM GLOBAL Y SINCRONIZADOR DE JSON ---
def actualizar_saldo_json(cuenta: str, saldo: float, payment_data: dict = None, apagar: bool = False):
    """Actualiza los JSON y la RAM del orquestador, apagando la cuenta si es necesario."""
    if payment_data is not None:
        payment_data["saldo"] = saldo
        payment_data["balance"] = saldo
        payment_data["saldo_actualizado"] = saldo

    try:
        if os.path.exists("data/estado_bot.json"):
            with open("data/estado_bot.json", "r", encoding="utf-8") as f:
                est = json.load(f)
            if "saldos" not in est: est["saldos"] = {}
            est["saldos"][cuenta] = saldo
            with open("data/estado_bot.json", "w", encoding="utf-8") as f:
                json.dump(est, f, ensure_ascii=False, indent=4)
    except: pass
    
    try:
        for ruta_acc in ["data/accounts.json", "accounts.json", "data/cuentas.json", "cuentas.json"]:
            if os.path.exists(ruta_acc):
                with open(ruta_acc, "r", encoding="utf-8") as f:
                    data_acc = json.load(f)
                modificado = False
                if isinstance(data_acc, list):
                    for acc in data_acc:
                        if acc.get("nombre") == cuenta or acc.get("name") == cuenta:
                            acc["saldo"] = saldo
                            acc["balance"] = saldo
                            # 🔥 Si se activa la orden de apagado, tumba el switch principal
                            if apagar:
                                acc["activa"] = False
                                acc["activo"] = False
                                logger.warning(f"🛑 Switch principal de {cuenta} APAGADO (Límite de Dinero Durmiendo alcanzado).")
                            modificado = True
                if modificado:
                    with open(ruta_acc, "w", encoding="utf-8") as f:
                        json.dump(data_acc, f, ensure_ascii=False, indent=4)
    except: pass

# --- MOTOR PRIVADO DE INTERCEPCIÓN DE GMAIL ---
async def interceptar_otp_gmail(correo: str, clave_aplicacion: str, timeout: int = 60) -> str:
    def fetch_email():
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(correo, clave_aplicacion)
            mail.select("inbox")
            _, messages = mail.search(None, '(UNSEEN)')
            mail_ids = messages[0].split()
            
            if not mail_ids: return None
                
            for num in reversed(mail_ids[-3:]): 
                _, msg_data = mail.fetch(num, "(RFC822)")
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        subject = str(msg.get("Subject", ""))
                        if "Clave" in subject or "Banesco" in subject or "Operaciones" in subject:
                            body = ""
                            if msg.is_multipart():
                                for part in msg.walk():
                                    if part.get_content_type() == "text/plain":
                                        body = part.get_payload(decode=True).decode(errors="ignore")
                                        break
                            else:
                                body = msg.get_payload(decode=True).decode(errors="ignore")
                            
                            match = re.search(r'\b\d{6,8}\b', body)
                            if match: return match.group(0)
            return None
        except Exception as e:
            logger.error(f"Fallo interno conectando a Gmail: {e}")
            return None

    tiempo_inicio = time.time()
    while (time.time() - tiempo_inicio) < timeout:
        otp = await asyncio.to_thread(fetch_email)
        if otp: return otp
        await asyncio.sleep(2) 
    return None

# --- PLAN B: VERIFICADOR DE RECIBOS EN GMAIL (RESCATE ANTI-FANTASMAS) ---
async def verificar_pago_gmail(correo: str, clave_aplicacion: str, cedula_destino: str, monto_esperado: float) -> str:
    def fetch_receipt():
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(correo, clave_aplicacion)
            mail.select("inbox")
            _, messages = mail.search(None, 'ALL')
            mail_ids = messages[0].split()
            
            if not mail_ids: return None
            
            # Limpiamos los datos para que coincidan perfecto
            ced_limpia = "".join(filter(str.isdigit, str(cedula_destino)))
            monto_int = str(int(monto_esperado))
            
            # Revisamos rápido los últimos 5 correos que acaban de llegar
            for num in reversed(mail_ids[-5:]): 
                _, msg_data = mail.fetch(num, "(RFC822)")
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        subject = str(msg.get("Subject", ""))
                        if "Transferencia" in subject or "Pago" in subject or "Banesco" in subject:
                            body = ""
                            if msg.is_multipart():
                                for part in msg.walk():
                                    if part.get_content_type() == "text/plain":
                                        body = part.get_payload(decode=True).decode(errors="ignore")
                                        break
                            else:
                                body = msg.get_payload(decode=True).decode(errors="ignore")
                            
                            texto = body.upper().replace("\n", " ").replace("\r", "")
                            
                            # Si coinciden la cédula y el monto entero, ¡Es el pago correcto!
                            if ced_limpia in texto and monto_int in texto:
                                match_ref = re.search(r'Referencia Nro:\s*(\d+)', body, re.IGNORECASE)
                                if match_ref: return match_ref.group(1)
                                return "GMAIL_" + str(int(time.time()))
            return None
        except Exception as e:
            logger.error(f"Fallo interno leyendo recibos en Gmail: {e}")
            return None

    logger.info(f"🕵️‍♂️ PLAN B ACTIVADO: Entrando a Gmail de forma invisible para cazar el recibo de Bs. {monto_esperado}...")
    tiempo_inicio = time.time()
    # Espera hasta 20 segundos refrescando el correo
    while (time.time() - tiempo_inicio) < 20.0:
        ref = await asyncio.to_thread(fetch_receipt)
        if ref: return ref
        await asyncio.sleep(4)
        
    return None

async def execute_pagomovil(page: Any, payment_data: Dict[str, Any]) -> Tuple[bool, str]:
    order_id = payment_data.get("order_id", "TEST")
    telefono = payment_data.get("telefono", "")
    cedula = payment_data.get("identity_doc", "")
    cuenta_nombre = str(payment_data.get("nombre_cuenta", "Desconocida"))
    
    nombre_bruto = payment_data.get("account_name") or payment_data.get("nombre_contraparte") or payment_data.get("nombre_cliente") or "Frank"
    nombre_cliente = re.sub(r'[^a-zA-Z\s]', ' ', str(nombre_bruto)).strip()[:25]
    if len(nombre_cliente) < 3: 
        nombre_cliente = "Frank"

    if payment_data.get("nueva_sesion"):
        CACHE_OTP_SESIONES.pop(cuenta_nombre, None)
        logger.info(f"🧹 Nueva sesión detectada para {cuenta_nombre}. Caché de OTP borrado.")

    codigo_banco_raw = str(payment_data.get("banco_destino", "")).upper()
    match_banco = re.search(r'\b(01\d{2})\b', codigo_banco_raw)
    codigo_banco = match_banco.group(1) if match_banco else codigo_banco_raw.strip()

    # 🔥 ESCUDO: LISTA NEGRA EXCLUSIVA (SOLO VENEZOLANO DE CRÉDITO) 🔥
    es_banco_prohibido = False
    banco_detectado = ""
    
    if "0104" in codigo_banco_raw or "VENEZOLANO" in codigo_banco_raw:
        es_banco_prohibido = True
        banco_detectado = "Venezolano de Crédito (0104)"

    if es_banco_prohibido:
        logger.warning(f"🛑 Banco problemático detectado ({banco_detectado}). Abortando para evitar colapso P2PBACK-696.")
        mensaje_bloqueo = (
            f"⛔ **BANCO EN LISTA NEGRA:**\n"
            f"🏦 **Cuenta asignada:** `{cuenta_nombre}`\n"
            f"🧾 **Orden:** `{order_id}`\n"
            f"🏦 **Destino:** `{banco_detectado}`\n\n"
            f"Este banco presenta fallas constantes de conexión con Banesco. La orden fue pausada. Pide otro banco al cliente por el chat de Binance."
        )
        try: await enviar_alerta_telegram(mensaje_bloqueo)
        except: pass
        
        payment_data["pago_enviado"] = False
        return False, "BANCO_RECHAZADO_POR_SISTEMA"

    monto_bruto = str(payment_data.get("amount", "0,00"))
    monto = monto_bruto.replace(".", ",")
    if "," not in monto: monto += ",00"
        
    if "." in monto and "," in monto:
        monto_float_str = monto.replace(".", "").replace(",", ".")
    else:
        monto_float_str = monto.replace(",", ".")
        
    try:
        monto_orden_float = float(monto_float_str)
    except ValueError:
        monto_orden_float = 0.0

    logger.info(f"📱 Iniciando PM Infinito | Orden: {order_id} | Destino: {codigo_banco} | Tel: {telefono} | Monto: Bs. {monto}")

    if not telefono or len(telefono) < 10: return False, "TELEFONO_INVALIDO"

    try:
        # ======================================================
        # 1. NAVEGACIÓN Y DETECCIÓN DE SESIÓN CADUCADA
        # ======================================================
        logger.info("Buscando si hay ventanas molestas post-login o sesión caducada...")
        try: 
            await page.evaluate("document.querySelectorAll('.modal, #customModal, .modal-backdrop, .ui-widget-overlay, .swal2-container').forEach(e => e.remove());")
        except: pass

        for frame in page.frames:
            try:
                if await frame.locator("text=/No se ha detectado actividad/i").is_visible(timeout=1000) or \
                   await frame.locator("text=/su sesión se ha cerrado/i").is_visible(timeout=1000):
                    logger.warning("🚨 Banesco arrojó alerta de inactividad. Forzando reinicio de sesión desde cero...")
                    return False, "SESION_CADUCADA"
            except: pass

            try:
                btn_cerrar = frame.locator("input[value='Continuar'], button:has-text('Continuar'), button:has-text('Cerrar'), button:has-text('Cancelar')").first
                if await btn_cerrar.is_visible(timeout=1000):
                    await btn_cerrar.click(force=True)
                    logger.info("Anuncio de Banesco cerrado exitosamente.")
                    await asyncio.sleep(1)
            except: pass

        # 🔥 AUDITORÍA INICIAL 🔥
        logger.info("🔍 Extrayendo saldo real desde el Dashboard inicial...")
        try:
            for frame in page.frames:
                texto_dashboard = await frame.evaluate("() => document.body ? document.body.innerText : ''")
                match_saldo_dash = re.search(r'0134[\d\-]+[^\d]+([\d\.]+,\d{2})', texto_dashboard)
                if match_saldo_dash:
                    saldo_str = match_saldo_dash.group(1).replace('.', '').replace(',', '.')
                    saldo_real = float(saldo_str)
                    actualizar_saldo_json(cuenta_nombre, saldo_real, payment_data)
                    logger.info(f"💰 Saldo inicial verificado en pantalla: Bs. {saldo_real:,.2f}")
                    break
        except Exception as e:
            logger.warning(f"No se pudo extraer el saldo del Dashboard inicial: {e}")

        # 🔥 NUEVA NAVEGACIÓN BLINDADA 🔥
        logger.info("Desplegando menú lateral de Pago Móvil...")
        for _ in range(20):
            clic_menu = False
            for frame in page.frames:
                try:
                    clic_menu = await frame.evaluate("""() => { 
                        let items = Array.from(document.querySelectorAll('a, span, h3'));
                        let btn = items.find(e => {
                            if (!e.innerText || e.offsetParent === null) return false;
                            let txt = e.innerText.toUpperCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
                            return txt.includes('PAGO MOVIL');
                        });
                        if (btn) { btn.click(); return true; } 
                        return false; 
                    }""")
                    if clic_menu: break
                except: pass
            if clic_menu: break
            await asyncio.sleep(0.2)
            
        await asyncio.sleep(1.5)
        
        logger.info("Haciendo clic en Enviar Pago...")
        for _ in range(20):
            clic_sub = False
            for frame in page.frames:
                try:
                    clic_sub = await frame.evaluate("""() => { 
                        let items = Array.from(document.querySelectorAll('a, span'));
                        let btn = items.find(e => {
                            if (!e.innerText || e.offsetParent === null) return false;
                            return e.innerText.toUpperCase().includes('ENVIAR PAGO');
                        });
                        if (btn) { btn.click(); return true; } 
                        return false; 
                    }""")
                    if clic_sub: break
                except: pass
            if clic_sub: break
            await asyncio.sleep(0.2)

        # ======================================================
        # BUCLE DE REINTENTO ANTE ERRORES FANTASMA (388)
        # ======================================================
        intentos_form = 0
        estado_respuesta = None

        while intentos_form < 3:
            intentos_form += 1
            if intentos_form > 1:
                logger.info(f"🔄 Reintentando llenado de formulario (Intento {intentos_form}/3)...")
                payment_data["pago_enviado"] = False 
                for _ in range(5):
                    for frame in page.frames:
                        try:
                            if await frame.evaluate("""() => { let t = Array.from(document.querySelectorAll('a, span')).find(e => e.innerText==='Enviar Pago' && e.offsetParent!==null); if(t){t.click(); return true;} return false; }"""): break
                        except: pass
                    await asyncio.sleep(1)

            logger.info("Esperando que cargue el formulario nativo de Pago Móvil...")
            target_frame = None
            # 🔥 Aumentamos la paciencia de 150 a 600 (60 segundos máximos de espera)
            for _ in range(600): 
                for frame in page.frames:
                    try:
                        if await frame.locator("text=Número de Teléfono del Beneficiario").is_visible(timeout=5) or \
                           await frame.locator("text=Saldo Disponible").is_visible(timeout=5):
                            target_frame = frame
                            break
                    except: pass
                if target_frame: break
                await asyncio.sleep(0.1)

            if not target_frame: 
                logger.error("❌ TIMEOUT: Banesco no mostró el formulario a tiempo. Extrayendo HTML de emergencia...")
                os.makedirs("logs/screenshots", exist_ok=True)
                marca = int(time.time())
                try: await page.screenshot(path=f"logs/screenshots/atasco_pantalla_{marca}.png")
                except: pass
                try:
                    html_emergencia = await page.content()
                    with open(f"logs/screenshots/atasco_codigo_{marca}.txt", "w", encoding="utf-8") as f:
                        f.write(html_emergencia)
                except: pass
                return False, "TIMEOUT_CARGA_PAGOMOVIL"

            try: await target_frame.evaluate("window.scrollTo(0, document.body.scrollHeight);")
            except: pass
            await asyncio.sleep(0.5)

            # ======================================================
            # 3. AUDITORÍA DE SALDO DINÁMICA
            # ======================================================
            logger.info("⏳ Cazando saldo disponible dinámicamente...")
            saldo_actual = 0.0
            tiempo_saldo = time.time()
            
            while (time.time() - tiempo_saldo) < 6.0:
                try:
                    texto_completo = await target_frame.evaluate("() => document.body ? document.body.innerText : ''")
                    match_saldo = re.search(r'Saldo Disponible:\s*([\d\.]+,\d{2})', texto_completo, re.IGNORECASE)
                    if match_saldo:
                        saldo_str = match_saldo.group(1).replace('.', '').replace(',', '.')
                        saldo_temp = float(saldo_str)
                        if saldo_temp > 0:
                            saldo_actual = saldo_temp
                            break
                except: pass
                await asyncio.sleep(0.5)

            actualizar_saldo_json(cuenta_nombre, saldo_actual, payment_data)

            if saldo_actual > 0:
                dinero_durmiendo = float(payment_data.get("dinero_durmiendo", 0.0))
                logger.info(f"💰 Auditoría - Saldo detectado: Bs. {saldo_actual:,.2f} | Orden: Bs. {monto_orden_float:,.2f} | Durmiendo: Bs. {dinero_durmiendo:,.2f}")

                if saldo_actual < monto_orden_float:
                    error_msg = (
                        f"⛔ **FONDOS INSUFICIENTES PARA LA ORDEN:**\n"
                        f"🏦 **Cuenta:** `{cuenta_nombre}`\n"
                        f"💵 **Saldo actual:** Bs. {saldo_actual:,.2f}\n"
                        f"📉 **Monto a pagar:** Bs. {monto_orden_float:,.2f}\n\n"
                        f"La cuenta no tiene saldo para cubrir este pago. Abortando Pago Móvil."
                    )
                    logger.critical(f"La cuenta {cuenta_nombre} no puede cubrir el monto.")
                    await enviar_alerta_telegram(error_msg)
                    return False, "FONDOS_INSUFICIENTES"

                elif (saldo_actual - monto_orden_float) < dinero_durmiendo:
                    payment_data["apagar_cuenta_despues"] = True 
            else:
                logger.warning("No se pudo extraer el saldo visualmente, el bot intentará continuar a ciegas.")

            # ======================================================
            # 4. INYECCIÓN DIRECTA EN IDs REALES (NÚCLEO BANESCO)
            # ======================================================
            prefijo_tel = telefono[:4]
            numero_tel = telefono[4:]
            tipo_doc = cedula[0].upper()
            numero_doc = "".join(filter(str.isdigit, cedula)) 

            logger.info(f"Escribiendo formulario... Cédula a inyectar: {numero_doc}")

            try:
                # 🔥 Inyección directa blindada usando la función interna de JS 🔥
                js_fill = f"""() => {{
                    let inyectar = (id, valor) => {{
                        let el = document.getElementById(id);
                        if(el) {{
                            el.value = valor;
                            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            el.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                        }}
                    }};

                    inyectar('pref', '{prefijo_tel}');
                    inyectar('tel', '{numero_tel}');
                    inyectar('NacCli', '{tipo_doc}');
                    inyectar('ced', '{numero_doc}');
                    inyectar('monto', '{monto}');
                    inyectar('concepto', 'pago');
                    
                    let selBanco = document.getElementById('banco');
                    if (selBanco) {{
                        let opcion = Array.from(selBanco.options).find(opt => opt.value.includes('{codigo_banco}') || opt.text.includes('{codigo_banco}'));
                        if (opcion) {{
                            selBanco.value = opcion.value;
                            selBanco.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            selBanco.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        }}
                    }}
                }}"""
                
                await target_frame.evaluate(js_fill)
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Fallo llenando formulario nativo: {e}")
                os.makedirs("logs/screenshots", exist_ok=True)
                marca = int(time.time())
                try: 
                    await page.screenshot(path=f"logs/screenshots/emergencia_js_{order_id}_{marca}.png", full_page=True)
                except: pass
                
                # 🔥 CAJA NEGRA: EXTRACCIÓN HTML SOLO EN CASO DE ERROR 🔥
                try:
                    if target_frame:
                        html_error = await target_frame.content()
                    else:
                        html_error = await page.content()
                    with open(f"logs/screenshots/codigo_error_js_{order_id}_{marca}.txt", "w", encoding="utf-8") as f:
                        f.write(html_error)
                except: pass
                
                return False, "ERROR_LLENADO_NATIVO"
            
            # ======================================================
            # 5. CLIC INICIAL DIRECTO (🔥 FIX: Pagar o Aceptar 🔥)
            # ======================================================
            logger.info("⚡ Disparando clic inicial...")
            
            # =========================================================
            # 🛑 ÚLTIMA MIRADA: ¿LA ORDEN SIGUE VIVA EN BINANCE? 🛑
            # =========================================================
            verificador = payment_data.get("verificador_orden")
            if verificador:
                orden_viva = await verificador() 
                if not orden_viva:
                    logger.warning(f"🚨 ¡ABORTO DE EMERGENCIA! La orden {order_id} fue cancelada en Binance mientras llenábamos los datos.")
                    payment_data["pago_enviado"] = False
                    return False, "ORDEN_CANCELADA" 
            # =========================================================
            
            payment_data["pago_enviado"] = True
            
            try:
                btn_ini = target_frame.locator("input[value='Pagar']:visible, button:has-text('Pagar'):visible, input[value='Aceptar']:visible, button:has-text('Aceptar'):visible").last
                await btn_ini.click(force=True, timeout=500)
            except:
                await target_frame.evaluate("""() => { 
                    let btn = Array.from(document.querySelectorAll('input, button, a')).reverse().find(e => {
                        let txt = (e.value || e.innerText || "").toUpperCase();
                        return (txt.includes('PAGAR') || txt.includes('ACEPTAR')) && e.offsetParent !== null;
                    });
                    if(btn) btn.click(); 
                }""")
            
            tiempo_inicio = time.time()
            estado_respuesta = None
            
            while (time.time() - tiempo_inicio) < 15.0:
                for frame in page.frames:
                    try:
                        texto_up = await frame.evaluate("() => document.body ? document.body.innerText.toUpperCase() : ''")
                        
                        # 🔥 1. DETECCIÓN DE DATOS INVÁLIDOS (Sin clics para evitar que Chrome se congele) 🔥
                        if "LOS DATOS INTRODUCIDOS PRESENTAN ERRORES" in texto_up or "POR FAVOR INGRESE LOS DATOS" in texto_up or "NO PODEMOS PROCESAR" in texto_up or "P2PBACK-696" in texto_up: 
                            estado_respuesta = "DATOS_INVALIDOS"
                            break # ¡Sale inmediatamente del bucle sin tocar la página!

                        # 2. Otros errores Banesco
                        if "FONDOS INSUFICIENTES" in texto_up: estado_respuesta = "FONDOS_INSUFICIENTES"; break
                        if "EXCEDE EL MÁXIMO PERMITIDO" in texto_up or "P2PBACK-934" in texto_up: estado_respuesta = "LIMITE_EXCEDIDO"; break
                        if "CONFIRMACI" in texto_up or "OPERACIÓN EXITOSA" in texto_up or "CONTINGENCIA" in texto_up or "CONSULTE EN SU CORREO" in texto_up: estado_respuesta = "CONFIRMACION"; break
                        
                        # 🔥 3. DETECCIÓN DE ERRORES TEMPORALES (Solo 388 para reintentos) 🔥
                        if "REGISTRO NO EXISTENTE" in texto_up or "388" in texto_up:
                            estado_respuesta = "REGISTRO_NO_EXISTENTE"
                            try:
                                btn_err = frame.locator("input[value='Aceptar']:visible, button:has-text('Aceptar'):visible").last
                                if await btn_err.count() > 0: await btn_err.click(force=True, timeout=500)
                            except: pass
                            break
                    except: pass
                if estado_respuesta: break
                await asyncio.sleep(0.05)
                
            if estado_respuesta == "REGISTRO_NO_EXISTENTE":
                logger.warning("⚠️ Banesco arrojó un error temporal de plataforma. Clic en 'Aceptar' y reintentando pago...")
                await asyncio.sleep(2)
                continue 
                
            if not estado_respuesta: return False, "TIMEOUT_BANESCO"
            
            elif estado_respuesta == "DATOS_INVALIDOS": 
                logger.error("❌ Banesco rechazó los datos (P2PBACK-696 / Datos Inválidos).")
                os.makedirs("logs/screenshots", exist_ok=True)
                
                marca_tiempo = int(time.time())
                ruta_error = f"logs/screenshots/error_datos_{marca_tiempo}.png"
                ruta_html = f"logs/screenshots/codigo_error_datos_{marca_tiempo}.txt"
                
                try: 
                    await page.screenshot(path=ruta_error)
                    # 🔥 CAJA NEGRA 100% GARANTIZADA DESDE EL IFRAME 🔥
                    if target_frame:
                        html_mortal = await target_frame.content()
                    else:
                        html_mortal = await page.content()
                        
                    with open(ruta_html, "w", encoding="utf-8") as f:
                        f.write(html_mortal)
                    logger.info(f"✅ Código HTML guardado exitosamente en: {ruta_html}")
                except Exception as ex: 
                    logger.error(f"Fallo interno guardando el HTML: {ex}")
                
                mensaje_error = (
                    f"⚠️ **REVISIÓN MANUAL REQUERIDA:**\n"
                    f"🏦 **Cuenta asignada:** `{cuenta_nombre}`\n"
                    f"🧾 **Orden:** `{order_id}`\n\n"
                    f"Banesco arrojó 'Datos Inválidos' o 'P2PBACK-696'. La orden irá a cuarentena."
                )
                try: await enviar_foto_telegram(ruta_error, mensaje_error)
                except: pass
                
                payment_data["pago_enviado"] = False
                return False, "DATOS_INVALIDOS"
                
            elif estado_respuesta == "LIMITE_EXCEDIDO": 
                logger.error(f"🛑 Banesco rechazó el monto por límite excedido en {cuenta_nombre}.")
                os.makedirs("logs/screenshots", exist_ok=True)
                ruta_error = f"logs/screenshots/limite_{int(time.time())}.png"
                try: await page.screenshot(path=ruta_error) 
                except: pass
                
                mensaje_error = (
                    f"🛑 **CUENTA AGOTADA (LÍMITE BANCARIO):** `{cuenta_nombre}`\n"
                    f"🧾 **Orden en espera:** `{order_id}`\n\n"
                    f"Banesco indica que el monto excede el máximo permitido (P2PBACK-934).\n"
                    f"**La cuenta ha sido APAGADA automáticamente.** El bot buscará otra cuenta activa para pagar esta orden."
                )
                try: await enviar_foto_telegram(ruta_error, mensaje_error)
                except: pass
                
                payment_data["pago_enviado"] = False
                return False, "LIMITE_EXCEDIDO"


            elif estado_respuesta == "FONDOS_INSUFICIENTES": return False, "FONDOS_INSUFICIENTES"
            elif estado_respuesta == "CONFIRMACION": break
             
            
        if intentos_form >= 3 and estado_respuesta == "REGISTRO_NO_EXISTENTE":
            return False, "ERROR_BANESCO_388"

        # ======================================================
        # 6. BUCLE DE OTP Y RECIBO
        # ======================================================
        intentos_otp = 0
        max_intentos = 2
        recibo_ok = False

        while intentos_otp < max_intentos:
            intentos_otp += 1
            pide_otp = False
            tiempo_espera = time.time()
            
            logger.info(f"⚡ Disparando confirmación definitiva (Intento OTP {intentos_otp}/{max_intentos})...")
            
            while (time.time() - tiempo_espera) < 45.0:
                for frame in page.frames:
                    try:
                        texto_pantalla = await frame.evaluate("() => document.body ? document.body.innerText.toUpperCase() : ''")
                        
                        # 🔥 CAZADOR DE ERRORES EN TIEMPO REAL (Fase OTP) 🔥
                        if "EXCEDE EL MÁXIMO PERMITIDO" in texto_pantalla or "P2PBACK-934" in texto_pantalla:
                            logger.warning("🛑 Límite excedido detectado mientras se esperaba el OTP. Abortando...")
                            payment_data["pago_enviado"] = False
                            return False, "LIMITE_EXCEDIDO"
                            
                        if "FONDOS INSUFICIENTES" in texto_pantalla:
                            payment_data["pago_enviado"] = False
                            return False, "FONDOS_INSUFICIENTES"

                       # 🔥 CAZADOR DE ERRORES P2PBACK-696 (PLAN B) 🔥
                        if "NO PODEMOS PROCESAR" in texto_pantalla or "P2PBACK-696" in texto_pantalla:
                            logger.warning("🛑 Error P2PBACK-696 (Banco Caído/Rechazado). Forzando rutina de DATOS_INVALIDOS...")
                            
                            os.makedirs("logs/screenshots", exist_ok=True)
                            ruta_696 = f"logs/screenshots/error_696_{order_id}_{int(time.time())}.png"
                            try: 
                                await page.screenshot(path=ruta_696)
                                mensaje_error = (
                                    f"⚠️ **ERROR 696 - PLAN B ACTIVADO:**\n"
                                    f"🏦 **Cuenta:** `{cuenta_nombre}`\n"
                                    f"🧾 **Orden:** `{order_id}`\n\n"
                                    f"Banesco bloqueó el pago (P2PBACK-696). El bot le pedirá al cliente otros datos por Binance y entrará en modo Testamento."
                                )
                                await enviar_foto_telegram(ruta_696, mensaje_error)
                            except: pass

                            payment_data["pago_enviado"] = False
                            return False, "DATOS_INVALIDOS"
                            
                        if "OPERACIÓN EXITOSA" in texto_pantalla or "N° DE RECIBO" in texto_pantalla:
                            texto_limpio = texto_pantalla.replace("-", "").replace(" ", "").replace(".", "")
                            if telefono in texto_limpio and numero_doc in texto_limpio:
                                recibo_ok = True
                                logger.info("✅ Auditoría de Recibo: Operación Exitosa verificada.")
                                break
                        
                        es_pantalla_otp = await frame.evaluate("""() => {
                            let inputs = Array.from(document.querySelectorAll('input')).filter(e => e.offsetParent !== null && !e.disabled && !e.readOnly);
                            let otpField = inputs.find(i => i.type === 'password' || (i.id && i.id.toLowerCase().includes('clave')) || (i.id && i.id.toLowerCase().includes('otp')));
                            return otpField !== undefined;
                        }""")
                        
                        if es_pantalla_otp:
                            pide_otp = True
                            target_frame = frame
                            break
                            
                        if "CONSULTE EN SU CORREO" in texto_pantalla or "MENSAJES DE BANESCO CON LA CLAVE" in texto_pantalla:
                            btn_info = frame.locator("input[value='Aceptar']:visible, button:has-text('Aceptar'):visible").last
                            if await btn_info.count() > 0:
                                await btn_info.click(force=True, timeout=500)
                                logger.info("👉 Aviso previo de OTP cerrado. Avanzando a la caja fuerte...")
                                await asyncio.sleep(1.0)
                            continue 
                            
                        # 🔥 Manejo inteligente de ventanas emergentes sin hacer spam de clics 🔥
                        if "POSIBLE OPERACIÓN DUPLICADA" in texto_pantalla:
                            btn_dup = frame.locator("#enviar").last
                            if await btn_dup.count() > 0 and await btn_dup.is_visible():
                                await btn_dup.click(force=True, timeout=500)
                                logger.info("⚠️ Alerta de operación duplicada aceptada.")
                                await asyncio.sleep(1.0)
                            continue
                            
                        # 🔥 NUEVO: Manejo de la pantalla intermedia de Confirmación 🔥
                        if "CONFIRMACIÓN DE PAGO" in texto_pantalla or "¿ESTÁ USTED SEGURO" in texto_pantalla:
                            btn_conf = frame.locator("input[value='Pagar']:visible, button:has-text('Pagar'):visible, input[value='Aceptar']:visible, button:has-text('Aceptar'):visible").last
                            if await btn_conf.count() > 0 and await btn_conf.is_visible():
                                await btn_conf.click(force=True, timeout=500)
                                logger.info("✅ Confirmación de Pago aceptada. Solicitando OTP...")
                                await asyncio.sleep(2.0)
                            continue 
                    except: pass
                
                if recibo_ok or pide_otp: break
                await asyncio.sleep(0.05)

            if recibo_ok: break

            if pide_otp:
                otp = CACHE_OTP_SESIONES.get(cuenta_nombre)
                if otp:
                    logger.info(f"⚡ MODO RÁFAGA: Reutilizando OTP activo en memoria ({otp})...")
                else:
                    espera_correo = 10.0 if intentos_otp == 1 else 4.0
                    logger.warning(f"🛡️ Extrayendo OTP de Seguridad... Esperando {espera_correo}s para correo nuevo...")
                    await asyncio.sleep(espera_correo) 
                    
                    correo = payment_data.get("correo") or payment_data.get("seguridad_banco", {}).get("correo") or "briangonzalez060899@gmail.com"
                    clave_correo = payment_data.get("clave_correo") or payment_data.get("seguridad_banco", {}).get("clave_correo") or "rfhs scdl ytuy dccp"
                        
                    otp = await interceptar_otp_gmail(correo, clave_correo, timeout=40)
                    if not otp: return False, "TIMEOUT_CORREO_OTP"
                    
                    logger.info(f"¡OTP Capturado ({otp})! Guardando en memoria...")
                    CACHE_OTP_SESIONES[cuenta_nombre] = otp

                try:
                    js_inject_otp = """(codigo) => {
                        let inputs = Array.from(document.querySelectorAll('input')).filter(e => e.offsetParent !== null && !e.disabled && !e.readOnly);
                        let otpField = inputs.find(i => i.type === 'password' || (i.id && i.id.toLowerCase().includes('clave')) || (i.id && i.id.toLowerCase().includes('otp')));
                        if(otpField) { 
                            otpField.value = codigo; 
                            otpField.dispatchEvent(new Event('input', {bubbles: true}));
                            otpField.dispatchEvent(new Event('change', {bubbles: true})); 
                            otpField.dispatchEvent(new Event('blur', {bubbles: true}));
                            return true;
                        }
                        return false;
                    }"""
                    await target_frame.evaluate(js_inject_otp, otp)
                    await asyncio.sleep(0.5)
                    
                    btn_otp = target_frame.locator("input[value='Aceptar']:visible, button:has-text('Aceptar'):visible").last
                    if await btn_otp.count() > 0: await btn_otp.click(force=True, timeout=100)
                    
                    tiempo_recibo_otp = time.time()
                    necesita_reintento = False
                    
                    while (time.time() - tiempo_recibo_otp) < 45.0:
                        for f in page.frames:
                            try:
                                texto_eval = await f.evaluate("() => { if(!document.body) return ''; let t=document.body.innerText; document.querySelectorAll('input').forEach(i=>t+=' '+(i.value||'')); return t.toUpperCase(); }")
                                
                                # 🔥 CAZADOR DE ERRORES POST-OTP 🔥
                                if "EXCEDE EL MÁXIMO PERMITIDO" in texto_eval or "P2PBACK-934" in texto_eval:
                                    logger.warning("🛑 Límite excedido (P2PBACK-934) tras ingresar el OTP. Abortando...")
                                    
                                    # --- NUEVO: CAPTURA Y ENVÍO A TELEGRAM DE LÍMITE QUEMADO ---
                                    os.makedirs("logs/screenshots", exist_ok=True)
                                    ruta_limite = f"logs/screenshots/limite_quemado_{order_id}_{int(time.time())}.png"
                                    try: 
                                        await page.screenshot(path=ruta_limite)
                                        msg_limite = (
                                            f"🛑 **CUENTA QUEMADA POR LÍMITE (P2PBACK-934):**\n"
                                            f"🏦 **Cuenta:** `{cuenta_nombre}`\n"
                                            f"🧾 **Orden en pausa:** `{order_id}`\n\n"
                                            f"Banesco rechazó el pago en el último paso por límite excedido. La cuenta ha sido bloqueada en RAM y la orden pasará a la siguiente cuenta disponible."
                                        )
                                        await enviar_foto_telegram(ruta_limite, msg_limite)
                                    except Exception as e: 
                                        logger.error(f"No se pudo enviar foto del límite a Telegram: {e}")
                                    # -----------------------------------------------------------

                                    payment_data["pago_enviado"] = False
                                    return False, "LIMITE_EXCEDIDO"
                                if "FONDOS INSUFICIENTES" in texto_eval:
                                    payment_data["pago_enviado"] = False
                                    return False, "FONDOS_INSUFICIENTES"

                                if "OPERACIÓN EXITOSA" in texto_eval or "N° DE RECIBO" in texto_eval:
                                    texto_limpio = texto_eval.replace("-", "").replace(" ", "").replace(".", "")
                                    if telefono in texto_limpio and numero_doc in texto_limpio:
                                        recibo_ok = True
                                        logger.info("✅ Auditoría de Recibo Post-OTP: Operación Exitosa verificada.")
                                        break
                                    
                                if "INCORRECTAMENTE" in texto_eval or "ERRÓNEAMENTE" in texto_eval:
                                    logger.warning("🚨 BANESCO RECHAZÓ EL OTP (Clave vieja/errónea). Destruyendo caché y preparando reintento en caliente.")
                                    CACHE_OTP_SESIONES.pop(cuenta_nombre, None)
                                    necesita_reintento = True
                                    
                                    await f.evaluate("""() => {
                                        let btns = Array.from(document.querySelectorAll('input, button, a'));
                                        let aceptar = btns.find(b => (b.value || b.innerText || '').toUpperCase().includes('ACEPTAR'));
                                        if(aceptar) aceptar.click();
                                    }""")
                                    break
                            except: pass
                        if recibo_ok or necesita_reintento: break
                        await asyncio.sleep(0.5)
                        
                    if necesita_reintento:
                        if intentos_otp < max_intentos:
                            logger.info("🔁 Reintentando OTP desde cero...")
                            continue 
                        else: return False, "OTP_RECHAZADO"
                except Exception as e: return False, f"FALLO_INYECCION_OTP: {e}"
            else: break

        # ======================================================
        # 8. CAPTURA DEL RECIBO Y DESCUENTO DE SALDO
        # ======================================================
        os.makedirs("data/recibos", exist_ok=True)
        ruta_foto = f"data/recibos/PAGOMOVIL_{order_id}.png"
        
        # 🔥 PLAN B FINAL: Si la pantalla se colgó, buscar el recibo en el correo 🔥
        if not recibo_ok and payment_data.get("pago_enviado", False):
            logger.warning("⏳ Banesco se colgó y no mostró el recibo verde. Iniciando Plan B (Rescate por Gmail)...")
            correo_seg = payment_data.get("correo") or payment_data.get("seguridad_banco", {}).get("correo")
            clave_seg = payment_data.get("clave_correo") or payment_data.get("seguridad_banco", {}).get("clave_correo")
            
            if correo_seg and clave_seg:
                ref_gmail = await verificar_pago_gmail(correo_seg, clave_seg, numero_doc, monto_orden_float)
                if ref_gmail:
                    logger.info(f"✅ ¡RESCATE GMAIL EXITOSO! Pago validado de forma invisible. Ref: {ref_gmail}")
                    recibo_ok = True

        if recibo_ok:
            if saldo_actual > 0:
                saldo_post_pago = round(saldo_actual - monto_orden_float, 2)
                actualizar_saldo_json(cuenta_nombre, saldo_post_pago, payment_data)

            logger.info("✂️ Recortando el recibo para eliminar el menú lateral y espacios en blanco...")
            try:
                await target_frame.evaluate("""() => {
                    document.body.style.minHeight = 'auto'; 
                    document.body.style.height = 'auto';
                    document.documentElement.style.height = 'auto';
                    document.body.style.paddingBottom = '30px'; 
                }""")
                await target_frame.locator("body").screenshot(path=ruta_foto)
            except Exception:
                await page.screenshot(path=ruta_foto, full_page=True)
                
            logger.info(f"✅ ¡Recibo capturado exitosamente!")
            
            # 🔥 AUDITORÍA FINAL: Volver al inicio y leer saldo REAL (Cazador Rápido) 🔥
            logger.info("🏠 Volviendo al Inicio para auditar el saldo real en vivo...")
            try:
                for f in page.frames:
                    try:
                        await f.evaluate("""() => {
                            let imgs = Array.from(document.querySelectorAll('img'));
                            let imgCasita = imgs.find(img => img.src.toLowerCase().includes('home') || img.src.toLowerCase().includes('inicio'));
                            if (imgCasita && imgCasita.parentElement) { imgCasita.parentElement.click(); } 
                            else {
                                let btn = Array.from(document.querySelectorAll('a')).find(a => (a.title && a.title.toLowerCase().includes('inicio')));
                                if (btn) btn.click();
                            }
                        }""")
                    except: pass
                
                logger.info("👀 Escaneando la tabla de Banesco en busca del saldo...")
                tiempo_auditoria = time.time()
                saldo_encontrado = False
                
                # 🔥 CAZADOR DE SALDO INSTANTÁNEO (Basado en el HTML extraído) 🔥
                while (time.time() - tiempo_auditoria) < 8.0:
                    try:
                        # Extraemos el saldo directo desde la tabla sin leer el resto de la página
                        saldo_str = await page.evaluate("""() => {
                            let enlaces = Array.from(document.querySelectorAll('a'));
                            let cuenta = enlaces.find(a => a.innerText.includes('0134-'));
                            if (cuenta && cuenta.parentElement && cuenta.parentElement.nextElementSibling) {
                                return cuenta.parentElement.nextElementSibling.innerText.trim();
                            }
                            return null;
                        }""")
                        
                        if saldo_str:
                            saldo_limpio = float(saldo_str.replace('.', '').replace(',', '.'))
                            apagar_ahora = payment_data.get("apagar_cuenta_despues", False)
                            actualizar_saldo_json(cuenta_nombre, saldo_limpio, payment_data, apagar=apagar_ahora)
                            
                            logger.info(f"💳 Auditoría Final - Saldo REAL actualizado a: Bs. {saldo_limpio:,.2f}")
                            saldo_encontrado = True
                            break
                    except: pass
                    
                    await asyncio.sleep(0.5)
                    
                if not saldo_encontrado:
                    logger.warning("⚠️ El bot no pudo encontrar la celda del saldo a tiempo.")
                    
            except Exception as e:
                logger.warning(f"No se pudo volver al inicio o extraer el saldo: {e}")
            
            if "TEST" in str(order_id).upper():
                await enviar_foto_telegram(ruta_foto, f"✅ **TEST COMPLETADO:**\n🏦 Cuenta: `{cuenta_nombre}`\n📉 Monto debitado: Bs. {monto_orden_float:,.2f}")

            return True, ruta_foto

        else:
            await page.screenshot(path=f"data/errores/err_recibo_{order_id}.png", full_page=True)
            return False, "ERROR_RECIBO_INVALIDO"

    except Exception as e:
        logger.error(f"❌ CRASH GLOBAL DE PAGO MÓVIL: {e}")
        os.makedirs("data/errores", exist_ok=True)
        marca = int(time.time())
        try: await page.screenshot(path=f"data/errores/err_pm_{order_id}_{marca}.png", full_page=True)
        except: pass
        try:
            html_crash = await page.content()
            with open(f"data/errores/err_codigo_{order_id}_{marca}.txt", "w", encoding="utf-8") as f:
                f.write(html_crash)
        except: pass
        return False, str(e)
