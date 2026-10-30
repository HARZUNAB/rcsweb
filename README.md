# RCS Web

Plataforma web del **Revisor de Catálogos Sísmicos (RCS)** del CSN. Migración
incremental de la aplicación de escritorio, conservando el pipeline de análisis
ya validado.

**Estado actual: etapa 4C completada (v0.7.3).** Además de la carga local, la
plataforma puede solicitar y descargar catálogos del servidor y obtener SeisComp
desde PostgreSQL en solo lectura, combinando todas las bases. El radio de
estaciones es editable por solicitud, con 400 km por defecto. Las fechas se
ingresan como `dd/mm/aaaa` y el detalle del evento incluye mapas interactivos
online/offline con zoom, colores por fuente y viñetas de parámetros.

## Stack

- **Backend:** Flask 3, SQLAlchemy 2, Flask-Login, Flask-WTF
- **Frontend:** Jinja2 + Bootstrap 5.3 + HTMX 2 + JavaScript vanilla
- **Mapas:** matplotlib en modo `Agg` + cartopy + Pillow
- **Base de datos:** PostgreSQL 16
- **Tareas:** Celery + Redis
- **Infraestructura:** Docker + Docker Compose
- **Python:** 3.12 (aislado en el contenedor y en `.venv`)

## Fuentes de catálogo

- **eventquery** es la referencia publicada y siempre es obligatorio.
- **SeisComp** es la fuente local principal por defecto.
- **Seisan** es una fuente local secundaria, desmarcada por defecto.
- Cada fuente tiene un **alias** visible y un **formato** interno. La app no
  depende del nombre: un formato nuevo solo agrega un adaptador.
- Un trabajo necesita **al menos una fuente local** además de eventquery.
- Cada fuente seleccionada se valida y se procesa; si falla, el trabajo queda en
  borrador con el diagnóstico.
- La fuente principal se puede cambiar por trabajo.

## Catálogo estándar y adaptadores

El catálogo estándar vive en `app/domain/catalogs/` y se guarda como JSONL en
`workspace/<job>/catalogo/<source_id>/eventos.jsonl`.

- **Capa mínima:** fuente, evento, fecha, lat/lon/profundidad, magnitud, agencia,
  analista, estado, preferido/publicado y `raw`.
- **Extensiones:** `station`, `arrival`, `waveform_availability`,
  `station_magnitude` y `tensor` (tablas creadas; se llenan cuando la fuente las
  aporta).
- **Capacidades por formato:** eventos, orígenes, magnitudes, arribos,
  inventario, disponibilidad de ondas y excluidos.
- **Adaptadores separados del arranque:** `create_app()` no importa adaptadores.
  Se cargan de forma perezosa al parsear una fuente.
- SeisComp declara capacidades de estaciones/arribos/disponibilidad. Seisan no.
  El dump CSN, cuando se integre, tendrá picks pero no inventario ni
  disponibilidad.

La tarea **“disponible y no picada”** se calcula cruzando inventario activo,
arribos del origen preferido y disponibilidad de formas de onda. Si falta una
capacidad, se muestra “no evaluable”.

## Solicitudes por SSH

- `/solicitudes/nueva`: período, servidor, usuario, contraseña y fuentes.
- Descarga siempre el CSV de **eventquery** por SSH/SCP.
- **Seisan** (`select.out`) se descarga si está marcado.
- **SeisComp** se exporta desde PostgreSQL si está marcado (ver abajo).
- El **radio de estaciones** es editable por solicitud (400 km por defecto) y
  define la lista de estaciones sin arribos del export.
- La contraseña se usa solo durante la descarga (`SSH_ASKPASS`) y no se guarda.
- Historial en `/solicitudes`, con estado por catálogo, progreso, log y
  reintento de lo fallido.
- Al validar, crea el trabajo con `origin=ssh` y lo encola en el pipeline.
- Los comandos remotos se ejecutan con un locale UTF-8 para que `eventquery2`
  no falle con nombres acentuados.
- Requiere `openssh-client` en la imagen y acceso al servidor.

Variables:

