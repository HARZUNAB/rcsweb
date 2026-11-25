"""Escritura y lectura del catálogo canónico en JSON Lines.

El pipeline del core sigue usando CSV planos; este módulo los traduce al
contrato canónico para que la app y las extensiones no dependan del formato de
entrada. Además de los eventos, una fuente puede aportar arribos y estaciones
sin arribos, que se guardan como extensiones junto al catálogo.
"""

from __future__ import annotations

import csv
import json
import math
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .schema import (
    SCHEMA_VERSION,
    ArriboCanonico,
    EstacionSinArribosCanonica,
    EventoCanonico,
    TensorMomentoCanonico,
)

EXTENSIONES = {
    "arribos": "arribos.jsonl",
    "estaciones_sin_arribos": "estaciones_sin_arribos.jsonl",
    "tensores": "tensores.jsonl",
}
META = "meta.json"

BLOQUES_CALIDAD = (
    "origin_quality",
    "origin_uncertainty",
    "origin_metadata",
    "magnitude_metadata",
)


class CanonicoInvalidoError(ValueError):
    """El catálogo canónico no cumple la validación de bloques."""


def _texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


def _numero(texto):
    try:
        return float(str(texto).strip())
    except (TypeError, ValueError):
        return None


def _entero(texto):
    numero = _numero(texto)
    return None if numero is None else int(numero)


def _boleano(texto):
    limpio = _texto(texto).lower()
    if limpio in ("1", "true", "t", "si", "sí", "s", "yes", "y", "usada"):
        return True
    if limpio in ("0", "false", "f", "no", "n", "sin usar"):
        return False
    return None


def _indice_crudo(fila: dict) -> int | None:
    """Índice de la fila en el archivo crudo, guardado en la columna 0."""
    for clave in ("", "_indice_crudo", "Unnamed: 0"):
        if clave not in fila:
            continue
        valor = _texto(fila.get(clave))
        if valor.isdigit():
            return int(valor)
    return None


def _ruta(workspace: Path, source_id: str, nombre: str) -> Path:
    return workspace / "catalogo" / source_id / nombre


def ruta_canonica(workspace: Path, source_id: str) -> Path:
    return _ruta(workspace, source_id, "eventos.jsonl")


def ruta_arribos(workspace: Path, source_id: str) -> Path:
    return _ruta(workspace, source_id, EXTENSIONES["arribos"])


def ruta_estaciones_sin_arribos(workspace: Path, source_id: str) -> Path:
    return _ruta(workspace, source_id, EXTENSIONES["estaciones_sin_arribos"])


def ruta_tensores(workspace: Path, source_id: str) -> Path:
    return _ruta(workspace, source_id, EXTENSIONES["tensores"])


def ruta_meta(workspace: Path, source_id: str) -> Path:
    return _ruta(workspace, source_id, META)


def _leer_crudo(ruta: Path | None) -> list[dict]:
    if ruta is None or not ruta.is_file():
        return []
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo))


