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

// Escuta o evento de Push Notification vindo do servidor
self.addEventListener('push', function(event) {
    let data = { head: "Nova Notificação", body: "Você tem uma nova mensagem." };
    
    // Tenta ler os dados que o Django enviou
    if (event.data) {
        data = JSON.parse(event.data.text());
    }

    // Configura o visual da caixinha que vai aparecer no Windows/Celular
    const options = {
        body: data.body,
        icon: '/static/icons/icon-192.png', // O ícone do seu DBV
        badge: '/static/icons/icon-192.png',
        vibrate: [200, 100, 200] // Faz o celular vibrar
    };

    // Pede para o navegador exibir na tela
    event.waitUntil(
        self.registration.showNotification(data.head, options)
    );
});