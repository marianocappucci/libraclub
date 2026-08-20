"""ABM de usuarios, sobre el repositorio de `libraauth`.

Mismo contrato que el resto de la familia —`Usuarios` de `libra-ui` lo consume
tal cual, pasándole el `basePath`— con el prefijo en castellano, como el resto
de la API de este producto.

Existe para que el **backoffice de la suite** (`admin.libraclub.com.ar`) pueda
administrar los usuarios de esta instancia. Sin este router, la pestaña
"Usuarios" del panel contesta 404 contra este producto.

> El repositorio es el de `libraauth`: la tabla `usuarios` la crea y la versiona
> el motor, no este producto. Acá sólo se expone.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from libraauth.repository import UsernameTaken, UserRepository
from pydantic import BaseModel, Field

from app.auth import get_current_user, require_admin_o_servicio

router = APIRouter(
    prefix="/api/usuarios",
    tags=["usuarios"],
    # Rol admin **o** token de servicio: el backoffice administra los usuarios de
    # una instancia por acá, y no tiene —ni debería tener— una sesión de usuario
    # en cada una.
    #
    # Sin `LIBRA_SERVICE_TOKEN` en el entorno se comporta exactamente igual que
    # `require_admin`, así que ponerlo en una instancia que no define la variable
    # no abre nada.
    dependencies=[Depends(require_admin_o_servicio)],
)

Rol = Literal["admin", "staff"]


def repositorio(request: Request) -> UserRepository:
    """El repositorio que `crear_app` dejó en `app.state`.

    Se lee de ahí y no se construye uno nuevo: dos repositorios sobre la misma
    tabla son una fábrica de sesiones de más, y el de `app.state` es el que usa
    el login.
    """
    return request.app.state.users


class UsuarioNuevo(BaseModel):
    username: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1)
    #: `staff` por default: en este producto es el rol del encargado de
    #: mostrador, que es quien se da de alta seguido. Un admin de más es la
    #: clase de cosa que nadie revisa después.
    role: Rol = "staff"
    email: str = ""


class UsuarioEditado(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: Rol
    active: bool = True
    #: 🔴 `None` es "dejalo como está"; `""` lo borra. El default **tiene** que
    #: ser `None`: el botón de activar/desactivar de la grilla manda este mismo
    #: cuerpo sin tocar el correo, y con `""` por default desactivar a alguien
    #: le borraría el mail en silencio.
    email: str | None = None


class ClaveNueva(BaseModel):
    password: str


class UsuarioOut(BaseModel):
    id: str
    username: str
    name: str
    role: str
    active: bool
    email: str = ""


@router.get("", response_model=list[UsuarioOut])
def listar(usuarios: UserRepository = Depends(repositorio)):
    return usuarios.list()


@router.post("", response_model=UsuarioOut, status_code=201)
def crear(datos: UsuarioNuevo, usuarios: UserRepository = Depends(repositorio)):
    try:
        return usuarios.create(
            datos.username, datos.name, datos.password, datos.role, email=datos.email
        )
    except UsernameTaken:
        raise HTTPException(409, "ya existe un usuario con ese nombre") from None


@router.get("/{id_}", response_model=UsuarioOut)
def traer(id_: str, usuarios: UserRepository = Depends(repositorio)):
    usuario = usuarios.get_by_id(id_)
    if usuario is None:
        raise HTTPException(404, f"no existe el usuario {id_}")
    return usuario


@router.put("/{id_}", response_model=UsuarioOut)
def editar(
    id_: str,
    datos: UsuarioEditado,
    usuarios: UserRepository = Depends(repositorio),
    actual: dict = Depends(get_current_user),
):
    """🔴 Un admin **no puede desactivarse ni bajarse de rol a sí mismo**.

    Con un solo administrador —que es el caso de una instancia recién
    entregada— eso deja el producto sin nadie que pueda administrar usuarios, y
    la única salida es entrar a la base. La regla mira el usuario **de la
    sesión**, no el cuerpo del pedido.

    > Cuando quien pide es el backoffice —token de servicio, sin sesión de
    > usuario— `actual` viene vacío y la regla no aplica: el superadmin no es
    > usuario de este producto, así que no se puede estar desactivando a sí
    > mismo. Es lo que permite destrabar una instancia desde el panel.
    """
    if actual and str(actual.get("id")) == str(id_):
        if not datos.active:
            raise HTTPException(409, "no te podes desactivar a vos mismo")
        if datos.role != "admin":
            raise HTTPException(409, "no te podes sacar el rol de admin a vos mismo")
    try:
        return usuarios.update(id_, datos.name, datos.role, datos.active, email=datos.email)
    except KeyError:
        raise HTTPException(404, f"no existe el usuario {id_}") from None


@router.put("/{id_}/password", status_code=204)
def cambiar_clave(
    id_: str, datos: ClaveNueva, usuarios: UserRepository = Depends(repositorio)
):
    """Sin mínimo de largo, pero **la clave vacía se rechaza**.

    Este endpoint existe para destrabar a alguien que quedó afuera, y un
    requisito que el administrador no puede cumplir en el momento lo manda de
    vuelta a la base. Pero `""` hasheada no es una contraseña floja: es ninguna.
    """
    if not (datos.password or "").strip():
        raise HTTPException(422, "la contraseña no puede estar vacía")
    try:
        usuarios.update_password(id_, datos.password)
    except KeyError:
        raise HTTPException(404, f"no existe el usuario {id_}") from None
    return Response(status_code=204)


@router.delete("/{id_}", status_code=204)
def eliminar(
    id_: str,
    usuarios: UserRepository = Depends(repositorio),
    actual: dict = Depends(get_current_user),
):
    """Tampoco se puede borrar a sí mismo, por lo mismo que no puede desactivarse."""
    if actual and str(actual.get("id")) == str(id_):
        raise HTTPException(409, "no te podes borrar a vos mismo")
    try:
        usuarios.delete(id_)
    except KeyError:
        raise HTTPException(404, f"no existe el usuario {id_}") from None
    return Response(status_code=204)
