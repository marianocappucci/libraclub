"""`GET`/`PUT /config/mercadopago` — con qué cuenta cobra el QR del mostrador.

El prefijo va sin `/api`, igual que `/config/arca`: es la convención de las
pantallas de configuración que comparte la familia. Ver la nota en
`routers/facturacion.py`.

🔑 **Admin, no staff.** Quien pueda escribir acá cambia a qué cuenta de
MercadoPago va la plata del complejo. El encargado del mostrador cobra; qué
cuenta cobra es del dueño.

Las credenciales viven en el `config.json` de LibraCore —el mismo lugar donde el
webhook del portal ya lee `mp_access_token` y `mp_webhook_secret`— y no en una
tabla propia. No hay una segunda copia de esto en el producto.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.servicios import cobro_qr

router = APIRouter(prefix="/config/mercadopago", tags=["mercadopago"])


class ConfigEntrada(BaseModel):
    #: El de la aplicación de MercadoPago del complejo. Firma todas las
    #: llamadas a su API, incluida la consulta del pago que hace el webhook.
    access_token: str = ""
    #: El **collector id** de la cuenta: el `id` que devuelve `GET /users/me`.
    #: Va en la URL de la orden, no en un header.
    user_id: str = ""
    #: El **external_id** de la caja creada en MercadoPago, no su nombre ni su
    #: id numérico. Una caja sin `external_id` cargado no es direccionable por
    #: esta API, y el síntoma es un 404 que no dice eso.
    pos_id: str = ""
    #: La firma del webhook. Sin esto el webhook del portal **no procesa nada**:
    #: procesar sin verificar sería dejar que cualquiera confirme reservas.
    webhook_secret: str = ""
    #: Si al acreditarse el cobro del mostrador se emite la factura sola.
    auto_facturar: bool = False


class ConfigSalida(ConfigEntrada):
    #: Si las tres credenciales del QR están cargadas. Se calcula acá y no en la
    #: pantalla para que sea el mismo criterio que usa el mostrador
    #: (`cobro_qr.esta_configurado()`) y no dos reglas que puedan divergir.
    configurado: bool = False


def _salida(cfg: dict) -> ConfigSalida:
    return ConfigSalida(
        access_token=str(cfg.get("mp_access_token") or ""),
        user_id=str(cfg.get("mp_user_id") or ""),
        pos_id=str(cfg.get("mp_pos_id") or ""),
        webhook_secret=str(cfg.get("mp_webhook_secret") or ""),
        auto_facturar=bool(cfg.get("mp_auto_facturar_reservas")),
        configurado=cobro_qr.esta_configurado(),
    )


@router.get("", response_model=ConfigSalida)
def obtener() -> ConfigSalida:
    """Devuelve el token en claro, igual que Contalibra: el router entero es
    admin-only y sin devolverlo la pantalla obligaría a retipearlo entero cada
    vez que cambia el POS ID. El frontend lo muestra como campo de contraseña."""
    return _salida(cobro_qr.cargar_config())


@router.put("", response_model=ConfigSalida)
def guardar(datos: ConfigEntrada) -> ConfigSalida:
    """Guarda las credenciales.

    🔴 **Se carga la config entera, se actualizan las cinco claves y se
    guarda.** `config_manager.save()` mergea contra los DEFAULTS, así que
    guardar un dict con sólo estas cinco dejaría el resto de `config.json`
    —empresa, SMTP, ARCA— en su valor por defecto. Es un borrado silencioso: el
    PUT contesta 200 y lo que se perdió recién se nota cuando alguien va a
    emitir un comprobante.
    """
    cfg = cobro_qr.cargar_config()
    cfg.update({
        "mp_access_token": datos.access_token.strip(),
        "mp_user_id": datos.user_id.strip(),
        "mp_pos_id": datos.pos_id.strip(),
        "mp_webhook_secret": datos.webhook_secret.strip(),
        "mp_auto_facturar_reservas": datos.auto_facturar,
    })
    cobro_qr.guardar_config(cfg)
    return _salida(cobro_qr.cargar_config())
