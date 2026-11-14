import os, time, sqlite3, secrets, hashlib
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "library.db")
SECRET_FILE = os.path.join(BASE, ".kq_secret")

LOCK_ATTEMPTS = 5
LOCK_WINDOW   = 15 * 60
RESET_TTL     = 30 * 60
SESSION_TIMEOUT = 30 * 60


def get_secret():
    if os.path.exists(SECRET_FILE):
        return open(SECRET_FILE, "rb").read()
    s = secrets.token_bytes(64)
    with open(SECRET_FILE, "wb") as f:
        f.write(s)
    os.chmod(SECRET_FILE, 0o600)
    return s


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def init_security_tables():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS admin(
            id INTEGER PRIMARY KEY CHECK (id=1),
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            phone TEXT,
            twofa_enabled INTEGER DEFAULT 0,
            created INTEGER)""")
        con.execute("""CREATE TABLE IF NOT EXISTS recovery_codes(
            code_hash TEXT PRIMARY KEY, used INTEGER DEFAULT 0, created INTEGER)""")
        con.execute("""CREATE TABLE IF NOT EXISTS login_attempts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT, ip TEXT, success INTEGER, ts INTEGER)""")
        con.execute("""CREATE TABLE IF NOT EXISTS audit_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT, detail TEXT, ip TEXT, ts INTEGER)""")


def has_admin():
    with db() as con:
        return con.execute("SELECT 1 FROM admin WHERE id=1").fetchone() is not None


def get_admin():
    with db() as con:
        row = con.execute("SELECT * FROM admin WHERE id=1").fetchone()
    return dict(row) if row else None


def create_admin(email, password, phone=""):
    if len(password) < 8:
        raise ValueError("كلمة السر قصيرة — 8 أحرف على الأقل")
    pw = generate_password_hash(password, method="pbkdf2:sha256:260000")
    with db() as con:
        con.execute("INSERT INTO admin(id,email,password_hash,phone,twofa_enabled,created) VALUES(1,?,?,?,0,?)",
                    (email.lower().strip(), pw, phone, int(time.time())))
    return generate_recovery_codes()


def verify_password(email, password):
    a = get_admin()
    if not a:
        return False
    if a["email"] != (email or "").lower().strip():
        return False
    return check_password_hash(a["password_hash"], password or "")


def change_password(email, new_password, current_password=None):
    if current_password is not None and not verify_password(email, current_password):
        raise ValueError("كلمة السر الحالية خاطئة")
    if len(new_password) < 8:
        raise ValueError("كلمة السر الجديدة قصيرة")
    with db() as con:
        con.execute("UPDATE admin SET password_hash=? WHERE id=1",
                    (generate_password_hash(new_password, method="pbkdf2:sha256:260000"),))


def set_2fa(enabled):
    with db() as con:
        con.execute("UPDATE admin SET twofa_enabled=? WHERE id=1", (1 if enabled else 0,))


def generate_recovery_codes():
    with db() as con:
        con.execute("DELETE FROM recovery_codes")
    codes = []
    now = int(time.time())
    with db() as con:
        for _ in range(10):
            code = secrets.token_hex(4).upper()
            codes.append(code)
            con.execute("INSERT INTO recovery_codes(code_hash,used,created) VALUES(?,0,?)",
                        (hashlib.sha256(code.encode()).hexdigest(), now))
    return codes


def use_recovery_code(code):
    h = hashlib.sha256((code or "").strip().upper().encode()).hexdigest()
    with db() as con:
        row = con.execute("SELECT used FROM recovery_codes WHERE code_hash=?", (h,)).fetchone()
        if not row or row["used"]:
            return False
        con.execute("UPDATE recovery_codes SET used=1 WHERE code_hash=?", (h,))
    return True


def remaining_recovery_codes():
    with db() as con:
        return con.execute("SELECT COUNT(*) c FROM recovery_codes WHERE used=0").fetchone()["c"]


def is_locked(email, ip):
    now = int(time.time())
    with db() as con:
        fails = con.execute(
            "SELECT COUNT(*) c FROM login_attempts WHERE (email=? OR ip=?) AND success=0 AND ts>?",
            ((email or "").lower().strip(), ip or "", now - LOCK_WINDOW)).fetchone()["c"]
    return fails >= LOCK_ATTEMPTS


def record_attempt(email, ip, success):
    now = int(time.time())
    with db() as con:
        con.execute("INSERT INTO login_attempts(email,ip,success,ts) VALUES(?,?,?,?)",
                    ((email or "").lower().strip(), ip or "", 1 if success else 0, now))
        con.execute("DELETE FROM login_attempts WHERE ts < ?", (now - 86400,))


def make_reset_token(email):
    return URLSafeTimedSerializer(get_secret()).dumps({"e": email}, salt="pwreset")


def validate_reset_token(token):
    try:
        data = URLSafeTimedSerializer(get_secret()).loads(token, salt="pwreset", max_age=RESET_TTL)
        return data["e"]
    except (BadSignature, SignatureExpired):
        return None


def make_otp():
    return f"{secrets.randbelow(1_000_000):06d}"


def audit(action, detail="", ip=""):
    with db() as con:
        con.execute("INSERT INTO audit_log(action,detail,ip,ts) VALUES(?,?,?,?)",
                    (action, str(detail)[:200], ip or "", int(time.time())))