```dotenv
CATALOGOS_SSH_HOST=10.54.217.9
CATALOGOS_SSH_USER=sysopr
```

## Exportación de SeisComp (solo lectura)

La exportación reutiliza `exporta_ventana_seiscomp.py` del proyecto base con
`--base todas`: consulta la base histórica y la de tiempo real y combina los
resultados. El script escribe el CSV, `_fases.csv`, `_no_picadas.csv` y la marca
`.completo`.

La conexión usa un **rol de solo lectura** (`rcs_ro`). Además, el runner
`app/services/runner_seiscomp.py` envuelve `psycopg2.connect` y agrega
`default_transaction_read_only=on` a cada conexión, porque el script del core
pasa su propio `options` y pisa `PGOPTIONS`.

```dotenv
SEISCOMP_DB_HOST=10.54.217.69
SEISCOMP_DB_PORT=5432
SEISCOMP_DB_NAME=seiscomp2
SEISCOMP_DB_USER=rcs_ro
SEISCOMP_DB_PASSWORD=
SEISCOMP_RADIO_KM=400

# Mapas: auto | online | offline
MAPS_MODE=auto
```

El rol debe crearse una sola vez con permisos de lectura y `CONNECT` en todas
las bases que se quieran combinar:

```sql
CREATE ROLE rcs_ro LOGIN PASSWORD '...';
ALTER ROLE rcs_ro SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE seiscomp2 TO rcs_ro;
-- repetir CONNECT para cada base histórica o de tiempo real
\c seiscomp2
GRANT USAGE ON SCHEMA public TO rcs_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO rcs_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO rcs_ro;
```

`/solicitudes/nueva` incluye **Probar conexión SeisComp**, que valida las
credenciales y lista las bases visibles sin escribir nada. Si faltan las
variables, la app muestra el error y deja la solicitud como borrador en vez de
fallar.

## Puesta en marcha

```bash
cp .env.example .env      # ajustar SECRET_KEY y contraseñas
make up                   # construye y levanta web, worker, db y redis
make ps
```

Abrir **http://localhost:8000** e ingresar con el usuario definido en `.env`
(`ADMIN_USERNAME` / `ADMIN_PASSWORD`, por defecto `admin` / `admin_dev_password`).

```bash
make logs                 # logs de todos los servicios
make down                 # detener (conserva datos)
make clean                # detener y borrar volúmenes
```

> Si el usuario pertenece al grupo `docker` pero la sesión no lo tiene cargado,
> usar `sg docker -c "..."` o reiniciar la sesión.

## Flujo de uso

1. **Solicitar catálogos** (flujo principal): período, servidor, contraseña SSH,
   fuentes y radio de estaciones. Descarga eventquery/Seisan y exporta SeisComp.
2. **Subir catálogos** (alternativa secundaria): si los archivos ya están en
   disco, se suben desde `/jobs/new` con eventquery y una o más fuentes locales
   (SeisComp y/o Seisan). Se valida el contenido antes de encolar.
3. El trabajo se encola en Celery. La página de detalle muestra progreso, pasos y
   log en vivo (polling HTMX cada 2 s).
4. Al terminar: tarjetas con conteos, tablas paginables con búsqueda, filtros
   por columna, orden y exportación del resultado filtrado.
5. Cada fila muestra una **ficha de ubicación** compacta (Chile
   continental/insular/costa, país, mar chileno o alta mar); las **miniaturas**
   del perfil y el mini mapa se activan con el interruptor «Miniaturas» o con
   «Ver miniaturas» de cada fila. El detalle muestra Δ por parámetro,
   clasificación, mapa de planta y perfil, y en repetidos el grupo completo de
   duplicados.
6. Se puede cancelar un trabajo en cola o en ejecución.
6. La sección **Auditoría** (solo administradores) registra login, alta,
   cancelación, fin/fallo y descargas.
7. Un trabajo terminado, fallido o cancelado puede **eliminarse** desde el panel
   o el detalle (creador o admin); se borran sus resultados y su workspace.

## Pipeline

