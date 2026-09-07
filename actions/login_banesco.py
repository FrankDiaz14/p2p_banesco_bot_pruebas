"""
Módulo Orquestador de Inicio de Sesión.
(Modo Caos Humano: Tiempos de reacción y tecleo aleatorios para máxima evasión antibot).
"""

import asyncio
import logging
import os
import time
import random
from typing import Dict, Any

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError
from core.humanizer import generate_mouse_curve
from integrations.telegram_notifier import enviar_alerta_telegram, enviar_foto_telegram

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# --- DETECTOR ÁGIL ---
async def find_element_in_frames(page: Page, selector: str, timeout: int = 25000):
    start_time = time.time()
    while (time.time() - start_time) < (timeout / 1000.0):
        for frame in page.frames:
            loc = frame.locator(selector).first
            try:
                if await loc.is_visible():
                    return loc
            except Exception:
                pass
        await asyncio.sleep(0.15)
    raise PlaywrightTimeoutError(f"Timeout: Elemento {selector} no encontrado.")

# --- RATÓN ORGÁNICO CON PAUSA ALEATORIA ---
async def organic_mouse_move_and_click(page: Page, selector: str) -> None:
    target_locator = await find_element_in_frames(page, selector)
    box = await target_locator.bounding_box()
    if not box:
        raise ValueError(f"Sin coordenadas para: {selector}")
        
    target_x = box["x"] + box["width"] / 2.0
    target_y = box["y"] + box["height"] / 2.0
    
    curve_points = generate_mouse_curve((0.0, 0.0), (target_x, target_y), num_points=15)
    
    for px, py in curve_points:
        await page.mouse.move(px, py)
        await asyncio.sleep(0.003)
    
    # Pausa microscópica aleatoria antes de asentar el clic (entre 0.05 y 0.2 segundos)
    await asyncio.sleep(random.uniform(0.05, 0.2))
    await page.mouse.click(target_x, target_y)

# --- TECLADO FLUIDO ALEATORIO ---
async def type_organically(page: Page, selector: str, text: str) -> None:
    await organic_mouse_move_and_click(page, selector)
    target_locator = await find_element_in_frames(page, selector)
    
    # Calcula una velocidad de tecleo distinta para cada caja de texto (entre 30ms y 85ms por letra)
    velocidad_aleatoria = random.randint(30, 85)
    await target_locator.press_sequentially(text, delay=velocidad_aleatoria)

async def capture_failure(page: Page, reason: str, order_id: str = "N/A", nombre_cuenta: str = "N/A") -> None:
    try:
        os.makedirs("logs/screenshots", exist_ok=True)
        timestamp_actual = int(time.time())
        filepath_img = f"logs/screenshots/login_crash_{reason}_{timestamp_actual}.png"
        filepath_html = f"logs/screenshots/login_crash_{reason}_{timestamp_actual}.html"
        
        # 1. Toma la foto
        await page.screenshot(path=filepath_img, full_page=True)
        
        # 2. 🔥 EXTRAE EL HTML COMPLETO (Caja Negra) 🔥
        try:
            html_mortal = await page.content()
            with open(filepath_html, "w", encoding="utf-8") as f:
                f.write(html_mortal)
            logger.info(f"💾 Caja Negra guardada: {filepath_img} y .html")
        except Exception as html_err:
            logger.error(f"No se pudo extraer el HTML: {html_err}")

        mensaje_error = (
            f"🚨 **ERROR EN BANESCO (Fase de Login):**\n"
            f"🏦 **Cuenta:** `{nombre_cuenta}`\n"
            f"🧾 **Orden:** `{order_id}`\n\n"
            f"Motivo: `{reason}`\n"
            f"Se ha guardado una copia del código fuente (.html) en el servidor para análisis."
        )
        await enviar_foto_telegram(filepath_img, mensaje_error)
    except Exception as e:
        logger.error(f"Fallo crítico en capture_failure: {e}")

