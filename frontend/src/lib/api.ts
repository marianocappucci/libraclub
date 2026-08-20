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
  del: (ruta: string) => pedir<void>(ruta, { method: 'DELETE' }),
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

export const sesion = {
  login: (username: string, password: string) =>
    api.post<{ username: string }>('/auth/login', { username, password }),
  logout: () => api.post('/auth/logout', {}),
  yo: () => api.get<{ username: string; role?: string }>('/auth/me'),
}
