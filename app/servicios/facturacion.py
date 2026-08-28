"""La facturación de LibraClub, compuesta sobre `libracore.db`.

Hoy sólo la **configuración de ARCA**: qué CUIT emite, con qué punto de venta y
con qué certificado. La emisión viene después — ver el pendiente de F3 en
`wiki/entities/libraclub.md`.

🔴 **`libracore.db` va contra su PROPIA base, no la del dominio.** No es una
preferencia: `init_core_schema()` crea `usuarios` y `auth_log`, y este producto
**ya tiene esas dos tablas** con la forma de `libraauth`. Compartiendo base el
`CREATE TABLE IF NOT EXISTS` no las pisaría —así que nada fallaría— y libracore
quedaría leyendo tablas con las columnas de otro motor. El síntoma sería un
error de columna inexistente en la primera factura, meses después.

Es el mismo arreglo que ya usan Gestiolibra, MedLibra y VentaLibra, donde
además `usuarios` vive del lado de LibraCore. Acá vive del lado del dominio, así
que la separación es al revés — pero la conclusión es la misma: dos bases.

> ⚠️ **Dos bases significa que el backup tiene que llevarse las dos.** Un backup
> de una sola no se puede restaurar: o volvés el dominio y te quedan facturas de
> otro momento, o al revés. Y no falla — da un ZIP que se descarga y pesa poco.
> Ver `_instancia_a_respaldar` en `app/main.py`.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from libracommerce.db.schema import init_schema as init_commerce_schema
from libracore import arca_facturacion, config_manager
from libracore.db import arca_config as db_arca_config
from libracore.db import caja as db_caja
from libracore.db import core as libracore_core
from libracore.db import facturas as db_facturas
from libracore.db.schema import init_core_schema

from app.servicios import buffet, caja
from app.tiempo import a_local

#: Una sola "empresa" ARCA: LibraClub es de instancia única por cliente
#: (arquitectura silo), así que no hay lista de empresas para elegir. Es una
#: constante y no una tabla, igual que en los tres verticales de la familia.
EMPRESA = "complejo"

#: Códigos de tipo de comprobante de ARCA.
FACTURA_A = 1
FACTURA_B = 6
FACTURA_C = 11

#: Códigos de condición de IVA del receptor que exige ARCA.
IVA_CODES = {
    "Responsable Inscripto": 1,
    "Monotributista": 6,
    "IVA Exento": 4,
    "Consumidor Final": 5,
}

_IVA = Decimal("0.21")


def tipo_de_comprobante(condicion_emisor: str | None) -> int:
    """Qué comprobante emite este complejo, según SU condición frente al IVA.

    🔴 **Un monotributista emite C, no B.** La lógica que la familia tiene hoy
    (`_tipo_comprobante` de Gestiolibra) sólo mapea A y B: devuelve **B** para
    todo lo que no sea Responsable Inscripto. Copiada tal cual acá, un complejo
    monotributista —que es el caso más probable, y el default de la config—
    emitiría el comprobante equivocado. No es un bug de pantalla: es fiscal.

    Decidido con el humano el 2026-08-21: se deriva del emisor.

    > ⚠️ **La A no se emite todavía, y falta un dato para poder hacerlo.** Un
    > Responsable Inscripto le emite A a otro RI y B al resto — y `Cliente` de
    > este producto **no tiene condición frente al IVA**, sólo CUIT. Sin ese
    > campo no se puede distinguir, así que un emisor RI emite siempre B. Emitir
    > B donde iba A le niega el crédito fiscal al cliente; agregar el campo es el
    > próximo paso si aparece un complejo RI.
    """
    return FACTURA_C if (condicion_emisor or "") != "Responsable Inscripto" else FACTURA_B


def importes(total: Decimal, tipo: int) -> tuple[Decimal, Decimal]:
    """Devuelve `(neto, iva)` para el total final.

    🔑 **Una Factura C no discrimina IVA**: el monotributista no lo cobra, así
    que el neto ES el total y el IVA va en cero. `_split_iva` de la familia parte
    siempre al 21% — correcto para A y B, y **mal para C**, donde inventaría un
    IVA que nadie pagó y dejaría el neto 21% por debajo del total.
    """
    if tipo == FACTURA_C:
        return total, Decimal("0.00")
    neto = (total / (Decimal("1") + _IVA)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return neto, total - neto


class FacturacionNoConfigurada(RuntimeError):
    """La instancia no tiene `LIBRACLUB_LIBRACORE_DATABASE_URL`.

    Se levanta al usar la facturación, **no al arrancar**: un complejo que
    todavía no factura tiene que poder levantar la aplicación igual.
    """


def configurar(database_url: str | None) -> bool:
    """Apunta `libracore.db` a su base y crea el schema. Devuelve si quedó lista.

    Idempotente: `init_core_schema` usa `CREATE TABLE IF NOT EXISTS`, así que
    llamarla en cada arranque no rompe nada.

    Sin URL no hace nada y devuelve `False` — la app levanta igual y lo único
    que no anda es la facturación.
    """
    global _hay_base
    if not database_url:
        _hay_base = False
        return False
    # 🔴 **Este producto corre sobre PostgreSQL y nada mas.** La guarda va aca,
    # en el arranque del producto, y no dentro de `libracore.db.core`: el motor
    # tiene que poder abrir un SQLite igual, porque de eso vive la herramienta
    # de diagnostico `python -m libracore.db.schema_dump`, que vuelca el schema
    # de un archivo viejo o de la base de LibraEdge --- la excepcion permanente
    # de la familia. La regla "este producto no habla con otro motor" es del
    # producto.
    if not libracore_core.es_url_postgres(database_url):
        raise RuntimeError(
            f"LibraClub factura solo contra PostgreSQL y recibio "
            f"{database_url!r}, que es una ruta de archivo. El modo SQLite se "
            "retiro el 2026-08-12: no chequea las FK, tipa dinamicamente y "
            "acepta cadenas donde la base pide enteros."
        )
    _crear_base_si_falta(database_url)
    libracore_core.configure(database_url)
    conexion = libracore_core.get_connection()
    try:
        init_core_schema(conexion)
        # 🔑 **El schema del buffet vive en LA MISMA base que LibraCore**, y no
        # en una tercera. Se verificó que **no colisiona ni una tabla**: las de
        # LibraCore están en castellano (`ventas`, `facturas`, `clients`) y las
        # de LibraCommerce en inglés (`sales`, `catalog_items`, `parties`).
        #
        # Van juntas porque las dos hablan el mismo dialecto —el API estilo
        # `sqlite3` que `libracore.db.core` traduce a PostgreSQL— y porque el
        # buffet **le cobra a la misma caja y le factura al mismo comprobante**
        # que la cancha. Separarlas obligaría a una transacción distribuida para
        # que una venta descuente stock y entre al turno a la vez.
        init_commerce_schema(conexion)
        conexion.commit()
    finally:
        conexion.close()
    # Una caja por defecto, que es lo que después necesita el cierre por turno.
    if db_caja.get_default_caja_id() is None:
        caja_id = db_caja.create_caja_config(
            "Caja del complejo", "", list(db_caja.MEDIOS_PAGO_LABELS),
        )
        db_caja.set_default_caja(caja_id)
    _hay_base = True
    return True


#: Si esta instancia tiene base de LibraCore. Lo fija `configurar()` al arrancar.
_hay_base = False


def hay_base() -> bool:
    return _hay_base


def _crear_base_si_falta(url: str) -> None:
    """Crea la base de LibraCore si no existe todavía.

    🔑 **Para que el deploy sea `git pull` + rebuild y nada más.** La alternativa
    era un paso manual (`createdb`) en la receta del README, al lado de
    `alembic upgrade head` — y un paso manual que se olvida acá **tira el
    contenedor al arrancar**, porque psycopg no se puede conectar a una base que
    no existe. Un producto que ya tiene dos bases no puede depender de que
    alguien se acuerde de crear la segunda.

    Es idempotente y no toca nada si la base ya está. Requiere que el usuario de
    la conexión pueda crear bases; en los composes de la familia es el
    `POSTGRES_USER` del propio contenedor, que sí puede.
    """
    import psycopg

    servidor, _, nombre = url.rpartition("/")
    nombre = nombre.split("?", 1)[0]
    if not nombre:
        return
    # `postgres` es la base de mantenimiento: existe siempre y no se toca.
    with psycopg.connect(f"{servidor}/postgres", autocommit=True) as conexion:
        existe = conexion.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (nombre,)
        ).fetchone()
        if not existe:
            # Sin parámetro: `CREATE DATABASE` no los acepta. El nombre sale de
            # una variable de entorno del operador, no de una request.
            conexion.execute(f'CREATE DATABASE "{nombre}"')


def obtener_config_arca() -> dict | None:
    return db_arca_config.obtener_arca_config(EMPRESA)


def guardar_config_arca(
    cuit: str, punto_venta: int, clave_path: str, certificado_path: str,
    ambiente: str = "homologacion",
) -> dict:
    """Crea o actualiza la configuración de ARCA de esta instancia.

    🔑 `ambiente` por default en `homologacion`: una instancia recién configurada
    **no** puede emitir contra producción por omisión. Pasar a `produccion` es un
    acto deliberado, no lo que pasa si alguien deja el campo como vino.
    """
    if obtener_config_arca() is None:
        db_arca_config.crear_arca_config(
            EMPRESA, cuit, punto_venta, clave_path, certificado_path, ambiente,
        )
    else:
        db_arca_config.actualizar_arca_config(
            EMPRESA, cuit=cuit, punto_venta=punto_venta,
            clave_path=clave_path, certificado_path=certificado_path,
            ambiente=ambiente,
        )
    return obtener_config_arca()


class ReservaYaFacturada(RuntimeError):
    """Esa reserva ya tiene comprobante.

    🔑 Se corta acá y no se deja emitir de nuevo: dos comprobantes por la misma
    reserva son dos veces el mismo ingreso ante ARCA, y no hay forma de anular
    uno sin nota de crédito. El reintento tras un error de ARCA es otro caso —
    ahí la factura existe **sin CAE** y lo que hay que reintentar es el CAE, no
    la emisión.
    """


class SinPrecio(RuntimeError):
    """La reserva no tiene precio: no hay nada que facturar."""


def _linea(descripcion: str, cantidad: Decimal, importe: Decimal, tipo: int) -> dict:
    """Una línea del comprobante, en la forma que espera el PDF de LibraCore.

    🔑 **`unit_price` y `subtotal` van en NETO, no en el precio de mostrador.**
    `_draw_items_table` recibe `iva_incluido` y le vuelve a sumar el IVA a cada
    línea cuando el receptor no discrimina. Poner el precio final acá lo
    duplicaría en el papel. En una C el neto ES el total, así que no se nota —
    y ése es justamente el motivo por el que hay que escribirlo: el día que un
    complejo emita B, el error aparecería en el comprobante y no en un test.
    """
    neto_total, _ = importes(importe, tipo)
    unitario = (neto_total / cantidad).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "description": descripcion,
        "qty": float(cantidad),
        "unit_price": float(unitario),
        "subtotal": float(neto_total),
        "iva_pct": 0 if tipo == FACTURA_C else float(_IVA * 100),
    }


def lineas_de_la_reserva(reserva, cancha_nombre: str, tipo: int) -> list[dict]:
    """La cancha y lo consumido en el buffet, como líneas del comprobante.

    🔑 **Ésta es la razón de ser de F4: UNA factura con las dos cosas.** El grupo
    juega y toma tres gaseosas; sale un comprobante con el alquiler y el consumo
    detallados por separado, que es lo que el cliente espera ver y lo que hace
    que el buffet no necesite su propia numeración fiscal.

    El detalle importa: una factura de $11.300 sin líneas obliga al cliente a
    creer en el número. Con líneas, lo puede verificar.
    """
    duracion = int((reserva.termina_at - reserva.comienza_at).total_seconds() // 60)
    lineas = [
        _linea(
            f"Alquiler de {cancha_nombre} — {a_local(reserva.comienza_at):%d-%m-%Y %H:%M}"
            f" ({duracion} min)",
            Decimal("1"),
            Decimal(str(reserva.precio)),
            tipo,
        )
    ]
    for consumo in buffet.lineas_para_factura(reserva.id):
        lineas.append(
            _linea(
                consumo.description_snapshot,
                Decimal(consumo.quantity),
                Decimal(consumo.quantity) * Decimal(consumo.unit_price),
                tipo,
            )
        )
    return lineas


async def facturar_reserva(reserva, cliente, cancha_nombre: str = "cancha") -> dict:
    """Emite el comprobante de una reserva **con su consumo de buffet** adentro.

    Una factura por reserva, emitida **cuando alguien la pide** — no por cada
    pago. Es el mismo diseño que MedLibra y Gestiolibra: si hubo seña, la seña y
    el saldo son dos movimientos de caja contra la MISMA factura, y la seña nunca
    genera comprobante propio.

    🔑 **El total incluye el buffet.** Lo que se consumió durante el turno se
    carga a la reserva (`servicios/buffet.py`) y sale como líneas de este mismo
    comprobante. Facturarlos por separado obligaría a dos comprobantes por un
    solo cobro, y a que el buffet queme numeración fiscal por cada gaseosa.

    ⚠️ **No registra movimiento de caja.** El cobro se registra en la caja del
    turno, que es donde el arqueo lo va a contar — ver `servicios/caja.py`.
    """
    if not hay_base():
        raise FacturacionNoConfigurada(
            "Falta LIBRACLUB_LIBRACORE_DATABASE_URL en esta instancia."
        )
    if reserva.precio is None or Decimal(str(reserva.precio)) <= 0:
        raise SinPrecio("La reserva no tiene precio cargado.")
    if reserva.factura_id is not None:
        raise ReservaYaFacturada(f"La reserva {reserva.id} ya tiene comprobante.")

    empresa = config_manager.load()
    tipo = tipo_de_comprobante(empresa.get("empresa_iva_condition"))
    lineas = lineas_de_la_reserva(reserva, cancha_nombre, tipo)
    # 🔴 **El total se suma DESDE las líneas, no desde `reserva.precio`.** Es la
    # diferencia entre un comprobante que cierra y uno que no: si el total
    # saliera del precio de la cancha, el buffet aparecería detallado en el
    # cuerpo y ausente del importe, y ARCA autorizaría un CAE por menos plata de
    # la que se cobró.
    total = Decimal(str(reserva.precio)) + buffet.total_consumido(reserva.id)
    neto, iva = importes(total, tipo)

    arca = obtener_config_arca()
    punto_venta = arca["punto_venta"] if arca else 1

    numero, ta, arca_usado = await arca_facturacion.get_next_numero_with_arca(
        punto_venta, tipo
    )
    factura_id = db_facturas.create_factura(
        tipo, punto_venta, numero, date.today().isoformat(),
        (cliente.cuit or "") if cliente else "",
        (cliente.nombre if cliente else "Consumidor Final"),
        # Sin campo de condición frente al IVA en `Cliente`, el receptor es
        # Consumidor Final. Ver la nota en `tipo_de_comprobante`.
        IVA_CODES["Consumidor Final"],
        lineas, float(neto), float(iva), float(total),
    )
    factura = db_facturas.get_factura(factura_id)
    factura = await arca_facturacion.solicitar_cae(factura_id, factura, ta, arca_usado)

    # 🔑 El vínculo se escribe DESPUÉS de emitir y lo commitea el caller. Si ARCA
    # falla, la factura queda creada sin CAE y la reserva **sin** `factura_id`:
    # el próximo intento la vuelve a emitir. Es preferible a dejarla marcada
    # apuntando a un comprobante sin CAE, que se vería como "ya facturada" y no
    # habría forma de reintentar desde la pantalla.
    reserva.factura_id = factura_id

    # 🔑 **Y se atan los cobros que ya estaban.** En un mostrador se cobra antes
    # de facturar tan seguido como después: sin esto, un turno cobrado en
    # efectivo el sábado y facturado el lunes deja el comprobante viéndose «sin
    # cobrar» sobre plata que ya entró. Ver `servicios/caja.py`.
    #
    # Va acá y no en el caller porque la condición es "esta reserva acaba de
    # conseguir su comprobante", que es justo lo que sabe esta línea.
    caja.vincular_cobros_a_factura(reserva.id, factura_id)
    return factura


def factura_de_reserva(reserva) -> dict | None:
    """El comprobante de una reserva, o `None` si todavía no se facturó."""
    if not hay_base() or reserva.factura_id is None:
        return None
    return db_facturas.get_factura(reserva.factura_id)
