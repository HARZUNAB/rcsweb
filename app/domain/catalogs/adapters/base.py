"""Interfaz común de los adaptadores de catálogo."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class PasoPlan:
    clave: str
    titulo: str
    script: str | None
    args: list[str] = field(default_factory=list)
    verificar: Callable | None = None
    post: Callable | None = None
    condicion: Callable | None = None


class Adaptador:
    """Contrato que implementa cada formato.

    El adaptador es el único lugar que conoce los nombres de archivo, scripts y
    claves que espera el core. La aplicación solo usa ``id`` y ``label`` del
    manifiesto.
    """

    formato: str = ""
    tipo: str = ""  # reference | select | export | db
    prefijo: str = ""
    prefijo_repetidos: str = ""
    source_id: str = ""
    # Indica si el adaptador puede informar un rango de fechas disponible.
    soporta_disponibilidad: bool = False
    # Etiqueta genérica que usa repetidos.py cuando hay una sola fuente local
    # que no es un select.out. Es un detalle del core, no un nombre de fuente.
    prefijo_repetidos_core: str = "seisan"
    capacidades: frozenset[str] = frozenset()
    # Clave de color que espera el renderizador del core, si difiere del label.
    render_fuente: str = ""

    def pasos(self, job, referencia: str) -> list[PasoPlan]:
        raise NotImplementedError

    def catalogo(self, job, referencia: str) -> str:
        """Ruta relativa del CSV plano normalizado de esta fuente."""
        raise NotImplementedError

    def extensiones(self, job, referencia: str, workspace=None) -> dict[str, str]:
        """Archivos adicionales junto a la entrada, por clave canónica.

        Las claves son ``arribos`` y ``estaciones_sin_arribos``. Las rutas son
        relativas al workspace del trabajo. Una fuente que no aporta
        estaciones devuelve un diccionario vacío.
        """
        return {}

    def disponibilidad(self, usuario=None) -> dict | None:
        """Rango de fechas disponible en la fuente, si se puede consultar.

        Las fuentes que reciben archivo no lo saben hasta la carga. Las fuentes
        directas, como Central, lo implementan. El rango es informativo: no
        limita el período del trabajo.
        """
        return None

    def validar_periodo(self, job, rango=None) -> dict:
        """Validación de una fuente sin archivo, antes de crear el trabajo."""
        return {
            "codigo": self.source_id or self.formato,
            "ok": False,
            "errores": [
                "La fuente no implementa la validación por período."
            ],
            "advertencias": [],
            "eventos": 0,
            "desde": None,
            "hasta": None,
        }

    def prefijo_salida(self, source_id: str) -> str:
        return self.prefijo or f"{source_id}_"

    def archivo_no_publicados(self, source_id: str) -> str:
        return f"no_pub_desde_2_5_{self.prefijo_salida(source_id)}estricto.csv"

    def archivo_no_actualizados(self, source_id: str) -> str:
        prefijo = self.prefijo or f"{source_id}_"
        return f"no_act_{prefijo}estricto.txt"

    def archivo_repetidos(self, source_id: str, sufijo: str) -> str:
        prefijo = self.prefijo_repetidos or source_id
        return f"rep_{prefijo}_{sufijo}.txt"

    def archivo_repetidos_final(self, source_id: str, sufijo: str) -> str:
        return f"rep_{source_id}_{sufijo}.txt"

    def archivo_atribucion(self, source_id: str) -> str:
        return f"atribucion_{source_id}.csv"
