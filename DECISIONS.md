# Decisiones

Una entrada por decisión, con el motivo. Las decisiones no se borran: si una se
revierte, se agrega otra que la reemplaza y se marca la vieja.

---

## ADR-001 — PostgreSQL es el único motor, desde el día uno

**Decisión.** `DATABASE_URL` tiene que apuntar a PostgreSQL. No hay default a
SQLite, ni camino dual, ni fallback para tests.

**Motivo.** Es la regla de la familia desde el 2026-08-12: una suite verde
sobre SQLite no dice nada sobre el motor real —no chequea FKs con el pragma
apagado, tipa dinámicamente y acepta cadenas donde la base pide enteros—. En
este producto la razón es más fuerte todavía: **la garantía central de F1 es un
constraint de exclusión GiST, que SQLite no tiene**. Una suite sobre SQLite no
podría siquiera ejercitar lo que hace correcto al producto.

Los productos que nacieron con la capa dual todavía la están sacando. Este no
la tiene que sacar porque no la tuvo nunca.

---

## ADR-002 — `Sucursal` es una entidad de primera clase, y la consolidación entre instancias es el panel del dueño

**Decisión.** Dos capas, no una:

1. **Adentro de la instancia**: existe una tabla `sucursales`. Cada sucursal
   agrupa sus canchas, su caja, su depósito y **su propio punto de venta de
   ARCA**. Una instancia puede tener una sucursal o varias.
2. **Entre instancias**: la consolidación de un dueño con más de una razón
   social —o con complejos que se compraron por separado— la resuelve el
   **panel del dueño**, preguntándole por HTTP a cada instancia. Ver el
   ADR-009.

**Motivo.** El pedido fue *"que se puedan manejar sucursales como en ContaLibra,
y el panel para los dueños con más de una"*. Pero **ContaLibra no tiene entidad
sucursal**: tiene `depositos` (stock) y `cajas` (dinero), y el punto de venta
colgado de la instancia. El relevamiento del 2026-08-20 lo dice con todas las
letras — *"lo que sigue sin existir es una entidad sede única que ate caja +
depósito + punto de venta en una sola pantalla"*, y lo clasifica como cosmético
y de configuración, no como desarrollo.

O sea que "como en ContaLibra" es la **capacidad**, no la implementación.
Copiarla al pie sería heredar el agujero. LibraClub nace hoy y le sale barato
tener la entidad de entrada; retrofitearla después es tocar canchas, tarifas,
caja, reportes y facturación a la vez. Y hay precedente en el motor:
`libragenda.Branch` ya existe, con `Resource.branch_id` y `Holiday.branch_id`
—feriados por sucursal—, así que el dominio ya lo tenía previsto.

**El punto de venta por sucursal no es un detalle.** La numeración de
comprobantes es por `(tipo, punto_venta)` y **no lleva CUIT**: dos sucursales
del mismo CUIT emitiendo con el mismo punto de venta se pisan la numeración, y
ARCA rechaza o duplica. Con la sucursal como entidad, el punto de venta es una
columna suya y la trampa deja de depender de que alguien se acuerde en el alta.
Entre instancias distintas del mismo CUIT sigue siendo configuración del alta,
y ahí sí hay que acordarse.

**Lo que NO se hace.** Una sucursal no es un tenant: no hay aislamiento de datos
entre sucursales de la misma instancia, y el admin las ve todas. Un cliente que
necesite aislamiento real —o que facture con otro CUIT— va en otra instancia.
Ese es el límite entre las dos capas.

**Lo que cuesta.** Casi todas las consultas de la agenda, la caja y los reportes
llevan sucursal en el filtro, y la UI necesita un selector persistente. Es el
precio de no retrofitear.

---

## ADR-003 — Las tarifas viven en LibraClub, no en LibraGenda

**Decisión.** El modelo de precios por cancha, día, franja y feriado es del
vertical.

**Motivo.** LibraGenda **no tiene ningún modelo de precio**: su único objeto con
plata es `Deposit`, que es una seña ya calculada por el que la crea. Y hay
precedente: Gestiolibra resolvió lo mismo con un `ServicePriceRepository`
propio, dentro del vertical.

