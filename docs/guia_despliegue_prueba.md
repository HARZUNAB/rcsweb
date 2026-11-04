# Guía de despliegue de prueba

Esta guía describe cómo publicar una instancia de prueba de RCS Web en la máquina `10.54.218.72`, usando una cuenta dedicada `rcswebtest`, sin entregar acceso al sistema operativo y sin abrir puertos a Internet.

El resultado final es:

- una instancia separada de desarrollo;
- una base de datos y un workspace independientes;
- un usuario de aplicación para el tester;
- una URL HTTPS privada de Tailscale;
- el tester recibe solamente la URL y sus credenciales de RCS Web.

> **Importante:** el tester no debe recibir la cuenta `rcswebtest`, la cuenta `sysop`, acceso SSH, acceso a Docker ni el usuario `admin`.

## Principios de seguridad

| Elemento | Decisión |
|---|---|
| Cuenta del sistema | `rcswebtest`, bloqueada, sin `sudo` ni grupo `docker` |
| Acceso del tester | Solo aplicación web |
| Usuario de RCS | `supervisor` o `consulta`, nunca `admin` |
| Puerto de la app | `127.0.0.1:8001` |
| PostgreSQL y Redis | Sin puertos publicados al host |
| Servidor de aplicación | Gunicorn, sin `FLASK_DEBUG` |
| Acceso remoto | Tailscale Serve con HTTPS |
| Datos | Base y workspace de prueba separados |

La cuenta `/home/sysop` tiene `sudo`; no se usa para esta prueba.

## Crear la cuenta rcswebtest

Desde la cuenta `hriquelmez`:

```bash
sudo adduser --disabled-password --gecos "" rcswebtest
sudo passwd -l rcswebtest
```

Verificar que no tenga privilegios:

```bash
id rcswebtest
```

No agregar claves SSH, no incluirla en `sudo` y no incluirla en el grupo `docker`.

## Copiar el proyecto

Clonar como `hriquelmez` en `/tmp` y mover el resultado a la cuenta nueva:

```bash
git clone git@github.com:HARZUNAB/rcsweb.git /tmp/rcsweb-test
sudo mv /tmp/rcsweb-test /home/rcswebtest/rcsweb
sudo chown -R rcswebtest:rcswebtest /home/rcswebtest/rcsweb
```

Crear el workspace con el UID del usuario `rcs` del contenedor, que es `1000`:

```bash
sudo install -d -o 1000 -g 1000 /home/rcswebtest/rcsweb/workspace
```

## Configurar el archivo .env

```bash
cd /home/rcswebtest/rcsweb
sudo -u rcswebtest cp .env.example .env
sudo -u rcswebtest chmod 600 .env
```

Generar secretos nuevos:

```bash
openssl rand -hex 32
openssl rand -hex 24
```

Editar el archivo:

```bash
sudo -u rcswebtest nano .env
```

Valores mínimos que deben quedar configurados:

```dotenv
SECRET_KEY=<resultado de openssl rand -hex 32>

POSTGRES_USER=rcs
POSTGRES_PASSWORD=<otra clave larga>
POSTGRES_DB=rcs
DATABASE_URL=postgresql+psycopg://rcs:<la misma clave>@db:5432/rcs

ADMIN_USERNAME=admin
ADMIN_PASSWORD=<contraseña fuerte>

RCS_CORE_PATH_HOST=/home/hriquelmez/Desarrollo/revisacatalogosweb
RCS_CORE_PATH=/opt/rcs-core

DATOS_PATH_HOST=/home/hriquelmez/datos
DATOS_PATH=/data

CARTOPY_DATA_DIR_HOST=/home/hriquelmez/datos/cartopy
CARTOPY_DATA_DIR=/data/cartopy

SESSION_COOKIE_SECURE=1
```

`SESSION_COOKIE_SECURE=1` se usa porque la URL de Tailscale será HTTPS.

Si el tester va a crear trabajos reales, configure también las fuentes SSH y SeisComp con credenciales de prueba o de solo lectura. No use credenciales de escritura de producción.

## Crear el compose de prueba

En `/home/rcswebtest/rcsweb` crear:

```bash
sudo -u rcswebtest nano docker-compose.test.yml
```

Contenido:

```yaml
services:
  db:
    container_name: rcsweb-test-db
    ports: !reset []

  redis:
    container_name: rcsweb-test-redis
    ports: !reset []

  web:
    container_name: rcsweb-test-web
    ports: !override
      - "127.0.0.1:8001:8000"
    environment:
      FLASK_DEBUG: "0"
    command: >
      sh -c "flask --app app db upgrade &&
             flask --app app seed-admin &&
             gunicorn --bind 0.0.0.0:8000 --workers 2 --access-logfile - 'app:create_app()'"

  worker:
    container_name: rcsweb-test-worker
```

