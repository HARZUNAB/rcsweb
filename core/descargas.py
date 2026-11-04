#!/usr/bin/env python3
"""
descargas.py
============
Todo lo que la app deja escribir en disco para que uno se lo lleve.

Centraliza las descargas en un solo lugar para que las cuatro vistas con
tabla (los dos listados de no actualizados, los no publicados y los repetidos)
más los paneles no repitan la misma mecánica: preguntar el nombre y el formato,
construir un nombre que no pise el anterior, escribir con el BOM que necesita
Excel y avisar dónde quedó.

Por qué una carpeta propia y no informes/ o listados/: lo que uno descarga es
suyo, no un resultado del análisis. Informes/ es caché que la app relee para no
repetir trabajo; mezclar ahí los entregables haría imposible saber qué se puede
borrar sin romper la reapertura.

Dos formatos porque los dos se piden:

CSV   separado por comas, para planillas.
TXT   separado por tabulaciones, que es lo que pega directo en las planillas
      que se usan para revisar y distribuyen los resultados.

El CSV va con utf-8-sig: sin el BOM, Excel en Windows abre los acentos mal y las
columnas numéricas como texto. La TXT va con utf-8 pelado, porque un BOM se cuela
en el primer campo y rompe las comparaciones contra el encabezado.

Los informes que ya son texto se pueden volcar tal cual con exportar_lineas,
que no pregunta el formato (el contenido no es una tabla). Hoy no lo usa la app:
los repetidos se muestran como tabla y se bajan por el mismo diálogo que el
resto. Se mantiene por compatibilidad.

Este módulo no toca la caché: solo escribe en descargas/, y una vez escrito el
archivo es del usuario.
"""

import csv
import os
import subprocess
import sys
from datetime import datetime

import rutas

# Marca de fecha para los nombres de archivo, no para leer datos. La misma que
# usa el exportador de SeisComp para las ventanas, para que los nombres se
# vean todos del mismo modo.
FORMATO_FECHA = "%Y%m%d%H%M%S"

EXTENSIONES = {"csv": ".csv", "txt": ".txt"}
SEPARADORES = {"csv": ",", "txt": "\t"}

# La última elección del usuario: uno que exporta a CSV para Excel y después a
# TXT para la planilla no debería tener que volver a decidir en cada descarga.
_ultimo_formato = "csv"


def _etiqueta_secundaria(ttk, marco, texto, **opciones):
    """
    Una Label atenuada, con el estilo de ttkbootstrap si está disponible.

    Este módulo se importa desde scripts que no usan la app, donde ttk es el de
    la biblioteca estándar y no acepta bootstyle. Por eso el estilo va en un
    try: la diferencia es que se vea más claro o más apagado, no que el diálogo
    no abra. Que este diálogo no abriera era justo el bug reportado.
    """
    try:
        return ttk.Label(marco, text=texto, bootstyle="secondary",
                         **opciones)
    except Exception:
        return ttk.Label(marco, text=texto, foreground="#777777", **opciones)


def encima_de(padre, ventana=None, modal=True):
    """
    Pone una ventana delante de la principal y, si es un diálogo, la hace modal.

    Sin esto, un Toplevel con transient() puede abrirse detrás de la ventana
    principal: el diálogo se está mostrando, la app sigue respondiendo y parece
    que no pasó nada. Con grab_set() tampoco se puede mandar a otro lado
    clickeando fuera, que es justo lo que se pierde por no verlo.

    'modal=True' es lo correcto para un diálogo de confirmación: la app no debe
    seguir hasta contestarlo. En cambio, para las ventanas de consulta (el
    detalle del evento, las estaciones), el grab deja la app bloqueada mientras
    están abiertas y hay que cerrarlas para seguir navegando. Ahí va
    'modal=False': se suben y se les da el foco la primera vez, pero sin capturar
    la entrada, así el teclado y el mouse siguen en la lista.

    El grab solo se toma si la ventana ya está mapeada: un grab sobre una
    ventana sin mapear (o sobre una pila gráfica frágil, p. ej. nvidia con
    AnyDesk) puede dejar la sesión entera bloqueada hasta matar el proceso. Si
    no está mapeada, el diálogo se muestra igual, solo que sin capturar la
    entrada.

    ventana puede venir None (los messagebox devuelven None al cerrarse): en ese
    caso solo se sube el foco a la ventana principal, que es lo que hace falta
    para que el mensaje que ya se mostró quede a la vista.
    """
    try:
        objetivo = ventana if ventana is not None else padre
        if objetivo is None:
            return
        objetivo.lift()
        if ventana is None or modal:
            # En un diálogo modal el foco tiene que caer adentro. En una ventana
            # de consulta no: robar el foco en cada clic corta la navegación con
            # el teclado sobre la lista.
            objetivo.focus_force()
        if ventana is not None and modal:
            ventana.update_idletasks()
            if ventana.winfo_viewable():
                ventana.grab_set()
    except Exception:
        # Si el gestor de ventanas no colabora, el diálogo igual funciona: es
        # mejor un Toplevel detrás que no tener diálogo.
        pass


