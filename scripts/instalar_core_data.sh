#!/usr/bin/env bash
# Copia los datos grandes del core desde una instalación existente.
#
# Uso:
#   scripts/instalar_core_data.sh /ruta/a/revisacatalogosweb
#
# El destino por defecto es core_data/ dentro de este repositorio.
set -euo pipefail

ORIGEN="${1:-${REVISACATALOGOS_SOURCE:-/home/hriquelmez/Desarrollo/revisacatalogosweb}}"
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESTINO="${RCS_CORE_DATA:-$RAIZ/core_data}"

if [ ! -d "$ORIGEN" ]; then
    echo "No existe el directorio de origen: $ORIGEN" >&2
    exit 1
fi

mkdir -p "$DESTINO"

for elemento in \
    grillas \
    plantillas \
    base_2020_2026.dat \
    base_2020_2026.csv \
    localidades.csv \
    NE2_LR_LC_SR_W_DR.tif \
    relieve_chile.tif
do
    if [ -e "$ORIGEN/$elemento" ]; then
        cp -a "$ORIGEN/$elemento" "$DESTINO/"
        echo "Copiado: $elemento"
    else
        echo "Aviso: no se encontró $ORIGEN/$elemento" >&2
    fi
done

echo "Datos del core disponibles en: $DESTINO"
