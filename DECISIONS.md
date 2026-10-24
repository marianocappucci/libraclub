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

**4. El pago del portal vuelve por MercadoPago; el de mostrador, por la caja.**
Un cobro de mostrador ya entró a la caja del turno
(`PagoDeReserva.caja_movimiento_id`): devolverlo por API dejaría el arqueo
descuadrado, con la plata saliendo por un lado que la caja no ve.

*Reescrita el 2026-09-11.* Hasta esa fecha esta decisión decía que esa devolución
«se hace desde la caja» y el código **lo decía sin hacerlo**: el pago seguía
`aprobado`, la caja no se movía, y la plata que se le devolvía al jugador salía
del cajón como un faltante sin explicación. Ahora, cuando la política dice que
corresponde, es un **egreso en efectivo del turno de caja abierto** de quien
cancela, con la referencia `devolucion-<referencia del pago>`, y el pago pasa a
`DEVUELTO`. Nada se borra: el ingreso del cobro sigue vivo y el arqueo ve los dos.

Sin turno abierto —o si cancela el jugador desde el portal, que no tiene caja— no
se inventa nada: queda `DEVOLUCION_PENDIENTE` con el motivo, **el mismo criterio
que MercadoPago sin credenciales**, y el reintento de admin la saca de **su** caja
abierta.

> 🔑 **El egreso y el estado del pago viven en dos bases.** El movimiento se
> escribe en la de LibraCore, que commitea sola; el `DEVUELTO`, en la del
> dominio, al final del request. Si ese segundo commit se pierde, el reintento
> no saca la plata dos veces: `create_caja_movimiento` es idempotente por
> `(referencia, factura_id)` y la referencia es del pago, no del intento — el
> mismo papel que cumple la `X-Idempotency-Key` del otro lado.
>
> **En efectivo y no por el medio del cobro**, que fue el QR: un egreso
> `mercadopago` bajaría el bucket que se concilia contra lo que MercadoPago
> deposita. Ver `MEDIOS_DE_EGRESO` en `servicios/caja.py`.

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

## ADR-017 — El ausentismo se cuenta y se avisa; no se bloquea

**Fecha:** 2026-09-11 · **Estado:** aceptada

`AUSENTE` se marcaba desde el primer día y **nadie lo contaba**: el que faltó
tres veces en el mes reservaba igual que el que viene todos los martes, y el
encargado se enteraba cuando la cancha quedaba vacía otra vez. Es el último punto
de la Fase A.

### Las tres decisiones

**1. Contar y avisar, sin bloquear.** Decisión del humano. Ni el mostrador ni el
portal le impiden reservar a nadie: el mostrador ve el aviso y decide él —pedirle
la seña entera, llamarlo el día antes, o tomarle el turno igual porque sabe por
qué faltó—. Un bloqueo automático se equivoca en todos esos casos, y el cliente
que se lo come se va a otro complejo.

**2. La regla vive en un solo lugar: 3 ausencias en 90 días**, dos constantes de
`app/servicios/ausentismo.py`. La API devuelve el reincidente **ya resuelto**,
junto con el umbral y la ventana para que la pantalla los pueda decir. La
pantalla no sabe que son «3 en 90»: si lo supiera, el día que el número cambie
habría dos lugares que actualizar.

**3. La ventana se mide sobre `comienza_at`.** Importa a qué turno faltó, no
cuándo lo marcó el encargado. Y tiene cota de arriba: un turno futuro marcado
`ausente` por error no cuenta como algo que ya pasó.

### Por qué un endpoint aparte y no un campo del cliente

`GET /api/clientes/ausentismo/reincidentes` trae sólo a los que pasaron el
umbral, que son pocos. Sumar el conteo a cada fila del listado obligaría a la
fábrica genérica de los cinco maestros (`construir_abm`) a saber qué es una
reserva. Y va con **dos segmentos** después de `/clientes` porque
`GET /api/clientes/{item_id}` matchea cualquier segmento único — mismo criterio
que `/api/reservas/series/listado`.


## ADR-018 — Varios procesos listos (`WEB_CONCURRENCY`, hoy 1) y el registro de errores de la familia

- Estado: aceptada. **Exige `libracore >= v1.159.0`, `libraauth >= v0.50.0` (con migración `0003_captcha_usados`) y `libra-ui >= v0.142.1`.**
- Fecha: 2026-10-13
- Contexto: el dueño decidió (2026-10-13) dejar el código listo para correr con `uvicorn --workers N` **sin prender más workers todavía**: todo sigue en 1 (ADR-044 de libracore, `docs/varios-procesos.md`). Y (2026-10-12) que la familia tenga un registro de errores propio (ADR-045 de libracore, ADR-053 de libra-ui): hasta ahora un 500 iba al stdout de uvicorn y se perdía en cada recreate del contenedor.
- Qué ya existía (se miró antes): `docs/varios-procesos.md` y `docs/errores.md` del motor, ADR-023 de libraauth (captcha en la base), el `pool_pre_ping` de este producto. `pool_pre_ping=True` ya estaba (`app/db.py`).
- Decisión:
  - **Siembras de arranque serializadas.** `ensure_default_admin`, `ensure_demo_user` y las cajas iniciales por sucursal (`asegurar_cajas_de_todas`) (`app/main.py`, `crear_app`) corren adentro de `una_vez_al_arrancar("libraclub-sembrar", destino=config.database_url)`; `destino` es la base del dominio porque `libracore.db` puede no estar configurada (una instancia sin facturación arranca igual).
  - **Captcha en la base.** `app/routers/auth.py` define `USADOS_DEL_CAPTCHA = UsadosEnBase(...)` y lo usan **los dos**: el router de `/auth` (`captcha_usados=`) y el portal de jugadores (`routers/portal.py::_exigir_captcha`, que llama `_captcha_de(request, USADOS_DEL_CAPTCHA)`). El portal verifica con el `Captcha` de proceso; si el `GET /auth/captcha` cayó en otro worker, al que le toca crearlo lo crea con los `usados` en la base y no en memoria.
  - **Nota de crédito.** No emite notas de crédito por su cuenta (usa el router del motor): no aplica.
  - **Registro de errores.** Backend: `instalar_registro_de_errores(app, "libraclub")` al lado de `SecurityHeadersMiddleware`, que monta `POST /api/errores-cliente`. Frontend: `instalarReporteDeErrores()` antes de montar y `<ErrorBoundary>` alrededor de todo en `main.tsx`. Compose de `-dev`: `LIBRA_ENTORNO=dev`, `LIBRA_INSTANCIA=libraclub-dev`, `LIBRA_VERSION=${LIBRA_VERSION:-dev}`; las instancias de cliente y demo las escribe el panel.
  - **Compose de `-dev`**: `exec uvicorn ... --workers ${WEB_CONCURRENCY:-1}`. `uvicorn>=0.30` ya era el piso.