def _bloques_calidad(fila: dict, source_id: str) -> dict:
    """Bloques opcionales de calidad del origen.

    Si la fuente no aporta las columnas extendidas, los cuatro bloques quedan
    vacíos. Así el contrato es el mismo para todas las fuentes y el consumidor
    no necesita preguntar por la fuente.
    """
    claves = (
        "associated_phase_count",
        "minimum_distance_deg",
        "time_uncertainty",
        "magnitude_uncertainty",
        "origin_type",
    )
    if not any(clave in fila for clave in claves):
        return {
            "origin_quality": {},
            "origin_uncertainty": {},
            "origin_metadata": {},
            "magnitude_metadata": {},
        }

    def numero(clave):
        return _numero(fila.get(clave))

    def primero(*claves):
        for clave in claves:
            valor = numero(clave)
            if valor is not None:
                return valor
        return None

    def texto(clave):
        valor = _texto(fila.get(clave))
        return valor or None

    def lista(clave):
        valor = _texto(fila.get(clave)).replace(";", ",")
        return [item.strip() for item in valor.split(",") if item.strip()]

    def fuente(prefijo):
        return texto(f"{prefijo}_source") or source_id

    def derivado(prefijo):
        return bool(_boleano(fila.get(f"{prefijo}_derived")))

    def derivados(prefijo):
        return lista(f"{prefijo}_derived_fields")

    calidad = {
        "source": fuente("quality"),
        "derived": derivado("quality"),
        "derived_fields": derivados("quality"),
        "used_phase_count": (
            _entero(fila.get("fases"))
            if "fases" in fila
            else _entero(fila.get("used_phase_count"))
        ),
        "associated_phase_count": _entero(fila.get("associated_phase_count")),
        "used_station_count": _entero(fila.get("used_station_count")),
        "associated_station_count": _entero(
            fila.get("associated_station_count")
        ),
        "depth_phase_count": _entero(fila.get("depth_phase_count")),
        "standard_error": primero("standard_error", "rms"),
        "azimuthal_gap": primero("azimuthal_gap", "azgap"),
        "secondary_azimuthal_gap": numero("secondary_azimuthal_gap"),
        "ground_truth_level": texto("ground_truth_level"),
        "minimum_distance_km": numero("minimum_distance_km"),
        "maximum_distance_km": numero("maximum_distance_km"),
        "median_distance_km": numero("median_distance_km"),
    }
    incertidumbre = {
        "source": fuente("unc"),
        "derived": derivado("unc"),
        "derived_fields": derivados("unc"),
        "time": {
            "value": numero("time_uncertainty"),
            "lower": numero("time_lower_uncertainty"),
            "upper": numero("time_upper_uncertainty"),
            "confidence": numero("time_confidence"),
        },
        "latitude": {
            "value": numero("latitude_uncertainty"),
            "lower": numero("latitude_lower_uncertainty"),
            "upper": numero("latitude_upper_uncertainty"),
            "confidence": numero("latitude_confidence"),
        },
        "longitude": {
            "value": numero("longitude_uncertainty"),
            "lower": numero("longitude_lower_uncertainty"),
            "upper": numero("longitude_upper_uncertainty"),
            "confidence": numero("longitude_confidence"),
        },
        "depth": {
            "value": numero("depth_uncertainty"),
            "lower": numero("depth_lower_uncertainty"),
            "upper": numero("depth_upper_uncertainty"),
            "confidence": numero("depth_confidence"),
        },
        "horizontal": {
            "value": numero("horizontal_uncertainty"),
            "min": numero("min_horizontal_uncertainty"),
            "max": numero("max_horizontal_uncertainty"),
            "azimuth_max": numero("azimuth_max_horizontal_uncertainty"),
        },
        "ellipse": {
            "semimajor": numero("ellipse_semimajor"),
            "semiminor": numero("ellipse_semiminor"),
            "semiintermediate": numero("ellipse_semiintermediate"),
            "plunge": numero("ellipse_plunge"),
            "azimuth": numero("ellipse_azimuth"),
            "rotation": numero("ellipse_rotation"),
        },
        "preferred_description": texto(
            "uncertainty_preferred_description"
        ),
        "confidence_level": numero("uncertainty_confidence"),
        "error_ellipse": texto("error_ellipse"),
    }
    metadatos = {
        "source": fuente("origin"),
        "derived": derivado("origin"),
        "derived_fields": derivados("origin"),
        "origin_time_us": _entero(fila.get("origin_time_us")),
        "type": texto("origin_type"),
        "evaluation_mode": texto("evaluation_mode"),
        "method_id": texto("method_id"),
        "earth_model_id": texto("earth_model_id"),
        "depth_type": texto("depth_type"),
        "evaluation_status": texto("evaluation_status")
        or texto("estatus"),
        "software": texto("software"),
        "velocity_model": texto("velocity_model"),
    }
    magnitud = {
        "source": fuente("magnitude"),
        "derived": derivado("magnitude"),
        "derived_fields": derivados("magnitude"),
        "uncertainty": numero("magnitude_uncertainty"),
        "lower_uncertainty": numero("magnitude_lower_uncertainty"),
        "upper_uncertainty": numero("magnitude_upper_uncertainty"),
        "confidence": numero("magnitude_confidence"),
        "station_count": _entero(fila.get("magnitude_station_count")),
        "azimuthal_gap": numero("magnitude_azimuthal_gap"),
        "status": texto("magnitude_status"),
        "method_id": texto("magnitude_method_id"),
    }
    return {
        "origin_quality": calidad,
        "origin_uncertainty": incertidumbre,
        "origin_metadata": metadatos,
        "magnitude_metadata": magnitud,
    }


