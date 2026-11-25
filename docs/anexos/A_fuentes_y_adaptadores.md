## Anexo A. Fuentes y adaptadores

Este anexo describe **de dónde sale cada dato**, cómo se transporta, qué
archivos intermedios produce y qué adaptador lo lleva al catálogo canónico.
El Anexo D documenta los parámetros; el Anexo B, las consultas y tablas; el
Anexo C, la normalización campo a campo.

La fuente de verdad es el código y el manifiesto
`app/domain/catalogs/sources.json`. Si este anexo y el código difieren, manda
el código; las pruebas de CI avisan cuando un adaptador no está documentado.

### A.0 Alcance

| Fuente | Rol | ¿Base de datos? | Transporte |
|---|---|---|---|
| Eventquery | Referencia pública | No | SSH/SCP + `eventquery2` |
| SeisComp | Local | Sí, PostgreSQL de solo lectura | SQL + exportación |
| Seisan | Local | **No** | SSH/SCP + programa `select` |
| Central | Local derivada | Sí, PostgreSQL de solo lectura | SQL directo |

Convenciones de rutas dentro de `workspace/<job_id>/`:

| Ruta | Contenido |
|---|---|
| `inputs/` | Archivos subidos o descargados, tal como llegaron |
| `files/` | Archivos de una solicitud SSH antes de canonizar |
| `datos/` | CSV normalizados y caché del pipeline |
| `trabajo/` | Archivos intermedios que se borran solos |
| `informes/` | Reportes de texto |
| `catalogo/<fuente>/` | Catálogo canónico JSONL |
| `resultados/` | Tablas y artefactos que lee la app |

### A.1 Matriz general

| Fuente | Transporte | Origen | Intermedio | Canónico | Adaptador |
|---|---|---|---|---|---|
| Eventquery | SSH/SCP + `eventquery2` | CSV remoto | `datos/new_2_*.csv` | `eventos.jsonl` | `adapters/eventquery.py` |
| SeisComp | PostgreSQL solo lectura | SQL de ventana | `datos/seiscomp_parametros.csv`, `*_fases.csv`, `*_no_picadas.csv` | `eventos.jsonl`, `arribos.jsonl`, `estaciones_sin_arribos.jsonl` | `adapters/seiscomp.py` |
| Seisan | SSH/SCP + `select` | `select.out` | `newcollect.txt`, `datos/salida_collect.csv`, `datos/seisan_*_fases.csv` | `eventos.jsonl`, `arribos.jsonl` | `adapters/seisan.py` |
| Central | PostgreSQL solo lectura | SQL directo | `datos/central_*_parametros.csv`, `*_fases.csv`, `*_tensores.csv` | `eventos.jsonl`, `arribos.jsonl`, `tensores.jsonl` | `adapters/central.py` |

Cada adaptador declara:

- `formato`: `referencia`, `local_export`, `local_select` o `local_db`;
- `tipo`: `reference`, `export`, `select` o `db`;
- `capacidades`: eventos, orígenes, magnitudes, arribos, inventario,
  disponibilidad de ondas, excluidos o tensores;
- `pasos()`: scripts y acciones que ejecuta el pipeline;
- `catalogo()`: archivo plano que se convierte en `eventos.jsonl`;
- `extensiones()`: arribos, estaciones sin arribos o tensores.

### A.2 Eventquery

Es la fuente de **referencia** para comparar publicaciones. No es una fuente
local ni aporta arribos.

```text
Solicitud o carga manual
  → core/traer_catalogos.py:traer_eventquery
      ssh host: type -P eventquery2
      eventquery2 --start-time <ISO> --end-time <ISO> <salida.csv>
      scp host:tmp/<salida.csv> → workspace/
  → adapters/eventquery.py:pasos
      proc_query_harz_2.py → datos/new_2_<archivo>
  → eventos.jsonl
```

- Binario remoto: `eventquery2`, no `eventquery` (la versión vieja duplicaba
  soluciones).
- El archivo descargado se guarda como `eventquery_<inicio>_<fin>.csv`.
- Si el archivo local ya tiene filas, se reutiliza; `forzar=True` lo rebaja.
- Validador: `eventquery`.
- Capacidades: eventos, orígenes, magnitudes y percibidos.
- La app no compara por el texto `eventquery`: usa el rol `reference` del
  manifiesto.

