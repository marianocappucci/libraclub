// Guard: todo campo donde se elige un cliente ofrece darlo de alta ahí mismo (ADR-071, libra-ui v0.158.0).
//
// 🔴 **Lee los FUENTES, no el DOM.** Lo que hay que impedir es que vuelva a nacer un desplegable de cliente sin el botón «Agregar nuevo cliente»
// (en LibraDesk, un cliente que no estaba cargado no se podía elegir al recibir un equipo). Eso se ve en el JSX. El motor vive en
// `libra-ui/auditoria-de-clientes` y tiene sus propios tests allá.
//
// Un campo de cliente es `SelectCliente`. Un *filtro* o un campo que no crea nada se marca con `cliente-sin-alta: <motivo>` en su renglón o en los
// tres de arriba.
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { auditarCamposDeCliente, describirCamposSinAlta } from 'libra-ui/auditoria-de-clientes'

const SRC = join(process.cwd(), 'src')

describe('todo campo donde se elige un cliente ofrece el alta', () => {
  const r = auditarCamposDeCliente(SRC)

  it('🔴 el control — el guard midió campos de cliente (un parser que devuelve cero sería un falso verde)', () => {
    expect(r.archivos).toBeGreaterThan(0)
    expect(r.campos).toBeGreaterThan(0)
    expect(r.conAlta).toBeGreaterThan(0)
  })

  it('ningún campo de cliente deja de ser SelectCliente, salvo los marcados `cliente-sin-alta: <motivo>`', () => {
    expect(describirCamposSinAlta(r.infracciones)).toEqual([])
  })
})
