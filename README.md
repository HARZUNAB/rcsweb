# RCS Web

Plataforma web del **Revisor de Catálogos Sísmicos (RCS)** del CSN. Migración
incremental de la aplicación de escritorio, conservando el pipeline de análisis
ya validado.

**Estado actual: etapa 1 completada.** Se pueden cargar los catálogos, ejecutar
el pipeline en segundo plano, seguir el progreso y consultar/descargar las
tablas de no publicados, no actualizados y repetidos.

## Stack

- **Backend:** Flask 3, SQLAlchemy 2, Flask-Login, Flask-WTF
- **Frontend:** Jinja2 + Bootstrap 5.3 + HTMX 2 + JavaScript vanilla
- **Base de datos:** PostgreSQL 16
- **Tareas:** Celery + Redis
- **Infraestructura:** Docker + Docker Compose
- **Python:** 3.12 (aislado en el contenedor y en `.venv`)

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

1. **Nuevo trabajo**: período y tres archivos (`select.out`, CSV de eventquery y
   exportación de SeisComp opcional).
2. El trabajo se encola en Celery. La página de detalle muestra progreso, pasos y
   log en vivo (polling HTMX cada 2 s).
3. Al terminar: tarjetas con conteos, tablas paginables con búsqueda y orden, y
   descargas en CSV/TXT.
4. Se puede cancelar un trabajo en cola o en ejecución.

## Pipeline

El worker ejecuta los scripts del proyecto base con `cwd` en
`workspace/<job>/` y `RV_PROG=1`/`RV_ENTREGABLES=1`:

| # | Paso | Script |
|---|---|---|
| 1 | Normalizar eventquery | `proc_query_harz_2.py` |
| 2 | Procesar select.out | `revisaselect.py` |
| 3 | Armar catálogo local | `revisacollect.py` |
| 4 | Comparar contra Seisan | `compara.py` |
| 5 | Convertir SeisComp | `seiscomp_a_parametros.py` |
| 6 | Comparar contra SeisComp | `compara.py` (prefijo `seiscomp_`) |
| 7 | Cruzar no publicados | `cruza_nopub.py` |
| 8 | Revisar excluidos | `revisaexcluidos.py` |
| 9 | Repetidos en excluidos | `repetidosexclu.py` |
| 10 | Detectar repetidos | `repetidos.py` |

Al final se normalizan las salidas en `workspace/<job>/resultados/` y se
registran los artefactos descargables.

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
│   ├── models/              # users, jobs, job_files, job_steps, artifacts
│   ├── blueprints/          # auth, dashboard, jobs, results, health
│   ├── services/
│   │   ├── pipeline.py      # adaptador y orquestación
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

Incluye un test de integración que ejecuta el pipeline real si el proyecto base
está montado (`/opt/rcs-core` o `RCS_CORE_PATH`); si no, se salta.

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
| GET | `/jobs/<id>/resultados` | Resumen de resultados |
| GET | `/jobs/<id>/resultados/no-publicados` | Tabla de no publicados |
| GET | `/jobs/<id>/resultados/no-actualizados` | Tabla de no actualizados |
| GET | `/jobs/<id>/resultados/repetidos` | Informes de repetidos |
| GET | `/jobs/<id>/descargas` | Artefactos descargables |
| GET | `/health` | Estado de base, core, workspace y dump |

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

## Próximos pasos (etapa 2)

- Detalle de evento con Δ por parámetro y agrupación por perfil.
- Filtros por columna y exportación del resultado filtrado.
- Atribución de analista en repetidos.
- Auditoría de acciones por usuario.
- Luego: mapas (etapa 3), SeisComp (etapa 4) y catálogo histórico (etapa 6a).
