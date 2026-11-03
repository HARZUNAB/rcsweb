# Manual de usuario

RCS Web es el revisor de catálogos sísmicos de la red. Permite solicitar o
subir catálogos, procesarlos, revisar los resultados, abrir el detalle de cada
evento y consultar los paneles de contexto sismotectónico.

**Versión:** 0.7.3 · **Actualizado:** noviembre de 2026

## Acceso

Ingrese desde el navegador con el usuario y la contraseña que le entregó el
administrador.

![Pantalla de ingreso](img/login.png)

Si no recuerda la contraseña, use el enlace **«¿Olvidó su contraseña?»**. Por
seguridad, las claves no se recuperan: un administrador debe restablecerla
desde **Usuarios**. Si usted es el administrador, el manual técnico explica el
comando de recuperación.

### Roles

| Rol | Alcance |
|---|---|
| **Administrador** | Acceso total, usuarios y auditoría |
| **Supervisor** | Toda la operación y la auditoría, sin gestión de usuarios |
| **Analista** | Operación diaria sobre sus propios trabajos y solicitudes |
| **Consulta** | Solo lectura de sus propios trabajos |

El **analista** y la **consulta** solo ven los trabajos que crearon. El
administrador y el supervisor ven todos. La columna **Creador** del panel y la
línea «por …» del detalle identifican al autor.

Cada usuario tiene un **código corto de analista** y, opcionalmente, alias. El
código no tiene que coincidir con el nombre de usuario de la app. Por ejemplo,
el usuario `gjerez` puede tener código `Jere` y alias `JereV, jerez`.

En Resultados y Paneles, el analista solo ve los eventos cuyo campo de analista
coincide con su código o alias. La comparación ignora mayúsculas, acentos y
espacios, y tolera variantes por prefijo de al menos tres caracteres, como
`Jere` con `Jerez` o `JereV`. Si un nombre coincide con dos usuarios, no se
muestra y queda para revisión del administrador.

Sin código corto asignado, el analista o la consulta no ven eventos. El
administrador y el supervisor no se filtran por este código.

## Panel de trabajos

Al ingresar verá el resumen de trabajos y la lista de los más recientes.

![Panel de trabajos](img/panel.png)

- **Total, En curso, Terminados y Fallidos** muestran los trabajos que puede
  ver.
- Cada fila indica período, estado, creador, paso actual y fecha de creación.
- **Ver** abre el detalle.
- **Eliminar** aparece solo si tiene permiso y el trabajo es suyo, salvo para
  administradores y supervisores.

## Crear un trabajo

Hay dos formas de iniciar un trabajo.

### Solicitar catálogos

Use **Solicitar catálogos** cuando la aplicación deba conectarse al servidor
para descargar los archivos.

![Solicitud de catálogos](img/solicitud.png)

1. Indique el período.
2. Complete los datos del servidor y la contraseña SSH.
3. Elija las fuentes disponibles en la configuración.
4. Defina el radio de estaciones.
5. Envíe la solicitud.

La fuente de referencia se descarga siempre como catálogo de referencia; no es
una fuente local de Observaciones.

La contraseña SSH se usa solo para la descarga y no se guarda.

Mientras un catálogo se está descargando, el estado muestra un spinner y un
pulso lento, y la página se actualiza cada 2 segundos. Así se distingue una
descarga en curso de una pantalla detenida.

La tarjeta de progreso también muestra el **tiempo transcurrido** y cada
catálogo tiene su propio **porcentaje de avance**. Si el catálogo informa
etapas internas, el porcentaje avanza con ellas; si no, se mantiene el estado
de descarga y el reloj.

El listado muestra **Estado inicial** y **Estado final**:

- **Estado inicial**: la descarga o solicitud, por ejemplo Terminada, Fallida,
  Parcial, En cola o Descargando.
- **Estado final**:
  - **Trabajo vigente**: el trabajo asociado existe y se puede consultar.
  - **Trabajo eliminado**: el trabajo existió, pero fue eliminado.
  - **Preparando trabajo**: la solicitud está en curso y todavía no generó el
    trabajo.
  - **Sin trabajo**: la solicitud no generó un trabajo.

