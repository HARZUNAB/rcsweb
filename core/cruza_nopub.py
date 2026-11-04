#!/usr/bin/env python3
"""
cruza_nopub.py
==============
Completa los listados de «No publicados» con la información de la otra fuente.

Un evento puede no estar publicado según Seisan y, al mismo tiempo, ser el
mismo sismo que SeisComp sí publicó: las dos fuentes entregan su localización,
pero el catálogo público terminó usando una de las dos. Este script no elimina
ni reclasifica nada; solo agrega columnas al final de los CSV de no publicados
para que el listado y los paneles puedan avisar esa situación.

La búsqueda tiene dos ventanas:

    confirmación : |Δt| <= 6 s   y |Δlat|, |Δlon| <= 0.5°
    revisión     : |Δt| <= 120 s y |Δlat|, |Δlon| <= 2.0°

La confirmación exige una única solución candidata de la otra fuente. Si hay
varias, el caso es ambiguo y no se afirma que esté publicado. La ventana de
revisión sirve para dejar a la vista casos cercanos que requieren revisión
manual, sin marcarlos como publicados.

Las columnas agregadas son:

    Publicado_en   : Seisan / SeisComp, o vacío si no hay confirmación
    Estado         : Publicado en..., Ambiguo: N candidatos en..., Candidato
                     en... o Sin coincidencia
    Dt_otra_seg    : diferencia de hora con el candidato elegido
    Dist_otra_km   : distancia con el candidato elegido
    Analista_otra  : analista de la solución de la otra fuente

La atribución de la otra fuente tiene que ser vigente (igual o más nueva que su
catálogo local). Si no lo es, no se usa: es preferible dejar las columnas sin
candidatos antes que marcar un evento con un cruce de una corrida anterior.

Uso:
    python3 cruza_nopub.py
"""

import csv
import datetime
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import comparacion
import prog
import rutas

# Confirmación: mismos valores que la comparación entre fuentes ya usada en el
# proyecto, con el espacio ampliado a 0.5° porque hay pares reales que difieren
# hasta 0.411° en longitud.
VENTANA_SEG = 6.0
TOL_GRADOS = 0.5

# Revisión: no confirma nada, solo deja a la vista casos cercanos para mirarlos
# a mano. En zonas con varios eventos seguidos suele haber más de un candidato.
VENTANA_REVISION_SEG = 120.0
TOL_REVISION_GRADOS = 2.0

COLUMNAS_NUEVAS = ("Publicado_en", "Estado", "Dt_otra_seg", "Dist_otra_km",
                   "Analista_otra")

# Para cada listado de no publicados: de qué fuente es, contra qué atribución
# de la otra fuente se cruza y cuál es el catálogo local de esa otra fuente
# (para exigir que la atribución esté vigente).
FUENTES = (
    {
        "no_pub": "no_pub_desde_2_5_estricto.csv",
        "etiqueta": "Seisan",
        "otra": "SeisComp",
        "atribucion": "atribucion_seiscomp.csv",
        "catalogo_otra": "seiscomp_parametros.csv",
        "informe": "no_act_seiscomp_estricto.txt",
    },
    {
        "no_pub": "no_pub_desde_2_5_seiscomp_estricto.csv",
        "etiqueta": "SeisComp",
        "otra": "Seisan",
        "atribucion": "atribucion_seisan.csv",
        "catalogo_otra": "salida_collect.csv",
        "informe": "no_act_estricto.txt",
    },
)


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
    # Algunas fuentes agregan texto después de los segundos; si el formato
    # completo no sirvió, se intenta con los primeros 19 caracteres.
    for formato in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.datetime.strptime(limpio[:19], formato)
        except ValueError:
            continue
    return None


def _numero(texto):
    return comparacion.a_numero(texto)