async def execute_login(page: Page, payment_data: Dict[str, Any]) -> bool:
    order_id = str(payment_data.get("order_id", "N/A"))
    nombre_cuenta = str(payment_data.get("nombre_cuenta", "N/A"))

    try:
        if "login" not in page.url.lower() and page.url != "about:blank":
            logger.info("Verificando si la sesión en caché sigue viva...")
            sesion_viva = False
            for frame in page.frames:
                if await frame.locator("#m_1").first.is_visible(timeout=2000):
                    sesion_viva = True
                    break
            
            if sesion_viva:
                logger.info("⚡ ¡Sesión Viva Confirmada! Saltando Login...")
                await enviar_alerta_telegram(f"⚡ **Fase Ráfaga:** Reutilizando sesión (`{nombre_cuenta}`) | 🧾 Orden: `{order_id}`")
                return True
    except Exception:
        pass

    payment_data["nueva_sesion"] = True
    datos_banco = payment_data.get("seguridad_banco", {})
    
    credentials = {
        "username": datos_banco.get("usuario", "").strip(),
        "password": datos_banco.get("clave", "").strip()
    }
    security_questions = datos_banco.get("preguntas", {})

    if not credentials["username"] or not credentials["password"]:
        return False

    URL_BANCO = "https://www.banesconline.com/mantis/Website/Login.aspx"
    SEL_USUARIO, SEL_BOTON_ACEPTAR = "#txtUsuario", "#bAceptar"
    SEL_PREGUNTA_1_TEXT, SEL_RESPUESTA_1 = "#lblPrimeraP", "#txtPrimerar"
    SEL_PREGUNTA_2_TEXT, SEL_RESPUESTA_2 = "#lblSegundaP", "#txtSegundaR"
    SEL_CLAVE, SEL_DASHBOARD = "#txtClave", "#m_1"

    MAX_REINTENTOS = 3
    intento_actual = 0

    while intento_actual < MAX_REINTENTOS:
        intento_actual += 1
        try:
            if intento_actual > 1:
                await page.context.clear_cookies()
                await asyncio.sleep(1.0)

            logger.info(f"Navegando a Banesco... (Intento {intento_actual})")
            if intento_actual == 1:
                await enviar_alerta_telegram(f"🌐 **Fase 1:** Conectando a Banesco (`{nombre_cuenta}`) | 🧾 Orden: `{order_id}`")
            
            await page.goto(URL_BANCO, wait_until="networkidle", timeout=60000)
            
            logger.info("Escribiendo Usuario...")
            if intento_actual == 1:
                await enviar_alerta_telegram(f"👤 **Fase 2:** Inyectando credenciales...")
            
            await type_organically(page, SEL_USUARIO, credentials["username"])
            
            # Pausa aleatoria antes de aceptar (ej. 0.38s, 0.61s, 0.45s)
            await asyncio.sleep(random.uniform(0.3, 0.7)) 
            await organic_mouse_move_and_click(page, SEL_BOTON_ACEPTAR)
            
            logger.info("⏳ Detectando próxima pantalla...")
            
            fase_activa = None
            alerta_visible = False
            start_time = time.time()
            
            while (time.time() - start_time) < 25.0:
                for frame in page.frames:
                    try:
                        if await frame.locator(SEL_CLAVE).first.is_visible():
                            fase_activa = "clave"
                            break
                        elif await frame.locator(SEL_RESPUESTA_1).first.is_visible():
                            fase_activa = "preguntas"
                            break
                            
                        # 🔥 DETECCIÓN BLINDADA DE SESIÓN FANTASMA 🔥
                        texto_pantalla = await frame.evaluate("() => document.body ? document.body.innerText.toUpperCase() : ''")
                        if "CONEXIÓN ACTIVA" in texto_pantalla or "CONEXION ACTIVA" in texto_pantalla:
                            alerta_visible = True
                            break
                    except: pass
                
                if fase_activa or alerta_visible: break
                await asyncio.sleep(0.15)
                
            if alerta_visible:
                logger.warning("⚠️ Sesión fantasma detectada. Destruyendo sesión vieja...")
                
                # 🔥 DOBLE CLIC DE SEGURIDAD (JS + Playwright Nativo) 🔥
                for f in page.frames:
                    try:
                        await f.evaluate("""() => { 
                            let btn = Array.from(document.querySelectorAll('input, button, a')).find(b => (b.value || b.innerText || '').toUpperCase().includes('ACEPTAR')); 
                            if(btn) btn.click(); 
                        }""")
                        
                        btn = f.locator("input[value='Aceptar'], button:has-text('Aceptar')").last
                        if await btn.count() > 0: 
                            await btn.click(force=True, timeout=1500)
                    except: pass
                
                logger.info("♻️ Refrescando página tras forzar el cierre de sesión...")
                await asyncio.sleep(4.0)
                await page.goto(URL_BANCO, wait_until="domcontentloaded")
                await asyncio.sleep(2.0)
                continue
                
            if not fase_activa:
                if intento_actual == MAX_REINTENTOS:
                    await capture_failure(page, "timeout_pantalla_2", order_id, nombre_cuenta)
                continue

            await enviar_alerta_telegram("🛡️ **Fase 3:** Resolviendo validaciones...")

            if fase_activa == "preguntas":
                logger.info("Respondiendo preguntas dinámicas...")
                loc_q1 = await find_element_in_frames(page, SEL_PREGUNTA_1_TEXT)
                loc_q2 = await find_element_in_frames(page, SEL_PREGUNTA_2_TEXT)
                q1_text, q2_text = await loc_q1.inner_text(), await loc_q2.inner_text()
                
                ans1 = next((resp for clave, resp in security_questions.items() if clave != "" and clave in q1_text.lower()), None)
                ans2 = next((resp for clave, resp in security_questions.items() if clave != "" and clave in q2_text.lower()), None)
                    
                if not ans1 or not ans2: 
                    await capture_failure(page, "pregunta_desconocida", order_id, nombre_cuenta)
                    return False
                    
                await type_organically(page, SEL_RESPUESTA_1, str(ans1))
                await type_organically(page, SEL_RESPUESTA_2, str(ans2))
                
                # Segunda pausa aleatoria
                await asyncio.sleep(random.uniform(0.3, 0.7))
                await organic_mouse_move_and_click(page, SEL_BOTON_ACEPTAR)
                
                await find_element_in_frames(page, SEL_CLAVE, timeout=15000)

            logger.info("Escribiendo Contraseña...")
            await type_organically(page, SEL_CLAVE, credentials["password"])
            
            # Tercera pausa aleatoria
            await asyncio.sleep(random.uniform(0.3, 0.7))
            await organic_mouse_move_and_click(page, SEL_BOTON_ACEPTAR)
            
            logger.info("Verificando ingreso al Dashboard...")
            tiempo_dash = time.time()
            ingreso_exitoso = False
            
            while (time.time() - tiempo_dash) < 25.0:
                for frame in page.frames:
                    try:
                        # 1. Buscamos el menú principal para confirmar éxito
                        if await frame.locator(SEL_DASHBOARD).first.is_visible():
                            ingreso_exitoso = True
                            break
                        
                        # 2. 🔥 CAZADOR DE SESIÓN FANTASMA TARDÍA 🔥
                        texto_pantalla = await frame.evaluate("() => document.body ? document.body.innerText.toUpperCase() : ''")
                        if "CONEXIÓN ACTIVA" in texto_pantalla or "CONEXION ACTIVA" in texto_pantalla:
                            logger.warning("⚠️ Sesión fantasma tardía detectada. Destruyendo sesión vieja...")
                            
                            # Clic brutal JS + Playwright
                            await frame.evaluate("""() => { 
                                let btn = Array.from(document.querySelectorAll('input, button')).find(b => (b.value || b.innerText || '').toUpperCase().includes('ACEPTAR')); 
                                if(btn) btn.click(); 
                            }""")
                            try:
                                btn_aceptar = frame.locator("input[value='Aceptar']:visible, button:has-text('Aceptar'):visible").last
                                if await btn_aceptar.count() > 0:
                                    await btn_aceptar.click(force=True, timeout=1000)
                            except: pass
                            
                            await asyncio.sleep(2.0)
                            raise Exception("SESION_FANTASMA_TARDIA") 
                    except Exception as ex: 
                        if "SESION_FANTASMA_TARDIA" in str(ex):
                            # 🔥 FIX VITAL: Forzamos la navegación a la página de login limpia antes de lanzar el error
                            logger.info("♻️ Refrescando página tras forzar el cierre de sesión tardío...")
                            await page.goto(URL_BANCO, wait_until="domcontentloaded")
                            await asyncio.sleep(1.0)
                            raise ex # Ahora sí pasamos el error para el reintento
                
                if ingreso_exitoso: 
                    break
                await asyncio.sleep(0.2)
                
            if not ingreso_exitoso:
                raise PlaywrightTimeoutError("Timeout: Banesco no cargó el Dashboard a tiempo.")
                
            await enviar_alerta_telegram(f"✅ **Fase 4:** ¡Login exitoso! (`{nombre_cuenta}`) | 🧾 Orden: `{order_id}`")
            return True 

        except Exception as e:
            logger.warning(f"Fallo en intento de Login {intento_actual}: {e}")
            if intento_actual == MAX_REINTENTOS:
                await capture_failure(page, "crash_general", order_id, nombre_cuenta)
            await asyncio.sleep(2.0)

    return False