El worker arma el plan según las fuentes seleccionadas y ejecuta los scripts del
proyecto base con `cwd` en `workspace/<job>/` y `RV_PROG=1`/`RV_ENTREGABLES=1`:

| Fuente | Pasos |
|---|---|
| eventquery (siempre) | `proc_query_harz_2.py` |
| SeisComp | `seiscomp_a_parametros.py` + `compara.py` (prefijo `seiscomp_`) + repetidos SeisComp |
| Seisan | `revisaselect.py` + `revisacollect.py` + `compara.py` + excluidos + repetidos Seisan |
| Dos fuentes locales | `cruza_nopub.py` para el cruce entre fuentes |
| Resultados | `construir_resultados()` recorre solo las fuentes presentes |

Los pasos de Seisan solo existen si Seisan está seleccionado. Lo mismo para
SeisComp. Al final se normalizan las salidas en `workspace/<job>/resultados/` y
se registran los artefactos descargables.

El detalle del trabajo es el punto de entrada a los resultados: muestra los
conteos por fuente, los catálogos procesados y los accesos a las tablas. La ruta
`/jobs/<id>/resultados` redirige a ese detalle.

## Validación y borradores

Antes de encolar se valida cada catálogo:

- eventquery: cabecera, eventos, coordenadas y fechas;
- Seisan: `select.out`, codificación y eventos;
- SeisComp: columnas del export, eventos y cobertura.

Si una fuente seleccionada falla, el trabajo queda en estado **Borrador** con el
detalle por fuente y no se ejecuta el pipeline. Se puede corregir el archivo y
crear un trabajo nuevo, o eliminar el borrador. La validación se repite en el
servidor al crear el trabajo.

## Migraciones

El esquema se administra con **Alembic / Flask-Migrate**:

```bash
make migrate    # flask db upgrade
make init-db    # db upgrade + seed-admin
```

Los trabajos existentes se migraron con `job_sources` inferidas desde
`job_files`: la fuente local principal es SeisComp si estaba presente; si no,
Seisan. El trabajo de demostración conserva sus resultados.

## Mapas

- **Miniaturas a pedido**: el perfil de subducción de cada fila se genera con
  matplotlib puro y se cachea en `workspace/<job>/plots/miniaturas/`. No se
  piden hasta activar el interruptor «Miniaturas» o el botón «Ver miniaturas»
  de la fila; así el listado carga liviano.
- **Detalle interactivo**: planta y perfil con zoom. Online usa Leaflet con
  OpenStreetMap; offline usa Plotly con TopoJSON local (`world_110m.json` y
  `world_50m.json`). Los eventos se colorean por fuente, hay leyenda y al hacer
  clic se muestran sus parámetros en una viñeta flotante. **La selección es
  compartida**: al elegir un evento en la planta o en el perfil se abre la misma
  viñeta y el evento se resalta en ambas vistas; no se dibuja una línea vertical.
  La viñeta busca una zona libre y no se superpone con la planta ni el perfil;
  en pantallas angostas se muestra como hoja inferior. En
  `No actualizados` se ven la solución local y la publicada; en `Repetidos` se
  ve el grupo completo.
- **Colores y leyendas**: se usa la paleta del proyecto base: amarillo para
  sismos registrados o no percibidos, rojo para Eventquery percibido, anillo
  blanco/negro para la solución publicada, borde violeta para sospechosos, aro
  azul marino para el seleccionado y aro magenta para soluciones superpuestas.
- **Hover sincronizado**: al pasar el mouse por un evento de la planta se
  muestra el mismo evento en el perfil, y viceversa, con fecha, hora y fuente.
  También funciona entre Leaflet y el perfil.
- **Sismicidad histórica en paneles**: la casilla «Sismicidad histórica
  (perfil)» carga la serie del perfil seleccionado bajo demanda, la cachea y la
  dibuja detrás de topografía, slab y eventos. Se mantiene al cambiar de perfil
  y queda deshabilitada en territorios sin perfil.
- **Perfil**: topografía, slab, nivel del mar y eventos calculados con
  `asigna_perfiles` del core, con zoom y clic. El contenedor se limita a
  820 × 420 px en escritorio para que no quede demasiado estirado.
