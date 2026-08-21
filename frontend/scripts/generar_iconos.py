"""Genera los iconos de la PWA de LibraClub.

Se versiona el SCRIPT y también los PNG que produce: los iconos tienen que
existir en `public/` para que Vite los copie, pero un PNG suelto en el repo no
dice de dónde salió ni cómo rehacerlo. Con esto, cambiar el color de marca o el
dibujo es editar cuatro líneas y volver a correrlo.

    .venv/bin/python frontend/scripts/generar_iconos.py

🔑 **Los colores NO se inventan acá.** Salen de la landing del producto
(`libraclub_web/public/css/style.css`), que a su vez los genera `libra-web-kit`
desde `site_css_tokens.py`. Ese es el lugar donde vive la identidad de cada
sitio de la familia, así que el icono usa lo mismo que la web pública en vez de
un verde parecido.

⚠️ **Esto es una marca provisoria, no un logo diseñado.** Es un dibujo
geométrico —una cancha vista desde arriba— que se lee a 32px y a 512px. El día
que haya un logo de verdad, se reemplazan los PNG y se borra este script; lo que
NO hay que hacer es dejar los dos y que diverjan.
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

#: El verde de LibraClub, tal cual lo declara la landing (`--brand`).
MARCA = (1, 123, 75)
BLANCO = (255, 255, 255)

#: Se dibuja a 8x y se reduce con LANCZOS. Dibujar directo a 192px deja los
#: bordes del círculo y las líneas dentados: PIL no antialiasea las primitivas.
ESCALA = 8

_AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.join(_AQUI, "..", "public", "icons")
#: El mismo dibujo, pero como asset del bundle: es el que muestran el login y la
#: sidebar. Va en `src/assets` y no en `public` porque Vite le pone hash y lo
#: importa el código — ver `src/branding.ts`.
ASSETS = os.path.join(_AQUI, "..", "src", "assets")


def dibujar(lado: int, margen: float, redondeado: bool) -> Image.Image:
    """Una cancha vista desde arriba sobre el verde de la marca.

    `margen` es la fracción del lado que queda libre alrededor del dibujo. En
    los iconos comunes alcanza con poco; en el **maskable** tiene que ser
    grande, porque Android recorta hasta un círculo inscripto y todo lo que
    quede fuera del 80% central se pierde.
    """
    g = lado * ESCALA
    img = Image.new("RGBA", (g, g), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # El fondo. Redondeado para el icono normal (queda como una app más) y
    # cuadrado lleno para el maskable, que lo recorta el sistema.
    if redondeado:
        d.rounded_rectangle([0, 0, g - 1, g - 1], radius=int(g * 0.22), fill=MARCA)
    else:
        d.rectangle([0, 0, g - 1, g - 1], fill=MARCA)

    m = int(g * margen)
    # La cancha es apaisada: ocupa todo el ancho util y menos alto, que es lo que
    # la hace leerse como cancha y no como un cuadrado con lineas. En el maskable
    # el margen ya es grande, asi que ahi el alto sale del propio margen.
    borde_vertical = int(g * 0.30) if margen < 0.2 else m + int(g * 0.06)
    izq, der = m, g - m
    arr, aba = borde_vertical, g - borde_vertical
    grosor = max(2, int(g * 0.022))

    # El rectángulo de la cancha, la línea del medio y el círculo central: los
    # tres trazos que hacen que se lea como una cancha y no como un cuadrado.
    d.rectangle([izq, arr, der, aba], outline=BLANCO, width=grosor)
    medio_y = (arr + aba) // 2
    d.line([izq, medio_y, der, medio_y], fill=BLANCO, width=grosor)
    radio = int((der - izq) * 0.16)
    cx = (izq + der) // 2
    d.ellipse([cx - radio, medio_y - radio, cx + radio, medio_y + radio],
              outline=BLANCO, width=grosor)

    return img.resize((lado, lado), Image.LANCZOS)


def main() -> None:
    os.makedirs(RAIZ, exist_ok=True)
    piezas = [
        # (archivo, lado, margen, redondeado)
        ("icon-192.png", 192, 0.14, True),
        ("icon-512.png", 512, 0.14, True),
        # 180px y sin transparencia por el borde: iOS no redondea por su cuenta
        # si el PNG ya viene con esquinas, y una esquina transparente se ve
        # negra en el springboard.
        ("icon-apple-180.png", 180, 0.14, True),
        # El maskable: mucho más margen, y fondo cuadrado lleno. Android recorta
        # a gusto del launcher y sólo garantiza el 80% central.
        ("icon-maskable-512.png", 512, 0.26, False),
    ]
    for archivo, lado, margen, redondeado in piezas:
        img = dibujar(lado, margen, redondeado)
        if archivo == "icon-apple-180.png":
            fondo = Image.new("RGB", (lado, lado), MARCA)
            fondo.paste(img, (0, 0), img)
            img = fondo
        destino = os.path.join(RAIZ, archivo)
        img.save(destino, "PNG", optimize=True)
        print(f"{archivo}: {lado}x{lado} -> {os.path.getsize(destino)} bytes")

    # El logo del login y la sidebar. Sale del MISMO dibujo que los iconos a
    # propósito: si se generaran por separado, el día que cambie la marca uno de
    # los dos se queda viejo y nadie lo ve, porque nunca se miran juntos.
    os.makedirs(ASSETS, exist_ok=True)
    logo = os.path.join(ASSETS, "logo-libraclub.png")
    dibujar(256, 0.14, True).save(logo, "PNG", optimize=True)
    print(f"logo-libraclub.png: 256x256 -> {os.path.getsize(logo)} bytes")


if __name__ == "__main__":
    main()
