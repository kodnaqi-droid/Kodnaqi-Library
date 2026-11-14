const T = {
  ar: {
    key_ph: "مفتاح الترخيص", enter: "دخول", bad_key: "مفتاح غير صالح",
    library: "📚 المكتبة", logout: "خروج", read: "قراءة",
    offline: "✅ أوفلاين", online: "☁️ يتطلب نت", empty: "لا توجد كتب بعد",
    loading: "📚 جاري التحميل...", admin: "لوحة الأدمن", pages: "صفحة",
    back: "⬅ رجوع", retry: "إعادة المحاولة", error: "حدث خطأ أثناء تحميل الكتب. تأكد من أن السيرفر يعمل."
  },
  en: {
    key_ph: "License key", enter: "Login", bad_key: "Invalid key",
    library: "📚 Library", logout: "Logout", read: "Read",
    offline: "✅ Offline", online: "☁️ Online", empty: "No books yet",
    loading: "📚 Loading...", admin: "Admin panel", pages: "pages",
    back: "⬅ Back", retry: "Retry", error: "Error loading books. Check if the server is running."
  }
};
let lang = localStorage.getItem('kq-lang') || 'ar';
const t = k => T[lang][k] || k;

function toggleTheme() {
  const th = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = th;
  localStorage.setItem('kq-theme', th);
  document.getElementById('themeBtn').textContent = th === 'dark' ? '☀️' : '🌙';
}
function toggleLang() {
  lang = lang === 'ar' ? 'en' : 'ar';
  localStorage.setItem('kq-lang', lang);
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
  document.getElementById('langBtn').textContent = lang === 'ar' ? 'EN' : 'ع';
  sessionStorage.getItem('view') === 'lib' ? showLibrary() : showLogin();
}

if ('serviceWorker' in navigator) navigator.serviceWorker.register('/static/sw.js');

async function api(url, opts = {}) {
  opts.credentials = 'same-origin';
  if (opts.json) { opts.headers = {'Content-Type':'application/json'}; opts.body = JSON.stringify(opts.json); delete opts.json; }
  const r = await fetch(url, opts);
  if (r.status === 401 && !url.includes('login')) { showLogin(); throw new Error('401'); }
  const json = await r.json();
  if (!r.ok) throw new Error(json.error || 'Server error');
  return json;
}

function showLogin() {
  sessionStorage.setItem('view','login');
  document.getElementById('root').innerHTML = `
    <h1>📚 KodNaqi Library</h1>
    <div class="card">
      <input id="key" placeholder="${t('key_ph')}" autocomplete="off">
      <button onclick="doLogin()">${t('enter')}</button>
      <div id="err" class="err"></div>
    </div>
    <button class="off" onclick="location.href='/static/admin.html'">${t('admin')}</button>`;
}

async function doLogin() {
  try {
    const r = await api('/api/login', {method:'POST', json:{key: document.getElementById('key').value}});
    if (r.ok) showLibrary(); else document.getElementById('err').textContent = r.error || t('bad_key');
  } catch(e) {
    document.getElementById('err').textContent = e.message;
  }
}

async function showLibrary() {
  sessionStorage.setItem('view','lib');
  document.getElementById('root').innerHTML = `<h1>${t('loading')}</h1>`;
  
  try {
    const books = await api('/api/books');
    const cached = new Set();
    for (const cname of await caches.keys()) {
      const cs = await caches.open(cname);
      for (const req of await cs.keys()) {
        const m = req.url.match(/\/api\/book\/([a-z0-9]+)\/pdf/);
        if (m) cached.add(m[1]);
      }
    }
    
    document.getElementById('root').innerHTML = `
      <div class="topbar"><h1 style="margin:0">${t('library')}</h1>
        <button style="width:auto;padding:8px 16px" onclick="api('/api/logout',{method:'POST'}).then(showLogin)">${t('logout')}</button>
      </div>
      <div id="list"></div>`;
      
    const list = document.getElementById('list');
    if (!books.length) { list.innerHTML = `<div class="card">${t('empty')}</div>`; return; }
    
    books.forEach(b => {
      const off = cached.has(b.id);
      const d = document.createElement('div');
      d.className = 'card book';
      d.innerHTML = `
        <div>
          <b>${b.title}</b><br>
          <small>${b.author||''}</small> <span class="subj">${b.subject}</span><br>
          <small>${(b.size/1048576).toFixed(1)} MB • ${b.pages||'?'} ${t('pages')}</small>
        </div>
        <div style="text-align:${lang==='ar'?'left':'right'}">
          <span class="pill ${off?'':'no'}">${off?t('offline'):t('online')}</span><br><br>
          <button style="width:auto;padding:8px 18px" onclick="location.href='/static/viewer.html?id=${b.id}'">${t('read')}</button>
        </div>`;
      list.appendChild(d);
    });
  } catch(e) {
    // إذا حدث خطأ (السيرفر متوقف أو الجلسة انتهت)
    document.getElementById('root').innerHTML = `
      <div class="card" style="text-align:center">
        <h2 style="color:#e05c5c">⚠️ ${e.message === '401' ? '' : t('error')}</h2>
        <button onclick="showLibrary()" style="margin-top:15px">${t('retry')}</button>
        <button class="off" onclick="showLogin()" style="margin-top:10px">${t('logout')}</button>
      </div>`;
  }
}
document.getElementById('themeBtn').textContent = document.documentElement.dataset.theme === 'dark' ? '☀️' : '🌙';
document.getElementById('langBtn').textContent = lang === 'ar' ? 'EN' : 'ع';
showLogin();
