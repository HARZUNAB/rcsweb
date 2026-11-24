## Anexo D. Parámetros y configuración

Este anexo reúne los valores que gobiernan el comportamiento de RCS Web. La fuente de verdad es `docs/parametros.toml`; las tablas se generan con `scripts/generar_parametros.py --write` y se validan en las pruebas con `--check`.

Incluye variables de entorno, flags de scripts y constantes numéricas o booleanas que cambian el comportamiento. Excluye estados, etiquetas, rutas y constantes puramente visuales.

La columna **Módulo** muestra el archivo y la línea actual donde se define el valor. Si el código se mueve, el número se actualiza al regenerar el anexo.

### D.0 Índice de parámetros

| Sección | Contenido | Página |
|---|---|---|
| D.1 | Variables de entorno | [[PAGEREF:_D_1]] |
| D.2 | Constantes de módulos | [[PAGEREF:_D_2]] |
| D.3 | Parámetros de scripts | [[PAGEREF:_D_3]] |
| D.4 | Parámetros por trabajo | [[PAGEREF:_D_4]] |
| D.5 | Reglas y umbrales | [[PAGEREF:_D_5]] |

> Las páginas se resuelven al actualizar el índice en el DOCX. En Markdown no existe paginación.

Resumen: 61 variables de entorno, 96 constantes y 17 parámetros de scripts.

### D.1 Variables de entorno

Se leen al arrancar la aplicación o el servicio. Cambiarlas requiere reiniciar el contenedor correspondiente.


**Aplicación y sesiones**

| Variable | Módulo | Defecto | Ámbito | Efecto |
|---|---|---|---|---|
| `ADMIN_PASSWORD` | `app/cli.py:43` | `admin` | despliegue | Clave inicial del administrador. Cambiar antes del primer arranque. |
| `ADMIN_USERNAME` | `app/cli.py:42` | `admin` | despliegue | Usuario administrador inicial creado por seed-admin. |
| `APP_VERSION` | `app/config.py:30` | `0.8.0` | despliegue | Versión visible de la aplicación. |
| `CARTOPY_DATA_DIR` | `app/services/plot_cli.py:31` | `—` | despliegue | Datos de Cartopy para mapas offline. |
| `DATOS_PATH` | `app/config.py:60` | `/data` | despliegue | Datos externos montados dentro del contenedor. |
| `MAPS_MODE` | `app/services/maps.py:33` | `auto` | despliegue | Modo de mapas: auto, online u offline. |
| `MAX_UPLOAD_MB` | `app/config.py:31` | `200` | despliegue | Tamaño máximo de archivos subidos, en MB. |
| `RCS_CORE_DATA` | `app/config.py:54` | `BASE_DIR / 'core_data'` | despliegue | Datos grandes del core (grillas, catálogo sísmico). |
| `RCS_CORE_PATH` | `app/config.py:51` | `BASE_DIR / 'core'` | despliegue | Código del core dentro del contenedor. |
| `SECRET_KEY` | `app/config.py:29` | `dev-insecure-cambiar` | despliegue | Clave de firma de sesiones y formularios. Cambiar en producción. |
| `SESSION_COOKIE_SECURE` | `app/config.py:43` | `0` | despliegue | Exige HTTPS para la cookie de sesión (1 = sí). |
| `WORKSPACE_ROOT` | `app/config.py:50` | `BASE_DIR / 'workspace'` | despliegue | Carpeta de trabajos dentro del contenedor. |

**Base de datos**

| Variable | Módulo | Defecto | Ámbito | Efecto |
|---|---|---|---|---|
| `DATABASE_URL` | `app/config.py:35` | `postgresql+psycopg://rcs:rcs@db:5432/rcs` | despliegue | Conexión SQLAlchemy a PostgreSQL de la aplicación. |

**Catálogos y fuentes**