def _valor_con_datos(valor) -> bool:
    if valor is None:
        return False
    if isinstance(valor, str):
        return valor.strip() not in ("", "-")
    return True


def _calidad_con_datos(calidad: dict) -> bool:
    if not isinstance(calidad, dict):
        return False
    return any(
        _valor_con_datos(calidad.get(clave))
        for clave in (
            "used_phase_count",
            "associated_phase_count",
            "used_station_count",
            "associated_station_count",
            "depth_phase_count",
            "standard_error",
            "azimuthal_gap",
            "secondary_azimuthal_gap",
            "ground_truth_level",
            "minimum_distance_km",
            "maximum_distance_km",
            "median_distance_km",
        )
    )


def _incertidumbre_con_datos(incertidumbre: dict) -> bool:
    if not isinstance(incertidumbre, dict):
        return False
    for eje in ("time", "latitude", "longitude", "depth"):
        datos = incertidumbre.get(eje) or {}
        if any(
            _valor_con_datos(datos.get(clave))
            for clave in ("value", "lower", "upper", "confidence")
        ):
            return True
    horizontal = incertidumbre.get("horizontal") or {}
    if any(
        _valor_con_datos(horizontal.get(clave))
        for clave in ("value", "min", "max", "azimuth_max")
    ):
        return True
    elipse = incertidumbre.get("ellipse") or {}
    if any(
        _valor_con_datos(elipse.get(clave))
        for clave in (
            "semimajor",
            "semiminor",
            "semiintermediate",
            "plunge",
            "azimuth",
            "rotation",
        )
    ):
        return True
    return any(
        _valor_con_datos(incertidumbre.get(clave))
        for clave in (
            "preferred_description",
            "confidence_level",
            "error_ellipse",
        )
    )


def _origen_con_datos(metadatos: dict) -> bool:
    if not isinstance(metadatos, dict):
        return False
    return any(
        _valor_con_datos(metadatos.get(clave))
        for clave in (
            "origin_time_us",
            "type",
            "evaluation_mode",
            "method_id",
            "earth_model_id",
            "depth_type",
            "evaluation_status",
            "software",
            "velocity_model",
        )
    )


def _magnitud_con_datos(magnitud: dict) -> bool:
    if not isinstance(magnitud, dict):
        return False
    return any(
        _valor_con_datos(magnitud.get(clave))
        for clave in (
            "uncertainty",
            "lower_uncertainty",
            "upper_uncertainty",
            "confidence",
            "station_count",
            "azimuthal_gap",
            "status",
            "method_id",
        )
    )


def bloques_con_datos(evento: dict) -> dict[str, bool]:
    """Indica qué bloques normalizados tienen datos útiles."""
    return {
        "origin_quality": _calidad_con_datos(
            evento.get("origin_quality") or {}
        ),
        "origin_uncertainty": _incertidumbre_con_datos(
            evento.get("origin_uncertainty") or {}
        ),
        "origin_metadata": _origen_con_datos(
            evento.get("origin_metadata") or {}
        ),
        "magnitude_metadata": _magnitud_con_datos(
            evento.get("magnitude_metadata") or {}
        ),
    }


