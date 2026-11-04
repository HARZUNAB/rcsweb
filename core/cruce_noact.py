#!/usr/bin/env python3
"""
cruce_noact.py
==============
Clasifica los eventos de «No actualizados» según qué fuente parece haber
publicado y cuánta prioridad tiene revisarlos.

Las filas de no actualizados ya están confirmadas como publicadas: el cruce con
eventquery existe. Lo que no se sabe es si el catálogo público terminó usando
la solución de esta fuente o la de la otra. La columna «Referencia» de
eventquery es solo una descripción geográfica, así que la respuesta se infiere
comparando las dos atribuciones y se presenta siempre como probabilidad.

Reglas:

    Esta fuente       Alta   solo esta fuente tiene candidata, o está más cerca
    Compartida        Media  ambas fuentes están igual de cerca
    Otra fuente       Baja   la otra fuente está claramente más cerca
    Duplicado público Alta   eventquery repite el mismo sismo
    No evaluable      —      falta o está vencida la otra atribución

La detección de duplicados usa la misma ventana estricta que repetidos.py:
3 s y 1°. No modifica los CSV de atribución; solo agrega campos a las filas que
ya están en memoria.
"""

import csv
import datetime
import os

import comparacion
import rutas

VENTANA_DUPLICADO_SEG = 3.0
TOL_DUPLICADO_GRADOS = 1.0

# Diferencia mínima para considerar que una fuente está «claramente» más cerca.
DIF_DIST_KM = 0.5
DIF_DT_SEG = 0.5

ETIQUETA_FUENTE = {"seisan": "Seisan", "seiscomp": "SeisComp"}

FUENTES = {
    "seisan": {
        "otra": "seiscomp",
        "etiqueta_otra": "SeisComp",
        "catalogo_otra": "seiscomp_parametros.csv",
    },
    "seiscomp": {
        "otra": "seisan",
        "etiqueta_otra": "Seisan",
        "catalogo_otra": "salida_collect.csv",
    },
}

AYUDA_REVISION_NO_ACTUALIZADOS = (
    "Clasificación de No actualizados\n\n"
    "Publicación probable | Revisión | Regla\n"
    "Esta fuente          | Alta     | Solo esta fuente o la más cercana.\n"
    "Compartida           | Media    | Ambas, sin diferencia clara.\n"
    "Otra fuente          | Baja     | La otra fuente está más cerca.\n"
    "Duplicado público    | Alta     | eventquery repite el mismo sismo.\n"
    "No evaluable         | —        | Falta o venció la otra atribución.\n\n"
    "Alta = revisar primero."
)

CAMPO_PUBLICACION = "publicacion_probable"
CAMPO_REVISION = "revision"
CAMPO_MOTIVO = "revision_motivo"
CAMPO_ORDEN = "revision_orden"

_ORDEN_REVISION = {"Alta": 1, "Media": 2, "Baja": 3, "—": 4}


def _instante(texto):
    """Fecha/hora como datetime, o None si no se puede leer."""
    if texto is None:
        return None
    limpio = " ".join(str(texto).strip().split())
    if len(limpio) >= 2 and limpio[-2:] == "60":
        limpio = limpio[:-2] + "59"
    for formato in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S.%f",
                    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.datetime.strptime(limpio, formato)
        except ValueError:
            continue
    for formato in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.datetime.strptime(limpio[:19], formato)
        except ValueError:
            continue
    return None


def _numero(texto):
    return comparacion.a_numero(texto)


def _clave(fila, prefijo):
    """Clave (instante, lat, lon) de la solución local o publicada."""
    instante = _instante(fila.get("fecha_%s" % prefijo))
    lat = _numero(fila.get("lat_%s" % prefijo))
    lon = _numero(fila.get("lon_%s" % prefijo))
    if instante is None or lat is None or lon is None:
        return None
    return (instante, round(lat, 3), round(lon, 3))


def _clave_publicado(fila):
    return _clave(fila, "eventquery")


def _clave_local(fila):
    return _clave(fila, "local")


def _mismo_publicado(a, b):
    """True si dos claves de eventquery caen en la ventana estricta."""
    dt = abs((a[0] - b[0]).total_seconds())
    return (dt <= VENTANA_DUPLICADO_SEG
            and abs(a[1] - b[1]) <= TOL_DUPLICADO_GRADOS
            and abs(a[2] - b[2]) <= TOL_DUPLICADO_GRADOS)


