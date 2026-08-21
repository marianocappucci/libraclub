// El service worker mínimo que hace falta para que el navegador ofrezca
// instalar la aplicación, y NADA MÁS.
//
// 🔴 A propósito no cachea un solo byte. El frontend se sirve desde el mismo
// proceso que la API y se reemplaza entero en cada deploy, con los assets
// versionados por hash: un caché acá no ahorraría nada y sí podría dejar a un
// usuario con el bundle de anteayer sin manera de enterarse.
//
// `fetch` está vacío pero tiene que existir: es lo que el navegador mira para
// considerar la aplicación instalable. Al no llamar a `respondWith`, cada
// pedido sigue su camino normal a la red.
self.addEventListener('install', () => {
  // Sin esperar a que se cierren las pestañas viejas: como no hay caché, no hay
  // nada que pueda quedar inconsistente entre una versión y la siguiente.
  self.skipWaiting()
})

self.addEventListener('activate', (evento) => {
  evento.waitUntil(self.clients.claim())
})

self.addEventListener('fetch', () => {})
