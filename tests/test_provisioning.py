"""Las dos puntas del provisioning, atadas al código que corre.

**Por qué existe este archivo.** El alta de un cliente le estampa a su
contenedor un healthcheck contra `health_path`. Con la SPA horneada, apuntarlo a
una ruta que la app **no** sirve no se ve como un 404: lo contesta el catch-all
de `app/asgi.py` con el `index.html`, o sea 200 con HTML. La instancia nacería
con un chequeo que mide que haya estáticos y se vería sana con la base caída.

Le pasó a [[libradesk]], que servía sólo `/api/health` mientras el provisioning
probaba `/health`, y no lo agarró el diff: lo agarró medir adentro del
contenedor.

Los tests no comparan contra un literal escrito acá. Sacan las rutas **del
router** y exigen que la que el provisioning va a usar esté entre ellas: un
literal repetido en el test es una tercera copia que puede divergir igual que
las otras dos.
"""

import importlib
import pathlib
import re

import pytest


def _rutas_de_salud() -> set[str]:
    """Las rutas que el router de salud sirve de verdad, leídas de él."""
    from app.routers import salud

    rutas = {r.path for r in salud.router.routes}
    assert rutas, "el router de salud no declara ninguna ruta"
    return rutas


@pytest.mark.parametrize("script", ["nuevo_cliente", "panel_admin"])
def test_el_health_path_del_provisioning_es_una_ruta_que_el_router_sirve(script):
    """Lo que el alta le va a estampar a la próxima instancia.

    Se prueban los **dos** scripts por separado y con `reload`: `configure()`
    pisa un `_cfg` global y `libracore.admin.services` importa los dos en el
    mismo proceso, así que manda el último import. Mirar uno solo dejaría al
    otro desviarse sin que nada lo dijera.
    """
    from libracore.provisioning import get_config

    modulo = importlib.import_module(f"scripts.{script}")
    importlib.reload(modulo)  # re-ejecuta su configure(), gane quien gane antes

    efectivo = get_config().health_path
    assert efectivo in _rutas_de_salud(), (
        f"scripts/{script}.py deja health_path={efectivo!r}, que el router de "
        "salud no sirve: toda instancia nueva nacería unhealthy para siempre, "
        "salvo que el catch-all de la SPA la tape con un 200."
    )


def test_los_dos_scripts_configuran_LO_MISMO():
    """El desvío que el comentario de los dos archivos promete que no existe.

    No alcanza con que cada uno sea válido por su lado: como comparten el
    `_cfg` global, dos configuraciones distintas hacen que el resultado dependa
    del orden de los imports — o sea que un alta después de un listado salga
    distinta que un alta sola.
    """
    from dataclasses import asdict

    from libracore.provisioning import get_config

    def config_de(script):
        importlib.reload(importlib.import_module(f"scripts.{script}"))
        return asdict(get_config())

    uno = config_de("nuevo_cliente")
    otro = config_de("panel_admin")

    distintos = {k: (uno[k], otro[k]) for k in uno if uno[k] != otro[k]}
    assert not distintos, f"los dos scripts configuran distinto: {distintos}"


@pytest.mark.parametrize("script", ["nuevo_cliente", "panel_admin"])
def test_el_deploy_declara_las_migraciones_que_este_repo_tiene(script):
    """Un producto con revisiones de Alembic tiene que declararlas, y bien.

    **Por qué existe.** `migraciones` es opcional y su default es vacío, así
    que un producto que no la declara no ve ningún paso y su deploy pasa de
    largo en silencio. Y declararla mal es peor: hasta el 2026-08-24 acá estaba
    en forma **plana**, válida contra el `v1.48.0` que este repo pineaba pero
    rechazada con `TypeError` por el `1.51.0` que el panel del VPS ya tenía
    instalado — o sea que el próximo deploy rompía el panel al importar.

    🔑 **Se aserta lo que el DEPLOY hace con el valor, no el valor.** Comparar
    lo declarado contra la tupla que uno escribió en el otro archivo se cumple
    por construcción y no prueba nada.
    """
    from libracore.provisioning import get_config

    raiz = pathlib.Path(__file__).parent.parent
    revisiones = sorted((raiz / "migrations" / "versions").glob("*.py"))

    importlib.reload(importlib.import_module(f"scripts.{script}"))
    declarados = get_config().migraciones

    if not revisiones:
        return

    assert declarados, (
        f"este repo tiene {len(revisiones)} revisiones de Alembic y "
        f"scripts/{script}.py no declara `migraciones`: el deploy las va a "
        "saltear en silencio."
    )
    # Textualmente lo que hace `cmd_actualizar` por cada comando.
    for comando in declarados:
        assert not isinstance(comando, str), (
            f"scripts/{script}.py declara {declarados!r} en forma PLANA.")
        " ".join(comando)

    assert any("alembic" in c for c in declarados), (
        f"scripts/{script}.py declara {declarados!r}, sin el `alembic` de la "
        "cadena propia de este repo.")