def resumen_bloques_calidad(eventos: list[dict]) -> dict:
    """Conteo de eventos con datos en cada bloque."""
    resumen = {
        "events": len(eventos),
        **{f"with_{bloque}": 0 for bloque in BLOQUES_CALIDAD},
    }
    for evento in eventos:
        for bloque, tiene_datos in bloques_con_datos(evento).items():
            if tiene_datos:
                resumen[f"with_{bloque}"] += 1
    return resumen


def validar_bloques_calidad(
    eventos: list[dict],
    bloques_requeridos: tuple[str, ...],
) -> list[str]:
    """Errores de validación para los bloques que exige el formato."""
    if not eventos or not bloques_requeridos:
        return []
    errores = []
    for bloque in bloques_requeridos:
        if bloque not in BLOQUES_CALIDAD:
            errores.append(f"Bloque de calidad desconocido: {bloque}.")
            continue
        if not any(
            bloques_con_datos(evento).get(bloque, False)
            for evento in eventos
        ):
            errores.append(f"El canónico no generó datos en {bloque}.")
    return errores


def leer_eventos(ruta: Path) -> list[dict]:
    """Eventos de un JSONL canónico, útil para validar un temporal."""
    return _lineas_jsonl(ruta)


def escribir_desde_csv(
    workspace: Path,
    source_id: str,
    formato: str,
    ruta_csv: Path,
    *,
    es_referencia: bool | None = None,
    ruta_cruda: Path | None = None,
    validar: Callable[[Path], list[str]] | None = None,
) -> Path:
    """Convierte un CSV plano normalizado al catálogo canónico JSONL.

    ``es_referencia`` decide si las soluciones se marcan como publicadas. Si no
    se indica, se resuelve por el rol del formato en el registro.

    ``ruta_cruda`` es la exportación original. Se usa solo para recuperar
    ``id_evento`` e ``id_origen`` mediante la columna 0 del CSV normalizado, que
    conserva el índice de la fila cruda. Si falta, el evento se escribe igual
    con esos campos vacíos.

    El archivo se escribe en un temporal y solo se reemplaza si ``validar`` no
    devuelve errores. Así una validación fallida no deja un canónico incompleto.
    """
    if es_referencia is None:
        from .registry import formato as _formato

        es_referencia = _formato(formato).rol == "referencia"
    destino = ruta_canonica(workspace, source_id)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(f"{destino.name}.{uuid4().hex}.tmp")
    crudas = _leer_crudo(ruta_cruda)
    try:
        with ruta_csv.open(encoding="utf-8-sig", newline="") as archivo:
            lector = csv.DictReader(archivo)
            with temporal.open("w", encoding="utf-8") as salida:
                for posicion, fila in enumerate(lector):
                    indice = _indice_crudo(fila)
                    if indice is None:
                        indice = posicion
                    original = (
                        crudas[indice] if 0 <= indice < len(crudas) else {}
                    )
                    publicado = _boleano(fila.get("Publicado"))
                    if publicado is None:
                        publicado = _boleano(fila.get("publicado"))
                    if publicado is None:
                        publicado = es_referencia
                    revision = (
                        _texto(fila.get("Revisión"))
                        or _texto(fila.get("Revision"))
                        or _texto(fila.get("revision"))
                    )
                    bloques = _bloques_calidad(fila, source_id)
                    evento = EventoCanonico(
                        source_id=source_id,
                        event_id=f"{source_id}:{indice:06d}",
                        event_time=fila.get("Fecha_Hora") or None,
                        latitude=_numero(fila.get("Latitud")),
                        longitude=_numero(fila.get("Longitud")),
                        depth_km=_numero(fila.get("Prof.")),
                        magnitude=_numero(fila.get("Mag.")),
                        magnitude_type=fila.get("Tipo_mag.", "") or "",
                        agency=source_id,
                        analyst=fila.get("Analista", "") or "",
                        status="published" if publicado else "reported",
                        revision=revision,
                        is_preferred=True,
                        is_published=publicado,
                        source_event_id=(
                            _texto(fila.get("id_evento"))
                            or _texto(original.get("id_evento"))
                        ),
                        origin_id=(
                            _texto(fila.get("id_origen"))
                            or _texto(original.get("id_origen"))
                        ),
                        database=(
                            _texto(fila.get("base_datos"))
                            or _texto(original.get("base_datos"))
                        ),
                        raw_index=indice,
                        origin_quality=bloques["origin_quality"],
                        origin_uncertainty=bloques["origin_uncertainty"],
                        origin_metadata=bloques["origin_metadata"],
                        magnitude_metadata=bloques["magnitude_metadata"],
                        raw=dict(fila),
                    )
                    salida.write(
                        json.dumps(evento.to_dict(), ensure_ascii=False)
                        + "\n"
                    )
        if validar is not None:
            errores = validar(temporal)
            if errores:
                raise CanonicoInvalidoError(
                    "El catálogo canónico no es válido: "
                    + " ".join(errores)
                )
        os.replace(temporal, destino)
    finally:
        temporal.unlink(missing_ok=True)
    return destino


