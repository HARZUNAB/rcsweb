"""Glosario único de términos de la aplicación.

Las definiciones se reutilizan en los paneles de ayuda contextual, en los
tooltips y en la página /ayuda. No se guardan en base de datos.
"""

from __future__ import annotations

GRUPOS = (
    ("publicacion", "Publicación y cruce Eventquery"),
    ("fases", "Fases y patrones"),
    ("cobertura", "Cobertura y estaciones"),
    ("picks", "Cobertura de picks"),
    ("residuales", "Residuales y peso"),
    ("prioridad", "Prioridad"),
    ("resultados", "Resultados y cruces"),
    ("revisiones", "Solicitudes de revisión"),
    ("usuarios", "Roles y analistas"),
)

TERMINOS = {
    "cruce_eventquery": {
        "titulo": "Cruce Eventquery",
        "texto": (
            "Estimación de si una solución local corresponde a un evento "
            "publicado en Eventquery. La fuente local no declara publicación "
            "por sí sola."
        ),
    },
    "con_cruce": {
        "titulo": "Con cruce",
        "texto": (
            "La solución local coincide en tiempo y posición con un evento de "
            "Eventquery dentro de la ventana de comparación."
        ),
    },
    "sin_cruce": {
        "titulo": "Sin cruce",
        "texto": (
            "La solución local no encontró un evento equivalente en Eventquery. "
            "No confirma que el evento no esté publicado: solo que no se pudo "
            "establecer el cruce."
        ),
    },
    "sin_evaluar": {
        "titulo": "Sin evaluar",
        "texto": (
            "No hay datos suficientes para decidir el cruce, o la fuente es "
            "derivada y no se usa como evidencia de publicación."
        ),
    },
    "eventos_referencia": {
        "titulo": "Eventos de referencia",
        "texto": "Eventos únicos del catálogo publicado Eventquery.",
    },
    "soluciones_con_cruce": {
        "titulo": "Soluciones con cruce",
        "texto": (
            "Soluciones locales que cruzaron con Eventquery. Puede haber más "
            "de una solución local para un mismo evento de referencia."
        ),
    },
    "coincidencias_extra": {
        "titulo": "Coincidencias extra",
        "texto": (
            "Soluciones locales adicionales para una referencia que ya tenía "
            "al menos otra coincidencia."
        ),
    },
    "referencias_con_cruce": {
        "titulo": "Referencias con cruce",
        "texto": (
            "Eventos de Eventquery que tienen al menos una solución local "
            "asociada."
        ),
    },
    "referencias_sin_cruce": {
        "titulo": "Referencias sin cruce",
        "texto": (
            "Eventos de Eventquery que no tienen ninguna solución local "
            "asociada en el trabajo. El botón Ver sin cruce muestra cuáles "
            "son y el candidato local más cercano dentro de 120 s y 50 km, "
            "si existe."
        ),
    },
    "fuente_derivada": {
        "titulo": "Fuente derivada",
        "texto": (
            "Fuente que se llena desde otras fuentes locales, como Central. No "
            "se usa como referencia ni como evidencia independiente de "
            "publicación."
        ),
    },
    "percibido": {
        "titulo": "Percibido",
        "texto": (
            "Indica si el evento fue percibido por la población. Eventquery es "
            "la fuente que trae este dato; en una fuente local puede ser un "
            "valor heredado del cruce, no declarado por esa fuente."
        ),
    },
    "solucion_sospechosa": {
        "titulo": "Solución sospechosa",
        "texto": (
            "La localización no calza con el contexto sismotectónico esperado. "
            "Es una clasificación de la solución, no de las fases."
        ),
    },
    "solucion_normal": {
        "titulo": "Solución normal",
        "texto": (
            "La localización es consistente con el contexto y no activa una "
            "señal de sospecha."
        ),
    },
    "solucion_no_evaluable": {
        "titulo": "Solución no evaluable",
        "texto": "No hay datos suficientes para clasificar la localización.",
    },
    "patron": {
        "titulo": "Patrón",
        "texto": (
            "Resumen de cómo se comportan las fases anómalas: puntual, "
            "sistemático, varias señales, fuera de orden o pick antes del "
            "origen."
        ),
    },
    "patron_puntual": {
        "titulo": "Puntual",
        "texto": (
            "Una o pocas estaciones con residual extremo. Suele sugerir un "
            "pick o una asociación errónea."
        ),
    },
    "patron_sistematico": {
        "titulo": "Sistemático",
        "texto": (
            "Muchas estaciones con residuales del mismo signo. Puede indicar "
            "un problema de modelo, profundidad u origen. Si no hay "
            "residuales individuales > 5 s, se considera no concluyente y no "
            "sube la prioridad."
        ),
    },
    "patron_varias_senales": {
        "titulo": "Varias señales",
        "texto": (
            "Se combinan residuales altos, fases fuera de orden o picks antes "
            "del origen. No hay un único patrón dominante."
        ),
    },
    "patron_fuera_orden": {
        "titulo": "Fase inconsistente con la distancia",
        "texto": (
            "Una estación más cercana tiene mayor residual que una más lejana: "
            "el orden esperado por distancia no se cumple."
        ),
    },
    "patron_pick_antes_origen": {
        "titulo": "Pick antes del origen",
        "texto": "La lectura de fase es anterior al instante del origen.",
    },
    "patron_sin_fase": {
        "titulo": "Sin inconsistencia de fases",
        "texto": (
            "No se encontró una anomalía de fases. La solución puede seguir "
            "siendo sospechosa por su localización."
        ),
    },
    "senales_fase": {
        "titulo": "Señales de fase",
        "texto": (
            "Detalle de las anomalías encontradas en las fases: residual alto, "
            "fuera de orden, pick antes del origen o patrón sistemático."
        ),
    },
    "evidencia_principal": {
        "titulo": "Evidencia principal",
        "texto": (
            "Arribo con mayor residual absoluto entre los que generan el "
            "indicio. No es necesariamente la única evidencia."
        ),
    },
    "cobertura": {
        "titulo": "Cobertura",
        "texto": (
            "Calidad geométrica de las estaciones para sostener la solución. "
            "Depende del número de estaciones, del azimutal gap y de si hay "
            "perfil asignado."
        ),
    },
    "cobertura_fuerte": {
        "titulo": "Cobertura fuerte",
        "texto": (
            "Al menos 5 estaciones disponibles y usadas, azimutal gap ≤ 180° y "
            "perfil asignado."
        ),
    },
    "cobertura_debil": {
        "titulo": "Cobertura débil",
        "texto": (
            "Falla alguna condición de cobertura: pocas estaciones, azimutal "
            "gap > 180° o ausencia de perfil. Hace menos concluyente la "
            "evidencia."
        ),
    },
    "estaciones_disponibles": {
        "titulo": "Estaciones disponibles",
        "texto": (
            "Estaciones usadas más las del inventario sin arribos. Es el total "
            "conocido para el evento."
        ),
    },
    "estaciones_usadas": {
        "titulo": "Estaciones usadas",
        "texto": "Estaciones cuyos arribos influyeron en la solución.",
    },
    "azimutal_gap": {
        "titulo": "Azimutal gap",
        "texto": (
            "Mayor hueco angular sin estaciones alrededor del evento. Un valor "
            "grande indica cobertura desigual."
        ),
    },
    "residual": {
        "titulo": "Residual",
        "texto": (
            "Diferencia entre el tiempo de la fase observada y el esperado por "
            "el modelo. Un residual grande indica una fase que no calza."
        ),
    },
    "residual_extremo": {
        "titulo": "Residual extremo",
        "texto": (
            "El residual absoluto supera 60 s o 10 veces la mediana de los "
            "residuales de las fases usadas. En el listado se marca como "
            "«extremo»."
        ),
    },
    "indicio_debil": {
        "titulo": "Indicio débil",
        "texto": (
            "La anomalía existe, pero la fase tiene peso 3: influyó poco en la "
            "solución. No basta por sí sola para priorizar la revisión."
        ),
    },
    "peso": {
        "titulo": "Peso",
        "texto": (
            "Escala 0–4 de influencia de una fase: 0 es máxima influencia y 4 "
            "es sin influencia. Solo las fases con peso 0–3 entran al análisis."
        ),
    },
    "residuo_slab": {
        "titulo": "Residuo al slab",
        "texto": (
            "Diferencia vertical entre la profundidad del evento y la "
            "profundidad del slab de subducción. No es un residual de tiempos "
            "de fase."
        ),
    },
    "distancia_slab": {
        "titulo": "Distancia al slab",
        "texto": (
            "Distancia entre el evento y la superficie del slab. Complementa al "
            "residuo vertical."
        ),
    },
    "prioridad_alta": {
        "titulo": "Prioridad alta",
        "texto": (
            "Evento publicado y con solución sospechosa. La duda de "
            "localización manda: la fase no baja la prioridad."
        ),
    },
    "prioridad_media": {
        "titulo": "Prioridad media",
        "texto": (
            "Evento publicado, con solución normal y fase fuerte. Es una "
            "señal de calidad de catálogo, no de localización."
        ),
    },
    "prioridad_baja": {
        "titulo": "Prioridad baja",
        "texto": (
            "Evento no publicado, con solución sospechosa y fase fuerte. Se "
            "revisa por el flujo de No publicados."
        ),
    },
    "prioridad_informativa": {
        "titulo": "Prioridad informativa",
        "texto": (
            "Combinaciones restantes. No entra a la revisión prioritaria."
        ),
    },
    "motivo_prioridad": {
        "titulo": "Motivo de la prioridad",
        "texto": (
            "Localización: evento publicado y sospechoso. Fases: evento "
            "publicado con fase fuerte y solución normal. No publicado: "
            "evento sin cruce con solución sospechosa y fase fuerte."
        ),
    },
    "prioridad_sin_evaluar": {
        "titulo": "Prioridad sin evaluar",
        "texto": "No se pudo determinar el cruce o la solución.",
    },
    "no_publicados": {
        "titulo": "No publicados",
        "texto": (
            "Eventos locales que no encontraron un cruce con Eventquery. Es una "
            "estimación, no una declaración de la fuente local."
        ),
    },
    "no_actualizados": {
        "titulo": "No actualizados",
        "texto": (
            "Eventos que sí aparecen en Eventquery o en otra fuente, pero cuyos "
            "parámetros difieren de la versión de referencia."
        ),
    },
    "repetidos": {
        "titulo": "Repetidos",
        "texto": (
            "Dos o más soluciones que probablemente representan el mismo "
            "evento dentro de un catálogo o entre fuentes."
        ),
    },
    "coincidencias_otras_fuentes": {
        "titulo": "Coincidencias en otras fuentes",
        "texto": (
            "Para un evento no publicado, indica en qué otras fuentes locales "
            "existe y si esa solución tiene cruce con Eventquery."
        ),
    },
    "publicado_otra_fuente": {
        "titulo": "Publicado en otra fuente",
        "texto": (
            "Columna antigua del cruce por pares. Indica una fuente donde el "
            "evento parece publicado; el detalle actual muestra todas las "
            "fuentes."
        ),
    },
    "revision_notificada": {
        "titulo": "Notificada",
        "texto": "La solicitud fue creada y está pendiente de aceptación.",
    },
    "revision_en_proceso": {
        "titulo": "En proceso",
        "texto": "El analista asignado aceptó la solicitud y está revisando.",
    },
    "revision_cerrada": {
        "titulo": "Cerrada",
        "texto": "El analista terminó y registró los antecedentes del cierre.",
    },
    "sin_usuario": {
        "titulo": "Sin usuario",
        "texto": (
            "El analista de la fuente no coincide con un usuario activo de la "
            "aplicación. El evento se puede ver, pero no asignar."
        ),
    },
    "rol_multiple": {
        "titulo": "Roles múltiples",
        "texto": (
            "Un usuario puede tener más de un rol. Los permisos son la unión de "
            "todos sus roles."
        ),
    },
    "codigo_analista": {
        "titulo": "Código de analista",
        "texto": (
            "Nombre corto con el que la fuente identifica al analista. Se usa "
            "para asociar eventos con un usuario; no tiene que coincidir con el "
            "nombre de usuario."
        ),
    },
    "alias_analista": {
        "titulo": "Alias de analista",
        "texto": (
            "Nombres alternativos del mismo analista, separados por coma. "
            "Ayudan a reconocer variantes de escritura en la fuente."
        ),
    },
    "estacion_observada": {
        "titulo": "Estación observada",
        "texto": "La estación tiene un pick observado en la solución.",
    },
    "estacion_sin_consultar": {
        "titulo": "Sin consultar",
        "texto": "No se consultaron las formas de onda de la estación.",
    },
    "estacion_sin_datos": {
        "titulo": "Sin datos",
        "texto": "Se consultaron las formas de onda y no hay datos disponibles.",
    },
    "estacion_disponible_no_usada": {
        "titulo": "Disponible no usada",
        "texto": (
            "Hay formas de onda disponibles, pero la estación no tiene un pick "
            "usado en la solución."
        ),
    },
    "picks_faltantes": {
        "titulo": "Estaciones cercanas sin aportar",
        "texto": (
            "Estaciones con registro disponible, dentro del radio de búsqueda, "
            "que no contribuyeron a la solución: no tienen arribo o tienen un "
            "pick que no se usó. Se muestran como sin picar + picadas no usadas."
        ),
        "grupo": "picks",
    },
    "sin_picar": {
        "titulo": "Sin picar",
        "texto": (
            "Estación con registro disponible y sin arribo para el evento. Es "
            "una candidata a pick faltante; no confirma por sí sola que la "
            "señal sea clara."
        ),
        "grupo": "picks",
    },
    "picada_no_usada": {
        "titulo": "Picada no usada",
        "texto": (
            "Estación con un pick que no influyó en la solución: peso 0, fase "
            "descartada o componente horizontal. Es distinto de una estación "
            "sin pick."
        ),
        "grupo": "picks",
    },
    "senal_pendiente": {
        "titulo": "Señal pendiente",
        "texto": (
            "El evento tiene candidatas, pero todavía no se analizaron las "
            "formas de onda. El conteo es de inventario; falta confirmar si "
            "hay señal clara."
        ),
        "grupo": "picks",
    },
    "senal_clara": {
        "titulo": "Señal clara",
        "texto": (
            "Regla prevista: al menos 2 de las bandas 1–5, 1–10 y 2–15 Hz con "
            "STA/LTA ≥3 y racha ≥0.7 s en el canal vertical. La correlación es "
            "informativa. Esta confirmación todavía no está activa."
        ),
        "grupo": "picks",
    },
    "sin_senal_clara": {
        "titulo": "Sin señal clara",
        "texto": (
            "La estación fue analizada y no alcanzó la regla de señal; no se "
            "cuenta como pick faltante claro."
        ),
        "grupo": "picks",
    },
    "cobertura_picks": {
        "titulo": "Cobertura de picks",
        "texto": (
            "Indicador de revisión que cuenta estaciones cercanas con registro "
            "disponible que no aportaron a la solución. En la lista se muestra "
            "como pestaña Sin aportar. Se calcula al terminar el trabajo; la "
            "confirmación con formas de onda es una segunda etapa."
        ),
        "grupo": "picks",
    },
    "prioridad_picks": {
        "titulo": "Prioridad por cobertura de picks",
        "texto": (
            "Prioridad preliminar según el número de estaciones sin aportar y "
            "la distancia mínima. Alta con ≥3 o una a <100 km; Media con 1–2. "
            "La señal confirmada puede ajustarla."
        ),
        "grupo": "picks",
    },
    "radio_picks": {
        "titulo": "Radio de búsqueda de picks",
        "texto": (
            "Distancia máxima para considerar una estación cercana. Se "
            "configura con RCS_PICKS_RADIO_KM; por defecto 250 km."
        ),
        "grupo": "picks",
    },
    "miniaturas_perfil_planta": {
        "titulo": "Miniaturas de perfil y planta",
        "texto": (
            "Vista compacta del perfil de subducción y de la ubicación del "
            "evento en el mapa de planta. Se cargan al activar la opción o al "
            "abrir la fila."
        ),
    },
    "filtros_estaciones_mapa": {
        "titulo": "Filtros del mapa de estaciones",
        "texto": (
            "El radio y Solo cercanas recortan todas las estaciones del mapa, "
            "incluidas las que tienen arribos. Las casillas de estado permiten "
            "mostrar u ocultar con arribos, disponibles no usadas, sin datos y "
            "sin consultar. Sin datos queda oculto por defecto."
        ),
    },
    "correo_analista": {
        "titulo": "Correo del analista",
        "texto": (
            "Dirección configurada en Usuarios. Se usa para avisar al analista "
            "cuando se le asigna una solicitud de revisión."
        ),
    },
    "evidencia_cierre": {
        "titulo": "Evidencia de cierre",
        "texto": (
            "Archivo opcional que el analista adjunta al cerrar la solicitud. "
            "Se aceptan PDF, imágenes, DOC/DOCX, XLS/XLSX, TXT, CSV y ZIP, "
            "con un máximo de 20 MB."
        ),
    },
    "url_actualizada_evento": {
        "titulo": "URL actualizada del evento",
        "texto": (
            "Enlace que se registra por evento cuando sus parámetros cambiaron "
            "durante la revisión. Es obligatorio si se marca que el evento "
            "cambió y sigue publicado."
        ),
    },
    "evento_despublicado": {
        "titulo": "Evento despublicado",
        "texto": (
            "Evento que estaba publicado y dejó de estarlo después de cambiar "
            "sus parámetros. En ese caso no se exige URL actualizada; se "
            "registra la observación del analista."
        ),
    },
    "observacion_evento": {
        "titulo": "Observación por evento",
        "texto": (
            "Nota opcional que el analista agrega a cada evento al cerrar la "
            "solicitud, por ejemplo para explicar una despublicación o un "
            "cambio."
        ),
    },
    "fase_fuerte": {
        "titulo": "Fase fuerte",
        "texto": (
            "Anomalía de fase que cuenta como evidencia fuerte: residual "
            "absoluto > 5 s en una fase de peso 0–2, fase fuera de orden por "
            "distancia o pick antes del origen."
        ),
    },
    "residual_temporal": {
        "titulo": "Residual temporal",
        "texto": (
            "Residual completado temporalmente desde otra fuente local. No "
            "proviene de la base de la fuente analizada."
        ),
    },
    "parametros_actualizados": {
        "titulo": "Parámetros actualizados",
        "texto": (
            "El evento cambió magnitud, posición, profundidad u otro parámetro "
            "durante la revisión. En el cierre se marca «¿Cambió?»."
        ),
    },
    "wadati": {
        "titulo": "Wadati",
        "texto": (
            "Método que estima Vp/Vs y la corrección de la hora de origen a "
            "partir de los tiempos P y S de varias estaciones. Requiere al "
            "menos 3 pares P/S; con 4 o más el ajuste es más concluyente."
        ),
    },
    "vp_vs": {
        "titulo": "Vp/Vs",
        "texto": (
            "Relación entre la velocidad de las ondas P y S estimada por el "
            "ajuste Wadati. Un valor típico está entre 1,6 y 1,9; fuera de "
            "1,5–2,0 conviene revisar los picks."
        ),
    },
    "r2_wadati": {
        "titulo": "R² del ajuste",
        "texto": (
            "Coeficiente de determinación del ajuste Wadati. Cerca de 1 "
            "indica que los pares P/S siguen una recta; por debajo de 0,90 "
            "el ajuste es dudoso."
        ),
    },
    "t0_wadati": {
        "titulo": "T0 del ajuste",
        "texto": (
            "Corrección de la hora de origen respecto de la hora del catálogo. "
            "Un valor distinto de cero puede indicar un problema de origen, "
            "modelo o localización; se muestra como advertencia."
        ),
    },
    "wadati_calidad": {
        "titulo": "Calidad Wadati",
        "texto": (
            "Consistente: 4 o más pares, R² ≥ 0,90, Vp/Vs entre 1,5 y 2,0 y "
            "dispersión ≤ 0,5 s. Preliminar: solo 3 pares. Dudoso: falla "
            "algún criterio. Insuficiente: menos de 3 pares P/S."
        ),
    },
}


