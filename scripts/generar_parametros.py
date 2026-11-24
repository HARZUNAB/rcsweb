"""Genera y valida el registro de parámetros de RCS Web.

El registro vive en ``docs/parametros.toml``. Este script:

- verifica que toda variable de entorno y todo flag de script esté registrado;
- verifica que las constantes declaradas en ``[constantes].modulos`` estén
  documentadas y que sus valores por defecto coincidan;
- detecta entradas obsoletas;
- genera ``docs/anexos/D_parametros.md`` para el manual técnico.

Uso:
    python scripts/generar_parametros.py --check
    python scripts/generar_parametros.py --write
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
import tomllib
import warnings
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TOML = RAIZ / "docs" / "parametros.toml"
ANEXO = RAIZ / "docs" / "anexos" / "D_parametros.md"
DIRS = ("app", "core", "tasks", "scripts")
IGNORAR = {"__pycache__", ".venv", "tests", "node_modules"}

SECCIONES = {
    "D.1": "Variables de entorno",
    "D.2": "Constantes de módulos",
    "D.3": "Parámetros de scripts",
    "D.4": "Parámetros por trabajo",
    "D.5": "Reglas y umbrales",
}

CAMPOS = ("nombre", "tipo", "modulo", "simbolo", "defecto", "ambito", "grupo", "seccion")
_NO_EVALUABLE = object()


class ErrorParametros(RuntimeError):
    """El registro no coincide con el código."""


def _archivos():
    for base in DIRS:
        for ruta in sorted((RAIZ / base).rglob("*.py")):
            if any(parte in IGNORAR for parte in ruta.parts):
                continue
            if ruta.resolve() == Path(__file__).resolve():
                continue
            yield ruta


def _parsear(ruta: Path) -> ast.AST | None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            return ast.parse(ruta.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return None


def _nombre_entorno(nodo: ast.AST) -> str | None:
    """Devuelve el nombre de entorno de una llamada de lectura, o None."""
    if not isinstance(nodo, ast.Call):
        return None
    func = nodo.func
    if isinstance(func, ast.Attribute):
        if func.attr != "get":
            return None
        base = func.value
        if not (
            (isinstance(base, ast.Attribute) and base.attr == "environ")
            or (isinstance(base, ast.Name) and base.id == "environ")
        ):
            return None
    elif isinstance(func, ast.Name):
        if func.id not in ("getenv", "_bool"):
            return None
    else:
        return None
    if not nodo.args:
        return None
    primero = nodo.args[0]
    if not isinstance(primero, ast.Constant) or not isinstance(
        primero.value, str
    ):
        return None
    valor = primero.value
    if not valor.isupper() or len(valor) < 3:
        return None
    return valor


def _nombre_flag(nodo: ast.AST) -> str | None:
    if not isinstance(nodo, ast.Call):
        return None
    func = nodo.func
    if not isinstance(func, ast.Attribute) or func.attr != "add_argument":
        return None
    if not nodo.args:
        return None
    primero = nodo.args[0]
    if not isinstance(primero, ast.Constant) or not isinstance(
        primero.value, str
    ):
        return None
    if not primero.value.startswith("--"):
        return None
    return primero.value


def _evaluar(nodo: ast.AST):
    try:
        return ast.literal_eval(nodo)
    except (ValueError, TypeError, SyntaxError):
        pass
    try:
        return eval(
            compile(ast.Expression(nodo), "<parametros>", "eval"),
            {"__builtins__": {}},
            {},
        )
    except Exception:  # noqa: BLE001 - expresión no evaluable
        return _NO_EVALUABLE


def _es_parametro(valor) -> bool:
    if valor is _NO_EVALUABLE:
        return False
    if valor is None:
        return True
    if isinstance(valor, bool):
        return True
    if isinstance(valor, (int, float)):
        return True
    if isinstance(valor, (tuple, list)):
        return bool(valor) and all(
            isinstance(item, (int, float, bool)) for item in valor
        )
    return False


def inventario_entorno() -> dict[str, list[tuple[Path, int]]]:
    salida: dict[str, list[tuple[Path, int]]] = defaultdict(list)
    for ruta in _archivos():
        arbol = _parsear(ruta)
        if arbol is None:
            continue
        for nodo in ast.walk(arbol):
            nombre = _nombre_entorno(nodo)
            if nombre:
                salida[nombre].append((ruta, getattr(nodo, "lineno", 0)))
    return dict(salida)


def inventario_flags() -> dict[tuple[str, str], int]:
    salida: dict[tuple[str, str], int] = {}
    for ruta in _archivos():
        arbol = _parsear(ruta)
        if arbol is None:
            continue
        relativa = str(ruta.relative_to(RAIZ))
        for nodo in ast.walk(arbol):
            flag = _nombre_flag(nodo)
            if flag:
                salida[(relativa, flag)] = getattr(nodo, "lineno", 0)
    return salida


def inventario_constantes(
    modulos: list[str],
) -> dict[tuple[str, str], tuple[object, int]]:
    salida: dict[tuple[str, str], tuple[object, int]] = {}
    for modulo in modulos:
        ruta = RAIZ / modulo
        arbol = _parsear(ruta)
        if arbol is None:
            continue
        for nodo in arbol.body:
            if not isinstance(nodo, ast.Assign) or len(nodo.targets) != 1:
                continue
            objetivo = nodo.targets[0]
            if not isinstance(objetivo, ast.Name):
                continue
            nombre = objetivo.id
            if not nombre.isupper():
                continue
            valor = _evaluar(nodo.value)
            if not _es_parametro(valor):
                continue
            salida[(modulo, nombre)] = (valor, getattr(nodo, "lineno", 0))
    return salida


def _normalizar(valor) -> str:
    texto = str(valor).strip()
    if len(texto) >= 2 and texto[0] == texto[-1] and texto[0] in "'\"":
        texto = texto[1:-1]
    return texto


def _sin_lineas(texto: str) -> str:
    """Ignora los números de línea al comparar el anexo generado."""
    return re.sub(r"(\.py):\d+", r"\1:?", texto)


def cargar() -> dict:
    if not TOML.is_file():
        raise ErrorParametros(f"No existe {TOML.relative_to(RAIZ)}.")
    with TOML.open("rb") as archivo:
        datos = tomllib.load(archivo)
    parametros = datos.get("parametros") or []
    for numero, parametro in enumerate(parametros, start=1):
        for campo in CAMPOS:
            if campo == "defecto":
                continue
            if not str(parametro.get(campo) or "").strip():
                raise ErrorParametros(
                    f"Parámetro #{numero} sin campo obligatorio: {campo}."
                )
        if parametro["tipo"] not in ("entorno", "constante", "script"):
            raise ErrorParametros(
                f"Parámetro {parametro['nombre']}: tipo inválido."
            )
    return datos


def verificar(datos: dict) -> dict[str, int]:
    parametros = datos.get("parametros") or []
    modulos = list((datos.get("constantes") or {}).get("modulos") or [])
    if not modulos:
        raise ErrorParametros("Falta [constantes].modulos en el registro.")

    entorno = inventario_entorno()
    flags = inventario_flags()
    constantes = inventario_constantes(modulos)

    doc_entorno = {
        p["nombre"] for p in parametros if p["tipo"] == "entorno"
    }
    doc_flags = {
        (p["modulo"], p["nombre"])
        for p in parametros
        if p["tipo"] == "script"
    }
    doc_constantes = {
        (p["modulo"], p["simbolo"])
        for p in parametros
        if p["tipo"] == "constante"
    }

    faltan_entorno = sorted(set(entorno) - doc_entorno)
    faltan_flags = sorted(set(flags) - doc_flags)
    faltan_constantes = sorted(
        clave
        for clave in set(constantes) - doc_constantes
        if not clave[1].startswith("_")
    )
    sobran_flags = sorted(doc_flags - set(flags))
    sobran_constantes = sorted(doc_constantes - set(constantes))

    errores = []
    if faltan_entorno:
        errores.append(
            "Variables de entorno sin documentar: "
            + ", ".join(faltan_entorno)
        )
    if faltan_flags:
        errores.append(
            "Flags sin documentar: "
            + ", ".join(f"{modulo}:{flag}" for modulo, flag in faltan_flags)
        )
    if faltan_constantes:
        errores.append(
            "Constantes sin documentar: "
            + ", ".join(
                f"{modulo}:{simbolo}"
                for modulo, simbolo in faltan_constantes
            )
        )
    if sobran_flags:
        errores.append(
            "Flags documentados que ya no existen: "
            + ", ".join(f"{modulo}:{flag}" for modulo, flag in sobran_flags)
        )
    if sobran_constantes:
        errores.append(
            "Constantes documentadas que ya no existen: "
            + ", ".join(
                f"{modulo}:{simbolo}"
                for modulo, simbolo in sobran_constantes
            )
        )

    for parametro in parametros:
        if parametro["tipo"] == "constante":
            clave = (parametro["modulo"], parametro["simbolo"])
            if clave not in constantes:
                continue
            valor = _normalizar(constantes[clave][0])
            documentado = _normalizar(parametro["defecto"])
            if valor != documentado:
                errores.append(
                    f"{parametro['modulo']}:{parametro['simbolo']} "
                    f"vale {valor} y el registro dice {documentado}."
                )
        elif parametro["tipo"] == "script":
            clave = (parametro["modulo"], parametro["nombre"])
            if clave not in flags:
                continue
            # Los defectos que vienen de una expresión se revisan a mano.
            documentado = _normalizar(parametro["defecto"])
            if documentado and "(" not in documentado:
                continue

    if errores:
        raise ErrorParametros("\n".join(errores))

    return {
        "entorno": len(doc_entorno),
        "flags": len(doc_flags),
        "constantes": len(doc_constantes),
        "constantes_codigo": len(constantes),
    }


def _linea(modulo: str, simbolo: str, tipo: str) -> str:
    ruta = RAIZ / modulo
    if not ruta.is_file():
        return f"{modulo}:?"
    patron = re.compile(
        rf'^\s*{re.escape(simbolo)}\s*=|["\']{re.escape(simbolo)}["\']'
    )
    for numero, linea in enumerate(
        ruta.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if patron.search(linea):
            return f"{modulo}:{numero}"
    return f"{modulo}:?"


def _celda(texto, defecto: str = "") -> str:
    valor = str(texto if texto not in (None, "") else defecto)
    return valor.replace("|", "\\|").replace("\n", " ").strip() or "—"


def _fila(parametro: dict) -> str:
    tipo = parametro["tipo"]
    if tipo == "script":
        script = Path(parametro["modulo"]).name
        return (
            f"| `{_celda(parametro['nombre'])}` | `{_celda(script)}` | "
            f"`{_celda(parametro['defecto'])}` | "
            f"{_celda(parametro['descripcion'])} |"
        )
    ubicacion = _linea(
        parametro["modulo"], parametro["simbolo"], parametro["tipo"]
    )
    return (
        f"| `{_celda(parametro['nombre'])}` | `{_celda(ubicacion)}` | "
        f"`{_celda(parametro['defecto'])}` | "
        f"{_celda(parametro['ambito'])} | "
        f"{_celda(parametro['descripcion'])} |"
    )


def _contenido_anexo(datos: dict, resumen: dict[str, int]) -> str:
    parametros = datos.get("parametros") or []
    por_seccion: dict[str, list[dict]] = defaultdict(list)
    for parametro in parametros:
        por_seccion[parametro["seccion"]].append(parametro)

    criterio = str((datos.get("constantes") or {}).get("criterio") or "")
    lineas = [
        "## Anexo D. Parámetros y configuración",
        "",
        "Este anexo reúne los valores que gobiernan el comportamiento de RCS "
        "Web. La fuente de verdad es `docs/parametros.toml`; las tablas se "
        "generan con `scripts/generar_parametros.py --write` y se validan en "
        "las pruebas con `--check`.",
        "",
    ]
    if criterio:
        lineas.extend([criterio, ""])
    lineas.extend(
        [
            "La columna **Módulo** muestra el archivo y la línea actual donde "
            "se define el valor. Si el código se mueve, el número se "
            "actualiza al regenerar el anexo.",
            "",
            "### D.0 Índice de parámetros",
            "",
        ]
    )
    lineas.extend(
        [
            "| Sección | Contenido | Página |",
            "|---|---|---|",
        ]
    )
    for clave in ("D.1", "D.2", "D.3", "D.4", "D.5"):
        lineas.append(
            f"| {clave} | {SECCIONES[clave]} | "
            f"[[PAGEREF:_D_{clave.split('.')[1]}]] |"
        )
    lineas.extend(
        [
            "",
            "> Las páginas se resuelven al actualizar el índice en el DOCX. "
            "En Markdown no existe paginación.",
            "",
            f"Resumen: {resumen['entorno']} variables de entorno, "
            f"{resumen['constantes']} constantes y "
            f"{resumen['flags']} parámetros de scripts.",
            "",
        ]
    )

    lineas.extend(
        [
            "### D.1 Variables de entorno",
            "",
            "Se leen al arrancar la aplicación o el servicio. Cambiarlas "
            "requiere reiniciar el contenedor correspondiente.",
            "",
        ]
    )
    for grupo, items in _agrupar(por_seccion["D.1"]):
        lineas.extend(
            [
                "",
                f"**{grupo}**",
                "",
                "| Variable | Módulo | Defecto | Ámbito | Efecto |",
                "|---|---|---|---|---|",
            ]
        )
        for parametro in items:
            lineas.append(_fila(parametro))
    lineas.append("")

    lineas.extend(
        [
            "### D.2 Constantes de módulos",
            "",
            "Son valores de código. Cambiarlos exige modificar el módulo, "
            "revisar las pruebas y regenerar la caché que dependa de ellos.",
            "",
        ]
    )
    for grupo, items in _agrupar(por_seccion["D.2"]):
        lineas.extend(
            [
                f"**{grupo}**",
                "",
                "| Constante | Módulo | Valor | Ámbito | Efecto |",
                "|---|---|---|---|---|",
            ]
        )
        for parametro in items:
            lineas.append(_fila(parametro))
        lineas.append("")

    lineas.extend(
        [
            "### D.3 Parámetros de scripts",
            "",
            "| Flag | Script | Defecto | Efecto |",
            "|---|---|---|---|",
        ]
    )
    for parametro in sorted(
        por_seccion["D.3"], key=lambda p: (p["modulo"], p["nombre"])
    ):
        lineas.append(_fila(parametro))
    lineas.extend(
        [
            "",
            "### D.4 Parámetros por trabajo",
            "",
            "En esta versión no hay parámetros editables por trabajo. Los "
            "valores de la regla son globales y la caché guarda la versión "
            "efectiva para que un cambio invalide solo lo necesario.",
            "",
            "| Parámetro | Dónde se guarda | Versión | Invalidación |",
            "|---|---|---|---|",
            "| Regla de indicios | `app/services/indicios.py` | "
            "`ESQUEMA_INDICIOS` | cambia el esquema o los umbrales |",
            "| Caché de disponibilidad | `disponibilidad.jsonl` | — | "
            "se reemplaza por evento |",
            "| Regla de señal (prevista) | `core/correlacion.py` | "
            "hash de la regla | al implementar la columna de señal |",
            "",
            "### D.5 Reglas y umbrales",
            "",
            "Los valores que definen una regla de negocio se listan también "
            "en D.2. Esta tabla los reúne para revisión rápida.",
            "",
            "| Regla | Constante | Valor | Módulo |",
            "|---|---|---|---|",
        ]
    )
    for parametro in sorted(
        (
            p
            for p in parametros
            if p["tipo"] == "constante" and p["ambito"] == "regla"
        ),
        key=lambda p: (p["grupo"], p["nombre"]),
    ):
        lineas.append(
            f"| {_celda(parametro['grupo'])} | "
            f"`{_celda(parametro['nombre'])}` | "
            f"`{_celda(parametro['defecto'])}` | "
            f"`{_celda(parametro['modulo'])}` |"
        )
    lineas.append("")

    return "\n".join(lineas).rstrip() + "\n"


def generar_anexo(datos: dict, resumen: dict[str, int]) -> Path:
    contenido = _contenido_anexo(datos, resumen)
    ANEXO.parent.mkdir(parents=True, exist_ok=True)
    ANEXO.write_text(contenido, encoding="utf-8")
    return ANEXO


def _agrupar(items: list[dict]):
    grupos: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        grupos[item["grupo"]].append(item)
    for grupo in sorted(grupos):
        yield grupo, sorted(grupos[grupo], key=lambda p: p["nombre"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Valida y genera el registro de parámetros."
    )
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument(
        "--check",
        action="store_true",
        help="Verifica que el registro cubra el código.",
    )
    grupo.add_argument(
        "--write",
        action="store_true",
        help="Genera docs/anexos/D_parametros.md.",
    )
    args = parser.parse_args()

    try:
        datos = cargar()
        resumen = verificar(datos)
        if args.write:
            destino = generar_anexo(datos, resumen)
            print(
                f"{destino.relative_to(RAIZ)}: "
                f"{resumen['entorno']} entornos, "
                f"{resumen['constantes']} constantes, "
                f"{resumen['flags']} flags"
            )
        else:
            if not ANEXO.is_file():
                raise ErrorParametros(
                    "Falta docs/anexos/D_parametros.md; ejecute --write."
                )
            esperado = _contenido_anexo(datos, resumen)
            actual = ANEXO.read_text(encoding="utf-8")
            # Los números de línea cambian con cualquier edición. La
            # verificación exige las mismas filas y descripciones, no la
            # misma línea exacta.
            if _sin_lineas(actual) != _sin_lineas(esperado):
                raise ErrorParametros(
                    "docs/anexos/D_parametros.md está desactualizado; "
                    "ejecute --write."
                )
            print(
                "Parámetros OK: "
                f"{resumen['entorno']} variables de entorno, "
                f"{resumen['constantes']} constantes, "
                f"{resumen['flags']} flags."
            )
        return 0
    except ErrorParametros as exc:
        print(f"Error de parámetros:\n{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
