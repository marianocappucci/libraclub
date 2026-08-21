"""El sello de contenido en la URL de cada icono.

**Por qué existe.** Chrome no guarda el favicon en el caché HTTP: lo guarda en
una base propia, indexada por la **URL del icono**, y esa base no mira el
`cache-control` que manda el servidor. Mientras la URL no cambie, la pestaña
puede seguir mostrando el dibujo de hace semanas aunque el archivo servido ya
sea otro. Pasó de verdad el 2026-08-21: los ocho productos servían el icono
nuevo del kit —200, `last-modified` del 20-08, los bytes correctos— y dos
pestañas seguían mostrando la inicial plateada que ese kit había reemplazado.
Desde afuera se ve igual que un deploy que no salió.

El arreglo es que un cambio de bytes sea un cambio de URL: cada `href` del
`index.html` y cada `src` del manifest llevan `?v=<8 hex del sha256 del
archivo>`.

**Y por eso existe este test.** Un sello escrito a mano es un campo que nadie
mantiene: quien regenere un icono no tiene por qué acordarse de tocar además el
HTML y el manifest, y el defecto vuelve sin que nada se ponga en rojo. Acá el
valor esperado se **recalcula de los bytes**, así que el olvido no es un icono
viejo en la pestaña de un cliente dentro de tres semanas: es un test rojo que
dice qué hay que poner.
"""
import hashlib
import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
INDEX = RAIZ / "frontend" / "index.html"
PUBLICO = RAIZ / "frontend" / "public"
MANIFEST = PUBLICO / "manifest.webmanifest"


def _sello(nombre: str) -> str:
    """Los 8 primeros hex del sha256 del archivo, que es lo que va en la URL."""
    return hashlib.sha256((PUBLICO / "icons" / nombre).read_bytes()).hexdigest()[:8]


def test_el_index_sella_los_iconos_que_enlaza():
    html = INDEX.read_text(encoding="utf-8")

    for nombre in ("icon-192.png", "icon-apple-180.png"):
        esperado = f'href="/icons/{nombre}?v={_sello(nombre)}"'
        assert esperado in html, (
            f"el sello de {nombre} no es el de sus bytes: tiene que decir {esperado}"
        )


def test_el_manifest_sella_sus_iconos():
    """El manifest alimenta el icono de la aplicación instalada, que se cachea
    igual que el de la pestaña y por el mismo motivo."""
    datos = json.loads(MANIFEST.read_text(encoding="utf-8"))

    for icono in datos["icons"]:
        ruta, _, consulta = icono["src"].partition("?")
        nombre = ruta.rsplit("/", 1)[-1]
        assert consulta == f"v={_sello(nombre)}", (
            f"{icono['src']}: el sello no es el de sus bytes"
        )


def test_ninguna_url_de_icono_queda_sin_sello():
    """El control, y no es decorativo: los dos tests de arriba miran los iconos
    que ya están: un `<link>` nuevo sin sellar los deja a los dos en verde."""
    texto = INDEX.read_text(encoding="utf-8") + MANIFEST.read_text(encoding="utf-8")

    sin_sello = re.findall(r"/icons/[\w.-]+\.png(?!\?v=)", texto)

    assert not sin_sello, f"URLs de icono sin sello: {sin_sello}"
