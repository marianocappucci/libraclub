import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { App } from './App'
import './index.css'

const raiz = document.getElementById('root')
if (!raiz) throw new Error('falta #root en index.html')

createRoot(raiz).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)

// Instalable como aplicación: el service worker no cachea nada (ver
// `public/sw.js`), sólo existe para que el navegador ofrezca instalarla.
// El fallo se traga a propósito: que no se pueda registrar —contexto sin
// https, un navegador que no lo soporta— no tiene por qué romper la app.
//
// 🔴 Este bloque es la parte que se olvida. [[libracargo]] tiene el
// `manifest.webmanifest`, el `sw.js` y los cuatro iconos, y **no registra
// nada**: sin esto el navegador nunca ofrece instalar, y desde afuera se ve
// igual que si la PWA estuviera puesta. Verificado el 2026-08-20 en los siete
// productos — seis registran acá, LibraCargo no.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {})
  })
}
