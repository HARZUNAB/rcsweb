# RCS Web

Plataforma web del **Revisor de Catálogos Sísmicos (RCS)** del CSN. Migración
incremental de la aplicación de escritorio, conservando el pipeline de análisis
ya validado.

**Estado actual: etapa 4C completada (v0.7.3).** Además de la carga local, la
plataforma puede solicitar y descargar catálogos del servidor y obtener SeisComp
desde PostgreSQL en solo lectura, combinando todas las bases. El radio de
estaciones es editable por solicitud, con 400 km por defecto. Las fechas se
ingresan como `dd/mm/aaaa` y el detalle del evento incluye mapas interactivos
online/offline con zoom, colores por fuente y panel de parámetros.

## Documentación

- **Manual de usuario**: [Markdown](docs/manual_usuario.md) ·
  [DOCX](docs/manual_usuario.docx)
- **Manual técnico**: [Markdown](docs/manual_tecnico.md) ·
  [DOCX](docs/manual_tecnico.docx)

Los Markdown son la fuente de verdad. Los DOCX se regeneran con:

```bash
.venv/bin/python scripts/generar_docs.py
```

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
6. La sección **Auditoría** (administradores y supervisores) registra login,
   alta, cancelación, fin/fallo y descargas.
7. Un trabajo terminado, fallido o cancelado puede **eliminarse** desde el panel
   o el detalle (creador, administrador o supervisor); se borran sus resultados
   y su workspace.

## Roles y permisos

| Opción | Administrador | Supervisor | Analista | Consulta |
|---|:---:|:---:|:---:|:---:|
| Ver trabajos | Sí | Sí | Sí | Sí |
| Subir catálogos | Sí | Sí | Sí | — |
| Cancelar trabajo | Sí, todos | Sí, todos | Solo propios | — |
| Eliminar trabajo | Sí, todos | Sí, todos | Solo propios | — |
| Descargar artefactos | Sí | Sí | Sí | — |
| Solicitar catálogos | Sí | Sí | Sí | — |
| Ver solicitudes | Sí | Sí | Sí | — |
| Reintentar solicitud | Sí, todas | Sí, todas | Solo propias | — |
| Paneles | Sí | Sí | Sí | Sí |
| Catálogos y resultados | Sí | Sí | Sí | Sí |
| Exportar listados | Sí | Sí | Sí | — |
| Auditoría | Sí | Sí | — | — |
| Gestión de usuarios | Sí | — | — | — |

- **Administrador**: acceso total.
- **Supervisor**: toda la operación y la auditoría; no administra cuentas ni
  restablece contraseñas.
- **Analista**: operación diaria; solo cancela, elimina o reintenta lo que creó
  y solo ve eventos asociados a su código corto de analista.
- **Consulta**: solo lectura; no crea, descarga ni exporta. Por ahora se filtra
  por código de analista igual que el analista.

Cada trabajo guarda su creador. El **analista** y la **consulta** solo ven sus
propios trabajos; el **administrador** y el **supervisor** ven todos. La columna
**Creador** del panel y la línea «por …» del detalle identifican al autor. Las
solicitudes de catálogos siguen la misma regla de propiedad.

Cada usuario tiene `analyst_code` y alias opcionales. En Resultados y Paneles,
analista y consulta solo ven eventos cuyo analista coincide con su código,
ignorando mayúsculas, acentos y espacios, y tolerando prefijos de al menos tres
caracteres. Sin código asignado no ven eventos. En Catálogos ven todas las
fuentes y datos, pero sin columnas de analista, sin detalle/miniaturas/Web y con
una única descarga sanitizada: **Descargar catálogo**.

Los permisos se aplican en el servidor. Ocultar un botón no reemplaza el
control: un acceso directo sin permiso responde **403**. Si una cuenta se
desactiva, su sesión se cierra en la siguiente petición.

## Usuarios y acceso

- La pantalla **Usuarios** (solo administrador) permite crear cuentas, cambiar
  roles, activar o desactivar usuarios y restablecer contraseñas. No permite
  dejar el sistema sin administradores activos.
- La pantalla **Auditoría** está disponible para administradores y supervisores.
- El login incluye **«¿Olvidó su contraseña?»** con las instrucciones de
  recuperación. Las contraseñas no se pueden recuperar; solo restablecer.
- Comandos de recuperación y mantenimiento:

```bash
docker compose exec web flask --app app list-users
docker compose exec web flask --app app set-role <usuario> <rol>
docker compose exec web flask --app app reset-password <usuario>
docker compose exec web flask --app app create-user <usuario> --role analista \
  --analyst-code Jere --analyst-aliases "JereV,jerez"
docker compose exec web flask --app app set-analyst-code gjerez Jere \
  --aliases "JereV,jerez"
```

## Dónde se guardan los trabajos

- **Registro y metadatos**: PostgreSQL `rcs` del contenedor `rcsweb-db`, en el
  volumen Docker `rcsweb_pgdata`. Las tablas principales son `jobs`,
  `job_files`, `job_sources`, `job_steps`, `job_artifacts`, `catalog_requests`,
  `audit_log` y `users`. El puerto del host es `127.0.0.1:5434`.
- **Archivos de cada trabajo**: en el host,
  `workspace/<job_id>/` (montado como `/workspace` en los contenedores). Ahí
  quedan catálogos, resultados, mapas, miniaturas y registros. Al eliminar el
  trabajo se borran su registro y su carpeta; la auditoría se conserva. Si el
  trabajo provenía de una solicitud, la solicitud queda en el historial. El
  listado muestra **Estado inicial** (descarga) y **Estado final** (Trabajo
  vigente, Trabajo eliminado, Preparando trabajo o Sin trabajo), además de la
  fecha de eliminación en la columna **Eliminado**.
- Para inspeccionar el volumen de PostgreSQL:
  `sudo docker volume inspect rcsweb_pgdata`.

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
make migrate    # aplica las migraciones pendientes
make init-db    # aplica migraciones y crea el administrador
make up         # aplica migraciones y levanta web, worker, db y redis
make restart    # reinicia web y worker
```

`make up` ejecuta `make migrate` antes de levantar los servicios. Así, después
de actualizar el código con una migración nueva, no es necesario recordar el
`db upgrade` por separado.

El contenedor `web` también ejecuta `flask db upgrade` al arrancar, pero el
recargador de Flask no repite ese comando cuando cambia el código. Por eso, si
actualiza el repositorio sin reiniciar los contenedores, ejecute:

```bash
make migrate
docker compose restart web worker
```

Si aparece un error del tipo `column ... does not exist`, la base quedó en una
revisión anterior. Aplique `make migrate` y reinicie `web` y `worker` antes de
volver a crear solicitudes.

Los trabajos existentes se migraron con `job_sources` inferidas desde
`job_files`: la fuente local principal es SeisComp si estaba presente; si no,
Seisan. El trabajo de demostración conserva sus resultados.

## Mapas

- **Miniaturas a pedido**: el perfil de subducción de cada fila se genera con
  matplotlib puro y se cachea en `workspace/<job>/plots/miniaturas/`. No se
  piden hasta activar el interruptor «Miniaturas» o el botón «Ver miniaturas»
  de la fila; así el listado carga liviano. Al abrirlas, el perfil y el mini
  mapa de planta se muestran lado a lado; la primera columna se ensancha solo
  lo necesario y los parámetros conservan su ancho (la tabla sigue con scroll
  horizontal). También funcionan en los listados de Catálogos, incluido
  Eventquery.
- **Detalle interactivo**: planta y perfil con zoom. Online usa Leaflet con
  OpenStreetMap; offline usa Plotly con TopoJSON local (`world_110m.json` y
  `world_50m.json`). Los eventos se colorean por fuente, hay leyenda y al pasar
  el cursor sus parámetros se previsualizan en el panel fijo. Al hacer clic la
  selección queda fija y el evento se resalta en ambas vistas; no se dibuja una
  línea vertical ni una etiqueta flotante sobre los marcadores vecinos. En
  pantallas angostas el panel pasa debajo de los mapas. La planta abre con una
  vista regional: si el evento o el grupo están muy concentrados, se usa un
  mínimo de 8° de longitud × 3° de latitud y se limita el zoom inicial a 7.
  En `No actualizados` se ven la solución local y la publicada, y la publicada
  es la referencia; en `Repetidos` se ve el grupo completo.
- **Colores y leyendas**: se usa la paleta del proyecto base: amarillo para
  sismos registrados o no percibidos, rojo para Eventquery percibido, anillo
  blanco/negro para la solución publicada, borde violeta para sospechosos, aro
  azul marino para el seleccionado y aro magenta para soluciones superpuestas.
- **Hover y selección**: al pasar el cursor por un evento, sus parámetros se
  previsualizan en el panel fijo sin tapar los marcadores vecinos. Al hacer clic,
  la selección queda fija y se resalta en planta y perfil.
- **Distancia entre soluciones**: cuando el grupo tiene más de una solución, el
  panel muestra la separación respecto del evento de referencia. El punto de
  referencia aparece como «0 km (referencia)». En `No actualizados` la
  referencia es la solución publicada (Eventquery); en eventos únicos no se
  muestra, porque no hay otra solución con la cual comparar.
- **Sismicidad histórica en paneles**: la casilla «Sismicidad histórica
  (perfil)» carga la serie del perfil seleccionado bajo demanda, la cachea y la
  dibuja detrás de topografía, slab y eventos. Se mantiene al cambiar de perfil
  y queda deshabilitada en territorios sin perfil.
- **Perfil**: topografía, slab, nivel del mar y eventos calculados con
  `asigna_perfiles` del core, con zoom y clic. El contenedor se limita a
  820 × 420 px en escritorio para que no quede demasiado estirado.
- **Sismicidad histórica**: casilla opcional en el bloque **Perfil** del
  detalle, tanto online como offline. Al activarla se pide la serie del perfil
  por JSON y se redibuja solo el perfil, sin recargar la página: se conservan
  el scroll y el zoom del mapa. El rango de los ejes se calcula sin la capa
  histórica, de modo que el perfil no se achata al activarla. El estado queda
  en la URL del detalle y los enlaces de modo online/offline lo conservan. La
  planta no dibuja la capa histórica.
- **Sospechosos**: se reutiliza `sismicidad.es_sospechoso` del core. El evento
  conserva el color de su fuente y se marca con borde violeta `#7b1196` y la
  leyenda “Sospechoso (borde violeta)”.
