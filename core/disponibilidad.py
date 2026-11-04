#!/usr/bin/env python3
"""
disponibilidad.py
=================
¿La estación tiene formas de onda en la ventana del evento?

El listado de «Sin arribos» dice qué estaciones del inventario no tienen
arrivals/picks asociados al origen preferido, pero no prueba que hayan grabado:
la base de metadatos de SeisComp no registra formas de onda. Este módulo
responde esa pregunta consultando, en orden:

1. el archivo **SDS** local (por defecto /mnt/sds/archive);
2. el **recordstream** de tiempo real configurado en el global.cfg de SeisComp
   (SeedLink/Arclink), que cubre las últimas horas/días que el SDS todavía no
   tiene.

Se usa `scart` (de SeisComp) en modo consulta, sin escribir nada:

    scart -d  --print-streams -n NET.STA.LOC.CHA -t t0~t1 <sds>
    scart -I <recordstream> --test --print-streams -n NET.STA.LOC.CHA -t t0~t1

La salida de `--print-streams` trae una línea por stream con inicio, fin,
registros, muestras y frecuencia; si no hay datos en la ventana, no aparece la
línea. El parser se queda con esas líneas.

La ausencia de datos en las dos fuentes NO prueba que la estación estuviera
caída: puede que el archivo no esté completo o que la retención no llegue a esa
fecha. Por eso la UI mantiene la actividad ±2 h como indicador indirecto de
respaldo.
"""

import os
import re
import shutil
import subprocess


# Semiancho de la ventana que se consulta alrededor del origen del evento.
VENTANA_MINUTOS = 10.0

# Tiempo máximo de una corrida de scart. Si el servidor de tiempo real no
# responde, se corta y se sigue con lo que haya.
TIMEOUT = 20.0

ESTADO_CON_DATOS = "CON_DATOS"
ESTADO_SIN_DATOS = "SIN_DATOS"
ESTADO_NO_CONSULTADO = "NO_CONSULTADO"

FUENTE_SDS = "SDS"
FUENTE_RECORDSTREAM = "RECORDSTREAM"

# Qué tan fuerte es la conclusión de que la estación estaba disponible:
# VERIFICADO es certeza (hay formas de onda); INDICIO es la deducción por
# actividad (picó otros eventos cerca); SIN_EVIDENCIA es haber mirado y no
# encontrar nada; NO_CONSULTADO es no haber mirado y no tener actividad.
EVIDENCIA_VERIFICADO = "VERIFICADO"
EVIDENCIA_INDICIO = "INDICIO"
EVIDENCIA_SIN_EVIDENCIA = "SIN_EVIDENCIA"
EVIDENCIA_NO_CONSULTADO = "NO_CONSULTADO"

# NET.STA.LOC.CHA: la localización puede venir vacía (NET.STA..CHA).
_RE_STREAM = re.compile(r"^[A-Za-z0-9]+\.[A-Za-z0-9]*\.[A-Za-z0-9]*\.[A-Za-z0-9]+$")
# Una línea de --print-streams:
# C.CCSP.18.HNE  2026-02-11T00:00:00.635Z  2026-02-11T00:01:00.92Z  30 12057 200.0
_RE_LINEA = re.compile(
    r"^(\S+)\s+(\S+)\s+(\S+)\s+(\d+)\s+(\d+)\s+(\S+)\s*$")


def raiz_sds():
    """Raíz del SDS local, configurable con RCS_SDS_ROOT."""
    return os.environ.get("RCS_SDS_ROOT") or "/mnt/sds/archive"


def ruta_scart():
    """Ruta de scart: RCS_SCART, SEISCOMP_ROOT/bin/scart o el PATH."""
    env = os.environ.get("RCS_SCART")
    if env:
        return env
    root = os.environ.get("SEISCOMP_ROOT")
    if root:
        candidato = os.path.join(root, "bin", "scart")
        if os.path.isfile(candidato):
            return candidato
    return shutil.which("scart")


def _global_cfg():
    """Ubica el global.cfg de SeisComp, igual que exporta_ventana_seiscomp."""
    candidatos = []
    root = os.environ.get("SEISCOMP_ROOT")
    if root:
        candidatos.append(os.path.join(root, "etc", "global.cfg"))
    candidatos.append(os.path.expanduser("~/seiscomp/etc/global.cfg"))
    for ruta in candidatos:
        if os.path.isfile(ruta):
            return ruta
    return None


def recordstream():
    """
    URL del recordstream de tiempo real: RCS_RECORDSTREAM o el global.cfg.

    El global.cfg lo declara como `recordstream = combined://...;...`. Si no
    está, se devuelve None y el respaldo de tiempo real simplemente no se usa.
    """
    env = os.environ.get("RCS_RECORDSTREAM")
    if env:
        return env
    ruta = _global_cfg()
    if ruta is None:
        return None
    try:
        with open(ruta, encoding="utf-8", errors="replace") as f:
            for linea in f:
                limpia = linea.split("#", 1)[0].strip()
                if limpia.lower().startswith("recordstream"):
                    _, _, valor = limpia.partition("=")
                    valor = valor.strip()
                    if valor:
                        return valor
    except OSError:
        return None
    return None


