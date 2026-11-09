"""Adaptador de la base central CSN: consulta directa de solo lectura.

La fuente no recibe archivo. El adaptador consulta las tablas ``event``,
``origin`` y ``magnitude`` para el período del trabajo, escribe un CSV plano
normalizado y, si existen, los tensores del origen preferido.

No se modifica el esquema de la base central: todas las conexiones se abren en
modo de solo lectura y solo se ejecutan consultas ``SELECT``.
"""

from __future__ import annotations

import csv
import os
from datetime import UTC, datetime
from pathlib import Path

from flask import current_app

from .. import manifest as fuentes_manifest
from .base import Adaptador as Base
from .base import PasoPlan

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
    capacidades = frozenset(
        {"eventos", "origenes", "magnitudes", "tensores"}
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

    def extensiones(self, job, referencia: str, workspace=None) -> dict[str, str]:
        ruta = Path(workspace) / self._ruta_tensores() if workspace else None
        if ruta is not None:
            if not ruta.is_file():
                return {}
            with ruta.open(encoding="utf-8", newline="") as archivo:
                if sum(1 for _ in archivo) <= 1:
                    return {}
        return {"tensores": self._ruta_tensores()}

    def exportar(self, workspace: Path, job) -> None:
        """Consulta la base y deja el CSV normalizado en el workspace."""
        inicio, fin = _periodo(job)
        eventos, tensores = self._consultar(inicio, fin)
        eventos, tensores = self._filtrar_por_usuario(job, eventos, tensores)

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
                           m.magnitude_value,
                           m.magnitude_type
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

    def validar_periodo(self, job) -> dict:
        """Comprueba conexión y existencia de eventos para el período."""
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
        if codigos is not None and not codigos:
            resultado["errores"].append(
                "El usuario no tiene código de analista configurado."
            )
            return resultado
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
            if codigos is not None:
                resultado["errores"].append(
                    "La base central no tiene eventos propios en el período "
                    "seleccionado."
                )
            else:
                resultado["errores"].append(
                    "La base central no tiene eventos en el período seleccionado."
                )
            return resultado
        resultado["ok"] = True
        return resultado
