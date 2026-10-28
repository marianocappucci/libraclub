#!/usr/bin/env python
"""Manda las confirmaciones, los recordatorios, las cancelaciones y los avisos de seña por vencer. Lo corre el cron.

🔴 **Este script ES el interruptor de los avisos.** No hay un `avisos_activos`
en la config, a propósito: dos interruptores para lo mismo terminan en
desacuerdo, y el día que el dueño diga «no me manda los mails» habría que
adivinar cuál de los dos está apagado. Sin el cron no sale nada; con el cron
puesto y el SMTP cargado, sale.

Corre cada 5 minutos. Es la granularidad de la confirmación —el que reserva a
las 20:00 recibe el mail a más tardar 20:05— y no importa para los
recordatorios, que se miden en horas.

    */5 * * * * docker exec libraclub-dev python /app/scripts/enviar_avisos.py \
        >> /var/log/libraclub_avisos.log 2>&1

Instalado en `dev` el 2026-08-29. El log va además a la lista explícita de
`/etc/logrotate.d/libra-crons`: sin eso crece sin techo, a 288 corridas por día.

⚠️ **Si el cron estuvo caído más de dos horas, las confirmaciones de esa ventana
no salen.** Es deliberado: la ventana es lo que impide que la primera corrida le
escriba a todos los clientes por todos los turnos futuros ya cargados. Ver
`VENTANA_DE_CONFIRMACION` en `servicios/avisos.py`.

## Cómo sale (ADR-030)

Qué corresponde avisar lo deduce `servicios/avisos.py`; **cómo sale** —mail por el SMTP de la instancia, WhatsApp
apagado, en registro o por Evolution— es del motor (`libracore.avisos`, ADR-090), que además reserva cada aviso en
`avisos_envios` antes de mandarlo: dos corridas superpuestas no mandan lo mismo dos veces.

**Un aviso, un canal** (addendum de ADR-030, 2026-10-28): hay **un solo barrido** con los dos canales a la vez, no
uno por canal. Cada aviso sale por WhatsApp si el cliente tiene un teléfono válido y WhatsApp está disponible
(registro o Evolution); si no, por mail, y por mail también si WhatsApp lo da por perdido. Lo que ya salió por un
canal no sale por el otro aunque la configuración haya cambiado entre dos corridas. El log dice qué canales estaban
disponibles y el resumen de lo que pasó.

🔴 **El almacén de secretos tiene que estar enchufado antes de despachar.** La `apikey` de Evolution vive cifrada ahí y
el cron corre por `docker exec`, sin el arranque de la app: sin el almacén, WhatsApp "no tiene credencial" y no manda
(`configuracion.motivo_de_whatsapp()` lo dice). Por eso se importa `app.asgi`, que es lo que levanta el contenedor y
enchufa el almacén, como `sync_mp_auto.py` (mismo criterio; lo vigila `tests/test_secretos_config_json.py`).

**No llama a `reintentar_fallidos`, a propósito.** El barrido ya reintenta los `fallido` (siguen siendo candidatos hasta
agotar los intentos) y lo hace *con la regla de cada aviso*: no manda el recordatorio de un turno que ya empezó ni el
«se libera en 8 minutos» de una seña que ya se liberó. `reintentar_fallidos` reenvía el mensaje guardado hasta 24 horas
después sin mirar eso, y está pensado para quien no tiene un barrido que repita la consulta.
"""

from __future__ import annotations

import os
import sys

# 🔴 Este script corre POR RUTA desde el cron, así que `sys.path[0]` es `/app/scripts` y no `/app`: sin esto no
# encuentra el paquete `app`. En el resto del repo el insert no hace falta —el paquete está instalado—, y acá es lo
# único que sostiene el import.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 🔴 `app.asgi` es lo que levanta el contenedor: `crear_app()` inicializa la base, configura la de LibraCore y enchufa
# el almacén cifrado de secretos, donde vive la apikey de Evolution. Sin esto el cron corre sin ese arranque, lee la
# apikey vacía y WhatsApp no manda. Importar el arranque, no rearmarlo (como `sync_mp_auto.py`).
import app.asgi  # noqa: E402,F401
from app import db  # noqa: E402
from app.servicios import avisos as servicio  # noqa: E402
from app.smtp import smtp_config  # noqa: E402
from app.tiempo import ahora  # noqa: E402


def main() -> int:
    fabrica = db.fabrica_de_sesiones()

    with fabrica() as sesion:
        # Los dos canales juntos: el SMTP de la instancia y el WhatsApp que diga el motor (apagado, registro o
        # Evolution). `barrer` elige por cuál sale cada aviso (uno solo). El barrido sólo lee las reservas; lo que
        # se anota lo escribe el motor en `avisos_envios`, y cada paso se confirma solo.
        proveedores = servicio.construir_proveedores(smtp_config)
        resumen = servicio.barrer(sesion, proveedores)
        canales = [canal for canal, p in proveedores.items() if p.disponible()]

    # Una línea por corrida, con fecha. El cron escribe a un log y lo que se
    # mira ahí es "esto corrió y cuándo": un script silencioso es
    # indistinguible de uno que no está en el crontab. Cuando el SMTP no está
    # configurado y WhatsApp está apagado el resumen es todo ceros, que es la
    # respuesta correcta y también hay que poder verla: por eso dice qué canales había.
    print(f"[{ahora():%d-%m-%Y %H:%M:%S}] avisos · canales: {', '.join(canales) or 'ninguno'} · {resumen}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