- Consecuencias:
  - **La migración `0003` de libraauth corre antes de uvicorn** en todo camino de arranque (la cadena de `scripts/panel_admin.py` y el `command:` del compose ya incluyen `libraauth-migrar upgrade`): `exigir_schema_al_dia` hace que el producto no arranque sin ella, aunque no use `UsadosEnBase`.
  - Sin migración propia. Con más de un worker, después de un restore en caliente hay que **reiniciar el contenedor** (`docs/varios-procesos.md` del motor).
  - Las serializaciones del arranque cubren las siembras («si no existe, crear»); la creación idempotente del esquema (`CREATE TABLE IF NOT EXISTS` de `ensure_schema`) no se serializa: antes de subir `WEB_CONCURRENCY` a más de 1 hay que medirlo con dos workers.
  - Tests: `tests/test_registro_de_errores.py`, `tests/test_arranque_varios_procesos.py` y el caso de `captcha_usados` en `tests/test_captcha_login.py`; los dobles del captcha de los `conftest` aceptan el segundo argumento que libraauth v0.50.0 pasa a `_captcha_de(request, usados)`.


## ADR-019 — El cliente se elige con `SelectCliente` y se da de alta ahí mismo

- Estado: aceptada. **Exige `libra-ui >= v0.158.1`** (ADR-071 del kit).
- Fecha: 2026-10-16
- Contexto: el humano pidió (2026-10-16) que **todo** campo de la suite donde se elige un cliente ofrezca darlo de alta en el lugar, con un solo componente. El caso que lo disparó fue el mostrador de LibraDesk, donde un cliente no cargado no se podía elegir. En este producto había dos campos: la reserva (con un «Cliente nuevo» propio que reemplazaba el select y creaba el cliente **al reservar**) y «Nueva cancha fija» (sin alta: sin clientes ni siquiera se mostraba el botón).
- Qué ya existía (se miró antes): `libra-ui/SelectCliente` y su guard `libra-ui/auditoria-de-clientes`; el alta de clientes de `construir_abm` con `rol_escritura=require_staff` (`app/routers/maestros.py`): un encargado puede crear clientes, que es lo que ya hacía el «Cliente nuevo» de la reserva.
- Decisión:
  - Los dos campos usan `SelectCliente` con `campos=['telefono','email']` (lo que se tiene a mano cuando alguien llama por primera vez). Documento, CUIT y observaciones se completan en Clientes.
  - **El cliente se crea en el panel, no al reservar.** `crear` hace `POST /api/clientes` con `{nombre, telefono, email}` y el campo lo elige solo; la reserva y la cancha fija usan su id. Un único helper, `frontend/src/lib/clientes.ts`.
  - El campo no se esconde por falta de clientes: «Nueva cancha fija» se ofrece aunque la lista esté vacía.
  - Lo que no es un campo de cliente se marca `cliente-sin-alta: <motivo>` en el código; hoy es «Copiar datos de…» de `FacturaNueva`, que rellena dos inputs escritos a mano.
  - `frontend/src/test/campos-de-cliente.test.ts` falla si nace un desplegable de cliente sin alta ni marca.
- Consecuencias:
  - Una reserva rechazada (409/422) ya no deja un cliente huérfano ni crea otro al reintentar.
  - Un cliente dado de alta en el panel existe aunque después se cancele la reserva: es a propósito, ya está en Clientes.
  - Sin migración ni cambios de API.


## ADR-020 — Una sola base: LibraCore vuelve a vivir en la del dominio (el código anda con las dos formas)

- Estado: aceptada. Una migración de esquema (`0012_actividad_log`) y ninguna de datos: **este PR no une ninguna instancia**. Exige `libracore >= v1.189.0` y `libracommerce >= v0.72.1` (los que ya están pineados).
- Fecha: 2026-10-22
- Contexto: el humano decidió (2026-10-22) que LibraClub pase a **una sola base**, dominio y core juntos. Los motivos son los de LibraCargo (ADR-029 de ese producto): el buffet, la caja y la factura tienen que escribirse en una sola transacción, y el nodo de LibraEdge (plan «LibraCargo y LibraClub en la versión de escritorio», wiki del ecosistema) necesita una sola base. LibraClub las llevaba aparte desde que entró la facturación porque `init_core_schema()` crea `usuarios` y `auth_log`, que acá ya existen con la forma de `libraauth`; medido en LibraCargo y en las otras cuatro apps, las columnas son las mismas y es la convivencia de ContaLibra, VentaLibra y LibraCargo.
- Qué ya existía (se miró antes): ADR-029 de LibraCargo (`_misma_base`, `nuevo_cliente` con `base_core_separada=False`, la revisión `0015`, la suite con `vaciar_auth`), `libracore.db.url_de_instancia` y `libracore.provisioning.db_urls`, y el `libracore-unir-bases` del motor (otro PR, en curso). LibraClub **no tiene clientes reales**: `libraclub-dev` y `libraclub-demo` son las dos únicas instancias con `libraclub_core`.
- Medido el 2026-10-22, sobre bases descartables de PostgreSQL 16 con libracore `v1.189.0`:
  - **Dos cadenas sobre `alembic_version` se pisan.** En una base vacía con las dos variables en la misma URL, `libracore-migrar` deja `alembic_version = 0028_caja_del_nodo` y `alembic upgrade head` del producto muere con *Can't locate revision identified by '0028_caja_del_nodo'*.
  - **Con la tabla propia, la cadena entera corre** sobre una base vacía en el orden `libracore-migrar`, `libracommerce-migrar`, `libraauth-migrar --base dominio`, `alembic`. Quedan cuatro tablas de versión: `alembic_version`, `_libracommerce`, `_libraauth` y `_libraclub`.
  - **Sobre el estado de `dev` y `demo` de hoy** (dominio con `alembic_version = 0011_qr_del_buffet`, core aparte), `libracore-unir-bases verificar` corta con `version_repetida`. Tras el deploy de este PR (autorrenombre) dice «Se puede unir».
  - **`libracommerce-migrar` migra la base del dominio** (`url_de_commerce`), no la del core. Con dos bases, sin más, crea 25 tablas vacías de LibraCommerce en `libraclub`, y `verificar` corta con 21 `choque_de_tablas` (`sales`, `parties`, `actividad_log`...). Con `LIBRACOMMERCE_MIGRAR_URL` apuntando al core migra el buffet donde está y `verificar` da «Se puede unir».
  - **`actividad_log` tiene dos formas y en una sola base gana la primera que se crea.** `libracommerce-migrar` (antes que la cadena de este producto) la crea con `ts TEXT` y `entidad_id INTEGER`; el listener de `libraauth` que audita el dominio castea cada parámetro a `TIMESTAMP`/`VARCHAR` y **cada escritura auditada —una sucursal, una reserva— moría con `DatatypeMismatch`**. El registrador crudo del motor comercial escribe en las dos formas (el `ts` y el id viajan como texto); el ORM sólo en la de `libraauth`.
