"""Los comprobantes del complejo: facturas, notas de crédito y notas de débito.

Los doce endpoints los arma `libracore.facturas_router` —el mismo módulo que
consumen [[contalibra]] y [[restolibra]] desde el 2026-08-27—, así que este
producto no reimplementa nada del circuito fiscal.

Lo que sí es de acá:

- **El PDF** (`GET /api/facturas/{id}/pdf`), que el factory no trae: los otros
  dos productos lo sirven desde su router Jinja2 viejo, que este producto no
  tiene.
- **El `usuario_id` en `None`**, por una razón que conviene leer antes de
  "arreglarlo" — ver `_usuario_para_el_motor`.
- **El cobro por la caja del turno**: el motor lo hace solo con `exigir_turno=True`
  (ADR-060 de libracore) y acá sólo se le dice quién cobra (`usuario_del_turno`)
  y qué rechaza este producto (`_validar_cobro`). Ver los comentarios de
  `build_comprobantes_router` más abajo.

> ⚠️ **La emisión desde el turno sigue siendo otra cosa.**
> `POST /api/reservas/{id}/facturar` arma la factura de una reserva con su
> alquiler y su consumo de buffet adentro, y vive en `servicios/facturacion.py`.
> Lo que agrega este router es la emisión **manual** —una factura que no sale de
> un turno— y las notas de crédito y débito, que antes no existían en el
> producto.
"""

from __future__ import annotations

import tempfile

from fastapi import APIRouter, Depends, HTTPException, Response
from libracore import cobros as libracore_cobros
from libracore import pdf_generator
from libracore.db import facturas as db_facturas
from libracore.facturas_router import build_comprobantes_router

from app.auth import get_current_user, require_admin
from app.routers.facturacion import exigir_base
from app.servicios import caja as servicio_caja
from app.smtp import smtp_config

#: El PDF va en su propio router porque el otro lo arma el motor. Mismo prefijo:
#: las rutas no chocan —`/{id}/pdf` son dos segmentos y `/{id}` uno—, y para la
#: pantalla es un solo recurso.
router = APIRouter(prefix="/api/facturas", tags=["facturas"])


def _usuario_para_el_motor(usuario: dict = Depends(get_current_user)) -> dict:
    """El usuario de la sesión, pero **sin id para LibraCore**.

    🔴 `facturas.usuario_id` es una FK contra la tabla `usuarios` **de la base de
    LibraCore**, y en este producto los usuarios no viven ahí: viven en la base
    del dominio, con la forma de `libraauth`. Es la separación al revés que en
    Gestiolibra, MedLibra y VentaLibra, donde `usuarios` sí está del lado del
    motor — ver el docstring de `servicios/facturacion.py`.

    Pasar el id del usuario del dominio haría una de dos cosas, las dos malas:
    reventar el INSERT con un `FOREIGN KEY constraint failed`, o —si algún día
    esa tabla tuviera filas— **acreditarle la factura a otra persona**, que es
    peor porque no falla.

    Queda en `None`, que es exactamente lo que ya hace `facturar_reserva` desde
    el 2026-08-21. La trazabilidad de quién emitió no se pierde: la anota el log
    de actividad de este producto, que corre sobre la base del dominio.

    Se conserva la dependencia de sesión igual, así que el endpoint sigue
    exigiendo estar logueado.

    🔑 **`id_dominio` es el agregado, y es lo que necesita el cobro por turno.**
    El motor tiene que abrir el turno de quien está logueado —el `usuario_id`
    de `turnos_caja` es el del dominio— sin tocar el `id` que ve el propio
    motor, que sigue en `None` por lo de arriba. Se lo dice
    `usuario_del_turno=lambda u: u["id_dominio"]` en `build_comprobantes_router`.
    """
    return {**usuario, "id": None, "id_dominio": usuario["id"]}


