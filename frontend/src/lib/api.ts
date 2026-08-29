/**
 * Cliente HTTP. Mismo origen que la SPA, así que la cookie de sesión viaja sola.
 *
 * Todo lo que sale de acá habla **ISO 8601**. El `dd-mm-aaaa` es de `fechas.ts`
 * y no toca la API.
 */

export class ErrorDeApi extends Error {
  // Campo declarado y asignado a mano, no una "parameter property"
  // (`constructor(readonly status: number)`): con `erasableSyntaxOnly` —que
  // exige que quitar los tipos deje JavaScript válido— esa forma no compila,
  // porque genera una asignación que no existe en el código escrito.
  status: number

  constructor(status: number, mensaje: string) {
    super(mensaje)
    this.status = status
  }
}

async function pedir<T>(ruta: string, init?: RequestInit): Promise<T> {
  const respuesta = await fetch(ruta, {
    // `same-origin` explícito: la SPA se sirve desde el mismo proceso FastAPI,
    // y sin las credenciales toda la API contesta 401.
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (respuesta.status === 204) return undefined as T
  const cuerpo = await respuesta.json().catch(() => null)
  if (!respuesta.ok) {
    // 🔴 El `detail` de FastAPI puede ser un string (los `HTTPException` de este
    // producto) **o una lista** (los errores de validación de pydantic).
    // Mostrarlo sin distinguir deja al operador leyendo `[object Object]`.
    const detalle = cuerpo?.detail
    const mensaje = Array.isArray(detalle)
      ? detalle.map((d: { msg?: string }) => d.msg ?? '').join('; ')
      : typeof detalle === 'string'
        ? detalle
        : `Error ${respuesta.status}`
    throw new ErrorDeApi(respuesta.status, mensaje)
  }
  return cuerpo as T
}

export const api = {
  get: <T>(ruta: string) => pedir<T>(ruta),
  post: <T>(ruta: string, cuerpo: unknown) =>
    pedir<T>(ruta, { method: 'POST', body: JSON.stringify(cuerpo) }),
  put: <T>(ruta: string, cuerpo: unknown) =>
    pedir<T>(ruta, { method: 'PUT', body: JSON.stringify(cuerpo) }),
  // `T = void` para que los DELETE de siempre no cambien: los que devuelven
  // algo —anular un movimiento contesta el resumen del turno— lo declaran.
  del: <T = void>(ruta: string) => pedir<T>(ruta, { method: 'DELETE' }),
}

export interface Sucursal {
  id: number
  nombre: string
  direccion: string | null
  localidad: string | null
  telefono: string | null
  email: string | null
  punto_venta_arca: number | null
  activa: boolean
  observaciones: string | null
}

/** Lo que se manda al crear o editar una sucursal. */
export interface SucursalEntrada {
  nombre: string
  direccion: string | null
  localidad: string | null
  telefono: string | null
  email: string | null
  /** 🔴 Único entre sucursales, y lo garantiza un índice parcial en la base.
   *  La numeración de comprobantes de ARCA es por `(tipo, punto_venta)` y **no
   *  lleva CUIT**: dos sucursales con el mismo punto de venta se pisan la
   *  numeración entre ellas. `null` no colisiona — una sucursal que todavía no
   *  factura puede quedar sin punto de venta. */
  punto_venta_arca: number | null
  activa: boolean
  observaciones: string | null
}

export interface Cancha {
  id: number
  sucursal_id: number
  nombre: string
  deporte: string
  duracion_turno_min: number
  techada: boolean
  iluminacion: boolean
  superficie: string | null
  orden: number
  activa: boolean
  observaciones: string | null
}

export interface Tarifa {
  id: number
  sucursal_id: number
  cancha_id: number | null
  nombre: string
  alcance_dia: 'todos' | 'dia_semana' | 'feriado'
  dia_semana: number | null
  hora_desde: string
  hora_hasta: string
  precio: string
  sena_porcentaje: number
  vigente_desde: string | null
  vigente_hasta: string | null
  prioridad: number
  activa: boolean
}

export interface Turno {
  comienza_at: string
  termina_at: string
  libre: boolean
  precio: string | null
  reserva_id: number | null
  estado: string | null
  cliente: string | null
  motivo: string | null
}

export interface Semana {
  desde: string
  hasta: string
  /** `{ "<cancha_id>": { "aaaa-mm-dd": Turno[] } }` */
  canchas: Record<string, Record<string, Turno[]>>
}

export interface Cliente {
  id: number
  nombre: string
  telefono: string | null
  email: string | null
  documento: string | null
  cuit: string | null
  activo: boolean
  observaciones: string | null
}

/** Lo que se manda al crear o editar un cliente. */
export interface ClienteEntrada {
  nombre: string
  telefono: string | null
  email: string | null
  documento: string | null
  cuit: string | null
  activo: boolean
  observaciones: string | null
}

export interface Reserva {
  id: number
  cancha_id: number
  cliente_id: number | null
  estado: string
  origen: string
  comienza_at: string
  termina_at: string
  precio: string | null
  sena: string | null
  motivo: string | null
  observaciones: string | null
}

export const sucursales = {
  listar: () => api.get<Sucursal[]>('/api/sucursales'),
  crear: (cuerpo: SucursalEntrada) => api.post<Sucursal>('/api/sucursales', cuerpo),
  editar: (id: number, cuerpo: SucursalEntrada) =>
    api.put<Sucursal>(`/api/sucursales/${id}`, cuerpo),
  borrar: (id: number) => api.del(`/api/sucursales/${id}`),
}

/** Lo que se manda al crear o editar una cancha. */
export interface CanchaEntrada {
  sucursal_id: number
  nombre: string
  deporte: string
  duracion_turno_min: number
  techada: boolean
  iluminacion: boolean
  superficie: string | null
  orden: number
  activa: boolean
  observaciones: string | null
}

export const canchas = {
  listar: () => api.get<Cancha[]>('/api/canchas'),
  crear: (cuerpo: CanchaEntrada) => api.post<Cancha>('/api/canchas', cuerpo),
  // PUT y no PATCH: el endpoint reemplaza la fila entera, asi que el formulario
  // manda TODOS los campos. Mandar solo los tocados dejaria los demas en el
  // default del schema —una cancha techada volveria a no serlo sin que nadie la
  // haya tocado.
  editar: (id: number, cuerpo: CanchaEntrada) =>
    api.put<Cancha>(`/api/canchas/${id}`, cuerpo),
  borrar: (id: number) => api.del(`/api/canchas/${id}`),
}

/** Lo que se manda al crear o editar una tarifa. */
export interface TarifaEntrada {
  sucursal_id: number
  cancha_id: number | null
  nombre: string
  alcance_dia: 'todos' | 'dia_semana' | 'feriado'
  /** Obligatorio con `alcance_dia = 'dia_semana'`, y PROHIBIDO en los otros dos:
   *  hay un CHECK en la base y un validador en el schema. Mandar un dia con
   *  alcance `feriado` devuelve 422, no se ignora. */
  dia_semana: number | null
  hora_desde: string
  hora_hasta: string
  precio: string
  sena_porcentaje: number
  vigente_desde: string | null
  vigente_hasta: string | null
  prioridad: number
  activa: boolean
}

export const tarifas = {
  listar: () => api.get<Tarifa[]>('/api/tarifas'),
  crear: (cuerpo: TarifaEntrada) => api.post<Tarifa>('/api/tarifas', cuerpo),
  editar: (id: number, cuerpo: TarifaEntrada) =>
    api.put<Tarifa>(`/api/tarifas/${id}`, cuerpo),
  borrar: (id: number) => api.del(`/api/tarifas/${id}`),
}

/** El mínimo para dar de alta un cliente desde el diálogo de reserva.
 *
 *  Los demás campos quedan en su default del schema: un cliente que llama por
 *  teléfono para reservar da su nombre, y pedirle el CUIT en ese momento es la
 *  forma más rápida de que el encargado no lo cargue. Se completan después
 *  desde la pantalla de Clientes. */
export type ClienteMinimo = { nombre: string; telefono?: string | null }

export const clientes = {
  listar: () => api.get<Cliente[]>('/api/clientes'),
  // 🔑 El alta y la edición de clientes las puede hacer un encargado (`staff`),
  // no sólo un admin — es lo que permite tomarle la reserva a alguien que llama
  // por primera vez. Es el único de los cinco maestros con ese permiso; ver
  // `construir_abm` en el backend.
  crear: (cuerpo: ClienteEntrada | ClienteMinimo) =>
    api.post<Cliente>('/api/clientes', cuerpo),
  editar: (id: number, cuerpo: ClienteEntrada) =>
    api.put<Cliente>(`/api/clientes/${id}`, cuerpo),
  borrar: (id: number) => api.del(`/api/clientes/${id}`),
}

export const agenda = {
  semana: (sucursalId: number, desde?: string) =>
    api.get<Semana>(
      `/api/disponibilidad/semana?sucursal_id=${sucursalId}` +
        (desde ? `&desde=${desde}` : ''),
    ),
  reservar: (cuerpo: {
    cancha_id: number
    cliente_id: number
    // 🔴 ISO **con offset**, tal cual lo devolvió la grilla. No se reconstruye a
    // partir del día y la hora: el backend ya mandó el instante correcto, y
    // rearmarlo en el cliente es donde aparecen las reservas corridas tres
    // horas.
    comienza_at: string
    duracion_min?: number
    estado?: string
    origen?: string
    precio?: string
    observaciones?: string | null
  }) => api.post<Reserva>('/api/reservas', cuerpo),
  cambiarEstado: (id: number, estado: string, motivo?: string) =>
    api.post(`/api/reservas/${id}/estado`, { estado, motivo }),
}

/** El comprobante de una reserva. Los importes viajan como número porque los
 *  arma el motor de facturación, no este producto. */
export interface Factura {
  id: number
  tipo: number
  punto_venta: number
  numero: number
  fecha: string
  total: number
  /** Vacío mientras ARCA no lo haya dado. **No es un error**: la factura existe
   *  y lo que falta es el CAE. Sin certificado cargado siempre viene vacío. */
  cae: string
  cae_vto: string
}

/** Cómo se nombra un tipo de comprobante de ARCA. */
export const TIPO_DE_FACTURA: Record<number, string> = {
  1: 'A',
  6: 'B',
  11: 'C',
}

export type CobroDeTurno = {
  id: number
  fecha: string
  monto: number
  medio_pago: string
  concepto: string
  /** A qué comprobante quedó atado. `null` mientras el turno no se facturó. */
  factura_id: number | null
}

export type EstadoDeCobro = {
  /** Alquiler + buffet consumido: el mismo número que factura el turno. */
  total: number
  cobrado: number
  pendiente: number
  cobros: CobroDeTurno[]
}

/** El cobro de un turno, atado a su comprobante.
 *
 * 🔑 **No es lo mismo que la pantalla de Caja.** Ahí el cobro se carga como
 * monto más concepto libre, sin vínculo con nada — sirve para un ingreso suelto
 * y deja el comprobante del turno viéndose «sin cobrar». Acá el movimiento nace
 * sabiendo de qué reserva es y, si ya se facturó, contra qué comprobante va.
 */
export const cobroDelTurno = {
  ver: (reservaId: number) =>
    api.get<EstadoDeCobro>(`/api/reservas/${reservaId}/cobros`),
  registrar: (reservaId: number, datos: {
    monto: string
    medio_pago: string
    /** Qué parte de la cuenta se está pagando. El backend lo agrega al
     *  concepto; sin esto, tres cobros fraccionados de un mismo turno quedan
     *  con el mismo texto y montos que nadie puede reconstruir. */
    detalle?: string
  }) => api.post<EstadoDeCobro>(`/api/reservas/${reservaId}/cobros`, datos),
}

/** Un turno del día que todavía debe plata, como lo ve el mostrador. */
export type TurnoPorCobrar = {
  reserva_id: number
  cancha_id: number
  cancha: string
  deporte: string
  comienza_at: string
  termina_at: string
  cliente: string
  /** `confirmada`, `jugada`… Lo mira el cobro con QR, que no se ofrece sobre
   *  un turno cancelado. */
  estado: string
  total: number
  cobrado: number
  pendiente: number
}

/** El selector de la Caja: qué turnos hay que cobrar hoy.
 *
 * 🔑 **No es `/agenda/proximas`, aunque el nombre invite.** Esa ruta filtra
 * `comienza_at >= ahora` y el turno que se cobra en el mostrador es justamente
 * el que **está terminando**: a las 21:00, el de 20:00 a 21:30 ya no es
 * "próximo" y es el que tiene al cliente enfrente.
 *
 * Y el pendiente viene calculado del backend —alquiler más buffet consumido,
 * menos lo que entró—, no derivado acá: el mismo número que el detalle de la
 * reserva y que el comprobante. Dos pantallas restando por su cuenta terminan
 * cobrando distinto.
 */
export const turnosPorCobrar = {
  listar: (sucursalId: number) =>
    api.get<TurnoPorCobrar[]>(
      `/api/reservas/agenda/por-cobrar?sucursal_id=${sucursalId}`,
    ),
}

/** Cómo se escribe cada deporte en pantalla.
 *
 * 🔑 **El valor guardado es la clave del enum** (`padel`, `futbol`), sin
 * acentos y en minúscula, porque es lo que viaja a la base. Las cuatro
 * pantallas que lo mostraban lo escupían crudo: en la agenda se leía
 * *"Cancha 1 · padel"*, con el deporte en minúscula y sin tilde al lado de un
 * nombre propio. Reportado el 2026-08-28.
 *
 * El mapa vive acá, con los tipos de comprobante, y no en cada pantalla: cuatro
 * copias de esta lista es cómo se llega a que una diga «Padel» y otra «Pádel».
 *
 * El `?? deporte` del uso cubre un valor nuevo del enum que todavía no esté
 * acá: se ve crudo, que es feo pero no rompe. */
export const NOMBRE_DE_DEPORTE: Record<string, string> = {
  padel: 'Pádel',
  futbol: 'Fútbol',
  tenis: 'Tenis',
  basquet: 'Básquet',
  voley: 'Vóley',
  hockey: 'Hockey',
  otro: 'Otro',
}

/** Los mostradores de cada sucursal.
 *
 * 🔑 El listado lo lee el **mostrador** —es lo que elige al abrir el turno— y el
 * alta, la edición y la baja son de **admin**: dar de alta un cajón es
 * configurar el complejo, no operarlo.
 */
export const cajas = {
  deLaSucursal: (sucursalId: number) =>
    api.get<CajaDeMostrador[]>(`/api/cajas?sucursal_id=${sucursalId}`),
  mediosDisponibles: () =>
    api.get<{ valor: string; etiqueta: string }[]>('/api/cajas/medios-disponibles'),
  crear: (datos: {
    nombre: string
    descripcion?: string
    medios_pago?: string[]
    sucursal_id: number
  }) => api.post<CajaDeMostrador>('/api/cajas', datos),
  editar: (id: number, datos: {
    nombre: string
    descripcion?: string
    medios_pago?: string[]
    activo: boolean
  }) => api.put<CajaDeMostrador>(`/api/cajas/${id}`, datos),
  borrar: (id: number) => api.del<void>(`/api/cajas/${id}`),
}

export const facturacion = {
  /** `null` si todavía no se facturó. Lo puede ver el mostrador. */
  ver: (reservaId: number) => api.get<Factura | null>(`/api/reservas/${reservaId}/factura`),
  // 🔑 Emitir es de admin: el mostrador toma reservas y cobra, pero qué se le
  // factura a quién es del dueño. Si el rol no alcanza, el backend contesta 403
  // — la pantalla esconde el botón para no ofrecer lo que va a fallar.
  emitir: (reservaId: number) => api.post<Factura>(`/api/reservas/${reservaId}/facturar`, {}),
  /** El PDF del comprobante. Es una URL y no un `fetch`: la abre un `<a
   *  target="_blank">`, y la cookie de sesión —`SameSite=Lax`— viaja en una
   *  navegación GET de nivel superior. Con `fetch` habría que armar un blob
   *  para nada. */
  urlDelPdf: (facturaId: number) => `/api/facturas/${facturaId}/pdf`,
}

/** Una fila del listado de comprobantes. Trae al cliente, que la factura de una
 *  reserva no necesita —ahí ya se sabe de quién es el turno—. */
export interface FacturaDeListado extends Factura {
  cliente_razon: string
  cliente_cuit: string
}

export interface PaginaDeFacturas {
  items: FacturaDeListado[]
  total: number
  total_pages: number
  page: number
}

/** Lo que el formulario de alta manda. **Sin `client_id`**, y es a propósito:
 *  el motor lo resolvería contra la tabla `clients` de LibraCore, que es otra
 *  base que la de los clientes de este producto — ver `FacturaNueva.tsx`. */
export interface FacturaNuevaEntrada {
  tipo: number
  punto_venta: number
  fecha: string
  condicion_venta: string
  client_name: string
  client_cuit: string
  observations: string
  items: { description: string; qty: number; unit_price: number }[]
}

/** Qué puede emitir este complejo, según SU condición frente al IVA. */
export interface TiposDeComprobante {
  tipos: { value: number; label: string }[]
  conceptos: { value: number; label: string }[]
  condiciones_venta: string[]
  punto_venta: number
  es_monotributista: boolean
}

/** El listado de comprobantes del complejo. **Todo de admin** — ver
 *  `app/routers/facturas.py`. */
export const facturas = {
  listar: (filtros: { desde?: string; hasta?: string; q?: string; page?: number }) => {
    const params = new URLSearchParams()
    // Sólo lo que tiene valor: un `desde=` vacío es un filtro que el backend
    // igual evalúa, y ensucia la URL que se ve en el navegador.
    if (filtros.desde) params.set('desde', filtros.desde)
    if (filtros.hasta) params.set('hasta', filtros.hasta)
    if (filtros.q) params.set('q', filtros.q)
    params.set('page', String(filtros.page ?? 1))
    return api.get<PaginaDeFacturas>(`/api/facturas?${params}`)
  },
  tipos: () => api.get<TiposDeComprobante>('/api/facturas/tipos'),
  /** Devuelve el comprobante **pelado**, con su `id` arriba: la pantalla navega
   *  al detalle con eso. Envuelto en el detalle, `factura.id` quedaría
   *  `undefined` — pasó de verdad al extraer el módulo al motor. */
  crear: (cuerpo: FacturaNuevaEntrada) =>
    api.post<FacturaDeListado>('/api/facturas', cuerpo),
}

/** Lo que el mostrador necesita saber del QR sin ver ninguna credencial. */
export interface QrDisponible {
  disponible: boolean
  auto_facturar: boolean
}

export interface QrPuesto {
  referencia: string
  monto: number
}

export interface QrEstado {
  /** `aprobado`, `pendiente`, `rechazado`, `sin_orden`. */
  estado: string
  payment_id: string | null
  /** El comprobante que salió solo, si la automática está prendida. */
  factura_id: number | null
}

/** El cobro con QR de MercadoPago en el mostrador.
 *
 * 🔑 **No hay ninguna imagen de QR.** Es el cartel impreso de la caja, que no
 * cambia nunca; lo que `poner` cambia es cuánto cobra cuando alguien lo escanea.
 */
export const cobroQr = {
  /** Si este mostrador puede cobrar por QR, y si eso factura solo. */
  estado: () => api.get<QrDisponible>('/api/reservas/mp/estado'),
  poner: (reservaId: number) =>
    api.post<QrPuesto>(`/api/reservas/${reservaId}/mp-qr`, {}),
  /** 🔴 Sin esto, el próximo que escanee paga el turno anterior. */
  bajar: (reservaId: number) => api.del(`/api/reservas/${reservaId}/mp-qr`),
  consultar: (reservaId: number) =>
    api.get<QrEstado>(`/api/reservas/${reservaId}/mp-status`),
}

/** Las credenciales del QR. Sólo las lee la pantalla de Configuración, que es
 *  admin: quien escriba acá cambia a qué cuenta va la plata del complejo. */
export interface ConfigMercadoPago {
  access_token: string
  user_id: string
  pos_id: string
  webhook_secret: string
  auto_facturar: boolean
  /** Lo calcula el backend con el mismo criterio que usa el mostrador. */
  configurado?: boolean
}

export const configMercadoPago = {
  ver: () => api.get<ConfigMercadoPago>('/config/mercadopago'),
  guardar: (datos: Omit<ConfigMercadoPago, 'configurado'>) =>
    api.put<ConfigMercadoPago>('/config/mercadopago', datos),
}

export interface TurnoDeCaja {
  id: number
  usuario_id: number
  /** El mostrador sobre el que se abrió. `null` en los turnos anteriores al
   *  2026-08-28, que nacieron sin caja. */
  caja_id: number | null
  caja_nombre: string
  apertura: string
  cierre: string | null
  monto_inicial: number
  monto_declarado_cierre: number | null
  monto_esperado_cierre: number | null
  estado: string
  notas: string
}

/** Un mostrador de una sucursal. Una sede puede tener más de uno. */
export interface CajaDeMostrador {
  id: number
  nombre: string
  descripcion: string
  medios_pago: string[]
  activo: boolean
  es_default: boolean
  sucursal_id: number | null
}

export interface ResumenDeCaja {
  // 🔑 `tipo` viene desde siempre en la consulta del motor y este tipo no lo
  // declaraba: sin él la pantalla no puede distinguir un ingreso de un
  // egreso, que es lo que hace que la lista se pueda sumar de arriba abajo.
  movimientos: {
    id: number
    fecha: string
    tipo: 'ingreso' | 'egreso'
    concepto: string
    monto: number
    medio_pago: string
    /** 1 = anulado. La fila **queda** en la lista y sale de los totales del
     *  arqueo: un movimiento de caja se anula, no se borra. */
    anulado: number
  }[]
  pagos_por_medio: Record<string, number>
  total_ventas: number
  efectivo_ventas: number
}

// 🔴 Acá había un `MEDIOS_DE_PAGO` escrito a mano, con un comentario que decía
// que "tiene que coincidir con `MEDIOS_PAGO` del backend — si se agrega uno de
// un lado y no del otro, el cobro da 422". O sea que la divergencia estaba
// **prevista y aceptada** en vez de cerrada. Y ya había ocurrido: las dos
// listas decían `tarjeta`, que no existe en el vocabulario de la familia (ARCA
// la parte en débito y crédito).
//
// Ahora la lista sale de `GET /api/caja/medios-pago`. El subconjunto sigue
// siendo de este producto —un complejo de canchas no cobra con cheque— pero se
// declara **una sola vez**, en `app/servicios/caja.py`.
//
// Ver `wiki/concepts/medios-de-pago-familia-libra.md`.

export type MedioDePago = { valor: string; etiqueta: string }

export const caja = {
  /** `null` si este usuario no tiene caja abierta. */
  actual: () => api.get<{ turno: TurnoDeCaja; resumen: ResumenDeCaja } | null>('/api/caja/turnos/actual'),
  /** Por qué puede salir plata del cajón. Lista cerrada del backend. */
  motivosDeEgreso: () => api.get<string[]>('/api/caja/motivos-de-egreso'),
  /** Plata que **sale**. Devuelve el resumen al momento, como el cobro. */
  egreso: (datos: { monto: string; motivo: string; detalle?: string; medio_pago: string }) =>
    api.post<ResumenDeCaja>('/api/caja/egresos', datos),
  /** Anula un movimiento **del turno abierto**. Un arqueo cerrado no se toca. */
  anular: (movimientoId: number) =>
    api.del<ResumenDeCaja>(`/api/caja/movimientos/${movimientoId}`),
  /** El turno se abre **sobre un mostrador**: el arqueo del cierre es el de ESE
   *  cajón. `caja_id` es obligatorio del lado del backend. */
  abrir: (monto_inicial: string, notas = '', caja_id?: number) =>
    api.post<TurnoDeCaja>('/api/caja/turnos', { monto_inicial, notas, caja_id }),
  cobrar: (cuerpo: { monto: string; concepto: string; medio_pago: string }) =>
    api.post<ResumenDeCaja>('/api/caja/cobros', cuerpo),
  cerrar: (turnoId: number, monto_declarado: string, notas = '') =>
    api.post<TurnoDeCaja & { diferencia_de_caja: number }>(
      `/api/caja/turnos/${turnoId}/cerrar`, { monto_declarado, notas },
    ),
  historial: () => api.get<TurnoDeCaja[]>('/api/caja/turnos'),
}

export const sesion = {
  login: (username: string, password: string) =>
    api.post<{ username: string }>('/auth/login', { username, password }),
  logout: () => api.post('/auth/logout', {}),
  yo: () => api.get<{ username: string; role?: string }>('/auth/me'),
}

export interface SaldoDeCuenta {
  cliente_id: number
  cliente: string
  /** Positivo = debe. Negativo = tiene saldo a favor. Lo calcula el backend. */
  saldo: number
}

export interface MovimientoDeCuenta {
  fecha: string
  /** `debito` suma deuda, `credito` la baja. */
  tipo: string
  concepto: string
  /** 🔑 **Siempre positivo**: el signo lo pone `tipo`, no el número. */
  monto: number
  /** N° de transferencia o cheque que se tecleó al cobrar. Vacío si no se puso. */
  referencia: string
  medio: string
  usuario_nombre: string | null
}

/** Lo que el diálogo de cobro le manda al backend.
 *
 * `fecha`, `concepto` y `referencia` son opcionales: vacíos, el backend usa
 * hoy y "Pago a cuenta". El default vive **de un solo lado** —el servicio— para
 * que no haya dos que puedan diferir.
 */
export interface PagoDeCuenta {
  monto: string
  medio_pago: string
  /** ISO `aaaa-mm-dd`. Es la fecha de la línea del extracto: el movimiento de
   *  caja va igual al turno abierto, que es de hoy. */
  fecha?: string
  concepto?: string
  referencia?: string
}

export const cuentaCorriente = {
  /** Fía una reserva: queda como deuda del cliente. */
  cargar: (reservaId: number) =>
    api.post<SaldoDeCuenta>(`/api/cuenta-corriente/reservas/${reservaId}/cargar`, {}),
  /** Un pago a cuenta. Exige turno de caja abierto — el backend contesta 409. */
  pagar: (clienteId: number, cuerpo: PagoDeCuenta) =>
    api.post<SaldoDeCuenta>(`/api/cuenta-corriente/clientes/${clienteId}/pagos`, cuerpo),
  ver: (clienteId: number) =>
    api.get<SaldoDeCuenta & { movimientos: MovimientoDeCuenta[] }>(
      `/api/cuenta-corriente/clientes/${clienteId}`,
    ),
  /** La pantalla de cobranza. De **mostrador**: el encargado es el que fía y
   *  el que cobra, y sin ver el saldo no puede atender al que viene a pagar.
   *
   *  El `total_deuda` lo suma el backend —sólo los saldos positivos— por la
   *  misma razón que cada saldo: es plata, y dos lugares sumándola por su
   *  cuenta terminan mostrando números distintos. */
  deudores: () =>
    api.get<{ deudores: SaldoDeCuenta[]; total_deuda: number }>(
      '/api/cuenta-corriente/deudores',
    ),
}

// ── Horario de atención ──────────────────────────────────────────────────

export interface FranjaEntrada {
  sucursal_id: number
  cancha_id: number | null
  alcance_dia: 'todos' | 'dia_semana' | 'feriado'
  dia_semana: number | null
  /** `HH:MM` desde el formulario; el backend devuelve `HH:MM:SS`. */
  abre: string
  /** 🔑 Menor o igual que `abre` significa **que cierra al día siguiente**: es
   *  el complejo que abre a las 16 y cierra a las 02, que en pádel es lo
   *  normal. Igual = 24 horas. */
  cierra: string
  activa: boolean
}

export interface Franja extends FranjaEntrada {
  id: number
}

export const horarios = {
  listar: () => api.get<Franja[]>('/api/horarios'),
  crear: (cuerpo: FranjaEntrada) => api.post<Franja>('/api/horarios', cuerpo),
  editar: (id: number, cuerpo: FranjaEntrada) =>
    api.put<Franja>(`/api/horarios/${id}`, cuerpo),
  borrar: (id: number) => api.del(`/api/horarios/${id}`),
}

// ── Buffet ───────────────────────────────────────────────────────────────

export interface ProductoDeBuffet {
  item_id: number
  nombre: string
  precio: number
  activo: boolean
  stock: number
  stock_minimo: number
  bajo_minimo: boolean
}

export interface ProductoEntrada {
  nombre: string
  precio: string
  costo: string
  stock_minimo: string
  activo: boolean
}

export interface LineaDeConsumo {
  descripcion: string
  cantidad: number
  precio_unitario: number
  importe: number
}

export const buffet = {
  productos: (sucursalId: number) =>
    api.get<ProductoDeBuffet[]>(`/api/buffet/productos?sucursal_id=${sucursalId}`),
  crearProducto: (sucursalId: number, cuerpo: ProductoEntrada) =>
    api.post<ProductoDeBuffet>(`/api/buffet/productos?sucursal_id=${sucursalId}`, cuerpo),
  editarProducto: (sucursalId: number, itemId: number, cuerpo: ProductoEntrada) =>
    api.put<ProductoDeBuffet>(
      `/api/buffet/productos/${itemId}?sucursal_id=${sucursalId}`, cuerpo,
    ),
  /** `cantidad` positiva repone, negativa descuenta (rotura, vencido). */
  ajustar: (sucursalId: number, cuerpo: { item_id: number; cantidad: string; motivo: string }) =>
    api.post<ProductoDeBuffet>(`/api/buffet/ajustes?sucursal_id=${sucursalId}`, cuerpo),
  /** Con `reserva_id` se carga a la cancha y NO se cobra: se cobra con el turno. */
  consumir: (
    sucursalId: number,
    cuerpo: {
      lineas: { item_id: number; cantidad: string }[]
      reserva_id?: number | null
      medio_pago?: string | null
    },
  ) =>
    api.post<{ id: number; numero: string; total: number; reserva_id: number | null }>(
      `/api/buffet/consumos?sucursal_id=${sucursalId}`, cuerpo,
    ),
  consumosDe: (reservaId: number) =>
    api.get<{ total: number; lineas: LineaDeConsumo[] }>(
      `/api/buffet/reservas/${reservaId}/consumos`,
    ),
}

// ── Turnos fijos (canchas fijas / series) ────────────────────────────────

export interface SerieEntrada {
  cancha_id: number
  cliente_id: number
  /** 0 = lunes … 6 = domingo. */
  dia_semana: number
  /** `HH:MM`. */
  hora: string
  duracion_min: number
  desde: string
  /** `null` = sin fin, que es el caso normal de una cancha fija. */
  hasta: string | null
  observaciones?: string | null
}

export interface Serie extends SerieEntrada {
  id: number
  activa: boolean
  cliente: string
  cancha: string
  /** 🔑 Hasta cuándo hay reservas generadas. `null` = **ninguna**, o sea que la
   *  serie existe y no está funcionando. Es lo que evita que una cancha fija se
   *  apague sola al agotarse la ventana de 90 días. */
  materializada_hasta: string | null
  /** Reservas futuras vivas. Es lo que se cancela al dar de baja. */
  proximas: number
}

/** Una fecha de la serie que no se pudo crear, **con el motivo**. */
export interface Salteada {
  comienza_at: string
  /** `sin_tarifa` | `ocupada` | `fuera_de_horario`. */
  motivo: string
  detalle: string
}

export interface SerieCreada {
  serie: Serie
  creadas: Reserva[]
  salteadas: Salteada[]
}

export const series = {
  listar: () => api.get<Serie[]>('/api/reservas/series/listado'),
  /** `hasta` acota hasta dónde generar; sin él, la ventana por defecto (90 días). */
  crear: (cuerpo: SerieEntrada, hasta?: string) =>
    api.post<SerieCreada>(
      `/api/reservas/series${hasta ? `?hasta=${hasta}` : ''}`, cuerpo,
    ),
  /** Genera las ocurrencias que faltan de una serie ya creada. */
  extender: (id: number, hasta?: string) =>
    api.post<SerieCreada>(
      `/api/reservas/series/${id}/extender${hasta ? `?hasta=${hasta}` : ''}`, {},
    ),
  /** Corta la cancha fija. Devuelve cuántas reservas futuras se cancelaron. */
  darDeBaja: (id: number, cuerpo: { cancelar_futuras: boolean; motivo?: string }) =>
    api.post<{ serie_id: number; canceladas: number }>(
      `/api/reservas/series/${id}/baja`, cuerpo,
    ),
}

// ── Portal público ───────────────────────────────────────────────────────
//
// 🔴 **Todo esto sale a internet sin sesión de staff.** Las respuestas traen
// menos campos que las del backoffice a propósito: la disponibilidad pública no
// dice quién ocupa los turnos, y las canchas no traen `punto_venta_arca`. Si
// algún día un tipo de acá crece de golpe, mirar el servidor antes que la
// pantalla.

export interface Jugador {
  id: number
  nombre: string
  email: string
}

export interface CanchaPublica {
  id: number
  nombre: string
  deporte: string
  techada: boolean
  iluminacion: boolean
  duracion_turno_min: number
}

export interface TurnoLibre {
  comienza_at: string
  termina_at: string
  precio: number
}

export interface ReservaDelJugador {
  id: number
  cancha: string
  comienza_at: string
  termina_at: string
  estado: string
  precio: number | null
  /** `pendiente` | `aprobado` | `rechazado` | `vencido` | `null`. */
  pago: string | null
  /** Hasta cuándo se retiene el turno esperando el pago. */
  vence_at: string | null
}

export interface ReservaCreada {
  reserva_id: number
  pago_id: number
  referencia: string
  monto: number
  vence_at: string
  /** `null` mientras la instancia no tenga credenciales de MercadoPago. */
  url_de_pago: string | null
}

export const portal = {
  registro: (cuerpo: {
    email: string; password: string; nombre: string; telefono?: string
  }) => api.post<Jugador>('/api/portal/registro', cuerpo),
  login: (cuerpo: { email: string; password: string }) =>
    api.post<Jugador>('/api/portal/login', cuerpo),
  logout: () => api.post<void>('/api/portal/logout', {}),
  yo: () => api.get<Jugador | null>('/api/portal/yo'),

  canchas: (sucursalId: number) =>
    api.get<CanchaPublica[]>(`/api/portal/canchas?sucursal_id=${sucursalId}`),
  disponibilidad: (canchaId: number, dia: string) =>
    api.get<TurnoLibre[]>(`/api/portal/disponibilidad?cancha_id=${canchaId}&dia=${dia}`),

  reservar: (cuerpo: { cancha_id: number; comienza_at: string }) =>
    api.post<ReservaCreada>('/api/portal/reservas', cuerpo),
  misReservas: () => api.get<ReservaDelJugador[]>('/api/portal/reservas'),
  cancelar: (id: number) =>
    api.post<{ id: number; estado: string }>(`/api/portal/reservas/${id}/cancelar`, {}),

  /** 🔴 Sólo existe fuera de producción. La pantalla lo ofrece únicamente
   *  cuando el endpoint contesta; en la instancia de un complejo da 404. */
  simularPago: (pagoId: number, aprobado = true) =>
    api.post<{ pago: string; reserva: string; simulado: boolean }>(
      `/api/portal/pagos/${pagoId}/simular?aprobado=${aprobado}`, {},
    ),
}

// ── «Falta uno» ──────────────────────────────────────────────────────────

/** Un partido en el listado. **Sin datos de contacto** — a propósito: el
 *  listado lo ve cualquiera con cuenta. */
export interface PartidoAbierto {
  id: number
  cancha: string
  deporte: string
  comienza_at: string
  termina_at: string
  organizador: string
  faltan: number
  nota: string | null
}

/** El detalle. `organizador_telefono` y los `telefono` de los anotados vienen
 *  `null` **salvo que quien pregunta juegue ahí** — el servidor lo decide, no
 *  la pantalla. */
export interface PartidoDetalle {
  id: number
  cancha: string
  comienza_at: string
  termina_at: string
  organizador: string
  organizador_telefono: string | null
  faltan: number
  nota: string | null
  abierta: boolean
  soy_organizador: boolean
  estoy_anotado: boolean
  anotados: { nombre: string; telefono: string | null; soy_yo: boolean }[]
}

export const partidos = {
  abiertos: () => api.get<PartidoAbierto[]>('/api/portal/partidos'),
  mios: () => api.get<PartidoDetalle[]>('/api/portal/partidos/mios'),
  ver: (id: number) => api.get<PartidoDetalle>(`/api/portal/partidos/${id}`),
  publicar: (reservaId: number, cuerpo: { faltan: number; nota?: string }) =>
    api.post<PartidoDetalle>(
      `/api/portal/reservas/${reservaId}/buscar-jugadores`, cuerpo),
  sumarme: (id: number) =>
    api.post<PartidoDetalle>(`/api/portal/partidos/${id}/sumarme`, {}),
  bajarme: (id: number) =>
    api.post<PartidoDetalle>(`/api/portal/partidos/${id}/bajarme`, {}),
  cerrar: (id: number) =>
    api.post<PartidoDetalle>(`/api/portal/partidos/${id}/cerrar`, {}),
}

// ── Torneos ──────────────────────────────────────────────────────────────
//
// El backoffice, no el portal: acá **sí** viajan los teléfonos de los
// integrantes, porque quien consulta es el encargado que necesita avisarle a
// una pareja que su partido se movió. La regla contraria —la del portal— vive
// en `partidos`, más arriba.

/** `eliminacion` | `liga` | `zonas`. */
export type FormatoTorneo = 'eliminacion' | 'liga' | 'zonas'
/** `armado` | `sorteado` | `finalizado` | `cancelado`. */
export type EstadoTorneo = 'armado' | 'sorteado' | 'finalizado' | 'cancelado'

export const FORMATOS: { valor: FormatoTorneo; nombre: string; ayuda: string }[] = [
  {
    valor: 'eliminacion',
    nombre: 'Eliminación directa',
    ayuda: 'Llaves: el que pierde se va. Con byes si no son potencia de dos.',
  },
  {
    valor: 'liga',
    nombre: 'Todos contra todos',
    ayuda: 'Una sola tabla, sin playoff. El campeón es el primero.',
  },
  {
    valor: 'zonas',
    nombre: 'Zonas y playoff',
    ayuda: 'Grupos y después llaves entre los que clasifican.',
  },
]

export interface TorneoEntrada {
  sucursal_id: number
  nombre: string
  deporte: string
  formato: FormatoTorneo
  desde: string
  hasta: string | null
  /** 1 = fútbol (un solo resultado). 2 = al mejor de tres, el pádel normal. */
  sets_para_ganar: number
  /** Sólo en formato `zonas`; `null` en los otros, y el backend lo exige así. */
  cantidad_zonas: number | null
  /** Sólo en formato `zonas`. El backend soporta 1 o 2. */
  clasifican_por_zona: number | null
  observaciones: string | null
}

export interface Torneo extends TorneoEntrada {
  id: number
  estado: EstadoTorneo
  /** La semilla del sorteo. Con ella y la lista de inscriptos el cuadro se
   *  reproduce entero: es lo que hace auditable el sorteo. */
  semilla: number | null
}

export interface TorneoEnLista extends Torneo {
  competidores: number
  partidos: number
  jugados: number
  /** Partidos sin cancha ni horario. Es lo que le dice al encargado que le
   *  queda trabajo por hacer. */
  sin_programar: number
  campeon: string | null
}

export interface Integrante {
  nombre: string
  telefono: string | null
}

export interface Competidor {
  id: number
  nombre: string
  siembra: number | null
  zona_id: number | null
  zona: string | null
  integrantes: Integrante[]
}

export interface CompetidorEntrada {
  nombre: string
  siembra: number | null
  integrantes: Integrante[]
}

export interface Parcial {
  numero: number
  puntos_a: number
  puntos_b: number
}

export interface PartidoDeTorneo {
  id: number
  /** `grupos` | `llaves`. */
  etapa: 'grupos' | 'llaves'
  zona_id: number | null
  zona: string | null
  ronda: number
  orden: number
  /** «Semifinal», «Zona A · Fecha 2». Lo resuelve el servidor porque depende de
   *  cuántas rondas tiene el cuadro. */
  instancia: string
  competidor_a_id: number | null
  competidor_a: string | null
  competidor_b_id: number | null
  competidor_b: string | null
  avanza_a_id: number | null
  avanza_a_slot: string | null
  reserva_id: number | null
  cancha: string | null
  comienza_at: string | null
  termina_at: string | null
  ganador_id: number | null
  finalizado: boolean
  parciales: Parcial[]
}

export interface Fixture {
  /** Cuántas rondas tiene el cuadro; `0` si todavía no hay llaves. Es lo que la
   *  pantalla usa para dibujar las columnas. */
  rondas: number
  partidos: PartidoDeTorneo[]
}

export interface FilaDePosiciones {
  competidor_id: number
  nombre: string
  jugados: number
  ganados: number
  empatados: number
  perdidos: number
  /** La suma de los parciales: goles en fútbol, games en pádel y tenis. */
  a_favor: number
  en_contra: number
  diferencia: number
  puntos: number
}

export interface TablaDeZona {
  zona_id: number | null
  /** `null` en una liga, que no tiene zonas. */
  nombre: string | null
  filas: FilaDePosiciones[]
}

export const torneos = {
  listar: (sucursalId?: number) =>
    api.get<TorneoEnLista[]>(
      `/api/torneos${sucursalId ? `?sucursal_id=${sucursalId}` : ''}`,
    ),
  ver: (id: number) => api.get<Torneo>(`/api/torneos/${id}`),
  crear: (cuerpo: TorneoEntrada) => api.post<Torneo>('/api/torneos', cuerpo),
  /** Sólo lo que no toca el cuadro: el formato no se puede cambiar. */
  editar: (
    id: number,
    cuerpo: { nombre: string; desde: string; hasta: string | null; observaciones: string | null },
  ) => api.put<Torneo>(`/api/torneos/${id}`, cuerpo),
  cancelar: (id: number) =>
    api.post<{ torneo_id: number; canchas_liberadas: number }>(
      `/api/torneos/${id}/cancelar`, {},
    ),

  competidores: (id: number) =>
    api.get<Competidor[]>(`/api/torneos/${id}/competidores`),
  inscribir: (id: number, cuerpo: CompetidorEntrada) =>
    api.post<Competidor>(`/api/torneos/${id}/competidores`, cuerpo),
  bajar: (competidorId: number) =>
    api.del(`/api/torneos/competidores/${competidorId}`),

  /** `semilla` reproduce un sorteo hecho frente a la gente. Sin ella se elige
   *  una y se guarda igual. */
  sortear: (id: number, semilla?: number) =>
    api.post<Torneo>(
      `/api/torneos/${id}/sortear${semilla ? `?semilla=${semilla}` : ''}`, {},
    ),
  playoff: (id: number) => api.post<Torneo>(`/api/torneos/${id}/playoff`, {}),

  fixture: (id: number) => api.get<Fixture>(`/api/torneos/${id}/fixture`),
  posiciones: (id: number) => api.get<TablaDeZona[]>(`/api/torneos/${id}/posiciones`),

  programar: (
    partidoId: number,
    cuerpo: { cancha_id: number; comienza_at: string; duracion_min?: number | null },
  ) => api.post<PartidoDeTorneo>(`/api/torneos/partidos/${partidoId}/programar`, cuerpo),
  liberar: (partidoId: number) =>
    api.post<PartidoDeTorneo>(`/api/torneos/partidos/${partidoId}/liberar`, {}),
  cargarResultado: (partidoId: number, parciales: { puntos_a: number; puntos_b: number }[]) =>
    api.post<PartidoDeTorneo>(`/api/torneos/partidos/${partidoId}/resultado`, { parciales }),
  borrarResultado: (partidoId: number) =>
    api.del(`/api/torneos/partidos/${partidoId}/resultado`),
}
