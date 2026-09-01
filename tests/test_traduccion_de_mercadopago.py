"""Qué quiso decir MercadoPago lo traduce el motor, no un `if` de cada archivo.

🔑 **Qué se unificó y qué NO.** Este producto conserva su `EstadoPago`, que dice
algo que el del motor no dice: *"APROBADO es lo único que confirma la reserva"*.
Eso es la regla del portal y es suya. Lo que se unificó es la otra mitad —**qué
significa el `status` que devuelve MercadoPago**—, que no tiene nada de propio.

🔴 **El riesgo que esto cierra.** El mismo `if` con los mismos literales estaba
escrito **dos veces**: en el poll del QR del mostrador
(`servicios/cobro_qr.py`) y en el webhook del portal (`routers/portal.py`). Dos
copias es de donde salen las divergencias: si MercadoPago agrega un estado que
hay que tratar como rechazado, actualizar una y olvidar la otra deja al portal y
al mostrador **cobrando distinto el mismo pago**.
"""

import inspect

from libracore import pagos as acreditacion

from app.routers import portal
from app.servicios import cobro_qr

#: Los estados que MercadoPago devuelve hoy, más uno inventado. El inventado es
#: el que importa: es el que aparece cuando MercadoPago agrega algo.
ESTADOS_DE_MP = [
    "approved", "rejected", "cancelled", "pending",
    "in_process", "in_mediation", "authorized", "un_estado_nuevo", "", None,
]


def test_un_estado_desconocido_no_acredita():
    """🔴 La propiedad que hace que unificar valga: MercadoPago puede agregar
    estados, y el único default que no acredita plata de más es dejarlo
    esperando."""
    assert (acreditacion.estado_desde_mercadopago("un_estado_nuevo")
            is acreditacion.EstadoAcreditacion.PENDIENTE)


def test_authorized_no_es_aprobado():
    """`authorized` es dinero **retenido, no capturado**. Tratarlo como
    aprobado confirmaría una reserva que todavía puede no pagarse."""
    assert (acreditacion.estado_desde_mercadopago("authorized")
            is acreditacion.EstadoAcreditacion.PENDIENTE)


def test_cancelled_es_rechazado():
    """Para el turno son lo mismo: no hay plata, la reserva no se confirma."""
    assert (acreditacion.estado_desde_mercadopago("cancelled")
            is acreditacion.EstadoAcreditacion.RECHAZADO)


def _decide_sobre_el_status_crudo(linea: str) -> bool:
    """Si esta línea es un `if` que decide mirando el `status` de MercadoPago.

    🔑 **Una sola definición, usada por el barrido Y por su control.** La
    primera versión tenía el patrón escrito dos veces —una en el barrido y otra
    inline en el control—, así que romper el del barrido no ponía nada en rojo:
    el control se estaba midiendo a sí mismo. Lo delató una mutación que
    sobrevivió.

    Pasar el estado crudo como **dato** —el `estado_mp="approved"` de los
    simuladores— no decide nada y no cuenta.
    """
    pelada = linea.strip()
    if pelada.startswith("#") or pelada.startswith("*"):
        return False
    return pelada.startswith("if ") and (
        '"approved"' in pelada or '"rejected"' in pelada or '"cancelled"' in pelada
    )


def test_los_dos_caminos_traducen_por_el_MISMO_lugar():
    """🔑 **El test que fija el cambio.**

    No compara comportamiento —eso ya lo cubren los tests del cobro— sino que
    ninguno de los dos archivos vuelva a decidir por su cuenta. Se lee el
    fuente porque lo que se afirma es una **ausencia**: que no haya un `if` con
    los literales de MercadoPago escrito a mano.

    Su control positivo es el test de abajo, que comprueba que el patrón
    encuentra algo donde el literal sí está.
    """
    culpables = []
    for modulo in (cobro_qr, portal):
        for n, linea in enumerate(inspect.getsource(modulo).splitlines(), 1):
            if _decide_sobre_el_status_crudo(linea):
                culpables.append(f"{modulo.__name__}:{n}: {linea.strip()}")
    assert not culpables, (
        "Un `if` decide sobre el status crudo de MercadoPago en vez de usar "
        "`estado_desde_mercadopago`:\n  " + "\n  ".join(culpables)
    )


def test_el_control_del_barrido_encuentra_lo_que_busca():
    """🔴 El control positivo del de arriba: ese test pasa **leyendo texto**, y
    con el patrón mal escrito daría verde para siempre sin mirar nada.

    Acá se le da una línea que sí tiene la forma prohibida y se comprueba que
    la reconoce.
    """
    # 🔑 Llama a la MISMA función que el barrido. Con el patrón reimplementado
    # acá, romper el del barrido no ponía nada en rojo.
    assert _decide_sobre_el_status_crudo('    if estado_mp == "approved":')
    assert _decide_sobre_el_status_crudo('    if estado_mp in ("rejected", "cancelled"):')
    # Y lo que NO debe reconocer: pasar el estado como dato, o un comentario.
    assert not _decide_sobre_el_status_crudo('    sesion, pago, estado_mp="approved"')
    assert not _decide_sobre_el_status_crudo('    # if estado_mp == "approved":')


def test_los_dos_modulos_importan_la_traduccion():
    """Que no haya `if` no alcanza: si ninguno de los dos importara el motor,
    el barrido pasaría igual con la traducción borrada."""
    for modulo in (cobro_qr, portal):
        assert "estado_desde_mercadopago" in inspect.getsource(modulo), (
            f"{modulo.__name__} no usa la traducción del motor")


def test_la_traduccion_cubre_todo_lo_que_MP_puede_devolver():
    """Ninguno de los estados conocidos —ni uno inventado, ni vacío, ni
    `None`— hace levantar la traducción. Un `KeyError` acá dejaría el poll del
    mostrador tirando 500 en la cara del cajero."""
    for estado in ESTADOS_DE_MP:
        resultado = acreditacion.estado_desde_mercadopago(estado)
        assert isinstance(resultado, acreditacion.EstadoAcreditacion)