Errores frecuentes:

- `eventquery2` no está en el PATH del login remoto;
- el CSV llega vacío o sin encabezado;
- el período no tiene eventos publicados.

### A.3 SeisComp

SeisComp **sí** es una base de datos PostgreSQL, consultada en modo de solo
lectura. La app no consulta la base desde el proceso web: lanza una exportación
en el core.

```text
app/services/seiscomp.py:exportar_ventana
  → core/exporta_ventana_seiscomp.py
      CONSULTA_SQL           → eventos y soluciones preferidas
      CONSULTA_FASES_SQL     → llegadas de la solución preferida
      CONSULTA_INVENTARIO_SQL→ estaciones y épocas
      CONSULTA_ACTIVIDAD_SQL → actividad reciente
      CONSULTA_COBERTURA_SQL → cobertura del origen
      CONSULTA_TAMANO_SQL    → tamaño de la ventana
      CONSULTA_ESTIMACION_NO_PICADAS_SQL
  → seiscomp_<inicio>_<fin>.csv
  → adapters/seiscomp.py:pasos
      seiscomp_a_parametros.py → datos/seiscomp_parametros.csv
  → eventos.jsonl, arribos.jsonl, estaciones_sin_arribos.jsonl
```

- Archivo principal: `seiscomp_<inicio>_<fin>.csv`.
- Catálogo plano: `datos/seiscomp_parametros.csv`.
- Extensiones: `<salida>_fases.csv` y `<salida>_no_picadas.csv`, junto a la
  exportación; en solicitudes SSH se copian al workspace.
- Validador: `seiscomp`.
- Capacidades: eventos, orígenes, magnitudes, arribos, inventario y
  disponibilidad de ondas.
- El detalle de las consultas y tablas está en el Anexo B.2.

#### A.3.1 Catálogo canónico extendido

El catálogo canónico de SeisComp guarda, además de los campos base, cuatro
bloques opcionales:

```text
origin_quality
origin_uncertainty
origin_metadata
magnitude_metadata
```

Cada bloque incluye `source`, `derived` y `derived_fields`. En esta etapa
SeisComp, Central y Seisan los llenan. En Seisan, RMS y GAP salen del
encabezado de `select.out`; ERH/ERZ se mapean a incertidumbre horizontal y de
profundidad. `derived_fields` lista los campos calculados cuando un bloque
mezcla datos directos y derivados.

El flujo es:

```text
CONSULTA_SQL
  → seiscomp_<inicio>_<fin>.csv   (columnas extendidas)
  → seiscomp_a_parametros.py
  → datos/seiscomp_parametros.csv (base + columnas extendidas)
  → canonical.py
  → eventos.jsonl                 (bloques origin_quality, etc.)
```

- Esquema canónico: **1.3**.
- `origin_time_us` está en microsegundos.
- Las distancias de `origin_quality` están en **km**.
- El CSV crudo conserva `minimum_distance_deg`, `maximum_distance_deg` y
  `median_distance_deg` en grados, como los entrega SeisComp.
- El bloque `raw` del evento conserva la fila normalizada completa.

#### A.3.2 Descarga del catálogo completo desde Catálogos

La descarga vive en la página **Catálogos**, no en el detalle del trabajo.
Para una fuente ya seleccionada hay tres opciones:

| Opción | Contenido | Arribos | Mapas |
|---|---|---|---|
| **Descargar CSV** | Tabla de eventos filtrada, como la vista del catálogo | No | No |
| **Descargar ZIP** | Tabla de eventos + mapas de planta y perfiles | No | Sí |
| **Descargar catálogo completo** | Eventos + arribos + resumen por estación + LEEME | Sí | No |

El catálogo completo se descarga como:

```text
catalogo_completo_<fuente>_<inicio>_<fin>.zip
  eventos.csv
  arribos.csv
  estaciones_resumen.csv
  LEEME.txt
```