| Variable | Módulo | Defecto | Ámbito | Efecto |
|---|---|---|---|---|
| `CATALOGOS_SSH_HOST` | `app/forms.py:71` | `10.54.217.9` | despliegue | Servidor SSH para descargar catálogos. |
| `CATALOGOS_SSH_USER` | `app/forms.py:75` | `sysopr` | despliegue | Usuario SSH para descargar catálogos. |
| `CATALOG_SOURCES_MANIFEST` | `app/domain/catalogs/manifest.py:89` | `—` | despliegue | Ruta alternativa del manifiesto de fuentes. |
| `CSN_DUMP_PATH` | `app/blueprints/health.py:41` | `/data/csn/dumps/csn_test_full_2026-09-30.dump` | despliegue | Dump de la base CSN usado por el chequeo de salud. |
| `DEFAULT_PRIMARY_LOCAL` | `app/domain/catalogs/registry.py:146` | `local_export` | despliegue | Fuente local principal por defecto (local_export o local_select). |
| `RCS_CATALOGO_SISMICIDAD` | `app/config.py:57` | `base_2018_2026.dat` | despliegue | Archivo del catálogo sísmico histórico. |
| `RCS_CENTRAL_DSN` | `app/config.py:74` | `—` | despliegue | DSN de solo lectura de la base central CSN. |
| `RCS_DATA_DIR` | `core/exporta_ventana_seiscomp.py:612` | `—` | despliegue | Directorio de datos del core para exportaciones. |
| `RCS_RECORDSTREAM` | `core/disponibilidad.py:107` | `—` | despliegue | Comando de recordstream; si está vacío se lee de global.cfg. |
| `RCS_SCART` | `core/disponibilidad.py:76` | `—` | despliegue | Comando o ruta de scart para consultar la base. |
| `RCS_SDS_ROOT` | `core/disponibilidad.py:71` | `—` | despliegue | Raíz del SDS con formas de onda. |
| `RCS_SEISAN_STATIONS_DIR` | `app/config.py:64` | `str(DATOS_PATH / 'csn' / 'datseisan')` | despliegue | Directorio de listas de estaciones de Seisan. |
| `RCS_VETO_TENDENCIA` | `core/sismicidad.py:86` | `1` | despliegue | Activa el veto por tendencia histórica (1 = sí). |
| `RV_ENTREGABLES` | `core/rutas.py:41` | `—` | despliegue | Directorio de entregables del pipeline. |
| `RV_PROG` | `core/prog.py:25` | `—` | despliegue | Directorio de programas del pipeline. |
| `SEISCOMP_DB_HOST` | `app/services/amplification.py:36` | `—` | despliegue | Host de la base SeisComp. |
| `SEISCOMP_DB_NAME` | `app/services/amplification.py:112` | `seiscomp2` | despliegue | Nombre de la base SeisComp. |
| `SEISCOMP_DB_PASSWORD` | `app/services/amplification.py:38` | `—` | despliegue | Clave del usuario de SeisComp. |
| `SEISCOMP_DB_PORT` | `app/services/amplification.py:115` | `5432` | despliegue | Puerto de la base SeisComp. |
| `SEISCOMP_DB_USER` | `app/services/amplification.py:37` | `—` | despliegue | Usuario de solo lectura de SeisComp. |
| `SEISCOMP_RADIO_KM` | `app/forms.py:80` | `400` | despliegue | Radio de exportación de estaciones del catálogo. |
| `SEISCOMP_ROOT` | `core/disponibilidad.py:79` | `—` | despliegue | Raíz de la instalación de SeisComp. |

**Celery y pipeline**

| Variable | Módulo | Defecto | Ámbito | Efecto |
|---|---|---|---|---|
| `CELERY_BROKER_URL` | `app/config.py:109` | `redis://redis:6379/0` | despliegue | Broker de Celery. |
| `CELERY_RESULT_BACKEND` | `app/config.py:110` | `redis://redis:6379/1` | despliegue | Backend de resultados de Celery. |
| `PIPELINE_STEP_TIMEOUT` | `app/services/pipeline.py:54` | `1800` | despliegue | Timeout por paso del pipeline, en segundos. |
| `RCS_ENRIQUECER_RESIDUALES` | `app/services/pipeline.py:439` | `1` | despliegue | Enriquece residuales con fuentes locales (1 = sí). |

**Disponibilidad de ondas**

| Variable | Módulo | Defecto | Ámbito | Efecto |
|---|---|---|---|---|
| `RCS_DISPONIBILIDAD_HOST` | `app/services/availability_service.py:241` | `0.0.0.0` | despliegue | Interfaz donde escucha el sidecar. |
| `RCS_DISPONIBILIDAD_MAX_ESTACIONES` | `app/config.py:122` | `150` | despliegue | Máximo de estaciones por consulta. |
| `RCS_DISPONIBILIDAD_MAX_STREAMS` | `app/config.py:125` | `5000` | despliegue | Máximo duro de streams por consulta. |
| `RCS_DISPONIBILIDAD_PORT` | `app/services/availability_service.py:242` | `8010` | despliegue | Puerto del sidecar. |
| `RCS_DISPONIBILIDAD_TIMEOUT` | `app/config.py:119` | `240` | despliegue | Timeout de la consulta de disponibilidad, en segundos. |
| `RCS_DISPONIBILIDAD_TOKEN` | `app/config.py:116` | `—` | despliegue | Token compartido con el sidecar. |
| `RCS_DISPONIBILIDAD_URL` | `app/config.py:113` | `—` | despliegue | URL del sidecar de disponibilidad. |