def _clusters_publicados(filas):
    """
    Agrupa las claves de eventquery de UNA atribución que parecen el mismo
    sismo. Devuelve {clave: (conjunto_de_claves, tamaño)}.

    El agrupado se hace por fuente a propósito: la misma fila de eventquery
    puede aparecer en las dos atribuciones y no es un duplicado. Un duplicado
    real se ve como dos claves distintas dentro de una misma atribución.
    """
    claves = []
    vistos = set()
    for fila in filas:
        clave = _clave_publicado(fila)
        if clave is not None and clave not in vistos:
            vistos.add(clave)
            claves.append(clave)

    # Se ordena por instante para recorrer solo la ventana de duplicado. Sin
    # esto, comparar todos los pares se vuelve O(n²) y con catálogos grandes
    # bloquea el listado durante decenas de segundos.
    claves.sort(key=lambda clave: clave[0])
    padre = list(range(len(claves)))

    def _raiz(i):
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i

    for i, clave_i in enumerate(claves):
        for j in range(i + 1, len(claves)):
            clave_j = claves[j]
            if ((clave_j[0] - clave_i[0]).total_seconds()
                    > VENTANA_DUPLICADO_SEG):
                break
            if _mismo_publicado(clave_i, clave_j):
                ri, rj = _raiz(i), _raiz(j)
                if ri != rj:
                    padre[rj] = ri

    grupos = {}
    for i, clave in enumerate(claves):
        grupos.setdefault(_raiz(i), set()).add(clave)
    resultado = {}
    for grupo in grupos.values():
        for clave in grupo:
            resultado[clave] = (frozenset(grupo), len(grupo))
    return resultado


def _puntaje(fila):
    """Tupla comparable: menos parámetros distintos, luego distancia y Δt."""
    distintos = len(comparacion.parametros_discrepantes(
        fila.get("lat_eventquery", ""), fila.get("lon_eventquery", ""),
        fila.get("prof_eventquery", ""), fila.get("mag_eventquery", ""),
        fila.get("lat_local", ""), fila.get("lon_local", ""),
        fila.get("prof_local", ""), fila.get("mag_local", "")))
    distancia = _numero(fila.get("dist_km"))
    if distancia is None:
        distancia = comparacion.distancia_km(
            fila.get("lat_eventquery"), fila.get("lon_eventquery"),
            fila.get("lat_local"), fila.get("lon_local"))
    dt = _numero(fila.get("dt_seg"))
    return (distintos,
            float("inf") if distancia is None else distancia,
            float("inf") if dt is None else abs(dt))


def _diferencia_clara(a, b, tolerancia):
    """True si dos valores difieren lo suficiente para decidir."""
    if a == b:
        return False
    if a == float("inf") or b == float("inf"):
        return True
    return abs(a - b) >= tolerancia


def _comparar(propia, otra):
    """
    -1 si la solución propia está más cerca, 1 si lo está la otra y 0 si hay
    empate. El orden de los criterios es el mismo que documenta la ayuda.
    """
    if propia[0] != otra[0]:
        return -1 if propia[0] < otra[0] else 1
    if _diferencia_clara(propia[1], otra[1], DIF_DIST_KM):
        return -1 if propia[1] < otra[1] else 1
    if _diferencia_clara(propia[2], otra[2], DIF_DT_SEG):
        return -1 if propia[2] < otra[2] else 1
    return 0


def _resultado(publicacion, revision, motivo):
    return {
        CAMPO_PUBLICACION: publicacion,
        CAMPO_REVISION: revision,
        CAMPO_MOTIVO: motivo,
        CAMPO_ORDEN: _ORDEN_REVISION.get(revision, 9),
    }


def _clasificar(tamano_duplicado, motivo, propias, otras, etiqueta_otra,
                puntaje=_puntaje):
    if tamano_duplicado > 1:
        return _resultado("Duplicado público", "Alta",
                          "eventquery repite el mismo sismo")
    if motivo:
        return _resultado("No evaluable", "—", motivo)
    if not propias:
        return _resultado("No evaluable", "—",
                          "sin candidato de esta fuente para el publicado")
    if not otras:
        return _resultado("Esta fuente", "Alta",
                          "sin candidato de %s" % etiqueta_otra)

    mejor_propia = min(propias, key=puntaje)
    mejor_otra = min(otras, key=puntaje)
    comparacion_fuentes = _comparar(puntaje(mejor_propia),
                                    puntaje(mejor_otra))
    if comparacion_fuentes < 0:
        return _resultado("Esta fuente", "Alta", "esta fuente está más cerca")
    if comparacion_fuentes > 0:
        return _resultado("Otra fuente", "Baja",
                          "%s está más cerca" % etiqueta_otra)
    return _resultado("Compartida", "Media",
                      "ambas fuentes están igual de cerca")


def _indice_atribucion(filas, con_local):
    """
    Indexa las filas crudas por clave publicada, una sola vez.

    'con_local' evita parsear la clave local de la otra fuente, que no se usa
    para clasificar. Cada entrada guarda la posición original para conservar el
    orden de las candidatas y, con él, los desempates.
    """
    indice = {}
    for posicion, fila in enumerate(filas):
        clave_publicada = _clave_publicado(fila)
        if clave_publicada is None:
            continue
        clave_local = _clave_local(fila) if con_local else None
        indice.setdefault(clave_publicada, []).append(
            (posicion, clave_local, fila))
    return indice