def _formatear_instante(instante):
    """UTC en el formato que entiende scart: 2026-02-11T00:00:00."""
    return instante.strftime("%Y-%m-%dT%H:%M:%S")


def _parsear_salida(texto):
    """
    {stream: {desde, hasta, records}} de la salida de --print-streams.

    Se ignoran las líneas de log («Info: skipping …», «Test mode …») y la
    cabecera; solo entran las que empiezan con un NET.STA.LOC.CHA válido.
    """
    encontrados = {}
    for linea in (texto or "").splitlines():
        partes = _RE_LINEA.match(linea.strip())
        if not partes:
            continue
        stream = partes.group(1)
        if not _RE_STREAM.match(stream):
            continue
        encontrados[stream] = {
            "desde": partes.group(2),
            "hasta": partes.group(3),
            "records": int(partes.group(4)),
        }
    return encontrados


def _correr(scart, modo, streams, desde, hasta, timeout):
    """
    Corre scart para 'streams' y devuelve (encontrados, consultados).

    'modo' es la lista de argumentos de la fuente: ['-d', <sds>] o
    ['-I', <recordstream>, '--test']. 'consultados' son los streams sobre los
    que la fuente efectivamente respondió (aunque no tuviera datos); si scart
    no existe, falla o se cuelga, queda vacío y no se afirma nada.
    """
    if not scart or not streams:
        return {}, []
    comando = [scart] + list(modo) + [
        "--print-streams", "-n", ",".join(streams),
        "-t", "%s~%s" % (_formatear_instante(desde),
                         _formatear_instante(hasta))]
    try:
        proceso = subprocess.run(
            comando, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            universal_newlines=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return {}, []
    encontrados = _parsear_salida(proceso.stderr)
    if proceso.returncode != 0:
        # Puede haber encontrado algunos streams y fallado en otros; se
        # conserva lo encontrado, pero no se afirma que el resto no tenga datos.
        return encontrados, []
    return encontrados, list(streams)


def _aplicar(resultado, encontrados, consultados, fuente):
    """Vuelca una corrida de scart en el resultado acumulado."""
    for stream, datos in encontrados.items():
        if stream not in resultado:
            continue
        resultado[stream].update({
            "status": ESTADO_CON_DATOS,
            "source": fuente,
            "desde": datos["desde"],
            "hasta": datos["hasta"],
            "records": datos["records"],
        })
    for stream in consultados:
        if stream in resultado and resultado[stream]["status"] != ESTADO_CON_DATOS:
            resultado[stream]["status"] = ESTADO_SIN_DATOS


def consultar(streams, desde, hasta, *, scart=None, sds=None,
              recordstream_url=None, timeout=TIMEOUT, al_progreso=None):
    """
    Consulta disponibilidad para una lista de streams en [desde, hasta].

    Devuelve {stream: {status, source, desde, hasta, records}} con un estado por
    stream: CON_DATOS, SIN_DATOS (alguna fuente respondió y no lo encontró) o
    NO_CONSULTADO (no se pudo consultar ninguna fuente).

    Prueba primero el SDS y, para lo que falte, el recordstream de tiempo real.

    'al_progreso' es un callback opcional que recibe un mensaje de texto con la
    fase en curso. Se llama desde el hilo que consulta, así que la interfaz debe
    limitarse a encolarlo (no tocar Tk desde aquí).
    """
    def _avisar(mensaje):
        if al_progreso is not None:
            try:
                al_progreso(mensaje)
            except Exception:
                pass

    streams = [s for s in dict.fromkeys(streams) if s]
    resultado = {
        stream: {"status": ESTADO_NO_CONSULTADO, "source": "", "desde": "",
                 "hasta": "", "records": None}
        for stream in streams
    }
    if not streams:
        return resultado

    scart = scart if scart is not None else ruta_scart()
    if not scart:
        _avisar("No hay scart disponible; no se pudo consultar.")
        return resultado

    consultado_algo = False
    raiz = sds if sds is not None else raiz_sds()
    if raiz and os.path.isdir(raiz):
        _avisar("Consultando el archivo SDS…")
        encontrados, consultados = _correr(
            scart, ["-d", raiz], streams, desde, hasta, timeout)
        _aplicar(resultado, encontrados, consultados, FUENTE_SDS)
        consultado_algo = True

    faltan = [s for s in streams
              if resultado[s]["status"] != ESTADO_CON_DATOS]
    url = (recordstream_url if recordstream_url is not None
           else recordstream())
    if faltan and url:
        _avisar("Buscando en el tiempo real…")
        encontrados, consultados = _correr(
            scart, ["-I", url, "--test"], faltan, desde, hasta, timeout)
        _aplicar(resultado, encontrados, consultados, FUENTE_RECORDSTREAM)
        consultado_algo = True
    if consultado_algo:
        _avisar("Listo.")
    else:
        _avisar("No hay fuentes de formas de onda disponibles.")
    return resultado


def specs_de_fila(fila):
    """
    Streams a consultar para una fila de sin arribos.

    Usa la lista completa `streams_vigentes_ids` (con la referencia primero);
    si la exportación es vieja y no la trae, cae al stream de referencia.
    """
    ids = str(fila.get("streams_vigentes_ids") or "").strip()
    specs = [s.strip() for s in ids.split(";") if s.strip()]
    if specs:
        return specs
    red = str(fila.get("red") or "").strip()
    estacion = str(fila.get("estacion") or "").strip()
    loc = str(fila.get("loc_ref") or "").strip()
    cha = str(fila.get("cha_ref") or "").strip()
    if red and estacion and cha:
        return ["%s.%s.%s.%s" % (red, estacion, loc, cha)]
    return []


def _actividad(fila):
    """actividad_ventana como número; 0 si falta o no es numérica."""
    try:
        return float(fila.get("actividad_ventana"))
    except (TypeError, ValueError):
        return 0.0


def estado_evidencia(fila):
    """
    Qué tan fuerte es la conclusión de que la estación estaba disponible.

    Orden: VERIFICADO (hay formas de onda) > INDICIO (picó otros eventos cerca)
    > SIN_EVIDENCIA (se miraron las ondas y no hay, ni actividad) >
    NO_CONSULTADO (no se miraron las ondas y no hay actividad).
    """
    if str(fila.get("waveform_status") or "") == ESTADO_CON_DATOS:
        return EVIDENCIA_VERIFICADO
    if _actividad(fila) > 0:
        return EVIDENCIA_INDICIO
    if str(fila.get("waveform_status") or "") == ESTADO_SIN_DATOS:
        return EVIDENCIA_SIN_EVIDENCIA
    return EVIDENCIA_NO_CONSULTADO


def texto_evidencia(fila):
    """Texto de la columna «Evidencia»: distingue certeza de deducción."""
    estado = estado_evidencia(fila)
    if estado == EVIDENCIA_VERIFICADO:
        fuente = str(fila.get("availability_source") or "")
        if fuente == FUENTE_SDS:
            return "Verificado (SDS)"
        if fuente == FUENTE_RECORDSTREAM:
            return "Verificado (tiempo real)"
        return "Verificado"
    if estado == EVIDENCIA_INDICIO:
        return "Indicio (actividad)"
    if estado == EVIDENCIA_SIN_EVIDENCIA:
        return "Sin evidencia"
    return "Sin consultar"


def aplicar_resultado(fila, resultado):
    """
    Vuelca el resultado de `consultar` en una fila de sin arribos.

    Escribe las columnas que ya estaban reservadas en el CSV
    (waveform_status, availability_source, cobertura_desde/hasta), actualiza
    `evidencia` y devuelve el estado final. Elige el primer stream con datos:
    como la referencia va primero, se prefiere; si no tiene, se usan los demás
    vigentes.
    """
    specs = specs_de_fila(fila)
    elegido = None
    for spec in specs:
        datos = resultado.get(spec)
        if datos and datos.get("status") == ESTADO_CON_DATOS:
            elegido = datos
            break
    if elegido is not None:
        fila["waveform_status"] = ESTADO_CON_DATOS
        fila["availability_source"] = elegido.get("source", "")
        fila["cobertura_desde"] = elegido.get("desde", "")
        fila["cobertura_hasta"] = elegido.get("hasta", "")
    else:
        if any(resultado.get(s, {}).get("status") == ESTADO_SIN_DATOS
               for s in specs):
            fila["waveform_status"] = ESTADO_SIN_DATOS
        else:
            fila["waveform_status"] = ESTADO_NO_CONSULTADO
        fila["availability_source"] = ""
        fila["cobertura_desde"] = ""
        fila["cobertura_hasta"] = ""
    fila["evidencia"] = estado_evidencia(fila)
    return fila["waveform_status"]


def texto_formas_onda(fila):
    """Texto corto para la columna «Formas de onda» de la interfaz."""
    estado = str(fila.get("waveform_status") or "")
    fuente = str(fila.get("availability_source") or "")
    if estado == ESTADO_CON_DATOS:
        if fuente == FUENTE_SDS:
            return "SDS"
        if fuente == FUENTE_RECORDSTREAM:
            return "Tiempo real"
        return "Con datos"
    if estado == ESTADO_SIN_DATOS:
        return "Sin datos"
    return ""
