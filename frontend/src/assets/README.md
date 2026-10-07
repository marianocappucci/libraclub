# Esta carpeta ya no guarda el logo

La marca de LibraClub (el trofeo blanco sobre un cuadrado del verde de la marca) **no es un archivo**: la dibuja
`libra-ui/MarcaProducto` desde el registro `libra-ui/identidad` (ADR-033 del kit), y se pasa como `producto="libraclub"` a `Layout` y `Login`.
El `logo-libraclub.png` ilustrado del `kit-libra-v1` se retiró el 2026-10-07 (decisión del humano: el ícono plano reemplaza al logo ilustrado).

Los íconos de la aplicación instalada (`frontend/public/icons/*.png`) y el `frontend/public/favicon.svg` salen del favicon que genera el kit de
landings (`libraclub_web/public/img/favicon.svg`: cuadrado redondeado del color + glifo blanco). Los PNG se rasterizan de ese SVG: `icon-192` e
`icon-512` con esquinas transparentes, `icon-maskable-512` y `icon-apple-180` a sangre (sin esquinas) y con el glifo dentro de la zona segura.
Cada cambio de bytes cambia el sello `?v=` de `index.html` y del manifest (`tests/test_sello_de_los_iconos.py`).
