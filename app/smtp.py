"""El SMTP efectivo de la instancia, en un solo lugar.

🔴 **Existe porque en la familia hubo DOS configuraciones de SMTP.** La de
libraauth --cifrada, la que escribe la pantalla de Configuración y la que manda
la recuperación de contraseña-- y la de `email_smtp_*` en `config.json`, que
era la que `libracore.facturas_router` leía para mandar comprobantes.

En LibraClub el segundo store **no lo escribe nadie**: la pantalla siempre
guardó en la base. O sea que hasta el 2026-08-30 mandar una factura por mail
fallaba con un 400 --"configurá el servidor SMTP"-- aunque la instancia tuviera
un SMTP perfectamente cargado y andando para los mails de contraseña.

Vive en su propio módulo y no en `app/main.py` porque el router de comprobantes
se arma **al importar** `app/routers/facturas.py`, antes de que corra el
arranque de la app.
"""
from libraauth.smtp_settings import resolver_smtp_config

from app import db


def smtp_config():
    """El SMTP a usar: el guardado en la base, o el del entorno si no hay.

    Se pasa **como callable**, nunca como valor: resuelto una sola vez, guardar
    el SMTP desde la pantalla no tendría efecto hasta recrear el contenedor.
    """
    return resolver_smtp_config(db.fabrica_de_sesiones())
