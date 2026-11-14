const SHELL = 'kodnaqi-shell-v6';
const BOOKS_CACHE = 'kodnaqi-books-v1';

self.addEventListener('install', e => {
  e.waitUntil(caches.open(SHELL).then(c => c.addAll([
    '/static/index.html', '/static/app.js', '/static/style.css',
    '/static/pdf.min.js', '/static/pdf.worker.min.js',
    '/static/fonts/cairo-400.woff2', '/static/fonts/cairo-600.woff2', '/static/fonts/cairo-700.woff2',
    '/static/fonts/poppins-400.woff2', '/static/fonts/poppins-600.woff2', '/static/fonts/poppins-700.woff2'
  ]).catch(()=>{})));
  self.skipWaiting();
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ns => Promise.all(
    ns.filter(n => n.startsWith('kodnaqi-shell') && n !== SHELL).map(n => caches.delete(n))
  )).then(() => clients.claim()));
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // 🛑 مهم جداً: لا تتدخل أبداً في طلبات POST (مثل رفع الكتب أو تسجيل الدخول)
  if (e.request.method !== 'GET') {
    return; 
  }

  // admin.html + API → network-first دائماً
  if (url.pathname === '/static/admin.html' || url.pathname.startsWith('/api/')) {
    e.respondWith((async () => {
      try { return await fetch(e.request); }
      catch { return (await caches.match(e.request)) || new Response('offline',{status:503}); }
    })());
    return;
  }

  // كتب PDF: نت أولاً ثم كاش
  if (url.pathname.match(/^\/api\/book\/[a-z0-9]+\/pdf/)) {
    e.respondWith((async () => {
      const cache = await caches.open(BOOKS_CACHE);
      try {
        const net = await fetch(e.request);
        if (net.ok) cache.put(e.request, net.clone());
        return net;
      } catch {
        const hit = await cache.match(e.request);
        if (hit) return hit;
        return new Response(JSON.stringify({error:'offline'}), {status:503});
      }
    })());
    return;
  }

  if (e.request.method === 'GET' && url.origin === location.origin) {
    e.respondWith(caches.match(e.request).then(hit => hit || fetch(e.request)));
  }
});