Este archivo:

- quita los puertos públicos de PostgreSQL y Redis;
- publica la app solo en `127.0.0.1:8001`;
- desactiva Flask debug;
- usa Gunicorn en lugar del servidor de desarrollo;
- usa nombres de contenedor distintos para no chocar con desarrollo.

Los tags `!reset` y `!override` requieren Docker Compose 2.24 o superior. En esta máquina hay Compose 2.40.

## Levantar la instancia

Desde `hriquelmez`, con `sudo`:

```bash
cd /home/rcswebtest/rcsweb

sudo docker compose \
  -p rcsweb-test \
  -f docker-compose.yml \
  -f docker-compose.test.yml \
  up -d --build
```

Verificar:

```bash
sudo docker compose -p rcsweb-test ps
curl -fsS http://127.0.0.1:8001/health
```

Ver logs si algo falla:

```bash
sudo docker compose -p rcsweb-test logs -f web
```

## Crear el usuario del tester

Para una prueba funcional completa, usar `supervisor`: ve todo, pero no administra usuarios.

```bash
sudo docker compose -p rcsweb-test exec web \
  flask --app app create-user tester --role supervisor
```

El comando pedirá una contraseña. Usar una contraseña fuerte y distinta de las de desarrollo.

Si el tester debe ver solo datos restringidos, usar `consulta` con un código que exista en los datos de prueba:

```bash
sudo docker compose -p rcsweb-test exec web \
  flask --app app create-user tester \
  --role consulta \
  --analyst-code PRUEBA
```

No entregar el usuario `admin`.

## Publicar con Tailscale

Instalar Tailscale en la máquina:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Autenticar la máquina con la cuenta de Tailscale.

Publicar la app local en la tailnet:

```bash
sudo tailscale serve --bg 8001
sudo tailscale serve status
```

Tailscale mostrará una URL similar a:

```text
https://rcsweb-test.tailXXXX.ts.net/
```

Esa es la URL que se entrega. No abrir el puerto `8001` en el firewall ni en el router.

Si Tailscale indica que HTTPS no está habilitado, habilitarlo en la consola de administración de Tailscale (DNS y certificados).

## Dar acceso al tester

El tester debe:

1. Instalar Tailscale.
2. Iniciar sesión o aceptar la invitación a la tailnet.
3. Abrir la URL.

Si el tester es externo, invitarlo a la tailnet o compartir el nodo desde la consola de Tailscale. Si la política de Tailscale lo permite, restringir su acceso únicamente al nodo de prueba.

## Entrega final

Entregar solamente:

```text
URL: https://rcsweb-test.tailXXXX.ts.net/
Usuario RCS: tester
Contraseña: <contraseña fuerte>
```

No entregar:

- usuario o contraseña de `rcswebtest`;
- usuario o contraseña de `sysop`;
- acceso SSH;
- usuario `admin`;
- acceso a Docker;
- la base de datos de desarrollo.

## Verificación antes de entregar

```bash
# La app escucha solo en localhost
ss -ltnp | grep 8001

# Contenedores de prueba
sudo docker compose -p rcsweb-test ps

# Tailscale está sirviendo
sudo tailscale serve status

# Debug apagado
sudo docker compose -p rcsweb-test exec web printenv FLASK_DEBUG
```

El último comando debe mostrar:

```text
0
```

Probar desde el equipo del tester:

```text
https://rcsweb-test.tailXXXX.ts.net/
```

## Alternativa para red local

Si el tester está en la misma red `10.54.218.0/24` y no puede usar Tailscale, se puede publicar solo en la IP privada.

Cambiar en `docker-compose.test.yml`:

```yaml
ports: !override
  - "10.54.218.72:8001:8000"
```

Permitir solo la IP del tester:

```bash
sudo ufw allow from <IP_DEL_TESTER> to any port 8001 proto tcp
```

Y usar en `.env`:

```dotenv
SESSION_COOKIE_SECURE=0
```

La URL sería:

```text
http://10.54.218.72:8001
```

Esta opción solo debe usarse si el tester está dentro de la red corporativa o entra por VPN. No abrir este puerto a Internet.

## Detener la instancia

```bash
sudo docker compose \
  -p rcsweb-test \
  -f docker-compose.yml \
  -f docker-compose.test.yml \
  down
```