Se promueve al motor el día que haya un segundo consumidor con la misma forma
de tarifa. Hoy, subirlo sería diseñar para un usuario imaginario.

---

## ADR-004 — LibraClub es dueño de la tabla de reservas; de LibraGenda consume el dominio puro

**Decisión.** Las reservas viven en una tabla propia de LibraClub. De LibraGenda
se importan **funciones sin persistencia** — `RecurrenceRule` /
`generate_occurrences` para las canchas fijas, `intervals_overlap`, la política
de recordatorios y `Deposit`/`DepositStatus` cuando entre la seña. No se usan
sus repositorios SQLAlchemy ni sus tablas.

**Motivo.** El gate de F1 es *cero doble reserva en concurrencia*, y **LibraGenda
no lo puede sostener**. Su chequeo de superposición es, en
`libragenda/application.py`:

```python
existing = [item for item in self.repository.list() if item.id != exclude_id]
if find_conflicts(appointment, existing):
    raise AppointmentConflict(appointment.id)
```

Read-then-write, en Python, sin nada del lado de la base. Dos requests
concurrentes para el mismo turno leen los dos "no hay conflicto" e insertan los
dos. Para una barbería con una recepcionista no se nota. Para un portal público
de canchas —donde el caso de uso *es* mucha gente peleando por el turno de las
20:00— es el modo de falla principal.

Sumado a eso, LibraGenda todavía soporta SQLite (es su default de producción
documentado), así que un constraint de exclusión GiST no le entra sin resolver
antes su capa dual.

**Lo que esta decisión cuesta**, y hay que decirlo: es duplicación de un motor
que la familia ya tiene, exactamente lo que
`auditoria-duplicacion-familia-libra` advierte. Se acepta porque lo que se
duplica es la **persistencia** —tres tablas—, no las reglas: recurrencia,
solapamiento y recordatorios se importan.

**Pendiente que sale de acá:** proponerle a LibraGenda el constraint de
exclusión. Beneficia a Gestiolibra y MedLibra, que hoy corren con la misma
carrera latente.

---

## ADR-005 — La no-superposición se garantiza en la base, no en la aplicación

**Decisión.** La tabla `reservas` lleva una columna generada `periodo`
(`tstzrange`) y un constraint de exclusión sobre `(cancha_id, periodo)`,
restringido a los estados que ocupan la cancha.

Los bloqueos van en la misma tabla, como reservas de tipo bloqueo, **para que el
constraint los cubra**: un bloqueo en otra tabla no puede impedir una reserva.

**Motivo.** Es la única forma de que la promesa valga bajo concurrencia. Un
chequeo en la aplicación necesita serializar la transacción entera para ser
correcto, y nadie se acuerda de hacerlo en el segundo endpoint que inserta.

La aplicación **igual** valida antes, para dar un mensaje decente; el constraint
es la red, no el mensaje. El `IntegrityError` con el nombre de esta constraint se
traduce a un 409 con texto propio.

Requiere la extensión `btree_gist` (para poder comparar `cancha_id` por
igualdad dentro de un índice GiST), que la migración crea.

---

## ADR-006 — La reserva tiene estados explícitos, superconjunto de los de LibraGenda

**Decisión.**

| Estado | Qué significa | Ocupa la cancha |
|---|---|---|
| `provisoria` | Retenida sin confirmar, con vencimiento | sí |
| `pendiente_pago` | Esperando la seña | sí |
| `confirmada` | Confirmada | sí |
| `jugada` | Ya ocurrió | sí |
| `cancelada` | Cancelada | no |
| `ausente` | El cliente no vino | no |
| `bloqueo` | No es una reserva: mantenimiento, torneo, lluvia | sí |

**Motivo.** Los seis de `AppointmentStatus` de LibraGenda no alcanzan: falta el
**hold con vencimiento**, que es lo que hace posible un portal público sin que
un carrito abandonado deje la cancha muerta. `pendiente_pago` se separa de
`provisoria` porque la política de cancelación es distinta.

