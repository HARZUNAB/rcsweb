import csv
import sys, os
from os import remove
import time
import shutil
import datetime
from datetime import timedelta

import rutas
import prog

# Separador de los informes: tabulador. Antes eran espacios y no se podían leer
# como columnas: "fecha hora" partía en dos y una referencia o un analista con
# espacios corrían el resto de la fila. Con tabulador cada campo va entero.
SEP = "\t"

# Definiciones de columnas de cada informe: (clave, título, ancho, es_num). Las
# usa la app para mostrar y descargar la tabla de «Ver repetidos», así que la
# cabecera del archivo y las columnas de la pantalla salen de la misma lista.
COLUMNAS_PUBLICA = [
    ("fecha_hora", "Fecha y hora", 150, False),
    ("latitud", "Lat", 80, True),
    ("longitud", "Lon", 80, True),
    ("prof", "Prof (km)", 80, True),
    ("mag", "Mag", 60, True),
    ("tipomag", "Tipo", 60, False),
    ("referencia", "Referencia", 280, False),
    ("percibido", "Percib.", 70, False),
]
COLUMNAS_SEISAN = [
    ("fecha_hora", "Fecha y hora", 150, False),
    ("latitud", "Lat", 80, True),
    ("longitud", "Lon", 80, True),
    ("prof", "Prof (km)", 80, True),
    ("mag", "Mag", 60, True),
    ("tipomag", "Tipo", 60, False),
    ("analista", "Analista", 150, False),
]
COLUMNAS_EXCLU = [
    ("fecha_hora", "Fecha y hora", 150, False),
    ("analista", "Analista", 150, False),
]

# cabeceras para cada archivo .txt de salida (misma clave que COLUMNAS_*)
cabecera_publica = SEP.join(c[0] for c in COLUMNAS_PUBLICA) + "\n"
cabecera_seisan = SEP.join(c[0] for c in COLUMNAS_SEISAN) + "\n"

# campos de cada fuente utilizados en los archivos de salida
campos_publica=['fecha_hora', 'lat', 'lon', 'prof', 'mag', 'tipo_mag', 'ref', 'perc']
campos_seisan=['fecha_hora', 'lat', 'lon', 'prof', 'mag', 'tipo_mag', 'analista']

# parametros de los dos niveles de filtro (amplio y estricto)
MAX_SEG_AMPLIO=6
MAX_LAT_LON_AMPLIO=2.0
MAX_SEG_ESTRICTO=3
MAX_LAT_LON_ESTRICTO=1.0

_FORMATO='%Y-%m-%d  %H:%M:%S'

def _normalizar_fecha_hora(texto):
    # unifica las variantes que llegan según la fuente: 'T' de eventquery,
    # 'Z'/microsegundos de las exportaciones, espacios simples o dobles.
    texto = (texto or "").strip()
    if texto.endswith("Z"):
        texto = texto[:-1]
    texto = texto.replace("T", " ")
    if "." in texto:
        texto = texto.split(".", 1)[0]
    return texto

def _parsear_fecha_hora(texto):
    texto = _normalizar_fecha_hora(texto)
    # normaliza el segundo 60 -> 59 antes de convertir
    if texto[-2:] == '60':
        texto = texto[:-2] + '59'
    return datetime.datetime.strptime(texto, _FORMATO)

def detecta_repetidos(lista_sismos, max_seg, max_lat, max_lon, nombre_archivo, cabecera, campos):
    # revisa cada sismo contra toda la lista y cuenta las coincidencias dentro de la ventana de tiempo y coordenadas
    total_repetidos=0
    avance=0
    archivo=open(rutas.p_informes(nombre_archivo), "w")
    archivo.write(cabecera)
    for sismo in lista_sismos:
        repeticiones=0
        avance=avance+1
        prog.avance(avance / len(lista_sismos))
        hora_1=sismo['dt']

        for sismo_aux in lista_sismos:
            hora_2=sismo_aux['dt']

            deltatiempo1=hora_2-hora_1
            deltatiempo2=hora_1-hora_2

            deltadias1=deltatiempo1.days
            deltasegundos1=deltatiempo1.total_seconds()

            deltadias2=deltatiempo2.days
            deltasegundos2=deltatiempo2.total_seconds()

            # ventana de tiempo para filtrar posibles eventos repetidos
            if (deltadias1 == 0 or deltadias2 == 0) and ((deltasegundos1 >=0 and deltasegundos1 <=max_seg) or (deltasegundos2 >= 0 and deltasegundos2 <= max_seg)):
                lat_sismo=float(sismo['lat'])
                lat_aux=float(sismo_aux['lat'])
                lon_sismo=float(sismo['lon'])
                lon_aux=float(sismo_aux['lon'])
                delta_lat=round((lat_sismo*(-1))-(lat_aux*(-1)),3)
                delta_lon=round((lon_sismo*(-1))-(lon_aux*(-1)),3)

                if delta_lat<0:
                    delta_lat=delta_lat*(-1)

                if delta_lon<0:
                    delta_lon=delta_lon*(-1)

                # ventana de coordenadas para filtrar posibles eventos repetidos
                if (delta_lat >= 0 and delta_lat <= max_lat) and (delta_lon >= 0 and delta_lon <= max_lon):
                    repeticiones=repeticiones+1

        # si encuentra mas de un evento con similitudes en la busqueda lo define como posible repetido
        # esto es por que la busqueda se hace tomando un elemento de la lista y lo busca en la misma lista hasta llegar al final de esta
        if repeticiones > 1:
            total_repetidos=total_repetidos+1
            linea=SEP.join(sismo[campo] for campo in campos)
            archivo.write(linea+"\n")

    archivo.close()
    return total_repetidos