Esto detiene los contenedores, pero conserva los volúmenes de prueba. Para borrar también la base y Redis de prueba:

```bash
sudo docker compose \
  -p rcsweb-test \
  -f docker-compose.yml \
  -f docker-compose.test.yml \
  down -v
```

Usar `down -v` solo si se quiere descartar toda la base de prueba.

## Anexo A. Actualizar la app de prueba con avances de desarrollo

### A.1 Flujo en la máquina de desarrollo

Antes de actualizar la instancia de prueba, validar en `/home/hriquelmez/Desarrollo/rcsweb`:

```bash
cd /home/hriquelmez/Desarrollo/rcsweb
.venv/bin/ruff check app tests scripts
.venv/bin/pytest -q
git status
```

Si todo pasa, registrar el avance:

```bash
git add -A
git commit -m "Descripción del avance"
git push origin main
```

Si el avance cambia mapas, revisar `VERSION_MAPAS` en `app/services/catalog_export.py` para invalidar la caché de imágenes. Si cambia la versión visible de la app, revisar `APP_VERSION`.

### A.2 Actualización por rsync

Es la forma más simple cuando desarrollo y prueba están en la misma máquina.

Antes de actualizar, crear un respaldo del código y la configuración de prueba (sin workspace ni `.env`):

```bash
sudo mkdir -p /home/rcswebtest/backups
sudo tar czf /home/rcswebtest/backups/rcsweb-code-$(date +%F-%H%M).tgz \
  -C /home/rcswebtest rcsweb \
  --exclude=rcsweb/workspace \
  --exclude=rcsweb/.env
```

Copiar solo el código, preservando `.env`, `docker-compose.test.yml` y `workspace`:

```bash
sudo rsync -a --delete --chown=rcswebtest:rcswebtest \
  --exclude '.env' \
  --exclude 'docker-compose.test.yml' \
  --exclude 'workspace/' \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  /home/hriquelmez/Desarrollo/rcsweb/ /home/rcswebtest/rcsweb/
```

Notas:

- `--delete` no elimina los archivos excluidos.
- El workspace de prueba no se toca.
- El `.env` de prueba no se sobrescribe.
- Si cambió `.env.example`, comparar y actualizar manualmente el `.env` de prueba.
- Si se agregaron dependencias en `pyproject.toml`, será necesario reconstruir la imagen.

### A.3 Alternativa por Git

Si la cuenta `rcswebtest` tiene una deploy key de solo lectura o se usa HTTPS con token, se puede actualizar con Git:

```bash
sudo -u rcswebtest git -C /home/rcswebtest/rcsweb pull --ff-only
```

El `.env` y `docker-compose.test.yml` no están versionados, así que no se sobrescriben.

Para volver a una versión anterior:

```bash
sudo -u rcswebtest git -C /home/rcswebtest/rcsweb log --oneline
sudo -u rcswebtest git -C /home/rcswebtest/rcsweb checkout <commit>
```

### A.4 Reiniciar o reconstruir

Si solo cambiaron archivos Python, plantillas, JavaScript o CSS, basta reiniciar los procesos para que tomen el código montado:

```bash
cd /home/rcswebtest/rcsweb

sudo docker compose \
  -p rcsweb-test \
  -f docker-compose.yml \
  -f docker-compose.test.yml \
  restart web worker
```

Si cambió `pyproject.toml`, el `Dockerfile` o una dependencia, reconstruir:

```bash
sudo docker compose \
  -p rcsweb-test \
  -f docker-compose.yml \
  -f docker-compose.test.yml \
  up -d --build
```

Si cambió `.env` o `docker-compose.test.yml`, recrear los contenedores:

```bash
sudo docker compose \
  -p rcsweb-test \
  -f docker-compose.yml \
  -f docker-compose.test.yml \
  up -d --force-recreate
```

El servicio `web` ejecuta `flask --app app db upgrade` al iniciar, por lo que las migraciones nuevas se aplican al reiniciar o recrear.

### A.5 Migraciones y respaldo de la base de prueba

Antes de una actualización con migraciones nuevas, se puede respaldar la base de prueba:

```bash
sudo docker compose -p rcsweb-test exec -T db \
  pg_dump -U rcs -d rcs > /home/rcswebtest/backups/rcs-test-$(date +%F-%H%M).sql
```

Verificar que la migración terminó bien:

```bash
sudo docker compose -p rcsweb-test logs --tail=100 web
```

Si la migración falla, revisar el error y restaurar el respaldo solo si es necesario. La base de prueba no debe contener datos de producción sin autorización.