def preparar_candidatos(filas):
    """
    Normaliza las filas de atribucion_<fuente>.csv a una lista de soluciones.

    Deduplica por solución local: el mismo evento local puede aparecer en más
    de una fila si cruzó con más de un publicado, pero para contar candidatos
    nos interesa la solución, no cada cruce.
    """
    candidatos = []
    vistos = set()
    for fila in filas:
        instante = _instante(fila.get("fecha_local"))
        latitud = _numero(fila.get("lat_local"))
        longitud = _numero(fila.get("lon_local"))
        if instante is None or latitud is None or longitud is None:
            continue
        clave = (instante, round(latitud, 3), round(longitud, 3))
        if clave in vistos:
            continue
        vistos.add(clave)
        candidatos.append({
            "instante": instante,
            "lat": latitud,
            "lon": longitud,
            "analista": str(fila.get("analista", "") or "").strip(),
        })
    return candidatos


def _candidatos_en_ventana(evento, candidatos, ventana_seg, tol_grados):
    """Candidatos dentro de la ventana, ordenados por Δt y luego distancia."""
    instante = _instante(evento.get("Fecha_Hora"))
    latitud = _numero(evento.get("Latitud"))
    longitud = _numero(evento.get("Longitud"))
    if instante is None or latitud is None or longitud is None:
        return []

    encontrados = []
    for candidato in candidatos:
        dt_seg = abs((candidato["instante"] - instante).total_seconds())
        if dt_seg > ventana_seg:
            continue
        if (abs(candidato["lat"] - latitud) > tol_grados
                or abs(candidato["lon"] - longitud) > tol_grados):
            continue
        distancia = comparacion.distancia_km(
            latitud, longitud, candidato["lat"], candidato["lon"])
        encontrados.append({
            "dt_seg": dt_seg,
            "dist_km": distancia,
            "analista": candidato["analista"],
        })
    encontrados.sort(key=lambda c: (
        c["dt_seg"],
        c["dist_km"] if c["dist_km"] is not None else float("inf")))
    return encontrados


def _diagnostico(candidato):
    """Las tres columnas de diagnóstico de un candidato, ya formateadas."""
    if candidato is None:
        return {"dt_seg": "", "dist_km": "", "analista": ""}
    return {
        "dt_seg": round(candidato["dt_seg"], 1),
        "dist_km": ("" if candidato["dist_km"] is None
                    else round(candidato["dist_km"], 1)),
        "analista": candidato["analista"],
    }


def evaluar_evento(evento, candidatos, etiqueta_otra):
    """
    Decide el estado de un no publicado frente a las soluciones de la otra
    fuente.

    Devuelve un dict con Publicado_en, Estado y el diagnóstico del candidato
    elegido. 'candidatos' viene de preparar_candidatos().
    """
    confirmados = _candidatos_en_ventana(
        evento, candidatos, VENTANA_SEG, TOL_GRADOS)
    revision = _candidatos_en_ventana(
        evento, candidatos, VENTANA_REVISION_SEG, TOL_REVISION_GRADOS)

    if len(confirmados) == 1:
        elegido = confirmados[0]
        resultado = {
            "publicado_en": etiqueta_otra,
            "estado": "Publicado en %s" % etiqueta_otra,
        }
    elif len(confirmados) > 1:
        elegido = confirmados[0]
        resultado = {
            "publicado_en": "",
            "estado": "Ambiguo: %d candidatos en %s"
                      % (len(confirmados), etiqueta_otra),
        }
    elif len(revision) == 1:
        elegido = revision[0]
        resultado = {
            "publicado_en": "",
            "estado": "Candidato en %s" % etiqueta_otra,
        }
    elif len(revision) > 1:
        elegido = revision[0]
        resultado = {
            "publicado_en": "",
            "estado": "Ambiguo: %d candidatos en %s"
                      % (len(revision), etiqueta_otra),
        }
    else:
        elegido = None
        resultado = {
            "publicado_en": "",
            "estado": "Sin coincidencia",
        }

    resultado.update(_diagnostico(elegido))
    return resultado


def _vigente(ruta_atribucion, ruta_catalogo):
    """True si la atribución es igual o más nueva que su catálogo local."""
    try:
        return (os.path.getmtime(ruta_atribucion)
                >= os.path.getmtime(ruta_catalogo))
    except OSError:
        return False