Qué estados ocupan la cancha es **la cláusula `WHERE` del ADR-005**, no una
convención: cancelar libera el turno porque el estado sale del predicado.

---

## ADR-007 — LibraClub emite sus propias facturas; el puente a ContaLibra queda como opción

**Decisión.** LibraClub monta el motor de facturación de **LibraCore**
(`arca_facturacion`, `arca_wsaa`, `arca_wsfe`) y emite directo a ARCA con el
certificado y el punto de venta del complejo. El puente a una instancia de
ContaLibra queda disponible como **configuración opcional**, no como camino
principal.

**Motivo.** Los dos modelos ya existen en la familia y no son equivalentes:

| | Emisión propia | Puente a ContaLibra |
|---|---|---|
| Quién lo usa hoy | ContaLibra, RestoLibra, VentaLibra, GestioLibra, MedLibra | LibraDesk |
| Dónde vive | `libracore.arca_facturacion` | `comprobantes_pendientes`, también en LibraCore |
| Cuándo emite | En el acto | **Borrador + confirmación humana. Nunca un CAE automático** |

Esa última fila decide. El circuito central de LibraClub es *el jugador paga la
cancha y quiere su comprobante* — y el requisito textual del primer prospecto
fue **"cobro por QR que se facture solo"**. Un borrador que espera a que alguien
lo confirme en otra instancia no puede atender eso.

LibraDesk es la excepción y lo es por su circuito: factura cuotas de contrato y
reclamos cobrables, en tandas, sin nadie esperando en el mostrador. LibraClub se
parece a RestoLibra y VentaLibra, no a LibraDesk.

**El puente igual se deja disponible** porque no cuesta casi nada —la tabla y su
API ya están en LibraCore, y el lado emisor es el `facturacion_externa.py` de
LibraDesk— y sirve al grupo que ya tenga ContaLibra y quiera una sola bandeja
para el cierre mensual. Es una opción de configuración por instancia, y las dos
no conviven para el mismo comprobante.

**Consecuencia operativa:** cada instancia necesita certificado de ARCA y punto
de venta propios — ver el ADR-002.

**Nota sobre quién es dueño de qué.** El motor de ARCA **no es de ContaLibra**:
es de LibraCore, y ContaLibra lo monta como lo montaría cualquiera. La tabla del
puente también está en LibraCore, y se puso ahí a propósito para que un puente a
medida no dejara al resto de la familia repitiendo el trabajo. Ninguno de los
dos modelos implica una dependencia de LibraClub hacia ContaLibra **como
producto**.

---

## ADR-008 — F1 no incluye portal público, cobro online ni buffet

**Decisión.** La primera entrega es la agenda interna con tarifas. El portal con
seña por Mercado Pago es F2; el buffet sobre LibraCommerce es F3.

**Motivo.** El portal es el diferencial comercial y también el tramo más
riesgoso: endpoints sin sesión, anti-abuso, holds con vencimiento y el webhook
de Mercado Pago. Apoyarlo sobre una agenda que todavía no probó nadie es
construir dos cosas nuevas a la vez.

El orden no es negociable en un sentido: **el hold con vencimiento y el
constraint de exclusión tienen que estar antes que el portal**, y por eso los dos
entran en F1 aunque F1 no los use en concurrencia real.

---

## ADR-009 — El panel del dueño le pregunta a la instancia por HTTP, y esta expone `GET /admin/resumen`

**Decisión.** LibraClub sirve un endpoint `GET /admin/resumen?desde=&hasta=`,
gateado por el token de servicio (`LIBRA_SERVICE_TOKEN`), con los números de la
instancia agregados **y abiertos por sucursal**. El panel del dueño consume ese
endpoint en las N instancias del dueño y suma.

**Motivo.** Es la decisión que la familia ya tomó, dos veces. `libra-backoffice`
empezó abriendo la base de cada instancia y **se descartó a mitad de camino**:
los secretos son por instancia —la contraseña SMTP se cifra con una clave
derivada del `SECRET_KEY` de cada una—, así que un panel que administra N
instancias no puede tener N secretos en un solo entorno. El panel del dueño
refuerza el argumento: **no necesita credenciales de ninguna base**.

