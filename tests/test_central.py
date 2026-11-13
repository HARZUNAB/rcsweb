"""Pruebas del adaptador de la base central."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.domain.catalogs.adapters.central import (
    Adaptador,
    _elegir_origen_local,
    _estado_texto,
    _periodo,
    limpiar_cache_disponibilidad,
)
from app.domain.catalogs.stations import EstacionLista
from app.extensions import db
from app.models import Job, User, nuevo_uuid


@pytest.fixture(autouse=True)
def _cache_limpia():
    limpiar_cache_disponibilidad()
    yield
    limpiar_cache_disponibilidad()


def _job(usuario_id: int) -> Job:
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC),
        status="queued",
        created_by_id=usuario_id,
    )
    db.session.add(job)
    db.session.commit()
    return job


def _usuario(nombre: str, rol: str, codigo: str = "") -> User:
    usuario = User(username=nombre, role=rol, analyst_code=codigo)
    usuario.set_password("secret")
    db.session.add(usuario)
    db.session.commit()
    return usuario


def _eventos():
    return [
        {
            "event_id": "e-1",
            "published": False,
            "origin_id": "o-1",
            "author": "eatl",
            "status": "REVIEWED",
            "origin_time": datetime(2026, 10, 1, 0, 0, tzinfo=UTC),
            "latitude": -30.0,
            "longitude": -71.0,
            "depth": 10.0,
            "magnitude_value": 2.5,
            "magnitude_type": "ML",
        },
        {
            "event_id": "e-2",
            "published": True,
            "origin_id": "o-2",
            "author": "otro",
            "status": "final",
            "origin_time": datetime(2026, 10, 2, 0, 0, tzinfo=UTC),
            "latitude": -31.0,
            "longitude": -72.0,
            "depth": 20.0,
            "magnitude_value": 3.0,
            "magnitude_type": "ML",
        },
    ]


def _tensores():
    return [
        {"event_id": "e-1", "origin_id": "o-1", "tensor_id": "t-1",
         "method": "SCMT", "mechanism": "DC", "strike1": 10.0,
         "dip1": 20.0, "rake1": 30.0, "strike2": 40.0, "dip2": 50.0,
         "rake2": 60.0, "m_rr": 1e18, "m_tt": -1e18, "m_pp": 0.0,
         "m_rt": 0.0, "m_rp": 0.0, "m_tp": 0.0,
         "scalar_moment": 1e18},
        {"event_id": "e-2", "origin_id": "o-2", "tensor_id": "t-2",
         "method": "SCMT", "mechanism": "DC", "strike1": 0.0,
         "dip1": 0.0, "rake1": 0.0, "strike2": 0.0, "dip2": 0.0,
         "rake2": 0.0, "m_rr": 0.0, "m_tt": 0.0, "m_pp": 0.0,
         "m_rt": 0.0, "m_rp": 0.0, "m_tp": 0.0,
         "scalar_moment": 0.0},
    ]


def test_estado_normalizado():
    assert _estado_texto("REVIEWED") == "Revisado"
    assert _estado_texto("final") == "Final"
    assert _estado_texto("confirmed") == "Confirmado"
    assert _estado_texto("automatic") == "Automático"
    assert _estado_texto("manual") == "Manual"
    assert _estado_texto("desconocido") == "desconocido"


def test_periodo_desde_el_job(app):
    with app.app_context():
        usuario = _usuario("ana", "analista", "eatl")
        job = _job(usuario.id)
        inicio, fin = _periodo(job)
        assert inicio == datetime(2026, 10, 1, tzinfo=UTC)
        assert fin == datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC)


def test_exportar_filtra_por_analista(app, tmp_path, monkeypatch):
    with app.app_context():
        usuario = _usuario("ana", "analista", "eatl")
        job = _job(usuario.id)
        adaptador = Adaptador()
        adaptador.source_id = "central"
        monkeypatch.setattr(
            adaptador, "_consultar", lambda _inicio, _fin: (_eventos(), _tensores())
        )

        adaptador.exportar(tmp_path, job)

        eventos = (tmp_path / "datos/central_parametros.csv").read_text(
            encoding="utf-8"
        )
        assert "eatl" in eventos
        assert "otro" not in eventos
        assert "Sí" not in eventos
        assert "Revisado" in eventos

        tensores = (tmp_path / "datos/central_tensores.csv").read_text(
            encoding="utf-8"
        )
        assert "e-1" in tensores
        assert "e-2" not in tensores


def test_exportar_admin_ve_todo(app, tmp_path, monkeypatch):
    with app.app_context():
        usuario = _usuario("admin2", "admin", "")
        job = _job(usuario.id)
        adaptador = Adaptador()
        adaptador.source_id = "central"
        monkeypatch.setattr(
            adaptador, "_consultar", lambda _inicio, _fin: (_eventos(), _tensores())
        )

        adaptador.exportar(tmp_path, job)

        eventos = (tmp_path / "datos/central_parametros.csv").read_text(
            encoding="utf-8"
        )
        assert "eatl" in eventos
        assert "otro" in eventos
        assert "Sí" in eventos


def test_extension_de_tensores_solo_si_hay_filas(app):
    with app.app_context():
        adaptador = Adaptador()
        adaptador.source_id = "central"
        trabajo = app.config["WORKSPACE_ROOT"] / "sin_tensores"
        (trabajo / "datos").mkdir(parents=True, exist_ok=True)
        (trabajo / "datos/central_tensores.csv").write_text(
            "id_evento,id_origen,tensor_id\n", encoding="utf-8"
        )

        assert adaptador.extensiones(None, "", trabajo) == {}

        (trabajo / "datos/central_tensores.csv").write_text(
            "id_evento,id_origen,tensor_id\ne-1,o-1,t-1\n", encoding="utf-8"
        )
        assert adaptador.extensiones(None, "", trabajo) == {
            "tensores": "datos/central_tensores.csv"
        }


class _CursorFalso:
    def __init__(self, filas):
        self.filas = filas

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, *_args, **_kwargs):
        return None

    def fetchall(self):
        return self.filas


class _ConexionFalsa:
    def __init__(self, filas):
        self.filas = filas

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def cursor(self):
        return _CursorFalso(self.filas)


class _CursorRango:
    def __init__(self, rango):
        self.rango = rango

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, *_args, **_kwargs):
        return None

    def fetchone(self):
        return self.rango


class _ConexionRango:
    def __init__(self, rango):
        self.rango = rango

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def cursor(self):
        return _CursorRango(self.rango)


def test_disponibilidad_global_y_cache(app, monkeypatch):
    with app.app_context():
        app.config["RCS_CENTRAL_DSN"] = "postgresql://fake"
        adaptador = Adaptador()
        adaptador.source_id = "central"
        rango = (
            datetime(1982, 9, 18, tzinfo=UTC),
            datetime(2025, 3, 31, tzinfo=UTC),
        )
        llamados = []

        def _conectar():
            llamados.append(1)
            return _ConexionRango(rango)

        monkeypatch.setattr(adaptador, "_conectar", _conectar)

        primero = adaptador.disponibilidad()
        segundo = adaptador.disponibilidad()

        assert primero == {"desde": rango[0], "hasta": rango[1]}
        assert segundo == primero
        assert len(llamados) == 1


def test_validar_periodo_filtra_por_analista(app, monkeypatch):
    with app.app_context():
        usuario = _usuario("ana2", "analista", "eatl")
        job = _job(usuario.id)
        adaptador = Adaptador()
        adaptador.source_id = "central"
        filas = [
            ("eatl", datetime(2026, 10, 1, tzinfo=UTC)),
            ("otro", datetime(2026, 10, 2, tzinfo=UTC)),
        ]
        monkeypatch.setattr(
            adaptador, "_conectar", lambda: _ConexionFalsa(filas)
        )

        resultado = adaptador.validar_periodo(job)

        assert resultado["ok"] is True
        assert resultado["eventos"] == 1


def test_validar_periodo_sin_eventos_es_advertencia(app, monkeypatch):
    with app.app_context():
        usuario = _usuario("ana3", "analista", "eatl")
        job = _job(usuario.id)
        adaptador = Adaptador()
        adaptador.source_id = "central"
        monkeypatch.setattr(adaptador, "_conectar", lambda: _ConexionFalsa([]))
        rango = {
            "desde": datetime(1982, 9, 18, tzinfo=UTC),
            "hasta": datetime(2025, 3, 31, tzinfo=UTC),
        }

        resultado = adaptador.validar_periodo(job, rango)

        assert resultado["ok"] is True
        assert resultado["eventos"] == 0
        assert resultado["errores"] == []
        assert "Rango disponible" in " ".join(resultado["advertencias"])


def test_validar_periodo_sin_codigo_es_advertencia(app, monkeypatch):
    with app.app_context():
        usuario = _usuario("sin-codigo", "analista", "")
        job = _job(usuario.id)
        adaptador = Adaptador()
        adaptador.source_id = "central"
        monkeypatch.setattr(adaptador, "_conectar", lambda: _ConexionFalsa([]))

        resultado = adaptador.validar_periodo(job)

        assert resultado["ok"] is True
        assert resultado["eventos"] == 0
        assert "código de analista" in " ".join(resultado["advertencias"])


def test_validar_periodo_error_de_conexion(app, monkeypatch):
    with app.app_context():
        usuario = _usuario("ana4", "analista", "eatl")
        job = _job(usuario.id)
        adaptador = Adaptador()
        adaptador.source_id = "central"

        def _falla():
            raise RuntimeError("sin conexión")

        monkeypatch.setattr(adaptador, "_conectar", _falla)

        resultado = adaptador.validar_periodo(job)

        assert resultado["ok"] is False
        assert "sin conexión" in " ".join(resultado["errores"])


class _CursorConsultas:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.consultas = []

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, consulta, parametros=None):
        self.consultas.append((consulta, parametros))

    def fetchall(self):
        return self.respuestas.pop(0)


class _ConexionConsultas:
    def __init__(self, respuestas):
        self.cursor_falso = _CursorConsultas(respuestas)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def cursor(self, **_kwargs):
        return self.cursor_falso


def test_elegir_origen_local_por_tiempo_y_posicion():
    evento = {
        "event_id": "e-1",
        "origin_time": datetime(2025, 1, 1, 0, 0, tzinfo=UTC),
        "latitude": -30.0,
        "longitude": -71.0,
    }
    candidatos = [
        {
            "origin_id": "lejano",
            "origin_time": datetime(2025, 1, 1, 0, 0, 5, tzinfo=UTC),
            "latitude": -30.0,
            "longitude": -71.0,
            "creation_time": datetime(2025, 1, 2, tzinfo=UTC),
        },
        {
            "origin_id": "cercano",
            "origin_time": datetime(2025, 1, 1, 0, 0, 0, 300000, tzinfo=UTC),
            "latitude": -30.0001,
            "longitude": -71.0001,
            "creation_time": datetime(2025, 1, 1, tzinfo=UTC),
        },
    ]

    elegido = _elegir_origen_local(evento, candidatos)

    assert elegido is not None
    assert elegido["origin_id"] == "cercano"


class _ResolutorFalso:
    def __init__(self, _config):
        pass

    def resolver(self, _selector, station, **_kwargs):
        coordenadas = {
            "PB01": (-21.04, -69.48, 900.0),
            "PB02": (-21.31, -69.89, 1015.0),
        }
        if station not in coordenadas:
            return None
        lat, lon, elev = coordenadas[station]
        return EstacionLista(
            network="C1",
            station=station,
            latitude=lat,
            longitude=lon,
            elevation_m=elev,
            source_file="STATION0.HYP",
        )


def test_consultar_arribos_publicado_y_no_publicado(app, monkeypatch):
    with app.app_context():
        adaptador = Adaptador()
        adaptador.source_id = "central"
        monkeypatch.setattr(
            "app.domain.catalogs.adapters.central.ResolutorEstaciones",
            _ResolutorFalso,
        )
        eventos = [
            {
                "event_id": "e-publicado",
                "origin_id": "o-publicado",
                "software": "eventquery_catalog",
                "tiene_picks": False,
                "origin_time": datetime(2025, 1, 1, 0, 0, tzinfo=UTC),
                "latitude": -30.0,
                "longitude": -71.0,
                "author": "ana",
            },
            {
                "event_id": "e-local",
                "origin_id": "o-local",
                "software": "Seisan_v9.1",
                "tiene_picks": True,
                "origin_time": datetime(2025, 1, 2, 0, 0, tzinfo=UTC),
                "latitude": -31.0,
                "longitude": -72.0,
                "author": "beto",
            },
        ]
        origenes = [
            {
                "event_id": "e-publicado",
                "origin_id": "o-local-publicado",
                "software": "Seisan_v9.1",
                "author": "ana",
                "origin_time": datetime(2025, 1, 1, 0, 0, tzinfo=UTC),
                "latitude": -30.0,
                "longitude": -71.0,
                "creation_time": datetime(2025, 1, 1, 1, 0, tzinfo=UTC),
            }
        ]
        picks = [
            {
                "origin_id": "o-local-publicado",
                "pick_id": "p-1",
                "channel": "C1.PB01..HHZ",
                "pick_time": datetime(2025, 1, 1, 0, 0, 30, tzinfo=UTC),
                "phase": "P",
                "polarity": "UP",
                "uncertainty": 1.25,
                "probability": None,
                "weight": 1.0,
                "pick_status": "manual",
            },
            {
                "origin_id": "o-local",
                "pick_id": "p-2",
                "channel": "C1.PB02..HHZ",
                "pick_time": datetime(2025, 1, 2, 0, 0, 40, tzinfo=UTC),
                "phase": "S",
                "polarity": None,
                "uncertainty": None,
                "probability": None,
                "weight": 0.0,
                "pick_status": "manual",
            },
        ]
        conexion = _ConexionConsultas([origenes, picks])
        monkeypatch.setattr(adaptador, "_conectar", lambda: conexion)

        filas = adaptador._consultar_arribos(
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 31, tzinfo=UTC),
            eventos,
        )

        assert len(filas) == 2
        por_evento = {fila["id_evento"]: fila for fila in filas}
        publicado = por_evento["e-publicado"]
        assert publicado["id_origen"] == "o-local-publicado"
        assert publicado["est_lat"] == -21.04
        assert publicado["est_lista"] == "STATION0.HYP"
        assert publicado["est_vigencia"] == "current"
        assert publicado["base_datos"] == "Seisan_v9.1"
        assert publicado["fase"] == "P"
        assert publicado["usada"] == "True"
        assert publicado["residual_s"] == 1.25
        local = por_evento["e-local"]
        assert local["id_origen"] == "o-local"
        assert local["est_lat"] == -21.31
        assert local["fase"] == "S"
        assert local["usada"] == "False"
        assert local["residual_s"] == ""


def test_exportar_escribe_arribos_y_extension(app, tmp_path, monkeypatch):
    with app.app_context():
        usuario = _usuario("admin-arribos", "admin", "")
        job = _job(usuario.id)
        adaptador = Adaptador()
        adaptador.source_id = "central"
        monkeypatch.setattr(
            adaptador, "_consultar", lambda _inicio, _fin: (_eventos(), _tensores())
        )
        monkeypatch.setattr(
            adaptador,
            "_consultar_arribos",
            lambda _inicio, _fin, _eventos: [
                {
                    "id_evento": "e-1",
                    "id_origen": "o-1",
                    "id_pick": "p-1",
                    "red": "C1",
                    "estacion": "PB01",
                    "loc": "",
                    "cha": "HHZ",
                    "fase": "P",
                    "llegada_utc": "2026-10-01 00:00:30",
                    "llegada_us": "000000",
                    "est_lat": -21.04,
                    "est_lon": -69.48,
                    "usada": "True",
                }
            ],
        )

        adaptador.exportar(tmp_path, job)

        ruta = tmp_path / adaptador._ruta_fases(job)
        assert ruta.is_file()
        assert adaptador.extensiones(job, "", tmp_path)["arribos"] == adaptador._ruta_fases(job)


def _workspace_canonico_central(tmp_path):
    from app.domain.catalogs import arribos_csv
    from app.domain.catalogs.canonical import escribir_desde_csv, escribir_extensiones

    workspace = tmp_path / "ws"
    (workspace / "datos").mkdir(parents=True)
    catalogo = workspace / "datos" / "central_parametros.csv"
    catalogo.write_text(
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista,"
        "Publicado,Revisión,id_evento,id_origen\n"
        "0,2025-03-26 12:18:20,-30.370,-69.571,13.2,3.1,ML,jaba,"
        "Sí,Final,e-1,o-eq\n",
        encoding="utf-8",
    )
    escribir_desde_csv(workspace, "central", "local_db", catalogo)
    fases = workspace / "datos" / "central_fases.csv"
    arribos_csv.escribir(
        fases,
        [
            {
                "id_evento": "e-1",
                "id_origen": "o-eq",
                "id_pick": "p-1",
                "red": "C1",
                "estacion": "CO01",
                "loc": "",
                "cha": "HHZ",
                "fase": "P",
                "llegada_utc": "2025-03-26 12:18:32",
                "llegada_us": "630000",
                "est_lat": -29.9773,
                "est_lon": -70.094,
                "est_lista": "seiscomp_inventory",
                "est_vigencia": "event_epoch",
                "software": "SeisComP3",
            }
        ],
    )
    escribir_extensiones(
        workspace, "central", "local_db", {"arribos": "datos/central_fases.csv"}
    )
    return workspace


def test_revisar_fila_central_en_las_tres_tablas(tmp_path):
    from app.services.station_review import revisar_fila

    workspace = _workspace_canonico_central(tmp_path)
    casos = [
        (
            "no_publicados",
            "central",
            {
                "Fecha_Hora": "2025-03-26 12:18:20",
                "Latitud": "-30.370",
                "Longitud": "-69.571",
            },
        ),
        (
            "no_actualizados",
            "central",
            {
                "fecha_local": "2025-03-26 12:18:20",
                "lat_local": "-30.370",
                "lon_local": "-69.571",
            },
        ),
        (
            "repetidos",
            "central_estricto",
            {
                "fecha_hora": "2025-03-26 12:18:20",
                "latitud": "-30.370",
                "longitud": "-69.571",
            },
        ),
    ]

    for tabla, opcion, fila in casos:
        revision = revisar_fila(workspace, tabla, opcion, fila)
        assert revision is not None, tabla
        assert revision["estado"] == "ok", tabla
        assert revision["tiene_coordenadas"] is True, tabla
        assert revision["tiene_tiempos"] is True, tabla
        punto = next(
            punto
            for punto in revision["estaciones_mapa"]
            if punto["estacion"] == "CO01"
        )
        assert punto["est_lista"] == "Inventario SeisComp", tabla
        assert punto["est_vigencia"] == "event_epoch", tabla
        assert punto["software"] == "SeisComP3", tabla


def test_elegir_origen_local_prefiere_solucion_revisada():
    evento = {
        "event_id": "e-1",
        "origin_time": datetime(2025, 1, 1, 0, 0, tzinfo=UTC),
        "latitude": -30.0,
        "longitude": -71.0,
    }
    base = {
        "origin_time": datetime(2025, 1, 1, 0, 0, tzinfo=UTC),
        "latitude": -30.0,
        "longitude": -71.0,
    }
    candidatos = [
        dict(base, origin_id="automatico", status="AUTOMATIC",
             creation_time=datetime(2025, 1, 3, tzinfo=UTC)),
        dict(base, origin_id="revisado", status="REVIEWED",
             creation_time=datetime(2025, 1, 2, tzinfo=UTC)),
    ]

    elegido = _elegir_origen_local(evento, candidatos)

    assert elegido is not None
    assert elegido["origin_id"] == "revisado"
