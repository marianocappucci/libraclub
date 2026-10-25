# Changelog

Formato [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/),
versionado [SemVer](https://semver.org/lang/es/).

## [No publicado]

- **Se adopta libracore v1.195.0: `GET /api/nodo/conexion` y una sola forma del 202 «en cola»** (2026-10-25, ADR-026; libracore ADR-084; sin migración).
  - **`GET /api/nodo/conexion`** (`build_conexion_del_nodo_router(conexion=offline.CONEXION, ...)`, cualquier usuario de la instancia): `{es_nodo, en_linea, node_id, a_facturar}`. El cartel «Sin conexión» deja de preguntarle a la cola (`/api/nodo/cola?limite=1`): `Layout.tsx` ya no pasa la `ruta` y usa la del kit.
  - **El 202 de la factura conjunta** (`POST /api/reservas/{id}/facturar` en un nodo) lo arma el motor: `respuesta_en_cola(pedido, mensaje=resultado["mensaje"])`. El cuerpo es `{en_cola: true, codigo: "en_cola", estado, pedido_id, mensaje, motivo}`: **gana `codigo` y `motivo`**; `en_cola`, `estado`, `pedido_id` y `mensaje` son los de antes. libra-ui no cambia (`esRespuestaEnCola`).
  - Tests: `tests/test_nodo_roles_y_aprovisionamiento.py` (fila nueva de la ruta), `tests/test_nodo_factura_conjunta.py` (la forma única del 202), `src/pages/Cola.test.tsx`.
- **Editar en el nodo un cliente dado de alta como provisorio: `cliente_club.edicion`** (2026-10-25, segundo addendum a ADR-022; sin migración). Fuera de un nodo no cambia nada.
  - **En el nodo** (`clientes_nodo.editar`): `PUT /api/clientes/{id}` con un cliente **provisorio** (id negativo, con o sin conexión) actualiza la fila local y encola `cliente_club.edicion` en la misma transacción, con **sólo los campos que cambiaron** y su valor anterior (`antes`/`despues`). Sin cambios no encola nada. Siempre va **detrás del alta** (no se reescribe el alta pendiente): el outbox sube por secuencia, así que el central aplica el alta y después la edición.
  - **En el central** (`aplicar_cliente_edicion`): traduce el id con el mapeo de LibraEdge y compara campo por campo con la base del nodo. Idempotente (si ya está el valor nuevo no hace nada). **Conflicto** —alguien cambió en el central el mismo campo, o el alta se unió a una ficha con otros datos—: no se aplica nada y la operación entera va a **revisión manual** con lo que tiene el central y lo que quería el nodo; se reintenta o se descarta (`libraedge-central revision`). **A confirmar con el humano**: la alternativa es «gana el último por campo».
  - **Sigue igual**: un cliente del central no se edita en el nodo (409 `sin_conexion` / `solo_en_el_central`) y un provisorio no se borra (409; se lo da de baja con «Activo»). Si el nodo recibió el id definitivo mientras se guardaba, el `PUT` da 409 y no un 500.
  - **Pantalla**: la etiqueta «Provisorio» del kit (libra-ui v0.181.0, ADR-095) en la lista de Clientes y en el título del formulario, con el aviso de que los cambios suben junto con el alta.
  - Tests: `tests/test_clientes_en_el_nodo.py`, `tests/test_clientes_aplicador_central.py`, `tests/test_nodo_clientes.py` (de punta a punta por el receptor real) y, en el frontend, `Clientes.test.tsx` y `FormularioDeCliente.test.tsx`.
- **El cuadro de llaves con líneas, y tres arreglos de la grilla del americano** (2026-10-25, ADR-025; pedido del humano; sólo frontend, sin migración).
  - **Llaves** (`Fixture`, `components/llaves.ts`): las líneas que unen cada par de partidos con el siguiente, como un bracket de papel; cada partido queda a la **altura media exacta** de sus dos orígenes (se leen de `avanza_a_id` / `avanza_a_slot`). Con byes el partido que recibe a un solo origen queda a su altura con una línea recta y no cuelga ninguna. El orden vertical no cambia, las tarjetas son de alto fijo y el cuadro sigue scrolleando horizontal. Claro y oscuro.
  - **Grilla**: dice «equipo» o «competidor» donde no son parejas (sólo pádel y tenis son parejas); sin control de games (fútbol y el resto) las columnas de la derecha son **Pts / Dif / Pos.** en vez de PG, como la tabla de posiciones; y la **diagonal va rellena de rojo** (también en papel y en oscuro) en lugar de la línea fina.
  - Tests: `llaves.test.ts`, `Fixture.test.tsx` y casos nuevos en `GrillaDeZona.test.tsx`.

- **Campeonatos americanos: grilla por zona, el partido a 6 o a 9 games, desempate con cara a cara, zonas sin llaves, categorías y eventos** (2026-10-25, ADR-024; pedido del humano; **migración `0015_americanos`**, aditiva y reversible). Los torneos que ya existen no cambian, salvo el orden de la tabla de pádel y tenis por zonas.
  - **Cómo se juega el partido** (`games_por_set`, además de `sets_para_ganar`): un set a 6 games (6-0 a 6-4, 7-5, 7-6), un set a 9 (9-0 a 9-8; no existe el 10-8) o al mejor de 3 sets. Se valida cada set y un 1-1 en sets es un partido sin terminar y no un empate. Fútbol y el resto: sin cambios.
  - **Después de las zonas** (`termina_en_zonas`): o pasan a llaves los 1 o 2 primeros de cada zona (como siempre) o el torneo termina en las zonas y el primero de cada zona es el campeón de su zona (sin playoff, el torneo se cierra solo).
  - **Desempate de una zona de pádel o tenis**: partidos ganados; entre dos empatados, el resultado entre ellos; diferencia de sets; diferencia de games; games a favor. La tabla trae las columnas de sets (`servicios/desempate.py`).
  - **Categorías**: `categoria` en el torneo suelto, y **eventos** (`/api/eventos`, pantalla en `/torneos/eventos/:id`) que agrupan categorías —cada una un torneo— con las mismas fechas (se copian y se actualizan) y canchas (programar fuera de ellas es un 422).
  - **La grilla** (pestaña «Grilla», `GrillaDeZona`): parejas en filas y columnas, diagonal tachada en rojo, el resultado desde la fila en cada casillero (clic para cargarlo o corregirlo), PG, sets, games y puesto al costado, e **impresión** (una zona por página, apaisada).
  - **Un agujero del CHECK `ck_torneos_zonas_coherente` cerrado**: con `cantidad_zonas` o `clasifican_por_zona` en `NULL` el CHECK aceptaba el torneo por zonas.
  - Tests: `tests/test_americano.py` (todos contra todos, sets a 6 y a 9, desempates con cara a cara, sin llaves, eventos, migración) y, en el frontend, `GrillaDeZona.test.tsx`, `FormularioDeTorneo.test.tsx`, `FormularioDeEvento.test.tsx`, `Evento.test.tsx`, `Torneos.test.tsx` y casos nuevos en `Torneo.test.tsx`.

- **El esquema del core y del buffet se arma de a un arranque por vez: con `WEB_CONCURRENCY=2` un worker ya no muere con `TimeoutError: 'libracommerce.esquema' ... 120 s`** (2026-10-24; sin migración). `facturacion.configurar()` son dos transacciones (la 1ª toma el candado del core y el de LibraCommerce; la 2ª, `crear_venta_links` y el cierre diario, sólo el de LibraCommerce y pide una tabla del core con el `CREATE TABLE ... REFERENCES`). Si el otro worker está en su 1ª, cada uno espera lo del otro y PostgreSQL no ve el ciclo porque el candado se reintenta con `pg_try_advisory_xact_lock`: dura hasta que se rinde a los 120 s. Sólo en el primer arranque tras un release que suma una tabla con FK al core. Ahora `configurar()` corre el esquema y la caja por defecto adentro de `una_vez_al_arrancar("libraclub-esquema-core")`, como VentaLibra y Contalibra. Tests: `tests/test_arranque_varios_procesos.py` (dos arranques con el entrelazado forzado y tres sin coreografía).

- **El frontend conoce el nodo sin conexión: el 202 `en_cola`, las etiquetas de reserva y la cola de ARCA** (2026-10-24; cablea libra-ui v0.180.0, ADR-094, sobre ADR-022 y ADR-023; sólo frontend, sin migración). Fuera de un nodo no cambia nada visible.
  - **Facturar una reserva** (`DetalleDeReserva`): el 202 `{en_cola: true, …}` ya no se toma por una factura («Factura undefined 0000-NaN»); `registrar` de `useAvisoDeEnCola` lo reconoce y `<AvisoEnCola>` dice «Se emite al volver la conexión.» en el lugar del botón. Los 409 `solo_en_el_central` / `sin_conexion` ya mostraban su `mensaje` (`lib/api.ts`).
  - **Etiquetas** (`EtiquetasDeReservaDelNodo`) en el detalle y en cada casillero de la agenda: «Sin subir al central» para el id negativo y «En conflicto» para `en_conflicto`. **No se llama «Provisoria»**: `provisoria` sigue siendo el turno retenido esperando el pago del portal y no lleva la etiqueta del nodo. `AvisoDeConflictos` queda en el producto, como dice el ADR-094.
  - **Ruta `/cola`** (`pages/Cola.tsx`, `BandejaDeLaCola`) y su entrada de menú «Cola de comprobantes», **sólo en un nodo**: reintentar, descartar y marcar emitido son de admin (`puedeResolver`), el mostrador la mira. LibraClub no tiene `BandejaDeComprobantes`, así que va en pantalla propia y no como pestaña.
  - **Cartel «Sin conexión»** (`conexionDelNodo`) con la frase de la cola (`TEXTO_CARTEL_SIN_CONEXION_CON_COLA`). Lee `GET /api/nodo/cola?limite=1` y no `/api/nodo/conexion`, que LibraClub no monta: la cola contesta los mismos `es_nodo` y `en_linea`.
  - **Un id negativo no se muestra como número de reserva** (`lib/reservas.ts`, `numeroDeReserva`): en la cola y en Devoluciones dice «sin número todavía».
  - Tests: `DetalleDeReserva.nodo.test.tsx`, `Agenda.nodo.test.tsx`, `Cola.test.tsx`, `reservas.test.ts` y un caso en `Devoluciones.test.tsx`; `/cola` entra al guard de íconos del menú.

- **Cancelar un conflicto devuelve siempre la seña, y los clientes dados de alta en el nodo suben como provisorios** (2026-10-24, addendum a ADR-022; decisiones del humano; sin migración).
  - **Cancelar una reserva `en_conflicto` devuelve la seña entera**, aunque la política de la sucursal diga otra cosa (también sin política cargada): por MercadoPago si el pago entró por el portal, por la caja si fue un cobro de mostrador. Vale en el central, donde se resuelve, y para todo camino que cancele un conflicto (`/api/reservas-en-conflicto/{id}/resolver`, la agenda y el portal). Queda auditado: el motivo de la reserva empieza con `Conflicto de reserva del nodo` y el concepto del egreso de caja también. Una reserva común sigue por la política.
  - **`app/servicios/clientes_nodo.py`**: en un nodo, el alta de un cliente del club (`POST /api/clientes`) nace con id provisorio negativo y encola `cliente_club.alta` en la misma transacción; el central la aplica de forma idempotente (mapeo `(nodo, 'clientes', id)`) y no duplica a la misma persona (por `documento`, `cuit` o `email`, nunca por el nombre; ver ADR-022). La `reserva.creada` de un cliente provisorio se materializa con el id definitivo. Fuera de un nodo, el alta es la de siempre.
  - **En un nodo**: editar o borrar un cliente da 409 (`sin_conexion` o `solo_en_el_central`) —desde el 2026-10-25 un provisorio sí se edita— y el portal de jugadores no registra cuentas (409 `solo_en_el_central`).
  - **Cableado** (sobre el PR 11): `offline.configurar_clientes()`, `registrar_clientes` en el despachador del central, `AltaEnNodo("clientes")` en `ALTAS_EN_EL_NODO`, y `clientes` sale de `TABLAS_SOLO_LECTURA` y de la guarda general de los maestros (antes `POST /api/clientes` en un nodo era 409).
  - Tests: `tests/test_cancelar_conflicto.py`, `tests/test_clientes_en_el_nodo.py` y `tests/test_clientes_aplicador_central.py` y `tests/test_nodo_clientes.py` (el armado real).

- **LibraClub sin conexión: el buffet, la caja, el pago de una reserva y la factura conjunta en el nodo de LibraEdge** (2026-10-24, ADR-023; PR 11 del plan de la versión de escritorio; **migración `0014_libraedge`**, aditiva). Decisión del humano (2026-10-22): sin internet, en el club se vende en el buffet, se opera la caja, se cobran las canchas, se cargan consumos y se dan reservas (estas últimas, PR 12). **Fuera de un nodo no cambia nada.** Exige `libracore` v1.191.0, `libracommerce` v0.73.0 y `libraedge` v0.22.0 (**temporalmente pineado al commit `1d7ab0a` de su `develop`**: v0.22.0 no tiene tag; se cambia antes del merge).
  - **`app/offline.py`**: `nodo()`, `en_linea()`, `CONEXION`, `OUTBOX`, `GANCHOS_DE_CAJA`, la cola de ARCA (`cola()`), el cliente del ticket y el `aprovisionamiento` (qué baja al nodo y qué no: el nodo genera ventas, stock, caja, facturas y la cola, que suben como operaciones; **nunca** se espeja `arca_credenciales_servicio` ni el almacén de claves). **`app/routers/sincronizacion_offline.py`**: el despachador del central (los trece tipos de la capa ERP, `cola.pedido`, `club.factura_conjunta`) con `prestar_ticket=ta_para_el_nodo` y la carga inicial del stock. Se montan siempre, con `create_nodos_router` (admin) y `create_canje_router` (público).
  - **El buffet y la caja suben**: `ganchos_del_consumo` envuelve con `con_outbox` (el vínculo con la reserva sale en el payload y el central lo traduce con `tablas_de_origen={"reserva": "reservas"}`); `servicios/caja.py` pasa `ganchos=` en sus cuatro escrituras y el cierre diario también. La reposición del buffet sube como `stock.movimiento`. `ubicacion_de` no crea el depósito en un nodo (409: viene del central).
  - **El pago de una reserva** sube como `caja.movimiento`; su vínculo es la referencia (`reserva-<id>-<azar>`). Con el id provisorio de una reserva dada en el nodo (`reserva--1-…`) el pendiente lo entiende, el central traduce la referencia con el mapeo (`aplicar_movimiento_de_club`) y el nodo sigue viéndolo cuando la reserva recibe su id definitivo (`libraedge_mapeo`).
  - **La factura conjunta** (reserva más consumos) en un nodo **va a la cola de ARCA** (`libracore.cola_arca`): `POST /api/reservas/{id}/facturar` contesta 201 si sale en el momento y **202 `en_cola`** si no hay conexión; al volver se emite **una sola vez**, con el ticket que presta el central y **sin numerar nunca local**. Sube como `cola.pedido` + `club.factura_conjunta`; el central la escribe con el mismo número y CAE, la ata a la reserva y a sus cobros. En el central se factura como antes (`comprobante_de` se separó de `facturar_reserva`; mismas líneas y total).
  - **Lo que el nodo no hace** (409 `solo_en_el_central`; las lecturas pasan): maestros, usuarios, cajas, catálogo del buffet, cuenta corriente, devoluciones, facturación manual y cobro con QR. La barra del pie muestra la conexión del nodo y las facturas en cola.
  - **El nodo no escribe `reservas.factura_id`** (guarda del espejo, `LE001`): el vínculo con su factura es una marca en `facturas.observaciones`.
  - **Despliegue**: motores → central → nodos; `libracommerce-migrar` (0010) y `libracore-migrar` (0029) en el central antes de que un nodo suba una venta con vínculo o un pedido de la cola. `libraedge` es público: el CI no necesita deploy key.
  - Tests: `tests/test_nodo_buffet_y_caja.py`, `tests/test_nodo_factura_conjunta.py`, `tests/test_nodo_roles_y_aprovisionamiento.py` (nodo encola; el central materializa con el vínculo; la factura sin conexión va a la cola y se emite una vez; el central factura igual; matriz de roles; el aprovisionamiento no espeja lo prohibido y se puede registrar un nodo).
  - **Abierto**: `LIBRAEDGE_CARGA_INICIAL` en la definición de libraedge; el frontend no conoce el 202; el alta de clientes en el nodo; lo cobrado en el central no baja a la caja del nodo. Ver ADR-023.

- **Reservas en el club sin conexión: exclusión partida, `en_conflicto`, `reserva.creada` y conflictos** (2026-10-24, ADR-022; PR 12 de «LibraCargo y LibraClub en la versión de escritorio»; **con migración `0013_reservas_en_el_nodo`**, aditiva y reversible). Fuera de un nodo, la web y el portal no cambian.
  - **Exclusión partida por el signo del id**: `ex_reservas_sin_superposicion` (el nombre de siempre) cubre `id > 0` y `ex_reservas_del_nodo_sin_superposicion` cubre `id < 0`. En la base de un nodo conviven una reserva dada sin conexión y la que bajó del central en el mismo horario, sin trabar la sincronización.
  - **Estado `en_conflicto`** (no ocupa la cancha) y dos columnas nulas, `conflicto_con_id` y `estado_previo`. Una reserva del club que al llegar al central choca con otra queda en conflicto: **gana la que llegó primero**.
  - **`app/servicios/reservas_nodo.py`**: las operaciones `reserva.creada` (con su aplicador idempotente y el mapeo de `libraedge_mapeo`) y `reserva.estado`, y las funciones para que el PR 11 las registre: `configurar`, `desde_el_outbox`, `registrar_en`. Sin `configurar()`, o fuera de un nodo, no hacen nada. `libraedge` se importa recién al usarse y todavía no es dependencia.
  - **En un nodo**: la reserva nace con id provisorio negativo y se encola en su misma transacción; cancelar o marcar jugada una reserva que no se dio ahí da 409 `sin_conexion` (409 `solo_en_el_central` si hay conexión); los bloqueos y las series dan 409 `solo_en_el_central`. El 409 con `{codigo, mensaje}` se muestra con su texto en el frontend.
  - **Portal**: «Mis reservas» cuenta una reserva `en_conflicto` como «En revisión: el complejo te va a contactar» (antes de este PR ese estado no existía; sin la etiqueta el jugador habría leído «Falta pagar»).
  - **API de conflictos**: `GET /api/reservas-en-conflicto` y `POST /api/reservas-en-conflicto/{id}/resolver` (`mover` o `cancelar`; sólo en el central). `AvisoDeConflictos` en la agenda. La pantalla visual es del kit (PR 13).
  - Tests: `tests/test_exclusion_partida.py` (incluye subir, bajar y volver a subir la `0013`), `tests/test_reservas_en_el_nodo.py`, `tests/test_reservas_aplicador_central.py` (se saltea sin `libraedge`), `tests/test_conflictos.py` y `frontend/src/components/AvisoDeConflictos.test.tsx`.

- **La venta del buffet nace por `registrar_venta` del motor** (2026-10-24, ADR-021; PR 10 del plan de la versión de escritorio; sin migración). `registrar_consumo` pasa de `save_sale` + `confirm_sale` a `libracommerce.erp.ventas.crear_venta_directa`, la puerta que usan ContaLibra, RestoLibra y VentaLibra, para que un nodo de LibraEdge la encole y la suba al central. **Sin cambio visible**: mismos totales, mismo vínculo (`source_type='reserva'` + `source_id`, o `'mostrador'`), misma caja (`servicios/caja.py`, referencia `buffet-<id>`; el motor no escribe pagos), mismo stock del depósito de la sucursal y misma factura conjunta.
  - **`ganchos_del_consumo(reserva_id)`**: su `al_registrar_venta` pone el vínculo (`UPDATE sales`) y anota el alta en `actividad_log`; con `con_outbox` corre antes de encolar, así el payload sale con `source_type` / `source_id` (ADR-072 de LibraCommerce). `GANCHOS_PROPIOS` (numerador y sin turno) es lo que usará el central.
  - **Numeración** (`BUF-000123`): sigue al último `%BUF-%`, con o sin prefijo de nodo, y corre con el write-lock del motor (reintenta si choca).
  - **`facturacion.configurar()` crea `venta_links`** (`crear_venta_links`): `registrar_venta` la lee al terminar toda venta cobrada. Idempotente; se crea sola en `dev` y `demo` al arrancar.
  - Cambia por dentro: `unit_cost_snapshot` queda `NULL` sin costo cargado (antes `0`); los movimientos de stock llevan `source_type='venta'` y nota `Venta ID n`; `status_detail='cobrada'`.
  - **No se mueve el cobro con QR** (`preparar_consumo` / `confirmar_consumo`): el motor no tiene cómo confirmar una venta pendiente sin pago; sigue siendo del central.
  - Tests: `tests/test_buffet_registrar_venta.py` (vínculo de reserva y de mostrador, totales, caja, stock, factura conjunta, resumen, log, numeración, paso por `registrar_venta`, gancho + `con_outbox`, todo-o-nada, `venta_links`).

- **Se va la variable del core: LibraClub es una sola base** (2026-10-22, addendum a ADR-020; sin migración ni cambios de API). `libracore-unir-bases` (ADR-078) unió `libraclub-dev` y `libraclub-demo`, y no hay clientes reales: no queda ninguna instancia con `libraclub_core`.
  - **Compose de dev**: sin `LIBRACLUB_LIBRACORE_DATABASE_URL` ni `LIBRACOMMERCE_MIGRAR_URL`. `Config.desde_entorno()` cae a `DATABASE_URL` y `libracommerce-migrar` migra la del dominio. `libracore-migrar --prefijo libraclub` sin la variable del core exige **libracore >= v1.190.1** (con `v1.190.0` falla con `SinURL`): el pin se sube en este mismo PR.
  - **Suite y CI**: la suite corre con una sola base; se retiró la de dos (`<base>_core`, plantilla `armada`, `LIBRACLUB_SUITE_UNA_BASE`) y el paso «Tests (una sola base)» del CI. El check protegido `test` no cambia de nombre. El código que soporta una variable del core con otra base se queda, y lo miden los tests de `tests/test_una_sola_base.py` sobre bases descartables.
  - **`scripts/reset_demo.sh`**: sin la variable en el contenedor, la base de LibraCore es la del dominio (antes abortaba). **Scripts, README y comentarios** dejan de presentar `libraclub_core` como algo vigente.
  - Tests nuevos o reescritos: el compose no declara las variables del core; `libracore-migrar` cae al dominio sin la variable (control: respeta una variable con otra base).
  - `libraclub_core` en el VPS queda sin uso; borrarla espera el OK del humano.

- **Una sola base: dominio y LibraCore juntos, y el código anda con las dos formas** (2026-10-22, ADR-020; decisión del humano). **Este PR no une ninguna instancia**: prepara el código para desplegarse antes de que `libracore-unir-bases` una `libraclub-dev` y `libraclub-demo`, y para que un alta nueva nazca con una sola base.
  - **Tabla de versión propia**: `alembic_version_libraclub` (antes `alembic_version`, el nombre de la cadena del motor). `migrations/env.py` la **renombra sola** —con su clave primaria— si encuentra la vieja con una revisión de este producto, en la misma transacción que la migración; una base nueva crea la suya; una base unida con la del motor no confunde las dos. Con `include_object` como LibraCargo.
  - **Config**: sin `LIBRACLUB_LIBRACORE_DATABASE_URL`, o con la misma base que el dominio, todo usa la del dominio (`Config.core_en_la_del_dominio`, `app.config.misma_base`): el respaldo no declara el core dos veces, `facturacion.configurar` no intenta crear una base que ya existe, `app/database.py` cae al dominio. Con dos bases, igual que hoy. Cambio visible: `crear_app()` sin la variable del core ya no es «instancia sin facturación»: factura contra el dominio.
  - **Cadena de migraciones**: suma `libracommerce-migrar upgrade --prefijo libraclub` (hoy el buffet lo crea `init_schema()` al arrancar), en el orden libracore, libracommerce, libraauth, alembic. El compose de dev declara `LIBRACOMMERCE_MIGRAR_URL` sobre la base del core mientras tenga dos: sin eso crea 25 tablas vacías en el dominio y la unión se corta (21 `choque_de_tablas`). `nuevo_cliente.py` y `panel_admin.py` declaran `base_core_separada=False`.
  - **Suite**: corre con dos bases (por defecto) y con una (`LIBRACLUB_SUITE_UNA_BASE=1`); el CI corre las dos. `tests/test_una_sola_base.py` mide el autorrenombre, la base unida, la config, el respaldo y la cadena entera sobre bases descartables. `scripts/reset_demo.sh` no resetea dos veces la misma base.
  - **Revisión `0012_actividad_log`**: lleva `actividad_log` a la forma de `libraauth` (`ts TIMESTAMP`, `entidad_id VARCHAR`) sea cual sea el orden de las cadenas. Con una sola base, `libracommerce-migrar` la crea primero con `ts TEXT`/`entidad_id INTEGER` y toda escritura auditada del dominio moría con `DatatypeMismatch`; en `dev` y `demo` ya tiene la forma buena y no hace nada.
  - Sin cambios de API.

- **La barra de estado del pie** (2026-10-20; pedido del humano; libracore ADR-075, libra-ui ADR-083; sin migración). Una línea chica al pie de todas las pantallas con el usuario, el certificado de ARCA que vence en menos de 30 días o venció, el último respaldo y la versión (este producto no tiene LibraEdge: esa parte no se muestra). `app/main.py` monta `build_estado_del_sistema_router` del motor (`GET /api/estado-del-sistema`, con `require_staff`: cualquier rol de la instancia; ARCA, respaldo y versión del motor, sólo el admin) con la carpeta de respaldos. Frontend: `createLayout({ barraDeEstado })`. La sucursal es la elegida en el selector (`barraDeEstado: { useSucursal }`). Tests: `tests/test_estado_del_sistema.py`. Pines: **libracore `v1.187.0`** (antes `v1.186.2`) y **libra-ui `v0.170.0`** (antes `v0.168.0`; trae también el ADR-084 del kit, «Sucursal sin internet» dice que en el local se entra por la copia local). Sin migración.

### Cambiado

- **Rotación sin corte del token de servicio** (libraauth `v0.52.0`): `docker-compose.yml` y `.env.example` declaran **`LIBRA_SERVICE_TOKEN_ANTERIOR`** con default vacío; mientras está definida, la instancia acepta el token nuevo y el anterior (`panel_admin.py token-servicio <slug> --rotar|--cerrar`, ADR-071 de libracore). Sin el pin de libraauth `v0.52.0` la variable no hace nada. Sin migración, sin cambio de código.

- **Todo campo donde se elige un cliente ofrece darlo de alta ahí mismo** (libra-ui `v0.158.1`, ADR-071 del kit; ADR-019 de este producto). Pin de **libra-ui `v0.158.1`** (antes `v0.157.0`; arrastra `@playwright/test` `1.64.1`, pedido como peer opcional por el kit). El campo «Cliente» de la **reserva** (`DialogoDeReserva`) y el de **Nueva cancha fija** (`FormularioDeSerie`) pasan a `SelectCliente`: el buscador de siempre con el botón «Agregar nuevo cliente» al lado, que abre un panel con nombre, teléfono y email. El cliente se crea **en el panel** (`POST /api/clientes`, lo puede hacer un encargado) y queda elegido. Se retira el «Cliente nuevo» propio de la reserva, que reemplazaba el select y creaba al reservar. Cambio visible: ya no se crea el cliente junto con la reserva, así que una reserva que falla (409 por turno ocupado) no deja un cliente huérfano ni lo duplica al reintentar. **«Nueva cancha fija» aparece aunque no haya clientes cargados** (antes se escondía el botón): el cliente se da de alta en el mismo formulario. Un helper compartido, `frontend/src/lib/clientes.ts` (`crearClienteParaSelect`, `opcionDeCliente`), copia el texto del backend a `detail` para que el panel lo muestre en vez de «Error de conexión.». «Copiar datos de…» de Facturas (`FacturaNueva`) lleva la marca `cliente-sin-alta` con su motivo: no elige a quién se factura. Guard nuevo: `frontend/src/test/campos-de-cliente.test.ts` (`libra-ui/auditoria-de-clientes`). Sólo frontend; sin migración.

- Pines: **libracore `v1.173.0`** (antes `v1.170.0`) y **libra-ui `v0.156.0`** (antes `v0.153.0`); libraauth sigue en `v0.51.0` y **libracommerce en `v0.16.4`** (el salto pendiente queda aparte). **Sin migración.** libracore `v1.171.0` (ADR-058): un cobro de factura no puede superar lo que falta (409). `v1.172.0` (ADR-059 y ADR-060): las notas de crédito con CAE restan de lo pendiente y el cobro entra por el turno de caja desde el motor. `v1.173.0` (ADR-061, `libracore.demo`): una demo no habla con ARCA ni muestra datos fiscales reales. libra-ui `v0.154.0` (sin desbordes a 390 px, contraste AA), `v0.155.0` (ADR-068: «Acreditada» y «pendiente» del motor) y `v0.156.0` (ADR-069: el error de la consulta de CUIT lleva al tutorial de Padrón A13).

- **El cobro de una factura entra por el turno con el cobro del motor, y tiene tope** (libracore `v1.172.0`, ADR-060). Se borra `_cobrar_del_turno` (`app/routers/facturas.py`), el hook que reemplazaba la escritura del motor, y `build_comprobantes_router` se monta con `exigir_turno=True`, `usuario_del_turno=lambda u: u["id_dominio"]` y `validar_cobro=_validar_cobro` (que conserva lo propio: 409 si la factura es a cuenta corriente y 400 ante un medio que la caja de este producto no ofrece, antes de escribir nada). Con eso el cobro de `POST /api/facturas/{id}/cobrar` gana el tope de lo pendiente (409, con lo que falta) y el candado de la factura, que el hook propio no tenía. **`POST /api/caja/cobros` con `factura_id`** (`app/servicios/caja.cobrar`) escribe dentro de `libracore.cobros.transaccion_de_cobro`: no puede cobrar de más (409; 404 si la factura no existe) y dos cobros simultáneos que la superan, entra uno; `registrar_movimiento` y `registrar_ingreso` aceptan `conn=`. **Sin tope, a propósito:** el cobro con QR (`cobro_qr.py`, la plata ya entró) y el cobro de un turno de la agenda (`reservas.py`, cuyo pendiente es el de la reserva con su buffet y no el de la factura). Cambio visible: un cobro con un medio desconocido y sin caja abierta ahora da 400 (antes 409), porque se valida el medio antes de mirar el turno.
- **Botón «Consultar en ARCA» en el alta de un cliente.** `app/main.py` monta `build_consultar_cuit_router` del motor (`GET /api/consultar-cuit/{cuit}`): completa razón social, domicilio y condición de IVA desde el padrón (`ws_sr_padron_a13`). Sin certificados, 503; si ARCA no delegó el servicio, 403 con el paso a seguir y un enlace «Cómo habilitarlo» al tutorial de Configuración → Integraciones. El componente propio repite la URL del tutorial porque libra-ui `v0.156.0` no exporta `URL_TUTORIAL_PADRON` (está en `src/configuracion/arca-tutorial.ts`, sin entrada en `exports`).
- **La demo no queda con datos fiscales reales** (ADR-061). Tests de la semilla con `libracore.demo` (`auditar_literales` sobre el texto y `auditar_datos_fiscales` sobre la base): `tests/test_seed_demo_fiscal.py`.

- Pines: **libracore `v1.170.0`** (antes `v1.168.0`), **libraauth `v0.51.0`** (antes `v0.50.0`) y **libra-ui `v0.153.0`** (antes `v0.152.1`). **Sin migración.** libracore `v1.169.0` suma `soltar_fk` (ADR-056; sin efecto en este producto, la usa LibraDesk). libracore `v1.170.0`: `delete_client` bloquea la baja de un cliente con cuenta corriente (`cc_pagos`, `cc_debitos`, `recibos` y `cc_asientos` con rol cliente; ADR-057) con un `ValueError` que dice que se puede desactivar. libraauth `v0.51.0`: el responsable puede aceptar por adelantado la próxima versión de los Términos (ADR-024). libra-ui `v0.153.0`: tras el gate de Términos, un aviso no bloqueante «Aceptar / Más tarde» (tarjeta abajo a la derecha, ADR-066). Efecto en este producto: ninguno en la baja, que usa sus propios maestros y no `delete_client` del motor.

- **Varios procesos listos (todo sigue en 1) y registro de errores** (2026-10-13, ADR-018; libracore `v1.159.0`, libraauth `v0.50.0`, libra-ui `v0.142.1`). Las siembras de arranque corren serializadas (`una_vez_al_arrancar`), el captcha anota los desafíos usados en la base (`UsadosEnBase`), el compose de `-dev` acepta `WEB_CONCURRENCY` (por defecto 1) y un 500 deja una línea en `errores/errores.jsonl` con un `ref` que ve el usuario (la pantalla «Algo falló» de libra-ui lo muestra). **Con migración de libraauth** (`0003_captcha_usados`), que corre antes de uvicorn. Sin migración propia.

- **Íconos del catálogo de la familia** (libra-ui `v0.125.0`, ADR-035). El menú y los títulos de pantalla toman el ícono de `libra-ui/iconos-identidad`: un concepto, un ícono, el mismo en los ocho productos. Cambios visibles: **Cuenta corriente** pasa de `NotebookText` a `BookOpen`; **Cierre diario** de `ClipboardCheck` a `CalendarCheck`; **Cajas** (los mostradores, en Maestros) de `Wallet` a `SquareStack`, porque `Wallet` es la **Caja**; **Turnos de caja** y su detalle de `Wallet` a `Clock`; **Caja por medio de pago** de `Wallet` a `Coins`; y **Horario de atención** de `Clock` a `CalendarClock`, porque `Clock` es del turno de caja. **Turnos fijos** conserva `Repeat`: es una reserva que se repite, no el turno de caja. El resto del menú conserva su dibujo, ahora desde el catálogo. Sólo frontend; sin cambios en la API ni migración. **Pide `libra-ui` v0.125.0.** Un test nuevo (`frontend/src/test/iconos-del-catalogo.test.ts`) falla si una entrada del menú o un título se aparta del catálogo.

- **libracore `v1.141.0`** (2026-10-06; antes `v1.140.0`). El emisor de los PDF se resuelve por documento (ADR-031 del motor): config de la instancia, después el `emisor_id` del comprobante, después lo que aporte el producto; acepta el logo como contenido (`logo_bytes`). El archivo de la factura lleva el id, así una nota de crédito no pisa a su factura. Sin migración; para quien no aporta nada, los PDF salen iguales.
- **libracore `v1.140.0`** (2026-10-06; antes `v1.139.0`). Suma la pre factura del motor (ADR-030): documento no fiscal con número interno, PDF y envío por correo, sobre la bandeja de comprobantes. **Con migración del motor**: `0021_pre_factura`, que agrega columnas vacías a `comprobantes_pendientes`. La bandeja de siempre no cambia.
- **libracore `v1.139.0`** (2026-10-06; antes `v1.138.0`). La cuenta corriente de clientes se lee **sólo** del libro (ADR-029 del motor): se retiran el saldo calculado y el interruptor `LIBRACORE_CC_DESDE_EL_LIBRO`. Sin migración. Lo cargado por fuera de los escritores del motor se ve después de `libro_de_clientes.reconstruir()`.
- **libracore `v1.138.0`** (2026-10-06; antes `v1.137.1`). Las lecturas de la cuenta corriente de clientes pueden salir del libro (ADR-028 del motor), detrás del interruptor por instancia `LIBRACORE_CC_DESDE_EL_LIBRO`, **apagado por defecto**: sin encenderlo no cambia nada. Sin migración.
- **libracore `v1.137.1`** (2026-10-06; antes `v1.136.1`). La cuenta corriente de clientes también como libro, **en sombra** (`libracore.db.libro_de_clientes`, ADR-027 del motor): los escritores del motor asientan cada pago, débito, cobro a cuenta y venta fiada en `cc_asientos`, y el saldo se sigue leyendo calculado. **Con migración del motor**: `0020_origen_del_asiento`, que agrega una columna vacía. La `v1.137.1` no rompe una base sin `cc_asientos`. LibraClub avisa al libro cuando vincula un cobro a su factura (`servicios/caja.py`).
- **libracore `v1.136.1`** (2026-10-06; antes `v1.135.0`). Suma el libro de cuenta corriente de terceros, opcional (`cc_asientos` y `libracore.db.libro_de_terceros`, ADR-026 del motor). **Con migración del motor**: `0019_libro_de_terceros`, que crea una tabla vacía y deja `cc_asientos.created_at` y `cierres_diarios.created_at` en hora de Argentina. Este producto no lo usa: su comportamiento no cambia.

- **libracore `v1.135.0`** (2026-10-05; antes `v1.134.0`). Las funciones del comprobante aceptan `conn=` para emitir dentro de la transacción del producto (ADR-025 del motor; sin `conn`, nada cambia) y el dinero del motor se guarda exacto en PostgreSQL (ADR-024): **migración `0018` del motor**, que pasa 33 columnas de dinero de `DOUBLE PRECISION` a `NUMERIC` sin redondear. La lectura sigue siendo `float`: el comportamiento de este producto no cambia.

- **libracore `v1.134.0`** (2026-10-05; antes `v1.132.0`). Trae el emisor opcional de cada comprobante (`facturas.emisor_id`, ADR-021 del motor), la anulación con rastro de un comprobante sin CAE (`POST /api/facturas/{id}/anular`, ADR-022) y el registro con número tipeado (ADR-023); incluye v1.133.0 (`libracore.spa`, la SPA del motor, que este producto no adopta todavía). **Con migración del motor**: `0016` y `0017` (columnas nuevas en `facturas` y el índice de numeración por emisor y ambiente); las aplica el arranque (`init_core_schema`) y `alembic upgrade head`. Para este producto no cambia el comportamiento: no pasa emisor.

- **libracore `v1.132.0`** (2026-10-05; antes `v1.131.0`). Suma `libracore.arca_wsfecred` (consultas al registro de FCE de ARCA) y `GET /api/facturas/fce/corresponde` (¿a esta factura le corresponde ser FCE?, para avisar antes de emitir; ADR-019 del motor). Nada cambia en la emisión. Sin migración.

- **libracore `v1.131.0`** (2026-10-05; antes `v1.127.0`). Trae la **nota de crédito parcial** con tope acumulado (v1.130.0: `{"importe": ...}` en `POST /api/facturas/{id}/nota-credito`; sin él, la total de siempre), la marca de cada nota en la cuenta corriente (v1.128.0), `build_nota_de_credito_router` (v1.129.0) y la nota total de una FCE frenada antes de ir a ARCA (v1.131.0). Cambia sólo `notas_de_credito` y `facturas_router`. Sin migración.

- **libracore `v1.109.0` y libra-ui `v0.73.2`** (2026-09-17). La copia externa
  del backup sale cifrada con `rclone crypt`, o no sale —eso corre en el host y
  ya está desplegado ahí—. Lo que llega con este pin: la pantalla *Datos /
  Backup* nombra la **clave privada de ARCA** y dice que la copia externa va
  cifrada; el estado deja de dar "al día" una copia que subió sin cifrar; y el
  botón de backup arma el mismo ZIP que el cron (todas las carpetas de `data/`,
  `arca_certs/` incluida). Como el pin de `libra-ui` venía de `v0.72.1`, trae
  además lo de `0.73.0` y `0.73.1`: el aviso en un modal cuando el ticket no se
  puede imprimir, y las fechas `dd-mm-aaaa` en los listados de comercio.

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

- **«Nueva cancha fija» ya no borra la pantalla de resultado apenas aparece.** El `useEffect` de `FormularioDeSerie` reseteaba el formulario cada vez que cambiaba la identidad de `canchas` o `clientes`, y `TurnosFijos` recarga ambos en `onCreada` (y arma `canchas` con un `filter` en cada render): el resumen de turnos generados y salteados se reemplazaba por el formulario vacío. Ahora resetea sólo al abrir (cerrado → abierto). Tests en `FormularioDeSerie.test.tsx`. Sólo frontend; sin migración.
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
