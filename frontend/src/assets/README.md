# De dónde salen el logo y los iconos

**Del kit de identidad de la familia**, no de un script de este repo:
`Proyectos-Wiki/diseños/kit-libra-v1/dist/libraclub/`.

Ahí están los cinco archivos ya normalizados —`logo-libraclub.png` y los cuatro
iconos de PWA— con el mismo lenguaje visual que los otros siete productos.

> 🔴 **Existió un `frontend/scripts/generar_iconos.py` que los dibujaba acá, y
> se borró el 2026-08-21.** Lo escribí sin haber buscado si ya existían, y
> existían: el análisis `libraclub-brecha-con-la-familia` decía *"el icono ya
> está normalizado en `diseños/kit-libra-v1/dist/libraclub/`"*. El resultado fue
> que LibraClub estuvo un día entero mostrando un dibujo propio —una cancha
> vista desde arriba— en vez de su logo, en el login, en el sidebar y en el
> icono de la aplicación instalada.
>
> El script se borró y no se arregló: mientras exista, alguien lo corre y los
> pisa de nuevo.

Para actualizarlos: copiar los cinco archivos del `dist/` del kit. Si el kit
cambia, cambian acá; no se regeneran.