La columna **Eliminado** muestra la fecha en que se eliminó el trabajo, o `—`
si sigue vigente. El estado de descarga puede seguir siendo **Terminada**,
porque la descarga sí se completó; el estado final indica qué pasó con el
trabajo asociado.

![Descarga en curso](img/descarga.png)

### Subir catálogos

Use **Subir catálogos** cuando ya tenga los archivos en su equipo.

![Subir catálogos](img/subir.png)

1. Seleccione el catálogo de referencia.
2. Agregue las fuentes locales disponibles según corresponda.
3. En cada fuente local puede cambiar **Nombre de la fuente** para
   identificarla mejor en tablas, paneles y filtros.
4. Indique el período y la fuente principal.
5. Envíe el formulario.

Si falta un archivo o el contenido no es válido, el trabajo queda en
**Borrador** con el detalle del problema. Corrija el archivo y cree uno nuevo,
o elimine el borrador.

## Seguimiento del trabajo

El detalle muestra el progreso, los pasos, el registro y los accesos a los
resultados.

![Detalle del trabajo](img/trabajo.png)

- **Resultados** lleva a las tablas del trabajo.
- **Paneles** abre el contexto sismotectónico.
- **Catálogos** permite revisar los catálogos procesados.
- **Descargas** reúne los archivos generados.
- **Cancelar trabajo** detiene un trabajo en cola o en ejecución.
- **Eliminar** borra el trabajo, sus archivos y sus resultados. La auditoría
  conserva el registro de la eliminación.

## Resultados

Las tablas **No publicados**, **No actualizados** y **Repetidos** permiten
revisar los eventos.

![Listado de resultados](img/resultados.png)

- **Buscar en todas las columnas** aplica una búsqueda general.
- **Filtros por columna**: las columnas de texto filtran por contenido. Las
  numéricas aceptan un rango como `3..5`, o expresiones como `>=3`, `<=5` y
  `=3`.
- **Ordenar**: haga clic en el encabezado de una columna.
- **Miniaturas**: active el interruptor o use **Ver miniaturas** en una fila
  para ver el perfil y el mini mapa de planta lado a lado.
- **Ficha de ubicación**: indica Chile continental, insular, costa, mar
  chileno, otro país o alta mar.
- **Publicado en otra fuente**: cuando corresponde, indica la otra fuente donde
  se publicó el evento. **Tipo mag.** es el tipo de magnitud, no la fuente.
- **Descargar todo** incluye todas las filas del archivo.
- **Descargar filtrado** incluye todas las filas que cumplen el filtro, no solo
  la página visible.
- **Descargar seleccionados** incluye solo las filas marcadas, aunque estén
  ocultas por el filtro.
- La barra horizontal superior permite desplazar la tabla sin bajar hasta el
  final.

## Detalle del evento

Al pulsar **Ver** en una fila se abre la ficha del evento.

![Mapa y perfil del evento](img/detalle.png)

- La columna izquierda muestra los parámetros de la solución local.
- La columna derecha muestra el estado en la otra fuente, cuando existe.
- El mapa interactivo permite acercar, alejar y seleccionar eventos.
- La planta abre con una vista regional para que el evento se ubique en el
  contexto del país.
- La planta y el perfil ocupan la columna izquierda; al hacer clic en un evento,
  sus parámetros aparecen en el panel fijo de la derecha. En pantallas angostas
  el panel pasa debajo de los mapas.
- En modo offline se resaltan el contorno nacional y las divisiones regionales
  de Chile.

Más abajo está el perfil de subducción.

![Perfil con sismicidad histórica](img/detalle_perfil.png)

- **Sismicidad histórica (perfil)** agrega los sismos históricos en gris.
- El perfil conserva su escala al activar o desactivar la casilla.
- Al pasar el mouse por un evento, sus parámetros aparecen en el panel fijo y
  no se dibuja una etiqueta sobre los eventos vecinos. El clic fija la selección
  y resalta el evento en ambas vistas.