def test_el_producto_declara_planes_con_sus_modulos():
    """El backoffice asigna un plan al dar de alta: sin esto, el alta falla."""
    import plans

    assert plans.PLANES, "sin planes el alta de un cliente no tiene qué asignar"
    assert set(plans.PLAN_MODULOS) == set(plans.PLANES), (
        "hay un plan sin módulos declarados, o al revés")
    assert set(plans.PLAN_LABELS) == set(plans.PLANES)
    assert set(plans.PLAN_PRECIOS) == set(plans.PLANES)

    # Los planes son acumulativos: cada uno trae lo del anterior. Si algún día
    # dejan de serlo será una decisión, no un descuido.
    basico, estandar, premium = (set(plans.PLAN_MODULOS[p]) for p in
                                 ("basico", "estandar", "premium"))
    assert basico <= estandar <= premium

    # Todo módulo de un plan tiene nombre para mostrar: el backoffice los lista.
    assert set(plans.MODULOS) == premium
    assert set(plans.MODULO_LABELS) == set(plans.MODULOS)


def _bloque_del_servicio_de_dev() -> str:
    """El bloque del servicio `*-dev` del compose del repo, como texto.

    Sin `yaml`: no es dependencia de este repo ni de sus tests, y sumar una
    para leer una línea sería peor que recortar el bloque a mano. El corte es
    por indentación —un servicio arranca con dos espacios y su cuerpo tiene
    más—, que es exactamente lo que el archivo garantiza.
    """
    raiz = pathlib.Path(__file__).parent.parent
    lineas = (raiz / "docker-compose.yml").read_text(encoding="utf-8").splitlines()
    servicios = [i for i, linea in enumerate(lineas)
                 if re.match(r"^  [A-Za-z0-9_.-]+:\s*$", linea)]
    inicio = next((i for i in servicios
                   if lineas[i].strip().rstrip(":").endswith("-dev")), None)
    assert inicio is not None, (
        "el compose del repo no declara ningún servicio `*-dev`: este test "
        "está mirando un archivo que ya no tiene la forma que supone.")
    fin = next((i for i in servicios if i > inicio), len(lineas))
    return "\n".join(lineas[inicio:fin])


def _comando_de_arranque_de_dev() -> str:
    """El **valor** del `command:` del servicio de dev, y nada más.

    🔴 **La primera versión de este test buscaba en el bloque entero, y eso
    pasaba en verde con el paso de migraciones sacado del `command:` y dejado
    en un comentario.** Medido el 2026-08-25, no supuesto: un comentario que
    menciona `alembic upgrade head` no lo corre. Buscar en el bloque también
    dejaba que un `ports: - "8086:8000"` satisficiera un token del comando de
    arranque, que es la misma clase de falso verde.

    Un comentario no matchea `^\s+command:` porque el `#` va antes de la clave.
    """
    bloque = _bloque_del_servicio_de_dev()
    m = re.search(r"^\s+command:\s*(\S.*)$", bloque, re.MULTILINE)
    assert m, (
        "el servicio de dev del compose no declara `command:`. Si el arranque "
        "pasó a otra forma, este test hay que reescribirlo — no borrarlo.")
    return m.group(1).strip()


@pytest.mark.parametrize("script", ["nuevo_cliente", "panel_admin"])
def test_la_instancia_de_dev_corre_las_mismas_migraciones_que_el_deploy(script):
    """El otro camino, el que `cmd_actualizar` no toca.

    🔴 **La declaración de `migraciones` no cubre `dev`.** El motor corre esos
    comandos al actualizar las instancias de cliente y la demo, que son las que
    el panel administra. La de `dev` la levanta el `docker-compose.yml` de este
    repo, y hasta el 2026-08-25 ahí no había ningún paso de Alembic en ninguno
    de los cinco productos de la familia que usan Alembic. Se descubrió porque
    `libracargo-dev` apareció con la base una revisión atrás del código, con el
    chequeo de salud en 200.

    Lo que se aserta es que las dos puntas digan **lo mismo y en el mismo
    orden**. El modo de fallar de esto no es que alguien borre el `command:`,
    es que agregue una segunda cadena en `scripts/` y se olvide del compose:
    ahí `dev` migraría de menos y el error culparía a la revisión equivocada.

    Se lee el compose como texto y no se compara contra un literal escrito acá:
    un literal sería una tercera copia, con exactamente el mismo problema.
    """
    from libracore.provisioning import get_config

    importlib.reload(importlib.import_module(f"scripts.{script}"))
    declarados = get_config().migraciones
    if not declarados:
        return  # sin cadena declarada no hay nada que exigirle al compose

    arranque = _comando_de_arranque_de_dev()
    cursor = 0
    for comando in declarados:
        texto = " ".join(comando)
        pos = arranque.find(texto, cursor)
        assert pos != -1, (
            f"scripts/{script}.py declara `{texto}` y el servicio de dev del "
            "compose no lo corre" + (" en ese orden" if cursor else "") + ": "
            "la instancia de dev va a quedar con el código nuevo sobre el "
            "esquema viejo, que es lo que le pasó a LibraCargo el 2026-08-25."
        )
        cursor = pos + len(texto)