**Qué devuelve.** Ocupación por franja, ingresos por medio de pago, reservas
canceladas, ausentes, y el corte por sucursal. La forma exacta la fija el panel;
lo que este ADR fija es que el dato **sale por la API y no por la base**.

**Por qué el corte por sucursal viaja en el mismo payload.** Si el panel suma N
instancias y cada una devuelve un solo número, un dueño con tres sucursales en
una instancia y dos en otra ve cinco complejos aplastados en dos filas. El
agregado sin la apertura no es reversible del otro lado.

**Falla cerrado.** Sin `LIBRA_SERVICE_TOKEN` definido el endpoint pide sesión de
admin, igual que el resto. Un token vacío no abre nada — `libraauth` lo trata
como no definido.

---

## ADR-010 — Un partido de torneo ocupa la cancha con un bloqueo de `reservas`

**Decisión.** `partidos_de_torneo` guarda el cruce del fixture y **no** el
horario. Cuando un partido recibe cancha y hora se crea una fila en `reservas`
con `estado = 'bloqueo'`, y el partido la referencia por `reserva_id`.

**Motivo.** Es el ADR-005 aplicado: la no-superposición la garantiza un
constraint de exclusión, y **un constraint sólo puede mirar su propia tabla**.
Un partido de torneo con su horario guardado en `partidos_de_torneo` no
impediría que el mostrador alquile esa cancha a esa hora — y el día del torneo
hay dos grupos en la puerta. Es exactamente el argumento por el que un bloqueo
de mantenimiento no tiene tabla propia (ADR-004).

**Consecuencia buena.** El torneo aparece solo en la agenda, en el detalle de la
reserva y en los reportes de ocupación, sin que ninguno de los tres se entere de
que existen los torneos.

**Consecuencia a manejar.** Cancelar el torneo tiene que **liberar los
bloqueos**, y reprogramar un partido tiene que soltar el viejo y tomar el nuevo
**en la misma transacción**: si el horario nuevo está ocupado y las dos cosas no
van en un mismo `SAVEPOINT`, el partido se queda sin ninguno.

**Lo que destapó.** Liberar un bloqueo lo cancela, y hasta el 2026-08-21 eso era
imposible: `ck_reservas_cliente_segun_estado` exigía cliente a toda fila que no
fuera `bloqueo`, y un bloqueo cancelado deja de ser `bloqueo` sin ganar cliente.
El botón «Quitar bloqueo» de la agenda venía dando 500 desde `0001`. La regla
dice ahora lo que quiso decir siempre: el cliente es obligatorio **mientras la
fila esté viva**. Ver la migración `0007`.

---

## ADR-011 — El fixture se arma con funciones puras, separadas de la base

**Decisión.** `app/servicios/fixture.py` calcula llaves, ronda robin y el orden
de los clasificados **sin tocar la base**: entran cantidades y salen cruces
identificados por índice. `app/servicios/torneos.py` los materializa.

**Motivo.** Un cuadro mal armado **no falla**: dibuja bien, deja jugar, y recién
en semifinales alguien nota que las dos cabezas de serie se cruzaron antes de
tiempo. Probar eso contra la base cuesta un torneo entero por caso; contra una
lista de enteros se prueban veintitrés tamaños distintos y **propiedades** en vez
de ejemplos — que todos entren una vez, que cada partido alimente un solo slot,
que ningún slot quede sin quien lo llene, que el 1 y el 2 sólo se crucen en la
final.

**Consecuencia.** Un bye **no genera partido**: el que sortea con suerte aparece
directamente en la ronda siguiente. Crear el partido y darlo por ganado llenaría
la pantalla de encuentros que nadie va a jugar y obligaría a que todo lo que
recorra el fixture sepa distinguirlos.

---

## ADR-012 — El resultado de un partido son parciales, y `sets_para_ganar` unifica los deportes