def _lineas_jsonl(ruta: Path) -> list[dict]:
    if not ruta.is_file():
        return []
    salida = []
    with ruta.open(encoding="utf-8") as archivo:
        for linea in archivo:
            if linea.strip():
                salida.append(json.loads(linea))
    return salida


def leer_canonico(workspace: Path, source_id: str) -> list[dict]:
    return _lineas_jsonl(ruta_canonica(workspace, source_id))


def leer_arribos(workspace: Path, source_id: str) -> list[dict]:
    return _lineas_jsonl(ruta_arribos(workspace, source_id))


def leer_estaciones_sin_arribos(workspace: Path, source_id: str) -> list[dict]:
    return _lineas_jsonl(ruta_estaciones_sin_arribos(workspace, source_id))


def leer_tensores(workspace: Path, source_id: str) -> list[dict]:
    return _lineas_jsonl(ruta_tensores(workspace, source_id))


def escribir_registros(ruta: Path, registros: list[dict]) -> None:
    """Escribe una lista de registros canónicos como JSON Lines."""
    _escribir_jsonl(ruta, registros)


def estacion_desde_no_picadas_base(
    fila: dict, source_id: str, event_id: str
) -> dict:
    """Convierte una fila de ``no_picadas_de_evento_desde_base`` al contrato."""
    streams = _texto(fila.get("streams_vigentes_ids"))
    return EstacionSinArribosCanonica(
        source_id=source_id,
        event_id=event_id,
        source_event_id=_texto(fila.get("id_evento")),
        origin_id=_texto(fila.get("id_origen")),
        network=_texto(fila.get("red")),
        station=_texto(fila.get("estacion")),
        location=_texto(fila.get("loc_ref")),
        channel=_texto(fila.get("cha_ref")),
        streams=streams,
        stream_ids=streams,
        distance_km=_numero(fila.get("distancia_km")),
        station_latitude=_numero(fila.get("est_lat")),
        station_longitude=_numero(fila.get("est_lon")),
        station_elevation_m=_numero(fila.get("est_elev")),
        station_place=_texto(fila.get("est_lugar")),
        station_country=_texto(fila.get("est_pais")),
        radio_km=_numero(fila.get("radio_km")),
        activity_window=_entero(fila.get("actividad_ventana")),
        evidence=_texto(fila.get("evidencia")),
        waveform_status=(
            _texto(fila.get("waveform_status")) or "NO_CONSULTADO"
        ),
        availability_source=_texto(fila.get("availability_source")),
        coverage_from=_texto(fila.get("cobertura_desde")) or None,
        coverage_to=_texto(fila.get("cobertura_hasta")) or None,
        raw=dict(fila),
    ).__dict__


