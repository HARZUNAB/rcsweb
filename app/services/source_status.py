"""Estado de las fuentes directas de un trabajo.

La validación de una fuente directa, como Central, existe en el adaptador.
Este servicio la ejecuta en el alta y, si hace falta, al abrir un trabajo ya
procesado. El resultado se guarda en ``JobSource.status`` y
``JobSource.message``. Un mensaje vacío significa «validada sin observaciones»
y evita repetir la consulta.
"""

from __future__ import annotations

from ..domain.catalogs import manifest as fuentes_manifest
from ..domain.catalogs.registry import adaptador as obtener_adaptador
from ..extensions import db


def validar_fuentes_directas(job, *, solo_sin_mensaje: bool = True) -> bool:
    """Valida las fuentes directas del trabajo y guarda su estado.

    Devuelve ``True`` si cambió algún registro. No falla si una fuente no se
    puede consultar: deja el error en el mensaje de la fuente.
    """
    cambiado = False
    for source in job.sources:
        definicion = fuentes_manifest.por_id(source.kind)
        if definicion is None or definicion.requires_file:
            continue
        if solo_sin_mensaje and source.message is not None:
            continue
        adapter = obtener_adaptador(definicion.format)
        adapter.source_id = definicion.id
        try:
            resultado = adapter.validar_periodo(job)
        except Exception as exc:  # noqa: BLE001 - se informa en la fuente
            source.status = "error"
            source.message = f"No se pudo validar la fuente: {exc}"
            cambiado = True
            continue
        mensajes = list(resultado.get("errores", [])) + list(
            resultado.get("advertencias", [])
        )
        source.status = "ok" if resultado.get("ok") else "error"
        # El mensaje vacío marca la validación sin observaciones.
        source.message = "\n".join(mensajes) if mensajes else ""
        cambiado = True
    if cambiado:
        db.session.commit()
    return cambiado


__all__ = ["validar_fuentes_directas"]