- **Sismicidad histórica**: casilla opcional en el bloque **Perfil** del
  detalle, tanto online como offline. Al activarla se cargan
  `base_2020_2026.dat` y la proyección al perfil; el estado queda en la URL
  del detalle. La planta no dibuja la capa histórica.
- **Sospechosos**: se reutiliza `sismicidad.es_sospechoso` del core. El evento
  conserva el color de su fuente y se marca con borde violeta `#7b1196` y la
  leyenda “Sospechoso (borde violeta)”.
- **Frontera**: los listados y las viñetas muestran la distancia a la frontera
  chilena más cercana (Perú, Bolivia o Argentina), reutilizando `fronteras.py`.
  No se muestra dentro de Chile ni en mar chileno; en el mar solo se muestra
  para aguas peruanas, según la regla de la interfaz.
- **Detección**: `MAPS_MODE=auto` consulta conectividad con caché de 5 minutos.
  Se puede forzar `online` u `offline` por configuración o con `?mapa=offline`.
- **PNG**: el mapa completo de planta y perfil sigue disponible para abrir o
  descargar, generado con `plotear.py` del core en modo `Agg` y cacheado en
  `workspace/<job>/plots/mapas/`.
- Los mapas estáticos usan cartopy montado en `/data/cartopy:ro`.
- **Mini mapa de planta**: cada fila incluye un SVG liviano de Chile y los
  países vecinos, reutilizado con `<use>` desde un único símbolo. Un punto
  del color de la fuente marca el evento y un badge indica **Chile**, **Mar**
  o **Fuera**, calculado con los polígonos de `fronteras.py`. No usa tiles ni
  peticiones por fila.
- Las miniaturas usan `loading="lazy"` y las imágenes se sirven con caché HTTP.

## Servicios y puertos

| Servicio | Puerto host | Descripción |
|---|---|---|
| `web` | 8000 | Flask (debug) / Gunicorn (imagen) |
| `worker` | — | Celery |
| `db` | 5434 | PostgreSQL 16 |
| `redis` | 6380 | Broker de Celery |

Los puertos se publican solo en `127.0.0.1`.

## Estructura

```
rcsweb/
├── app/
│   ├── __init__.py          # create_app()
│   ├── config.py
│   ├── extensions.py
│   ├── domain/catalogs/    # esquema canónico, registro y adaptadores
│   ├── models/              # users, jobs, job_sources, extensiones, artifacts
│   ├── blueprints/          # auth, dashboard, jobs, results, health
│   ├── services/
│   │   ├── pipeline.py      # plan dinámico según fuentes
│   │   ├── sources.py       # compatibilidad con el registro de formatos
│   │   ├── validators.py    # validación de catálogos
│   │   ├── results.py       # normalización y lectura de tablas
│   │   ├── workspace.py     # carpetas por trabajo y symlinks
│   │   └── queue.py         # encolado en Celery
│   ├── templates/           # Jinja2 + Bootstrap
│   └── static/              # CSS, JS y vendor (Bootstrap, HTMX)
├── tasks/                   # Celery
├── tests/                   # pytest
├── samples/                 # dataset de muestra reproducible
├── workspace/               # un directorio por trabajo (ignorado)
├── Dockerfile
└── docker-compose.yml
```

## Dataset de muestra

En `samples/` hay un conjunto pequeño que ejercita todos los casos:

- `select.out` con 3 eventos.
- `eventquery_*.csv` con coincidencias, un evento con parámetros distintos y un
  duplicado.
- `seiscomp_*.csv` con soluciones para ambas fuentes.

Resultado esperado: 1 no publicado de Seisan, 2 de SeisComp, 1 no actualizado
por fuente y 2 repetidos publicados.

## Tests y calidad

La suite corre en un `.venv` local con Python 3.12:

```bash
make venv     # crea .venv e instala dependencias + dev
make test     # pytest
make lint     # ruff check
make fmt      # ruff format
```

Incluye tests de validadores, plan dinámico, alta con SeisComp-only,
alta con Seisan-only, borradores por validación fallida, solicitudes SSH con un
módulo de red simulado, exportación SeisComp con `subprocess` simulado y el
runner de solo lectura. Total actual: **200 tests**.

