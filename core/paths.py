"""Rutas internas del core incorporado a RCS Web.

El código del core vive en ``core/``. Los datos grandes (grillas, relieves,
sismicidad histórica y localidades) viven en ``core_data/`` para no mezclarlos
con el código versionado ni con la imagen Docker.
"""

from __future__ import annotations

import os
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(
    os.environ.get("RCS_CORE_DATA", CORE_DIR.parent / "core_data")
).resolve()

# Catálogo de sismicidad histórica validado. El .dat es el que leen
# sismicidad.py y plotear.py; el .csv es la versión tabular de referencia.
CATALOGO_SISMICIDAD = "base_2018_2026.dat"
CATALOGO_SISMICIDAD_CSV = "base_2018_2026.csv"
