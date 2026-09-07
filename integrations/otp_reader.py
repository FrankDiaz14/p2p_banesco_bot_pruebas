"""
Módulo de integración IMAP para la extracción automatizada de códigos OTP.
(Versión Ráfaga: Ventana de 15 minutos para reutilizar el código de la misma sesión)
"""

import email
import email.utils
import imaplib
import logging
import os
import re
import time
from email.message import Message
from typing import Optional

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

class OTPReaderError(Exception): pass
class OTPAuthenticationError(OTPReaderError): pass
class OTPNetworkError(OTPReaderError): pass
class OTPNotFoundError(OTPReaderError): pass
class OTPParsingError(OTPReaderError): pass

class OTPReader:
    def __init__(self, email_account: str = None, app_password: str = None, host: str = "imap.gmail.com", port: int = 993) -> None:
        self.host = host
        self.port = port
        # Aislamiento: Usa las credenciales inyectadas, o busca en globales por si acaso
        self.email_account = email_account or os.environ.get("OTP_EMAIL_ACCOUNT")
        self.app_password = app_password or os.environ.get("OTP_APP_PASSWORD")

        if not self.email_account or not self.app_password:
            logger.warning("ADVERTENCIA: Faltan credenciales OTP_EMAIL_ACCOUNT o OTP_APP_PASSWORD en .env")

    def _get_email_body(self, msg: Message) -> str:
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if "attachment" in str(part.get("Content-Disposition")):
                    continue
                if part.get_content_type() in ("text/plain", "text/html"):
                    try:
                        charset = part.get_content_charset() or 'utf-8'
                        payload = part.get_payload(decode=True)
                        if payload:
                            body += payload.decode(charset, errors='replace') + " "
                    except Exception:
                        pass
        else:
            try:
                charset = msg.get_content_charset() or 'utf-8'
                payload = msg.get_payload(decode=True)
                if payload:
                    body = payload.decode(charset, errors='replace')
            except Exception:
                pass
        return body

    def _extract_otp_from_text(self, text: str) -> Optional[str]:
        pattern = r"\b\d{6,8}\b"
        matches = re.findall(pattern, text)
        if matches:
            return matches[0]
        return None

    def get_otp(self, sender_address: str = "notificacion@banesco.com", timeout: int = 180, interval: int = 4) -> str:
        if not self.email_account or not self.app_password:
            raise OTPAuthenticationError("Credenciales de correo no configuradas.")

        # TRUCO MODO RÁFAGA: En lugar de buscar un correo que llegue justo ahora, 
        # le damos una ventana de 15 MINUTOS hacia atrás.
        # Si Banesco no envía un código nuevo porque la sesión ya está abierta, 
        # el bot reciclará el último código recibido en esos 15 minutos y lo inyectará.
        bot_start_time = time.time() - (15 * 60) 
        mail = None

        try:
            mail = imaplib.IMAP4_SSL(self.host, self.port)
            mail.login(self.email_account, self.app_password)
            logger.info("Conectado a Gmail. Analizando correos por fecha de llegada...")

            while time.time() - (bot_start_time + (15 * 60)) < timeout:
                try:
                    mail.select("inbox")
                    status, messages = mail.search(None, f'(FROM "{sender_address}")')
                    
                    if status == "OK" and messages[0]:
                        email_ids = messages[0].split()
                        if email_ids:
                            latest_id = email_ids[-1]
                            res_status, data = mail.fetch(latest_id, '(RFC822)')
                            
                            if res_status == "OK" and data and data[0]:
                                msg = email.message_from_bytes(data[0][1])
                                
                                date_tuple = email.utils.parsedate_tz(msg.get('Date'))
                                if date_tuple:
                                    email_timestamp = email.utils.mktime_tz(date_tuple)
                                    
                                    # Si el correo tiene menos de 15 minutos de antigüedad, lo usamos
                                    if email_timestamp >= bot_start_time:
                                        body = self._get_email_body(msg)
                                        otp_code = self._extract_otp_from_text(body)
                                        
                                        if otp_code:
                                            logger.info(f">>> OTP Recuperado de la Sesión Actual: {otp_code} <<<")
                                            return otp_code
                except Exception as e:
                    logger.debug(f"Error leyendo buzón: {e}")

                time.sleep(interval)

            raise OTPNotFoundError(f"Timeout. No llegó ningún correo nuevo de {sender_address}.")

        finally:
            if mail:
                try:
                    mail.close()
                    mail.logout()
                except Exception:
                    pass
