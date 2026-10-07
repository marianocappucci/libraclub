import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { App } from './App'
import './index.css'
import { aplicarIdentidad } from 'libra-ui/identidad'
import { cargarTema } from 'libra-ui/tema'

// La identidad del producto (libra-ui ADR-033): su color de acento (botón principal, ítem activo del menú, foco) y el `theme-color`. Va antes
// de `cargarTema()`: el acento que el backoffice elige por instancia se aplica en línea y, por eso, le gana a éste.
aplicarIdentidad('libraclub')

// El tema de la suite (libra-ui ADR-007/008): aplica lo último guardado de inmediato y pide los colores a esta misma instancia. No espera
// ni puede fallar: sin red o con un error, la app arranca con los colores de siempre.
void cargarTema()

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
// 🔴 Este bloque es la parte que se olvida, y hay un caso real: LibraCargo
// tenía el `manifest.webmanifest`, el `sw.js` y los cuatro iconos, y **no
// registraba nada** — sin esto el navegador nunca ofrece instalar, y desde
// afuera se ve igual que si la PWA estuviera puesta. Se arregló el 2026-08-21
// (libracargo#54); hoy los ocho productos de la familia registran acá.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {})
  })
}
