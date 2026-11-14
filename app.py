import os, json, sqlite3, io, time, uuid
from functools import wraps
from flask import Flask, request, jsonify, send_file, session, send_from_directory

from security import (
    init_security_tables, get_secret, has_admin, get_admin, create_admin,
    verify_password, change_password, set_2fa,
    generate_recovery_codes, use_recovery_code, remaining_recovery_codes,
    is_locked, record_attempt, make_reset_token, validate_reset_token,
    make_otp, audit, SESSION_TIMEOUT,
)
import mailer

BASE       = os.path.dirname(os.path.abspath(__file__))
DB         = os.path.join(BASE, "library.db")
BOOKS      = os.path.join(BASE, "books")
KEYS_FILE  = os.path.join(BASE, "keys.json")

os.makedirs(BOOKS, exist_ok=True)

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = get_secret()
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # حد أقصى 200 ميجا للكتاب

init_security_tables()


# ---------------- قاعدة بيانات ----------------
def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


with db() as con:
    con.execute("""CREATE TABLE IF NOT EXISTS books(
        id TEXT PRIMARY KEY, title TEXT, author TEXT, subject TEXT,
        filename TEXT, size INTEGER, pages INTEGER DEFAULT 0,
        uploaded INTEGER)""")


# ---------------- مفاتيح الطلاب ----------------
def load_keys():
    if not os.path.exists(KEYS_FILE):
        json.dump({}, open(KEYS_FILE, "w"))
    return json.load(open(KEYS_FILE))


def save_keys(k):
    json.dump(k, open(KEYS_FILE, "w"), ensure_ascii=False, indent=2)


# ---------------- أدوات PDF ----------------
def count_pages(path):
    try:
        import fitz
        d = fitz.open(path)
        n = d.page_count
        d.close()
        return n
    except Exception:
        from pypdf import PdfReader
        return len(PdfReader(path).pages)


def watermark_pdf(path, text):
    try:
        import fitz
        doc = fitz.open(path)
        for page in doc:
            r = page.rect
            for y in range(80, int(r.height), 220):
                for x in range(40, int(r.width), 260):
                    page.insert_text((x, y), text, fontsize=7,
                                     color=(0.75, 0.75, 0.75), rotate=45)
        buf = io.BytesIO()
        doc.save(buf, garbage=3, deflate=True)
        doc.close()
        buf.seek(0)
        return buf
    except Exception:
        pass

    from pypdf import PdfReader, PdfWriter
    from pypdf.annotations import FreeText
    from pypdf.generic import RectangleObject
    reader = PdfReader(path)
    writer = PdfWriter()
    writer.append(reader)
    for i, page in enumerate(reader.pages):
        w = float(page.mediabox.width)
        h = float(page.mediabox.height)
        for (x, y) in [(w*0.15, h*0.45), (w*0.15, h*0.75), (w*0.3, h*0.6)]:
            ann = FreeText(
                rect=RectangleObject([x, y, x + w*0.6, y + 24]),
                text=text, font="Helvetica", font_size="7pt",
                font_color="999999", border_color=None, background_color=None)
            writer.add_annotation(page_number=i, annotation=ann)
    buf = io.BytesIO()
    writer.write(buf)
    buf.seek(0)
    return buf


# ---------------- صلاحيات ----------------
def student_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not session.get("student"):
            return jsonify({"error": "سجل الدخول أولاً"}), 401
        return f(*a, **kw)
    return w


def admin_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not session.get("admin"):
            return jsonify({"error": "auth required", "auth": True}), 401
        if time.time() - session.get("admin_last", 0) > SESSION_TIMEOUT:
            session.clear()
            return jsonify({"error": "session expired", "auth": True, "timeout": True}), 401
        session["admin_last"] = time.time()
        return f(*a, **kw)
    return w


# ================ الطلاب ================
@app.post("/api/login")
def login():
    key = (request.json.get("key") or "").strip()
    keys = load_keys()
    if key in keys and keys[key].get("active", True):
        session["student"] = {"key": key, "name": keys[key]["name"],
                              "phone": keys[key].get("phone", "")}
        return jsonify({"ok": True, "name": keys[key]["name"]})
    return jsonify({"error": "مفتاح غير صالح"}), 401


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/books")
@student_required
def books():
    with db() as con:
        rows = con.execute("SELECT id,title,author,subject,size,pages,uploaded FROM books ORDER BY uploaded DESC").fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/book/<bid>/pdf")