- Decisión:
  - **La tabla de versión del producto es `alembic_version_libraclub`** (`migrations/env.py`), con su clave `_pkc`. **Autorrenombre**: si falta `alembic_version_libraclub` y `alembic_version` guarda sólo revisiones de la cadena de este repo, la renombra —y renombra la clave primaria, que un `RENAME` de tabla no mueve— en la misma transacción que la migración (si ésta falla, el renombre se deshace). Si `alembic_version` guarda una revisión del motor (base unida) no se toca. `include_object` limita `alembic check` a las tablas de este producto, como en LibraCargo.
  - **Una sola base o dos, según la instancia.** `Config.desde_entorno()`: sin `LIBRACLUB_LIBRACORE_DATABASE_URL`, o con la misma base que el dominio, `libracore_database_url` es la URL del dominio y `core_en_la_del_dominio` es verdadero (`misma_base` ignora el driver, los parámetros y la barra final). Con otra base, todo sigue igual que hasta hoy. `_instancia_a_respaldar` declara el core como segunda base sólo si es otra; `facturacion.configurar(..., url_del_dominio=)` crea la base del core sólo si es otra; `app/database.py` (el contrato del backoffice, que corre sin `Config`) cae al dominio.
  - **La cadena de migraciones suma `libracommerce-migrar upgrade --prefijo libraclub`**, entre el motor y `libraauth` (`scripts/panel_admin.py`, `scripts/nuevo_cliente.py` y el `command:` del compose de dev; `tests/test_provisioning.py` ata las dos puntas). Hasta acá las tablas del buffet las creaba `init_schema()` al arrancar la app. **El compose de dev declara `LIBRACOMMERCE_MIGRAR_URL` sobre la base del core** mientras tenga dos.
  - **Revisión `0012_actividad_log`** (`migrations/versions/`): lleva `actividad_log` a la forma de `libraauth` sea cual sea el orden —la crea si falta, convierte las dos columnas conservando las filas si la dejó el motor comercial, no toca la que ya la tiene (`dev` y `demo`)—. No depende de que la cadena corra antes o después de `libracommerce-migrar`.
  - **Un alta nueva nace con una sola base**: `base_core_separada=False` explícito en los dos scripts (era el default; ahora es una decisión escrita y con test).
  - **La suite corre con las dos formas.** Por defecto, dos bases (`<base>_core`, la plantilla `armada` por worker); con `LIBRACLUB_SUITE_UNA_BASE=1`, una (`tests/conftest.py`: `_dejar_el_core_de_cero` y `_auth_se_vacia`, que traduce el `drop_all` de auth en vaciar, porque las FK del motor referencian `usuarios`). El CI corre las dos.
- Consecuencias:
  - **Cuando entre este PR, `crear_app()` sin `LIBRACLUB_LIBRACORE_DATABASE_URL` factura contra la base del dominio.** Antes era «instancia sin facturación». Es lo que dice la decisión; las dos instancias vivas tienen la variable, y un alta nueva la escribe.
  - **Desplegar este PR ANTES de unir**: si se une primero, `libracore-migrar` corre contra una base donde `alembic_version` es de este producto y muere por revisión desconocida.
  - **La demo necesita una línea en su compose del VPS** (`LIBRACOMMERCE_MIGRAR_URL` = la URL del core, como en el de dev) antes de desplegar este PR; sin ella el deploy crea el schema del buffet en el dominio y la unión queda cortada hasta borrarlo. Al unir, esa variable y `LIBRACLUB_LIBRACORE_DATABASE_URL` pasan a la URL del dominio (o se sacan, cuando el motor sume LibraClub a `_UNA_SOLA_BASE`).
  - Con una sola base, `actividad_log` (la de `libraauth` y la de LibraCommerce) es una tabla: `/logs` ve también lo que escribe el buffet (`tests/test_una_sola_base.py` lo mide con la app andando).
  - 🔴 **Abierto para el motor: `libracore-unir-bases verificar` corta `dev` y `demo` por `choque_de_tablas: actividad_log`** (medido el 2026-10-22 con la herramienta en su worktree, `core-unir`): en el dominio la creó el arranque con la forma de `libraauth` y en el core la creó el motor comercial. Hay que tratarla como las tablas compartidas con `libraauth` (`usuarios`, `auth_log`), o copiar el log del core al del dominio convirtiendo los tipos. No es de este producto.
  - `scripts/reset_demo.sh` no resetea dos veces la misma base.
  - La base `libraclub_core` vieja se conserva un ciclo después de unir; no se borra sin preguntar.

### Addendum a ADR-020 (2026-10-22): las dos instancias se unieron y la variable del core se va