## Filtros y exportación

- **Filtro global** (`q`): busca en todas las columnas, sin distinguir
  mayúsculas ni acentos.
- **Filtros por columna**: las columnas de texto filtran por contenido. Las
  columnas numéricas usan un único campo compacto que acepta rangos inclusivos
  como `3..5`, además de `>=3`, `>3`, `<=5`, `<5` y `=3`. El campo es único para
  no restar columnas visibles ni obligar a desplazarse horizontalmente.
- Los filtros se combinan con AND y se conservan al ordenar y paginar.
- **Scroll horizontal**: todas las tablas que desbordan tienen una barra
  superior sincronizada con la inferior, para moverse sin bajar hasta el final
  del listado.
- **Descargar todo** genera un CSV con todas las filas del archivo, sin filtros.
- **Descargar filtrado** genera un CSV con todas las filas del filtro (no solo
  la página).
- **Descargar seleccionados** genera un CSV con las filas marcadas, aunque estén
  ocultas por el filtro actual. La selección se conserva en el navegador por
  trabajo, tabla y opción.
- Todos los CSV llevan BOM para Excel.
- El listado de eventos de los paneles también permite seleccionar y descargar
  todo, lo filtrado o lo seleccionado.
- El detalle de cada fila conserva el filtro y el orden al volver.

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/` | Panel de trabajos |
| GET/POST | `/login` | Ingreso |
| POST | `/logout` | Cierre de sesión |
| GET/POST | `/jobs/new` | Subida manual de catálogos (alternativa) |
| GET | `/jobs/<id>` | Detalle con progreso y log |
| GET | `/jobs/<id>/estado` | Fragmento para el polling HTMX |
| POST | `/jobs/<id>/cancelar` | Cancelar trabajo |
| POST | `/jobs/<id>/eliminar` | Eliminar trabajo terminado |
| GET | `/jobs/<id>/resultados` | Redirige al detalle del trabajo |
| GET | `/jobs/<id>/resultados/no-publicados` | Tabla de no publicados |
| GET | `/jobs/<id>/resultados/no-actualizados` | Tabla de no actualizados |
| GET | `/jobs/<id>/resultados/repetidos` | Informes de repetidos |
| GET | `/jobs/<id>/resultados/<tabla>/exportar` | CSV filtrado |
| GET | `/jobs/<id>/resultados/<tabla>/<opcion>/<fila>` | Detalle del evento |
| GET | `/jobs/<id>/resultados/<tabla>/<opcion>/<fila>/miniatura.png` | Miniatura del perfil |
| GET | `/jobs/<id>/resultados/<tabla>/<opcion>/<fila>/mapa.png` | Planta y perfil |
| GET | `/jobs/<id>/descargas` | Artefactos descargables |
| GET | `/solicitudes` | Historial de solicitudes |
| GET/POST | `/solicitudes/nueva` | Solicitud de catálogos y selección de fuentes |
| POST | `/solicitudes/probar-seiscomp` | Probar conexión SeisComp |
| GET | `/solicitudes/<id>` | Detalle y progreso |
| POST | `/solicitudes/<id>/reintentar` | Reintentar descarga |
| GET | `/admin/auditoria` | Auditoría (solo admin) |
| GET | `/health` | Estado de base, core, workspace y dump |

## Eliminación de trabajos

- Botón **Eliminar** en el panel y en el detalle, con confirmación modal.
- Solo para trabajos en estado `done`, `failed` o `cancelled`.
- Puede eliminar el **creador** del trabajo o un **administrador**.
- Borra el registro, sus archivos, pasos y artefactos, y la carpeta del
  workspace. La auditoría conserva la entrada `job.delete`.
- Un trabajo en cola o en ejecución no se puede eliminar; primero hay que
  cancelarlo.
- Limpieza administrativa por CLI:

```bash
docker compose exec web flask --app app delete-job <job_id>
```

## Relación con el proyecto base

El proyecto de escritorio vive en `~/Desarrollo/revisacatalogosweb` y se monta
**solo lectura** en `/opt/rcs-core`. El worker ejecuta sus scripts con el
directorio de trabajo en `workspace/<job>`. No se modifica el código original.

## Seguridad

- CSRF en formularios y cabecera `X-CSRFToken` para HTMX.
- Contraseñas con `werkzeug.security`.
- Sesiones `HttpOnly` y `SameSite=Lax`; `Secure` se activa con
  `SESSION_COOKIE_SECURE=1` bajo HTTPS.
- Subidas limitadas a `MAX_UPLOAD_MB`.
- El dump y el core se montan en solo lectura.
- SeisComp se consulta con el rol `rcs_ro` y el runner fuerza
  `default_transaction_read_only=on` en cada conexión.
- Descargas validadas contra el workspace del trabajo (sin traversal).
- No hay consola SQL arbitraria.

## Paneles y catálogos

- **Paneles**: cada trabajo tiene una vista de contexto sismotectónico. Los
  catálogos de entrada y el conjunto **Observaciones** (No publicados +
  No actualizados + Repetidos) se agrupan por perfil de subducción usando
  `asigna_perfiles` del core. Los eventos sin perfil se clasifican con la
  geografía precisa de `ubicacion.py`: **Nacional** (Chile continental, costa y
  mar chileno), **Insular** (islas oceánicas chilenas), **Antártico** (caja del
  reclamo) y **Otros** (otros países y alta mar). La vista muestra el resumen por
  perfil y, al seleccionar un grupo, la planta de sus eventos y el perfil
  topografía/slab **lado a lado**. Si el grupo no tiene perfil, el área del perfil
  muestra **«Perfil no disponible»**. Al hacer clic en un evento de cualquiera de
  las dos vistas se resalta en ambas, se muestra su viñeta flotante —ubicada
  sobre la columna de grupos para no tapar los mapas— y se puede abrir el detalle
  completo (planta y perfil interactivos) en una pestaña nueva.
- **Observaciones**: los informes de repetidos se deduplican por evento (fuente
  + fecha + coordenadas + profundidad), de modo que un evento que aparece en
  `amplio`, `estricto` y `excluidos` se cuenta una sola vez. Los filtros se
  presentan como una tabla con la **fuente** arriba (Todas, SeisComp, Seisan,
  Eventquery) y el **tipo** debajo (Todos, No publicados, No actualizados,
  Repetidos), con conteos cruzados y una línea «Filtro: …». Se aplican a los
  grupos, la planta, el perfil y el listado. La planta y el perfil muestran el
  mismo conteo de eventos del grupo seleccionado. Al elegir un filtro, la vista
  se desplaza hasta el **listado de eventos**; también hay enlaces «Ir al
  listado» y «Volver a los paneles». Los paneles de catálogo no muestran estas
  pestañas porque ya corresponden a una sola fuente. En la lista de grupos, las
  flechas **↑/↓** recorren perfiles y territorios y actualizan automáticamente
  la planta y el perfil, sin necesidad de hacer clic en cada fila.
- **Catálogos**: el detalle del trabajo tiene un menú con los catálogos de
  entrada disponibles (Eventquery, Seisan, SeisComp). Cada uno abre un listado
  con las mismas prestaciones que las tablas de resultados: búsqueda, filtros,
  orden, paginación, exportación, ficha de ubicación, miniaturas a pedido y
  enlace al catálogo diario de sismologia.cl. El catálogo **Eventquery** agrega
  la columna **«Analista probable»**, deducida cruzando cada evento publicado con
  las soluciones locales de SeisComp y Seisan; se muestran ambas fuentes cuando
  aportan (`SeisComp: …; Seisan: …`).
- El primer acceso a un panel calcula la asignación de perfiles y la deja en
  `workspace/<job>/paneles/`; las visitas siguientes usan esa caché.

## Próximos pasos (etapa 4D y 5)

- **4D**: cierre de la etapa 4, capturas y documentación final.
- **5**: revisión SeisComp (estaciones, arribos y disponibilidad de ondas).
- Luego: agencias y catálogo histórico.