- `eventos.csv`: eventos con los bloques aplanados.
- `arribos.csv`: los arribos **de los eventos filtrados**.
- `estaciones_resumen.csv`: RMS, conteos, distancias y azimut por estación.
  Se calcula al exportar y siempre lleva `derived=true`.
- `LEEME.txt`: unidades, procedencia, filtros aplicados y versión del esquema.

En `arribos.csv`, `distance_km` conserva el valor nativo de la fuente y
`distance_km_calc` es la distancia en km calculada desde coordenadas.

La descarga respeta los **filtros actuales** de la página. Para bajar todo el
catálogo, se limpian los filtros. En la página se muestra el número de eventos
y la nota correspondiente.

Solo está disponible para **admin/supervisor**, con `catalogos.ver` y
`trabajos.descargar`. Se controla con `RCS_CATALOGO_COMPLETO_ACTIVO` (activa por
defecto). Si se pone en `0`, el botón desaparece y la ruta responde 404. El
canónico sigue guardando los bloques extendidos aunque la exportación esté
desactivada.

Errores frecuentes:

- base o credenciales no configuradas;
- rol sin `SELECT`;
- ventana sin eventos;
- exportación sin fases o sin inventario.

### A.4 Seisan: adquisición remota, no base de datos

Seisan **no es una base de datos**: no tiene tablas ni SQL consultable. Los
datos se obtienen de un servidor remoto con el programa `select`, que produce
`select.out`; luego dos scripts locales lo normalizan y el adaptador lo lleva
al catálogo canónico.

Esta es la diferencia principal con SeisComp y Central y conviene tenerla
presente al revisar la trazabilidad.

#### A.4.1 Servidor y acceso

- Host y usuario: `CATALOGOS_SSH_HOST` y `CATALOGOS_SSH_USER`.
- Valores por defecto en desarrollo: `10.54.217.9` y `sysopr`.
- SSH con `StrictHostKeyChecking=accept-new`.
- La contraseña se entrega con `SSH_ASKPASS`; nunca se pasa por la línea de
  comandos ni queda en el listado de procesos.
- El shell de login debe cargar el entorno de Seisan: `select` se busca con
  `type -P select`.

#### A.4.2 `select.inp` y el programa `select`

La plantilla vive en:

```text
core_data/plantillas/select.inp
```

La app copia la plantilla a `trabajo/select.inp` y reemplaza **solo** las
líneas de tiempo:

```text
Start time: AAAAMMDDHHMMSS
End time:   AAAAMMDDHHMMSS
```

La plantilla tiene campos de longitud fija y 65 bytes NUL; se edita en bytes
para no perderlos. Si una etiqueta no aparece exactamente una vez, el proceso
falla en vez de generar un `.inp` a medias.

`select` es una palabra reservada de bash. Por eso no se invoca como
`bash -lc 'select ...'`: se resuelve con `type -P` y se ejecuta por ruta
absoluta.

#### A.4.3 Ejecución remota y descarga

```text
mkdir -p tmp
scp select.inp → host:tmp/select.inp
ssh: cd tmp && $(type -P select) select.inp \
     && mv -f select.out select_<inicio>_<fin>.out
scp host:tmp/select_<inicio>_<fin>.out → workspace/
```

El archivo local se llama `select_<inicio>_<fin>.out`. En solicitudes SSH se
guarda como `files/seisan__select.out` y luego se copia a `inputs/`.

#### A.4.4 Reutilización y re-exportación

- Si `select_<inicio>_<fin>.out` existe y tiene eventos, no se vuelve a bajar.
- `forzar=True` se usa al re-exportar: regenera el `.inp`, sube, ejecuta y
  rebaja aunque el archivo exista.
- `select_tiene_eventos()` busca una cabecera de evento: cuatro dígitos de año
  al inicio de la línea, sin letras. No valida el evento completo.

#### A.4.5 Estructura de `select.out`

- Codificación **Latin-1**.
- Cabecera de evento en dos formas conocidas:

```text
2025  326 0024 19.2
2026 11 1  019 52.0
```

- Líneas `ID:AAAAMMDDHHMMSS` y `OP:usuario`.
- Líneas de fase, bloques `ACTION` y eventos excluidos.
- La hora del encabezado manda sobre la del `ID`.
- `OP` con `TASK`, `NONE` o `NULL` se normaliza a vacío.
- Las fases se leen por bloques; un bloque sin fases no genera arribos.