def leer_meta(workspace: Path, source_id: str) -> dict | None:
    ruta = ruta_meta(workspace, source_id)
    if not ruta.is_file():
        return None
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _resolver_evento(
    fila: dict,
    por_evento: dict[str, str],
    por_origen: dict[tuple[str, str], str],
) -> str:
    id_evento = _texto(fila.get("id_evento")) or _texto(fila.get("source_event_id"))
    id_origen = _texto(fila.get("id_origen")) or _texto(fila.get("origin_id"))
    if (id_evento, id_origen) in por_origen:
        return por_origen[(id_evento, id_origen)]
    return por_evento.get(id_evento, "")


def _llegada(fila: dict) -> str | None:
    base = _texto(fila.get("llegada_utc"))
    if not base:
        return None
    micros = _texto(fila.get("llegada_us"))
    if micros and micros != "0" and "." not in base and micros.isdigit():
        base = f"{base}.{int(micros):06d}"
    return base


def _escribir_jsonl(ruta: Path, registros: list[dict]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8") as salida:
        for registro in registros:
            salida.write(json.dumps(registro, ensure_ascii=False) + "\n")


def _extension_arribos(
    filas: list[dict], source_id: str, por_evento, por_origen
) -> list[dict]:
    registros = []
    for fila in filas:
        identificador = _resolver_evento(fila, por_evento, por_origen)
        arribo = ArriboCanonico(
            source_id=source_id,
            event_id=identificador,
            origin_id=_texto(fila.get("id_origen")),
            network=_texto(fila.get("red")),
            station=_texto(fila.get("estacion")),
            location=_texto(fila.get("loc")),
            channel=_texto(fila.get("cha")),
            phase=_texto(fila.get("fase")),
            pick_time=_llegada(fila),
            pick_status=_texto(fila.get("modo_pick")),
            is_used_in_solution=_boleano(fila.get("usada")),
            weight=_numero(fila.get("peso")),
            polarity=_texto(fila.get("polaridad")),
            residual=_numero(fila.get("residual_s")),
            distance_km=_numero(fila.get("distancia")),
            azimuth=_numero(fila.get("azimut")),
            snr=_numero(fila.get("snr")),
            qc=_texto(fila.get("qc_estacion")),
            picker_probability=_numero(fila.get("picker_probability")),
            pick_uncertainty=_numero(fila.get("pick_uncertainty")),
            source_event_id=_texto(fila.get("id_evento")),
            pick_id=_texto(fila.get("id_pick")),
            time_correction_s=_numero(fila.get("correccion_s")),
            pick_author=_texto(fila.get("pick_autor")),
            pick_agency=_texto(fila.get("pick_agencia")),
            pick_method=_texto(fila.get("pick_metodo")),
            station_magnitude=_numero(fila.get("mag_estacion")),
            station_magnitude_type=_texto(fila.get("tipo_mag_estacion")),
            has_station_magnitude=_texto(fila.get("tiene_magnitud")),
            station_magnitude_residual=_numero(fila.get("mag_est_residuo")),
            station_latitude=_numero(fila.get("est_lat")),
            station_longitude=_numero(fila.get("est_lon")),
            station_elevation_m=_numero(fila.get("est_elev")),
            station_place=_texto(fila.get("est_lugar")),
            station_country=_texto(fila.get("est_pais")),
            database=_texto(fila.get("base_datos")),
            raw=dict(fila),
        )
        registros.append(arribo.__dict__)
    return registros


def _extension_sin_arribos(
    filas: list[dict], source_id: str, por_evento, por_origen
) -> list[dict]:
    registros = []
    for fila in filas:
        registros.append(
            EstacionSinArribosCanonica(
                source_id=source_id,
                event_id=_resolver_evento(fila, por_evento, por_origen),
                source_event_id=_texto(fila.get("id_evento")),
                origin_id=_texto(fila.get("id_origen")),
                network=_texto(fila.get("red")),
                station=_texto(fila.get("estacion")),
                location=_texto(fila.get("loc_ref")),
                channel=_texto(fila.get("cha_ref")),
                streams=_texto(fila.get("streams_vigentes_ids")),
                stream_ids=_texto(fila.get("streams_vigentes_ids")),
                distance_km=_numero(fila.get("distancia_km")),
                station_latitude=_numero(fila.get("est_lat")),
                station_longitude=_numero(fila.get("est_lon")),
                station_elevation_m=_numero(fila.get("est_elev")),
                station_place=_texto(fila.get("est_lugar")),
                station_country=_texto(fila.get("est_pais")),
                radio_km=_numero(fila.get("radio_km")),
                activity_window=_entero(fila.get("actividad_ventana")),
                evidence=_texto(fila.get("evidencia")),
                waveform_status=_texto(fila.get("waveform_status"))
                or "NO_CONSULTADO",
                availability_source=_texto(fila.get("availability_source")),
                coverage_from=_texto(fila.get("cobertura_desde")) or None,
                coverage_to=_texto(fila.get("cobertura_hasta")) or None,
                raw=dict(fila),
            ).__dict__
        )
    return registros


UNIDADES_MOMENTO = {
    "nm": ("Nm", 1.0),
    "n-m": ("Nm", 1.0),
    "newton-metro": ("Nm", 1.0),
    "newtonmetro": ("Nm", 1.0),
    "dyn-cm": ("Nm", 1e-7),
    "dyne-cm": ("Nm", 1e-7),
    "dina-cm": ("Nm", 1e-7),
    "dyncm": ("Nm", 1e-7),
    "dynecm": ("Nm", 1e-7),
    "dinacm": ("Nm", 1e-7),
}


def _unidad_momento(valor) -> tuple[str, tuple[str, float] | None]:
    original = _texto(valor)
    limpio = (
        original.lower()
        .replace(" ", "")
        .replace("*", "")
        .replace("_", "-")
    )
    return original, UNIDADES_MOMENTO.get(limpio)


def _mw_desde_momento(momento_nm: float | None) -> float | None:
    if momento_nm is None or momento_nm <= 0:
        return None
    return (2.0 / 3.0) * (math.log10(momento_nm) - 9.1)


def _extension_tensores(
    filas: list[dict], source_id: str, por_evento, por_origen
) -> list[dict]:
    registros = []
    for posicion, fila in enumerate(filas):
        event_id = _resolver_evento(fila, por_evento, por_origen)
        origin_id = _texto(fila.get("id_origen")) or _texto(
            fila.get("origin_id")
        )
        tensor_id = _texto(fila.get("tensor_id")) or _texto(
            fila.get("id_tensor")
        )
        if not tensor_id:
            tensor_id = (
                f"{source_id}:{event_id or 'evento'}:"
                f"{origin_id or 'origen'}:{posicion}"
            )
        original_units, unidad = _unidad_momento(
            fila.get("moment_units")
            or fila.get("unidades")
            or fila.get("units")
        )
        factor = unidad[1] if unidad else None
        canonical_units = unidad[0] if unidad else ""

        def componente(nombre: str) -> float | None:
            valor = _numero(fila.get(nombre))
            if valor is None:
                return None
            return valor * factor if factor is not None else valor

        scalar_moment = componente("scalar_moment")
        momento_magnitude = _numero(fila.get("moment_magnitude"))
        if momento_magnitude is None:
            momento_magnitude = _numero(fila.get("mw"))
        if momento_magnitude is None and factor is not None:
            momento_magnitude = _mw_desde_momento(scalar_moment)
        preferido = _boleano(fila.get("is_preferred"))
        if preferido is None:
            preferido = _boleano(fila.get("preferido"))
        registros.append(
            TensorMomentoCanonico(
                source_id=source_id,
                event_id=event_id,
                origin_id=origin_id,
                tensor_id=tensor_id,
                method=_texto(fila.get("method"))
                or _texto(fila.get("metodo")),
                mechanism=_texto(fila.get("mechanism"))
                or _texto(fila.get("mecanismo")),
                strike1=_numero(fila.get("strike1")),
                dip1=_numero(fila.get("dip1")),
                rake1=_numero(fila.get("rake1")),
                strike2=_numero(fila.get("strike2")),
                dip2=_numero(fila.get("dip2")),
                rake2=_numero(fila.get("rake2")),
                m_rr=componente("m_rr"),
                m_tt=componente("m_tt"),
                m_pp=componente("m_pp"),
                m_rt=componente("m_rt"),
                m_rp=componente("m_rp"),
                m_tp=componente("m_tp"),
                scalar_moment=scalar_moment,
                moment_units=canonical_units,
                moment_units_original=original_units,
                moment_magnitude=momento_magnitude,
                is_preferred=bool(preferido),
                raw=dict(fila),
            ).__dict__
        )
    return registros


def escribir_extensiones(
    workspace: Path,
    source_id: str,
    formato: str,
    rutas: dict[str, str | Path | None],
    *,
    radio_km: float | None = None,
    generado: str | None = None,
) -> dict:
    """Canoniza las extensiones disponibles y escribe ``meta.json``.

    Una extensión ausente no invalida el trabajo: se registra como no
    disponible para que la app muestre «no evaluable» en lugar de ocultar la
    revisión completa.
    """
    eventos = leer_canonico(workspace, source_id)
    por_evento: dict[str, str] = {}
    por_origen: dict[tuple[str, str], str] = {}
    for evento in eventos:
        id_evento = _texto(evento.get("source_event_id"))
        id_origen = _texto(evento.get("origin_id"))
        if id_evento:
            por_evento.setdefault(id_evento, evento.get("event_id", ""))
        if id_evento and id_origen:
            por_origen[(id_evento, id_origen)] = evento.get("event_id", "")

    estado: dict[str, dict] = {}
    radios: list[float] = []
    for clave, nombre in EXTENSIONES.items():
        valor = rutas.get(clave)
        ruta = Path(valor) if valor else None
        if ruta is not None and not ruta.is_absolute():
            ruta = workspace / ruta
        filas = _leer_crudo(ruta) if ruta is not None else []
        if clave == "arribos":
            registros = _extension_arribos(
                filas, source_id, por_evento, por_origen
            )
        elif clave == "estaciones_sin_arribos":
            registros = _extension_sin_arribos(
                filas, source_id, por_evento, por_origen
            )
            radios = [
                numero
                for numero in (_numero(fila.get("radio_km")) for fila in filas)
                if numero is not None
            ]
        elif clave == "tensores":
            registros = _extension_tensores(
                filas, source_id, por_evento, por_origen
            )
        else:
            registros = []
        if registros:
            _escribir_jsonl(_ruta(workspace, source_id, nombre), registros)
        estado[clave] = {
            "present": bool(ruta is not None and ruta.is_file()),
            "rows": len(registros),
            "file": nombre,
        }

    if radio_km is None and radios:
        radio_km = max(radios)

    from .registry import formato as _formato

    try:
        capacidades = sorted(_formato(formato).capacidades)
    except ValueError:
        capacidades = []

    meta = {
        "schema_version": SCHEMA_VERSION,
        "source_id": source_id,
        "format": formato,
        "generated_at": generado or datetime.now(UTC).isoformat(),
        "capabilities": capacidades,
        "extensions": estado,
        "station_radius_km": radio_km,
        "quality_blocks": resumen_bloques_calidad(eventos),
    }
    ruta_meta(workspace, source_id).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta


def version() -> str:
    return SCHEMA_VERSION
