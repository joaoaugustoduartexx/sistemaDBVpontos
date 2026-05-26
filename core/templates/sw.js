const CACHE_NAME = 'dbv-cache-v2'; // Mudamos para v2 para forçar a atualização

// Instalação: Cache inicial básico
self.addEventListener('install', event => {
  self.skipWaiting(); // Força o novo Service Worker a assumir o controle imediatamente
});

// Ativação: Limpa caches antigos (v1) para não ocupar memória do celular
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheName !== CACHE_NAME) {
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
});

// Fetch: O Motor de Velocidade
self.addEventListener('fetch', event => {
  const requestUrl = new URL(event.request.url);

  // ESTRATÉGIA 1: CACHE FIRST (Para estáticos, CSS, Imagens e CDNs do Bootstrap/FontAwesome)
  // O celular carrega da própria memória instantaneamente.
  if (
    requestUrl.pathname.startsWith('/static/') || 
    requestUrl.hostname.includes('cdn.jsdelivr.net') || 
    requestUrl.hostname.includes('cdnjs.cloudflare.com')
  ) {
    event.respondWith(
      caches.match(event.request).then(cachedResponse => {
        if (cachedResponse) {
          return cachedResponse; // Retorna instantâneo do celular
        }
        // Se não tem no cache, baixa da rede e salva para a próxima vez
        return fetch(event.request).then(networkResponse => {
          return caches.open(CACHE_NAME).then(cache => {
            cache.put(event.request, networkResponse.clone());
            return networkResponse;
          });
        });
      })
    );
  } 
  // ESTRATÉGIA 2: NETWORK FIRST (Para páginas HTML e API de notificações)
  // Garante que o ranking e as listas estejam sempre atualizados.
  else {
    event.respondWith(
      fetch(event.request).catch(() => {
        // Se estiver offline, tenta buscar a última versão salva na memória
        return caches.match(event.request);
      })
    );
  }
});

// Escuta o evento de Push Notification vindo do servidor
self.addEventListener('push', function(event) {
    let data = { head: "Nova Notificação", body: "Você tem um novo aviso.", url: "/notificacoes/" };
    
    // Tenta ler os dados que o Django enviou
    if (event.data) {
        data = JSON.parse(event.data.text());
    }

    const options = {
        body: data.body,
        icon: '/static/icons/icon-192.png',
        badge: '/static/icons/icon-192.png',
        vibrate: [200, 100, 200],
        data: { url: data.url } // SALVA A URL DE DESTINO AQUI
    };

    event.waitUntil(
        self.registration.showNotification(data.head, options)
    );
});

// NOVO: Ação ao CLICAR na notificação Push
self.addEventListener('notificationclick', function(event) {
    event.notification.close(); // Fecha a caixinha do aviso
    
    // Pega a URL que o Django enviou (ou vai para o mural por padrão)
    const urlToOpen = event.notification.data.url || '/notificacoes/';

    event.waitUntil(
        // Verifica se o app já está aberto em alguma aba do celular/PC
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(clientList) {
            for (let i = 0; i < clientList.length; i++) {
                let client = clientList[i];
                // Se já estiver aberto, apenas foca na tela e redireciona
                if ('focus' in client) {
                    client.navigate(urlToOpen);
                    return client.focus();
                }
            }
            // Se o app estiver fechado, abre uma nova janela na tela certa
            if (clients.openWindow) {
                return clients.openWindow(urlToOpen);
            }
        })
    );
});