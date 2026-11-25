"""Pruebas de validación y escritura atómica del canónico."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from app.domain.catalogs import canonical


def _evento_con_bloques() -> dict:
    return {
        "source_id": "seiscomp",
        "event_id": "seiscomp:000001",
        "event_time": "2026-01-01 00:00:00",
        "latitude": -30.0,
        "longitude": -71.0,
        "depth_km": 35.0,
        "magnitude": 4.5,
        "magnitude_type": "MLv",
        "origin_quality": {
            "source": "seiscomp",
            "derived": False,
            "used_phase_count": 12,
        },
        "origin_uncertainty": {
            "source": "seiscomp",
            "derived": False,
            "time": {"value": 0.1},
        },
        "origin_metadata": {
            "source": "seiscomp",
            "derived": False,
            "method_id": "NonLinLoc",
        },
        "magnitude_metadata": {
            "source": "seiscomp",
            "derived": False,
            "uncertainty": 0.2,
        },
    }


def _csv_simple(ruta: Path) -> None:
    with ruta.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow(
            [
                "Fecha_Hora",
                "Latitud",
                "Longitud",
                "Prof.",
                "Mag.",
                "Tipo_mag.",
                "Analista",
            ]
        )
        escritor.writerow(
            [
                "2026-01-01 00:00:00",
                "-30.0",
                "-71.0",
                "35.0",
                "4.5",
                "MLv",
                "ana",
            ]
        )


def test_bloques_con_datos_y_resumen():
    evento = _evento_con_bloques()
    assert all(canonical.bloques_con_datos(evento).values())

    resumen = canonical.resumen_bloques_calidad([evento])
    assert resumen["events"] == 1
    for bloque in canonical.BLOQUES_CALIDAD:
        assert resumen[f"with_{bloque}"] == 1


def test_validar_bloques_calidad_falla_sin_datos():
    assert (
        canonical.validar_bloques_calidad(
            [_evento_con_bloques()],
            ("origin_quality", "origin_uncertainty"),
        )
        == []
    )

    errores = canonical.validar_bloques_calidad(
        [{}],
        ("origin_quality", "origin_uncertainty"),
    )
    assert errores == [
        "El canónico no generó datos en origin_quality.",
        "El canónico no generó datos en origin_uncertainty.",
    ]


def test_escribir_desde_csv_no_reemplaza_si_falla_validacion(tmp_path):
    workspace = tmp_path / "ws"
    csv_normalizado = tmp_path / "normalizado.csv"
    _csv_simple(csv_normalizado)
    destino = canonical.ruta_canonica(workspace, "seiscomp")
    destino.parent.mkdir(parents=True)
    destino.write_text(
        json.dumps({"event_id": "anterior"}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(canonical.CanonicoInvalidoError):
        canonical.escribir_desde_csv(
            workspace,
            "seiscomp",
            "local_export",
            csv_normalizado,
            validar=lambda _ruta: ["fallo de prueba"],
        )

    assert json.loads(destino.read_text(encoding="utf-8"))["event_id"] == (
        "anterior"
    )
    assert not list(destino.parent.glob("*.tmp"))


def test_escribir_desde_csv_reemplaza_si_valida(tmp_path):
    workspace = tmp_path / "ws"
    csv_normalizado = tmp_path / "normalizado.csv"
    _csv_simple(csv_normalizado)

    destino = canonical.escribir_desde_csv(
        workspace,
        "seiscomp",
        "local_export",
        csv_normalizado,
        validar=lambda ruta: canonical.validar_bloques_calidad(
            canonical.leer_eventos(ruta),
            (),
        ),
    )
    evento = json.loads(destino.read_text(encoding="utf-8"))
    assert evento["event_id"] == "seiscomp:000000"
    assert not list(destino.parent.glob("*.tmp"))


def test_escribir_extensiones_agrega_quality_blocks(tmp_path):
    workspace = tmp_path / "ws"
    canonical.escribir_registros(
        canonical.ruta_canonica(workspace, "seiscomp"),
        [_evento_con_bloques()],
    )
    meta = canonical.escribir_extensiones(
        workspace,
        "seiscomp",
        "local_export",
        {},
    )
    assert meta["quality_blocks"]["events"] == 1
    assert meta["quality_blocks"]["with_origin_quality"] == 1
    assert meta["quality_blocks"]["with_origin_uncertainty"] == 1
    assert meta["quality_blocks"]["with_origin_metadata"] == 1
    assert meta["quality_blocks"]["with_magnitude_metadata"] == 1