def _validar_cobro(factura: dict, pagos: list[dict], usuario: dict) -> None:
    """Lo que este producto rechaza de un cobro **antes** de que el motor escriba nada.

    🔑 **Es todo lo que queda del hook propio de cobro.** Hasta ADR-060 de
    libracore este módulo reemplazaba la escritura entera del motor
    (`_cobrar_del_turno`) porque el default no sabía de turnos y dejaba la plata
    fuera de todo arqueo. Ahora el motor entra solo por el turno abierto de quien
    cobra (`exigir_turno=True`: `turno_id`, la caja del turno y su dueño; `fecha`
    y `caja_id` del pedido se ignoran; sin turno, 409), con el tope de lo
    pendiente y el candado de la factura. Acá sólo queda lo que el motor no
    conoce:

    🔴 **Una factura a cuenta corriente se rechaza con 409.** La cuenta corriente
    de LibraClub (`servicios/cuenta_corriente.py`) es un sistema propio del
    dominio —clientes y saldos del dominio, sin relación con `clients` de
    LibraCore— y no tiene forma de imputar un pago a una factura puntual:
    `registrar_pago` no recibe `factura_id`. El camino correcto es la pantalla de
    la cuenta corriente del cliente, no este diálogo.

    🔑 **El vocabulario de medios de ESTE producto**, validado para todos los
    pagos antes de escribir el primero: un cobro con dos medios y el segundo
    inválido no deja escrito el primero. La cuenta corriente como medio la sigue
    rechazando el motor, con su propio mensaje (`MedioNoEsDeCobro`).
    """
    if factura.get("condicion_venta") == "Cuenta Corriente":
        raise HTTPException(
            409,
            "Esta factura se emitió a cuenta corriente: el pago se registra "
            "desde la cuenta corriente del cliente.",
        )

    for pago in pagos or []:
        monto = float(pago.get("monto") or 0)
        if monto <= 0:
            continue
        medio = pago.get("medio_id", "")
        if libracore_cobros.es_medio_cuenta_corriente(medio):
            continue
        if medio not in servicio_caja.MEDIOS_PAGO:
            raise HTTPException(
                400,
                f"Medio de pago desconocido: {medio!r}. Medios válidos: "
                f"{', '.join(servicio_caja.MEDIOS_PAGO)}.",
            )


comprobantes = build_comprobantes_router(
    usuario_actual=_usuario_para_el_motor,
    solo_admin=require_admin,
    # Este producto no tiene bandeja de MercadoPago ni ventas de POS que
    # vincular después de emitir, así que no hay hook de post-emisión. La
    # factura que sale de un turno se emite por `/api/reservas/{id}/facturar`,
    # que escribe `reserva.factura_id` por su cuenta.
    al_emitir=None,
    # 🔑 La caja de este producto es por turno (`turnos_caja`, con su arqueo al
    # cerrar), así que el cobro **entra por el turno abierto de quien cobra**: el
    # motor lo hace con `exigir_turno=True` (ADR-060 de libracore) y conserva su
    # tope de lo pendiente (409) y su candado, que un `registrar_cobro` propio
    # perdería. Sin turno, 409 «No hay una caja abierta…».
    exigir_turno=True,
    # El turno se abrió con el id del DOMINIO; el `id` que ve el motor es `None`
    # (ver `_usuario_para_el_motor`).
    usuario_del_turno=lambda usuario: usuario["id_dominio"],
    validar_cobro=_validar_cobro,
    donde_configurar_smtp="Configuración → Email",
    # 🔴 Sin esto el motor lee `email_smtp_*` de `config.json`, que en este
    # producto **no lo escribe nadie** — la pantalla de Configuración guarda en
    # la base cifrada de libraauth, igual que en los otros siete. O sea que
    # mandar un comprobante por mail fallaba con un 400 aunque la instancia
    # tuviera un SMTP perfectamente cargado. Ver `app/smtp.py`.
    smtp_config=smtp_config,
)


@router.get("/{factura_id}/pdf")
def pdf(factura_id: int) -> Response:
    """El PDF del comprobante, generado al momento.

    🔑 **Se regenera en cada pedido y no queda nada en disco.** El motor sabe
    guardarlo y Contalibra lo usa así, pero acá no conviene: un PDF guardado se
    queda con el logo y el domicilio **viejos** si el dueño edita los datos de la
    empresa; el nombre que arma el motor es `factura_{pv}_{numero}.pdf`, **sin el
    tipo**, así que una nota de crédito con el mismo número lo pisaría; y el
    backup de este producto lleva las dos bases pero `directorios=[]`, o sea que
    el archivo no entraría al ZIP.

    Un comprobante se reconstruye entero desde su fila: guardarlo sería cachear
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
    # `inline` y no `attachment`: el navegador lo abre en una pestaña y desde ahí
    # se imprime o se guarda, que es lo que hace falta en un mostrador.
    return Response(
        contenido,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{nombre}"'},
    )
