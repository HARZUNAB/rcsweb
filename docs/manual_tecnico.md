# Manual técnico

Documentación de instalación, operación, almacenamiento y mantenimiento de
RCS Web.

**Versión:** 0.7.3 · **Actualizado:** noviembre de 2026

## Arquitectura

RCS Web es una aplicación Flask con tareas asíncronas en Celery. La interfaz
web y el worker comparten el mismo código y el mismo espacio de trabajo; el
proyecto base se monta en solo lectura.

![Arquitectura de RCS Web](img/arquitectura.png)

| Componente | Función |
|---|---|
| **Flask web** | Interfaz, autenticación, permisos, tablas, paneles y descargas |
| **Celery worker** | Ejecuta el pipeline del proyecto base |
| **PostgreSQL** | Usuarios, trabajos, archivos, pasos, artefactos, solicitudes y auditoría |
| **Redis** | Cola de Celery |
| **Core sísmico** | Scripts de procesamiento montados en solo lectura |
| **Workspace** | Archivos de entrada y salida de cada trabajo |

## Puesta en marcha

### Requisitos

- Docker y Docker Compose.
- El proyecto base en el host, por ejemplo
  `/home/usuario/Desarrollo/revisacatalogosweb`.
- Los datos sísmicos y Cartopy en el host.
- El archivo `.env` configurado.

### Variables principales

| Variable | Uso | Valor por defecto |
|---|---|---|
| `DATABASE_URL` | Conexión SQLAlchemy | `postgresql+psycopg://rcs:rcs@db:5432/rcs` |
| `WORKSPACE_ROOT` | Carpeta de trabajos dentro del contenedor | `/workspace` |
| `RCS_CORE_PATH` | Proyecto base dentro del contenedor | `/opt/rcs-core` |
| `DATOS_PATH` | Datos de entrada dentro del contenedor | `/data` |
| `CARTOPY_DATA_DIR` | Datos de Cartopy | `/data/cartopy` |
| `MAPS_MODE` | `auto`, `online` u `offline` | `auto` |
| `ADMIN_USERNAME` | Administrador inicial | `admin` |
| `ADMIN_PASSWORD` | Clave inicial del administrador | `admin` |

Cambie `ADMIN_PASSWORD` antes de la primera puesta en marcha. `seed-admin`
solo crea el usuario si no existe; no cambia una clave existente.

### Arranque

```bash
docker compose up -d --build
docker compose ps
```

Las migraciones y el administrador inicial se ejecutan al iniciar el servicio
`web`:

```bash
docker compose exec web flask --app app db upgrade
docker compose exec web flask --app app seed-admin
```

La aplicación queda en `http://127.0.0.1:8000`.

## Servicios, puertos y volúmenes

| Servicio | Puerto host | Descripción |
|---|---|---|
| `web` | `8000` | Flask / Gunicorn |
| `db` | `5434` | PostgreSQL 16 |
| `redis` | `6380` | Redis |

| Volumen | Tipo | Contenido |
|---|---|---|
| `pgdata` | Volumen Docker | Datos de PostgreSQL |
| `redisdata` | Volumen Docker | Persistencia de Redis |
| `./workspace` | Bind mount | Archivos de los trabajos |

El servicio `web` monta además `./app`, `./tasks` y `./migrations`, y el core y
los datos en solo lectura.

## Almacenamiento

### Base de datos

- Contenedor: **`rcsweb-db`**.
- Imagen: **`postgres:16`**.
- Base de datos: **`rcs`**.
- Usuario: **`rcs`**.
- Puerto del host: **`127.0.0.1:5434`**.
- Volumen Docker: **`rcsweb_pgdata`**.
- Ruta física en el host:
  **`/var/lib/docker/volumes/rcsweb_pgdata/_data`**.
- Ruta dentro del contenedor:
  **`/var/lib/postgresql/data`**.

El volumen es un directorio de PostgreSQL, no un archivo `.db`. No se debe
editar ni copiar con la base encendida. Para inspeccionarlo:

```bash
sudo docker volume inspect rcsweb_pgdata
sudo ls -la /var/lib/docker/volumes/rcsweb_pgdata/_data
sudo du -sh /var/lib/docker/volumes/rcsweb_pgdata/_data
df -h /var/lib/docker
```

### Tablas principales

| Tabla | Contenido |
|---|---|
| `users` | Usuarios, rol, estado y hash de contraseña |
| `jobs` | Trabajos: período, estado, creador y solicitud asociada |
| `job_files` | Archivos de entrada del trabajo |
| `job_sources` | Fuentes locales y su prioridad |
| `job_steps` | Pasos del pipeline |
| `job_artifacts` | Artefactos descargables |
| `catalog_requests` | Solicitudes de catálogos por SSH |
| `audit_log` | Auditoría de acciones |

La relación de propiedad es `jobs.created_by_id → users.id`. Los trabajos
creados por solicitud usan el usuario que hizo la solicitud. Los trabajos sin
creador (datos antiguos o de demostración) solo los ven administradores y
supervisores.

### Workspace