**Informes y correo**

| Variable | Módulo | Defecto | Ámbito | Efecto |
|---|---|---|---|---|
| `MAIL_DEFAULT_SENDER` | `app/config.py:97` | `rcsweb@localhost` | despliegue | Remitente por defecto. |
| `MAIL_FROM_NAME` | `app/config.py:100` | `RCS Web` | despliegue | Nombre visible del remitente. |
| `MAIL_PASSWORD` | `app/config.py:96` | `—` | despliegue | Clave SMTP. |
| `MAIL_PORT` | `app/config.py:92` | `25` | despliegue | Puerto SMTP. |
| `MAIL_SERVER` | `app/config.py:91` | `—` | despliegue | Servidor SMTP. |
| `MAIL_SIGNATURE` | `app/config.py:101` | `RCS Web\|Centro Sismológico Nacional\|Universidad de Chile` | despliegue | Firma al pie de los correos. |
| `MAIL_SUPPRESS_SEND` | `app/config.py:106` | `0` | despliegue | No envía correos; solo los registra (1 = sí). |
| `MAIL_TIMEOUT` | `app/config.py:105` | `10` | despliegue | Timeout SMTP, en segundos. |
| `MAIL_USERNAME` | `app/config.py:95` | `—` | despliegue | Usuario SMTP. |
| `MAIL_USE_SSL` | `app/config.py:93` | `0` | despliegue | Usa SSL para el correo (1 = sí). |
| `MAIL_USE_TLS` | `app/config.py:94` | `0` | despliegue | Usa TLS para el correo (1 = sí). |
| `RCS_EVIDENCIA_MAX_MB` | `app/config.py:80` | `20` | despliegue | Tamaño máximo de la evidencia de cierre, en MB. |
| `RCS_INFORME_MAX_EVENTOS` | `app/config.py:77` | `50` | despliegue | Máximo de eventos por solicitud de revisión. |
| `RCS_NOTIFICAR_REVISION_DEFAULT` | `app/config.py:85` | `0` | despliegue | Preselecciona la notificación por correo (1 = sí). |
| `RCS_PUBLIC_URL` | `app/config.py:88` | `—` | despliegue | URL pública usada en los enlaces de los correos. |

### D.2 Constantes de módulos

Son valores de código. Cambiarlos exige modificar el módulo, revisar las pruebas y regenerar la caché que dependa de ellos.

**Adaptadores**

| Constante | Módulo | Valor | Ámbito | Efecto |
|---|---|---|---|---|
| `TOL_EVENTO_KM` | `app/domain/catalogs/adapters/residuals.py:32` | `5.0` | operación | Tolerancia geográfica para emparejar evento, en km. |
| `TOL_EVENTO_S` | `app/domain/catalogs/adapters/residuals.py:31` | `2.0` | operación | Tolerancia temporal para emparejar evento, en segundos. |
| `TOL_PICK_S` | `app/domain/catalogs/adapters/residuals.py:33` | `0.5` | operación | Tolerancia temporal para emparejar pick, en segundos. |
| `_TTL_DISPONIBILIDAD` | `app/domain/catalogs/adapters/central.py:178` | `300` | operación | Vigencia de la caché de disponibilidad de Central, en segundos. |

**Correlación y señal**

| Constante | Módulo | Valor | Ámbito | Efecto |
|---|---|---|---|---|
| `MAX_CANDIDATOS` | `core/correlacion.py:42` | `200` | operación | Máximo de candidatas por consulta al sidecar. |
| `MAX_VENTANA_S` | `core/correlacion.py:43` | `600.0` | operación | Duración máxima de la ventana analizada, en segundos. |
| `MIN_MUESTRAS` | `core/correlacion.py:44` | `50` | operación | Muestras mínimas para calcular métricas. |
| `VERSION` | `core/correlacion.py:22` | `1` | operación | Versión del contrato de correlación. |

**Cruces y comparación**