- **Frontera**: los listados y el panel del evento muestran la distancia a la frontera
  chilena más cercana (Perú, Bolivia o Argentina), reutilizando `fronteras.py`.
  No se muestra dentro de Chile ni en mar chileno; en el mar solo se muestra
  para aguas peruanas, según la regla de la interfaz.
- **Detección**: `MAPS_MODE=auto` consulta conectividad con caché de 5 minutos.
  Se puede forzar `online` u `offline` por configuración o con `?mapa=offline`.
- **PNG**: el mapa completo de planta y perfil sigue disponible para abrir o
  descargar, generado con `plotear.py` del core en modo `Agg` y cacheado en
  `workspace/<job>/plots/mapas/`.
- Los mapas estáticos usan cartopy montado en `/data/cartopy:ro`.
- **Mini mapa de planta**: cada fila incluye el SVG original de **90×130 px**
  con Chile y los países vecinos, reutilizado con `<use>` desde un único
  símbolo. Se conservan sus colores y su contorno; solo se agregó una capa de
  **divisiones regionales** con línea fina y segmentada, recortada al contorno
  de Chile. La proyección del SVG es lineal y coincide con
  `borders.posicion_mapa`, de modo que el punto del evento cae en el lugar
  correcto. El color indica la fuente y un badge muestra **Chile**, **Mar** o
  **Fuera**, calculado con los polígonos de `fronteras.py`. No usa tiles ni
  peticiones por fila.
- **Regiones en los paneles**: la planta de los paneles carga una sola vez
  `app/static/data/chile_regiones.json` con el contorno de Chile y las líneas
  regionales. Se dibujan en una capa SVG sobre el mapa con **todo Chile**: no
  intervienen en el encuadre y se vuelven a proyectar al hacer zoom, desplazar
  o redimensionar. La capa se ancla y recorta al mapa aunque el CSS venga de
  caché, y el botón **«Centrar»** devuelve el encuadre regional del grupo
  después de hacer zoom o desplazar. Una traza invisible de contexto mantiene
  el encuadre inicial.
- **Regenerar las regiones**: se ejecuta
  `CARTOPY_DATA_DIR=/ruta/a/cartopy python scripts/generar_mapa_chile.py`.
  El script toma el SVG base, agrega o reemplaza la capa `region-chile` con los
  límites de Natural Earth 10m y genera el JSON de contorno y regiones para los
  paneles. Cartopy descarga las capas la primera vez si no están. No modifica el
  proyecto base.
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
runner de solo lectura. Total actual: **325 tests**.

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
- **Publicado en otra fuente**: en los listados que tienen esa columna se
  muestra junto a «Analista», antes de la frontera. Indica la otra fuente donde
  se publicó el evento (por ejemplo, SeisComp); «Tipo mag.» es el tipo de
  magnitud y no la fuente.
