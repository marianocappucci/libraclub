"""La barra de estado del pie (libracore ADR-075, libra-ui ADR-083): `GET /api/estado-del-sistema` está montada, y el
respaldo y la versión del motor los ve sólo el admin. La sucursal la pone el frontend (el selector vive en el
navegador)."""
from tests.test_api import api, api_staff  # noqa: F401  (fixtures)


def test_el_admin_ve_respaldo_y_version_del_motor(api):  # noqa: F811
    r = api.get("/api/estado-del-sistema")
    assert r.status_code == 200
    datos = r.json()
    assert datos["usuario"]["rol"] == "admin" and datos["libraedge"] is None
    assert datos["respaldo"] is not None and datos["version"]["motor"]


def test_el_staff_no_ve_respaldo_ni_version_del_motor(api_staff):  # noqa: F811
    datos = api_staff.get("/api/estado-del-sistema").json()
    assert datos["usuario"]["rol"] == "staff"
    assert datos["respaldo"] is None and datos["arca"] is None and datos["version"]["motor"] is None
