"""
Módulo de Gestión de Navegación Automatizada (Playwright).

Este componente actúa como orquestador del ciclo de vida del motor web.
Lanza Chromium explícitamente en modo visible (Headless=False) y expone 
contextos aislados (BrowserContext) con huellas digitales realistas para 
evadir heurísticas básicas. Diseñado bajo el estándar de Async Context Manager 
para maximizar la resiliencia y prevenir fugas de memoria (memory leaks).
"""

import asyncio
import logging
from typing import Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Playwright,
    async_playwright,
)

# -----------------------------------------------------------------------------
# Configuración del Logger
# -----------------------------------------------------------------------------
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)


class BrowserManager:
    """
    Orquestador asíncrono del motor Chromium.
    
    Gestiona la instanciación, configuración y la estricta limpieza de 
    recursos y sockets pendientes si ocurre un fallo no previsto.
    """

    # User-Agent humano, moderno y realista para evitar usar la etiqueta de bot nativa.
    # Simula entorno Windows 10/11 con Chrome Desktop.
    REALISTIC_USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    
    # Resolución estándar solicitada para asegurar que el DOM del banco
    # renderice siempre la versión de escritorio completa.
    STANDARD_VIEWPORT: dict = {"width": 1920, "height": 1080}

    def __init__(self) -> None:
        """Inicializa los punteros de memoria en vacío."""
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None

    async def start_browser(self) -> Browser:
        """
        Inicializa el subsistema base e invoca el binario Chromium de forma asíncrona.
        """
        logger.info("Arrancando el ecosistema asíncrono de Playwright...")
        try:
            self.playwright = await async_playwright().start()
            
            logger.info("Lanzando Chromium explícitamente en modo visible (headless=False)...")
            self.browser = await self.playwright.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"]
            )
            logger.info("Navegador Chromium operativo.")
            return self.browser
            
        except PlaywrightError as e:
            logger.critical("Fallo catastrófico al intentar montar Chromium: %s", e)
            await self._cleanup_resources()
            raise

    async def create_stealth_context(self) -> BrowserContext:
        """
        Fabricante de entornos limpios, emulando la huella digital humana.
        """
        if not self.browser:
            raise RuntimeError(
                "Infracción de flujo: El motor Chromium no ha sido arrancado. "
                "Invoque start_browser() primeramente."
            )

        logger.info("Inyectando anti-fingerprint y construyendo nuevo BrowserContext...")
        try:
            context: BrowserContext = await self.browser.new_context(
                user_agent=self.REALISTIC_USER_AGENT,
                viewport=self.STANDARD_VIEWPORT,
                timezone_id="America/Caracas", 
                locale="es-ES",
                ignore_https_errors=True
            )
            logger.debug("Contexto sigiloso ensamblado con éxito.")
            return context
            
        except PlaywrightError as e:
            if "Target closed" in str(e) or "TargetClosed" in str(e):
                logger.error("Interrupción: El usuario cerró el navegador durante la inicialización del contexto.")
                raise
            logger.error("Error imprevisto en la ofuscación del contexto: %s", e)
            raise
        except Exception as e:
            logger.error("Error imprevisto en la ofuscación del contexto: %s", e)
            raise

    async def _cleanup_resources(self) -> None:
        """
        Ejecuta un barrido a nivel de procesos, matando de forma segura los hilos.
        """
        logger.info("Protocolo de emergencia / Limpieza estricta de memoria iniciado...")
        
        if self.browser:
            try:
                await self.browser.close()
                logger.debug("Browser despachado correctamente.")
            except Exception as e:
                logger.debug("Omitiendo fallo de cierre secundario de browser: %s", e)
            finally:
                self.browser = None
                
        if self.playwright:
            try:
                await self.playwright.stop()
                logger.debug("Bucle asíncrono del Playwright Manager detenido.")
            except Exception as e:
                logger.debug("Omitiendo fallo de cierre secundario del manager: %s", e)
            finally:
                self.playwright = None
                
        logger.info("Limpieza finalizada. Fugas de memoria mitigadas.")

    # -------------------------------------------------------------------------
    # Integración con Context Manager (try/except/finally arquitectónico)
    # -------------------------------------------------------------------------
    async def __aenter__(self) -> "BrowserManager":
        await self.start_browser()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        Captura de cierre abrupto y limpieza final garantizada bajo protocolo.
        """
        if exc_type is not None:
            if issubclass(exc_type, PlaywrightError) and ("Target closed" in str(exc_val) or "TargetClosed" in str(exc_val)):
                logger.error(
                    "DETECCIÓN DE IMPACTO (TargetClosedError): El navegador fue "
                    "cerrado de imprevisto por intervención manual (operador) o colapso "
                    "interno (Crash). El orquestador intervino la excepción."
                )
            else:
                logger.error(
                    "Excepción severa propagada desde la página hacia el orquestador: %s - %s", 
                    exc_type.__name__, 
                    exc_val
                )
                
        await self._cleanup_resources()