def _motivo_no_evaluable(ruta_publicado, ruta_catalogo, ruta_atribucion,
                         ruta_informe, etiqueta_otra):
    """
    Motivo por el que no se puede comparar, o None si la comparación es válida.

    Se revisa primero el catálogo publicado porque sin él no hay nada que
    comparar, aunque las fuentes locales tengan datos.
    """
    if ruta_publicado and not rutas.csv_tiene_filas(ruta_publicado):
        return "No evaluable: sin catálogo publicado (eventquery)"
    if ruta_catalogo and not rutas.csv_tiene_filas(ruta_catalogo):
        return "No evaluable: sin datos de %s en la ventana" % etiqueta_otra
    if (ruta_atribucion and ruta_catalogo
            and os.path.isfile(ruta_atribucion)
            and not _vigente(ruta_atribucion, ruta_catalogo)):
        return "No evaluable: atribución de %s desactualizada" % etiqueta_otra
    if ruta_informe is not None:
        if not os.path.isfile(ruta_informe):
            return "No evaluable: no se comparó %s" % etiqueta_otra
        if ruta_catalogo and not _vigente(ruta_informe, ruta_catalogo):
            return ("No evaluable: comparación de %s desactualizada"
                    % etiqueta_otra)
    return None


def _leer_atribucion(ruta):
    with open(ruta, encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo))


def _leer_csv(ruta):
    with open(ruta, encoding="utf-8-sig", newline="") as archivo:
        lector = csv.reader(archivo)
        encabezado = next(lector, [])
        return encabezado, list(lector)


def _sin_columnas_nuevas(encabezado, filas):
    """Quita columnas nuevas de una corrida anterior, para no duplicarlas."""
    presentes = [i for i, c in enumerate(encabezado)
                 if str(c).strip().lstrip("\ufeff") in COLUMNAS_NUEVAS]
    if not presentes:
        return encabezado, filas
    conservar = [i for i in range(len(encabezado)) if i not in presentes]
    nuevo_encabezado = [encabezado[i] for i in conservar]
    nuevas_filas = [[fila[i] if i < len(fila) else "" for i in conservar]
                    for fila in filas]
    return nuevo_encabezado, nuevas_filas


def _indice(encabezado, nombre):
    for i, columna in enumerate(encabezado):
        if str(columna).strip().lstrip("\ufeff") == nombre:
            return i
    return None


def _valor(fila, indice):
    """El valor de la fila en ese índice, o vacío si no existe."""
    if indice is None or indice >= len(fila):
        return ""
    return fila[indice]


def anotar(ruta_no_pub, ruta_atribucion, etiqueta_otra,
           ruta_catalogo_otra=None, ruta_informe=None, ruta_publicado=None):
    """
    Agrega las columnas de cruce al CSV de no publicados.

    Devuelve un dict con el total de eventos y cuántos quedaron publicados,
    ambiguos, candidatos, sin coincidencia y no evaluables. Si falta el CSV o
    no hay atribución vigente, igual agrega las columnas: así el esquema queda
    estable y no sobrevive el valor de una corrida anterior.
    """
    resumen = {"total": 0, "publicados": 0, "ambiguos": 0,
               "candidatos": 0, "sin_coincidencia": 0, "no_evaluables": 0}
    if not os.path.isfile(ruta_no_pub):
        return resumen

    encabezado, filas = _leer_csv(ruta_no_pub)
    encabezado, filas = _sin_columnas_nuevas(encabezado, filas)

    motivo = _motivo_no_evaluable(
        ruta_publicado, ruta_catalogo_otra, ruta_atribucion, ruta_informe,
        etiqueta_otra)

    candidatos = []
    if (not motivo and ruta_atribucion
            and os.path.isfile(ruta_atribucion)
            and (ruta_catalogo_otra is None
                 or _vigente(ruta_atribucion, ruta_catalogo_otra))):
        candidatos = preparar_candidatos(_leer_atribucion(ruta_atribucion))

    i_fecha = _indice(encabezado, "Fecha_Hora")
    i_lat = _indice(encabezado, "Latitud")
    i_lon = _indice(encabezado, "Longitud")

    nuevas_filas = []
    for fila in filas:
        evento = {
            "Fecha_Hora": _valor(fila, i_fecha),
            "Latitud": _valor(fila, i_lat),
            "Longitud": _valor(fila, i_lon),
        }
        if motivo:
            resultado = {"publicado_en": "", "estado": motivo,
                         "dt_seg": "", "dist_km": "", "analista": ""}
        else:
            resultado = evaluar_evento(evento, candidatos, etiqueta_otra)
        fila = list(fila) + [
            resultado["publicado_en"],
            resultado["estado"],
            resultado["dt_seg"],
            resultado["dist_km"],
            resultado["analista"],
        ]
        nuevas_filas.append(fila)

        resumen["total"] += 1
        if resultado["publicado_en"]:
            resumen["publicados"] += 1
        elif resultado["estado"].startswith("Ambiguo"):
            resumen["ambiguos"] += 1
        elif resultado["estado"].startswith("Candidato"):
            resumen["candidatos"] += 1
        elif resultado["estado"].startswith("No evaluable"):
            resumen["no_evaluables"] += 1
        else:
            resumen["sin_coincidencia"] += 1

    nuevo_encabezado = list(encabezado) + list(COLUMNAS_NUEVAS)
    temporal = ruta_no_pub + ".tmp"
    try:
        with open(temporal, "w", encoding="utf-8", newline="") as archivo:
            escritor = csv.writer(archivo)
            escritor.writerow(nuevo_encabezado)
            escritor.writerows(nuevas_filas)
        os.replace(temporal, ruta_no_pub)
    finally:
        try:
            if os.path.isfile(temporal):
                os.remove(temporal)
        except OSError:
            pass
    return resumen


