#!/usr/bin/env python3
"""Sincronización nocturna de MercadoPago.

    docker exec libraclub-dev python3 /app/scripts/sync_mp_auto.py [--dias N]

Trae de MercadoPago los cobros que **no llegaron por webhook** y los deja en la
bandeja. El trabajo lo hace `libracore.mp_sync`, que comparte la ingesta con el
botón *Sincronizar* de la pantalla: tenerlas separadas es lo que en Contalibra
dejó al cron afuera de un cambio y le costó dos comprobantes emitidos al CUIT
equivocado.

🔑 **Lo que este producto aporta es una sola cosa: qué cobros omitir.** Y no se
escribe acá: se importa de `app/routers/mp_bandeja.py`, el mismo lugar del que
lo lee la pantalla. Escribir el prefijo dos veces es exactamente cómo esto se
rompe en silencio — el filtro deja de matchear, los pagos de reservas que el
webhook ya resolvió aparecen en la bandeja, y alguien los factura dos veces.
"""

import asyncio
import logging
import os
import sys

# 🔴 Este script corre POR RUTA desde el cron, así que `sys.path[0]` es
# `/app/scripts` y no `/app`: sin esto no encuentra el paquete `app`. En el
# resto del repo el insert no hace falta —el paquete está instalado—, y acá es
# lo único que sostiene el import.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from libracore.mp_sync import sincronizar_y_facturar  # noqa: E402

from app.routers.mp_bandeja import REFERENCIAS_PROPIAS  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def main(argv=None) -> dict:
    import argparse

    parser = argparse.ArgumentParser(description="Sync automático de MercadoPago")
    parser.add_argument(
        "--dias", type=int, default=2,
        help="Días hacia atrás a sincronizar (default: 2)",
    )
    args = parser.parse_args(argv)
    return asyncio.run(
        sincronizar_y_facturar(
            dias=args.dias,
            # La MISMA constante que filtra la pantalla, importada y no
            # reescrita: es la divergencia que Contalibra ya pagó una vez.
            referencias_a_omitir=REFERENCIAS_PROPIAS,
            # Sin `debe_auto_facturar` propio: vale el default del motor, que
            # mira la bandera del cliente. La auto-facturación de las reservas
            # es otra cosa —vive en el cobro por QR— y esos pagos ni siquiera
            # llegan hasta acá, porque están en `REFERENCIAS_PROPIAS`.
        )
    )


if __name__ == "__main__":
    main()