**Decisión.** Un partido guarda N filas en `parciales_de_partido`. El torneo
declara `sets_para_ganar`: **1 en fútbol** —el partido es un único parcial, el
resultado— y **2 en un pádel al mejor de tres**.

**Motivo.** Con esa columna, contar quién ganó es el mismo código en los tres
deportes. La alternativa —una rama por deporte— acierta mientras la lista de
deportes no crezca, y `Deporte` ya tiene siete valores.

**Qué se valida.** Que el ganador se lleve exactamente `sets_para_ganar`
parciales; que ningún parcial termine empatado salvo en un torneo a uno; que una
llave no termine empatada —alguien tiene que pasar— y que **el último parcial lo
gane el que gana el partido**, que es el error de tipeo más común: `6-4 / 3-6 /
2-6` cargado como victoria de A haría avanzar al que perdió.

**El empate existe sólo en grupos.** `finalizado` es un booleano aparte de
`ganador_id` justamente por eso: `ganador_id IS NULL` no alcanza para distinguir
«empataron» de «todavía no se jugó».

---

## ADR-013 — Se soportan 1 o 2 clasificados por zona, y el límite es explícito

**Decisión.** `clasifican_por_zona` admite 1 o 2. Lo garantiza un CHECK.

**Motivo.** La regla que evita que dos de la misma zona se crucen en la primera
ronda del playoff es una rotación: el 1º de la zona `z` juega contra el 2º de la
zona siguiente. Con tres o más clasificados esa rotación deja de alcanzar y el
emparejamiento pasa a depender del reglamento del torneo — hay varios, y no son
equivalentes.

**Por qué un límite y no una aproximación.** Un cruce mal armado no falla:
enfrenta a dos que acaban de jugar entre ellos y el playoff pierde la gracia,
sin que nada avise. Es preferible no soportarlo a soportarlo de una forma que
parezca correcta.

**Si aparece la necesidad**, el lugar es `fixture.orden_de_clasificados`, y hay
que decidir *qué* reglamento antes de escribir código.

## ADR-014 — El cobro con QR usa la tabla del portal, y sólo el poll toca la caja

**Contexto.** Pedido de tener acá la misma función de facturación automática con
QR de MercadoPago que Contalibra tiene en producción desde el 2026-08-19. Este
producto ya tenía MercadoPago a medias: el webhook verificado por firma existe
desde F5, pero **nunca inicia un pago** — `POST /api/portal/reservas` devuelve
`url_de_pago: null`. El QR del mostrador es, entonces, el primer cobro real de
MercadoPago del producto.

**Decisión.** El pago del mostrador es un `PagoDeReserva` más, con una columna
`canal` que dice de dónde vino (migración `0008`). Misma tabla, misma
`external_reference`, mismo webhook. Lo que cambia es **qué hace al
acreditarse**:

- `PORTAL`: el pago **confirma la reserva** — sin pago no hay reserva.
- `MOSTRADOR`: la reserva ya está confirmada (o jugada, que es cuando el grupo
  suele pagar); lo que falta es el movimiento de caja y, si está prendido, la
  factura.

**Por qué una columna y no el prefijo de la referencia.** Distinguirlos leyendo
el string sería información de negocio escondida en un identificador: el día que
alguien cambie el formato, el cobro del mostrador empieza a comportarse como uno
del portal y nada lo avisa.

**🔴 Sólo el poll registra el cobro en la caja, y no es una omisión.** El
movimiento va contra el **turno abierto de quien cobra**, y el webhook no sabe
quién es: llega de MercadoPago, sin sesión. Un ingreso sin `turno_id` queda
fuera de todo arqueo — plata que entró y que ningún cierre cuenta. Así que el
webhook sella el pago y el poll —el tick siguiente, con el encargado ahí—
completa. Si el webhook llegó primero, el poll lo ve aprobado y hace su parte
igual; si no hay turno abierto, el poll corta con 409 **sin perder el cobro**:
el pago ya quedó sellado y el tick posterior a abrir la caja lo completa.

