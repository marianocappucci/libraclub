"""`GET /api/facturas` y `GET /api/facturas/{id}/pdf` — los comprobantes emitidos.

El listado que faltaba: hasta hoy una factura sólo se veía desde el turno que la
originó, así que *"¿qué facturé este mes?"* no tenía dónde preguntarse. El
detalle sigue siendo el diálogo de la reserva —acá no se reimplementa—; esto es
la vista de arriba y el PDF.

🔑 **Todo admin, también la lectura.** La factura de SU reserva la puede ver el
mostrador (`GET /api/reservas/{id}/factura`, `require_staff`); el listado de
todo lo facturado por el complejo es otra cosa: es la plata del negocio, y va
con el mismo criterio que el historial de caja y el log de actividad. El gate lo
pone `main.py` al montar, como en los otros dos routers de facturación.

⚠️ **Sin columna de cobrado, y es una decisión.** `get_facturas_filtradas`
devuelve `total_cobrado` cruzando `caja_movimientos.factura_id`, pero en este
producto ese campo **sólo lo llena el cobro por QR de MercadoPago**:
`POST /api/caja/cobros` lo acepta y la pantalla de Caja nunca lo manda, porque
el cobro en efectivo se carga como monto + concepto libre, sin vínculo con la
reserva. Una columna "cobrada" diría **pendiente para todo lo cobrado en
efectivo**, que es peor que no tenerla. Atar el cobro manual a la factura es su
propio trabajo.

⚠️ **La búsqueda por texto distingue mayúsculas.** `get_facturas_filtradas` usa
`LIKE` y `libracore.db.core` no lo traduce a `ILIKE`, así que sobre PostgreSQL
`juan` no encuentra `Juan`. No lo introduce este producto —le pasa igual a
Contalibra y a Restolibra— y se arregla en el motor, en su propia sesión.
"""

from __future__ import annotations

import tempfile

from fastapi import APIRouter, HTTPException, Query, Response
from libracore import pdf_generator
from libracore.db import facturas as db_facturas
from pydantic import BaseModel

from app.routers.facturacion import exigir_base

router = APIRouter(prefix="/api/facturas", tags=["facturas"])

#: Filas por página. El mismo que Contalibra, que es la pantalla de la que ésta
#: toma la forma.
TAMANIO_DE_PAGINA = 50

#: Qué comprobantes lista. **Fijo**: este producto emite facturas y nada más —
#: no hay notas de crédito ni de débito que mostrar, así que la `vista` del
#: motor no se expone como parámetro. Ofrecer pestañas vacías sería prometer un
#: circuito que no existe.
_VISTA = "facturas"


class FacturaDeListado(BaseModel):
    id: int
    tipo: int
    punto_venta: int
    numero: int
    fecha: str
    cliente_razon: str
    cliente_cuit: str
    total: float
    #: Vacío mientras ARCA no lo haya dado. **No es un error**: la factura
    #: existe y lo que falta es el CAE. Ver `servicios/facturacion.py`.
    cae: str
    cae_vto: str


class PaginaDeFacturas(BaseModel):
    items: list[FacturaDeListado]
    total: int
    total_pages: int
    page: int


def _a_salida(factura: dict) -> FacturaDeListado:
    # Los `or ""`: las cuatro columnas son NULL-ables en el schema del motor, y
    # un complejo le factura a Consumidor Final sin CUIT todo el tiempo.
    return FacturaDeListado(
        id=factura["id"], tipo=factura["tipo"], punto_venta=factura["punto_venta"],
        numero=factura["numero"], fecha=str(factura["fecha"]),
        cliente_razon=factura.get("cliente_razon") or "",
        cliente_cuit=factura.get("cliente_cuit") or "",
        total=float(factura["total"]),
        cae=factura.get("cae") or "", cae_vto=factura.get("cae_vto") or "",
    )


@router.get("", response_model=PaginaDeFacturas)
def listar(
    desde: str = "",
    hasta: str = "",
    q: str = "",
    page: int = Query(1, ge=1),
) -> PaginaDeFacturas:
    """Los comprobantes del complejo, con filtro de fechas y búsqueda.

    `desde`/`hasta` van en **ISO** (`aaaa-mm-dd`): es lo que manda un
    `<input type="date">` y lo que guarda la columna. El `dd-mm-aaaa` es de la
    pantalla y no toca la API.
    """
    exigir_base()
    resultado = db_facturas.get_facturas_filtradas(
        desde, hasta, q, _VISTA, TAMANIO_DE_PAGINA, (page - 1) * TAMANIO_DE_PAGINA,
    )
    total = resultado["total"]
    return PaginaDeFacturas(
        items=[_a_salida(f) for f in resultado["items"]],
        total=total,
        # `max(1, ...)`: sin resultados sigue habiendo una página, la vacía. Un
        # `total_pages` en 0 deja a la paginación de la pantalla sin nada que
        # numerar.
        total_pages=max(1, (total + TAMANIO_DE_PAGINA - 1) // TAMANIO_DE_PAGINA),
        page=page,
    )


@router.get("/{factura_id}/pdf")
def pdf(factura_id: int) -> Response:
    """El PDF del comprobante, generado al momento.

    🔑 **Se regenera en cada pedido y no queda nada en disco.** El motor sabe
    guardarlo (`update_factura_pdf_path`) y Contalibra lo usa así, pero acá no
    conviene por tres motivos que se juntan: un PDF guardado se queda con el
    logo y el domicilio **viejos** si el dueño edita los datos de la empresa;
    el nombre que arma el motor es `factura_{pv}_{numero}.pdf`, **sin el
    tipo**, así que el día que exista una nota de crédito con el mismo número
    se pisan; y el backup de este producto lleva las dos bases pero
    `directorios=[]`, o sea que un archivo en disco no entraría al ZIP. Un
    comprobante se reconstruye entero desde su fila — guardarlo sería cachear
    lo barato y arriesgar lo caro.
    """
    exigir_base()
    factura = db_facturas.get_factura(factura_id)
    if factura is None:
        raise HTTPException(404, "no existe ese comprobante")
    with tempfile.TemporaryDirectory() as carpeta:
        ruta = pdf_generator.generate_pdf_factura(factura, output_dir=carpeta)
        with open(ruta, "rb") as archivo:
            contenido = archivo.read()
    nombre = (
        f"factura-{str(factura['punto_venta']).zfill(4)}"
        f"-{str(factura['numero']).zfill(8)}.pdf"
    )
    # `inline` y no `attachment`: el navegador lo abre en una pestaña y desde
    # ahí se imprime o se guarda, que es lo que hace falta en un mostrador.
    return Response(
        contenido,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{nombre}"'},
    )