#### A.4.6 `revisaselect.py`

```text
select.out
  → trabajo/newcollect.txt
  → trabajo/excluidostmp1.txt
  → informes/excluidos.txt
```

Reacomoda la fecha y hora, separa día y mes y deja en `excluidos` los eventos
que no cumplen la estructura esperada.

#### A.4.7 `revisacollect.py`

```text
trabajo/newcollect.txt
  → datos/salida_collect.csv
     Fecha_Hora, Latitud, Longitud, Prof., Mag., Tipo_mag., Analista
```

Ajusta:

- días y meses de uno o dos dígitos;
- profundidades de tres o más dígitos, separando longitud y profundidad;
- segundos `60`, pasando al minuto siguiente;
- nombres de analista y archivos auxiliares.

El resultado es el catálogo plano que el adaptador convierte en
`eventos.jsonl`.

#### A.4.8 `preparar_arribos` y estaciones

```text
select.out
  → datos/seisan_<inicio>_<fin>_fases.csv
```

- Cada fase se asocia a un evento por cercanía temporal y geográfica.
- La estación se resuelve con los archivos `STATION*.HYP` del directorio
  `RCS_SEISAN_STATIONS_DIR`.
- Si un código aparece en varias listas, se elige la entrada cuya distancia al
  epicentro mejor coincide con la columna `DIS` del pick.
- La procedencia queda en `raw`: `est_lista`, `est_vigencia`, `software`,
  `origen_local`.

#### A.4.9 Adaptador

```text
app/domain/catalogs/adapters/seisan.py
```

| Campo | Valor |
|---|---|
| `formato` | `local_select` |
| `tipo` | `select` |
| `capacidades` | eventos, orígenes, magnitudes, arribos, excluidos |
| `catalogo()` | `datos/salida_collect.csv` |
| `extensiones()` | `arribos` → `datos/seisan_<inicio>_<fin>_fases.csv` |

Pasos:

1. `normalizar_seisan` → `revisaselect.py`.
2. `armar_catalogo` → `revisacollect.py`.
3. `preparar_arribos` → parseo de `select.out` y resolución de estaciones.

##### Calidad del evento

El adaptador agrega al final de `datos/salida_collect.csv` las mismas columnas
genéricas que usan las otras fuentes:

- `standard_error`: RMS del encabezado del evento (columnas 52–56).
- `azimuthal_gap`: valor `GAP=` de la línea siguiente al encabezado.
- `horizontal_uncertainty` y `depth_uncertainty`: ERH y ERZ de esa línea.
- `error_ellipse`: la línea `GAP=` completa, para conservar los valores de
  confianza.
- `used_phase_count`, `associated_phase_count`, estaciones usadas/asociadas y
  distancia mínima/máxima/mediana: derivados de las fases.
- `used` = peso 0–3, el mismo criterio que usa la app.
- `origin_time_us`: microsegundos del encabezado.
- `evaluation_status`: texto de `STATUS:` en la línea `ACTION`.
- `software`: `seisan`.

Los campos calculados se listan en `quality_derived_fields`. Las ocho columnas
históricas de `salida_collect.csv` no cambian; las nuevas van al final.

La página **Catálogos** ofrece la descarga del catálogo completo de **Seisan**
con el mismo ZIP de tres CSV más el LEEME.

#### A.4.10 Salidas canónicas

- `catalogo/seisan/eventos.jsonl` desde `salida_collect.csv`.
- `catalogo/seisan/arribos.jsonl` desde `seisan_*_fases.csv`.
- `catalogo/seisan/excluidos.jsonl` si el adaptador lo declara.

#### A.4.11 Errores frecuentes