- El cursor del perfil se mantiene como puntero normal; el arrastre sigue
  permitiendo acercar una zona.
- En grupos con más de una solución, **Distancia** indica la separación respecto
  del evento de referencia. El punto de referencia se muestra como
  «0 km (referencia)». En **No actualizados** la referencia es la solución
  publicada (Eventquery); en **Repetidos** es la fila que abrió el detalle. En
  eventos únicos no se muestra la distancia, porque no hay otra solución con la
  cual comparar.
- En **No actualizados**, al seleccionar el evento publicado de Eventquery en
  la planta o en el perfil, el panel muestra **Analista probable** con todos los
  autores deducidos de las soluciones locales. El evento local conserva su
  **Analista** real.
- **Abrir PNG** y **Descargar PNG** generan una imagen del mapa.
- El PNG incluye un encabezado con una fila por evento: fecha y hora, magnitud,
  profundidad, coordenadas, analista y estado en la otra fuente, separados por
  «|». En los no actualizados se muestran el local y el publicado, y debajo la
  diferencia.
- La vista en planta se adapta a la cantidad de soluciones:
  - con un solo evento usa una vista regional (unos 8° × 4°) para ubicarlo en
    el país;
  - con varias soluciones cercanas se acerca lo necesario para distinguirlas;
  - si el grupo está disperso, mantiene todos los eventos a la vista.

## Paneles sismotectónicos

Los paneles agrupan los eventos por perfil de subducción y, cuando no tienen
perfil, por territorio.

![Paneles sismotectónicos](img/paneles.png)

- **Fuente** y **Tipo** filtran los grupos, la planta, el perfil y el listado.
  Una pestaña con cero eventos se puede abrir y muestra el aviso
  correspondiente.
- **Grupos**: seleccione un perfil o territorio. Las flechas **↑/↓** recorren
  la lista.
- **Ver** abre el detalle del grupo con el mismo mapa interactivo de Resultados
  y Catálogos: planta, perfil, selector online/offline, listado de eventos y
  botones para abrir o descargar el PNG.
- Al volver desde el detalle, se conserva seleccionado el mismo perfil o
  territorio que estaba viendo.
- Al pasar el cursor por un evento de la planta o del perfil, el detalle se
  previsualiza en el cuadro ubicado justo debajo de ambos mini mapas. Al hacer
  clic, la selección queda fija. El cuadro no tapa la interfaz ni los eventos
  vecinos.
- **Planta del grupo**: muestra los eventos y las divisiones regionales de
  Chile. Use **Centrar** para volver al encuadre del grupo después de hacer
  zoom o desplazar.
- **Perfil**: topografía, slab y eventos. La casilla de sismicidad histórica
  carga la serie del perfil seleccionado.
- **Solo sospechosos** limita la vista a los eventos marcados.
- **Ir al listado** lleva a la tabla de eventos del grupo.
- **Descargar** permite bajar todo, lo filtrado o lo seleccionado.
- **PNG del grupo**: identifica el perfil o territorio, la fuente y los filtros
  aplicados, y muestra los conteos de No publicados, No actualizados y
  Repetidos. No incluye el listado de eventos dentro de la imagen.

![Detalle de un grupo de Paneles](img/paneles_grupo.png)

## Catálogos

Desde el detalle del trabajo puede abrir los catálogos procesados. Los nombres
visibles provienen del manifiesto de fuentes y pueden cambiar sin modificar la
aplicación.

- Las columnas y filtros funcionan como en los resultados.
- **Administrador y supervisor** mantienen el acceso completo: columnas de
  analista, **Web**, **Ver**, **Ver miniaturas**, descargas completas y el nuevo
  **Descargar catálogo**.
- **Analista y consulta** ven todas las fuentes y usan los filtros, pero no ven
  las columnas **Analista** ni **Analista probable**, y no pueden abrir **Web**,
  **Ver** ni **Ver miniaturas**. Tampoco pueden usar las descargas completas.
  Su única descarga es **Descargar catálogo**.
