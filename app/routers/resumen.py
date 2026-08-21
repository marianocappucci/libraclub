"""`GET /api/resumen` — los números de esta sucursal, para el panel del dueño.

El endpoint **no se implementa acá**: lo arma la factory de LibraCore
(`build_resumen_router`), y este módulo se limita a cablear lo que sabe el
producto. Mismo patrón que Contalibra.

🔑 **LibraClub es el primero con los TRES bloques.** Hasta ahora el resumen
tenía núcleo (LibraCore, en los seis) y comercio (LibraCommerce, en cuatro);
`agenda` nace acá, y nace con la ocupación adentro — que es el número por el
que un dueño de complejo mira un panel.

Ver `wiki/analyses/panel-del-dueno-multisucursal.md`.
"""

from __future__ import annotations

from libraauth.session_auth import json_api_require_panel_o_admin
from libracommerce.db.repository import SqliteCommerceRepository
from libracore import config_manager
from libracore.db import core as libracore_core
from libracore.resumen_router import build_resumen_router
from sqlalchemy import select

from app import db
from app.models.maestros import Sucursal
from app.servicios import facturacion
from app.servicios.resumen_agenda import resumen_agenda


def _identidad() -> dict:
    """Quién es esta sucursal, para que el panel la sepa nombrar y agrupar.

    El CUIT es lo que permite el consolidado **por razón social**, que es el
    único que cierra contra los libros: sumar entre CUITs da un número de
    gestión, no uno declarable.

    ⚠️ **El punto de venta sale de la sucursal, no de la config de ARCA.** En
    este producto es una columna de `sucursales` —`punto_venta_arca`— porque la
    numeración de ARCA es por `(tipo, punto_venta)` y **no lleva CUIT**: dos
    sucursales del mismo CUIT emitiendo con el mismo PV se pisan entre ellas.
    Contalibra lo lee de `arca_configs` porque allá la instancia es una sola
    sucursal; acá no.
    """
    cfg = config_manager.load()
    with db.fabrica_de_sesiones()() as sesion:
        pv = sesion.scalars(
            select(Sucursal.punto_venta_arca)
            .where(Sucursal.activa.is_(True), Sucursal.punto_venta_arca.is_not(None))
            .order_by(Sucursal.id)
        ).first()
    return {
        "nombre": cfg.get("empresa_nombre", ""),
        "cuit": cfg.get("empresa_cuit", ""),
        "punto_venta": pv,
    }


def _comercio(desde: str, hasta: str) -> dict:
    """El buffet: ventas del período y stock bajo mínimo. Lo trae LibraCommerce."""
    conexion = libracore_core.get_connection()
    try:
        return SqliteCommerceRepository(conexion).resumen_comercio(desde, hasta)
    finally:
        conexion.close()


def _agenda(desde: str, hasta: str) -> dict:
    """Reservas, ocupación y cancelaciones. Ver `servicios/resumen_agenda.py`."""
    with db.fabrica_de_sesiones()() as sesion:
        return resumen_agenda(sesion, desde, hasta)


def construir_router():
    """El router, armado en el arranque. `None` si esta instancia no puede
    contestarle al panel.

    🔴 **Es una función y no un `router` de módulo, a diferencia de Contalibra**,
    por dos motivos que se descubren juntos.

    El primero: el **núcleo** del resumen —facturado, cobrado, caja— sale de la
    base de LibraCore, que en una instancia sin
    `LIBRACLUB_LIBRACORE_DATABASE_URL` no existe. No es que falte un bloque: no
    hay núcleo, que es lo único que la factory manda siempre. Montar el endpoint
    igual daría un 500 al primer llamado del panel.

    El segundo: armado al importar, el módulo se evaluaría **antes** de que
    `facturacion.configurar()` haya corrido, así que ni siquiera se podría
    preguntar.

    Por eso el router se arma en `crear_app()` y **no se monta** cuando falta esa
    base. Una instancia así le contesta 404 al panel, que es distinguible de
    contestarle ceros — un producto que no puede medir no informa cero, no
    informa. Es la misma regla del resumen, un nivel más arriba: acá el que se
    omite no es un bloque sino el endpoint entero.
    """
    if not facturacion.hay_base():
        return None
    return build_resumen_router(
        identidad=_identidad,
        # El guard viene de libraauth y no de libracore: los dos son motores
        # peers y libracore no depende de aquel. El producto, que depende de los
        # dos, es el que los une.
        guard=json_api_require_panel_o_admin,
        # 🔑 LibraClub es el primero que manda los TRES: núcleo, comercio y
        # agenda. `comercio` lo puede contestar porque el buffet vive en la
        # misma base de LibraCore que se acaba de verificar.
        bloques={"comercio": _comercio, "agenda": _agenda},
    )