def _combinar_ordenadas(listas):
    """Une listas ya ordenadas por posición y conserva el orden original."""
    if len(listas) == 1:
        return listas[0]
    return sorted(
        (item for lista in listas for item in lista),
        key=lambda item: item[0])


def anotar(filas, filas_propias, filas_otras, fuente, motivo=None):
    """
    Agrega la clasificación a las filas de no actualizados y devuelve el total
    por revisión. 'filas_propias' y 'filas_otras' son las atribuciones crudas:
    hacen falta para ver candidatas alternativas y duplicados que el listado ya
    agrupó.

    Las claves se parsean una sola vez y las candidatas se buscan por índice.
    Antes se recorría la atribución completa por cada evento, lo que dominaba
    el tiempo de apertura del listado.
    """
    etiqueta = ETIQUETA_FUENTE.get(fuente, fuente)
    etiqueta_otra = FUENTES.get(fuente, {}).get(
        "etiqueta_otra", "la otra fuente")
    clusters = {}
    for filas_fuente in (filas_propias, filas_otras):
        for clave, (grupo, tamano) in _clusters_publicados(
                filas_fuente).items():
            previo = clusters.get(clave)
            if previo is None:
                clusters[clave] = (grupo, tamano)
            else:
                union = previo[0] | grupo
                clusters[clave] = (frozenset(union),
                                   max(previo[1], tamano, len(union)))

    propias_idx = _indice_atribucion(filas_propias, con_local=True)
    otras_idx = _indice_atribucion(filas_otras, con_local=False)
    candidatas = {}

    def _candidatas(claves):
        preparadas = candidatas.get(claves)
        if preparadas is not None:
            return preparadas
        propias_items = _combinar_ordenadas(
            [propias_idx.get(clave, ()) for clave in claves])
        propias = [item[2] for item in propias_items]
        propias_por_local = {}
        for _posicion, clave_local, fila in propias_items:
            propias_por_local.setdefault(clave_local, []).append(fila)
        otras = [item[2] for item in _combinar_ordenadas(
            [otras_idx.get(clave, ()) for clave in claves])]
        preparadas = (propias, propias_por_local, otras)
        candidatas[claves] = preparadas
        return preparadas

    puntajes = {}

    def _puntaje_calculado(fila):
        clave = id(fila)
        valor = puntajes.get(clave)
        if valor is None:
            valor = _puntaje(fila)
            puntajes[clave] = valor
        return valor

    conteo = {clave: 0 for clave in _ORDEN_REVISION}

    for fila in filas:
        clave_publicada = _clave_publicado(fila)
        if clave_publicada is None:
            fila.update(_resultado("No evaluable", "—",
                                   "sin evento publicado asociado"))
            conteo["—"] += 1
            continue

        grupo, tamano = clusters.get(clave_publicada, (frozenset(), 1))
        claves = grupo or frozenset((clave_publicada,))
        propia_local = _clave_local(fila)
        propias, propias_por_local, otras = _candidatas(claves)
        # Se prefiere la candidata del mismo evento local; si no hay, se usan
        # todas las de la fuente para ese publicado, como antes.
        propias = propias_por_local.get(propia_local) or propias

        fila.update(_clasificar(tamano, motivo, propias, otras,
                                etiqueta_otra or etiqueta,
                                puntaje=_puntaje_calculado))
        conteo[fila[CAMPO_REVISION]] = conteo.get(
            fila[CAMPO_REVISION], 0) + 1
    return conteo


def _leer_atribucion(ruta):
    with open(ruta, encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo))


def _vigente(ruta_atribucion, ruta_catalogo):
    try:
        return (os.path.getmtime(ruta_atribucion)
                >= os.path.getmtime(ruta_catalogo))
    except OSError:
        return False


def cargar_otra(cwd, fuente):
    """
    Lee la atribución de la otra fuente y dice si se puede evaluar.

    Devuelve (filas, motivo). Si falta la atribución, falta el catálogo de la
    otra fuente o la atribución es más vieja que ese catálogo, devuelve una
    lista vacía y el motivo para mostrarlo como «No evaluable».
    """
    info = FUENTES.get(fuente)
    if info is None:
        return [], "fuente sin atribución de comparación"
    ruta_atribucion = os.path.join(
        cwd, "datos", "atribucion_%s.csv" % info["otra"])
    ruta_catalogo = os.path.join(cwd, "datos", info["catalogo_otra"])
    if not os.path.isfile(ruta_atribucion):
        return [], "falta la atribución de %s" % info["etiqueta_otra"]
    if not rutas.csv_tiene_filas(ruta_catalogo):
        return [], "sin datos de %s en la ventana" % info["etiqueta_otra"]
    if not _vigente(ruta_atribucion, ruta_catalogo):
        return [], "atribución de %s desactualizada" % info["etiqueta_otra"]
    try:
        return _leer_atribucion(ruta_atribucion), None
    except OSError:
        return [], "no se pudo leer la atribución de %s" % info["etiqueta_otra"]