- Estado: aplicada en este PR. Sin migración ni cambios de API.
- Qué pasó: `libracore-unir-bases` (libracore `v1.190.0`, ADR-078) unió `libraclub-dev` y `libraclub-demo` el mismo día. **No queda ninguna instancia con dos bases** y LibraClub no tiene clientes reales, así que la forma de dos bases dejó de tener quién la use.
- Decisión:
  - **El compose de dev no declara `LIBRACLUB_LIBRACORE_DATABASE_URL` ni `LIBRACOMMERCE_MIGRAR_URL`.** Sin la primera, `Config.desde_entorno()` resuelve la base del dominio; sin la segunda, `libracommerce-migrar` migra la del dominio, que ahora es donde está el buffet. `tests/test_una_sola_base.py` falla si alguna de las dos vuelve a aparecer en el compose, y `tests/test_libraauth_resuelve_la_base.py` ata que el compose declare sólo `DATABASE_URL`.
  - 🔴 **`libracore-migrar --prefijo libraclub` sin la variable del core exige libracore `>= v1.190.1`** (`libraclub` en `_UNA_SOLA_BASE`, libracore#426). Con `v1.190.0` `url_de_core` falla con `SinURL` —su regla era «el core aparte no cae al dominio»— y el `command:` del compose, que lo corre primero, no deja arrancar el contenedor. Lo ata `test_libracore_migrar_cae_a_la_base_del_dominio_sin_la_variable_del_core`. El resto del código no depende de eso: `Config`, el respaldo, `app/database.py` y `libraauth-migrar --base dominio` ya resolvían la base del dominio.
  - **La suite corre con una sola base y se retiró la de dos.** `tests/conftest.py` perdió la plantilla `armada` por worker, la base `<base>_core` y el interruptor `LIBRACLUB_SUITE_UNA_BASE`; el CI perdió el paso «Tests (una sola base)» y su paso `Tests` (el check protegido `test`) corre ahora la de una base. Se retiró porque medía una forma de instancia que ya no existe y costaba una segunda corrida entera por PR. **El código que soporta dos bases se queda** (`Config.core_en_la_del_dominio`, el respaldo con base extra, `facturacion.configurar` creando la base del core): sacarlo no aporta nada hoy y arriesga romper una instancia que defina la variable con otra base. Lo siguen midiendo los tests de `tests/test_una_sola_base.py`, que arman sus bases a mano (`base_temporal`) y no dependen de la forma de la suite.
  - **`scripts/reset_demo.sh` ya no aborta si el contenedor no lleva la variable del core**: sin ella, la base de LibraCore es la del dominio. Si alguien la define con otra base, resetea las dos como antes.
  - Los comentarios de `scripts/panel_admin.py` y `scripts/nuevo_cliente.py` dejan de hablar de `libraclub_core` como algo vigente.
- Consecuencias:
  - **Orden de despliegue:** la imagen con este cambio necesita libracore `>= v1.190.1`. El compose de la demo en el VPS (fuera de este repo) tiene que dejar de apuntar `LIBRACLUB_LIBRACORE_DATABASE_URL` y `LIBRACOMMERCE_MIGRAR_URL` a `libraclub_core`: o las apunta a la base del dominio o las saca.
  - `libraclub_core` (la base vieja de cada instancia) queda sin uso. Borrarla en el VPS espera el OK del humano; no es de este PR.
  - Un alta nueva sigue saliendo del motor con las dos variables en la misma URL (`base_core_separada=False`); `Config` las trata como una sola base.


## ADR-021 — La venta del buffet nace por `registrar_venta` del motor, con su vínculo puesto por un gancho

- Estado: aceptada. Sin migración de esquema ni de datos. Exige `libracommerce >= v0.73.0` (ADR-072 del motor), ya pineado.
- Fecha: 2026-10-24
- Contexto: PR 10 del plan «LibraCargo y LibraClub en la versión de escritorio». Hasta acá el buffet guardaba su `Sale` por su cuenta (`save_sale` + `confirm_sale`, `source_type='reserva'|'mostrador'`), y la leía con SQL directo. En un nodo de LibraEdge la venta tiene que subir al central como las de ContaLibra, RestoLibra y VentaLibra, y eso cuelga de `al_registrar_venta`, que sólo llama `registrar_venta`.
- Qué ya existía (se miró antes): `registrar_venta` / `crear_venta_directa` y sus ganchos (`libracommerce/erp/ventas.py`, `hooks.py`); cómo los usan VentaLibra (`app/ganchos.py`: numerador propio, `turno_para`, `con_outbox`), ContaLibra y RestoLibra; ADR-067 y ADR-072 del motor (`con_outbox`, `Outbox.extra_de_venta`, `venta_origen_nodo`, `tablas_de_origen`). No hay nada del buffet en la familia: ningún otro producto ata la venta a otra entidad.
- Decisión:
  - **`registrar_consumo` llama a `crear_venta_directa`** con `estado='cobrada'`, `stock_habilitado=True`, `guardar_costo=True`, el depósito `Buffet #<sucursal>` como `deposito_id` (de ahí sale el stock y `sales.branch_id`) y **`pagos=[]`**.
  - **El vínculo lo pone el gancho `al_registrar_venta`** (`_vincular`): `UPDATE sales SET source_type = 'reserva', source_id = <reserva>` (o `'mostrador'`, sin `source_id`). `registrar_venta` crea la venta con `'pos'` y no recibe un origen (ADR-072: «el producto lo pone en su `al_registrar_venta`»); con `con_outbox` el gancho corre **antes** de encolar, así el payload de `venta.registrada` sale con `source_type` / `source_id`. Los ganchos son **por llamada** (`ganchos_del_consumo(reserva_id)`) porque el vínculo es de esa venta; `GANCHOS_PROPIOS` (numerador y sin turno) es lo que usa el central para aplicar lo que sube, donde el vínculo ya viene en el payload y rehacerlo lo pisaría.
  - **La caja no la escribe el motor.** `registrar_venta` escribe un movimiento por cada pago con el concepto `Venta <n> — <medio>` y sin la referencia `buffet-<id>` que leen el arqueo y los reportes por medio; además `ventas_pagos` apunta por FK a `ventas`, no a `sales` (el repunte lo hacen otros productos en su migración). El buffet no pasa pagos: la plata sigue entrando por `servicios/caja.py`, una sola vez, como antes. Tampoco se ata a `venta_links.turno_id` (`turno_para` devuelve `None`).
  - **Numeración**: el `numerador` del motor es `_numero_de_venta`, que sigue al último `%BUF-%` (con o sin prefijo de nodo: `con_outbox` antepone `S02-`). Antes se calculaba fuera de toda transacción; ahora corre con el write-lock y, si dos ventas eligen el mismo número, `crear_venta_directa` reintenta.
  - **`actividad_log`**: el repositorio auditado dejaba el alta de la venta; `registrar_venta` escribe por SQL, fuera de ese envoltorio. El gancho la anota con `app.commerce.auditar_alta`, en la misma transacción. Las filas por movimiento de stock del log ya no se escriben (el ledger sí).
  - **`venta_links` la crea `facturacion.configurar()`** (`crear_venta_links`, idempotente): `registrar_venta` la lee (`obtener_venta`) al terminar toda venta cobrada.
  - **Los lectores de `sales` no cambian** (`consumos_de_reserva`, `total_consumido`, `consumido_de_reservas`, `lineas_para_factura`, `resumen_comercio`): las dos columnas son las mismas. No hay datos viejos que migrar.
  - **El cobro con QR no se mueve** en este PR: `preparar_consumo` (borrador) y `confirmar_consumo` siguen con `save_sale` / `confirm_sale`. Se explica abajo.
- Diferencias que sí quedan (medidas):
  - `sale_items.unit_cost_snapshot` queda **NULL** cuando el producto no tiene costo cargado (antes `0`): es la regla del motor (ADR-016), y el margen distingue «sin costo» de «costó cero».
  - `stock_movements`: `source_type='venta'` y `note='Venta ID <n>'` (antes `'sale'` y sin nota), `occurred_at` a medianoche del día (antes la hora); mismo `movement_type='sale'`, mismo depósito, misma cantidad. `current_stock` las suma igual.
  - `sales.status_detail='cobrada'` (antes `NULL`) y `confirmed_at` `NULL` (antes la hora). Nadie en LibraClub las lee.
- Consecuencias:
  - 🔴 **El borrador del QR no llega al nodo.** El motor no tiene cómo confirmar una venta pendiente sin un pago a acreditar (`acreditar_pago_qr` mueve la caja y no el stock; `registrar_venta` con un pago pendiente descuenta el stock al crear, que es lo contrario de lo que decide el buffet). Hasta que el motor lo tenga, el cobro con QR del mostrador es del central. Anotado como abierto en el informe del PR.
  - Para el PR 11: ver `CHANGELOG.md` (se agrega `app/offline.py` con el `Outbox`, y `ganchos_del_consumo` pasa a envolver con `con_outbox`; el central registra `registrar_en(..., tablas_de_origen={"reserva": "reservas"})`).

## ADR-022 — Las reservas que se dan en un nodo sin conexión: exclusión partida, `en_conflicto` y dos operaciones

- Estado: aceptada. **Migración `0013_reservas_en_el_nodo`** (aditiva y reversible). Fuera de un nodo y sin operaciones de nodo, la web y el portal no cambian.
- Fecha: 2026-10-24
- Contexto: PR 12 del plan «LibraCargo y LibraClub en la versión de escritorio». Decisiones del humano (2026-10-22): en el club sin internet **también se dan reservas**; si una reserva del club choca con una de la web o del portal, **gana la que llegó primero al central** y la otra queda `en_conflicto`, **visible en las dos puntas**; cancelar o marcar jugada una reserva de la web **espera a la conexión**.
- Qué ya existía (se miró antes): la exclusión GiST `ex_reservas_sin_superposicion` (ADR-005) y el chequeo previo de `servicios/reservas.py`; `vencer_provisorias.py` y `EstadoReserva.PROVISORIA` (el turno retenido esperando el pago del portal: **no es esto**); `libracore.altas_en_nodo` y `libracommerce.erp.offline_clientes` (ADR-077 / ADR-070: id provisorio negativo, `cliente.alta`, mapeo, aplicador idempotente); `libraedge.mapeo` y la guarda del espejo (ADR-019/ADR-021 de libraedge: en una tabla con alta en el nodo sólo se escriben las filas con id negativo); `libracore.nodo_offline` (`SinConexion` → 409 `sin_conexion`, `SoloEnElCentral` → 409 `solo_en_el_central`); el vínculo de la venta del buffet con `source_type='reserva'` (ADR-021 y ADR-072 del motor).
- Decisión:
  - **Vocabulario.** «Provisorio» es el **id negativo** de una reserva dada en el nodo que todavía no tiene el definitivo. No toca a `EstadoReserva.PROVISORIA`. En el código: `es_del_nodo(id)`, `reservas_nodo`, «reserva del nodo».
  - **Exclusión partida por el signo del id** (`0013`). `ex_reservas_sin_superposicion` (el nombre de siempre) pasa a cubrir `id > 0`; `ex_reservas_del_nodo_sin_superposicion` cubre `id < 0`. En el central no hay ids negativos: hace lo mismo que antes. En la base del nodo, lo que baja del espejo y una reserva dada sin conexión pueden ocupar la misma cancha a la misma hora sin trabar el ciclo de sincronización (sin la partición el espejo no podía insertar la fila). Las provisorias siguen sin poder pisarse entre ellas. Lo que cruza los dos lados lo resuelve el central. Las dos listas de estados salen de `ESTADOS_QUE_OCUPAN` y las ata `tests/test_schema.py`.
  - **`en_conflicto`** (nuevo valor del ENUM `estado_reserva`, **fuera** de `ESTADOS_QUE_OCUPAN`): una reserva guardada que no ocupa la cancha ni la mira ninguna exclusión. Dos columnas nulas: `conflicto_con_id` (la que ganó; sin FK, porque el espejo no garantiza el orden en que llegan las filas) y `estado_previo` (`confirmada` o `pendiente_pago`, a lo que vuelve al resolverse).
  - **`reserva.creada`** (`servicios/reservas_nodo.py`). La encola `servicios.reservas.crear` **en la transacción de la reserva** (la sesión de SQLAlchemy y la conexión del motor comparten la conexión de PostgreSQL: `conexion_de_la_sesion`), con el id provisorio de `libraedge.mapeo`. Payload `version 1`: `reserva_id` (negativo), `cancha_id`, `cliente_id`, `estado`, `origen`, `comienza_at` / `termina_at` (ISO **con zona**), `precio`, `sena`, `observaciones`, `creada_at`. En el nodo sólo se dan reservas `confirmada` o `pendiente_pago`. El aplicador del central, idempotente por el mapeo `(nodo, 'reservas', id provisorio)`:
    1. valida el payload y que la cancha y el cliente existan (un `IntegrityError` ajeno sería leído por el receptor como «duplicado» y la reserva se perdería: todo lo rechazable es un `ValueError`, revisión manual);
    2. la inserta en un `SAVEPOINT`; si **la exclusión del central la rechaza**, la cancha ya estaba tomada cuando la operación llegó: la guarda `en_conflicto`, con `conflicto_con_id` y `estado_previo`. La decide la base y no un `SELECT` previo, así que dos operaciones simultáneas no pueden ganar las dos;
    3. anota el mapeo (también si quedó en conflicto: el nodo tiene que saber cuál es la suya). El `cliente_id` negativo (un cliente del dominio dado de alta en el nodo, que hoy no existe) se traduce con el mismo mapeo.
  - **`reserva.estado`.** Porque **una reserva del nodo se puede cancelar o marcar jugada ahí**, y sin esto el `reserva.creada` ya encolado subiría como si nada. La encola `cambiar_estado` sólo para un id negativo; el central aplica el cambio sobre la reserva mapeada (idempotente, `TRANSICIONES`). Una reserva `en_conflicto` cancelada desde el nodo queda cancelada; **marcada jugada se queda `en_conflicto`** con una nota (jugada ocuparía una cancha que otra reserva ya tiene).
  - **Las guardas en el nodo.** `reservas` es una tabla espejada con alta en el nodo: una fila con id positivo no se escribe ahí (SQLSTATE `LE001`). Se contesta antes con un 409 claro (`cambiar_estado` ya corre antes de tocar la plata de una cancelación): sin conexión, **`sin_conexion`** (decisión del humano); con conexión, **`solo_en_el_central`**, porque el nodo no tiene cómo subir ese cambio. Los bloqueos y las series (su id saldría de la secuencia del nodo) dan `solo_en_el_central`. `main.py` registra los dos errores como 409 con el cuerpo de siempre (`{"detail": {"codigo", "mensaje"}}`) y `api.ts` muestra su `mensaje`.
  - **Cómo se resuelve un conflicto** (`servicios/conflictos.py`, `/api/reservas-en-conflicto`), **sólo desde el central** (un nodo lo lista, que le llega por el espejo, pero no lo resuelve: 409 `solo_en_el_central`). Dos caminos: **mover** (otro horario y/o otra cancha libres, con las reglas de una reserva nueva; conserva la duración, el precio y la seña que se le dijeron al cliente; vuelve a su `estado_previo`; sin datos intenta el horario original, que sirve si la que ganó se canceló) y **cancelar** (por `servicios/cancelacion.py`, con la política de la sucursal). Desde la agenda, `POST /api/reservas/{id}/estado` a `cancelada` también sirve; a cualquier otro estado no.
  - **Frontend mínimo.** `AvisoDeConflictos` en la agenda (lista cada conflicto con la que ganó y deja mover o cancelar; sin conflictos no dibuja nada). La pantalla de verdad es del kit (PR 13).
- Consecuencias:
  - **Interfaz para el PR 11**: `reservas_nodo.configurar(reservas_nodo.desde_el_outbox(OUTBOX))` en el nodo y en el central, `reservas_nodo.registrar_en(despachador)` sólo en el central, y `AltaEnNodo("reservas")` en el `Aprovisionamiento` (con eso el nodo reapunta lo que referencia a la provisoria con las FK del catálogo y borra la fila provisoria cuando baja la definitiva). Hace falta `libraedge` en las dependencias y su deploy key en el CI: por eso los tests del aplicador y del outbox real se saltean donde no está (`-rs` lo dice).
  - 🔴 **Para el PR 11: en un nodo, un `UPDATE` sobre una reserva con id positivo muere con `LE001`**. Cobrar un turno que vino de la web no puede escribir `reservas.factura_id` ahí; y los `pagos_de_reserva` de una reserva provisoria, si la tabla se espeja, los borra el reapuntado (la definitiva trae los suyos del central): el pago de una reserva dada en el nodo tiene que subir como operación propia.
  - El `reserva.estado` de una reserva ya mapeada (id definitivo, positivo) no lo encola nadie: desde que baja del central es una reserva del central para el nodo.
- Abierto:
  - **Con conexión, el nodo tampoco cambia una reserva del central.** El humano dijo «espera a la conexión»; sin una operación para subir ese cambio la única forma segura es hacerlo desde la web. Si se quiere desde el nodo, hace falta `reserva.estado` también para ids positivos (y la devolución de la seña, que sale por MercadoPago, desde el nodo).
  - ✅ **Resuelto el 2026-10-24 (addendum de abajo): cancelar un conflicto devuelve siempre la seña entera.** Estaba abierto así: cancelar un conflicto seguía la política de cancelación de la sucursal, y el conflicto no es culpa del jugador; si a la mitad de la ventana se le cobra la seña, es una decisión de negocio que no está tomada.
  - ✅ **Resuelto el 2026-10-24 (addendum de abajo): suben como provisorios con `cliente_club.alta`.** Estaba abierto así: los clientes del dominio dados de alta en el nodo (`clientes`, no `clients` de LibraCore) no tienen id provisorio: una reserva nueva a un cliente nuevo hoy usa la secuencia local y chocaría con el central. Sale con su propia operación; el aplicador de `reserva.creada` ya traduce el `cliente_id` negativo.

### Addendum a ADR-022 (2026-10-24): cancelar un conflicto devuelve la seña entera, y los clientes dados de alta en el nodo suben como provisorios

- Estado: aplicada en este PR. **Sin migración.** Resuelve los dos puntos que ADR-022 dejó abiertos; los decidió el humano el 2026-10-24. Fuera de un nodo no cambia nada, **salvo la devolución al cancelar un conflicto, que vale también en el central** (es donde se resuelve).
- Qué ya existía (se miró antes): `servicios/cancelacion.py` (la ventana de la sucursal, `_devolver` por canal, `_devolver_por_caja`, `reintentar`); `libracore.altas_en_nodo` y `libracommerce.erp.offline_clientes` (ADR-077 / ADR-070: `cliente.alta`, id provisorio, mapeo, aplicador idempotente con deduplicación por `external_ref` o CUIT/DNI); `libraedge.mapeo` y `libraedge.altas.AltaEnNodo`; el aplicador de `reserva.creada`, que ya traducía un `cliente_id` negativo con `erp.offline.id_del_central`.

**1. Cancelar una reserva `en_conflicto` devuelve SIEMPRE la seña entera.**

- Decisión: `cancelacion.cancelar` lee el estado **antes** de cancelar (`cambiar_estado` limpia el conflicto) y, si era `en_conflicto`, **se salta la ventana de la sucursal**. La devolución sale por el camino de siempre —MercadoPago si el pago entró por el portal, la caja si fue un cobro de mostrador, según el `canal` del pago— y con sus mismas garantías (no se cae la cancelación si falla; pendiente y reintento; idempotencia por la referencia del pago). Está en `cancelacion.cancelar` y no en `conflictos.cancelar` porque **todos los caminos que cancelan un conflicto pasan por ahí**: `POST /api/reservas-en-conflicto/{id}/resolver`, la agenda (`POST /api/reservas/{id}/estado`) y la cancelación del jugador desde el portal. Una regla en un solo lugar.
- Auditoría: el motivo de la reserva queda `Conflicto de reserva del nodo: <lo que escribió quien cancela>` (hasta los 200 caracteres de la columna); el `detalle` del `Resultado` lo dice; y el **concepto del egreso de caja** lleva `— Conflicto de reserva del nodo`, también en un reintento (sale del motivo de la reserva, `cancelacion.es_de_conflicto`). Por MercadoPago no hay dónde anotarlo: la pasarela no recibe un motivo.
- Lo que no cambia: cancelar una reserva común sigue por la política; `mover` un conflicto no toca la plata (conserva la seña que se le dijo al cliente).

**2. Los clientes del club (`clientes`) dados de alta en un nodo suben como provisorios.**

- Decisión: `app/servicios/clientes_nodo.py`, el mismo patrón que `reservas_nodo`. En un nodo `clientes_nodo.agregar` le pone al cliente un **id provisorio negativo** (`libraedge.mapeo.siguiente_id_provisorio`: la misma secuencia que las reservas), lo guarda y encola **`cliente_club.alta`** en la misma transacción (`conexion_de_la_sesion`): si algo falla no queda ni el cliente ni la operación. Fuera de un nodo es `sesion.add` y nada más. El ABM de clientes (`POST /api/clientes`) pasa por ahí.
- **El nombre de la operación es `cliente_club.alta` y no `cliente.alta`** porque ése ya lo registra `libracommerce.erp.offline.registrar_en` para los `clients` del buffet, y el `Despachador` falla al arrancar con un tipo repetido. Su mapeo es `(nodo, 'clientes', id)`, distinto del `clients` de libracommerce.
- **El aplicador del central** (`aplicar_cliente_alta`) es idempotente por `libraedge_mapeo`: asigna el id definitivo, anota el mapeo y **deduplica**. Un alta ya mapeada no hace nada si el cliente mapeado es la misma persona; si no lo es (una PC reemplazada con el mismo `node_id` que reusó un id provisorio) es `ClienteDelNodoError`, revisión manual.
- **A quién considera la misma persona** (justificado con lo que el producto ya usa para identificar a alguien; no hay clave única sobre `clientes`): primero `documento`, después `cuit` (los dos datos «para facturar», normalizados sin puntos ni guiones), y última `email` (es lo que ata a una persona con su cuenta del portal, `uq_cuentas_jugador_email`, pero una familia puede compartir uno). La primera clave que encuentra gana, siempre sobre un cliente **activo y con id del central**; **se descarta la coincidencia si los dos traen un `documento` o un `cuit` distinto** (mismo email, personas distintas). **No se deduplica por nombre ni por teléfono**: dos «Juan Pérez» sin documento ni email son dos clientes; fusionar de más ata una reserva a otra persona y no se nota, duplicar de menos se junta a mano. Si encuentra a la persona, **usa su ficha y no toca sus datos** (el central es la autoridad del maestro).
- **El orden**: el alta se encola en el request que precede a la reserva, y el nodo sube por `(node_id, sequence)` (ADR-020 de libraedge), así que llega antes que la `reserva.creada` que lleva su id provisorio. Si el alta quedó en revisión manual, la reserva se rechaza (`VinculoNoSincronizado`) en vez de quedar a nombre de nadie y se reintenta en orden. `tests/test_clientes_aplicador_central.py` recorre el camino completo: alta y reserva en el nodo, el despachador real aplicándolas en orden, y la reserva atada al cliente definitivo.
- **El reapuntado** lo hace `libraedge` cuando baja el mapeo, con `AltaEnNodo("clientes")` en el aprovisionamiento: lee las FK del catálogo (`reservas.cliente_id`, `series.cliente_id`, `cuentas_de_jugador.cliente_id`). `tests/test_clientes_en_el_nodo.py` ata que **toda columna `cliente_id` tenga su FK a `clientes`**: una que guardara el id sin FK quedaría apuntando a un provisorio que ya no existe, y habría que declararla como `Referencia`.
- **Guardas en el nodo** (son consecuencia de la anterior; sin ellas la base rechazaría con un 500, SQLSTATE `LE001`): editar o borrar un cliente da 409 `sin_conexion` sin conexión y 409 `solo_en_el_central` con ella; un cliente **provisorio** tampoco se edita (la operación ya llevó sus datos: el cambio se perdería cuando baje el definitivo). El portal de jugadores (`portal.registrar`, que crea su propio `Cliente`) da 409 `solo_en_el_central`: es público y no corre en el equipo del local.
- Consecuencias:
  - **Cableado sobre el PR 11 (ADR-023)**: `app/offline.configurar_clientes()` (junto a `configurar_reservas`, desde `crear_app`); `sincronizacion_offline.registrar_clientes` en el despachador del central; `AltaEnNodo("clientes")` en `ALTAS_EN_EL_NODO` (`clientes_nodo.altas_en_nodo()`); y `clientes` **sale de `TABLAS_SOLO_LECTURA`**, que el PR 11 había declarado maestro de sólo lectura: sin eso la base del nodo rechazaría el alta provisoria. Por la misma razón el router de clientes no lleva la guarda general `escritura_solo_en_el_central` de los maestros (`maestros.CON_ALTA_EN_NODO`): el `POST /api/clientes` de un nodo era 409 `solo_en_el_central` y ahora da de alta; editar y borrar siguen siendo 409 por la guarda propia de `clientes_nodo`.
  - Con `libraedge` ya como dependencia (PR 11), los tests corren siempre; los de las piezas simulan el nodo y `tests/test_nodo_clientes.py` usa el armado real de la app.
- Abierto:
  - **Editar un cliente dado de alta en el nodo** (corregir un teléfono mal anotado) espera a que suba y baje el definitivo. Si se quiere desde el mostrador sin conexión hace falta una operación `cliente_club.editado` que el central aplique sobre el mapeado.
  - **El pago de una reserva dada en el nodo** sigue sin subir (ya estaba abierto en ADR-022): mientras tanto, cancelar desde el nodo una reserva que luego queda en conflicto no tiene seña que devolver en el central.
  - **Un cliente del central con documento repetido** (el maestro no tiene clave única) se resuelve por el de menor id.

  - **Cancelar un conflicto sigue la política de cancelación de la sucursal.** El conflicto no es culpa del jugador; si a la mitad de la ventana se le cobra la seña, es una decisión de negocio que no está tomada.
  - **Clientes del dominio dados de alta en el nodo** (`clientes`, no `clients` de LibraCore) no tienen id provisorio: una reserva nueva a un cliente nuevo hoy usa la secuencia local y chocaría con el central. Sale con su propia operación; el aplicador de `reserva.creada` ya traduce el `cliente_id` negativo.


## ADR-023 — LibraClub sin conexión: el buffet, la caja, el pago de una reserva y la factura conjunta en el nodo de LibraEdge

- Estado: aceptada. **Migración `0014_libraedge`** (aditiva: las tablas de LibraEdge). Exige `libracore >= v1.191.0` (ADR-079, la cola de ARCA), `libracommerce >= v0.73.0` (ADR-072) y `libraedge >= v0.22.0` (ADR-025). **`libraedge` queda pineado al commit `1d7ab0a` de su `develop`** (v0.22.0 todavía no tiene tag): se cambia por `@v0.22.0` antes del merge.
- Fecha: 2026-10-24
- Contexto: PR 11 del plan «LibraCargo y LibraClub en la versión de escritorio». Decisión del humano (2026-10-22): sin internet, en el club se **vende en el buffet, se opera la caja, se cobran las canchas, se cargan consumos y se dan reservas**. Las reservas son el PR 12 (ADR-022, ya en `develop`): este PR las enchufa al outbox y al despachador. Lo genérico es de los motores (el aprovisionamiento de LibraEdge, la capa ERP de LibraCommerce, la cola de ARCA de LibraCore); acá queda la costura del producto, como en VentaLibra (ADR-090).
- Qué ya existía (se miró antes): `app/offline.py` y `sincronizacion_offline.py` de VentaLibra, RestoLibra y ContaLibra; `libracommerce.erp.offline` (`con_outbox`, `registrar_en`, `aplicadores`, `id_del_central`), `offline_caja` (`caja_con_outbox`), `offline_stock` (`configurar`, carga inicial); `libracore.cola_arca` (`ColaDeArca`, `encolar_y_emitir`, `aplicar_pedido_del_nodo`, `build_cola_del_nodo_router`), `facturas_del_nodo` y `nodo_offline`; `libraedge` ADR-025 (el ticket por servicio, `para_servicio`). **No hay nada de la factura conjunta ni del cobro de una reserva en la familia**: ningún otro producto ata plata a una entidad de agenda.
- Decisión:
  1. **`app/offline.py`** declara: `nodo()`, `en_linea()`, `CONEXION`, el `OUTBOX` (`caja_con_turno=True`: el arqueo de LibraClub es por movimientos de caja con turno), `GANCHOS_DE_CAJA`, `solo_en_el_central`, el cliente del ticket y la `cola()` de ARCA, y el `aprovisionamiento`. `offline_stock.configurar(OUTBOX)` corre al importarlo, en las dos puntas: en un nodo la reposición del buffet sube como `stock.movimiento`; el central se niega (409) a mover el stock de una sucursal con nodo activo.
  2. **Quién manda sobre qué.** El central manda los maestros (`sucursales`, `canchas`, `clientes`, `tarifas`, `feriados`, `franjas_de_atencion`, `series`), el catálogo del buffet (`catalog_items`, `locations`, precios), `usuarios`, `cajas` y `arca_config`: bajan al nodo (`TABLAS_DE_REFERENCIA`) y los maestros son de **solo lectura** en el nodo (`tablas_solo_lectura`). El nodo manda lo que genera sin red —ventas, stock, caja, facturas y la cola `cola_arca—`: **no se espeja**, sube como operaciones. **Nunca se espeja** `arca_credenciales_servicio` ni el almacén de claves (`secretos_instancia`): el ticket de ARCA lo presta el central. Las `reservas` son de los dos (`AltaEnNodo("reservas")`), y se declara la referencia sin FK que hay que reapuntar cuando la reserva provisoria recibe su id definitivo: `sales.source_id` con `source_type='reserva'`. `listar_sucursales` lista `sucursales` (del dominio), no `branches` (vacía en este producto): `locations.branch_id` es el id de la sucursal del dominio y es lo que compara la guarda del central.
  3. **El buffet.** `ganchos_del_consumo` devuelve `con_outbox(replace(GANCHOS_PROPIOS, al_registrar_venta=_vincular(reserva_id)), OUTBOX)`: en un nodo el consumo sube como `venta.registrada` con su vínculo (el gancho del producto corre antes de encolar, ADR-072). El central registra `registrar_en`-equivalente con `con_outbox(GANCHOS_PROPIOS, OUTBOX)` y **`tablas_de_origen={"reserva": "reservas"}`**: un consumo de una reserva dada en el nodo llega con `source_id` negativo y se traduce con el mapeo. `ubicacion_de` **no crea** el depósito en un nodo (`SinUbicacion`, 409): tiene que venir del central. El catálogo (alta y edición de productos) y el cobro con QR (el borrador no sube, ADR-021) son del central: 409 `solo_en_el_central`.
  4. **La caja.** Toda la caja pasa por `servicios/caja.py`; sus cuatro escrituras (abrir turno, movimiento, anular, cerrar turno) reciben `ganchos=GANCHOS_DE_CAJA`, y el router del cierre diario también. El cobro del buffet y el pago de una reserva suben **como `caja.movimiento`** (la venta del buffet se registra con `pagos=[]`, así que no se duplica con `venta.registrada`). Sin el outbox, fuera de un nodo, no hacen nada.
  5. **El pago de una reserva.** Sube como movimiento de caja y **el vínculo con la reserva es su referencia** (`reserva-<id>-<azar>`). Con una reserva dada en el nodo el id es el provisorio (`reserva--1-ab12`): (a) `_id_de_referencia` entiende el signo; (b) el central traduce el texto con el mapeo de las reservas antes de escribir el cobro (`aplicar_movimiento_de_club`, que envuelve el aplicador de `caja.movimiento` del motor; sin mapeo, `ValueError` → revisión manual detrás de su `reserva.creada`); (c) en el nodo, cuando el espejo reapunta la reserva `-1` a la `500`, la referencia —un texto, que LibraEdge no reescribe— sigue diciendo `-1`: `_ids_equivalentes` lee también el provisorio por `libraedge_mapeo`, y el pendiente no se pierde. **`pagos_de_reserva` no se espeja**: sus filas apuntan por FK a la reserva y el reapuntado las borraría; el pago del nodo no usa esa tabla.
  6. **La factura conjunta.** En el central, `facturar_reserva` como siempre (la lógica de armar el comprobante se partió en `comprobante_de`, que comparten las dos). En un nodo, `POST /api/reservas/{id}/facturar` **no emite**: `encolar_y_emitir` del motor deja el pedido `documento` en la cola y, con conexión, lo emite ya (201, la factura, como el central); sin conexión o si se corta, **202** `{"en_cola": true, "estado", "mensaje"}` y sale solo al volver (`arrancar_cola_al_volver` en el `startup`). El emisor (`factura_del_nodo.emitir_documento`) numera con `ctx.numerar` (el ticket prestado; **nunca** `get_next_numero_with_arca`), toma la fecha de `ctx.fecha_de_la_factura` y pide el CAE; es idempotente por la marca `facturas.observaciones = "Reserva <id>"`. Lo que el nodo no hace: emitir a mano, autorizar, anular o cobrar contra los comprobantes (`/api/facturas*`, `/config/arca`, la bandeja de Mercado Pago): `escritura_solo_en_el_central` (409; las lecturas pasan).
  7. **Lo que sube de la factura.** `al_cambiar` de la cola encola `cola.pedido` (el estado, para que la web consulte; el central lo aplica con `aplicar_pedido_del_nodo`) y, si el pedido quedó **emitido**, **`club.factura_conjunta`** v1 (`libracore.facturas_del_nodo.payload_factura` más la reserva con el id del nodo), las dos en una transacción. El central: escribe la factura con el mismo número y CAE, traduce la reserva con el mapeo, le pone **su** `factura_id` y ata los cobros sin factura. Un cobro que llega después de la factura (el orden inverso) también se ata. Dos comprobantes para la misma reserva, o un conflicto de número, son `ValueError`: revisión manual.
  8. **El nodo no escribe `reservas.factura_id`, ni lo lee como un id suyo.** Es la guarda del espejo (ADR-019 de libraedge): una fila con id positivo es del central y un `UPDATE` en el nodo muere con `LE001`; y el `factura_id` que baja es de **otra base** (cada una numera sus facturas). El vínculo del nodo es la marca de la factura; el cobro lleva `factura_id_para_cobrar` (la factura local o `None`, porque `caja_movimientos.factura_id` es una FK).
  9. **El despachador del central** (`factura_del_nodo.armar_despachador`) es `registrar_en` de LibraCommerce abierto en sus dos pasos (`aplicadores` + `registrar`), porque hay que reemplazar el aplicador de `caja.movimiento`: los trece tipos del motor, `cola.pedido`, `club.factura_conjunta`, y las de las reservas del PR 12 (`reserva.creada` y `reserva.estado`, por `registrar_reservas` → `reservas_nodo.registrar_en`). La configuración de `reservas_nodo` sobre el `OUTBOX` la hace `offline.configurar_reservas()` desde `crear_app`.
  10. **Se monta siempre** (el gateo es el secreto del nodo, no una bandera): `sincronizacion_offline.router`, `create_nodos_router` (ADMIN) y `create_canje_router` (público: lo llama el instalador). La matriz de roles: las cuatro rutas de `RUTAS_AUTENTICADAS_POR_NODO` son «PÚBLICA, secreto del nodo» (401 aun con sesión de admin), `/api/nodos-offline*` y resolver la cola son ADMIN, ver y emitir la cola son de staff. La barra del pie (`estado-del-sistema`) recibe la conexión del nodo, las facturas que esperan y los nodos del central.
- Descartadas:
  - **Un `save_sale` propio que encole a mano**: ya está resuelto por `registrar_venta` (ADR-021).
  - **Subir el cobro de la reserva con `venta.pago_acreditado`**: el cobro de un turno no es una venta ni un pago pendiente de una venta; es un movimiento de caja con un vínculo en el texto.
  - **Una operación propia `club.cobro_de_reserva`**: el motor ya sube el movimiento, con su turno y su arqueo, y el central ya lo aplica idempotente. Lo propio es traducir la referencia, que se hace sobre el aplicador del motor.
  - **Guardar la factura del nodo en `reservas.factura_id`**: ver el punto 8.
  - **Espejar `facturas` o `pagos_de_reserva`**: ids propios de cada base; el reapuntado de una reserva provisoria borraría los pagos.
  - **Que el central se rehúse a facturar una reserva que el nodo tiene en cola**: el central no sabe qué reserva del nodo es la `-1` hasta que llega su `reserva.creada`; queda abierto.
- Consecuencias:
  - **Fuera de un nodo no cambia nada**: ningún gancho encola, la cola no emite, las guardas de solo-central no hacen nada, el despachador es nuevo pero el router sólo responde a un nodo con secreto. La suite previa pasa sin tocarla.
  - Se despliega **motores → central → nodos**. En el central: `libracommerce-migrar` (revisión 0010, `venta_origen_nodo`) **antes** de que un nodo suba una venta con vínculo; `libracore-migrar` (0029, `cola_arca`) y esta `0014`.
  - **`reservas.factura_id` de una reserva facturada por un nodo queda en el id del central**, que baja al nodo por el espejo y ahí es un id de otra base. El nodo lo trata como «ya facturada» y no la factura de nuevo.
- Abierto (anotado, no hecho acá):
  1. **`LIBRAEDGE_CARGA_INICIAL`** (`libracommerce.erp.offline_stock:aplicar_carga_inicial`) en `instalador/productos/libraclub.json` de libraedge: sin ella el nodo no trae el stock del depósito del buffet al vincular. El central ya expone `carga_inicial_del_central`. Es un cambio de una línea **en libraedge**.
  2. **El depósito del buffet tiene que existir en el central** antes de vincular el nodo (se crea al abrir el buffet de esa sucursal). `validar_registro` no lo exige: no sabe de qué sucursal es el nodo.
  3. **El alta de un cliente en el nodo** (`clientes` es de solo lectura): la reserva de alguien nuevo se da en el central o con un cliente ya cargado. Dar de alta clientes con id provisorio es del PR 12 (acepta ids negativos de cliente al aplicar) pero no tiene quién los cree.
  4. **Lo cobrado en el central o en el portal de una reserva no baja al nodo**: el pendiente de `caja_movimientos` es de cada base. Una reserva que pagó la seña por el portal figura impaga en el nodo hasta que sincronice la caja.
  5. **El frontend** no conoce el 202 de `facturar` (`en_cola`) ni los 409 `solo_en_el_central` de las pantallas de maestros.
  6. **Si `al_cambiar` falla** (el motor lo registra y sigue) el central no se entera de la factura; falta un reconciliador en `en_cada_vuelta`.
  7. Publicar un helper `encolar_operacion` en `libracommerce.erp.offline_caja` (hoy `_encolar` es privado; este PR usa la API de libraedge directo, y `reservas_nodo` del PR 12, el privado).