@student_required
def get_pdf(bid):
    with db() as con:
        row = con.execute("SELECT * FROM books WHERE id=?", (bid,)).fetchone()
    if not row:
        return jsonify({"error": "غير موجود"}), 404
    s = session["student"]
    wm = f"{s['name']} - {s['phone']} - KodNaqi Library"
    data = watermark_pdf(os.path.join(BOOKS, row["filename"]), wm)
    return send_file(data, mimetype="application/pdf",
                     download_name=row["title"] + ".pdf")


# ================ حالة الإعداد ================
@app.get("/api/admin/status")
def admin_status():
    return jsonify({
        "setup_needed": not has_admin(),
        "email_configured": mailer.is_configured(),
        "session_active": bool(session.get("admin")),
    })


# ================ إعداد أول مرة ================
@app.post("/api/admin/setup")
def admin_setup():
    if has_admin():
        return jsonify({"error": "تم الإعداد مسبقاً"}), 400
    d = request.json or {}
    email = (d.get("email") or "").strip().lower()
    pw    = d.get("password") or ""
    if "@" not in email:
        return jsonify({"error": "بريد غير صالح"}), 400
    if len(pw) < 8:
        return jsonify({"error": "كلمة السر قصيرة (8+)"}), 400
    try:
        codes = create_admin(email, pw, d.get("phone", ""))
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    audit("admin_setup", email, request.remote_addr)
    session.clear()
    session["admin"]       = True
    session["admin_email"] = email
    session["admin_last"]  = time.time()
    return jsonify({"ok": True, "recovery_codes": codes})


# ================ دخول ================
@app.post("/api/admin/login")
def admin_login():
    d = request.json or {}
    email = (d.get("email") or "").strip().lower()
    pw    = d.get("password") or ""
    ip    = request.remote_addr or ""
    if is_locked(email, ip):
        return jsonify({"error": "محظور مؤقتاً — حاول بعد 30 دقيقة"}), 429
    if not verify_password(email, pw):
        record_attempt(email, ip, False)
        audit("login_fail", email, ip)
        return jsonify({"error": "البريد أو كلمة السر خاطئة"}), 401
    record_attempt(email, ip, True)
    a = get_admin()
    if a.get("twofa_enabled") and mailer.is_configured():
        otp = make_otp()
        session["pending_otp"] = {"code": otp, "email": email, "exp": time.time() + 300}
        ok, msg = mailer.send_email(email, "رمز دخول KodNaqi Library",
            f"<p>رمز الدخول: <b style='font-size:28px;letter-spacing:4px'>{otp}</b></p>"
            f"<p style='color:#888'>صالح 5 دقائق.</p>")
        audit("login_2fa_sent", "ok" if ok else msg, ip)
        return jsonify({"ok": True, "otp_required": True})
    session.clear()
    session["admin"]       = True
    session["admin_email"] = email
    session["admin_last"]  = time.time()
    audit("login_ok", email, ip)
    return jsonify({"ok": True})


@app.post("/api/admin/verify_otp")
def admin_verify_otp():
    p = session.get("pending_otp")
    if not p or time.time() > p["exp"]:
        return jsonify({"error": "انتهت صلاحية الرمز"}), 400
    if (request.json or {}).get("code", "").strip() != p["code"]:
        return jsonify({"error": "الرمز خاطئ"}), 401
    session.clear()
    session["admin"]       = True
    session["admin_email"] = p["email"]
    session["admin_last"]  = time.time()
    audit("login_2fa_ok", p["email"], request.remote_addr)
    return jsonify({"ok": True})


@app.post("/api/admin/logout")
def admin_logout():
    session.clear()
    return jsonify({"ok": True})


