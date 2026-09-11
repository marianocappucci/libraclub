# Changelog

Formato [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/),
versionado [SemVer](https://semver.org/lang/es/).

## [No publicado]

### Agregado

- **Ausentismo: el mostrador ve quién viene faltando sin avisar.** Un cliente con
  **3 o más turnos en `ausente` en los últimos 90 días** aparece con un aviso al
  elegirlo en el diálogo de reserva —cuántas veces faltó y la fecha de la
  última— y marcado en el listado de Clientes. La regla vive en un solo lugar
  (`app/servicios/ausentismo.py`) y la API la devuelve resuelta
  (`GET /api/clientes/ausentismo/reincidentes`, con el umbral y la ventana).
  > 🔴 **Avisa, no bloquea**, ni en el mostrador ni en el portal: decisión del
  > humano. El encargado decide si le pide la seña entera o le toma el turno
  > igual. Ver ADR-017.

- **El aviso de cancelación dice qué pasó con la seña.** El mail que manda el
  cron ahora repite lo que el portal ya le decía al jugador —se devolvió, se
  está gestionando, o no se devuelve y por qué—, leído del estado **guardado**
  del pago y con los textos de `servicios/cancelacion.py`, que pasaron a una
  sola función. Si no hubo seña, el mail no dice nada de seña.

- **La devolución de una seña cobrada en el mostrador es un egreso real de
  caja.** Hasta hoy se anunciaba y no se hacía. Cuando la política dice que
  corresponde, sale como egreso en efectivo del turno de caja abierto, atado al
  pago por la referencia `devolucion-<referencia>`, y el pago queda `devuelto`.
  Sin caja abierta queda como devolución pendiente, con el motivo, y el
  reintento de admin la completa. Ver ADR-016, decisión 4.

- **La copia externa en la nube del cliente, como add-on `resguardo_externo`.**
  Con el add-on prendido, el admin conecta su Google Drive o Dropbox desde
  Configuración → Datos / Backup (`/api/config/resguardo-externo/enlace`, el
  router de LibraCore v1.93.0, carpeta «Resguardo LibraClub»). Es el primer
  add-on de LibraClub: disponible en cualquier plan, **viene apagado** y se
  prende por instancia desde el backoffice.
  > 🔴 Apagado —sin fila en `modulos`, con la fila en falso, o sin poder leerla
  > (instancia sin base de LibraCore, tabla que falta)— contesta **403 y nunca
  > 500**: la pantalla lo lee como "sin plan" y esconde la tarjeta. El gate es
  > `app/addons.py` y no el `require_module` del motor, que lee
  > `app.state.modules`, que este producto no carga.
  >
  > `app/database.py` es el contrato del backoffice (`get_modulos` /
  > `set_addon`, por `docker exec`), delegando en `libracore.db.modulos` contra
  > la base de LibraCore — no la del dominio, que no tiene la tabla.

- **La venta de buffet del mostrador se cobra con el QR de MercadoPago.** En
  Caja → Venta suelta → «Vender del buffet», elegir «MercadoPago» ahora pone el
  total en el cartel de la caja y espera la acreditación, en vez de anotar un
  movimiento a mano como si fuera una transferencia. Es el mismo agujero que el
  detalle del turno tenía hasta el 2026-08-28, sobre la otra cosa que se cobra
  en el mostrador.
  > 🔴 **La venta queda en BORRADOR hasta que MercadoPago acredita**: poner el
  > monto en el QR **no mueve stock ni plata**. Un QR que nadie escanea no
  > descuenta las gaseosas —que siguen en la heladera— ni deja una venta cobrada
  > que nadie pagó. El stock sale y el ingreso entra en el mismo tick del poll,
  > y sólo entonces.
  >
  > El pago vive en `pagos_de_reserva` con `reserva_id` en `NULL` y `venta_id`
  > cargado (revisión `0011`, con un CHECK que exige **uno de los dos**): así el
  > webhook lo encuentra por la misma referencia, con la misma traducción de
  > estados y la misma máquina de `EstadoPago`, sin una segunda tabla ni un
  > segundo `if`. Y sin credenciales cargadas la pantalla **dice** qué falta y
  > dónde se carga, que es la mitad del reporte del 2026-08-28 que era una
  > pantalla muda.

- **La pantalla dice de qué ambiente es el token de MercadoPago** — `Ambiente
  de prueba`, `Ambiente de producción` o `Ambiente sin verificar`, con la fecha
  en que se determinó.
  > 🔴 MercadoPago **no tiene homologación como ARCA**: no hay host de sandbox,
  > es el mismo `api.mercadopago.com` y lo que define el ambiente es el token.
  > Sin el cartel las dos fallas son mudas — un token de producción en una
  > instancia `dev` **cobra plata de verdad** y uno de prueba en la instancia de
  > un complejo **no cobra nada**, y las dos se ven igual: el QR del mostrador
  > se genera y la orden se crea.
  >
  > Mirar el prefijo no alcanza: un *usuario de prueba* de MercadoPago entrega
  > credenciales `APP_USR-` igual que las reales, y lo único que lo delata es el
  > `nickname` de `/users/me`. Por eso quien clasifica es **Probar conexión**,
  > que ahora recarga la sección. La clasificación lleva la huella del token, así
  > que si la credencial cambia por cualquier vía se descarta sola.

### Corregido

- 🔴 **Mandar una factura por mail no podía funcionar.** El motor leía
  `email_smtp_*` de `config.json`, un store que en LibraClub **no escribe
  nadie**: la pantalla de Configuración siempre guardó en la base cifrada de
  libraauth. El endpoint contestaba 400 —*"configurá el servidor SMTP en
  Configuración → Email"*— señalando justo la pantalla donde el SMTP ya estaba
  cargado y andando para los mails de contraseña. Con LibraCore v1.64.0 el
  producto le inyecta su resolver al router (`app/smtp.py`), y es el **mismo**
  que usa la recuperación de contraseña: que cada envío lo resolviera por su
  cuenta es exactamente como la familia terminó con dos configuraciones de SMTP
  distintas.

### Agregado

- **Política de cancelación y devolución de la seña** (ADR-016, parte de F2):
  cada sucursal declara con cuántas horas de anticipación hay que cancelar para
  que la seña vuelva, y si el turno se cancela a tiempo **se devuelve sola** por
  MercadoPago. Es lo que Alquila Tu Cancha vende como funcionalidad propia y lo
  que a este producto le faltaba: hasta hoy cancelar era gratis y la seña se
  quedaba donde estaba, ni devuelta ni anotada como no devuelta.

  **Cancelar siempre se puede**: la ventana decide la plata, no si el jugador
  puede soltar el turno. Y **la cancelación no se cae porque falle la
  devolución**: si MercadoPago no contesta, el turno igual queda libre y la deuda
  queda anotada como `devolución pendiente`, visible en su pantalla y
  reintentable por el dueño. Reintentar dos veces no devuelve dos veces.

  La política **arranca apagada** (`NULL`): las instancias que ya existen siguen
  comportándose igual hasta que alguien cargue el número en la sucursal. El cobro
  de mostrador no se devuelve por API —ya entró a la caja— y el resultado lo dice.
  Migración `0010`. 18 tests de backend y 3 de frontend, 9/9 mutaciones muertas.

- **Avisos al cliente por email** (ADR-015, parte de F2): confirmación cuando el
  turno queda tomado, recordatorio 24 h y 2 h antes, y aviso de cancelación. Es
  lo que mandan los cuatro competidores más vendidos del mercado argentino, y
  este producto no mandaba nada: había SMTP —lo usan el reset de clave y el envío
  de la factura— pero ninguna reserva disparaba un mail.

  **No hay cola**: el barrido le pregunta a las reservas qué corresponde avisar y
  `avisos` registra sólo lo intentado, así que los turnos confirmados por el
  webhook de MercadoPago —que escribe el estado a mano— quedan cubiertos igual
  que los del mostrador. Lo que impide el envío doble es un índice único, no un
  `if`. El canal usa el SMTP que ya configura «Configuración → Correo».

  El cliente que pide no recibir se apaga en `clientes.acepta_avisos`. Lo manda
  `scripts/enviar_avisos.py` desde el cron, cada 5 minutos: **ese cron es el
  interruptor de la función**. Migración `0009`. 20 tests, 9 de 9 mutaciones
  muertas.

- **Cobro con QR de MercadoPago y factura automática** (ADR-014): desde el
  detalle de un turno confirmado o jugado, «Cobrar con QR» pone el total —la
  cancha **más** el consumo de buffet— en el QR impreso del mostrador y espera a
  que MercadoPago avise. Al acreditarse, el cobro entra a la caja del turno y
  —si la instancia tiene la automática prendida— sale la factura sola, con las
  dos cosas detalladas. El QR es el cartel fijo de la caja y no cambia nunca;
  lo que cambia es cuánto cobra.

  Es el **primer cobro real de MercadoPago del producto**: hasta acá el webhook
  existía y verificaba firma, pero nada iniciaba un pago. Cancelar el cobro baja
  el monto del cartel, para que el próximo que escanee no pague el turno
  anterior. Sección nueva **Mercado Pago** en Configuración, que además reúne el
  Webhook Secret del portal. Migración `0008`. 20 tests de backend y 9 de
  frontend.

- **Torneos** (F6): eliminación directa, todos contra todos y zonas con
  playoff, para pádel, tenis y fútbol. Inscripción con integrantes y cabezas de
  serie, sorteo reproducible por semilla, fixture con byes, programación de
  cancha y horario, carga de resultados con avance automático del cuadro, y
  tabla de posiciones por zona.
- Un partido de torneo con cancha y horario **ocupa el turno en la agenda**: se
  crea un bloqueo real, así que nadie puede alquilar esa cancha a esa hora
  (ADR-010). Cancelar el torneo libera todos los bloqueos.

- Esqueleto del producto: configuración, sesión, salud, SPA y backup.
- Modelo de dominio de F1: canchas, tarifas, clientes, reservas, bloqueos y
  series recurrentes.
- Garantía de no-superposición a nivel de base con `EXCLUDE USING gist`.
- Alta de reserva desde la grilla de la agenda, con cliente nuevo en el mismo
  diálogo, y detalle de la reserva ocupada con sus transiciones.
- El alta de clientes la puede hacer un encargado (`staff`), no sólo un admin.
- ABM de canchas y de tarifas desde la UI: alta, edición y baja, con las
  acciones de escritura visibles sólo para admin.
- ABM de sucursales y de clientes desde la UI, con sus pantallas propias.
  Clientes trae buscador y filtro de dados de baja, y lo puede escribir un
  encargado.
- El selector de sucursal del encabezado se actualiza solo al crear, editar o
  borrar una sucursal, y se corre a otra si la elegida queda de baja.

### Corregido

- **«Quitar bloqueo» devolvía 500 desde la primera migración.** La máquina de
  estados declara `bloqueo -> cancelada` y el botón de la agenda manda esa
  transición, pero el CHECK `ck_reservas_cliente_segun_estado` exigía cliente a
  toda fila que no fuera `bloqueo` — y un bloqueo cancelado deja de ser
  `bloqueo` sin ganar cliente. La regla dice ahora lo que quiso decir siempre:
  el cliente es obligatorio mientras la fila esté viva (migración `0007`).
