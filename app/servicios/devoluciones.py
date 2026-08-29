"""La devolución de una seña en MercadoPago.

Vive **acá y no en `libracore.mp_api`** aunque sea una operación genérica de
MercadoPago: LibraClub es el primer producto de la familia que devuelve plata, y
la regla del repo es que algo sube al motor cuando es la tercera copia y no la
segunda. El día que Contalibra o VentaLibra necesiten devolver, esto se muda tal
cual — por eso no toca nada del dominio: recibe un `payment_id` y devuelve un
`refund_id`.

`mp_api` además es **async** y el camino de la cancelación es sincrónico. Un
cliente sincrónico en una ruta sincrónica de FastAPI corre en el threadpool y no
bloquea el loop; el puente al revés —correr async desde sync— es el que trae
problemas.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import httpx

MP_API_BASE = "https://api.mercadopago.com"

#: Cuánto se espera a MercadoPago. Generoso comparado con una lectura, porque
#: del otro lado hay un movimiento de plata: cortar a los 5 segundos deja la
#: duda de si la devolución salió, que es peor que esperar.
TIMEOUT = 20


class DevolucionRechazada(Exception):
    """MercadoPago no aceptó la devolución, o no se pudo preguntar."""


class Pasarela(Protocol):
    """Quién devuelve la plata. Un objeto para poder no tenerlo."""

    def disponible(self) -> bool:
        """Si hay con qué devolver.

        Se pregunta **antes** de intentar: una instancia sin credenciales no
        tiene que acumular intentos fallidos, tiene que dejar la devolución
        pendiente y decir por qué.
        """

    def devolver(self, *, payment_id: str, referencia: str) -> str:
        """Devuelve el `refund_id`, o levanta `DevolucionRechazada`."""


class DevolucionMercadoPago:
    """La de verdad: `POST /v1/payments/{id}/refunds`.

    **Devolución total y no parcial**: el pago del portal es exactamente la
    seña, así que devolver el pago entero es devolver la seña. Una devolución
    parcial requeriría decidir un monto, y ese número no lo tiene el sistema.
    """

    def __init__(self, token: Callable[[], str]) -> None:
        #: Un callable y no el valor: la pantalla de Mercado Pago edita el token
        #: mientras el proceso corre, igual que el SMTP de los avisos.
        self._token = token

    def disponible(self) -> bool:
        return bool((self._token() or "").strip())

    def devolver(self, *, payment_id: str, referencia: str) -> str:
        token = (self._token() or "").strip()
        if not token:
            raise DevolucionRechazada("La instancia no tiene Access Token de MercadoPago.")

        try:
            with httpx.Client(timeout=TIMEOUT) as cliente:
                respuesta = cliente.post(
                    f"{MP_API_BASE}/v1/payments/{payment_id}/refunds",
                    headers={
                        "Authorization": f"Bearer {token}",
                        # 🔴 **Lo que impide devolver dos veces la misma seña.**
                        # El reintento del mostrador manda el mismo pedido, y sin
                        # esta clave MercadoPago lo toma como una devolución
                        # nueva: el complejo pagaría dos veces. La clave es del
                        # pago, no del intento, justamente para que todos los
                        # reintentos compartan la misma.
                        "X-Idempotency-Key": referencia,
                    },
                )
        except httpx.HTTPError as exc:
            # No se pudo ni preguntar. Distinto de un rechazo: acá la devolución
            # puede haber salido igual, y por eso queda pendiente y se reintenta
            # con la misma clave de idempotencia.
            raise DevolucionRechazada(f"No se pudo hablar con MercadoPago: {exc}") from exc

        if respuesta.status_code >= 400:
            # 🔑 Se recorta el cuerpo: la respuesta de error de MercadoPago se
            # guarda en `detalle_devolucion` y se muestra en el mostrador. Sin
            # el corte, un HTML de error entero termina en la pantalla.
            raise DevolucionRechazada(
                f"MercadoPago rechazó la devolución ({respuesta.status_code}): "
                f"{respuesta.text[:300]}"
            )

        cuerpo = respuesta.json()
        refund_id = cuerpo.get("id")
        if not refund_id:
            raise DevolucionRechazada(
                f"MercadoPago contestó {respuesta.status_code} pero sin id de devolución."
            )
        return str(refund_id)


def pasarela_de_la_instancia() -> Pasarela:
    """La pasarela con el token que tenga cargado esta instancia.

    Se arma acá y no en cada router para que el token salga de un solo lugar
    —`config_manager`, la misma pantalla de Mercado Pago que usa el cobro con
    QR— y no de dos que puedan divergir.
    """
    from libracore import config_manager

    return DevolucionMercadoPago(
        lambda: str(config_manager.load().get("mp_access_token") or "")
    )


class SinPasarela:
    """No hay con qué devolver. Es el caso de una instancia sin credenciales.

    Existe como objeto —en vez de un `None` que haya que chequear en cada
    llamada— para que el camino de la cancelación sea uno solo: siempre se le
    pide a una pasarela, y la que no puede lo dice.
    """

    def disponible(self) -> bool:
        return False

    def devolver(self, *, payment_id: str, referencia: str) -> str:
        raise DevolucionRechazada("Esta instancia no tiene MercadoPago configurado.")
