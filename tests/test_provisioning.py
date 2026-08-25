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
