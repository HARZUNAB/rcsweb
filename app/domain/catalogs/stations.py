"""Catálogo de estaciones para resolver coordenadas antes de escribir el canónico.

Este módulo no conoce eventos, comparaciones ni interfaz. Solo lee listas de
estaciones y responde qué coordenada corresponde a un código, según la lista
que el adaptador haya declarado en el manifiesto.

Los proveedores son extensibles: hoy existen ``seisan_hyp`` (archivos
``STATION*.HYP``) y ``seiscomp_inventory`` (inventario de SeisComp). Una fuente
futura puede declarar otro proveedor sin tocar la app.
"""

from __future__ import annotations

import logging
import math
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

LOG = logging.getLogger(__name__)

# Código de 3 a 5 caracteres, latitud DDMM.mm con hemisferio, longitud DDDMM.mm
# con hemisferio, elevación opcional y corrección opcional.
PATRON_STATION_HYP = re.compile(
    r"^\s*(\S{3,5})\s*"
    r"(\d{2})(\d{2}\.\d+)([NS])\s*"
    r"(\d{2,3})(\d{2}\.\d+)([EW])"
    r"\s*(-?\d+)?"
)


def _texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


def _numero(valor) -> float | None:
    try:
        return float(str(valor).strip())
    except (TypeError, ValueError):
        return None