Cada trabajo tiene una carpeta:

```text
~/Desarrollo/rcsweb/workspace/<job_id>/
```

En el contenedor se ve como `/workspace/<job_id>/`. Allí quedan los catálogos
de entrada, los resultados, los mapas, las miniaturas, los paneles y los
registros. La base guarda los metadatos; el workspace guarda los archivos.

Al eliminar un trabajo se borran su registro, sus tablas relacionadas y su
carpeta. La entrada de auditoría de la eliminación se conserva.

### Consultas útiles

```bash
sudo docker compose exec db psql -U rcs -d rcs -c "\dt"
sudo docker compose exec db psql -U rcs -d rcs \
  -c "select id, created_by_id, status, created_at from jobs order by created_at desc;"
ls ~/Desarrollo/rcsweb/workspace
```

## Respaldo y restauración

### Base de datos

Respaldo en texto:

```bash
sudo docker compose exec -T db pg_dump -U rcs -d rcs > respaldo_rcs.sql
```

Respaldo comprimido y restaurable con `pg_restore`:

```bash
sudo docker compose exec -T db pg_dump -Fc -U rcs -d rcs > respaldo_rcs.dump
```

Restauración en una base vacía:

```bash
sudo docker compose exec -T db pg_restore -U rcs -d rcs --clean --if-exists < respaldo_rcs.dump
```

### Workspace

```bash
tar -czf respaldo_workspace.tar.gz -C ~/Desarrollo/rcsweb workspace
# o
rsync -a ~/Desarrollo/rcsweb/workspace/ /respaldo/workspace/
```

La base y el workspace deben respaldarse juntos: un trabajo sin sus archivos
no se puede procesar ni descargar. Para una copia consistente, detenga el
worker y el web antes de copiar el workspace, o hágalo en una ventana sin
trabajos activos.

### Advertencias

- `docker compose down` conserva los volúmenes.
- `docker compose down -v` **elimina** `rcsweb_pgdata` y `redisdata`, y con
  ellos la base y la cola.
- No copie `/var/lib/docker/volumes/...` con PostgreSQL encendido; use
  `pg_dump`.
- Para migrar a otro servidor: lleve el dump, el workspace y el `.env`.

## Roles, permisos y propiedad

### Matriz

| Opción | Administrador | Supervisor | Analista | Consulta |
|---|:---:|:---:|:---:|:---:|
| Ver trabajos | Sí | Sí | Solo propios | Solo propios |
| Subir catálogos | Sí | Sí | Sí | — |
| Cancelar trabajo | Todos | Todos | Solo propios | — |
| Eliminar trabajo | Todos | Todos | Solo propios | — |
| Descargar artefactos | Sí | Sí | Sí | — |
| Solicitar catálogos | Sí | Sí | Sí | — |
| Ver solicitudes | Sí | Sí | Solo propias | — |
| Reintentar solicitud | Todas | Todas | Solo propias | — |
| Paneles | Sí | Sí | Sí | Sí |
| Catálogos y resultados | Sí | Sí | Sí | Sí |
| Exportar listados | Sí | Sí | Sí | — |
| Auditoría | Sí | Sí | — | — |
| Gestión de usuarios | Sí | — | — | — |

### Implementación

- `app/security.py` define los permisos, los roles, las etiquetas y los
  decoradores.
- `@permiso_requerido("...")` exige sesión y permiso; sin permiso responde
  **403**.
- El administrador tiene todos los permisos.
- `puede_ver_trabajo` y `puede_ver_solicitud` aplican la propiedad: el
  administrador y el supervisor ven todo; el analista y la consulta solo lo
  propio.
- El panel filtra la lista y las estadísticas por creador.
- La sesión de una cuenta desactivada se cierra en la siguiente petición.
- La auditoría registra los cambios de usuarios y los inicios de sesión.

Los permisos se aplican en el servidor. Ocultar un botón en la plantilla es
solo la parte visual.

### Gestión de usuarios

La pantalla **Usuarios** está disponible solo para administradores:

- crear cuentas;
- cambiar rol;
- activar o desactivar;
- restablecer contraseña.

No permite dejar el sistema sin administradores activos. El detalle de cada
usuario permite cambiar rol/estado y restablecer la clave.

### Comandos

```bash
sudo docker compose exec web flask --app app list-users
sudo docker compose exec web flask --app app set-role <usuario> <rol>
sudo docker compose exec web flask --app app reset-password <usuario>
sudo docker compose exec web flask --app app create-user <usuario> --role analista
```

Roles válidos: `admin`, `supervisor`, `analista`, `consulta`.

## Autenticación y recuperación

- Las contraseñas se guardan con hash de Werkzeug.
- El login incluye **«¿Olvidó su contraseña?»**, que explica el procedimiento.
- Las claves no se recuperan: se restablecen.
- El administrador puede restablecer desde **Usuarios**.
- Si el administrador olvidó su clave, use el comando CLI.

```bash
sudo docker compose exec web flask --app app reset-password admin
```

Si el comando no existe, el contenedor está usando código antiguo:

```bash
sudo docker compose restart web
```

Si el socket de Docker responde «permission denied», ejecute con `sudo` o
agregue el usuario al grupo `docker`. Pertenecer a `docker` equivale a permisos
de root.

## Pipeline y datos

1. Se crea el trabajo por solicitud SSH o por carga de archivos.
2. El formulario valida los archivos y el período. Si algo falla, queda en
   **Borrador** con el detalle.
3. El trabajo se encola en Redis y lo ejecuta el worker.
4. El worker corre los scripts del core con `cwd` en el workspace:
   eventquery, SeisComp, Seisan, comparaciones y repetidos.
5. Los resultados se normalizan en `workspace/<job_id>/resultados/`.
6. La interfaz lee esos archivos para las tablas, miniaturas, mapas y paneles.

El proyecto base se monta en solo lectura y no se modifica. Las miniaturas,
mapas y paneles se cachean en el workspace.

Los PNG de evento llevan un encabezado con una fila por evento: fecha, magnitud,
profundidad, coordenadas, analista, frontera y estado en la otra fuente. En los
no actualizados se agregan las filas local y publicada y la diferencia; en los
repetidos, una fila por solución. El resumen se arma en `app/services/plots.py`
y la caché usa el sufijo `_resumen` para no servir imágenes antiguas sin datos.

Los grupos de Paneles tienen dos rutas: el detalle interactivo en
`/jobs/<job>/paneles/<dataset>/<perfil|territorio>/<id>` y el PNG en la misma
ruta con `/mapa.png`. El PNG usa `generar_mapa_grupo` de
`app/services/plots.py`, no incluye filas de eventos y su encabezado declara el
dataset, la fuente, el filtro de tipo y los conteos. Los perfiles usan
`modo="auto"` (planta + perfil) y los territorios `modo="planta"`. La caché de
`workspace/<job>/plots/paneles/` incluye el grupo y los filtros en la huella.

La vista en planta del PNG ajusta el margen en `app/services/extent.py`. Con un
solo evento usa 2.0° de contexto; con varias soluciones usa
`clamp(separación × 0.5, 0.01°, 0.6°)`, donde la separación es la mayor
diferencia en grados entre las soluciones. `app/services/plot_cli.py` intercepta
`plotear._extent_planta_por_eventos` para aplicar ese margen sin modificar el
core. El perfil conserva su escala.

## Operación y diagnóstico

### Estado de los servicios

```bash
sudo docker compose ps
sudo docker compose logs --tail=100 web
sudo docker compose logs --tail=100 worker
curl -s http://127.0.0.1:8000/health
```

### Errores frecuentes

| Síntoma | Causa / solución |
|---|---|
| `no configuration file provided` | Ejecutar desde la carpeta que contiene `docker-compose.yml` |
| `permission denied ... docker.sock` | Usar `sudo` o agregar el usuario al grupo `docker` |
| `No such command 'reset-password'` | Reiniciar o reconstruir `web` con el código nuevo |
| La web no responde | Revisar `docker compose ps` y los logs de `web` |
| No hay trabajos procesados | Revisar `worker`, Redis y el log del trabajo |
| Se perdió la base | Verificar que no se ejecutó `docker compose down -v` |
| Disco lleno | Revisar `df -h /var/lib/docker` y el tamaño del workspace |

### Espacio y limpieza

- Los trabajos eliminados liberan su carpeta del workspace.
- El volumen de PostgreSQL crece con la base; use `pg_dump` para respaldos y
  limpieza controlada.
- No borre archivos sueltos del volumen de PostgreSQL.

## Desarrollo

### Entorno local

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/ruff check app tests scripts
```

### Estructura

```text
app/
  blueprints/      # auth, jobs, results, panels, admin, solicitudes
  services/        # almacenamiento, permisos, pipeline, mapas, paneles
  static/          # CSS, JavaScript y datos de regiones
  templates/       # interfaz
docs/              # manuales y capturas
scripts/           # utilidades de mantenimiento y documentación
tests/             # suite de pruebas
workspace/         # archivos por trabajo (no versionado)
```

### Documentación

Los manuales se escriben en Markdown y se convierten a `.docx` con
`scripts/generar_docs.py`, que usa `markdown`, `beautifulsoup4`, `python-docx`
y `Pillow`. No requiere LibreOffice.

```bash
.venv/bin/python scripts/generar_docs.py
```

Genera:

- `docs/manual_usuario.docx`
- `docs/manual_tecnico.docx`

Los Markdown son la fuente de verdad; no edite los `.docx` a mano.

## Seguridad

- Use contraseñas largas y cambie la clave inicial del administrador.
- No comparta el archivo `.env` ni lo versione con secretos.
- El grupo `docker` da permisos equivalentes a root; úselo solo en equipos de
  confianza.
- Restrinja el acceso a `127.0.0.1:8000` o publíquelo detrás de un proxy con
  HTTPS.
- Mantenga respaldos de la base y del workspace.
- Revise la auditoría y desactive las cuentas que ya no se usan.
- No modifique el proyecto base; se monta en solo lectura.