def _ruta_publicado():
    """
    El CSV del catálogo publicado de esta corrida, o None si no se puede saber.

    Se prefiere new_2_*.csv, que es el que compara.py acaba de leer. Si no hay,
    se usa el concatenado todos_eventquery.csv como respaldo.
    """
    import glob
    candidatos = sorted(glob.glob(os.path.join("datos", "new_2_*.csv")))
    for ruta in candidatos:
        if rutas.csv_tiene_filas(ruta):
            return ruta
    if candidatos:
        return candidatos[0]
    todos = os.path.join("datos", "todos_eventquery.csv")
    return todos if os.path.isfile(todos) else None


def main():
    prog.avance_reset()
    ruta_publicado = _ruta_publicado()
    for i, fuente in enumerate(FUENTES):
        ruta_no_pub = rutas.p_datos(fuente["no_pub"])
        if not os.path.isfile(ruta_no_pub):
            print("No está %s; se omite el cruce de %s."
                  % (ruta_no_pub, fuente["etiqueta"]))
            prog.avance((i + 1) / len(FUENTES))
            continue

        ruta_atribucion = rutas.p_datos(fuente["atribucion"])
        ruta_catalogo = rutas.p_datos(fuente["catalogo_otra"])
        sin_datos_otra = not rutas.csv_tiene_filas(ruta_catalogo)
        sin_publicado = (ruta_publicado is not None
                         and not rutas.csv_tiene_filas(ruta_publicado))
        if sin_datos_otra:
            print("Sin datos de %s en la ventana." % fuente["otra"])
        elif sin_publicado:
            print("Sin catálogo publicado (eventquery).")
        elif not os.path.isfile(ruta_atribucion):
            print("Sin %s; las columnas de cruce quedan sin candidatos."
                  % ruta_atribucion)
        elif not _vigente(ruta_atribucion, ruta_catalogo):
            print("%s no es vigente respecto de %s; no se usa."
                  % (ruta_atribucion, ruta_catalogo))

        resumen = anotar(
            ruta_no_pub, ruta_atribucion, fuente["otra"], ruta_catalogo,
            ruta_informe=rutas.p_informes(fuente["informe"]),
            ruta_publicado=ruta_publicado)
        print("No publicados de %s: %d eventos (%d publicados en %s, "
              "%d ambiguos, %d candidatos, %d sin coincidencia, "
              "%d no evaluables)."
              % (fuente["etiqueta"], resumen["total"],
                 resumen["publicados"], fuente["otra"],
                 resumen["ambiguos"], resumen["candidatos"],
                 resumen["sin_coincidencia"], resumen["no_evaluables"]))
        prog.avance((i + 1) / len(FUENTES))


if __name__ == "__main__":
    main()
