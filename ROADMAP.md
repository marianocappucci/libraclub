# Roadmap

Cada fase tiene un **gate**: lo que hay que poder demostrar para darla por
cerrada. Un gate no es "los tests pasan" — es algo que se hace y se mira.

## F0 — Discovery *(no ejecutada)*

Entrevistar a dueño, encargado y cajero de al menos tres complejos: de dónde
vienen las reservas hoy (WhatsApp, teléfono, planilla), no-shows, señas y
devoluciones, tarifas por franja, reservas fijas, clases y torneos, bloqueos,
medios de pago, caja por turno, buffet y facturación por CUIT.

**Se saltea a propósito.** El producto arranca como inversión, sin piloto
comprometido: el grupo de cinco complejos que motivó el análisis descartó las
reservas el 2026-08-20. La consecuencia es explícita — **las reglas de negocio
de F1 son supuestos, no relevamiento**, y hay que tratarlas como tales cuando
aparezca el primer complejo real.

Gate: tres complejos relevados y métricas base medidas.

## F1 — Fundación *(en curso)*

Sucursales, canchas, tarifas, clientes, permisos, calendario semanal, reserva,
bloqueo, cancelación y reservas fijas recurrentes. Auditoría de quién tocó qué.

**Gate: cero doble reserva bajo concurrencia.** No "el test de solapamiento pasa"
— dos transacciones simultáneas peleando por la misma cancha, y una sola gana.

## F2 — Reservas con seña

Portal público responsive del complejo: disponibilidad, reserva con seña por
Mercado Pago, hold con vencimiento, confirmaciones, recordatorios,
cancelaciones con política y marcado de ausente.

Gate: un circuito completo con pago real, devolución y ausente — no una demo con
la pantalla abierta.

> El hold con vencimiento y el constraint de exclusión ya están en F1
> justamente para que esta fase no tenga que inventarlos.

**Confirmaciones, recordatorios y aviso de cancelación: hechos** (2026-08-29,
ADR-015), por email y con el SMTP que ya configura la pantalla de Correo. Los
manda `scripts/enviar_avisos.py` desde el cron, y **ese cron es el interruptor**.

**La política de cancelación: hecha** (2026-08-29, ADR-016). Ventana por
sucursal, devolución automática de la seña por MercadoPago cuando se cancela a
tiempo, y la deuda anotada y reintentable cuando la devolución falla.

**Aviso de seña por vencer: hecho** (2026-10-28, ADR-029) para el turno que
retiene el portal mientras se paga. La reserva `pendiente_pago` del mostrador no
vence hoy, así que no hay qué avisar: falta decidir el plazo de la seña.

Lo que sigue abierto de esta fase, en orden:

1. **El ausentismo**: `AUSENTE` existe como estado y se puede marcar, pero no se
   cuenta por cliente ni bloquea al reincidente. Es lo que ATC vende como tarjeta
   en garantía y Dónde Juego como lista negra.
2. **WhatsApp** como segundo canal. **Hecho en el motor y adoptado** (2026-10-28, ADR-030): el aviso sale por
   `libracore.avisos` (apagado, en registro o por Evolution API) y la pantalla «Avisos» lo conecta con los
   componentes del kit. **Falta** conectar una instancia real de Evolution (URL, instancia y apikey, desde la
   pantalla) y decidir si se suma la API de Meta, que pide plantillas aprobadas (el contrato del motor ya las
   admite).
3. **El aviso de cancelación no dice qué pasó con la seña.** El portal sí se lo
   dice al jugador en el momento de cancelar —que es cuando más le importa— pero
   el mail que sale después no lo repite. Para hacerlo, `redactar` tendría que
   mirar el pago, y hoy es una función pura que sólo recibe la reserva: es un
   cambio de forma, no una línea más de texto.
4. **La devolución de un cobro de mostrador**, que hoy queda dicha y no hecha:
   ese pago ya entró a la caja, así que devolverlo es un egreso de caja y no una
   llamada a la API. Necesita decidirse junto con el arqueo.

## F3 — Caja y factura

Caja por sucursal, conciliación de la reserva contra el cobro, punto de venta
de ARCA por sucursal y emisión directa con `libracore.arca_facturacion`
(ADR-007). El puente a ContaLibra queda como opción de configuración.

Gate: reintento verificado sin duplicar CAE, y un cierre diario que cuadra.

## F4 — Buffet

Catálogo, stock y POS del buffet sobre LibraCommerce, con el consumo asociable a
la reserva.

Gate: una venta de buffet que descuenta stock, entra a la caja de la sucursal y
sale en la misma factura que la cancha.

## F5 — Panel del dueño

`GET /admin/resumen` (ADR-009) y su consumo desde el panel: ocupación por franja,
ingresos, cancelaciones y ausentes, abiertos por sucursal y sumados entre
instancias.

Gate: un dueño con dos instancias y cinco sucursales viendo cinco filas, no dos.

**Del lado de LibraClub: hecho** (2026-10-25, ADR-027). `GET /api/resumen` trae la
clave `club` (una fila por sucursal: ocupación, franjas, ingresos contra el período
anterior, canceladas, ausentes y origen) y la pantalla «Panel del dueño»
(`GET /api/admin/panel-del-dueno`) la abre por sucursal, con el mapa de calor y el
top de ausentes. **Falta** el consumo en `libra-panel` (sumar entre instancias a
partir de `horas_abiertas` y `horas_reservadas`, no de los porcentajes).

## F6 — Producto

Socios y abonos, clases y escuelas, ~~torneos~~, eventos, analítica de
rentabilidad por cancha y por franja.

**Hora valle y promociones: hecho** (2026-10-28, ADR-029). Un porcentaje sobre la
tarifa por día, franja y vigencia, que el portal muestra con el precio de lista
tachado. Falta medir cuánto se rebaja por promoción (hoy no se guarda cuál aplicó).

**Torneos: hecho** (2026-08-22). Eliminación directa, todos contra todos y zonas
con playoff; sorteo reproducible por semilla, fixture con byes, cancha y horario
por partido —que ocupan el turno de verdad, ADR-010— y resultados con avance
automático del cuadro. Límite conocido y explícito: 1 o 2 clasificados por zona
(ADR-013), y **no hay eliminación doble** — el cuadro de perdedores es otro
problema y no apareció el pedido.

**Campeonatos americanos: hecho** (2026-10-25, ADR-024). Grilla de doble entrada
por zona (con impresión), el partido a 6 o a 9 games o al mejor de 3 sets,
desempate con cara a cara, zonas que terminan sin llaves, categorías y eventos
con las mismas fechas y canchas.

Gate: cada módulo justificado por uso medido, no por catálogo de features.

---

## Fuera de alcance, y a propósito

Marketplace nacional, matchmaking, ranking de jugadores, cámaras con IA, control
de acceso, app nativa y contabilidad formal.

El espacio defendible **no es competir por tamaño de red** contra Playtomic:
es unir la operación deportiva con el circuito argentino de caja y facturación,
que es lo que ninguno de los competidores locales —CanchaFija, CanchaYa, Dispo,
ReservoCancha, CanchaPlay, Canchero— hace hoy.