| Constante | Módulo | Valor | Ámbito | Efecto |
|---|---|---|---|---|
| `DECIMALES_COORDENADA` | `core/comparacion.py:26` | `3` | operación | Decimales usados al comparar coordenadas. |
| `DECIMALES_MAGNITUD` | `core/comparacion.py:28` | `1` | operación | Decimales usados al comparar magnitud. |
| `DECIMALES_PROFUNDIDAD` | `core/comparacion.py:27` | `1` | operación | Decimales usados al comparar profundidad. |
| `DIF_DIST_KM` | `core/cruce_noact.py:38` | `0.5` | operación | Diferencia de distancia para marcar no actualizado, en km. |
| `DIF_DT_SEG` | `core/cruce_noact.py:39` | `0.5` | operación | Diferencia temporal para marcar no actualizado, en segundos. |
| `GRADO_KM_LAT` | `core/sismicidad.py:34` | `111.0` | operación | Kilómetros por grado de latitud en el catálogo. |
| `MAX_LAT_LON_AMPLIO` | `core/repetidos.py:54` | `2.0` | operación | Diferencia geográfica máxima del criterio amplio, en grados. |
| `MAX_LAT_LON_ESTRICTO` | `core/repetidos.py:56` | `1.0` | operación | Diferencia geográfica máxima del criterio estricto, en grados. |
| `MAX_SEG_AMPLIO` | `core/repetidos.py:53` | `6` | operación | Diferencia temporal máxima del criterio amplio, en segundos. |
| `MAX_SEG_ESTRICTO` | `core/repetidos.py:55` | `3` | operación | Diferencia temporal máxima del criterio estricto, en segundos. |
| `RADIO_TIERRA_KM` | `app/services/attribution.py:17` | `6371.0088` | operación | Radio terrestre usado en atribución. |
| `RADIO_TIERRA_KM` | `core/comparacion.py:39` | `6371.0088` | operación | Radio terrestre usado en distancias geodésicas. |
| `TOLERANCIA_COORDENADA` | `core/comparacion.py:36` | `0.005` | operación | Tolerancia de coordenada para considerar el mismo evento. |
| `TOL_DUPLICADO_GRADOS` | `core/cruce_noact.py:35` | `1.0` | operación | Tolerancia geográfica para duplicados, en grados. |
| `TOL_GRADOS` | `core/cruza_nopub.py:54` | `0.5` | operación | Tolerancia geográfica del cruce, en grados. |
| `TOL_REVISION_GRADOS` | `core/cruza_nopub.py:59` | `2.0` | operación | Tolerancia geográfica para revisión, en grados. |
| `VENTANA_DUPLICADO_SEG` | `core/cruce_noact.py:34` | `3.0` | operación | Ventana temporal para detectar duplicados, en segundos. |
| `VENTANA_REVISION_SEG` | `core/cruza_nopub.py:58` | `120.0` | operación | Ventana temporal para revisión, en segundos. |
| `VENTANA_SEG` | `core/cruza_nopub.py:53` | `6.0` | operación | Ventana temporal del cruce con no publicados, en segundos. |

**Disponibilidad**

| Constante | Módulo | Valor | Ámbito | Efecto |
|---|---|---|---|---|
| `MAX_BODY` | `app/services/availability_service.py:47` | `2097152` | operación | Tamaño máximo del cuerpo HTTP, en bytes. |
| `MAX_STREAMS` | `app/services/availability_service.py:46` | `5000` | operación | Máximo de streams por consulta en el sidecar. |
| `TAMANO_LOTE` | `app/services/availability_service.py:48` | `300` | operación | Streams por lote en la consulta. |
| `TAREA_TTL` | `app/services/availability.py:33` | `900` | operación | Vigencia del registro de tarea, en segundos. |
| `TIMEOUT` | `core/disponibilidad.py:43` | `20.0` | operación | Timeout de lectura del SDS o recordstream, en segundos. |
| `VENTANA_MINUTOS` | `core/disponibilidad.py:39` | `10.0` | operación | Ventana de tolerancia para considerar datos disponibles, en minutos. |

**Exportación SeisComp**

