"""Pruebas del informe compacto de solicitudes de revisión."""

from __future__ import annotations

from docx import Document

from app.services import review_report


def _evento() -> dict:
    return {
        "fila": {
            "evento": "seiscomp:000584",
            "id_evento_fuente": "csn_prueba",
            "fecha_hora": "2026-11-06 07:23:35",
            "latitud": -28.359,
            "longitud": -71.875,
            "profundidad_km": 46.5,
            "magnitud": 3.6,
            "magnitud_tipo": "MLv",
            "analista": "maca",
            "cruce_eventquery": "con_cruce",
            "sospechoso": "Sí",
            "prioridad": "Alta",
            "motivo_prioridad": "Localización",
            "contexto": "débil",
            "n_usadas": 14,
            "max_residual_usado": 1.0,
        },
        "canonico": {},
        "clasificacion": {"residuo_km": 33.1, "perfil": "perfil-prueba"},
        "url": "http://localhost:8000/jobs/job/resultados/catalogos/seiscomp/584",
    }


def test_resumen_compacto():
    datos = dict(review_report._resumen(_evento()))

    assert datos["Solución"] == "Sospechosa"
    assert datos["Motivo de prioridad"] == "Localización"
    assert "residuo" not in datos["Solución"]
    for clave in (
        "Perfil",
        "Motivo",
        "Cobertura",
        "Estaciones usadas",
        "Máximo residual",
        "Enlace",
    ):
        assert clave not in datos


def test_resumen_traduce_solucion_y_motivo():
    evento = _evento()
    evento["fila"]["sospechoso"] = "No"
    evento["fila"]["motivo_prioridad"] = ""
    evento["fila"]["motivo"] = "fase"
    datos = dict(review_report._resumen(evento))
    assert datos["Solución"] == "Normal"
    assert datos["Motivo de prioridad"] == "Fases"

    evento["fila"]["sospechoso"] = "Desconocido"
    datos = dict(review_report._resumen(evento))
    assert datos["Solución"] == "Sin evaluar"


def test_docx_no_imprime_evidencia_ni_enlace(tmp_path):
    datos = {
        "job_id": "job-prueba",
        "source": "seiscomp",
        "creado_por": "admin",
        "asignado": "maca",
        "notified_at": "2026-11-18 10:00",
        "eventos": [_evento()],
        "nota": "",
    }
    ruta = tmp_path / "informe.docx"
    review_report.generar_docx(datos, ruta)

    documento = Document(ruta)
    textos = [parrafo.text for parrafo in documento.paragraphs]
    for tabla in documento.tables:
        for fila in tabla.rows:
            for celda in fila.cells:
                textos.append(celda.text)
    unido = "\n".join(textos)

    assert "Solución" in unido
    assert "Sospechosa" in unido
    assert "Motivo de prioridad" in unido
    assert "Evidencia de fases" not in unido
    assert "Sin inconsistencia de fases." not in unido
    assert "residuo" not in unido
    assert "http://localhost" not in unido
