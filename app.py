import os, io, time, uuid, requests
from functools import wraps
from flask import Flask, request, jsonify, send_file, session, send_from_directory
import pg8000.dbapi
from urllib.parse import urlparse
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import FreeText
from pypdf.generic import RectangleObject
from vercel_blob import put

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = os.environ.get("SECRET_KEY", "fallback-secret-key-2026")
DATABASE_URL = os.environ.get("POSTGRES_URL", "")

def get_db():
    url = urlparse(DATABASE_URL)
    return pg8000.dbapi.connect(
        user=url.username,
        password=url.password,
        host=url.hostname,
        port=url.port or 5432,
        database=url.path[1:] if url.path else "postgres",
        ssl_context=True
    )

def init_db():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS books (
            id TEXT PRIMARY KEY, title TEXT, author TEXT, subject TEXT,
            file_url TEXT, size INTEGER, pages INTEGER DEFAULT 0, uploaded INTEGER)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS student_keys (
            key TEXT PRIMARY KEY, name TEXT, phone TEXT, active INTEGER DEFAULT 1)""")
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print("DB Init Error:", e)

init_db()

def student_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not session.get("student"):
            return jsonify({"error": "سجل الدخول أولاً"}), 401
        return f(*a, **kw)
    return w

@app.post("/api/login")
def login():
    key = (request.json.get("key") or "").strip()
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT name, phone FROM student_keys WHERE key=%s AND active=1", (key,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            session["student"] = {"key": key, "name": row[0], "phone": row[1]}
            return jsonify({"ok": True, "name": row[0]})
    except Exception as e:
        return jsonify({"error": f"DB Error: {str(e)}"}), 500
    return jsonify({"error": "مفتاح غير صالح"}), 401

@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})

@app.get("/api/books")
@student_required
def books():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, title, author, subject, size, pages, uploaded FROM books ORDER BY uploaded DESC")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify([{
            "id": r[0], "title": r[1], "author": r[2], "subject": r[3], 
            "size": r[4], "pages": r[5], "uploaded": r[6]
        } for r in rows])
    except Exception as e:
        return jsonify({"error": f"DB Error: {str(e)}"}), 500

@app.get("/api/book/<bid>/pdf")
@student_required
def get_pdf(bid):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT title, file_url FROM books WHERE id=%s", (bid,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        
        if not row: return jsonify({"error": "غير موجود"}), 404
        title, file_url = row
        
        r = requests.get(file_url)
        if r.status_code != 200: return jsonify({"error": "فشل تحميل الملف"}), 500
        
        s = session["student"]
        wm = f"{s['name']} - {s['phone']} - KodNaqi Library"
        
        reader = PdfReader(io.BytesIO(r.content))
        writer = PdfWriter()
        writer.append(reader)
        
        for i, page in enumerate(reader.pages):
            w, h = float(page.mediabox.width), float(page.mediabox.height)
            for (x, y) in [(w*0.15, h*0.45), (w*0.15, h*0.75)]:
                ann = FreeText(
                    rect=RectangleObject([x, y, x+w*0.6, y+24]), text=wm,
                    font="Helvetica", font_size="7pt", font_color="999999",
                    border_color=None, background_color=None
                )
                writer.add_annotation(page_number=i, annotation=ann)
                
        buf = io.BytesIO()
        writer.write(buf)
        buf.seek(0)
        return send_file(buf, mimetype="application/pdf", as_attachment=False, download_name=f"{title}.pdf")
    except Exception as e:
        return jsonify({"error": f"Error: {str(e)}"}), 500

# ---------------- إدارة الأدمن (لإضافة المفاتيح والكتب) ----------------
@app.post("/api/admin/login")
def admin_login():
    # نسخة مبسطة لتسجيل دخول الأدمن (يمكنك تعديلها لاحقاً لتكون أكثر أماناً)
    if request.json.get("password") == os.environ.get("SECRET_KEY", ""):
        session["admin"] = True
        return jsonify({"ok": True})
    return jsonify({"error": "كلمة سر خاطئة"}), 401

@app.post("/api/admin/keys")
def add_key():
    if not session.get("admin"): return jsonify({"error": "أدمن فقط"}), 403
    d = request.json
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO student_keys (key, name, phone, active) VALUES (%s, %s, %s, 1) ON CONFLICT (key) DO UPDATE SET name=EXCLUDED.name, phone=EXCLUDED.phone",
                    (d["key"], d["name"], d.get("phone", "")))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.post("/api/admin/upload")
def upload():
    if not session.get("admin"): return jsonify({"error": "أدمن فقط"}), 403
    f = request.files.get("pdf")
    if not f: return jsonify({"error": "لم يصل الملف"}), 400
    bid = uuid.uuid4().hex[:12]
    try:
        blob = put(f"books/{bid}.pdf", f.read(), {"access": "public"})
        file_url = blob["url"]
        size = len(f.read())
        pages = 0
        try: pages = len(PdfReader(io.BytesIO(f.read())).pages)
        except: pass
        
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO books VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (bid, request.form.get("title","كتاب"), request.form.get("author",""),
                     request.form.get("subject",""), file_url, size, pages, int(time.time())))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"ok": True, "id": bid})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.get("/")
def home():
    return send_from_directory("static", "index.html")
