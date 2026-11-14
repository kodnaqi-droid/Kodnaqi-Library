import os, json, smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE, "email_config.json")


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return None
    try:
        return json.load(open(CONFIG_FILE))
    except Exception:
        return None


def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.chmod(CONFIG_FILE, 0o600)


def is_configured():
    c = load_config()
    return bool(c and c.get("smtp_host") and c.get("smtp_user") and c.get("smtp_pass"))


def send_email(to, subject, body_html):
    cfg = load_config()
    if not cfg:
        return False, "لم يتم إعداد البريد بعد"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{cfg.get('from_name','KodNaqi Library')} <{cfg['smtp_user']}>"
    msg["To"]      = to
    msg.attach(MIMEText(body_html, "html", "utf-8"))
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["smtp_host"], int(cfg.get("smtp_port", 465)), context=ctx, timeout=15) as s:
            s.login(cfg["smtp_user"], cfg["smtp_pass"])
            s.send_message(msg)
        return True, "تم الإرسال"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