| Síntoma | Causa probable | Dónde revisar |
|---|---|---|
| `Host key verification failed` | Host nuevo o cambiado | `~/.ssh/known_hosts`, `StrictHostKeyChecking` |
| `Permission denied` | Clave o usuario incorrecto | `SSH_ASKPASS`, `CATALOGOS_SSH_USER` |
| `select` no encontrado | El login no carga Seisan | `type -P select`, perfil remoto |
| Catálogo sin eventos | Período vacío o `select.inp` mal generado | `select.out`, `select_tiene_eventos()` |
| Acentos corruptos | Codificación distinta de Latin-1 | `select.out`, `revisaselect.py` |
| Fases sin estación | `STATION*.HYP` incompleto | `RCS_SEISAN_STATIONS_DIR` |
| Analista `TASK`/`NONE` | Valor no humano en `OP` | Normalización de `OP` |

### A.5 Central

Central consulta directamente la base CSN en modo de solo lectura. No recibe
archivo del usuario y no se carga en el esquema de la app.

```text
adapters/central.py:exportar
  → _consultar(inicio, fin)
      CONSULTA_ORIGENES_CON_PICKS
      CONSULTA_PICKS
      consulta de tensores
  → datos/central_<inicio>_<fin>_parametros.csv
  → datos/central_<inicio>_<fin>_fases.csv
  → datos/central_<inicio>_<fin>_tensores.csv
  → eventos.jsonl, arribos.jsonl, tensores.jsonl
```

- DSN: `RCS_CENTRAL_DSN`.
- La conexión se abre con `default_transaction_read_only=on`.
- Rol recomendado: `rcs_central_ro`, con `SELECT` y `CONNECT`.
- Solo se consultan el evento, el origen preferido, la magnitud preferida,
  los picks y los tensores del origen preferido.
- `event.published` se conserva como `Publicado`.
- `origin.status` se normaliza a `Revisión`.
- `origin.author` se usa como `Analista`.
- Los tensores se conservan tal como vienen hasta que la fuente declare la
  unidad de momento.
- Validador: `central`.
- Capacidades: eventos, orígenes, magnitudes, arribos y tensores.
- Es una fuente `derived`: no se usa como referencia de publicación ni suma al
  conteo de cruces.

#### A.5.1 Bloques de calidad

Central llena los mismos bloques que SeisComp:

- **Directo**: `standard_error`, `azimuthal_gap`, incertidumbres de tiempo,
  latitud, longitud y profundidad, `origin.station_count`, `error_ellipse`,
  `velocity_model`, `software`, `status`, incertidumbre de magnitud,
  estaciones de la magnitud y método de cálculo.
- **Derivado de los picks**: fases usadas/asociadas, estaciones
  usadas/asociadas, distancia mínima/máxima/mediana en km.
- `used_station_count` usa `origin.station_count` cuando existe; si no, se
  deriva de los picks.
- `quality_derived_fields` lista los campos calculados.
- `pick_uncertainty` conserva `pick.uncertainty`. `residual` queda vacío porque
  Central no trae un residual de tiempo separado.
- La descarga del catálogo completo está disponible desde **Catálogos**,
  igual que SeisComp y Seisan.

Errores frecuentes:

- DSN ausente o credenciales vencidas;
- rol sin `SELECT`;
- período fuera del rango disponible;
- tensores sin unidad declarada.

### A.6 Manifiesto, handlers y validadores

El manifiesto `app/domain/catalogs/sources.json` declara cada fuente. La app no
conoce de antemano los nombres ni la cantidad de fuentes.

| Campo | Uso |
|---|---|
| `id` | Identificador técnico y estable |
| `label` | Nombre visible |
| `role` | `reference` o `local` |
| `format` | Adaptador que se usa |
| `validator` | Validador del archivo |
| `download_handler` | Cómo se obtiene (`eventquery`, `seisan`, `seiscomp`) |
| `requires_file` | `false` para fuentes directas como Central |
| `requires_radius` | Si necesita radio de estaciones |
| `stored_filename` | Nombre fijo, por ejemplo `select.out` |
| `extraction_name` | Nombre sugerido de la extracción |
| `dsn_env` | Variable con la conexión de solo lectura |
| `capabilities` | Datos que aporta |
| `derived` | Fuente derivada de otras locales |
| `stations` | Proveedores y reglas de estaciones |

Handlers de descarga:

| Handler | Fuente | Acción |
|---|---|---|
| `eventquery` | Eventquery | `traer_eventquery` |
| `seisan` | Seisan | `traer_seisan` |
| `seiscomp` | SeisComp | `exportar_ventana` |
| vacío | Central | Consulta directa, sin archivo |

