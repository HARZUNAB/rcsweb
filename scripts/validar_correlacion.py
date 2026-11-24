"""Validación del prototipo de señal en estaciones sin arribos.

Se ejecuta dentro del contenedor ``web`` para poder leer ``/workspace`` y
llamar al servicio ``disponibilidad``. No modifica la app ni el workspace.

Ejemplo::

    docker cp scripts/validar_correlacion.py rcsweb-web:/tmp/
    docker compose exec -T web python /tmp/validar_correlacion.py \
        --job 9d461a97-94c7-46ac-8242-041fe6f04c37 \
        --salida /tmp/validacion_correlacion.json
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import requests

ESTADOS_SENAL = {"podria_picarse", "senal_detectada"}


@dataclass
class Evento:
    id: str
    lat: float
    lon: float
    prof: float
    mag: float
    instante: datetime
    picks: list[dict]
    candidatas: list[dict]


def leer_jsonl(ruta: Path) -> list[dict]:
    if not ruta.is_file():
        return []
    salida = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if not linea.strip():
            continue
        try:
            salida.append(json.loads(linea))
        except ValueError:
            continue
    return salida


def distancia_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = (
        math.sin(dp / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    )
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(h)))


def es_vertical(stream: str) -> bool:
    return stream.split(".")[-1].endswith("Z")


def iso(instante: datetime) -> str:
    return instante.replace(microsecond=0).isoformat()


def banda_lat(lat: float) -> str:
    if lat > -25:
        return "norte"
    if lat > -35:
        return "centro"
    return "sur"


def banda_prof(prof: float) -> str:
    if prof > 100:
        return "profundo"
    if prof >= 70:
        return "intermedio"
    if prof >= 20:
        return "somero"
    return "muy_somero"


def streams_verticales(fila: dict) -> list[str]:
    return [
        stream
        for stream in str(fila.get("stream_ids") or "").split(";")
        if stream and es_vertical(stream)
    ]


def cargar_eventos(
    workspace: Path, source: str, radio_km: float
) -> dict[str, Evento]:
    base = workspace / "catalogo" / source
    eventos = {e["event_id"]: e for e in leer_jsonl(base / "eventos.jsonl")}
    picks: dict[str, list[dict]] = defaultdict(list)
    for arribo in leer_jsonl(base / "arribos.jsonl"):
        if str(arribo.get("phase", "")).upper() != "P":
            continue
        if arribo.get("station_latitude") is None:
            continue
        picks[arribo.get("event_id")].append(arribo)
    candidatas: dict[str, list[dict]] = defaultdict(list)
    for fila in leer_jsonl(base / "estaciones_sin_arribos.jsonl"):
        candidatas[fila.get("event_id")].append(fila)
    salida = {}
    for eid, fila in eventos.items():
        if not picks[eid] or not candidatas[eid]:
            continue
        lat = fila.get("latitude")
        lon = fila.get("longitude")
        prof = fila.get("depth_km")
        if lat is None or lon is None or prof is None:
            continue
        instante = datetime.fromisoformat(fila["event_time"])
        verticales = [
            fila_cand
            for fila_cand in candidatas[eid]
            if streams_verticales(fila_cand)
            and fila_cand.get("station_latitude") is not None
            and fila_cand.get("station_longitude") is not None
            and distancia_km(
                lat,
                lon,
                fila_cand["station_latitude"],
                fila_cand["station_longitude"],
            )
            <= radio_km
        ]
        if len(verticales) < 2:
            continue
        salida[eid] = Evento(
            id=eid,
            lat=float(lat),
            lon=float(lon),
            prof=float(prof),
            mag=float(fila.get("magnitude") or 0.0),
            instante=instante,
            picks=picks[eid],
            candidatas=verticales,
        )
    return salida


def elegir_eventos(
    eventos: dict[str, Evento], por_estrato: int, estrategia: str = "picks"
) -> list[Evento]:
    grupos: dict[tuple[str, str], list[Evento]] = defaultdict(list)
    for evento in eventos.values():
        if len(evento.picks) < 3:
            continue
        if estrategia == "cobertura" and len(evento.picks) > 6:
            continue
        grupos[(banda_lat(evento.lat), banda_prof(evento.prof))].append(
            evento
        )
    elegidos = []
    for clave in sorted(grupos):
        if estrategia == "cobertura":
            grupo = sorted(
                grupos[clave],
                key=lambda evento: (
                    len(evento.picks),
                    -len(evento.candidatas),
                    -evento.mag,
                ),
            )
        else:
            grupo = sorted(
                grupos[clave],
                key=lambda evento: (
                    len(evento.picks),
                    len(evento.candidatas),
                    evento.mag,
                ),
                reverse=True,
            )
        elegidos.extend(grupo[:por_estrato])
    return elegidos


def construir_payload(
    evento: Evento,
    referencia: dict,
    max_candidatas: int,
    banda: tuple[float, float],
    persistencia: float,
    streams_filtro: set[str] | None,
) -> dict | None:
    picks = []
    for arribo in evento.picks:
        lat = arribo.get("station_latitude")
        lon = arribo.get("station_longitude")
        if lat is None or lon is None:
            continue
        distancia = distancia_km(evento.lat, evento.lon, lat, lon)
        segundos = (
            datetime.fromisoformat(arribo["pick_time"]) - evento.instante
        ).total_seconds()
        if segundos <= 0:
            continue
        picks.append(
            {
                "dist": distancia,
                "seg": segundos,
                "arribo": arribo,
                "stream": "{}.{}.{}.{}".format(
                    arribo.get("network", ""),
                    arribo.get("station", ""),
                    arribo.get("location", ""),
                    arribo.get("channel", ""),
                ),
            }
        )
    if len(picks) < 3:
        return None
    xs = np.array([p["dist"] for p in picks])
    ys = np.array([p["seg"] for p in picks])
    pendiente, intercepto = np.polyfit(xs, ys, 1)
    verticales = [p for p in picks if es_vertical(p["stream"])]
    if not verticales:
        verticales = picks
    verticales.sort(
        key=lambda p: math.hypot(p["dist"], evento.prof)
    )
    controles = [
        p for p in verticales if p["stream"] != referencia["stream"]
    ][:5]
    candidatas = []
    for fila in evento.candidatas:
        streams = streams_verticales(fila)
        if not streams:
            continue
        if streams_filtro and streams[0] not in streams_filtro:
            continue
        distancia = distancia_km(
            evento.lat,
            evento.lon,
            fila["station_latitude"],
            fila["station_longitude"],
        )
        esperado = evento.instante + timedelta(
            seconds=float(intercepto + pendiente * distancia)
        )
        candidatas.append(
            {
                "stream": streams[0],
                "station": "AVAIL {}".format(fila.get("station", "")),
                "distance_km": round(distancia, 1),
                "expected_time": iso(esperado),
            }
        )
        if len(candidatas) >= max_candidatas:
            break
    if streams_filtro and not candidatas:
        return None
    negativas = []
    for candidata in candidatas:
        copia = dict(candidata)
        copia["station"] = candidata["station"] + " NEG"
        copia["expected_time"] = iso(
            datetime.fromisoformat(candidata["expected_time"])
            + timedelta(seconds=60)
        )
        negativas.append(copia)
    return {
        "event_time": iso(evento.instante),
        "reference": {
            "stream": referencia["stream"],
            "pick_time": referencia["arribo"]["pick_time"],
            "distance_km": round(referencia["dist"], 1),
        },
        "candidates": [
            {
                "stream": p["stream"],
                "station": "CTRL {}".format(p["arribo"].get("station", "")),
                "distance_km": round(p["dist"], 1),
                "expected_time": iso(
                    evento.instante + timedelta(seconds=p["seg"])
                ),
            }
            for p in controles
        ]
        + candidatas
        + negativas,
        "fs": 100.0,
        "band": [banda[0], banda[1]],
        "template_before_s": 1.0,
        "template_after_s": 7.0,
        "candidate_before_s": 10.0,
        "candidate_after_s": 30.0,
        "max_lag_s": 5.0,
        "sta_s": 0.5,
        "lta_s": 10.0,
        "sta_lta_before_s": 1.5,
        "sta_lta_after_s": 4.0,
        "sta_lta_persistencia_s": persistencia,
        "cc_min": 0.5,
        "sta_lta_min": 3.0,
    }


def grupo_de(estacion: str) -> str:
    if estacion.endswith(" NEG"):
        return "NEG"
    if estacion.startswith("CTRL"):
        return "CTRL"
    return "AVAIL"


def resumir(respuesta: dict) -> dict:
    grupos = {"CTRL": [], "AVAIL": [], "NEG": []}
    for item in respuesta.get("resultados", []):
        grupos[grupo_de(str(item.get("station", "")))].append(item)
    salida = {}
    for clave, items in grupos.items():
        slt = [
            item["sta_lta_max"]
            for item in items
            if item.get("sta_lta_max") is not None
        ]
        cc = [
            item["cc_max"]
            for item in items
            if item.get("cc_max") is not None
        ]
        salida[clave] = {
            "n": len(items),
            "slt_med": statistics.median(slt) if slt else None,
            "cc_med": statistics.median(cc) if cc else None,
            "senal": sum(
                1
                for item in items
                if item.get("clasificacion") in ESTADOS_SENAL
            ),
            "sin_datos": sum(
                1
                for item in items
                if item.get("clasificacion") == "sin_datos"
            ),
        }
    return salida


def consultar(url: str, token: str, payload: dict) -> dict:
    respuesta = requests.post(
        url.rstrip("/") + "/correlacionar",
        json=payload,
        headers={"X-RCS-Token": token},
        timeout=300,
    )
    respuesta.raise_for_status()
    return respuesta.json()


def cargar_indicios(workspace: Path, source: str) -> dict[str, dict]:
    ruta = (
        workspace
        / "resultados"
        / "indicios"
        / f"indicios_{source}.csv"
    )
    if not ruta.is_file():
        return {}
    with ruta.open(encoding="utf-8", newline="") as archivo:
        return {
            fila.get("evento", ""): fila
            for fila in csv.DictReader(archivo)
        }


def combinar(
    resultados: list[dict],
    indice: dict | None,
    usadas_fallback: int = 0,
) -> dict:
    """Aplica la regla de >=2 bandas y resume el evento."""
    estaciones: dict[str, dict] = {}
    for resultado in resultados:
        banda = resultado["banda"]
        etiqueta = f"{banda[0]:g}-{banda[1]:g}"
        for item in resultado["respuesta"].get("resultados", []):
            estacion = str(item.get("station", ""))
            if not estacion.startswith("AVAIL") or estacion.endswith(" NEG"):
                continue
            stream = str(item.get("stream") or estacion)
            datos = estaciones.setdefault(
                stream,
                {
                    "station": estacion.replace("AVAIL ", ""),
                    "stream": stream,
                    "bandas": [],
                    "max_slt": 0.0,
                    "max_racha": 0.0,
                    "max_cc": None,
                    "con_datos": False,
                },
            )
            if item.get("status") == "CON_DATOS":
                datos["con_datos"] = True
            slt = item.get("sta_lta_max")
            if slt is not None:
                datos["max_slt"] = max(datos["max_slt"], float(slt))
            racha = item.get("sta_lta_racha_s")
            if racha is not None:
                datos["max_racha"] = max(datos["max_racha"], float(racha))
            cc = item.get("cc_max")
            if cc is not None:
                if datos["max_cc"] is None or cc > datos["max_cc"]:
                    datos["max_cc"] = float(cc)
            if (
                item.get("clasificacion") in ESTADOS_SENAL
                and (item.get("sta_lta_racha_s") or 0.0) >= 0.3
            ):
                if etiqueta not in datos["bandas"]:
                    datos["bandas"].append(etiqueta)
    disponibles = [
        datos for datos in estaciones.values() if datos["con_datos"]
    ]
    con_senal = [
        datos for datos in disponibles if len(datos["bandas"]) >= 2
    ]
    usadas = 0
    contexto = ""
    sospechoso = ""
    prioridad = ""
    if indice:
        try:
            usadas = int(float(indice.get("n_usadas") or 0))
        except ValueError:
            usadas = 0
        contexto = str(indice.get("contexto") or "")
        sospechoso = str(indice.get("sospechoso") or "")
        prioridad = str(indice.get("prioridad") or "")
    if usadas <= 0:
        usadas = usadas_fallback
    cobertura_estimada = not bool(contexto)
    if cobertura_estimada:
        contexto = "débil" if usadas < 5 else "suficiente (estimada)"
    ratio = (
        len(con_senal) / len(disponibles) if disponibles else 0.0
    )
    cobertura_debil = "débil" in contexto.lower()
    antecedente = bool(
        len(con_senal) >= 3
        and (
            ratio >= 0.3
            or (usadas and len(con_senal) >= usadas)
        )
        and (cobertura_debil or sospechoso == "Sí")
    )
    return {
        "disponibles": len(disponibles),
        "con_senal": len(con_senal),
        "ratio": round(ratio, 3),
        "usadas": usadas,
        "cobertura": contexto,
        "cobertura_estimada": cobertura_estimada,
        "sospechoso": sospechoso,
        "prioridad": prioridad,
        "antecedente": antecedente,
        "estaciones": sorted(
            disponibles,
            key=lambda item: (
                -len(item["bandas"]),
                -item["max_slt"],
                item["station"],
            ),
        ),
    }


def analizar_evento(
    evento: Evento,
    url: str,
    token: str,
    max_candidatas: int,
    bandas: list[tuple[float, float]],
    persistencia: float,
    streams_filtro: set[str] | None,
) -> list[dict]:
    candidatos_ref = []
    for arribo in evento.picks:
        if not es_vertical(
            "{}.{}.{}.{}".format(
                arribo.get("network", ""),
                arribo.get("station", ""),
                arribo.get("location", ""),
                arribo.get("channel", ""),
            )
        ):
            continue
        lat = arribo.get("station_latitude")
        lon = arribo.get("station_longitude")
        if lat is None or lon is None:
            continue
        distancia = distancia_km(evento.lat, evento.lon, lat, lon)
        segundos = (
            datetime.fromisoformat(arribo["pick_time"]) - evento.instante
        ).total_seconds()
        if segundos <= 0:
            continue
        candidatos_ref.append(
            {
                "dist": distancia,
                "seg": segundos,
                "arribo": arribo,
                "stream": "{}.{}.{}.{}".format(
                    arribo.get("network", ""),
                    arribo.get("station", ""),
                    arribo.get("location", ""),
                    arribo.get("channel", ""),
                ),
            }
        )
    candidatos_ref.sort(
        key=lambda p: math.hypot(p["dist"], evento.prof)
    )
    salida = []
    for banda in bandas:
        for referencia in candidatos_ref[:3]:
            payload = construir_payload(
                evento,
                referencia,
                max_candidatas,
                banda,
                persistencia,
                streams_filtro,
            )
            if payload is None:
                return salida
            try:
                respuesta = consultar(url, token, payload)
            except requests.HTTPError as exc:
                print(
                    "  banda {:.1f}-{:.1f} ref {} falló: {}".format(
                        banda[0],
                        banda[1],
                        referencia["arribo"].get("station"),
                        exc,
                    )
                )
                continue
            salida.append(
                {
                    "banda": banda,
                    "referencia": referencia,
                    "respuesta": respuesta,
                }
            )
            break
    return salida


def parse_bandas(texto: str) -> list[tuple[float, float]]:
    salida = []
    for parte in texto.split(","):
        if not parte.strip():
            continue
        try:
            fmin, fmax = parte.split("-", 1)
            salida.append((float(fmin), float(fmax)))
        except ValueError as exc:
            raise SystemExit(f"Banda inválida: {parte!r}") from exc
    if not salida:
        raise SystemExit("No hay bandas para probar.")
    return salida


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--job",
        default="9d461a97-94c7-46ac-8242-041fe6f04c37",
    )
    parser.add_argument("--source", default="seiscomp")
    parser.add_argument("--radio-km", type=float, default=250.0)
    parser.add_argument("--por-estrato", type=int, default=1)
    parser.add_argument(
        "--estrategia",
        choices=("picks", "cobertura"),
        default="picks",
    )
    parser.add_argument("--max-candidatas", type=int, default=10)
    parser.add_argument(
        "--bandas", default="1-10", help="Ej: 0.7-2,1-5,1-10,2-15"
    )
    parser.add_argument("--persistencia", type=float, default=0.0)
    parser.add_argument(
        "--streams",
        default="",
        help="Filtra candidatas por stream, separadas por coma",
    )
    parser.add_argument("--detalle", action="store_true")
    parser.add_argument(
        "--url",
        default=os.environ.get(
            "RCS_DISPONIBILIDAD_URL", "http://disponibilidad:8010"
        ),
    )
    parser.add_argument(
        "--token", default=os.environ.get("RCS_DISPONIBILIDAD_TOKEN", "")
    )
    parser.add_argument("--salida", default="")
    parser.add_argument("--eventos", default="")
    args = parser.parse_args()
    bandas = parse_bandas(args.bandas)
    streams_filtro = {
        stream.strip()
        for stream in args.streams.split(",")
        if stream.strip()
    } or None
    workspace = Path("/workspace") / args.job
    eventos = cargar_eventos(workspace, args.source, args.radio_km)
    indicios = cargar_indicios(workspace, args.source)
    if args.eventos:
        pedidos = [e.strip() for e in args.eventos.split(",") if e.strip()]
        elegidos = [eventos[e] for e in pedidos if e in eventos]
    else:
        elegidos = elegir_eventos(
            eventos, args.por_estrato, args.estrategia
        )
    print(
        f"job={args.job} eventos={len(elegidos)} "
        f"radio={args.radio_km:.0f} km "
        f"max_candidatas={args.max_candidatas} "
        f"bandas={bandas} persistencia={args.persistencia}s"
    )
    filas = []
    for evento in elegidos:
        print(
            f"\n{evento.id} {iso(evento.instante)} M{evento.mag:.1f} "
            f"prof={evento.prof:.1f} km "
            f"{banda_lat(evento.lat)}/{banda_prof(evento.prof)}"
        )
        resultados = analizar_evento(
            evento,
            args.url,
            args.token,
            args.max_candidatas,
            bandas,
            args.persistencia,
            streams_filtro,
        )
        if not resultados:
            print("  sin referencia o candidatas con datos")
            continue
        fila = {
            "evento": evento.id,
            "instante": iso(evento.instante),
            "lat": evento.lat,
            "prof": evento.prof,
            "mag": evento.mag,
            "estrato": f"{banda_lat(evento.lat)}/"
            f"{banda_prof(evento.prof)}",
            "bandas": [],
        }
        for resultado in resultados:
            respuesta = resultado["respuesta"]
            resumen = resumir(respuesta)
            banda = resultado["banda"]
            ref = resultado["referencia"]["arribo"].get("station")
            print(
                "  banda {:.1f}-{:.1f} Hz ref={} ref_slt={} resumen={}".format(
                    banda[0],
                    banda[1],
                    ref,
                    respuesta.get("referencia", {}).get("sta_lta_max"),
                    respuesta.get("resumen", {}),
                )
            )
            for clave in ("CTRL", "AVAIL", "NEG"):
                grupo = resumen[clave]
                slt = (
                    "-"
                    if grupo["slt_med"] is None
                    else str(round(grupo["slt_med"], 2))
                )
                cc = (
                    "-"
                    if grupo["cc_med"] is None
                    else str(round(grupo["cc_med"], 2))
                )
                print(
                    f"    {clave:<5s} n={grupo['n']:<3} "
                    f"slt_med={slt:<8} cc_med={cc:<8} "
                    f"senal={grupo['senal']:<3} "
                    f"sin_datos={grupo['sin_datos']}"
                )
            if args.detalle:
                for item in respuesta.get("resultados", []):
                    estacion = str(item.get("station", ""))
                    if not estacion.startswith("AVAIL"):
                        continue
                    slt = (
                        round(item["sta_lta_max"], 2)
                        if item.get("sta_lta_max") is not None
                        else "-"
                    )
                    racha = (
                        round(item.get("sta_lta_racha_s", 0.0), 2)
                        if item.get("sta_lta_racha_s") is not None
                        else "-"
                    )
                    cc = (
                        round(item["cc_max"], 2)
                        if item.get("cc_max") is not None
                        else "-"
                    )
                    print(
                        f"      {estacion:<20s} "
                        f"{str(item.get('stream')):<20s} "
                        f"{str(item.get('status')):<8s} "
                        f"slt={str(slt):<6s} racha={str(racha):<5s} "
                        f"cc={str(cc):<6s} "
                        f"{item.get('clasificacion')}"
                    )
            fila["bandas"].append(
                {
                    "banda": banda,
                    "referencia": ref,
                    "resumen": resumen,
                    "resumen_servicio": respuesta.get("resumen"),
                    "resultados": respuesta.get("resultados"),
                }
            )
        combinado = combinar(
            resultados,
            indicios.get(evento.id),
            len(
                {
                    (
                        pick.get("network"),
                        pick.get("station"),
                    )
                    for pick in evento.picks
                }
            ),
        )
        print(
            "  combinado: disponibles={} con_senal={} ({}%) "
            "usadas={} cobertura={} sospechoso={} antecedente={}".format(
                combinado["disponibles"],
                combinado["con_senal"],
                round(combinado["ratio"] * 100, 0),
                combinado["usadas"],
                combinado["cobertura"] or "-",
                combinado["sospechoso"] or "-",
                "Sí" if combinado["antecedente"] else "No",
            )
        )
        fila["combinado"] = combinado
        filas.append(fila)
    if args.salida:
        Path(args.salida).write_text(
            json.dumps(filas, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nJSON: {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
