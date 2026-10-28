# RCS Web

Plataforma web del **Revisor de Catálogos Sísmicos (RCS)** del CSN. Migración
incremental de la aplicación de escritorio, conservando el pipeline de análisis
ya validado.

**Estado actual: etapa 4B completada.** Además de la carga local, la plataforma
puede solicitar y descargar catálogos por SSH/SCP, con historial, progreso y
reintentos. La contraseña se usa por solicitud y no se guarda. Queda pendiente
4C: exportación automática de SeisComp desde PostgreSQL read-only.

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

- `/solicitudes/nueva`: período, servidor, usuario y contraseña.
- Descarga `select.out` y el CSV de eventquery por SSH/SCP.
- La contraseña se usa solo durante la descarga (`SSH_ASKPASS`) y no se guarda.
- Historial en `/solicitudes`, con estado por catálogo, progreso, log y
  reintento de lo fallido.
- Al validar, crea el trabajo con `origin=ssh` y lo encola en el pipeline.
- Requiere `openssh-client` en la imagen y acceso al servidor.
- La exportación automática de SeisComp se incorpora en 4C; por ahora se sube
  desde “Nuevo trabajo”.

Variables:

```dotenv
CATALOGOS_SSH_HOST=10.54.217.9
CATALOGOS_SSH_USER=sysopr
```

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

1. **Nuevo trabajo**: período, eventquery y una o más fuentes locales
   (SeisComp y/o Seisan). Se valida el contenido antes de encolar.
2. El trabajo se encola en Celery. La página de detalle muestra progreso, pasos y
   log en vivo (polling HTMX cada 2 s).
3. Al terminar: tarjetas con conteos, tablas paginables con búsqueda, filtros
   por columna, orden y exportación del resultado filtrado.
4. Cada fila tiene una **miniatura del perfil** y un detalle con Δ por
   parámetro, clasificación, mapa de planta y perfil, y en repetidos el grupo
   completo de duplicados.
5. Se puede cancelar un trabajo en cola o en ejecución.
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

- **Miniatura**: perfil de subducción de cada fila, generada en proceso con
  matplotlib puro y cacheada en `workspace/<job>/plots/miniaturas/`.
- **Mapa completo**: planta + perfil, generado en un subproceso con
  `plotear.py` del core en modo `Agg` y cacheado en
  `workspace/<job>/plots/mapas/`.
- Los mapas usan los datos de cartopy montados en `/data/cartopy:ro`
  (`CARTOPY_DATA_DIR_HOST` en `.env`).
- Para no bloquear la interfaz, las miniaturas usan `loading="lazy"` y las
  imágenes se sirven con caché HTTP.

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
alta con Seisan-only, borradores por validación fallida y un test de integración
que ejecuta el pipeline real si el proyecto base está montado. Total actual:
**76 tests**.

## Filtros y exportación

- **Filtro global** (`q`): busca en todas las columnas, sin distinguir
  mayúsculas ni acentos.
- **Filtros por columna**: contiene para texto; para columnas numéricas acepta
  `>=10`, `>10`, `<=10`, `<10`, `=10` y rangos `10..20`.
- Los filtros se combinan con AND y se conservan al ordenar y paginar.
- **Exportar filtrado** genera un CSV con todas las filas del filtro (no solo
  la página) y BOM para Excel.
- El detalle de cada fila conserva el filtro y el orden al volver.

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/` | Panel de trabajos |
| GET/POST | `/login` | Ingreso |
| POST | `/logout` | Cierre de sesión |
| GET/POST | `/jobs/new` | Alta de trabajo y subida de catálogos |
| GET | `/jobs/<id>` | Detalle con progreso y log |
| GET | `/jobs/<id>/estado` | Fragmento para el polling HTMX |
| POST | `/jobs/<id>/cancelar` | Cancelar trabajo |
| POST | `/jobs/<id>/eliminar` | Eliminar trabajo terminado |
| GET | `/jobs/<id>/resultados` | Resumen de resultados |
| GET | `/jobs/<id>/resultados/no-publicados` | Tabla de no publicados |
| GET | `/jobs/<id>/resultados/no-actualizados` | Tabla de no actualizados |
| GET | `/jobs/<id>/resultados/repetidos` | Informes de repetidos |
| GET | `/jobs/<id>/resultados/<tabla>/exportar` | CSV filtrado |
| GET | `/jobs/<id>/resultados/<tabla>/<opcion>/<fila>` | Detalle del evento |
| GET | `/jobs/<id>/resultados/<tabla>/<opcion>/<fila>/miniatura.png` | Miniatura del perfil |
| GET | `/jobs/<id>/resultados/<tabla>/<opcion>/<fila>/mapa.png` | Planta y perfil |
| GET | `/jobs/<id>/descargas` | Artefactos descargables |
| GET | `/solicitudes` | Historial de solicitudes |
| GET/POST | `/solicitudes/nueva` | Solicitud SSH |
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
- Descargas validadas contra el workspace del trabajo (sin traversal).
- No hay consola SQL arbitraria.

## Próximos pasos (etapa 4C)

- Exportación automática de SeisComp desde PostgreSQL en solo lectura,
  consultando todas las bases.
- Prueba de conexión y cobertura por base.
- Luego: revisión SeisComp (etapa 5), agencias y catálogo histórico.
