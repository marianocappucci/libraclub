# Esta carpeta ya no guarda el logo

La marca de LibraClub (el trofeo blanco sobre un cuadrado del verde de la marca) **no es un archivo**: la dibuja
`libra-ui/MarcaProducto` desde el registro `libra-ui/identidad` (ADR-033 del kit), y se pasa como `producto="libraclub"` a `Layout` y `Login`.
El `logo-libraclub.png` ilustrado del `kit-libra-v1` se retiró el 2026-10-07 (decisión del humano: el ícono plano reemplaza al logo ilustrado).

Los íconos de la aplicación instalada (`frontend/public/icons/*.png`) y el `frontend/public/favicon.svg` salen de la **marca dibujada** del kit
(ADR-034, libra-ui v0.124.0+): `marcas/libraclub-favicon.svg` es el `favicon.svg` tal cual, y los PNG se rasterizan de `marcas/libraclub.svg`
(la marca completa): `icon-192` e `icon-512` con esquinas transparentes, `icon-maskable-512` y `icon-apple-180` a sangre (sin esquinas, color de
la marca en todo el lienzo) y con el dibujo dentro de la zona segura.
Cada cambio de bytes cambia el sello `?v=` de `index.html` y del manifest (`tests/test_sello_de_los_iconos.py`).
