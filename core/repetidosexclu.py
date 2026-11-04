import csv
import sys, os
from os import remove
import time
import shutil
import datetime
from datetime import timedelta

import rutas
import prog

_FORMATO='%Y-%m-%d  %H:%M:%S'

def _parsear_fecha_hora(texto):
    # normaliza el segundo 60 -> 59 antes de convertir
    if texto[-2:]=='60':
        texto=texto[0:18]+'59'
    return datetime.datetime.strptime(texto, _FORMATO)

def detecta_excluidos(lista_excluidos, lista_select, max_seg, archivo):
    # Compara cada evento excluido contra el select y escribe una linea por
    # cada coincidencia dentro de la ventana de tiempo (mismo dia y a lo sumo
    # max_seg segundos). Devuelve el total de coincidencias: es una por par, no
    # por evento, igual que siempre.
    total = 0
    avance = 0
    for sismo2 in lista_excluidos:
        avance = avance + 1
        prog.avance(avance / len(lista_excluidos))
        hora_1 = sismo2['dt']
        for sismo3 in lista_select:
            hora_2 = sismo3['dt']

            deltatiempo1 = hora_2 - hora_1
            deltatiempo2 = hora_1 - hora_2

            deltadias1 = deltatiempo1.days
            deltasegundos1 = deltatiempo1.total_seconds()

            deltadias2 = deltatiempo2.days
            deltasegundos2 = deltatiempo2.total_seconds()

            # Ventana de 6 segundos para filtrar posibles eventos repetidos
            if (deltadias1 == 0 or deltadias2 == 0) and ((deltasegundos1 >= 0 and deltasegundos1 <= max_seg) or (deltasegundos2 >= 0 and deltasegundos2 <= max_seg)):
                archivo.write(sismo2['fecha_hora'] + '\t' + sismo2['analista'] + "\n")
                total = total + 1
    return total

def main(argv=None):
    argv = sys.argv if argv is None else argv

    # archivos de salida
    archivo2=open(rutas.p_informes("rep_seisan_exclu.txt"), "w")

    # cabeceras para cada archivo .txt de salida. Tabuladas, para que la app
    # las muestre como tabla (la referencia o el analista pueden tener espacios).
    archivo2.write("fecha_hora\tanalista\n")

    csv_file_2 = open(argv[1])
    csvreader_2 = csv.reader(csv_file_2)

    csv_file_3 = open(argv[2])
    csvreader_3 = csv.reader(csv_file_3)

    # saltar el encabezado
    next(csvreader_2,None)
    next(csvreader_3,None)

    # Declara listas
    listacsv_2=[]
    listacsv_3=[]

    numsis_csv_2=0
    numsis_csv_3=0

    # Creando diccionario que contiene lista con datos extraidos del .csv ordenado ("extraidos" desde select.out)
    for linea2 in csvreader_2:
        diccsv_2={
            "fecha_hora":linea2[1],
            "dt":_parsear_fecha_hora(linea2[1]),
            "analista":linea2[2],
        }
        listacsv_2.append(diccsv_2)

    for sismo in listacsv_2:
        numsis_csv_2+=1

    print('total de eventos a revisar', numsis_csv_2, "( fuente archivo excluidos del selec.out )")

    # Creando diccionario que contiene lista con datos extraidos del .csv ordenado (desde select.out)
    for linea3 in csvreader_3:
        diccsv_3={
            "fecha_hora":linea3[1],
            "dt":_parsear_fecha_hora(linea3[1]),
            "analista":linea3[7],
        }
        listacsv_3.append(diccsv_3)

    for sismo3 in listacsv_3:
        numsis_csv_3+=1

    print('total de eventos desde select.out', numsis_csv_3, "( fuente archivo select.out )")

    fecha_inicio = datetime.datetime.today().strftime("%Y-%m-%d %H:%M:%S")

    rep_seisan_exclu_total=detecta_excluidos(listacsv_2, listacsv_3, 6, archivo2)

    print("\nFinalizado")

    fecha_termino = datetime.datetime.today().strftime("%Y-%m-%d %H:%M:%S")
    fecha_inicio = datetime.datetime.strptime(fecha_inicio, '%Y-%m-%d  %H:%M:%S')
    fecha_termino = datetime.datetime.strptime(fecha_termino, '%Y-%m-%d  %H:%M:%S')
    tiempo_proc=fecha_termino-fecha_inicio

    print('tiempo proceso:', tiempo_proc) 
    print('Posibles repetidos excluidos en seisan:',rep_seisan_exclu_total)
    print('Archivos generados...')
    print(archivo2.name)


if __name__ == "__main__":
    main()