def _naive_utc(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    if valor.tzinfo is not None:
        return valor.astimezone(UTC).replace(tzinfo=None)
    return valor


def _config_valor(nombre: str) -> str:
    """Lee una variable de entorno o, si existe, la configuración de Flask."""
    valor = os.environ.get(nombre, "").strip()
    if valor:
        return valor
    try:
        from flask import current_app

        if current_app:
            return str(current_app.config.get(nombre, "") or "").strip()
    except (ImportError, RuntimeError):
        pass
    return ""


def distancia_km(lat1, lon1, lat2, lon2) -> float | None:
    """Distancia haversine entre dos puntos, en kilómetros."""
    valores = [_numero(lat1), _numero(lon1), _numero(lat2), _numero(lon2)]
    if any(valor is None for valor in valores):
        return None
    a, b, c, d = valores
    radio = 6371.0088
    phi1, phi2 = math.radians(a), math.radians(c)
    dphi = math.radians(c - a)
    dlambda = math.radians(d - b)
    h = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * radio * math.asin(min(1.0, math.sqrt(h)))


def azimut_grados(lat1, lon1, lat2, lon2) -> float | None:
    """Azimut inicial desde el evento hacia la estación, en grados."""
    valores = [_numero(lat1), _numero(lon1), _numero(lat2), _numero(lon2)]
    if any(valor is None for valor in valores):
        return None
    a, b, c, d = valores
    phi1, phi2 = math.radians(a), math.radians(c)
    dlambda = math.radians(d - b)
    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(
        dlambda
    )
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


@dataclass(frozen=True)
class EstacionLista:
    """Una estación tal como aparece en una lista de referencia."""

    network: str
    station: str
    latitude: float
    longitude: float
    elevation_m: float | None = None
    place: str = ""
    country: str = ""
    start_time: datetime | None = None
    end_time: datetime | None = None
    source_file: str = ""

    @property
    def time_basis(self) -> str:
        return "event_epoch" if self.start_time or self.end_time else "current"

    @property
    def clave(self) -> tuple[str, str]:
        return (self.network.upper(), self.station.upper())


class CatalogoEstaciones:
    """Índice de estaciones por código, con resolución de ambigüedades."""

    def __init__(self) -> None:
        self._por_estacion: dict[str, list[EstacionLista]] = {}
        self._vistos: set[tuple] = set()

    def agregar(self, estacion: EstacionLista) -> None:
        if not estacion.station:
            return
        if not (-90.0 <= estacion.latitude <= 90.0):
            return
        if not (-180.0 <= estacion.longitude <= 180.0):
            return
        huella = (
            estacion.station.upper(),
            round(estacion.latitude, 5),
            round(estacion.longitude, 5),
            round(estacion.elevation_m or 0.0, 1),
            _naive_utc(estacion.start_time),
            _naive_utc(estacion.end_time),
        )
        if huella in self._vistos:
            return
        self._vistos.add(huella)
        self._por_estacion.setdefault(estacion.station.upper(), []).append(estacion)

    def __len__(self) -> int:
        return len(self._por_estacion)

    def _vigente(self, estacion: EstacionLista, instante: datetime | None) -> bool:
        if instante is None:
            return True
        inicio = _naive_utc(estacion.start_time)
        fin = _naive_utc(estacion.end_time)
        if inicio is None and fin is None:
            return True
        momento = _naive_utc(instante)
        if inicio is not None and momento < inicio:
            return False
        if fin is not None and momento > fin:
            return False
        return True

    def resolver(
        self,
        station: str,
        *,
        network: str = "",
        lat_evento=None,
        lon_evento=None,
        instante: datetime | None = None,
        distancia: float | None = None,
    ) -> EstacionLista | None:
        candidatos = self._por_estacion.get(_texto(station).upper(), [])
        if not candidatos:
            return None

        red = _texto(network).upper()
        if red:
            misma_red = [
                estacion
                for estacion in candidatos
                if estacion.network.upper() == red
            ]
            if misma_red:
                candidatos = misma_red
            elif any(estacion.network for estacion in candidatos):
                # El inventario tiene redes, pero ninguna coincide: no se debe
                # usar la estación de otra red. Las listas STATION no tienen
                # red y sí se aceptan como respaldo.
                return None

        con_epoca = [
            estacion
            for estacion in candidatos
            if estacion.start_time is not None or estacion.end_time is not None
        ]
        if instante is not None and con_epoca:
            vigentes = [
                estacion
                for estacion in con_epoca
                if self._vigente(estacion, instante)
            ]
            if vigentes:
                candidatos = vigentes
            else:
                sin_epoca = [estacion for estacion in candidatos if estacion not in con_epoca]
                if not sin_epoca:
                    return None
                candidatos = sin_epoca

        def _puntaje(estacion: EstacionLista) -> tuple:
            distancia_estacion = distancia_km(
                lat_evento, lon_evento, estacion.latitude, estacion.longitude
            )
            if distancia_estacion is None:
                return (0.0, estacion.source_file)
            if distancia is not None:
                return (abs(distancia_estacion - distancia), estacion.source_file)
            return (distancia_estacion, estacion.source_file)

        return min(candidatos, key=_puntaje)


def leer_station_hyp(ruta: Path) -> list[EstacionLista]:
    """Lee un archivo ``STATION*.HYP`` de Seisan."""
    estaciones: list[EstacionLista] = []
    try:
        lineas = ruta.read_text(encoding="latin-1", errors="replace").splitlines()
    except OSError:
        return estaciones

    for linea in lineas:
        coincidencia = PATRON_STATION_HYP.match(linea)
        if coincidencia is None:
            continue
        (
            codigo,
            lat_grados,
            lat_minutos,
            lat_hemisferio,
            lon_grados,
            lon_minutos,
            lon_hemisferio,
            elevacion,
        ) = coincidencia.groups()
        latitud = int(lat_grados) + float(lat_minutos) / 60.0
        longitud = int(lon_grados) + float(lon_minutos) / 60.0
        if lat_hemisferio == "S":
            latitud = -latitud
        if lon_hemisferio == "W":
            longitud = -longitud
        estaciones.append(
            EstacionLista(
                network="",
                station=codigo.strip().upper(),
                latitude=latitud,
                longitude=longitud,
                elevation_m=_numero(elevacion),
                source_file=ruta.name,
            )
        )
    return estaciones


def cargar_seisan_hyp(
    directorio: Path | str, patron: str = "STATION*.HYP"
) -> CatalogoEstaciones:
    """Carga todas las listas ``STATION*.HYP`` de un directorio."""
    catalogo = CatalogoEstaciones()
    ruta = Path(directorio).expanduser()
    if not ruta.is_dir():
        LOG.warning("No existe el directorio de estaciones de Seisan: %s", ruta)
        return catalogo
    for archivo in sorted(ruta.glob(patron), key=lambda item: item.name.lower()):
        for estacion in leer_station_hyp(archivo):
            catalogo.agregar(estacion)
    return catalogo


def _config_seiscomp() -> dict[str, str]:
    return {
        "host": _config_valor("SEISCOMP_DB_HOST"),
        "port": _config_valor("SEISCOMP_DB_PORT") or "5432",
        "database": _config_valor("SEISCOMP_DB_NAME") or "seiscomp2",
        "user": _config_valor("SEISCOMP_DB_USER"),
        "password": _config_valor("SEISCOMP_DB_PASSWORD"),
    }


def cargar_inventario_seiscomp() -> CatalogoEstaciones:
    """Carga el inventario de estaciones de SeisComp, con sus épocas."""
    catalogo = CatalogoEstaciones()
    config = _config_seiscomp()
    if not (config["host"] and config["user"] and config["password"]):
        LOG.warning("SeisComp no está configurado; no se puede leer su inventario.")
        return catalogo
    try:
        import psycopg2

        conexion = psycopg2.connect(
            host=config["host"],
            port=int(config["port"]),
            dbname=config["database"],
            user=config["user"],
            password=config["password"],
            connect_timeout=8,
            options=(
                "-c default_transaction_read_only=on "
                "-c statement_timeout=30000"
            ),
        )
        try:
            cursor = conexion.cursor()
            cursor.execute(
                """
                SELECT n.m_code, s.m_code, s.m_latitude, s.m_longitude,
                       s.m_elevation, s.m_place, s.m_country, s.m_start, s.m_end
                  FROM station s
                  JOIN network n ON n._oid = s._parent_oid
                 WHERE s.m_latitude IS NOT NULL
                   AND s.m_longitude IS NOT NULL
                """
            )
            filas = cursor.fetchall()
        finally:
            conexion.close()
    except Exception as exc:  # noqa: BLE001
        LOG.warning("No se pudo leer el inventario de SeisComp: %s", exc)
        return catalogo

    for red, estacion, latitud, longitud, elevacion, lugar, pais, inicio, fin in filas:
        catalogo.agregar(
            EstacionLista(
                network=_texto(red).upper(),
                station=_texto(estacion).upper(),
                latitude=float(latitud),
                longitude=float(longitud),
                elevation_m=_numero(elevacion),
                place=_texto(lugar),
                country=_texto(pais),
                start_time=_naive_utc(inicio),
                end_time=_naive_utc(fin),
                source_file="seiscomp_inventory",
            )
        )
    return catalogo


def cargar_proveedor(config: dict | None) -> CatalogoEstaciones:
    """Carga un proveedor declarado en el manifiesto."""
    config = dict(config or {})
    tipo = _texto(config.get("kind"))
    if tipo == "seisan_hyp":
        nombre_dir = _texto(config.get("dir_env"))
        directorio = _config_valor(nombre_dir) if nombre_dir else ""
        directorio = directorio or _texto(config.get("dir"))
        return cargar_seisan_hyp(
            directorio, _texto(config.get("glob")) or "STATION*.HYP"
        )
    if tipo == "seiscomp_inventory":
        return cargar_inventario_seiscomp()
    if tipo:
        LOG.warning("Proveedor de estaciones desconocido: %s", tipo)
    return CatalogoEstaciones()


class ResolutorEstaciones:
    """Selecciona el proveedor según una regla del manifiesto."""

    def __init__(self, config: dict | None = None) -> None:
        self.config = dict(config or {})
        self.providers = dict(self.config.get("providers") or {})
        self.rules = list(self.config.get("rules") or [])
        self.default = _texto(self.config.get("default"))
        if not self.default and self.providers:
            self.default = next(iter(self.providers))
        self._catalogos: dict[str, CatalogoEstaciones] = {}

    def _catalogo(self, nombre: str) -> CatalogoEstaciones:
        if nombre not in self._catalogos:
            self._catalogos[nombre] = cargar_proveedor(self.providers.get(nombre))
        return self._catalogos[nombre]

    def _proveedor(self, selector: str) -> tuple[str, str]:
        valor = _texto(selector).lower()
        for regla in self.rules:
            patron = _texto(regla.get("match")).lower()
            if patron and valor.startswith(patron):
                return _texto(regla.get("provider")), _texto(regla.get("fallback"))
        return self.default, ""

    def resolver(
        self,
        selector: str,
        station: str,
        *,
        network: str = "",
        lat_evento=None,
        lon_evento=None,
        instante: datetime | None = None,
        distancia: float | None = None,
    ) -> EstacionLista | None:
        proveedor, respaldo = self._proveedor(selector)
        if proveedor:
            estacion = self._catalogo(proveedor).resolver(
                station,
                network=network,
                lat_evento=lat_evento,
                lon_evento=lon_evento,
                instante=instante,
                distancia=distancia,
            )
            if estacion is not None:
                return estacion
        if respaldo and respaldo != proveedor:
            return self._catalogo(respaldo).resolver(
                station,
                network=network,
                lat_evento=lat_evento,
                lon_evento=lon_evento,
                instante=instante,
                distancia=distancia,
            )
        return None
