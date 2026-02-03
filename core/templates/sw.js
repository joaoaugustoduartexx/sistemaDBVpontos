const CACHE_NAME = 'dbv-cache-v1';
const urlsToCache = [
  '/',
  '/static/css/bootstrap.min.css', 
  // Adicione outros arquivos estáticos cruciais aqui
];

// Instalação: Cache inicial
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        return cache.addAll(urlsToCache);
      })
  );
});

// Fetch: Tenta rede primeiro, se falhar (offline), tenta cache
self.addEventListener('fetch', event => {
  event.respondWith(
    fetch(event.request).catch(() => {
      return caches.match(event.request);
    })
  );
});