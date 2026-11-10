"""Adaptador de la base central CSN: consulta directa de solo lectura.

La fuente no recibe archivo. El adaptador consulta las tablas ``event``,
``origin`` y ``magnitude`` para el período del trabajo, escribe un CSV plano
normalizado y, si existen, los tensores del origen preferido.

No se modifica el esquema de la base central: todas las conexiones se abren en
modo de solo lectura y solo se ejecutan consultas ``SELECT``.
"""

from __future__ import annotations

import csv
import hashlib
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from flask import current_app

from .. import arribos_csv
from .. import manifest as fuentes_manifest
from ..stations import ResolutorEstaciones, azimut_grados, distancia_km
from .base import Adaptador as Base
from .base import PasoPlan

LOG = logging.getLogger(__name__)

ESTADOS = {
    "reviewed": "Revisado",
    "final": "Final",
    "confirmed": "Confirmado",
    "automatic": "Automático",
    "manual": "Manual",
}

COLUMNAS_EVENTOS = (
    "",
    "Fecha_Hora",
    "Latitud",
    "Longitud",
    "Prof.",
    "Mag.",
    "Tipo_mag.",
    "Analista",
    "Publicado",
    "Revisión",
    "id_evento",
    "id_origen",
)

COLUMNAS_TENSORES = (
    "id_evento",
    "id_origen",
    "tensor_id",
    "method",
    "mechanism",
    "strike1",
    "dip1",
    "rake1",
    "strike2",
    "dip2",
    "rake2",
    "m_rr",
    "m_tt",
    "m_pp",
    "m_rt",
    "m_rp",
    "m_tp",
    "scalar_moment",
    "moment_units",
    "is_preferred",
)

# Orígenes locales con picks. Se usan para los eventos publicados, cuyo origen
# preferido es la solución publicada y no trae las llegadas.
CONSULTA_ORIGENES_CON_PICKS = """
SELECT o.event_id,
       o.origin_id,
       o.software,
       o.author,
       o.status,
       o.origin_time,
       o.latitude,
       o.longitude,
       o.creation_time
  FROM origin o
 WHERE o.origin_time >= %s
   AND o.origin_time <= %s
   AND EXISTS (
       SELECT 1 FROM pick p WHERE p.origin_id = o.origin_id
   )
"""

CONSULTA_PICKS = """
SELECT p.origin_id,
       p.pick_id,
       p.channel,
       p.pick_time,
       p.phase,
       p.polarity,
       p.uncertainty,
       p.probability,
       p.weight,
       p.pick_status
  FROM pick p
 WHERE p.origin_id = ANY(%s)
 ORDER BY p.origin_id, p.pick_time, p.pick_id
"""


def _lotes(valores: list, tamano: int):
    for inicio in range(0, len(valores), tamano):
        yield valores[inicio : inicio + tamano]


def _elegir_origen_local(evento: dict, candidatos: list[dict]) -> dict | None:
    """Origen local que coincide con la solución preferida publicada."""
    mejores = []
    for candidato in candidatos:
        origen = candidato.get("origin_time")
        preferido = evento.get("origin_time")
        if origen is None or preferido is None:
            continue
        diferencia = abs((origen - preferido).total_seconds())
        if diferencia > 1.0:
            continue
        if abs(candidato.get("latitude", 0.0) - evento.get("latitude", 0.0)) > 0.01:
            continue
        if abs(candidato.get("longitude", 0.0) - evento.get("longitude", 0.0)) > 0.01:
            continue
        creacion = candidato.get("creation_time")
        prioridad = creacion.timestamp() if creacion is not None else 0.0
        estado = str(candidato.get("status") or "").upper()
        revisado = 1 if estado in {"REVIEWED", "FINAL", "CONFIRMED"} else 0
        mejores.append((-revisado, diferencia, -prioridad, candidato))
    if not mejores:
        return None
    return min(mejores, key=lambda item: (item[0], item[1], item[2]))[3]


def _texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


def _numero_texto(valor) -> str:
    return "" if valor is None else str(valor)


def _fecha_texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, datetime):
        return valor.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
    return _texto(valor)


def _fecha_dia_texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, datetime):
        return valor.astimezone(UTC).strftime("%d/%m/%Y")
    return _texto(valor)


def _rango_texto(rango) -> str:
    if not rango:
        return ""
    desde = rango.get("desde")
    hasta = rango.get("hasta")
    if desde is None or hasta is None:
        return ""
    return f"{_fecha_dia_texto(desde)} → {_fecha_dia_texto(hasta)}"


