# RCS Web

Plataforma web del **Revisor de Catálogos Sísmicos (RCS)** del CSN. Migración
incremental de la aplicación de escritorio, conservando el pipeline de análisis
ya validado.

**Estado actual: etapa 0 (andamiaje).** Hay login, panel de trabajos, salud del
servicio y la infraestructura Docker. La carga y el procesamiento de catálogos
llegan en la etapa 1.

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
│   ├── models/              # users, jobs, job_files, job_steps, audit_log
│   ├── blueprints/          # auth, dashboard, health
│   ├── templates/           # Jinja2 + Bootstrap
│   └── static/              # CSS, JS y vendor (Bootstrap, HTMX)
├── tasks/                   # Celery
├── tests/                   # pytest
├── samples/                 # dataset de muestra (etapa 1)
├── workspace/               # un directorio por trabajo (ignorado)
├── Dockerfile
└── docker-compose.yml
```

## Tests y calidad

La suite corre en un `.venv` local con Python 3.12 (las dependencias pesadas no
hacen falta dentro de la imagen web):

```bash
make venv     # crea .venv e instala dependencias + dev
make test     # pytest
make lint     # ruff check
make fmt      # ruff format
```

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/` | Panel de trabajos (requiere sesión) |
| GET/POST | `/login` | Ingreso |
| POST | `/logout` | Cierre de sesión |
| GET | `/health` | Estado de base, core, workspace y dump |

## Relación con el proyecto base

El proyecto de escritorio vive en `~/Desarrollo/revisacatalogosweb` y se monta
**solo lectura** en `/opt/rcs-core`. El worker ejecutará sus scripts con el
directorio de trabajo en `workspace/<job>`. No se modifica el código original.

## Seguridad

- CSRF en formularios y cabecera `X-CSRFToken` para HTMX.
- Contraseñas con `werkzeug.security`.
- Sesiones `HttpOnly` y `SameSite=Lax`; `Secure` se activa con
  `SESSION_COOKIE_SECURE=1` bajo HTTPS.
- Subidas limitadas a `MAX_UPLOAD_MB`.
- El dump y el core se montan en solo lectura.
- No hay consola SQL arbitraria.

## Próximos pasos

1. Etapa 1: formulario de trabajo, subida de catálogos y cola.
2. Adaptador del pipeline con progreso en vivo.
3. Tablas de no publicados, no actualizados y repetidos.
4. Etapa 6a: restauración e integración del catálogo histórico `csn_test`.