| Constante | Módulo | Valor | Ámbito | Efecto |
|---|---|---|---|---|
| `ACTIVIDAD_HORAS` | `core/exporta_ventana_seiscomp.py:202` | `2.0` | operación | Ventana de actividad para estimar disponibilidad, en horas. |
| `AVISO_DE_LOTES` | `core/exporta_ventana_seiscomp.py:179` | `200000` | operación | Número de filas que dispara el aviso de volumen. |
| `AVISO_NO_PICADAS_MB` | `core/exporta_ventana_seiscomp.py:1158` | `200.0` | operación | Tamaño que dispara el aviso de no picadas, en MB. |
| `GRADO_CELDA` | `core/exporta_ventana_seiscomp.py:1174` | `1.0` | operación | Tamaño de celda geográfica, en grados. |
| `NO_PICADAS_BYTES_FILA` | `core/exporta_ventana_seiscomp.py:1154` | `154` | operación | Bytes estimados por fila de estaciones sin arribos. |
| `RADIO_ESTACIONES_KM` | `core/exporta_ventana_seiscomp.py:192` | `400.0` | operación | Radio de búsqueda de estaciones, en km. |
| `RADIO_TIERRA_KM` | `core/exporta_ventana_seiscomp.py:1167` | `110.574` | operación | Kilómetros por grado de latitud para celdas. |
| `RADIO_TIERRA_LON_KM` | `core/exporta_ventana_seiscomp.py:1168` | `111.32` | operación | Kilómetros por grado de longitud en el ecuador. |
| `RANGO_MAG_ESTACION` | `core/exporta_ventana_seiscomp.py:184` | `(-1.0, 10.0)` | operación | Rango válido de magnitud por estación. |
| `STATEMENT_TIMEOUT_MS` | `core/exporta_ventana_seiscomp.py:171` | `60000` | operación | Timeout de sentencia SQL, en milisegundos. |
| `TAMANO_LOTE` | `core/exporta_ventana_seiscomp.py:175` | `5000` | operación | Filas por lote en la exportación. |
| `TIMEOUT_CONEXION` | `core/exporta_ventana_seiscomp.py:164` | `10` | operación | Timeout de conexión a la base, en segundos. |

**Indicios y prioridad**

| Constante | Módulo | Valor | Ámbito | Efecto |
|---|---|---|---|---|
| `CRUCE_AMPLIO_GRADOS` | `app/services/indicios.py:1296` | `2.0` | regla | Tolerancia geográfica del cruce amplio, en grados. |
| `CRUCE_AMPLIO_SEG` | `app/services/indicios.py:1295` | `6.0` | regla | Tolerancia temporal del cruce amplio, en segundos. |
| `CRUCE_ESTRICTO_GRADOS` | `app/services/indicios.py:1294` | `1.0` | regla | Tolerancia geográfica del cruce estricto, en grados. |
| `CRUCE_ESTRICTO_SEG` | `app/services/indicios.py:1293` | `3.0` | regla | Tolerancia temporal del cruce estricto, en segundos. |
| `ESQUEMA_INDICIOS` | `app/services/indicios.py:46` | `7` | regla | Versión del esquema de indicios. |
| `FACTOR_RESIDUAL_EXTREMO` | `app/services/indicios.py:38` | `10.0` | regla | Factor para clasificar residual extremo. |
| `MAX_PARES_DETALLE` | `app/services/indicios.py:45` | `40` | regla | Máximo de pares guardados en el detalle. |
| `MIN_ESTACIONES_FASE` | `app/services/indicios.py:36` | `3` | regla | Estaciones mínimas para evaluar un patrón de fase. |
| `SEPARACION_MINIMA_KM` | `app/services/indicios.py:35` | `20.0` | regla | Separación mínima entre estaciones, en km. |
| `UMBRAL_CONTEXTO_AZGAP` | `app/services/indicios.py:44` | `180.0` | regla | Azimutal gap máximo para cobertura suficiente. |
| `UMBRAL_CONTEXTO_ESTACIONES` | `app/services/indicios.py:42` | `5` | regla | Estaciones mínimas para considerar cobertura suficiente. |
| `UMBRAL_CONTEXTO_SIN_INVENTARIO` | `app/services/indicios.py:43` | `8` | regla | Umbral de estaciones cuando no hay inventario. |
| `UMBRAL_PESO` | `app/services/indicios.py:30` | `0.5` | regla | Peso que se considera influyente. |
| `UMBRAL_PESO_INFLUYENTE` | `app/services/indicios.py:31` | `0.125` | regla | Peso mínimo para marcar una fase influyente. |
| `UMBRAL_RESIDUAL` | `app/services/indicios.py:29` | `5.0` | regla | Residual alto, en segundos. |
| `UMBRAL_RESIDUAL_EXTREMO` | `app/services/indicios.py:37` | `60.0` | regla | Residual extremo, en segundos. |
| `UMBRAL_RESIDUAL_FUERA_DE_ORDEN` | `app/services/indicios.py:32` | `5.0` | regla | Residual fuera de orden, en segundos. |
| `UMBRAL_RESIDUAL_FUERA_DE_ORDEN_DEBIL` | `app/services/indicios.py:34` | `5.0` | regla | Residual débil fuera de orden, en segundos. |
| `UMBRAL_SISTEMATICO_ESTACIONES` | `app/services/indicios.py:39` | `5` | regla | Estaciones mínimas para un sesgo sistemático. |
| `UMBRAL_SISTEMATICO_MEDIANA` | `app/services/indicios.py:41` | `2.0` | regla | Residual mediano para un sesgo sistemático. |
| `UMBRAL_SISTEMATICO_PROPORCION` | `app/services/indicios.py:40` | `0.7` | regla | Proporción mínima para un sesgo sistemático. |
| `UMBRAL_TIEMPO_FUERA_DE_ORDEN_S` | `app/services/indicios.py:33` | `2.0` | regla | Diferencia temporal fuera de orden, en segundos. |
| `VENTANA_CANDIDATO_KM` | `app/services/indicios.py:1289` | `50.0` | regla | Ventana geográfica para buscar candidato, en km. |
| `VENTANA_CANDIDATO_SEG` | `app/services/indicios.py:1288` | `120.0` | regla | Ventana temporal para buscar candidato, en segundos. |
| `VENTANA_COMPATIBLE_MAG` | `app/services/indicios.py:1292` | `0.5` | regla | Diferencia de magnitud compatible. |
| `VENTANA_COMPATIBLE_PROF_KM` | `app/services/indicios.py:1291` | `20.0` | regla | Diferencia de profundidad compatible, en km. |
| `VENTANA_COMPATIBLE_SEG` | `app/services/indicios.py:1290` | `6.0` | regla | Diferencia temporal para considerar compatible, en segundos. |
| `VERSION_CRUCE` | `app/services/indicios.py:1287` | `4` | regla | Versión del cruce con Eventquery. |

