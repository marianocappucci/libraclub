# Tareas

Trabajo concreto vigente. Lo estratégico está en `ROADMAP.md`.

## F1 — Fundación

### Backend

- [x] Esqueleto: config, db, tiempo, auth, spa, asgi, salud
- [x] Modelo: sucursales, canchas, tarifas, clientes, reservas
- [x] Migración inicial con `btree_gist` y el constraint de exclusión
- [x] Servicio de tarifario: resolver el precio de un turno
- [x] Servicio de reservas: alta, cancelación, bloqueo, serie recurrente
- [x] Servicio de disponibilidad: la grilla de una semana
- [x] Routers de sucursales, canchas, tarifas, reservas y disponibilidad
- [x] `GET /admin/resumen` — ADR-009
- [x] Tests de API extremo a extremo: alta completa, choque 409, 422 sin tarifa
- [ ] Auditoría de quién tocó qué (patrón de LibraCargo). Los campos
      `created_by`/`updated_by` **existen en el modelo y nadie los llena**:
      hoy son cuatro columnas que se ven como trazabilidad y no lo son.
- [x] **Router de usuarios** (`/api/usuarios`), el camino por el que el
      backoffice de la suite administra esta instancia. Rol admin **o** token de
      servicio; con `LIBRA_SERVICE_TOKEN` sin definir se comporta igual que
      `require_admin`, así que no ponerlo no abre nada.

### Frontend

- [x] Login, layout con selector de sucursal persistente
- [x] Grilla semanal de la agenda, con precio en los turnos libres
- [x] Listado de canchas y de tarifas
- [x] Helper único de fechas (`src/lib/fechas.ts`), con tests
- [x] **Alta de reserva desde la grilla.** Click en un turno libre → diálogo con
      cliente (existente o nuevo), turnos, origen, estado y observaciones.
      Verificado en un navegador real, no sólo con tests.
- [x] Detalle de una reserva ocupada, con las acciones que su estado permite:
      confirmar, marcar jugada, no vino y cancelar (con motivo obligatorio).
- [x] **ABM de canchas y tarifas desde la UI**: alta, edición y baja, con los
      botones de escritura escondidos para quien no es admin. Verificado en un
      navegador real, incluida la baja que da 409 por tener reservas y su
      control positivo (una que sí se puede borrar).
- [x] **ABM de sucursales y clientes desde la UI**, con sus pantallas y su
      entrada en el menú. Sucursales es de admin; clientes lo puede escribir un
      encargado. Clientes tiene buscador por nombre, teléfono o documento, y un
      filtro para ver los dados de baja.
- [ ] **Integrar `libra-ui`.** El estándar de la familia es
      Tailwind + shadcn/ui + `libra-ui`; hoy hay Tailwind y componentes propios,
      para que el arranque no dependiera de resolver el kit compartido.

### Verificación del gate

- [x] **Dos transacciones concurrentes por la misma cancha, una sola gana.**
      `tests/test_concurrencia.py`, con `threading.Barrier` para que sean
      simultáneas de verdad y no secuenciales disfrazadas.
- [x] Control positivo: con el constraint dropeado, el mismo test da
      `["ok", "ok"]`. Sin ese control, el verde de arriba no prueba nada.
- [x] Un tercer test verifica que el constraint volvió: el `finally` que lo
      repone es justo donde no conviene confiar.

## Decisiones de la UI que valen como regla de negocio

- **Una reserva de N turnos manda el precio explícito.** La tarifa es por turno
  estándar y el backend **no prorratea ni multiplica**: librado a sí mismo,
  cobraría un solo turno por una reserva de tres horas. El diálogo muestra la
  cuenta (`3 × $14.000 = $42.000`) y la manda como `precio`. Multiplicar en
  silencio del lado del servidor sería inventar una regla; así el número lo ve y
  lo confirma una persona.
  > Consecuencia: con precio explícito **no se calcula seña** (el servicio no
  > inventa una seña sobre un número elegido a mano). Con un solo turno, que es
  > el caso normal, decide el tarifario y la seña sale sola.
- **Cancelar exige motivo.** Sin él, una discusión con un cliente dentro de un
  mes no se puede reconstruir.
- **Los formularios de edición mandan la fila entera.** Los endpoints son `PUT`
  y reemplazan: lo que no viaje vuelve al default del schema, y una cancha
  techada dejaría de serlo sin que nadie la haya tocado.
- **Cambiar el alcance de una tarifa limpia o completa `dia_semana` en el mismo
  paso.** `feriado` con día cargado lo rechaza un CHECK de la base, y el 422
  hablaría de un campo que el operador ya no ve en pantalla.
- **La UI esconde los botones que el servidor va a rechazar**, pero no decide el
  permiso: un POST directo salteando la pantalla sigue dando 403.
- **Los campos de texto vacíos viajan como `null`, no como cadena vacía.** Con
  `""` la fila queda con una cadena y la tabla muestra un hueco donde tendría
  que decir "no tiene". Y un `punto_venta_arca` vacío tiene que ser `null` y no
  `0`: `Number('')` es `0`, el schema pide `ge=1`, y `null` es además lo único
  que el índice único parcial deja repetir entre sucursales que todavía no
  facturan.
- **La pantalla de Sucursales lista también las dadas de baja; el selector del
  encabezado, no.** Son dos listas a propósito. Encontrado usándolo: con una
  sola lista filtrada a las activas, dar de baja una sucursal la hacía
  desaparecer de la pantalla y **no había forma de volver a activarla**.
- La tabla de transiciones del detalle es un **espejo** de la máquina de estados
  del backend, no la fuente: el servidor sigue rechazando con 409 lo que no
  corresponda. Lo que hace la UI es no ofrecer un botón que va a fallar.

## Conocidos, decididos y no arreglados

- **`HEAD /` devuelve 405.** El catch-all de la SPA sólo declara `GET`. Un
  monitor configurado con HEAD lo leería como caído. No entra en F1 porque el
  healthcheck del contenedor usa `GET /salud`; si aparece un monitor externo,
  se agrega `HEAD` al `api_route`.

## Infraestructura

- [ ] Crear el repo en GitHub y subir `main` + `develop`
- [ ] Rama default `main`, `develop` en el trigger del CI
- [ ] Deploy key SSH de solo lectura por motor, si la familia pasa a privada
- [ ] Instancia `dev` en el VPS y proxy host a `dev.libraclub.com.ar`

> `libraclub.com.ar` **ya está registrado** y resuelve a `149.50.136.218`
> (VPS Donweb), verificado el 2026-08-20.

## Pendientes que salen de decisiones tomadas

- [ ] **Proponerle a LibraGenda el constraint de exclusión** (ADR-004). Hoy su
      chequeo de solapamiento es read-then-write en Python, y Gestiolibra y
      MedLibra corren con esa carrera latente. Requiere resolver antes su capa
      dual SQLite/PostgreSQL.
- [ ] Confirmar con el humano si `sucursal` tiene que llegar también a
      ContaLibra como entidad, o si queda como diferencia entre productos.

## Supuestos a validar contra un complejo real

Nacieron sin relevamiento (ver `ROADMAP.md`, F0). No son verdades:

- Que la tarifa se resuelve por cancha + día de semana + franja + feriado.
- Que la reserva fija recurrente es semanal y sin fin, no por período.
- Que la seña es un porcentaje del turno y no un monto plano.
- Que el turno es de 60 o 90 minutos y no de duración libre.
