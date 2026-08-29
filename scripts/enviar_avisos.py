#!/usr/bin/env python
"""Manda las confirmaciones, los recordatorios y las cancelaciones. Lo corre el cron.

🔴 **Este script ES el interruptor de los avisos.** No hay un `avisos_activos`
en la config, a propósito: dos interruptores para lo mismo terminan en
desacuerdo, y el día que el dueño diga «no me manda los mails» habría que
adivinar cuál de los dos está apagado. Sin el cron no sale nada; con el cron
puesto y el SMTP cargado, sale.

Corre cada 5 minutos. Es la granularidad de la confirmación —el que reserva a
las 20:00 recibe el mail a más tardar 20:05— y no importa para los
recordatorios, que se miden en horas.

    */5 * * * * docker exec libraclub-dev python /app/scripts/enviar_avisos.py \
        >> /var/log/libraclub-avisos.log 2>&1

⚠️ **Si el cron estuvo caído más de dos horas, las confirmaciones de esa ventana
no salen.** Es deliberado: la ventana es lo que impide que la primera corrida le
escriba a todos los clientes por todos los turnos futuros ya cargados. Ver
`VENTANA_DE_CONFIRMACION` en `servicios/avisos.py`.
"""

from __future__ import annotations

import sys

from libraauth.smtp_settings import resolver_smtp_config

from app import db
from app.servicios import avisos as servicio
from app.tiempo import ahora


def main() -> int:
    db.inicializar()
    fabrica = db.fabrica_de_sesiones()
    transporte = servicio.TransporteEmail(lambda: resolver_smtp_config(fabrica))

    with fabrica() as sesion:
        resumen = servicio.despachar(sesion, transporte)
        sesion.commit()

    # Una línea por corrida, con fecha. El cron escribe a un log y lo que se
    # mira ahí es "esto corrió y cuándo": un script silencioso es
    # indistinguible de uno que no está en el crontab. Cuando el SMTP no está
    # configurado el resumen es todo ceros, que es la respuesta correcta y
    # también hay que poder verla.
    print(f"[{ahora():%d-%m-%Y %H:%M:%S}] avisos · {resumen}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