**Interfaz**

| Constante | Módulo | Valor | Ámbito | Efecto |
|---|---|---|---|---|
| `CERCA_KM` | `app/services/station_review.py:23` | `50.0` | operación | Radio para resaltar estaciones cercanas, en km. |
| `PER_PAGE` | `app/blueprints/admin.py:33` | `50` | operación | Filas por página en administración. |
| `_CACHE_MAXIMO` | `app/services/catalog_export.py:24` | `16` | operación | Máximo de entradas en la caché de mapas. |

**Perfiles y mapas**

| Constante | Módulo | Valor | Ámbito | Efecto |
|---|---|---|---|---|
| `ALTO_MAPA` | `app/services/borders.py:15` | `140.0` | operación | Alto del mapa de Chile, en unidades de dibujo. |
| `ANCHO_BIN_KM` | `core/asigna_perfiles.py:125` | `1.0` | operación | Ancho del bin de distancia para perfiles, en km. |
| `ANCHO_MAPA` | `app/services/borders.py:14` | `100.0` | operación | Ancho del mapa de Chile, en unidades de dibujo. |
| `GRADO_KM_LAT` | `core/asigna_perfiles.py:120` | `111.0` | operación | Kilómetros por grado de latitud. |
| `GRADO_KM_LON` | `core/asigna_perfiles.py:121` | `111.0` | operación | Kilómetros por grado de longitud. |
| `K_PESO_PROFUNDIDAD` | `core/asigna_perfiles.py:117` | `1.0` | operación | Peso de la profundidad en la distancia de perfil. |
| `LAT_MAX` | `app/services/borders.py:13` | `-14.0` | operación | Latitud máxima del mapa de Chile. |
| `LAT_MIN` | `app/services/borders.py:12` | `-56.0` | operación | Latitud mínima del mapa de Chile. |
| `LON_MAX` | `app/services/borders.py:11` | `-60.0` | operación | Longitud máxima del mapa de Chile. |
| `LON_MIN` | `app/services/borders.py:10` | `-82.0` | operación | Longitud mínima del mapa de Chile. |
| `MARGEN_BORDE_KM` | `core/asigna_perfiles.py:105` | `0.0` | operación | Margen de borde para asignar perfil, en km. |
| `UMBRAL_DIST_KM` | `core/asigna_perfiles.py:90` | `110.0` | operación | Distancia máxima para asignar un perfil, en km. |
| `UMBRAL_PERP_KM` | `core/asigna_perfiles.py:97` | `None` | operación | Umbral de distancia perpendicular; None lo desactiva. |