_TTL_DISPONIBILIDAD = 300
_CACHE_DISPONIBILIDAD: dict[tuple[str, str], tuple[float, dict]] = {}


def limpiar_cache_disponibilidad() -> None:
    """Vacía la caché del rango disponible (pruebas y cambios de conexión)."""
    _CACHE_DISPONIBILIDAD.clear()


def _estado_texto(valor) -> str:
    limpio = _texto(valor)
    return ESTADOS.get(limpio.lower(), limpio)


def _si_no(valor) -> str:
    return "Sí" if bool(valor) else "No"


def _periodo(job) -> tuple[datetime, datetime]:
    def _con_zona(valor: datetime) -> datetime:
        return valor.replace(tzinfo=UTC) if valor.tzinfo is None else valor

    inicio = getattr(job, "period_start", None)
    fin = getattr(job, "period_end", None)
    if isinstance(inicio, datetime) and isinstance(fin, datetime):
        return _con_zona(inicio), _con_zona(fin)
    inicio14 = getattr(job, "inicio14", "")
    fin14 = getattr(job, "fin14", "")
    return (
        datetime.strptime(inicio14, "%Y%m%d%H%M%S").replace(tzinfo=UTC),
        datetime.strptime(fin14, "%Y%m%d%H%M%S").replace(tzinfo=UTC),
    )


