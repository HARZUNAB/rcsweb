"""Pruebas de coincidencia y filtrado por analista."""

from __future__ import annotations

from app.extensions import db
from app.models import User
from app.services import panels
from app.services.analysts import (
    codigos_usuario,
    coincide,
    evento_visible,
    filtrar_filas,
    nombres_de_fila,
    normalizar_nombre,
)


def _usuario(username, code, alia=None, role="analista", active=True):
    usuario = User(
        username=username,
        role=role,
        analyst_code=code,
        analyst_aliases=alia,
        active=active,
    )
    usuario.set_password("secret")
    db.session.add(usuario)
    db.session.commit()
    return usuario


def test_normaliza_mayusculas_acentos_y_espacios():
    assert normalizar_nombre("  JERÉ  ") == "jere"
    assert normalizar_nombre("Jere V") == "jerev"
    assert codigos_usuario(
        User(username="x", role="analista", analyst_code="Jere", analyst_aliases="JereV, jerez")
    ) == ["jere", "jerev", "jerez"]


def test_coincide_por_prefijo_de_tres_caracteres():
    assert coincide("jere", "jerez")
    assert coincide("jere", "jerev")
    assert coincide("jere", "JERE")
    assert not coincide("ana", "mariana")
    assert not coincide("jere", "jorge")


def test_nombres_de_fila_separa_fuentes():
    fila = {
        "Analista probable": "SeisComp: mary; Seisan: jaba, ana",
        "Analista_otra": "beto",
    }
    assert nombres_de_fila(fila) == ["mary", "jaba", "ana", "beto"]


def test_evento_visible_para_analista(app):
    analista = _usuario("analista", "Jere")
    admin = _usuario("admin2", "admin", role="admin")

    assert evento_visible({"Analista": "Jerez"}, analista)
    assert evento_visible({"Analista": "jere"}, analista)
    assert evento_visible({"Analista probable": "SeisComp: mary"}, analista) is False
    assert evento_visible({"Analista": "otro"}, analista) is False
    assert evento_visible({"Analista": "otro"}, admin) is True


def test_nombre_ambiguo_no_da_acceso(app):
    _usuario("uno", "Jere")
    _usuario("dos", "Jerez")
    actual = db.session.execute(
        db.select(User).filter_by(username="uno")
    ).scalar_one()

    assert evento_visible({"Analista": "Jerez"}, actual) is False
    assert evento_visible({"Analista": "Jere"}, actual) is False


def test_analista_sin_codigo_no_ve_eventos(app):
    analista = _usuario("sin-codigo", None)
    assert evento_visible({"Analista": "Jere"}, analista) is False
    assert filtrar_filas([{"Analista": "Jere"}], analista) == []


def test_paneles_filtra_eventos_y_recalcula_resumen(app):
    ana = _usuario("ana-panel", "ana")
    _usuario("beto-panel", "beto")
    base = {
        "lat": -30.0,
        "lon": -71.0,
        "perfil": "P001",
        "along_km": 10.0,
        "sospechoso": False,
        "tipo_observacion": "no_publicado",
        "revision": "",
    }
    datos = {
        "eventos": [
            {**base, "analista": "ana"},
            {**base, "analista": "beto"},
        ]
    }

    filtrado = panels.filtrar_por_analista(datos, ana)

    assert filtrado["total"] == 1
    assert len(filtrado["eventos"]) == 1
    assert filtrado["eventos"][0]["analista"] == "ana"
    assert filtrado["perfiles"][0]["eventos"] == 1


def test_admin_no_se_filtra(app):
    admin = _usuario("admin3", "admin", role="admin")
    filas = [{"Analista": "uno"}, {"Analista": "dos"}]
    assert filtrar_filas(filas, admin) == filas