- **Descargar catálogo** abre una vista previa con mapas de planta por
  territorio y dos variantes por perfil. **Ningún mapa se genera al abrir la
  página**: use **Ver** para abrirlo en un modal con indicador de actividad, o
  **Descargar** para obtener solo ese PNG. El panel **Generar todos los mapas**
  permite incluir o no las plantas y elegir las variantes de perfil antes de
  descargar el ZIP. La interfaz indica cuántos PNG se incluirán y ofrece
  **Seleccionar todo**, que marca las plantas y las dos variantes de perfil.
  Permite obtener:
  - `catalogo.csv`, con fecha y hora, latitud, longitud, profundidad, magnitud,
    tipo de magnitud y referencia geográfica si la fuente la tiene;
  - `planta_nacional.png`, `planta_insular.png`, `planta_antartico.png` y
    `planta_otros.png`, cada uno solo si tiene eventos;
  - `perfil_<id>.png` (solo perfil) y `perfil_<id>_planta.png` (perfil + planta)
    por cada perfil;
  - un ZIP con todo lo seleccionado.
  El CSV no incluye el nombre del analista. Los mapas de esta vista llevan una
  leyenda mínima: amarillo para no percibidos y rojo solo si hay percibidos.
  Los eventos percibidos se dibujan sobre los no percibidos. El encabezado del
  PNG muestra los filtros aplicados, incluida la búsqueda de texto.
- La planta se separa en **Chile continental**, **territorio insular**,
  **territorio antártico** y **Otros**. Los eventos fuera de Chile pasan a
  Otros cuando superan el radio de influencia según la magnitud: 200 km para
  M<4, 300 km para M4, 400 km para M5 y 500 km para M6 o más. El mapa de Otros
  incluye la costa o islas chilenas más cercanas para orientar la vista y
  muestra solo el nombre y el punto de la localidad más cercana a los sismos.
- Cada perfil se asigna por cercanía individual del evento. Los eventos sin
  perfil aparecen solo en las plantas. Si el catálogo no tiene perfiles, solo
  se generan las plantas.
- **Eventquery** incluye **Percibido** y **Analista probable**, calculado
  cruzando la solución publicada con las fuentes locales del manifiesto. Si más de una fuente
  aporta una solución, se muestran todos los autores, por ejemplo
  `SeisComp: cris; Seisan: beto`. El dato es una deducción, no un campo del
  catálogo original de Eventquery.

## Usuarios y perfil

Cada usuario puede cambiar su contraseña desde **Mi perfil**.

![Mi perfil](img/perfil.png)

El **administrador** además dispone de la pantalla **Usuarios**.

![Usuarios](img/usuarios.png)

- Crear usuarios.
- Cambiar el rol.
- Activar o desactivar cuentas.
- Restablecer contraseñas.

El sistema no permite dejar sin administradores activos. Si una cuenta se
desactiva, su sesión se cierra en la siguiente petición.

## Preguntas frecuentes

**No veo un trabajo que otro usuario creó.**
Es normal: los analistas y las consultas solo ven sus propios trabajos. El
administrador o el supervisor pueden verlo.

**No aparece la fuente Eventquery.**
Puede tener cero eventos. La pestaña se puede abrir y muestra el aviso de
filtro sin eventos.

**El mapa se ve demasiado cerca.**
La planta usa una vista regional; puede alejar con la rueda del mouse. En los
paneles, use **Centrar** para volver al encuadre del grupo.

**La página tarda y no sé si está trabajando.**
Después de una navegación lenta aparece un aviso con un spinner y
«Cargando…».

**Olvidé mi contraseña.**
Use **«¿Olvidó su contraseña?»** en el ingreso. La clave solo puede
restablecerse desde **Usuarios** por un administrador.

**¿Dónde quedan mis trabajos?**
Los metadatos y la lista quedan en la base de datos de la aplicación; los
archivos de cada trabajo se guardan en el espacio de trabajo del servidor. El
manual técnico detalla las rutas.

**¿Puedo descargar los resultados?**
Sí, si su rol lo permite. Analistas, supervisores y administradores pueden
exportar; la consulta es solo lectura.