def definicion(clave: str) -> dict | None:
    return TERMINOS.get(clave)


def terminos(claves) -> list[dict]:
    return [
        {"clave": clave, **TERMINOS[clave]}
        for clave in claves
        if clave in TERMINOS
    ]


def grupos() -> list[dict]:
    return [
        {
            "clave": clave,
            "titulo": titulo,
            "terminos": [
                {"clave": termino, **datos}
                for termino, datos in TERMINOS.items()
                if datos.get("grupo", _grupo_de(termino)) == clave
            ],
        }
        for clave, titulo in GRUPOS
    ]


def _grupo_de(clave: str) -> str:
    if clave in {
        "cruce_eventquery",
        "con_cruce",
        "sin_cruce",
        "sin_evaluar",
        "eventos_referencia",
        "soluciones_con_cruce",
        "coincidencias_extra",
        "referencias_con_cruce",
        "referencias_sin_cruce",
        "fuente_derivada",
        "percibido",
    }:
        return "publicacion"
    if clave.startswith("patron") or clave in {
        "solucion_sospechosa",
        "solucion_normal",
        "solucion_no_evaluable",
        "senales_fase",
        "evidencia_principal",
        "fase_fuerte",
        "wadati",
        "vp_vs",
        "r2_wadati",
        "t0_wadati",
        "wadati_calidad",
    }:
        return "fases"
    if clave in {
        "cobertura",
        "cobertura_fuerte",
        "cobertura_debil",
        "estaciones_disponibles",
        "estaciones_usadas",
        "azimutal_gap",
        "filtros_estaciones_mapa",
        "estacion_observada",
        "estacion_sin_consultar",
        "estacion_sin_datos",
        "estacion_disponible_no_usada",
    }:
        return "cobertura"
    if clave in {
        "residual",
        "residual_extremo",
        "residual_temporal",
        "indicio_debil",
        "peso",
        "residuo_slab",
        "distancia_slab",
    }:
        return "residuales"
    if clave.startswith("prioridad") or clave == "motivo_prioridad":
        return "prioridad"
    if clave in {
        "no_publicados",
        "no_actualizados",
        "repetidos",
        "coincidencias_otras_fuentes",
        "publicado_otra_fuente",
        "miniaturas_perfil_planta",
    }:
        return "resultados"
    if clave in {
        "correo_analista",
        "evidencia_cierre",
        "url_actualizada_evento",
        "evento_despublicado",
        "observacion_evento",
        "parametros_actualizados",
    } or clave.startswith("revision"):
        return "revisiones"
    return "usuarios"