class Adaptador(Base):
    formato = "local_db"
    tipo = "db"
    soporta_disponibilidad = True
    capacidades = frozenset(
        {"eventos", "origenes", "magnitudes", "arribos", "tensores"}
    )

    def _definicion(self):
        if self.source_id:
            fuente = fuentes_manifest.por_id(self.source_id)
            if fuente is not None:
                return fuente
        for fuente in fuentes_manifest.fuentes():
            if fuente.format == self.formato:
                return fuente
        raise RuntimeError(
            "La fuente de base de datos no está declarada en el manifiesto."
        )

    def _dsn(self) -> str:
        fuente = self._definicion()
        nombre = fuente.dsn_env or f"RCS_{fuente.id.upper()}_DSN"
        return (
            os.environ.get(nombre, "").strip()
            or str(current_app.config.get(nombre, "") or "").strip()
        )

    def _clave_cache(self) -> tuple[str, str]:
        dsn = self._dsn()
        huella = hashlib.sha256(dsn.encode("utf-8")).hexdigest()[:12]
        return self._fuente_id(), huella

    def disponibilidad(self, usuario=None) -> dict | None:
        """Rango global de fechas de la base, sin filtrar por analista.

        Es informativo: no limita el período del trabajo ni la extracción de
        las demás fuentes. Se cachea unos minutos para no consultar la base en
        cada carga del formulario.
        """
        clave = self._clave_cache()
        ahora = time.monotonic()
        guardado = _CACHE_DISPONIBILIDAD.get(clave)
        if guardado is not None and ahora - guardado[0] < _TTL_DISPONIBILIDAD:
            return guardado[1]

        with self._conectar() as conexion:
            with conexion.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT min(o.origin_time), max(o.origin_time)
                      FROM event e
                      JOIN origin o ON o.origin_id = e.preferred_origin_id
                    """
                )
                desde, hasta = cursor.fetchone()
        rango = {"desde": desde, "hasta": hasta}
        _CACHE_DISPONIBILIDAD[clave] = (ahora, rango)
        return rango

    def _conectar(self):
        import psycopg

        dsn = self._dsn()
        if not dsn:
            raise RuntimeError(
                "Falta la cadena de conexión de la base central. "
                "Configure la variable de entorno declarada en el manifiesto."
            )
        conexion = psycopg.connect(dsn, connect_timeout=15)
        conexion.execute("SET default_transaction_read_only = on")
        return conexion

    def _ruta_parametros(self) -> str:
        return f"datos/{self._fuente_id()}_parametros.csv"

    def _ruta_tensores(self) -> str:
        return f"datos/{self._fuente_id()}_tensores.csv"

    def _fuente_id(self) -> str:
        if self.source_id:
            return self.source_id
        return self._definicion().id

    def pasos(self, job, eventquery: str) -> list[PasoPlan]:
        def _exportar(workspace) -> None:
            self.exportar(Path(workspace), job)

        return [
            PasoPlan(
                "consultar_central",
                "Consultar base central",
                None,
                post=_exportar,
            )
        ]

    def catalogo(self, job, referencia: str) -> str:
        return self._ruta_parametros()

    def _ruta_fases(self, job) -> str:
        return f"datos/central_{job.inicio14}_{job.fin14}_fases.csv"

    def _archivo_con_filas(self, ruta: Path) -> bool:
        if not ruta.is_file():
            return False
        try:
            with ruta.open(encoding="utf-8") as archivo:
                return sum(1 for _ in archivo) > 1
        except OSError:
            return False

    def extensiones(self, job, referencia: str, workspace=None) -> dict[str, str]:
        extensiones: dict[str, str] = {}
        if workspace is None:
            return extensiones
        raiz = Path(workspace)
        if self._archivo_con_filas(raiz / self._ruta_tensores()):
            extensiones["tensores"] = self._ruta_tensores()
        if job is not None and self._archivo_con_filas(raiz / self._ruta_fases(job)):
            extensiones["arribos"] = self._ruta_fases(job)
        return extensiones

    def exportar(self, workspace: Path, job) -> None:
        """Consulta la base y deja el CSV normalizado en el workspace."""
        inicio, fin = _periodo(job)
        eventos, tensores = self._consultar(inicio, fin)
        eventos, tensores = self._filtrar_por_usuario(job, eventos, tensores)
        try:
            arribos = self._consultar_arribos(inicio, fin, eventos)
        except Exception:  # noqa: BLE001
            LOG.exception("No se pudieron exportar los arribos de la base central.")
            arribos = []

        destino = workspace / self._ruta_parametros()
        destino.parent.mkdir(parents=True, exist_ok=True)
        with destino.open("w", encoding="utf-8", newline="") as archivo:
            escritor = csv.writer(archivo)
            escritor.writerow(COLUMNAS_EVENTOS)
            for posicion, evento in enumerate(eventos):
                escritor.writerow(
                    [
                        posicion,
                        _fecha_texto(evento.get("origin_time")),
                        _numero_texto(evento.get("latitude")),
                        _numero_texto(evento.get("longitude")),
                        _numero_texto(evento.get("depth")),
                        _numero_texto(evento.get("magnitude_value")),
                        _texto(evento.get("magnitude_type")),
                        _texto(evento.get("author")),
                        _si_no(evento.get("published")),
                        _estado_texto(evento.get("status")),
                        _texto(evento.get("event_id")),
                        _texto(evento.get("origin_id")),
                    ]
                )

        ruta_tensores = workspace / self._ruta_tensores()
        with ruta_tensores.open("w", encoding="utf-8", newline="") as archivo:
            escritor = csv.writer(archivo)
            escritor.writerow(COLUMNAS_TENSORES)
            for tensor in tensores:
                escritor.writerow(
                    [
                        _texto(tensor.get("event_id")),
                        _texto(tensor.get("origin_id")),
                        _texto(tensor.get("tensor_id")),
                        _texto(tensor.get("method")),
                        _texto(tensor.get("mechanism")),
                        _numero_texto(tensor.get("strike1")),
                        _numero_texto(tensor.get("dip1")),
                        _numero_texto(tensor.get("rake1")),
                        _numero_texto(tensor.get("strike2")),
                        _numero_texto(tensor.get("dip2")),
                        _numero_texto(tensor.get("rake2")),
                        _numero_texto(tensor.get("m_rr")),
                        _numero_texto(tensor.get("m_tt")),
                        _numero_texto(tensor.get("m_pp")),
                        _numero_texto(tensor.get("m_rt")),
                        _numero_texto(tensor.get("m_rp")),
                        _numero_texto(tensor.get("m_tp")),
                        _numero_texto(tensor.get("scalar_moment")),
                        "",
                        "Sí",
                    ]
                )

        ruta_fases = workspace / self._ruta_fases(job)
        if arribos:
            arribos_csv.escribir(ruta_fases, arribos)
        elif ruta_fases.is_file():
            ruta_fases.unlink()

    def _usuario(self, job):
        creador_id = getattr(job, "created_by_id", None)
        if not creador_id:
            return None
        from ....extensions import db
        from ....models import User  # import local para evitar ciclos

        return db.session.get(User, creador_id)

    def _filtrar_por_usuario(self, job, eventos, tensores):
        from ....services.analysts import (
            codigos_usuario,
            coincide,
            usuario_restringido,
        )

        usuario = self._usuario(job)
        if getattr(job, "created_by_id", None) and usuario is None:
            return [], []
        if usuario is None or not usuario_restringido(usuario):
            return eventos, tensores
        codigos = codigos_usuario(usuario)
        if not codigos:
            return [], []
        visibles = [
            evento
            for evento in eventos
            if any(coincide(codigo, evento.get("author") or "") for codigo in codigos)
        ]
        ids = {evento.get("event_id") for evento in visibles}
        return visibles, [
            tensor for tensor in tensores if tensor.get("event_id") in ids
        ]

    def _consultar(self, inicio: datetime, fin: datetime):
        from psycopg.rows import dict_row

        with self._conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT e.event_id,
                           e.published,
                           o.origin_id,
                           o.author,
                           o.status,
                           o.origin_time,
                           o.latitude,
                           o.longitude,
                           o.depth,
                           o.software,
                           m.magnitude_value,
                           m.magnitude_type,
                           EXISTS (
                               SELECT 1 FROM pick p
                                WHERE p.origin_id = o.origin_id
                           ) AS tiene_picks
                      FROM event e
                      JOIN origin o ON o.origin_id = e.preferred_origin_id
                      LEFT JOIN magnitude m
                             ON m.magnitude_id = e.preferred_magnitude_id
                     WHERE o.origin_time >= %s
                       AND o.origin_time <= %s
                     ORDER BY o.origin_time, e.event_id
                    """,
                    (inicio, fin),
                )
                eventos = cursor.fetchall()

                cursor.execute(
                    """
                    SELECT e.event_id,
                           t.origin_id,
                           t.tensor_id,
                           t.method,
                           t.mechanism,
                           t.strike1,
                           t.dip1,
                           t.rake1,
                           t.strike2,
                           t.dip2,
                           t.rake2,
                           t.m_rr,
                           t.m_tt,
                           t.m_pp,
                           t.m_rt,
                           t.m_rp,
                           t.m_tp,
                           t.scalar_moment
                      FROM tensor t
                      JOIN event e ON e.preferred_origin_id = t.origin_id
                      JOIN origin o ON o.origin_id = t.origin_id
                     WHERE o.origin_time >= %s
                       AND o.origin_time <= %s
                     ORDER BY o.origin_time, t.tensor_id
                    """,
                    (inicio, fin),
                )
                tensores = cursor.fetchall()
        return eventos, tensores

    def _consultar_arribos(
        self, inicio: datetime, fin: datetime, eventos: list[dict]
    ) -> list[dict]:
        """Arribos del origen que corresponde a cada evento.

        Si el origen preferido trae picks, se usa directamente (evento no
        publicado). Si no, se busca el origen local que coincide con la
        solución publicada por tiempo y posición.
        """
        if not eventos:
            return []
        from psycopg.rows import dict_row

        with self._conectar() as conexion:
            with conexion.cursor(row_factory=dict_row) as cursor:
                necesita_locales = any(
                    not evento.get("tiene_picks") for evento in eventos
                )
                locales: list[dict] = []
                if necesita_locales:
                    cursor.execute(
                        CONSULTA_ORIGENES_CON_PICKS,
                        (
                            inicio - timedelta(seconds=5),
                            fin + timedelta(seconds=5),
                        ),
                    )
                    locales = cursor.fetchall()

                por_evento: dict[str, list[dict]] = {}
                for origen in locales:
                    por_evento.setdefault(origen["event_id"], []).append(origen)

                seleccionados: list[dict] = []
                for evento in eventos:
                    if evento.get("tiene_picks"):
                        seleccionados.append(
                            {
                                "event_id": evento.get("event_id"),
                                "origin_id": evento.get("origin_id"),
                                "software": evento.get("software") or "",
                                "author": evento.get("author") or "",
                                "origin_time": evento.get("origin_time"),
                                "latitude": evento.get("latitude"),
                                "longitude": evento.get("longitude"),
                            }
                        )
                        continue
                    elegido = _elegir_origen_local(
                        evento, por_evento.get(evento.get("event_id"), [])
                    )
                    if elegido is not None:
                        seleccionados.append(elegido)

                if not seleccionados:
                    return []

                por_origen = {
                    origen["origin_id"]: origen for origen in seleccionados
                }
                picks: list[dict] = []
                for lote in _lotes(list(por_origen), 20000):
                    cursor.execute(CONSULTA_PICKS, (lote,))
                    picks.extend(cursor.fetchall())

        fuente = self._definicion()
        resolutor = ResolutorEstaciones(getattr(fuente, "stations", {}))
        filas: list[dict] = []
        for pick in picks:
            origen = por_origen.get(pick.get("origin_id"))
            if origen is None:
                continue
            red, estacion, loc, cha = arribos_csv.parsear_canal(pick.get("channel"))
            est = resolutor.resolver(
                origen.get("software") or "",
                estacion,
                network=red,
                lat_evento=origen.get("latitude"),
                lon_evento=origen.get("longitude"),
                instante=pick.get("pick_time"),
            )
            llegada_utc, llegada_us = arribos_csv.formatear_pick(pick.get("pick_time"))
            distancia = None
            azimut = None
            if est is not None:
                distancia = distancia_km(
                    origen.get("latitude"),
                    origen.get("longitude"),
                    est.latitude,
                    est.longitude,
                )
                azimut = azimut_grados(
                    origen.get("latitude"),
                    origen.get("longitude"),
                    est.latitude,
                    est.longitude,
                )
            filas.append(
                {
                    "id_evento": origen.get("event_id") or "",
                    "id_origen": pick.get("origin_id") or "",
                    "id_pick": pick.get("pick_id") or "",
                    "red": red,
                    "estacion": estacion,
                    "loc": loc,
                    "cha": cha,
                    "fase": pick.get("phase") or "",
                    "llegada_utc": llegada_utc,
                    "llegada_us": llegada_us,
                    "azimut": azimut if azimut is not None else "",
                    "distancia": distancia if distancia is not None else "",
                    "usada": "True",
                    "peso": (
                        pick.get("weight")
                        if pick.get("weight") is not None
                        else ""
                    ),
                    "polaridad": pick.get("polarity") or "",
                    "modo_pick": pick.get("pick_status") or "",
                    "pick_autor": origen.get("author") or "",
                    "tiene_magnitud": "No",
                    "est_lat": est.latitude if est else "",
                    "est_lon": est.longitude if est else "",
                    "est_elev": (
                        est.elevation_m
                        if est and est.elevation_m is not None
                        else ""
                    ),
                    "est_lugar": est.place if est else "",
                    "est_pais": est.country if est else "",
                    "base_datos": origen.get("software") or "",
                    "est_lista": est.source_file if est else "",
                    "est_vigencia": est.time_basis if est else "",
                    "software": origen.get("software") or "",
                    "origen_local": origen.get("origin_id") or "",
                }
            )
        return filas

    def validar_periodo(self, job, rango=None) -> dict:
        """Comprueba conexión y eventos para el período.

        La ausencia de eventos es una advertencia: el trabajo puede seguir con
        las otras fuentes. El alta decide si esa advertencia se convierte en
        error cuando Central es la única fuente local.
        """
        resultado = {
            "codigo": self._fuente_id(),
            "ok": False,
            "errores": [],
            "advertencias": [],
            "eventos": 0,
            "desde": None,
            "hasta": None,
        }
        inicio, fin = _periodo(job)
        texto_rango = _rango_texto(rango)
        from ....services.analysts import (
            codigos_usuario,
            coincide,
            usuario_restringido,
        )

        usuario = self._usuario(job)
        if getattr(job, "created_by_id", None) and usuario is None:
            resultado["errores"].append(
                "No se encontró el usuario creador del trabajo."
            )
            return resultado
        codigos = (
            codigos_usuario(usuario)
            if usuario is not None and usuario_restringido(usuario)
            else None
        )
        try:
            with self._conectar() as conexion:
                with conexion.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT o.author, o.origin_time
                          FROM event e
                          JOIN origin o ON o.origin_id = e.preferred_origin_id
                         WHERE o.origin_time >= %s
                           AND o.origin_time <= %s
                        """,
                        (inicio, fin),
                    )
                    filas = cursor.fetchall()
        except Exception as exc:  # noqa: BLE001 - se informa al usuario
            resultado["errores"].append(
                f"No se pudo consultar la base central: {exc}"
            )
            return resultado

        if codigos is not None:
            filas = [
                fila
                for fila in filas
                if any(coincide(codigo, fila[0] or "") for codigo in codigos)
            ]
        instantes = [fila[1] for fila in filas if fila[1] is not None]
        resultado["eventos"] = len(instantes)
        resultado["desde"] = (
            _fecha_texto(min(instantes)) if instantes else None
        )
        resultado["hasta"] = (
            _fecha_texto(max(instantes)) if instantes else None
        )
        if not resultado["eventos"]:
            if codigos is not None and not codigos:
                mensaje = (
                    "El usuario no tiene código de analista configurado; "
                    "la fuente Central no aportará eventos."
                )
            elif codigos is not None:
                mensaje = (
                    "La base central no tiene eventos propios en el período "
                    "seleccionado."
                )
            else:
                mensaje = (
                    "La base central no tiene eventos en el período "
                    "seleccionado."
                )
            if texto_rango:
                mensaje += f" Rango disponible en la base: {texto_rango}."
            resultado["advertencias"].append(mensaje)
            resultado["ok"] = True
            return resultado
        resultado["ok"] = True
        return resultado
