"""Pruebas del conversor SeisComp y su paso al canónico."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "core"))

import seiscomp_a_parametros as conversor  # noqa: E402
from seiscomp_campos import COLUMNAS_EXTENDIDAS  # noqa: E402

from app.domain.catalogs import canonical  # noqa: E402

BASE = (
    "id_evento",
    "id_origen",
    "ot_utc",
    "magnitud",
    "tipo_magnitud",
    "fases",
    "rms",
    "azgap",
    "latitud",
    "longitud",
    "profundidad_km",
    "agencia",
    "operador",
    "region",
    "estatus",
)


def _fila(extendida: bool = True) -> dict:
    campos = BASE + (COLUMNAS_EXTENDIDAS if extendida else ()) + ("base_datos",)
    fila = {campo: "" for campo in campos}
    fila.update(
        {
            "id_evento": "csn_sc1",
            "id_origen": "NLL.1",
            "ot_utc": "2026-01-01 00:00:00",
            "magnitud": "4.5",
            "tipo_magnitud": "MLv",
            "fases": "12",
            "rms": "0.25",
            "azgap": "120",
            "latitud": "-30.0",
            "longitud": "-71.0",
            "profundidad_km": "35.0",
            "agencia": "CSN",
            "operador": "ana",
            "region": "Chile",
            "estatus": "confirmed",
            "base_datos": "seiscomp2",
        }
    )
    if extendida:
        fila.update(
            {
                "origin_time_us": "123456",
                "time_uncertainty": "0.1",
                "latitude_uncertainty": "2.5",
                "longitude_uncertainty": "3.5",
                "depth_uncertainty": "4.5",
                "associated_phase_count": "20",
                "used_station_count": "10",
                "associated_station_count": "14",
                "minimum_distance_deg": "0.5",
                "maximum_distance_deg": "2.0",
                "median_distance_deg": "1.2",
                "origin_type": "hypocenter",
                "magnitude_uncertainty": "0.2",
                "magnitude_station_count": "8",
            }
        )
    return fila


def _escribir(ruta: Path, extendida: bool = True) -> None:
    fila = _fila(extendida)
    with ruta.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=list(fila))
        escritor.writeheader()
        escritor.writerow(fila)


def test_conversor_conserva_columnas_extendidas(tmp_path):
    origen = tmp_path / "raw.csv"
    destino = tmp_path / "normalizado.csv"
    _escribir(origen)
    resumen = conversor.convertir(str(origen), str(destino))
    assert resumen["convertidas"] == 1
    with destino.open(encoding="utf-8", newline="") as archivo:
        fila = next(csv.DictReader(archivo))
    assert fila["fases"] == "12"
    assert fila["associated_phase_count"] == "20"
    assert fila["minimum_distance_deg"] == "0.5"
    assert fila["minimum_distance_km"].startswith("55.5")
    assert fila["time_uncertainty"] == "0.1"
    assert fila["magnitude_uncertainty"] == "0.2"


def test_conversor_admite_exportacion_vieja(tmp_path):
    origen = tmp_path / "raw_viejo.csv"
    destino = tmp_path / "normalizado.csv"
    _escribir(origen, extendida=False)
    resumen = conversor.convertir(str(origen), str(destino))
    assert resumen["convertidas"] == 1
    with destino.open(encoding="utf-8", newline="") as archivo:
        fila = next(csv.DictReader(archivo))
    assert fila["associated_phase_count"] == ""
    assert fila["minimum_distance_km"] == ""


def test_conversor_y_canonico_arman_los_bloques(tmp_path):
    origen = tmp_path / "raw.csv"
    normalizado = tmp_path / "normalizado.csv"
    _escribir(origen)
    conversor.convertir(str(origen), str(normalizado))
    destino = canonical.escribir_desde_csv(
        tmp_path / "ws",
        "seiscomp",
        "local_export",
        normalizado,
        es_referencia=False,
        ruta_cruda=origen,
    )
    evento = json.loads(destino.read_text(encoding="utf-8").splitlines()[0])
    calidad = evento["origin_quality"]
    assert calidad["source"] == "seiscomp"
    assert calidad["derived"] is False
    assert calidad["used_phase_count"] == 12
    assert calidad["associated_phase_count"] == 20
    assert calidad["minimum_distance_km"] == 55.598
    assert evento["origin_uncertainty"]["time"]["value"] == 0.1
    assert evento["origin_metadata"]["origin_time_us"] == 123456
    assert evento["magnitude_metadata"]["station_count"] == 8