**Wadati**

| Constante | Módulo | Valor | Ámbito | Efecto |
|---|---|---|---|---|
| `MIN_PARES` | `app/services/wadati.py:14` | `3` | regla | Pares P/S mínimos para calcular. |
| `MIN_PARES_CONSISTENTE` | `app/services/wadati.py:15` | `4` | regla | Pares mínimos para calidad consistente. |
| `UMBRAL_DISPERSION` | `app/services/wadati.py:19` | `0.5` | regla | Dispersión máxima aceptable. |
| `UMBRAL_R2` | `app/services/wadati.py:16` | `0.9` | regla | R² mínimo para calidad consistente. |
| `UMBRAL_T0` | `app/services/wadati.py:20` | `2.0` | regla | T0 máximo aceptable, en segundos. |
| `UMBRAL_VP_VS_MAX` | `app/services/wadati.py:18` | `2.0` | regla | Vp/Vs máximo aceptable. |
| `UMBRAL_VP_VS_MIN` | `app/services/wadati.py:17` | `1.5` | regla | Vp/Vs mínimo aceptable. |

### D.3 Parámetros de scripts

| Flag | Script | Defecto | Efecto |
|---|---|---|---|
| `--datos` | `generar_mapa_chile.py` | `os.environ.get('CARTOPY_DATA_DIR')` | Directorio de datos de Cartopy. |
| `--json` | `generar_mapa_chile.py` | `RUTA_JSON` | Ruta del JSON de contorno y regiones. |
| `--salida` | `generar_mapa_chile.py` | `RUTA_SALIDA` | Ruta del SVG del mini mapa. |
| `--bandas` | `validar_correlacion.py` | `1-10` | Bandas separadas por coma; ejemplo 1-5,1-10,2-15. |
| `--detalle` | `validar_correlacion.py` | `—` | Muestra el detalle por estación y banda. |
| `--estrategia` | `validar_correlacion.py` | `picks` | Selección de eventos: picks o cobertura. |
| `--eventos` | `validar_correlacion.py` | `—` | IDs de evento separados por coma. |
| `--job` | `validar_correlacion.py` | `9d461a97-94c7-46ac-8242-041fe6f04c37` | Trabajo del workspace a analizar. |
| `--max-candidatas` | `validar_correlacion.py` | `10` | Máximo de candidatas por evento. |
| `--persistencia` | `validar_correlacion.py` | `0.0` | Duración mínima sobre el umbral STA/LTA. |
| `--por-estrato` | `validar_correlacion.py` | `1` | Eventos por estrato latitud/profundidad. |
| `--radio-km` | `validar_correlacion.py` | `250.0` | Radio para seleccionar candidatas. |
| `--salida` | `validar_correlacion.py` | `—` | Archivo JSON de salida. |
| `--source` | `validar_correlacion.py` | `seiscomp` | Fuente del trabajo (seiscomp, seisan, central). |
| `--streams` | `validar_correlacion.py` | `—` | Filtra candidatas por stream, separadas por coma. |
| `--token` | `validar_correlacion.py` | `os.environ.get('RCS_DISPONIBILIDAD_TOKEN', '')` | Token del sidecar de disponibilidad. |
| `--url` | `validar_correlacion.py` | `os.environ.get('RCS_DISPONIBILIDAD_URL', 'http://disponibilidad:8010')` | URL del sidecar de disponibilidad. |

### D.4 Parámetros por trabajo

En esta versión no hay parámetros editables por trabajo. Los valores de la regla son globales y la caché guarda la versión efectiva para que un cambio invalide solo lo necesario.

| Parámetro | Dónde se guarda | Versión | Invalidación |
|---|---|---|---|
| Regla de indicios | `app/services/indicios.py` | `ESQUEMA_INDICIOS` | cambia el esquema o los umbrales |
| Caché de disponibilidad | `disponibilidad.jsonl` | — | se reemplaza por evento |
| Regla de señal (prevista) | `core/correlacion.py` | hash de la regla | al implementar la columna de señal |

### D.5 Reglas y umbrales

Los valores que definen una regla de negocio se listan también en D.2. Esta tabla los reúne para revisión rápida.

