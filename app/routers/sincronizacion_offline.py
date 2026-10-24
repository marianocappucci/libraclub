"""El central expone la sincronización del nodo offline: `/sync/v1/push`, `/pull`, `/ticket-arca` y `/carga-inicial`.

PR 11 del plan «LibraCargo y LibraClub en la versión de escritorio» (ADR-023). Es el mismo armado que VentaLibra
(ADR-090), con las operaciones de LibraClub.

## Por qué se monta siempre, y no sólo en las instancias con nodos

El gateo está del otro lado: sin un nodo registrado **no existe ningún secreto válido**, así que en una instancia sin
nodos las rutas responden 401 a todo. Montarlas condicionalmente agregaría una bandera más que puede quedar mal
puesta, y el modo de fallar sería el peor posible: un nodo instalado que no puede sincronizar contra un central que
«debería» tener el endpoint.

## La conexión es por request

Se le pasa `libracore.db.core.get_connection` —la fábrica del motor— y no una conexión armada: el router abre una por
request (ver `create_sync_router` en LibraEdge). En LibraClub el dominio y LibraCore son la misma base (ADR-020), así
que esa conexión ve `reservas`, `sales` y `node_identity` a la vez.

## Qué se aplica

Un `Despachador` (libraedge ADR-007) con **todas** las operaciones que un nodo de LibraClub sube
(`servicios/factura_del_nodo.armar_despachador`):

| Operación | De quién es | Qué trae |
|---|---|---|
| `venta.registrada`, `venta.pago_acreditado`, `venta.anulada`, `venta.devolucion`, `venta.facturada` | LibraCommerce
| la venta del buffet, con el vínculo a la reserva traducido (`tablas_de_origen`) |
| `turno.abierto`, `turno.cerrado`, `caja.movimiento`, `caja.movimiento_anulado`, `dia.cerrado` | LibraCommerce | la
caja: el cobro del buffet y el de una reserva |
| `cliente.alta` | LibraCommerce | (registrado por el motor; LibraClub no da clientes de la ERP en el nodo) |
| `stock.movimiento`, `compra.recibida` | LibraCommerce | la reposición y los ajustes del buffet |
| `cola.pedido` | LibraCore | el estado de un pedido de la cola de ARCA (la web consulta) |
| `club.factura_conjunta` | LibraClub | la factura de una reserva con sus consumos, con su número y CAE |
| `reserva.creada`, `reserva.estado` | LibraClub (PR 12, ADR-022) | las reservas que se dieron en el nodo |

Lo que no tiene aplicador **no se marca aplicado**: va a revisión manual (`libraedge-central revision
listar|reintentar|descartar`, con `LIBRAEDGE_DESPACHADOR=app.routers.sincronizacion_offline:despachador`).

El router además controla la versión del esquema (`version_de_alembic`: 409 si el nodo no está migrado igual que el
central) y le presta al nodo el ticket de ARCA (`libracore.nodo_offline.ta_para_el_nodo`, libraedge ADR-009 y
ADR-025): la clave no sale del VPS. LibraClub no tiene `wscpe`: pedirlo es 501.
"""

from libracommerce.erp.offline_stock import carga_inicial_del_central
from libracore.db.core import get_connection
from libracore.nodo_offline import ta_para_el_nodo
from libraedge.sync.api import create_sync_router
from libraedge.sync.esquema import version_de_alembic

from app.servicios import factura_del_nodo


def registrar_reservas(despachador) -> None:
    """Registra `reserva.creada` y `reserva.estado` (PR 12, ADR-022) en el despachador del central.

    Las escribe `servicios/reservas_nodo.py`: su aplicador crea la reserva con su id, anota el mapeo `(nodo, 'reservas',
    id provisorio) -> id` y, si chocó con otra que llegó antes, la deja `en_conflicto`. Es lo que después usan la venta
    del buffet (`source_id`), el cobro (la referencia) y la factura conjunta de esa reserva para traducir su id."""
    from app.servicios import reservas_nodo

    reservas_nodo.registrar_en(despachador)


def armar_despachador():
    """Las operaciones que el central de LibraClub sabe aplicar (ver el docstring del módulo)."""
    return factura_del_nodo.armar_despachador(registrar_reservas)


despachador = armar_despachador()

router = create_sync_router(
    get_connection, despachador=despachador, version_esquema=version_de_alembic,
    prestar_ticket=ta_para_el_nodo,
    # `GET /sync/v1/carga-inicial` (libraedge ADR-023, libracommerce ADR-071): las existencias de la sucursal del
    # nodo, que trae al vincular (el stock del depósito del buffet). Autenticada con el secreto del nodo, como push y
    # pull.
    carga_inicial=carga_inicial_del_central,
)