- **Aviso de carga**: las navegaciones internas muestran un aviso con spinner
  y «Cargando…» cuando tardan más de ~120 ms. Se excluyen descargas, enlaces
  externos, anclas y peticiones HTMX.

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
| GET | `/admin/auditoria` | Auditoría (admin y supervisor) |
| GET | `/admin/usuarios` | Gestión de usuarios (solo admin) |
| GET | `/health` | Estado de base, core, workspace y dump |

## Eliminación de trabajos

- Botón **Eliminar** en el panel y en el detalle, con confirmación modal.
- Solo para trabajos en estado `done`, `failed` o `cancelled`.
- Puede eliminar el **creador** del trabajo, un **administrador** o un
  **supervisor**.
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
  muestra **«Perfil no disponible»**. Al pasar el cursor por un evento de
  cualquiera de las dos vistas, sus datos se previsualizan en la tarjeta inferior;
  al hacer clic la selección queda fija, se resalta en ambas y se puede abrir el
  detalle completo (planta y perfil interactivos) en una pestaña nueva.
- **Observaciones**: los informes de repetidos se deduplican por evento (fuente
  + fecha + coordenadas + profundidad), de modo que un evento que aparece en
  `amplio`, `estricto` y `excluidos` se cuenta una sola vez. Los filtros se
  presentan como una tabla con la **fuente** arriba (Todas, SeisComp, Seisan,
  Eventquery) y el **tipo** debajo (Todos, No publicados, No actualizados,
  Repetidos), con conteos cruzados y una línea «Filtro: …». Se aplican a los
  grupos, la planta, el perfil y el listado. La planta y el perfil muestran el
  mismo conteo de eventos del grupo seleccionado. Todas las pestañas están
  siempre activas: una fuente válida con **0 eventos** se conserva y muestra el
  aviso «No hay eventos para…», en lugar de volver a «Todas». Al elegir un
  filtro con eventos, la vista se desplaza hasta el **listado de eventos**;
  también hay enlaces «Ir al listado» y «Volver a los paneles». Los paneles de
  catálogo no muestran estas pestañas porque ya corresponden a una sola fuente. En la lista de grupos, las
  flechas **↑/↓** recorren perfiles y territorios y actualizan automáticamente
  la planta y el perfil, sin necesidad de hacer clic en cada fila. Al abrir
  **Ver** y volver, se conserva seleccionado el mismo perfil o territorio.
- **Catálogos**: el detalle del trabajo tiene un menú con los catálogos de
  entrada disponibles (Eventquery, Seisan, SeisComp). Administrador y supervisor
  mantienen el listado completo, columnas de analista, Web, Ver, miniaturas y
  descargas. Analista y consulta ven todas las fuentes y filtros, pero sin
  columnas de analista, sin Web/Ver/miniaturas y solo con **Descargar catálogo**.
  Esa descarga abre una vista previa con el CSV sanitizado, la planta de todo el
  catálogo y un PNG por perfil disponible, además de un ZIP con todo. El CSV
  contiene fecha y hora, coordenadas, profundidad, magnitud, tipo de magnitud y
  referencia geográfica cuando existe; no incluye al analista. El catálogo
  **Eventquery** agrega la columna **«Analista probable»**, deducida cruzando
  cada evento publicado con las soluciones locales de SeisComp y Seisan; se
  muestran ambas fuentes cuando aportan (`SeisComp: …; Seisan: …`). En **No
  actualizados**, el punto publicado muestra ese mismo texto como «Analista
  probable» tanto en la planta como en el perfil, mientras el punto local
  conserva su «Analista» real.
- El primer acceso a un panel calcula la asignación de perfiles y la deja en
  `workspace/<job>/paneles/`; las visitas siguientes usan esa caché.

## Próximos pasos (etapa 4D y 5)

- **4D**: cierre de la etapa 4, capturas y documentación final.
- **5**: revisión SeisComp (estaciones, arribos y disponibilidad de ondas).
- Luego: agencias y catálogo histórico.