| Regla | Constante | Valor | Módulo |
|---|---|---|---|
| Indicios y prioridad | `CRUCE_AMPLIO_GRADOS` | `2.0` | `app/services/indicios.py` |
| Indicios y prioridad | `CRUCE_AMPLIO_SEG` | `6.0` | `app/services/indicios.py` |
| Indicios y prioridad | `CRUCE_ESTRICTO_GRADOS` | `1.0` | `app/services/indicios.py` |
| Indicios y prioridad | `CRUCE_ESTRICTO_SEG` | `3.0` | `app/services/indicios.py` |
| Indicios y prioridad | `ESQUEMA_INDICIOS` | `7` | `app/services/indicios.py` |
| Indicios y prioridad | `FACTOR_RESIDUAL_EXTREMO` | `10.0` | `app/services/indicios.py` |
| Indicios y prioridad | `MAX_PARES_DETALLE` | `40` | `app/services/indicios.py` |
| Indicios y prioridad | `MIN_ESTACIONES_FASE` | `3` | `app/services/indicios.py` |
| Indicios y prioridad | `SEPARACION_MINIMA_KM` | `20.0` | `app/services/indicios.py` |
| Indicios y prioridad | `UMBRAL_CONTEXTO_AZGAP` | `180.0` | `app/services/indicios.py` |
| Indicios y prioridad | `UMBRAL_CONTEXTO_ESTACIONES` | `5` | `app/services/indicios.py` |
| Indicios y prioridad | `UMBRAL_CONTEXTO_SIN_INVENTARIO` | `8` | `app/services/indicios.py` |
| Indicios y prioridad | `UMBRAL_PESO` | `0.5` | `app/services/indicios.py` |
| Indicios y prioridad | `UMBRAL_PESO_INFLUYENTE` | `0.125` | `app/services/indicios.py` |
| Indicios y prioridad | `UMBRAL_RESIDUAL` | `5.0` | `app/services/indicios.py` |
| Indicios y prioridad | `UMBRAL_RESIDUAL_EXTREMO` | `60.0` | `app/services/indicios.py` |
| Indicios y prioridad | `UMBRAL_RESIDUAL_FUERA_DE_ORDEN` | `5.0` | `app/services/indicios.py` |
| Indicios y prioridad | `UMBRAL_RESIDUAL_FUERA_DE_ORDEN_DEBIL` | `5.0` | `app/services/indicios.py` |
| Indicios y prioridad | `UMBRAL_SISTEMATICO_ESTACIONES` | `5` | `app/services/indicios.py` |
| Indicios y prioridad | `UMBRAL_SISTEMATICO_MEDIANA` | `2.0` | `app/services/indicios.py` |
| Indicios y prioridad | `UMBRAL_SISTEMATICO_PROPORCION` | `0.7` | `app/services/indicios.py` |
| Indicios y prioridad | `UMBRAL_TIEMPO_FUERA_DE_ORDEN_S` | `2.0` | `app/services/indicios.py` |
| Indicios y prioridad | `VENTANA_CANDIDATO_KM` | `50.0` | `app/services/indicios.py` |
| Indicios y prioridad | `VENTANA_CANDIDATO_SEG` | `120.0` | `app/services/indicios.py` |
| Indicios y prioridad | `VENTANA_COMPATIBLE_MAG` | `0.5` | `app/services/indicios.py` |
| Indicios y prioridad | `VENTANA_COMPATIBLE_PROF_KM` | `20.0` | `app/services/indicios.py` |
| Indicios y prioridad | `VENTANA_COMPATIBLE_SEG` | `6.0` | `app/services/indicios.py` |
| Indicios y prioridad | `VERSION_CRUCE` | `4` | `app/services/indicios.py` |
| Wadati | `MIN_PARES` | `3` | `app/services/wadati.py` |
| Wadati | `MIN_PARES_CONSISTENTE` | `4` | `app/services/wadati.py` |
| Wadati | `UMBRAL_DISPERSION` | `0.5` | `app/services/wadati.py` |
| Wadati | `UMBRAL_R2` | `0.9` | `app/services/wadati.py` |
| Wadati | `UMBRAL_T0` | `2.0` | `app/services/wadati.py` |
| Wadati | `UMBRAL_VP_VS_MAX` | `2.0` | `app/services/wadati.py` |
| Wadati | `UMBRAL_VP_VS_MIN` | `1.5` | `app/services/wadati.py` |