Validadores:

| Validador | Qué comprueba |
|---|---|
| `eventquery` | CSV con eventos y columnas mínimas |
| `seisan` | `select.out` con cabecera de evento |
| `seiscomp` | Exportación con soluciones |
| `central` | Conexión y al menos un evento en el período |

### A.7 Estaciones y resolución de coordenadas

Los adaptadores resuelven las coordenadas **antes** de escribir el canónico.
La app sigue leyendo solo `arribos.jsonl`; no conoce listas de estaciones ni
sistemas de procesamiento.

- **Seisan**: lee todos los `STATION*.HYP` de `RCS_SEISAN_STATIONS_DIR`. Si un
  código aparece en varias listas, elige la distancia más compatible con el
  `DIS` del pick.
- **SeisComp**: usa el inventario con épocas. Si la estación no está, puede
  caer al respaldo de Seisan según las reglas del manifiesto.
- **Central**: elige el proveedor según el `software` del origen local. Las
  reglas viven en el manifiesto.
- **Sin coincidencia**: el pick se conserva en `arribos.jsonl`, pero no se
  dibuja en el mapa ni entra a la propagación.
- **Trabajos antiguos**: conservan la posición que usaron, aunque la lista
  cambie después.

Configuración de ejemplo:

```json
"stations": {
  "providers": {
    "seisan": {
      "kind": "seisan_hyp",
      "dir_env": "RCS_SEISAN_STATIONS_DIR",
      "glob": "STATION*.HYP"
    },
    "seiscomp": {
      "kind": "seiscomp_inventory"
    }
  },
  "rules": [
    {"match": "Seisan", "provider": "seisan"},
    {"match": "SeisComP", "provider": "seiscomp", "fallback": "seisan"}
  ],
  "default": "seisan"
}
```

### A.8 Errores frecuentes y diagnóstico

| Fuente | Síntoma | Causa | Dónde revisar |
|---|---|---|---|
| Eventquery | CSV vacío | `eventquery2` sin datos o período vacío | `files/eventquery_*.csv` |
| Eventquery | Soluciones duplicadas | Se usó `eventquery` viejo | `traer_catalogos.py` |
| SeisComp | Sin eventos | Base o rol mal configurado | `RCS_SEISCOMP_DB_*` |
| SeisComp | Sin fases | Origen sin arribos | `*_fases.csv`, Anexo B.2 |
| Seisan | Sin eventos | `select` o `.inp` | `select.out`, A.4.11 |
| Seisan | Sin fases | `STATION*.HYP` incompleto | A.4.8 |
| Central | Error de conexión | DSN o credenciales | `RCS_CENTRAL_DSN` |
| Central | Catálogo vacío | Período fuera de rango | `job_sources.message` |
| Todas | Fuente sin eventos | El trabajo sigue, pero advierte | `job_sources.status` |

### A.9 Matriz de trazabilidad

| Fuente | Adquisición | Normalización | Adaptador | Canónico | Pruebas |
|---|---|---|---|---|---|
| Eventquery | `core/traer_catalogos.py` | `proc_query_harz_2.py` | `adapters/eventquery.py` | `eventos.jsonl` | `tests/test_catalogos*` |
| SeisComp | `app/services/seiscomp.py`, `core/exporta_ventana_seiscomp.py` | `seiscomp_a_parametros.py` | `adapters/seiscomp.py` | `eventos.jsonl`, `arribos.jsonl` | `tests/test_adapters*` |
| Seisan | `core/traer_catalogos.py` | `revisaselect.py`, `revisacollect.py` | `adapters/seisan.py` | `eventos.jsonl`, `arribos.jsonl` | `tests/test_adapters*` |
| Central | `adapters/central.py` | `_normalizar_*` | `adapters/central.py` | `eventos.jsonl`, `arribos.jsonl`, `tensores.jsonl` | `tests/test_adapters*` |

Los nombres de pruebas son orientativos; el listado vigente se obtiene con:

```bash
.venv/bin/pytest --collect-only -q | grep -i adapter
```
