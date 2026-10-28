"""Pruebas de miniaturas, mapas y rutas de imágenes."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.extensions import db
from app.models import Job, nuevo_uuid
from app.services import plots
from app.services.workspace import crear_workspace

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 128


def test_fuente_por_tabla():
    assert plots._fuente("no_publicados", "seisan") == "seisan"
    assert plots._fuente("no_actualizados", "seiscomp") == "seiscomp"
    assert plots._fuente("repetidos", "publica_estricto") == "eventquery"
    assert plots._fuente("repetidos", "seiscomp_amplio") == "seiscomp"
    assert plots._fuente("repetidos", "seisan_exclu") == "seisan"


def test_eventos_no_publicados_y_no_actualizados():
    no_pub = {
        "Fecha_Hora": "2026-10-01 00:00:00",
        "Latitud": "-30.0",
        "Longitud": "-71.0",
        "Prof.": "10.0",
        "Mag.": "3.0",
        "Tipo_mag.": "ML",
        "Analista": "ana",
    }
    eventos = plots._eventos("no_publicados", "x.csv", [no_pub], 0)
    assert len(eventos) == 1
    assert eventos[0]["rol"] == "local"
    assert eventos[0]["latitud"] == -30.0

    no_act = {
        "fecha_local": "2026-10-01 00:00:00",
        "lat_local": "-30.0",
        "lon_local": "-71.0",
        "prof_local": "10.0",
        "mag_local": "3.0",
        "tipo_mag_local": "ML",
        "analista": "ana",
        "fecha_eventquery": "2026-10-01 00:00:00",
        "lat_eventquery": "-30.1",
        "lon_eventquery": "-71.1",
        "prof_eventquery": "12.0",
        "mag_eventquery": "3.1",
        "tipo_mag_eventquery": "ML",
    }
    eventos = plots._eventos("no_actualizados", "x.csv", [no_act], 0)
    assert [evento["rol"] for evento in eventos] == ["local", "publicado"]


def test_ruta_cache_no_permite_salir(tmp_path):
    with pytest.raises(ValueError):
        plots._ruta_cache(tmp_path, "miniaturas", "no_publicados", "../fuera.csv", 0)


def test_placeholder_es_png():
    datos = plots._placeholder("Sin perfil", ancho=260, alto=110)
    assert datos.startswith(b"\x89PNG\r\n\x1a\n")


def _job_done():
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, tzinfo=UTC),
        status="done",
    )
    db.session.add(job)
    db.session.commit()
    workspace = crear_workspace(job.id)
    (workspace / "resultados").mkdir(parents=True, exist_ok=True)
    (workspace / "resultados" / "no_publicados_seisan.csv").write_text(
        "Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista\n"
        "2026-10-01 00:00:00,-30.0,-71.0,10.0,3.0,ML,ana\n",
        encoding="utf-8",
    )
    return job


def test_ruta_miniatura_y_mapa(client, login, monkeypatch):
    job = _job_done()
    login()
    monkeypatch.setattr("app.blueprints.results.generar_miniatura", lambda *args, **kwargs: PNG)
    monkeypatch.setattr("app.blueprints.results.generar_mapa", lambda *args, **kwargs: PNG)

    respuesta = client.get(f"/jobs/{job.id}/resultados/no_publicados/seisan/0/miniatura.png")
    assert respuesta.status_code == 200
    assert respuesta.mimetype == "image/png"
    assert respuesta.data.startswith(b"\x89PNG")

    respuesta = client.get(f"/jobs/{job.id}/resultados/no_publicados/seisan/0/mapa.png")
    assert respuesta.status_code == 200
    assert respuesta.mimetype == "image/png"

    assert (
        client.get(f"/jobs/{job.id}/resultados/no_publicados/seisan/99/miniatura.png").status_code
        == 404
    )


def test_generar_miniatura_cachea(app, tmp_path, monkeypatch):
    app.config["RCS_CORE_PATH"] = tmp_path / "core"
    workspace = tmp_path / "ws"
    (workspace / "plots").mkdir(parents=True)
    filas = [
        {
            "Fecha_Hora": "2026-10-01 00:00:00",
            "Latitud": "-30.0",
            "Longitud": "-71.0",
            "Prof.": "10.0",
            "Mag.": "3.0",
            "Tipo_mag.": "ML",
            "Analista": "ana",
        }
    ]
    llamadas = []

    def _falso(eventos, perfil):
        llamadas.append(1)
        return PNG

    monkeypatch.setattr(plots, "_dibujar_miniatura", _falso)
    monkeypatch.setattr(plots, "_perfiles", lambda: [])

    with app.app_context():
        primero = plots.generar_miniatura(
            workspace, "no_publicados", "no_publicados_seisan.csv", filas, 0
        )
        segundo = plots.generar_miniatura(
            workspace, "no_publicados", "no_publicados_seisan.csv", filas, 0
        )

    assert primero == segundo == PNG
    assert len(llamadas) == 1
