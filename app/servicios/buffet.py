"""El buffet: catálogo, stock y consumo cargado a la cancha.

Se apoya en [LibraCommerce] —el motor comercial de la familia— y no reimplementa
nada de catálogo ni de inventario: `CatalogItem`, `StockMovement` y `Sale` ya
existen y los prueba ese repo. Lo que decide este módulo es lo propio de un
complejo de canchas.

## El consumo se carga a la reserva

🔑 **Ésa es la diferencia con un POS de mostrador.** En VentaLibra la venta es un
hecho suelto; acá el grupo de las 20:00 pide tres gaseosas durante el partido y
paga todo junto al final. Por eso la venta lleva `source_type="reserva"` y
`source_id` = id de la reserva: es lo que después permite emitir **una sola
factura** con la cancha y el buffet como líneas separadas, que es el gate de F4.

Una venta **sin** reserva también existe —el que pasa y compra un agua— y es la
misma `Sale` con `source_type="mostrador"`.

## La venta nace por `registrar_venta` del motor (ADR-021)

El consumo se registra con `libracommerce.erp.ventas.crear_venta_directa`, la misma
puerta que usan ContaLibra, RestoLibra y VentaLibra, y no con un `save_sale` propio.
Es lo que hace que, en un nodo de LibraEdge, el outbox la vea: el motor llama a
`al_registrar_venta` y de ahí cuelga el encolado (`con_outbox`).

El vínculo con la reserva lo pone **el gancho** (`_vincular`): `registrar_venta` crea
la venta con `source_type='pos'` y el buffet la pasa a `'reserva'`/`'mostrador'` en
su `al_registrar_venta`, que `con_outbox` corre **antes** de encolar, así el payload
sale con el vínculo (ADR-072 de LibraCommerce). Los ganchos son por llamada
(`ganchos_del_consumo`) y no una constante, porque el vínculo es de ESTA venta.

La **caja no la escribe `registrar_venta`**: el buffet no le pasa pagos. La plata del
mostrador sigue entrando por `servicios/caja.py`, con su concepto y su referencia
`buffet-<id>`.

## El stock se descuenta al confirmar, y se permite quedar en negativo

`confirm_sale(validar_stock=False)` es el default del motor y acá se respeta:
*"en un mostrador negarse a cobrar porque el inventario está mal cargado es peor
que quedar en negativo — el cliente ya tiene el producto en la mano"*. El
negativo se ve en la pantalla de stock, que es donde hay que arreglarlo.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal

from libracommerce.domain.catalog import CatalogItem, CatalogItemType, Unit
from libracommerce.domain.inventory import Location, StockMovement, StockMovementType
from libracommerce.domain.sales import Sale, SaleItem, SaleStatus
from libracommerce.erp import Hooks
from libracommerce.erp.ventas import crear_venta_directa
from libracommerce.usecases.sales import confirm_sale
from libracore.db import core as libracore_core

from app.commerce import auditar_alta, repositorio
from app.tiempo import ahora

#: La unidad de todo lo que vende un buffet. No hay balanza acá: se venden
#: latas, botellas y alfajores, no 300 gramos de fiambre.
UNIDAD = Unit(code="u", name="Unidad")


class SinUbicacion(RuntimeError):
    """La sucursal no tiene depósito de buffet todavía."""


class ProductoInexistente(ValueError):
    pass


class VentaVacia(ValueError):
    """Una venta sin líneas no es una venta."""


def _repo():
    return repositorio()


def _conexion():
    """Para las pocas consultas que el repositorio del motor no ofrece.

    `list_sales` no existe en `CommerceRepository` —VentaLibra hace lo mismo con
    SQL propio—, así que las búsquedas por `source_id` y el correlativo salen de
    acá. Se abre aparte y no se toca `repo._conn`: ese atributo es interno del
    envoltorio de auditoría y no parte de su contrato.
    """
    return libracore_core.get_connection()


# ── Ubicaciones ──────────────────────────────────────────────────────────


def ubicacion_de(sucursal_id: int) -> Location:
    """El depósito del buffet de esa sucursal, creándolo si falta.

    🔑 **Una ubicación por sucursal, y no una sola global.** El stock es físico:
    las gaseosas de la sucursal Centro no las puede vender la de Norte. Con una
    ubicación única, el complejo de dos sedes vería un stock que no existe donde
    lo necesita.

    Se crea sola porque el operador no tiene por qué saber que "ubicación" es un
    concepto: abre la pantalla del buffet y carga productos.
    """
    repo = _repo()
    nombre = f"Buffet #{sucursal_id}"
    existente = next((u for u in repo.list_locations() if u.name == nombre), None)
    if existente is not None:
        return existente
    return repo.save_location(
        Location(
            id=None,
            name=nombre,
            branch_id=sucursal_id,
            location_type="warehouse",
            description="Depósito del buffet",
        )
    )


# ── Catálogo ─────────────────────────────────────────────────────────────


def listar_productos(*, incluir_inactivos: bool = False) -> list[CatalogItem]:
    return [
        i
        for i in _repo().list_catalog_items()
        if i.item_type is CatalogItemType.PRODUCT and (incluir_inactivos or i.active)
    ]


def guardar_producto(
    *,
    item_id: int | None,
    nombre: str,
    precio: Decimal,
    costo: Decimal = Decimal("0"),
    stock_minimo: Decimal = Decimal("0"),
    activo: bool = True,
) -> CatalogItem:
    """Alta o edición de un producto del buffet.

    `min_stock` es lo que después dispara el aviso de reposición. Se pide en el
    alta y no después porque un producto sin mínimo nunca avisa, y el faltante
    se descubre cuando el cliente lo pide.
    """
    repo = _repo()
    if item_id is not None:
        actual = repo.get_catalog_item(item_id)
        if actual is None:
            raise ProductoInexistente(f"No existe el producto {item_id}.")
        return repo.save_catalog_item(
            replace(
                actual,
                name=nombre,
                default_sale_price=precio,
                default_cost=costo,
                min_stock=stock_minimo,
                active=activo,
            )
        )
    return repo.save_catalog_item(
        CatalogItem(
            id=None,
            item_type=CatalogItemType.PRODUCT,
            name=nombre,
            unit=UNIDAD,
            default_sale_price=precio,
            default_cost=costo,
            min_stock=stock_minimo,
            active=activo,
        )
    )


# ── Stock ────────────────────────────────────────────────────────────────


def stock_de(sucursal_id: int) -> list[dict]:
    """Cada producto con lo que hay en esa sucursal y si está bajo el mínimo."""
    repo = _repo()
    ubicacion = ubicacion_de(sucursal_id)
    filas = []
    for item in listar_productos(incluir_inactivos=True):
        cantidad = repo.current_stock(item.id, ubicacion.id)
        filas.append(
            {
                "item_id": item.id,
                "nombre": item.name,
                "precio": item.default_sale_price,
                "activo": item.active,
                "stock": cantidad,
                "stock_minimo": item.min_stock,
                # 🔑 `<=` y no `<`: estar justo en el mínimo ya es el momento de
                # reponer. Con `<` el aviso llega recién cuando falta.
                "bajo_minimo": item.min_stock > 0 and cantidad <= item.min_stock,
            }
        )
    return filas


def ajustar_stock(
    *, sucursal_id: int, item_id: int, cantidad: Decimal, motivo: str, usuario_id: int | None
) -> Decimal:
    """Reposición o ajuste manual. `cantidad` negativa descuenta (rotura, vencido).

    Se registra como movimiento y no como un "stock actual" que se pisa: el
    stock de LibraCommerce **es la suma de los movimientos**, así que un ajuste
    deja rastro de quién lo hizo y por qué. Pisar un número no.
    """
    if cantidad == 0:
        raise ValueError("Un ajuste de cero no registra nada.")
    repo = _repo()
    ubicacion = ubicacion_de(sucursal_id)
    if repo.get_catalog_item(item_id) is None:
        raise ProductoInexistente(f"No existe el producto {item_id}.")
    repo.append_stock_movement(
        StockMovement(
            id=None,
            item_id=item_id,
            location_id=ubicacion.id,
            movement_type=(
                StockMovementType.PURCHASE if cantidad > 0 else StockMovementType.ADJUSTMENT
            ),
            quantity_delta=cantidad,
            occurred_at=ahora(),
            note=motivo,
            created_by=usuario_id,
        )
    )
    return repo.current_stock(item_id, ubicacion.id)


# ── Ventas ───────────────────────────────────────────────────────────────


def _numero_de_venta(conexion) -> str:
    """`BUF-000123`. Correlativo propio del buffet.

    No usa la numeración de comprobantes de ARCA: una venta de buffet **no es un
    comprobante fiscal**. El comprobante sale después y puede juntar varias
    ventas con la cancha, así que atarle la numeración fiscal a cada consumo
    quemaría números por cada gaseosa.

    🔑 **Sigue al último `BUF-` aunque lleve prefijo de nodo** (`S02-BUF-000007`):
    `con_outbox` le antepone al número del producto el prefijo del nodo, y una
    venta que subió de un nodo llega al central con él. Buscar sólo `BUF-%`
    volvería a numerar desde 1 en el nodo —y chocaría con la suya— y en el
    central ignoraría lo que ya subió.

    Es también el `numerador` del motor (corre con la conexión de la venta, con
    el write-lock tomado): si dos ventas simultáneas eligen el mismo número,
    `crear_venta_directa` reintenta la perdedora en una transacción nueva.
    """
    fila = conexion.execute(
        "SELECT number FROM sales WHERE number LIKE '%BUF-%' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    proximo = int(fila[0].rsplit("-", 1)[1]) + 1 if fila else 1
    return f"BUF-{proximo:06d}"


def _sin_turno(conn, usuario_id):
    """El buffet no ata sus ventas al turno por `venta_links`: la plata va por `servicios/caja.py`."""
    return None


#: Los ganchos del buffet sin el vínculo de ninguna venta: el numerador propio y nada de turno.
#: Es lo que debe usar el **central** para aplicar lo que sube de un nodo (`registrar_en(...)`): ahí el
#: vínculo ya viene en el payload, y un gancho que lo rehiciera lo pisaría.
GANCHOS_PROPIOS = Hooks(numerador=_numero_de_venta, turno_para=_sin_turno)


def _vincular(reserva_id: int | None):
    """El `al_registrar_venta` del buffet para UNA venta: el vínculo y el alta en el log.

    🔑 `registrar_venta` crea la venta con `source_type='pos'` y no recibe un origen (ADR-072 de
    LibraCommerce: «el producto lo pone en su `al_registrar_venta`»). Acá se le pone `'reserva'` +
    `source_id=<reserva>` o `'mostrador'`, que es lo que leen `consumos_de_reserva` y la factura conjunta.
    Corre dentro de la transacción de la venta y, con `con_outbox`, **antes** de encolar: el payload que sube
    ya trae el vínculo.

    El alta en `actividad_log` también va acá: el repositorio auditado la dejaba al guardar la `Sale`, y
    `registrar_venta` escribe por SQL, fuera de ese envoltorio. Misma conexión: o están las dos cosas o ninguna.
    """
    origen = "reserva" if reserva_id is not None else "mostrador"
    id_origen = int(reserva_id) if reserva_id is not None else None

    def al_registrar_venta(conn, venta) -> None:
        conn.execute(
            "UPDATE sales SET source_type = ?, source_id = ? WHERE id = ?", (origen, id_origen, venta["id"])
        )
        auditar_alta(conn, "sales", venta["id"], {
            "number": venta["numero"], "status": venta["status"], "total": venta["total"],
            "source_type": origen, "source_id": id_origen,
        })

    return al_registrar_venta


def ganchos_del_consumo(reserva_id: int | None) -> Hooks:
    """Los ganchos con los que se registra el consumo de `reserva_id` (o el de mostrador, con `None`).

    Es el punto donde el nodo engancha el outbox: `con_outbox(ganchos_del_consumo(reserva_id), OUTBOX)`.
    """
    return replace(GANCHOS_PROPIOS, al_registrar_venta=_vincular(reserva_id))


def _congelar_lineas(lineas: list[tuple[int, Decimal]]) -> list[tuple[CatalogItem, Decimal]]:
    """Cada `(item_id, cantidad)` con su producto, validado. El precio se lee de ese producto, ahora.

    Es lo que comparten los dos finales del consumo (el borrador del QR y la venta en el acto): duplicarlo
    sería duplicar el congelamiento de precios, que es la parte que no se puede equivocar.
    """
    if not lineas:
        raise VentaVacia("No hay nada cargado.")
    repo = _repo()
    resultado = []
    for item_id, cantidad in lineas:
        producto = repo.get_catalog_item(item_id)
        if producto is None:
            raise ProductoInexistente(f"No existe el producto {item_id}.")
        if cantidad <= 0:
            raise ValueError(f"La cantidad de {producto.name} tiene que ser positiva.")
        resultado.append((producto, Decimal(cantidad)))
    return resultado


def _armar_venta(
    *,
    sucursal_id: int,
    lineas: list[tuple[int, Decimal]],
    usuario_id: int | None,
    cliente_nombre: str,
) -> Sale:
    """La venta de mostrador en borrador, sin guardar y sin tocar stock.

    Sólo la usa `preparar_consumo`: el borrador que espera que alguien escanee el QR. El consumo en el acto
    (`registrar_consumo`) no pasa por acá: lo arma el motor.
    """
    items = [
        SaleItem(
            kind=CatalogItemType.PRODUCT,
            description_snapshot=producto.name,
            quantity=cantidad,
            unit_price=producto.default_sale_price,
            item_id=producto.id,
            unit_cost_snapshot=producto.default_cost,
        )
        for producto, cantidad in _congelar_lineas(lineas)
    ]
    total = sum((i.quantity * i.unit_price for i in items), Decimal("0"))
    conexion = _conexion()
    try:
        numero = _numero_de_venta(conexion)
    finally:
        conexion.close()
    return Sale(
        id=None,
        number=numero,
        items=tuple(items),
        status=SaleStatus.DRAFT,
        branch_id=sucursal_id,
        source_type="mostrador",
        source_id=None,
        subtotal=total,
        total=total,
        customer_name_snapshot=cliente_nombre,
        created_by=usuario_id,
        occurred_on=ahora().date().isoformat(),
    )


def preparar_consumo(
    *,
    sucursal_id: int,
    lineas: list[tuple[int, Decimal]],
    usuario_id: int | None,
    cliente_nombre: str = "",
) -> Sale:
    """La venta de mostrador **en borrador**: guardada, sin mover stock.

    🔴 **Es lo que hace que un QR que nadie escanea no deje rastro.** El cobro
    con QR necesita un id y un total *antes* de que el cliente pague —la
    referencia que viaja a MercadoPago sale de ahí— pero descontar el stock ahí
    sería descontarlo por una venta que puede no ocurrir nunca: el cliente se va,
    la app le falla, se arrepiente. El borrador se queda quieto y el stock se
    mueve recién en `confirmar_consumo`, cuando la plata entró.

    Lo único que sí consume es un **número** de la serie `BUF-`: un QR abandonado
    deja un hueco en la numeración. Es aceptable a propósito — no es numeración
    fiscal (ver `_numero_de_venta`), y la alternativa es numerar al confirmar, o
    sea que el número dependa del orden en que paguen dos clientes.
    """
    venta = _armar_venta(
        sucursal_id=sucursal_id,
        lineas=lineas,
        usuario_id=usuario_id,
        cliente_nombre=cliente_nombre,
    )
    return _repo().save_sale(venta)


def confirmar_consumo(venta_id: int) -> Sale:
    """Confirma un borrador de `preparar_consumo`: acá recién se mueve el stock.

    🔑 **Idempotente**, y no por prolijidad: la llama el poll del QR, que corre
    cada 3 segundos y puede pegarle dos veces al mismo pago aprobado. Una venta
    ya confirmada se devuelve tal cual — `confirm_sale` del motor levantaría
    `ValueError` y el segundo tick se vería como un error del cobro.

    🔴 **La sucursal sale de la venta y no del caller**, a propósito: el stock es
    físico y por sucursal (ver `ubicacion_de`), así que un caller que pase la
    equivocada descuenta las gaseosas del depósito de la otra sede. La venta ya
    sabe de dónde salió; preguntárselo a otro es abrir la puerta a que no
    coincidan.
    """
    venta = _repo().get_sale(venta_id)
    if venta is None:
        raise ProductoInexistente(f"No existe la venta {venta_id}.")
    if venta.status is not SaleStatus.DRAFT:
        return venta
    if venta.branch_id is None:
        raise ValueError(f"La venta {venta_id} no tiene sucursal: no se sabe qué stock mover.")
    return confirm_sale(_repo(), venta, ubicacion_de(venta.branch_id).id, ahora())


def registrar_consumo(
    *,
    sucursal_id: int,
    lineas: list[tuple[int, Decimal]],
    usuario_id: int | None,
    reserva_id: int | None = None,
    cliente_nombre: str = "",
) -> Sale:
    """Una venta del buffet. Descuenta stock y queda lista para facturar.

    `lineas` son `(item_id, cantidad)`. El **precio se congela acá**, con el
    precio de lista del momento: si mañana sube la gaseosa, el consumo de ayer
    no cambia de importe. Es el mismo criterio que la reserva.

    Con `reserva_id` la venta queda colgada de esa reserva y entra en su factura;
    sin él es una venta de mostrador que se factura sola.

    ⚠️ **No registra movimiento de caja.** El consumo cargado a una reserva se
    cobra cuando se cobra la reserva; el de mostrador, en la pantalla del buffet.
    Anotar la plata acá la contaría dos veces.
    """
    items = []
    for producto, cantidad in _congelar_lineas(lineas):
        items.append({
            "producto_id": producto.id, "nombre": producto.name,
            "qty": cantidad, "precio": producto.default_sale_price,
        })
    total = sum((i["qty"] * i["precio"] for i in items), Decimal("0"))
    ubicacion = ubicacion_de(sucursal_id)
    venta_id = crear_venta_directa(
        libracore_core.get_connection,
        fecha=ahora().date().isoformat(),
        items=items,
        subtotal=total,
        descuento=Decimal("0"),
        total=total,
        cliente_id=None,
        cliente_nombre=cliente_nombre,
        usuario_id=usuario_id,
        observaciones="",
        estado="cobrada",
        # Sin pagos: la caja no la escribe el motor (ver el docstring de arriba).
        pagos=[],
        stock_habilitado=True,
        hooks=ganchos_del_consumo(reserva_id),
        # El depósito del buffet de ESA sucursal: de ahí sale el stock y de ahí sale `sales.branch_id`.
        deposito_id=ubicacion.id,
        guardar_costo=True,
    )
    return _repo().get_sale(venta_id)


def consumos_de_reserva(reserva_id: int) -> list[Sale]:
    """Las ventas del buffet cargadas a esa reserva, con sus líneas."""
    repo = _repo()
    conexion = _conexion()
    try:
        filas = conexion.execute(
            "SELECT id FROM sales WHERE source_type = 'reserva' AND source_id = ? "
            "AND status <> 'cancelled' ORDER BY id",
            (int(reserva_id),),
        ).fetchall()
    finally:
        conexion.close()
    return [repo.get_sale(f[0]) for f in filas]


def total_consumido(reserva_id: int) -> Decimal:
    return sum((v.total for v in consumos_de_reserva(reserva_id)), Decimal("0"))


def consumido_de_reservas(reserva_ids: Sequence[int]) -> dict[int, Decimal]:
    """Lo mismo que `total_consumido`, pero de muchas reservas y en una consulta.

    🔑 **Existe por el costo, no por prolijidad.** `total_consumido` pasa por
    `consumos_de_reserva`, que abre una conexión y despues llama a
    `repo.get_sale()` **por cada venta** para armar sus líneas. En el detalle de
    una reserva eso es una vez; en el listado del mostrador serían decenas de
    conexiones por refresco, y las líneas ni se usan: sólo hace falta el total.
    """
    ids = [int(x) for x in reserva_ids]
    if not ids:
        return {}
    marcas = ",".join("?" * len(ids))
    conexion = _conexion()
    try:
        filas = conexion.execute(
            "SELECT source_id, SUM(total) FROM sales"
            " WHERE source_type = 'reserva' AND status <> 'cancelled'"
            f" AND source_id IN ({marcas})"
            " GROUP BY source_id",
            tuple(ids),
        ).fetchall()
    finally:
        conexion.close()
    return {int(f[0]): Decimal(str(f[1] or 0)) for f in filas}


def lineas_para_factura(reserva_id: int) -> list[SaleItem]:
    """Las líneas de buffet de una reserva, aplanadas para el comprobante."""
    return [linea for venta in consumos_de_reserva(reserva_id) for linea in venta.items]


def venta_por_id(venta_id: int) -> Sale | None:
    return _repo().get_sale(venta_id)


def ventas_de_mostrador(limite: int = 50) -> list[dict]:
    """Las últimas ventas sueltas, para la pantalla del buffet."""
    conexion = _conexion()
    try:
        filas = conexion.execute(
            "SELECT id, number, total, occurred_on, customer_name_snapshot, "
            "       source_type, source_id "
            "FROM sales WHERE status <> 'cancelled' ORDER BY id DESC LIMIT ?",
            (limite,),
        ).fetchall()
    finally:
        conexion.close()
    return [
        {
            "id": f[0],
            "numero": f[1],
            "total": Decimal(str(f[2] or 0)),
            "fecha": f[3],
            "cliente": f[4] or "",
            "reserva_id": f[6] if f[5] == "reserva" else None,
        }
        for f in filas
    ]
