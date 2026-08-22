#!/usr/bin/env python
"""Libera los turnos que nadie pagó. Lo corre el cron cada pocos minutos.

🔴 **Sin esto el portal público no funciona.** Una reserva del portal se retiene
provisoria durante `VENCIMIENTO_PROVISORIA` y se libera **sólo si alguien la
vence**: sin este barrido, el turno que un visitante empezó a reservar y
abandonó queda retenido para siempre, y la cancha de las 20:00 de un viernes
deja de venderse porque alguien abrió el formulario en marzo.

`POST /api/reservas/vencer-provisorias` existe desde F1 y pide sesión de admin,
así que el cron no puede llamarlo. Este script hace el mismo trabajo entrando
por el servicio, que es lo que hace `sync_mp_auto.py` de Contalibra.

🔑 **Hace las DOS cosas, y la segunda es fácil de olvidar.** Vencer la reserva
libera el turno; marcar el pago deja de mostrarle al jugador «esperando pago»
sobre algo que ya no existe. Son dos tablas y dos servicios.

    docker exec libraclub-dev python /app/scripts/vencer_provisorias.py
"""

from __future__ import annotations

import sys

from app import db
from app.servicios import pagos as servicio_pagos
from app.servicios import reservas as servicio_reservas
from app.tiempo import ahora


def main() -> int:
    db.inicializar()
    with db.fabrica_de_sesiones()() as sesion:
        reservas = servicio_reservas.vencer_provisorias(sesion)
        pagos = servicio_pagos.marcar_vencidos(sesion)
        sesion.commit()

    # Una línea por corrida, con fecha: el cron escribe a un log y lo que se
    # mira ahí es "esto corrió y cuándo". Un script silencioso es
    # indistinguible de uno que no está en el crontab.
    print(
        f"[{ahora():%d-%m-%Y %H:%M:%S}] provisorias vencidas: {reservas} · "
        f"pagos marcados: {pagos}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
