import threading
import logging
import smtplib
from email.message import EmailMessage
import requests
import time
from typing import Optional, Dict

log = logging.getLogger(__name__)

class EmergencyNotifier:
    """
    Etapa 11: Gerenciador de Notificacoes Externas.
    Envia E-mails via SMTP e payloads JSON via Webhooks quando alertas criticos sao detectados.
    Executa chamadas de rede em background (Threads) para nao bloquear o pipeline principal.
    Possui Rate-Limiting para nao gerar spam de alertas seguidos.
    """
    
    def __init__(
        self,
        smtp_server: str = "smtp.gmail.com",
        smtp_port: int = 587,
        dest_email: str = "gabriellftavares@gmail.com",
        webhook_url: Optional[str] = None,
        cooldown_seconds: int = 60
    ):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.dest_email = dest_email
        self.webhook_url = webhook_url
        self.cooldown_seconds = cooldown_seconds
        
        # Tenta carregar as credenciais (se o arquivo existir e estiver preenchido)
        try:
            from config.secrets import SMTP_USER, SMTP_PASS
            self.smtp_user = SMTP_USER
            self.smtp_pass = SMTP_PASS
        except ImportError:
            self.smtp_user = None
            self.smtp_pass = None
        
        # Rate limiting: device_id -> timestamp ultimo alerta
        self._last_alert_time: Dict[str, float] = {}

    def notify_critical_incident(self, device_id: str, worker_id: str, location: str, risk_ratio: float, details: str, attachment_path: Optional[str] = None):
        """
        Ponto de entrada publico. Verifica rate limit e despacha as threads se necessario.
        """
        now = time.time()
        last_time = self._last_alert_time.get(device_id, 0.0)
        
        if (now - last_time) < self.cooldown_seconds:
            log.debug(f"Notificacao ignorada para {device_id} (em cooldown).")
            return
            
        self._last_alert_time[device_id] = now
        
        subject = f"[CRITICO] Risco de Explosao ({risk_ratio:.1f}%) - {worker_id}"
        body = (
            f"ALERTA MAXIMO DE SEGURANCA\n"
            f"===================================\n"
            f"Equipamento: {device_id}\n"
            f"Trabalhador: {worker_id}\n"
            f"Localizacao: {location}\n"
            f"Risco LEL:   {risk_ratio:.1f}%\n"
            f"Detalhes:    {details}\n\n"
            f"O laudo LaTeX correspondente foi gerado no servidor e esta em anexo.\n"
            f"Inicie protocolo de evacuacao imediatamente."
        )
        
        # Dispara SMTP em background
        t_smtp = threading.Thread(target=self._send_email, args=(subject, body, attachment_path), daemon=True)
        t_smtp.start()
        
        # Dispara Webhook em background
        if self.webhook_url:
            payload = {
                "alert_level": "CRITICAL",
                "device_id": device_id,
                "worker_id": worker_id,
                "location": location,
                "risk_ratio": risk_ratio,
                "details": details,
                "timestamp": time.time()
            }
            t_web = threading.Thread(target=self._send_webhook, args=(payload,), daemon=True)
            t_web.start()

    def _send_email(self, subject: str, body: str, attachment_path: Optional[str] = None):
        log.info("Tentando enviar e-mail de emergencia...")
        
        if not self.smtp_user or not self.smtp_pass:
            log.warning("Credenciais SMTP ausentes em config/secrets.py! O e-mail nao sera enviado na pratica.")
            # Escreve num arquivo local para provar que a logica rodou
            import os
            os.makedirs("reports/emails", exist_ok=True)
            with open(f"reports/emails/mock_email_{time.time()}.eml", "w") as f:
                f.write(f"To: {self.dest_email}\nSubject: {subject}\n\n{body}")
                if attachment_path:
                    f.write(f"\n[Anexo]: {attachment_path}")
            return
            
        msg = EmailMessage()
        msg.set_content(body)
        msg['Subject'] = subject
        msg['From'] = self.smtp_user
        msg['To'] = self.dest_email
        
        if attachment_path:
            import os
            if os.path.exists(attachment_path):
                import mimetypes
                ctype, encoding = mimetypes.guess_type(attachment_path)
                if ctype is None or encoding is not None:
                    ctype = 'application/octet-stream'
                maintype, subtype = ctype.split('/', 1)
                
                with open(attachment_path, 'rb') as f:
                    msg.add_attachment(
                        f.read(),
                        maintype=maintype,
                        subtype=subtype,
                        filename=os.path.basename(attachment_path)
                    )
        
        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls() # Fundamental para o Gmail
                server.login(self.smtp_user, self.smtp_pass)
                server.send_message(msg)
            log.info(f"E-mail de emergencia ENVIADO COM SUCESSO para {self.dest_email}")
        except Exception as e:
            log.error(f"Falha ao enviar e-mail SMTP: {e}")
            
    def _send_webhook(self, payload: dict):
        log.info(f"Enviando Webhook para {self.webhook_url}...")
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=5.0)
            resp.raise_for_status()
            log.info(f"Webhook enviado com sucesso (HTTP {resp.status_code}).")
        except Exception as e:
            log.error(f"Falha ao enviar webhook: {e}")