# ================ استرجاع كلمة السر ================
@app.post("/api/admin/forgot")
def admin_forgot():
    d = request.json or {}
    email = (d.get("email") or "").strip().lower()
    a = get_admin()
    if not a or a["email"] != email:
        return jsonify({"ok": True})
    if not mailer.is_configured():
        return jsonify({"error": "no_email",
                        "hint": "البريد غير مُعدّ — استخدم رمز استرداد بدلاً منه"}), 400
    token = make_reset_token(email)
    link = f"{request.host_url}static/admin.html?reset={token}"
    ok, msg = mailer.send_email(email, "استعادة كلمة السر — KodNaqi Library",
        f"<p>اضغط الرابط لإعادة تعيين كلمة السر (صالح 30 دقيقة):</p>"
        f"<p><a href='{link}'>{link}</a></p>")
    audit("forgot_requested", email, request.remote_addr)
    return jsonify({"ok": True, "sent": ok, "msg": msg})


@app.post("/api/admin/reset_password")
def admin_reset_password():
    d = request.json or {}
    pw = d.get("password") or ""
    if len(pw) < 8:
        return jsonify({"error": "كلمة السر قصيرة"}), 400
    token = d.get("token")
    code  = d.get("recovery_code")
    if token:
        email = validate_reset_token(token)
        if not email:
            return jsonify({"error": "رابط غير صالح أو منتهي"}), 400
        change_password(email, pw)
        audit("password_reset_via_email", email, request.remote_addr)
        return jsonify({"ok": True})
    if code:
        if not use_recovery_code(code):
            return jsonify({"error": "رمز استرداد خاطئ أو مستخدم"}), 400
        a = get_admin()
        change_password(a["email"], pw)
        audit("password_reset_via_recovery", a["email"], request.remote_addr)
        return jsonify({"ok": True, "remaining": remaining_recovery_codes()})
    return jsonify({"error": "بيانات ناقصة"}), 400