def _centrar_sobre(ventana, padre, ancho, alto):
    """
    Centra 'ventana' sobre 'padre' y la acota a la pantalla.

    Tk deja un Toplevel nuevo donde quiere el gestor de ventanas, y centrarlo
    sobre el padre y no sobre el escritorio virtual lo mantiene en el mismo
    monitor de la app (ver revisa_seiscomp._centrar_en_pantalla).
    """
    ancho = max(1, int(ancho))
    alto = max(1, int(alto))
    try:
        pantalla_ancho = ventana.winfo_screenwidth()
        pantalla_alto = ventana.winfo_screenheight()
    except Exception:
        ventana.geometry("%dx%d" % (ancho, alto))
        return
    ancho = min(ancho, pantalla_ancho)
    alto = min(alto, pantalla_alto)
    centro_x = pantalla_ancho // 2
    centro_y = pantalla_alto // 2
    if padre is not None:
        try:
            padre.update_idletasks()
            centro_x = padre.winfo_rootx() + padre.winfo_width() // 2
            centro_y = padre.winfo_rooty() + padre.winfo_height() // 2
        except Exception:
            pass
    x = max(0, min(centro_x - ancho // 2, pantalla_ancho - ancho))
    y = max(0, min(centro_y - alto // 2, pantalla_alto - alto))
    ventana.geometry("%dx%d+%d+%d" % (ancho, alto, x, y))


def mostrar_texto_mono(padre, titulo, texto, ancho=620, alto=320):
    """
    Muestra un texto de ancho fijo en un diálogo propio.

    Los messagebox usan fuente proporcional, así que una tabla alineada con
    espacios se ve corrida. Acá el texto va en un widget con fuente
    monoespaciada y scroll horizontal, para que las columnas queden alineadas.
    Se usa TkFixedFont y no un nombre de fuente, que en Linux puede no existir.

    Devuelve el Toplevel, o None si no hay Tk disponible.
    """
    try:
        import tkinter as tk
        from tkinter import ttk
        from tkinter import font as tkfont
    except ImportError:
        return None
    if padre is None:
        return None
    try:
        top = tk.Toplevel(padre)
        top.title(titulo)
        try:
            top.transient(padre)
        except Exception:
            pass

        fuente = tkfont.nametofont("TkFixedFont").copy()
        fuente.configure(size=10)

        marco = ttk.Frame(top, padding=8)
        marco.pack(fill="both", expand=True)
        caja = tk.Text(marco, wrap="none", font=fuente, width=1, height=1,
                       borderwidth=1, relief="solid")
        barra_v = ttk.Scrollbar(marco, orient="vertical", command=caja.yview)
        barra_h = ttk.Scrollbar(marco, orient="horizontal", command=caja.xview)
        caja.configure(yscrollcommand=barra_v.set, xscrollcommand=barra_h.set)
        caja.insert("1.0", texto)
        caja.configure(state="disabled")
        caja.grid(row=0, column=0, sticky="nsew")
        barra_v.grid(row=0, column=1, sticky="ns")
        barra_h.grid(row=1, column=0, sticky="ew")
        marco.rowconfigure(0, weight=1)
        marco.columnconfigure(0, weight=1)

        botones = ttk.Frame(marco)
        botones.grid(row=2, column=0, columnspan=2, sticky="e", pady=(6, 0))
        ttk.Button(botones, text="Cerrar", command=top.destroy).pack()

        def _cerrar(_evento=None):
            top.destroy()

        top.bind("<Escape>", _cerrar)
        top.bind("<Return>", _cerrar)
        top.protocol("WM_DELETE_WINDOW", _cerrar)
        _centrar_sobre(top, padre, ancho, alto)
        top.update_idletasks()
        encima_de(padre, top, modal=True)
        return top
    except Exception:
        return None


def _carpeta(base):
    """Carpeta de descargas bajo base, creándola si hace falta."""
    destino = os.path.join(base, rutas.DIR_DESCARGAS)
    os.makedirs(destino, exist_ok=True)
    return destino


def carpeta_descargas(cwd=None):
    """Ruta de la carpeta de descargas del directorio de ejecución."""
    return _carpeta(os.getcwd() if cwd is None else cwd)


def _sanear_nombre(nombre):
    """Deja solo lo que puede ir en un nombre de archivo (sin separadores)."""
    return "".join(c for c in (nombre or "").lower()
                   if c.isalnum() or c in "-_")


def _raiz_descarga(etiqueta, nombre=None):
    """Parte del nombre sin extensión: la elegida o la de por defecto.

    La marca de tiempo va en el nombre por defecto porque lo mismo se descarga
    más de una vez (distinto filtro, distinta fecha de corrida) y sin ella cada
    una pisaría a la anterior. Cuando el usuario escribió un nombre, se respeta
    tal cual: si quiere que se pise (o no) lo deciden el chequeo de existencia y
    la pregunta de sobrescritura, no la app.
    """
    if nombre is not None:
        return _sanear_nombre(nombre) or "descarga"
    raiz = _sanear_nombre(etiqueta) or "descarga"
    return "%s_%s" % (raiz, datetime.now().strftime(FORMATO_FECHA))


def ruta_descarga(etiqueta, extension, cwd=None, nombre=None):
    """
    Ruta exacta en descargas/ (sin correlativo) para una descarga.

    No crea la carpeta ni evita pisar: es el destino que se usa para preguntar
    si un archivo ya existe antes de escribir.
    """
    base = os.getcwd() if cwd is None else cwd
    extension = extension if extension in EXTENSIONES else "csv"
    carpeta = os.path.join(base, rutas.DIR_DESCARGAS)
    return os.path.join(carpeta, _raiz_descarga(etiqueta, nombre)
                        + EXTENSIONES[extension])


def nombre_descarga(etiqueta, extension, cwd=None, nombre=None,
                    sobrescribir=False):
    """
    Nombre único en descargas/ para una descarga.

    Con `nombre` se usa ese nombre base (el que el usuario escribió en el
    diálogo); sin él se arma `etiqueta_marca`. Si el destino ya existe y
    `sobrescribir` es False, le agrega un correlativo: una descarga no debería
    fallar nunca porque alguien exportó hace un minuto. Con `sobrescribir=True`
    se devuelve la ruta tal cual, para pisar lo que había.
    """
    base = os.getcwd() if cwd is None else cwd
    extension = extension if extension in EXTENSIONES else "csv"
    sufijo = EXTENSIONES[extension]
    raiz = _raiz_descarga(etiqueta, nombre)
    carpeta = _carpeta(base)
    ruta = os.path.join(carpeta, raiz + sufijo)
    if sobrescribir:
        return ruta
    n = 2
    while os.path.exists(ruta):
        ruta = os.path.join(carpeta, "%s_%d%s" % (raiz, n, sufijo))
        n += 1
    return ruta


def escribir_filas(ruta, encabezados, filas, formato="csv"):
    """
    Escribe una tabla de encabezados y filas en ruta.

    filas es una lista de listas ya formateadas a texto: entra exactamente lo
    que se ve en pantalla, con el guion de "sin dato" y los números ya
    redondeados. Lo de formatear es del caller, que es quien sabe de qué tipo
    es cada campo; aquí solo se elige el separador.

    Para CSV usa csv.writer porque entrecomilla los campos que bringan coma o
    salto, que en coordenadas y comentarios pasa siempre. Para TXT se hace a
    mano: el tabulador no necesita escapes y csv.writer lo transformaría en
    comillas que en la planilla quedan como caracteres de más.
    """
    # El BOM va solo en el CSV. Excel en Windows necesita utf-8-sig para no
    # romper los acentos, pero en la TXT un BOM parte el nombre de la primera
    # columna: se cuela en el primer campo y delata comparisons con cut -f1 o
    # con el encabezado de un read_csv de pandas.
    separador = SEPARADORES.get(formato, ",")
    if formato == "csv":
        with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
            escritor = csv.writer(f)
            escritor.writerow(list(encabezados))
            for fila in filas:
                escritor.writerow(list(fila))
        return ruta

    with open(ruta, "w", encoding="utf-8", newline="") as f:
        f.write(separador.join(str(h) for h in encabezados) + "\r\n")
        for fila in filas:
            f.write(separador.join(str(v) for v in fila) + "\r\n")
    return ruta


def exportar_tabla(encabezados, filas, etiqueta, cwd=None, formato="csv",
                   nombre=None, sobrescribir=False):
    """
    Escribe una tabla ya formateada y devuelve la ruta, o None si no hay filas.

    None en vez de un archivo vacío a propósito: un CSV con solo encabezados
    parece un listado que no encontró nada, y es peor que no haber descargado.

    `nombre` es el nombre base elegido en el diálogo (sin extensión) y
    `sobrescribir` si el usuario aceptó pisar un archivo existente.
    """
    if not filas:
        return None
    base = os.getcwd() if cwd is None else cwd
    ruta = nombre_descarga(etiqueta, formato, cwd=base, nombre=nombre,
                           sobrescribir=sobrescribir)
    escribir_filas(ruta, encabezados, filas, formato)
    return ruta


def exportar_lineas(lineas, etiqueta, cwd=None, nombre=None,
                    sobrescribir=False):
    """
    Vuelca un archivo de texto tal cual (informes de repetidos, etc.).

    A diferencia de exportar_tabla no formatea nada: lo que se descarga es el
    informe completo, no lo que entra en pantalla. Los listados se muestran
    recortados para que la ventana siga siendo usable; aquí va todo, porque un
    informe que se corta a la primera fila no sirve para nada.

    Siempre .txt y siempre sin BOM. Estos informes vienen separados por espacios
    con las columnas alineadas a lo ancho (ver repetidos.py), no son tablas: no
    hay un CSV que corresponda sin inventar columnas que no están. Por eso
    preguntar el formato aquí no tenía sentido.
    """
    if not lineas:
        return None
    base = os.getcwd() if cwd is None else cwd
    ruta = nombre_descarga(etiqueta, "txt", cwd=base, nombre=nombre,
                           sobrescribir=sobrescribir)
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        for linea in lineas:
            f.write(linea if linea.endswith("\n") else linea + "\n")
    return ruta


def leer_lineas(ruta):
    """Contenido de un archivo de texto como lista de líneas, o [] si no está."""
    if not os.path.isfile(ruta):
        return []
    with open(ruta, encoding="utf-8-sig", errors="replace") as f:
        return f.readlines()


def _rutas_candidatas(cwd, formato, nombre, sufijos):
    """Rutas que ocuparían los archivos de una descarga (una por sufijo)."""
    base = os.getcwd() if cwd is None else cwd
    extension = formato if formato in EXTENSIONES else "csv"
    sufijo = EXTENSIONES[extension]
    carpeta = os.path.join(base, rutas.DIR_DESCARGAS)
    return [os.path.join(carpeta,
                         (_sanear_nombre(nombre + s) or "descarga") + sufijo)
            for s in sufijos]


def _confirmar_sobrescribir(padre, existentes):
    """Pregunta si pisar lo que ya existe. Devuelve True si hay que pisar."""
    try:
        from tkinter import messagebox
    except ImportError:
        return False
    encima_de(padre)
    if len(existentes) == 1:
        mensaje = "Ya existe %s.\n\n¿Quieres sobrescribirlo?" % \
            os.path.basename(existentes[0])
    else:
        detalle = "\n".join(os.path.basename(r) for r in existentes)
        mensaje = ("Ya existen %d archivos:\n%s\n\n¿Quieres sobrescribirlos?"
                   % (len(existentes), detalle))
    return bool(messagebox.askyesno("Sobrescribir", mensaje, parent=padre))


def preguntar_descarga(padre, etiqueta="descarga", cwd=None, con_formato=True,
                       sufijos=("",), titulo="Descarga"):
    """
    Pregunta el nombre y (si corresponde) el formato de una descarga.

    Devuelve '(formato, nombre, sobrescribir)' o None si se cancela.

    'nombre' es la parte sin extensión: la extensión la decide el formato, que
    es lo que el usuario elige en el mismo diálogo. Si ya había un archivo con
    ese nombre, pregunta antes de pisarlo; 'sobrescribir' dice qué contestó, y
    con False el diálogo no se cierra hasta que el nombre no choque o se cancele.

    None cancela, no cae a valores por defecto: si alguien no elige, lo
    razonable es no escribir nada antes que adivinar mal.
    """
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        return None
    if padre is None:
        return None

    eleccion = {"formato": None, "nombre": None, "sobrescribir": False}
    por_defecto = _raiz_descarga(etiqueta)
    top = tk.Toplevel(padre)
    top.title(titulo)
    top.transient(padre)
    top.resizable(False, False)
    marco = ttk.Frame(top, padding=12)
    marco.pack(fill="both", expand=True)

    ttk.Label(marco, text="¿Con qué nombre quieres el archivo?"
              ).pack(anchor="w")
    marco_nombre = ttk.Frame(marco)
    marco_nombre.pack(anchor="w", fill="x", pady=(6, 0))
    entrada = tk.Entry(marco_nombre, width=42)
    entrada.pack(side="left")
    entrada.insert(0, por_defecto)
    entrada.selection_range(0, "end")
    ext_var = tk.StringVar(value=EXTENSIONES.get(_ultimo_formato, ".csv"))
    ttk.Label(marco_nombre, textvariable=ext_var).pack(side="left", padx=(4, 0))

    var = tk.StringVar(value=_ultimo_formato)
    if con_formato:
        ttk.Label(marco, text="¿En qué formato?").pack(anchor="w",
                                                       pady=(10, 0))
        opciones = [("csv", "CSV  (.csv)   para planillas"),
                    ("txt", "TXT  (.txt)   separado por tabulaciones")]
        marco_op = ttk.Frame(marco)
        marco_op.pack(anchor="w", fill="x", pady=(2, 4))
        # Una sola variable para las dos opciones: eso es lo que hace que sean
        # un grupo. Con una variable por opción cada radiobutton va por su
        # cuenta y no hay forma de desmarcar ninguno de los dos.
        for clave, texto in opciones:
            ttk.Radiobutton(marco_op, text=texto, value=clave,
                            variable=var).pack(anchor="w")

    vista = _etiqueta_secundaria(ttk, marco, "")
    vista.pack(anchor="w", pady=(6, 0))
    _etiqueta_secundaria(
        ttk, marco,
        "Se guarda en descargas/ dentro de la carpeta del análisis."
    ).pack(anchor="w")

    def _formato_actual():
        if not con_formato:
            return "txt"
        return var.get() if var.get() in EXTENSIONES else "csv"

    def _actualizar(*_args):
        extension = EXTENSIONES.get(_formato_actual(), ".csv")
        ext_var.set(extension)
        nombre = entrada.get().strip() or por_defecto
        vista.config(text="Se guardará como: %s%s" % (nombre, extension))

    entrada.bind("<KeyRelease>", _actualizar)
    var.trace_add("write", _actualizar)
    _actualizar()

    def aceptar(_evento=None):
        global _ultimo_formato
        elegido = _formato_actual()
        nombre = entrada.get().strip() or por_defecto
        rutas = _rutas_candidatas(cwd, elegido, nombre, sufijos)
        existentes = [r for r in rutas if os.path.exists(r)]
        if existentes and not _confirmar_sobrescribir(top, existentes):
            # No se cierra: el usuario puede corregir el nombre aquí mismo.
            return
        _ultimo_formato = elegido
        eleccion["formato"] = elegido
        eleccion["nombre"] = nombre
        eleccion["sobrescribir"] = bool(existentes)
        top.destroy()

    def cancelar(_evento=None):
        top.destroy()

    botones = ttk.Frame(marco)
    botones.pack(anchor="e", pady=(10, 0))
    # Los botones también son de ttkbootstrap en la app y de ttk estándar fuera
    # de ella: mismo try que en _etiqueta_secundaria.
    try:
        ttk.Button(botones, text="Cancelar", command=cancelar,
                   bootstyle="secondary").pack(side="right")
        ttk.Button(botones, text="Descargar", command=aceptar,
                   bootstyle="primary").pack(side="right", padx=(0, 6))
    except Exception:
        ttk.Button(botones, text="Cancelar", command=cancelar).pack(side="right")
        ttk.Button(botones, text="Descargar", command=aceptar).pack(
            side="right", padx=(0, 6))
    top.bind("<Return>", aceptar)
    top.bind("<Escape>", cancelar)
    top.protocol("WM_DELETE_WINDOW", cancelar)
    entrada.focus_set()
    encima_de(padre, top)
    padre.wait_window(top)
    if eleccion["formato"] is None:
        return None
    return eleccion["formato"], eleccion["nombre"], eleccion["sobrescribir"]


def preguntar_formato(padre, titulo="Formato de descarga"):
    """
    Pregunta el formato y devuelve 'csv', 'txt' o None si se cancela.

    Se mantiene por compatibilidad con los caminos que solo querían el formato.
    El diálogo ahora también pregunta el nombre; acá se descarta.
    """
    pedido = preguntar_descarga(padre, titulo=titulo)
    return pedido[0] if pedido else None


def _avisar_error(padre, mensaje):
    """Mostrar un error de escritura sin que se caiga la app."""
    try:
        from tkinter import messagebox
        # Primero se sube el foco a la ventana principal y después se abre el
        # mensaje: messagebox es bloqueante, así que pasarlo como argumento de
        # encima_de solo lo enfocaría al cerrarse, cuando ya no sirve de nada.
        encima_de(padre)
        messagebox.showerror("No se pudo descargar", mensaje, parent=padre)
    except Exception:
        print("[descargas] %s" % mensaje)


def _avisar_exito(padre, ruta):
    """Confirmar dónde quedó el archivo y ofrecer abrir la carpeta."""
    try:
        from tkinter import messagebox
        encima_de(padre)
        messagebox.showinfo(
            "Listo",
            "Se guardó:\n%s\n\n%s" % (os.path.basename(ruta),
                                       os.path.dirname(ruta)),
            parent=padre)
    except Exception:
        print("[descargas] escrito: %s" % ruta)


def abrir_carpeta(ruta=None):
    """
    Abre la carpeta en el explorador de archivos.

    Devuelve True si se pudo, False si no. No es un error si no se puede: en un
    servidor sin escritorio no hay explorador que abrir y el archivo ya está
    escrito, así que solo se avisa por pantalla.
    """
    destino = ruta if ruta is not None else _carpeta(os.getcwd())
    if not os.path.isdir(destino):
        return False
    try:
        if sys.platform.startswith("darwin"):
            subprocess.Popen(["open", destino])
        elif os.name == "nt":
            os.startfile(destino)  # noqa: S606  (API propia de Windows)
        else:
            subprocess.Popen(["xdg-open", destino])
        return True
    except Exception as exc:
        print("[descargas] no se pudo abrir %s: %s" % (destino, exc))
        return False


def descargar_tabla(padre, encabezados, filas, etiqueta, cwd=None, aviso=True):
    """
    Ruta común de las descargas con tabla: preguntar, escribir, avisar.

    Devuelve la ruta escrita, o None si se canceló o no había filas. Centraliza
    el manejo de errores para que ninguna vista tenga que escribir el mismo
    try/except OSError alrededor de la llamada.
    """
    if not filas:
        return None
    pedido = preguntar_descarga(padre, etiqueta, cwd=cwd)
    if pedido is None:
        return None
    formato, nombre, sobrescribir = pedido
    try:
        ruta = exportar_tabla(encabezados, filas, etiqueta, cwd=cwd,
                              formato=formato, nombre=nombre,
                              sobrescribir=sobrescribir)
    except OSError as exc:
        _avisar_error(padre, "No se pudo escribir el archivo: %s" % exc)
        return None
    if ruta is None:
        return None
    if aviso:
        _avisar_exito(padre, ruta)
    return ruta


def descargar_texto(padre, lineas, etiqueta, cwd=None):
    """
    Igual que descargar_tabla, pero para el contenido de un informe.

    No pregunta el formato: el archivo va como TXT, que es el formato del
    informe. Ver exportar_lineas.
    """
    if not lineas:
        return None
    try:
        ruta = exportar_lineas(lineas, etiqueta, cwd=cwd)
    except OSError as exc:
        _avisar_error(padre, "No se pudo escribir el archivo: %s" % exc)
        return None
    if ruta is not None:
        _avisar_exito(padre, ruta)
    return ruta