def _completar_coordenada(valor):
    if len(valor) <= 6:
        if len(valor) == 3:
            return valor + ".000"
        if len(valor) == 4:
            return valor + "000"
        if len(valor) == 5:
            return valor + "00"
        if len(valor) == 6:
            return valor + "0"
    return valor


def _leer_publica(ruta):
    lista = []
    with open(ruta) as archivo:
        lector = csv.reader(archivo)
        next(lector, None)
        for linea in lector:
            if len(linea) < 9:
                continue
            try:
                fecha = _parsear_fecha_hora(linea[1])
            except (ValueError, IndexError):
                continue
            lista.append({
                "fecha_hora": linea[1],
                "dt": fecha,
                "lat": _completar_coordenada(linea[2]),
                "lon": _completar_coordenada(linea[3]),
                "prof": linea[4],
                "mag": linea[5],
                "tipo_mag": linea[6],
                "ref": linea[7],
                "perc": linea[8],
            })
    return lista


def _leer_local(ruta):
    lista = []
    with open(ruta) as archivo:
        lector = csv.reader(archivo)
        next(lector, None)
        for linea in lector:
            if len(linea) < 8:
                continue
            try:
                fecha = _parsear_fecha_hora(linea[1])
            except (ValueError, IndexError):
                continue
            lista.append({
                "fecha_hora": linea[1],
                "dt": fecha,
                "lat": _completar_coordenada(linea[2]),
                "lon": _completar_coordenada(linea[3]),
                "prof": linea[4],
                "mag": linea[5],
                "tipo_mag": linea[6],
                "analista": linea[7],
            })
    return lista


def _separar_argumentos(argv):
    prefijos = None
    rutas = []
    for argumento in argv[1:]:
        if argumento.startswith("--prefijos="):
            valor = argumento.split("=", 1)[1]
            prefijos = [p.strip() for p in valor.split(",") if p.strip()]
        else:
            rutas.append(argumento)
    return rutas, prefijos


def _prefijos_historicos(rutas):
    prefijos = []
    for indice, _ in enumerate(rutas):
        if indice == 0:
            prefijos.append("seisan")
        elif indice == 1:
            prefijos.append("seiscomp")
        else:
            prefijos.append("fuente%d" % (indice + 1))
    return prefijos


def main(argv=None):
    argv = sys.argv if argv is None else argv
    rutas, prefijos = _separar_argumentos(argv)
    if not rutas:
        print(
            "Uso: repetidos.py <eventquery.csv> <catalogo_local.csv> [...] "
            "[--prefijos=a,b]"
        )
        return 2

    ruta_publica = rutas[0]
    rutas_locales = rutas[1:]
    if prefijos is None:
        prefijos = _prefijos_historicos(rutas_locales)
    if len(prefijos) != len(rutas_locales):
        print("La cantidad de prefijos no coincide con los catálogos locales.")
        return 2

    lista_publica = _leer_publica(ruta_publica)
    print("total eventos", ruta_publica, len(lista_publica),
          "( fuente eventquery )")

    print("Revisando datos de publica...")
    if lista_publica:
        detecta_repetidos(
            lista_publica, MAX_SEG_AMPLIO, MAX_LAT_LON_AMPLIO,
            MAX_LAT_LON_AMPLIO, "rep_publica_amplio.txt",
            cabecera_publica, campos_publica,
        )
        detecta_repetidos(
            lista_publica, MAX_SEG_ESTRICTO, MAX_LAT_LON_ESTRICTO,
            MAX_LAT_LON_ESTRICTO, "rep_publica_estricto.txt",
            cabecera_publica, campos_publica,
        )
    print("\nFinalizado")

    for ruta_local, prefijo in zip(rutas_locales, prefijos):
        lista = _leer_local(ruta_local)
        print("total eventos", ruta_local, len(lista),
              "( fuente %s )" % prefijo)
        print("\nRevisando datos de %s..." % prefijo)
        if lista:
            detecta_repetidos(
                lista, MAX_SEG_AMPLIO, MAX_LAT_LON_AMPLIO,
                MAX_LAT_LON_AMPLIO, "rep_%s_amplio.txt" % prefijo,
                cabecera_seisan, campos_seisan,
            )
            detecta_repetidos(
                lista, MAX_SEG_ESTRICTO, MAX_LAT_LON_ESTRICTO,
                MAX_LAT_LON_ESTRICTO, "rep_%s_estricto.txt" % prefijo,
                cabecera_seisan, campos_seisan,
            )
        print("\nFinalizado")

    print("----------------------------------- Salida -----------------------------------")
    print("Archivos generados en informes/: rep_publica_*.txt y "
          "rep_<fuente>_*.txt")
    return 0


if __name__ == "__main__":
    main()