**Qué se cobra: el turno entero.** Cancha **más** el consumo de buffet, que es
el mismo total que factura `facturar_reserva`. Si el QR cobrara sólo
`reserva.precio`, la factura saldría por más de lo que entró y el arqueo no
cerraría — y el que lo descubre es el cierre de turno, horas después.

**La idempotencia del cobro es `caja_movimiento_id`, no la de LibraCore.** El
chequeo de `create_caja_movimiento` es por `(referencia, factura_id)`: un primer
intento sin factura —porque ARCA estaba caído— y un reintento que sí factura
**no se ven entre sí** y entran dos veces. La pantalla pollea cada 3 segundos,
así que eso no es un caso raro.

**Dos bases, sin transacción única.** La factura y el movimiento viven en la
base de LibraCore; el pago y la reserva, en la del dominio. Cada parte es
idempotente por separado — el mismo criterio que VentaLibra documenta en su
ADR-022.

**Bajar la orden del QR es parte del cobro.** `DELETE /api/reservas/{id}/mp-qr`
saca el monto del cartel al cancelar o al agotarse la espera. Contalibra **no
llama nunca** a `eliminar_orden_qr` —no tiene un solo call site en todo el
repo— y por eso depende de que nadie escanee entre un cobro y el siguiente.

**El rol.** Cobrar es `staff`; facturar a mano sigue siendo `admin`. La factura
que sale sola no rompe esa línea: quien decidió que se emita fue el dueño, al
prender el toggle en Configuración — el encargado no elige nada.

## ADR-015 — Los avisos se deducen de las reservas; `avisos` es el registro, no la cola

**Fecha:** 2026-08-29 · **Estado:** aceptada

El producto tiene que mandar confirmación, recordatorio y cancelación: es lo que
manda todo el rubro y lo primero que se nombra al comparar contra Turnito,
Canchero, ATC o EasyCancha. La forma obvia es una **cola** — cuando se confirma
un turno se encolan sus avisos con su fecha de envío, y un worker despacha lo
vencido.

**No se hizo así.** Hoy hay **tres** caminos que dejan una reserva confirmada y
ninguno pasa por los otros dos:

1. `servicios/reservas.crear()` — el mostrador, que nace `CONFIRMADA`;
2. `servicios/reservas.cambiar_estado()` — el botón de la agenda;
3. `servicios/pagos.aplicar_pago_aprobado()` — el webhook de MercadoPago, que
   escribe `reserva.estado = EstadoReserva.CONFIRMADA` **a mano**.

Con una cola hay que acordarse de encolar en los tres. El día que aparezca un
cuarto —una reserva desde el panel, una importación de planilla— el síntoma **no
es un error**: es que no le llega el mail al cliente, y eso no lo descubre nadie.
Un aviso que no sale no rompe nada, que es justamente lo que lo hace difícil de
encontrar. Lo mismo del otro lado: una cola obliga a *desencolar* desde cada
camino que cancela.

**La decisión:** el barrido le pregunta a `reservas` qué corresponde avisar, y
`avisos` guarda sólo lo ya intentado — `enviado`, `fallido` u `omitido`. Un
camino nuevo queda cubierto sin tocar el servicio. Lo que impide mandar dos veces
es `uq_avisos_reserva_tipo_canal` — `(reserva_id, tipo, canal, horas_antes)` con
`NULLS NOT DISTINCT` — y no un `if`: dos corridas del cron superpuestas pasan las
dos por el `if` antes de que cualquiera escriba.

**Lo que se paga:** una consulta por regla en cada corrida (con índice y acotada
por fecha), y que la confirmación sale con la granularidad del cron —hasta 5
minutos— en vez de instantánea.

**La ventana de dos horas de la confirmación es parte de la decisión.** Sin ella,
la primera corrida encuentra *todas* las reservas futuras ya confirmadas
—cargadas durante meses, sin que nadie prometiera un mail— y le escribe a cada
cliente por cada turno. El precio es que si el cron estuvo caído más de dos horas
esas confirmaciones no salen, y es el lado correcto para equivocarse. Los
**recordatorios no llevan ventana**: la primera corrida sí manda los de las
próximas 24 h, y eso es el producto funcionando.

