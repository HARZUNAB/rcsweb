#!/usr/bin/env python3
"""Convierte el CSV de sismicidad histórica al .dat tabulado del core.

El catálogo `.dat` que leen ``sismicidad.py`` y ``plotear.py`` tiene una línea
por evento, sin encabezado, con columnas separadas por tabs:

    YYYY-MM-DD  HH:MM:SS<TAB>lat<TAB>lon<TAB>prof<TAB>mag<TAB>tipo<TAB>percibido<TAB>región

Acepta los dos formatos de CSV usados por el proyecto:

- exportación con ``time, latitude, longitude, depth [km], ...``;
- planilla con ``Fecha_Hora, Latitud, Longitud, Prof., Mag., Tipo_mag., ...``.

Uso:
    python core/convertir_catalogo.py core_data/catalogo.csv core_data/catalogo.dat
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

COLUMNAS = {
    "tiempo": ("time", "Fecha_Hora"),
    "lat": ("latitude", "Latitud"),
    "lon": ("longitude", "Longitud"),
    "prof": ("depth [km]", "Prof."),
    "mag": ("magnitude", "Mag."),
    "tipo": ("magnitude_type", "Tipo_mag."),
    "percibido": ("felt", "Percep", "Percep."),
    "region": ("region_name", "Referencia"),
}
COLUMNAS_OBLIGATORIAS = ("tiempo", "lat", "lon", "prof")


def _columna(campos: list[str], opciones: tuple[str, ...]) -> str | None:
    for opcion in opciones:
        if opcion in campos:
            return opcion
    return None


def _resolver_columnas(campos: list[str]) -> dict[str, str | None]:
    columnas = {
        clave: _columna(campos, opciones) for clave, opciones in COLUMNAS.items()
    }
    faltantes = [
        clave for clave in COLUMNAS_OBLIGATORIAS if columnas.get(clave) is None
    ]
    if faltantes:
        raise ValueError(
            "Faltan columnas en el CSV: "
            + ", ".join(
                " o ".join(COLUMNAS[clave]) for clave in faltantes
            )
        )
    return columnas


def _numero(valor, formato: str) -> str:
    valor = (valor or "").strip()
    if not valor:
        return ""
    try:
        return formato.format(float(valor))
    except ValueError:
        return ""


def _fecha(valor: str) -> str:
    texto = (valor or "").strip().replace("Z", "+00:00")
    if not texto:
        return ""
    try:
        return datetime.fromisoformat(texto).strftime("%Y-%m-%d  %H:%M:%S")
    except ValueError:
        return texto


def _percibido(valor: str) -> str:
    texto = (valor or "").strip().lower()
    if texto in ("t", "s", "sí", "si", "true", "1"):
        return "S"
    return "N"


def convertir(entrada: Path, salida: Path) -> tuple[int, str, str]:
    """Convierte ``entrada`` y devuelve (filas, primera fecha, última fecha)."""
    salida.parent.mkdir(parents=True, exist_ok=True)
    filas = 0
    primera = ""
    ultima = ""

    with entrada.open(encoding="utf-8-sig", newline="") as origen:
        lector = csv.DictReader(origen)
        columnas = _resolver_columnas(lector.fieldnames or [])

        with salida.open("w", encoding="utf-8", newline="") as destino:
            for fila in lector:
                fecha = _fecha(fila.get(columnas["tiempo"], ""))
                destino.write(
                    "\t".join(
                        [
                            fecha,
                            _numero(fila.get(columnas["lat"]), "{:.3f}"),
                            _numero(fila.get(columnas["lon"]), "{:.3f}"),
                            _numero(fila.get(columnas["prof"]), "{:.1f}"),
                            _numero(
                                fila.get(columnas["mag"])
                                if columnas["mag"]
                                else "",
                                "{:.1f}",
                            ),
                            (
                                (fila.get(columnas["tipo"]) or "").strip()
                                if columnas["tipo"]
                                else ""
                            ),
                            _percibido(
                                fila.get(columnas["percibido"], "")
                                if columnas["percibido"]
                                else ""
                            ),
                            (
                                (fila.get(columnas["region"]) or "").strip()
                                if columnas["region"]
                                else ""
                            ),
                        ]
                    )
                    + "\n"
                )
                filas += 1
                if not primera:
                    primera = fecha
                ultima = fecha

    return filas, primera, ultima


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Convierte el catálogo CSV de sismicidad histórica al .dat "
            "tabulado que lee el core."
        )
    )
    parser.add_argument("entrada", type=Path, help="CSV de entrada")
    parser.add_argument("salida", type=Path, help="DAT de salida")
    args = parser.parse_args()

    if not args.entrada.is_file():
        print(f"No existe el archivo de entrada: {args.entrada}", file=sys.stderr)
        return 1

    try:
        filas, primera, ultima = convertir(args.entrada, args.salida)
    except (OSError, ValueError) as error:
        print(f"No se pudo convertir: {error}", file=sys.stderr)
        return 1

    if not filas:
        print("No se generaron filas: revise el CSV de entrada.", file=sys.stderr)
        return 1

    print(f"{args.salida}: {filas} filas")
    print(f"Rango: {primera} → {ultima}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
