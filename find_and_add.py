import os, uuid, time, sqlite3, shutil, sys
from pypdf import PdfReader

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "library.db")
BOOKS = os.path.join(BASE, "books")

os.system('clear')
print("========================================")
print("🔍 جاري البحث عن ملفات PDF في هاتفك...")
print("========================================")

pdf_files = []
# البحث في مجلد التخزين الرئيسي مع تجاهل مجلدات النظام لتسريع البحث
for root, dirs, files in os.walk(os.path.expanduser("~/storage/shared")):
    dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('Android', 'data', 'obb')]
    for f in files:
        if f.lower().endswith('.pdf'):
            pdf_files.append(os.path.join(root, f))

if not pdf_files:
    print("❌ لم يتم العثور على أي ملف PDF في هاتفك.")
    print("تأكد من أنك قمت بتحميل الكتب على الهاتف أولاً.")
    sys.exit()

print(f"✅ تم العثور على {len(pdf_files)} ملف PDF:\n")
for i, path in enumerate(pdf_files):
    print(f"[{i+1}] {os.path.basename(path)}")

print("\n----------------------------------------")
try:
    choice = int(input("👉 اكتب رقم الكتاب الذي تريد إضافته للمكتبة: ")) - 1
    if choice < 0 or choice >= len(pdf_files):
        raise ValueError
except ValueError:
    print("❌ اختيار غير صحيح.")
    sys.exit()

selected_path = pdf_files[choice]

print("\n========================================")
title = input("📝 عنوان الكتاب: ").strip() or os.path.basename(selected_path)
author = input("✍️  المؤلف: ").strip()
subject = input("🧪 التخصص: ").strip()

bid = uuid.uuid4().hex[:12]
fname = bid + ".pdf"
dest = os.path.join(BOOKS, fname)

print("\n⏳ جاري نسخ الكتاب وإضافته لقاعدة البيانات...")
try:
    shutil.copy2(selected_path, dest)
    pages = len(PdfReader(dest).pages)
    size = os.path.getsize(dest)
except Exception as e:
    print(f"❌ حدث خطأ أثناء النسخ: {e}")
    if os.path.exists(dest): os.remove(dest)
    sys.exit()

with sqlite3.connect(DB) as con:
    con.execute("INSERT INTO books VALUES(?,?,?,?,?,?,?,?)",
        (bid, title, author, subject, fname, size, pages, int(time.time())))

print("\n✅ تمت إضافة الكتاب بنجاح!")
print(f"📖 العنوان: {title}")
print(f"📄 الصفحات: {pages} صفحة")
print(f"⚖️  الحجم: {round(size/1048576, 2)} ميجابايت")
print("========================================")
print("🎉 يمكنك الآن فتح المتصفح وسيظهر الكتاب للطلاب!")