**El cron es el interruptor.** No hay un `avisos_activos` en la configuración:
dos interruptores para lo mismo terminan en desacuerdo, y el día que el dueño
diga «no me manda los mails» habría que adivinar cuál de los dos está apagado. El
día que haga falta apagarlo desde la pantalla, el flag **reemplaza** al cron como
interruptor; no se suma.

**El canal no trae SMTP propio.** `TransporteEmail` usa `libraauth.email_sender`
y `resolver_smtp_config`: el mismo servidor que ya configura «Configuración →
Correo» y que manda el mail de recuperación de contraseña. Un segundo lugar donde
cargar un SMTP es un lugar más donde cargarlo mal.

## ADR-016 — Cancelar siempre se puede; la ventana decide la plata

**Fecha:** 2026-08-29 · **Estado:** aceptada

Hasta acá cancelar era gratis y sin consecuencias: el turno se liberaba y la seña
se quedaba donde estaba, **ni devuelta ni anotada como no devuelta**. Es lo que
Alquila Tu Cancha vende como funcionalidad propia —*devolución automática si
cancela con más de 24 horas*— y la segunda brecha de la Fase A.

### Las cuatro decisiones

**1. Cancelar siempre se puede.** `sucursales.horas_de_cancelacion` decide si se
devuelve la plata, **no** si el jugador puede soltar el turno. Impedirle cancelar
fuera de plazo no le devuelve la cancha al complejo: la deja ocupada por alguien
que ya sabe que no viene, y encima sin poder revenderla.

**2. La cancelación nunca se cae porque falle la devolución.** Soltar el turno es
una acción del cliente; devolver la plata es una deuda del complejo. Primero se
cambia el estado y después se mira la plata — al revés, un error de MercadoPago
dejaría el turno sin cancelar. Por eso `DEVOLUCION_PENDIENTE` es un **estado del
pago** y no un booleano: sin él, una devolución que falló se ve igual que una que
nunca correspondió, y la deuda se descubre cuando llama el jugador.

**3. La política vive en la sucursal, y arranca en `NULL`.** Es del complejo:
«devolvemos si avisás con un día» no cambia según en qué cancha ibas a jugar.
🔴 Y `NULL` —«no devuelve nada automáticamente»— es el default **a propósito**:
una migración que dejara 24 le prendería la devolución de plata a todas las
instancias que ya existen sin que nadie lo decida. Una migración no es el lugar
donde se toman decisiones de negocio.

**4. Sólo se devuelve el pago del portal.** Un cobro de mostrador ya entró a la
caja del turno (`PagoDeReserva.caja_movimiento_id`): devolverlo por API dejaría
el arqueo descuadrado, con la plata saliendo por un lado que la caja no ve. Esa
devolución se hace desde la caja, y el resultado **lo dice** en vez de quedarse
callado como si no hubiera habido seña.

### Lo que sostiene que no se devuelva dos veces

La `X-Idempotency-Key` de MercadoPago, y es **del pago** (`devolucion-<referencia
del pago>`), no del intento: todos los reintentos mandan la misma, así que
apretar el botón dos veces devuelve una sola vez. Sin eso, el reintento del
mostrador sería una devolución nueva y el complejo pagaría dos veces.

### Por qué el reintento es un botón y no un cron

Una devolución que falla suele fallar por algo que hay que **arreglar** —el token
vencido, un pago que MercadoPago no deja devolver— y un reintento automático cada
cinco minutos sólo agrega ruido al log. Ver la lista es de `staff` —el encargado
tiene que poder contestarle al jugador que llama— y reintentar es de `admin`:
mover plata hacia afuera es del dueño.

### Dónde vive el cliente de la API

En `app/servicios/devoluciones.py` y **no** en `libracore.mp_api`, aunque devolver
un pago sea una operación genérica de MercadoPago: LibraClub es el primer producto
de la familia que devuelve plata, y la regla del repo es que algo sube al motor
cuando es la tercera copia y no la segunda. No toca nada del dominio —recibe un
`payment_id`, devuelve un `refund_id`— justamente para que mudarlo sea copiarlo.