# ================ إعدادات الحساب ================
@app.post("/api/admin/change_password")
@admin_required
def admin_change_password():
    d = request.json or {}
    try:
        change_password(session["admin_email"], d.get("new_password", ""),
                        d.get("current_password", ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    audit("password_changed", session["admin_email"], request.remote_addr)
    return jsonify({"ok": True})


@app.post("/api/admin/regenerate_recovery")
@admin_required
def admin_regen():
    d = request.json or {}
    if not verify_password(session["admin_email"], d.get("password", "")):
        return jsonify({"error": "كلمة السر خاطئة"}), 401
    codes = generate_recovery_codes()
    audit("recovery_regen", session["admin_email"], request.remote_addr)
    return jsonify({"ok": True, "codes": codes})


@app.get("/api/admin/recovery_info")
@admin_required
def admin_recovery_info():
    return jsonify({"remaining": remaining_recovery_codes()})


@app.post("/api/admin/toggle_2fa")
@admin_required
def admin_toggle_2fa():
    d = request.json or {}
    if not verify_password(session["admin_email"], d.get("password", "")):
        return jsonify({"error": "كلمة السر خاطئة"}), 401
    enable = bool(d.get("enable"))
    if enable and not mailer.is_configured():
        return jsonify({"error": "no_email"}), 400
    set_2fa(enable)
    audit("2fa_toggled", str(enable), request.remote_addr)
    return jsonify({"ok": True, "twofa_enabled": enable})


@app.post("/api/admin/email_config")
@admin_required
def admin_email_config():
    d = request.json or {}
    if not verify_password(session["admin_email"], d.get("password", "")):
        return jsonify({"error": "كلمة السر خاطئة"}), 401
    if not d.get("smtp_user") or not d.get("smtp_pass"):
        return jsonify({"error": "بيانات ناقصة"}), 400
    cfg = {
        "smtp_host": d.get("smtp_host", "smtp.gmail.com"),
        "smtp_port": int(d.get("smtp_port", 465)),
        "smtp_user": d["smtp_user"],
        "smtp_pass": d["smtp_pass"],
        "from_name": d.get("from_name", "KodNaqi Library"),
    }
    mailer.save_config(cfg)
    ok, msg = mailer.send_email(session["admin_email"],
        "اختبار إعدادات البريد — KodNaqi Library",
        "<p>إعدادات البريد تعمل بشكل صحيح.</p>")
    audit("email_configured", "ok" if ok else msg, request.remote_addr)
    return jsonify({"ok": ok, "test_msg": msg})


@app.get("/api/admin/audit")
@admin_required
def admin_audit():
    with db() as con:
        rows = con.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 100").fetchall()
    return jsonify([dict(r) for r in rows])


# ================ إدارة الكتب ================
@app.post("/api/admin/upload")
@admin_required
def upload():
    print(f"[UPLOAD] request received | files={list(request.files.keys())} | form={list(request.form.keys())}")
    if "pdf" not in request.files:
        print("[UPLOAD] ERROR: pdf key missing")
        return jsonify({"error": "لم يصل الملف (pdf missing) — أعد المحاولة"}), 400
    f = request.files["pdf"]
    if not f or not f.filename:
        print("[UPLOAD] ERROR: empty filename")
        return jsonify({"error": "لم يتم اختيار ملف"}), 400
    if not f.filename.lower().endswith(".pdf"):
        print(f"[UPLOAD] ERROR: not pdf -> {f.filename}")
        return jsonify({"error": "الملف ليس PDF: " + f.filename}), 400
    bid = uuid.uuid4().hex[:12]
    fname = bid + ".pdf"
    filepath = os.path.join(BOOKS, fname)
    try:
        f.save(filepath)
    except Exception as e:
        print(f"[UPLOAD] ERROR save: {e}")
        return jsonify({"error": "فشل حفظ الملف: " + str(e)}), 500
    size = os.path.getsize(filepath)
    if size == 0:
        try: os.remove(filepath)
        except OSError: pass
        print("[UPLOAD] ERROR: 0 bytes")
        return jsonify({"error": "الملف فارغ (0 بايت)"}), 400
    pages = 0
    try:
        pages = count_pages(filepath)
    except Exception as e:
        print(f"[UPLOAD] count_pages warning: {e}")
    title = request.form.get("title") or f.filename
    with db() as con:
        con.execute("INSERT INTO books VALUES(?,?,?,?,?,?,?,?)",
            (bid, title, request.form.get("author", ""),
             request.form.get("subject", "عام"),
             fname, size, pages, int(time.time())))
    audit("book_uploaded", title, request.remote_addr)
    print(f"[UPLOAD OK] {title} | {size} bytes | {pages} pages | id={bid}")
    return jsonify({"ok": True, "id": bid, "size": size, "pages": pages})


@app.get("/api/admin/books")
@admin_required
def admin_books():
    with db() as con:
        rows = con.execute("SELECT * FROM books ORDER BY uploaded DESC").fetchall()
    return jsonify([dict(r) for r in rows])


@app.delete("/api/admin/book/<bid>")
@admin_required
def delete_book(bid):
    with db() as con:
        row = con.execute("SELECT filename FROM books WHERE id=?", (bid,)).fetchone()
        if row:
            con.execute("DELETE FROM books WHERE id=?", (bid,))
            try:
                os.remove(os.path.join(BOOKS, row["filename"]))
            except OSError:
                pass
    audit("book_deleted", bid, request.remote_addr)
    return jsonify({"ok": True})


# ================ إدارة المفاتيح ================
@app.post("/api/admin/keys")
@admin_required
def add_key():
    d = request.json
    keys = load_keys()
    keys[d["key"]] = {"name": d["name"], "phone": d.get("phone", ""), "active": True}
    save_keys(keys)
    return jsonify({"ok": True})


@app.get("/api/admin/keys")
@admin_required
def list_keys():
    return jsonify(load_keys())


@app.post("/api/admin/toggle_key")
@admin_required
def toggle_key():
    keys = load_keys()
    k = request.json["key"]
    keys[k]["active"] = not keys[k].get("active", True)
    save_keys(keys)
    return jsonify({"ok": True})


@app.get("/")
def home():
    return send_from_directory("static", "index.html")


if __name__ == "__main__":
    print("==================================================")
    print("🚀 KodNaqi Library Server Started (Waitress)")
    print("🌐 Local URL:   http://127.0.0.1:8000")
    print("📱 Network URL: http://10.53.11.108:8000")
    print("==================================================")
    from waitress import serve
    serve(app, host="0.0.0.0", port=8000, threads=4)