### A.6 Caché del navegador

Si el avance cambia mapas, JavaScript o estilos:

- subir `VERSION_MAPAS` si cambiaron los mapas;
- hacer **Ctrl+F5** en el navegador;
- probar en una ventana incógnita si hay dudas;
- verificar que la URL de los mapas incluya la nueva versión.

La app ya usa versionado en las URLs de mapas y `cache: "no-store"` en las peticiones de catálogo, pero otros archivos estáticos pueden requerir recarga forzada.

### A.7 Verificación después de actualizar

```bash
cd /home/rcswebtest/rcsweb

sudo docker compose -p rcsweb-test ps
curl -fsS http://127.0.0.1:8001/health
sudo docker compose -p rcsweb-test logs --tail=80 web
sudo tailscale serve status
```

Luego, desde la URL:

1. iniciar sesión con el usuario de prueba;
2. abrir un trabajo;
3. probar la pantalla modificada;
4. probar un mapa si el cambio lo afecta;
5. confirmar que la versión o el texto esperado aparece.

### A.8 Rollback

Si la actualización falla, restaurar el respaldo de código:

```bash
sudo tar xzf /home/rcswebtest/backups/rcsweb-code-<fecha>.tgz \
  -C /home/rcswebtest
```

Luego reiniciar:

```bash
sudo docker compose \
  -p rcsweb-test \
  -f docker-compose.yml \
  -f docker-compose.test.yml \
  restart web worker
```

Si se usó Git, también se puede volver a un commit anterior con `git checkout`.

Si la migración de base fue el problema, restaurar el respaldo SQL en la base de prueba. No revertir una migración de producción sin revisar el impacto.

### A.9 Checklist de actualización

| Paso | Verificación |
|---|---|
| Desarrollo | `ruff` limpio, pruebas pasando |
| Commit | Cambios confirmados y subidos |
| Respaldo | Código y `.env` respaldados |
| Copia | `.env`, workspace y compose de prueba preservados |
| Dependencias | Rebuild si cambió `pyproject.toml` |
| Migraciones | Logs de `db upgrade` sin errores |
| Procesos | `web` y `worker` reiniciados o recreados |
| Salud | `/health` responde |
| Tailscale | `serve status` activo |
| Prueba funcional | Login, trabajo y pantalla revisada |
| Caché | Ctrl+F5 / incógnito si corresponde |

## Anexo B. Problemas frecuentes

| Síntoma | Revisión |
|---|---|
| La URL de Tailscale no responde | `sudo tailscale serve status` y `sudo tailscale status` |
| La app no responde en localhost | `sudo docker compose -p rcsweb-test ps` y logs de `web` |
| Error `port is already allocated` | Cambiar `8001` por otro puerto en el compose de prueba |
| `Permission denied` en workspace | `sudo chown -R 1000:1000 /home/rcswebtest/rcsweb/workspace` |
| `password authentication failed` | `POSTGRES_PASSWORD` y `DATABASE_URL` deben coincidir |
| El tester no ve eventos | Revisar rol y código de analista; para ver todo usar `supervisor` |
| Login en bucle | `SESSION_COOKIE_SECURE=1` requiere HTTPS; si se prueba por HTTP, usar `0` |
| Los mapas no cambian | Ctrl+F5, ventana incógnita y revisar `VERSION_MAPAS` |
| `docker compose` no acepta `!reset` | Actualizar Docker Compose a 2.24 o superior |
| No se puede hacer `git pull` en prueba | Usar la actualización por `rsync` |

## Anexo C. Checklist de entrega al tester

| Requisito | Confirmado |
|---|---|
| Cuenta `rcswebtest` bloqueada | Sí / No |
| La cuenta no tiene `sudo` | Sí / No |
| La cuenta no está en el grupo `docker` | Sí / No |
| El tester no recibe acceso SSH | Sí / No |
| `FLASK_DEBUG=0` | Sí / No |
| PostgreSQL y Redis sin puertos públicos | Sí / No |
| App publicada solo en `127.0.0.1:8001` | Sí / No |
| Tailscale Serve activo | Sí / No |
| Usuario de RCS creado con rol limitado | Sí / No |
| Usuario `admin` no entregado | Sí / No |
| URL y credenciales de RCS enviadas | Sí / No |

La entrega debe ser:

```text
URL: https://rcsweb-test.tailXXXX.ts.net/
Usuario RCS: tester
Contraseña: <contraseña fuerte>
```

No se entrega ningún acceso al sistema operativo.
