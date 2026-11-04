# Core incorporado

Este directorio contiene la parte del proyecto `revisacatalogosweb` que RCS Web
necesita para procesar catálogos y generar mapas.

- Código copiado desde `revisacatalogosweb`.
- Commit de origen: `aec8b81` y cambios locales del 2026-10-29.
- Los datos grandes no viven aquí: están en `../core_data/`.
- Las rutas de datos se resuelven con `core/paths.py` y la variable
  `RCS_CORE_DATA`.
- No se incluyen las interfaces gráficas `app.py` ni `solicita_catalogos.py`.

Para instalar los datos en otra máquina:

```bash
scripts/instalar_core_data.sh /ruta/al/revisacatalogosweb
```
