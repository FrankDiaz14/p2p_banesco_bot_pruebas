# Visión del Proyecto: Automatización P2P Banesco

## Objetivo Principal
Sistema RPA en Python con Playwright para procesar órdenes P2P de Binance de forma autónoma a través de Banesco (Venezuela). Incluye extracción de OTP por Gmail y notificaciones por Telegram.

## Reglas de Negocio Críticas
1. Soporte para 6 cuentas bancarias, seleccionando una activa y con saldo suficiente.
2. Leer saldo antes y después de la transferencia. Si el sobrante es menor a 100,000 VES, desactivar la cuenta inmediatamente.
3. Simular comportamiento humano con pausas de 32 a 45 segundos y velocidad de tecleo simulada.
4. Lectura de OTP dinámico vía IMAP en menos de 3 segundos.
5. Enviar comprobante de transferencia y alertas a un chat privado de Telegram.

## Arquitectura y Stack
- Lenguaje: Python 3.11+
- Automatización: Playwright (Async)
- Base de Datos: SQLite
- Despliegue: Docker, orquestado directamente en Open Claw.

## Metodología de Trabajo (Agentes)
- CEO: Define alcance y delega tareas paso a paso.
- Senior Coder: Escribe código modular, asíncrono y maneja excepciones.
- QA Inspector: Valida selectores, audita errores y da aprobación final.