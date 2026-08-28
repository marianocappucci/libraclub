"""La bandeja de MercadoPago: conciliar lo que entró y facturarlo.

Es la pantalla del motor (`libracore.mp_bandeja_router`), la misma que usan
[[contalibra]] y [[restolibra]]. Acá se arma con lo único que es de este
producto: **qué pagos NO le pertenecen**.

## 🔑 El reparto por `external_reference`

Este complejo cobra por MercadoPago de dos maneras, y las dos marcan sus pagos
con una referencia que arranca en `lc-`:

- la seña del portal público, cuando un jugador reserva desde internet;
- el QR del mostrador, cuando el encargado cobra un turno.

Esos dos los atiende el webhook del producto (`POST /api/portal/webhook`), que
confirma la reserva y —si está prendida la automática— emite la factura. **No
tienen que entrar a la bandeja**: ya están resueltos, y mostrarlos ahí sería
pedirle a alguien que concilie dos veces el mismo cobro.

Lo que sí entra es todo lo demás: una transferencia que le hicieron al complejo,
un pago suelto, un cobro que no salió de un turno. Hoy eso **se pierde** — el
webhook lo mira, no reconoce la referencia y contesta 200 sin registrar nada.

> ⚠️ **El prefijo `lc-` tiene que seguir coincidiendo con
> `servicios/pagos.nueva_referencia`.** Si esa función cambiara de formato, acá
> quedaría un filtro que no matchea y los pagos de reservas empezarían a
> aparecer en la bandeja como si nadie los hubiera resuelto. Hay un test que ata
> las dos puntas.
"""

from libracore.mp_bandeja_router import build_mp_bandeja_router

from app.servicios.pagos import PREFIJO_DE_REFERENCIA

#: Los prefijos que la bandeja **no** trae, porque el producto ya los resuelve.
REFERENCIAS_PROPIAS = (PREFIJO_DE_REFERENCIA,)

router = build_mp_bandeja_router(
    prefix="/api/mp-bandeja",
    referencias_a_omitir=REFERENCIAS_PROPIAS,
)
