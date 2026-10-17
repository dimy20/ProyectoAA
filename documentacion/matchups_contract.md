# Contrato de entrada para la extracción de ventanas de ACOLITE

`tools/ac/extract_windows.py` requiere `--matchups RUTA`. No hay un conjunto de datos de entrada predeterminado. GeoJSON es el formato de referencia; también se pueden usar otros formatos vectoriales que GeoPandas pueda leer, siempre que cumplan este contrato.

Cada fila representa una medición asociada a una escena de ACOLITE:

| Campo | Representación requerida | Significado |
|---|---|---|
| geometry | Punto (`Point`) válido, no vacío y con un CRS declarado | Ubicación de la medición. Se acepta cualquier CRS transformable a EPSG:4326; la extracción realiza esa conversión. |
| pass_id | Cadena no vacía ni compuesta solo por espacios, sin `/` ni `\`; no puede ser `.` ni `..` | Nombre exacto de la carpeta de la escena bajo el prefijo de S3 seleccionado. Puede diferir del nombre de un producto L1C reprocesado. |
| delta | Número finito, mayor o igual que cero | Diferencia absoluta entre la fecha y hora de la medición y la adquisición satelital, **en segundos**. No se aceptan duraciones expresadas como texto. |

Se permiten ubicaciones e identificadores de escena repetidos. Se conserva el orden de las filas. La extracción no impone regiones, rangos de clorofila, categorías tróficas ni diferencias temporales máximas; esas decisiones corresponden a la preparación previa del conjunto de datos.

Los atributos adicionales son opcionales y se conservan en la salida. El conjunto de referencia incluye `fecha`, `fuente`, `chla`, `grupo_nombre` y `estado_trofico`. Los análisis posteriores pueden requerirlos, aunque la extracción no los necesita.

La extracción reemplaza `lon` y `lat` por las coordenadas derivadas de la geometría y convierte `delta` en una duración redondeada a segundos. La geometría no se incluye en el CSV. Las columnas de estadísticas de bandas e índices, junto con `sin_resultado`, `pocos_pixeles_buenos` e `indices_no_finitos`, reemplazan cualquier columna de entrada con el mismo nombre. La columna de índice del CSV se llama `matchup_index`.

Archivo de referencia inspeccionado: `data/nuevos/matchups_registros_finales.geojson`, con 2963 filas de tipo `Point`, CRS EPSG:32721 y `delta` numérico en segundos. Este archivo sirve como ejemplo; no se utiliza como entrada predeterminada.

```bash
python -m tools.ac.extract_windows \
  --matchups ruta/a/matchups.geojson \
  --prefix acolite_geometria acolite \
  --out ruta/a/estadisticas_ventanas.csv
```

Los prefijos se buscan en el orden indicado. Para cada escena se utiliza el primero que tenga resultados L2W. La salida predeterminada sigue siendo `data/nuevos/matchups_ventanas.csv`; se puede elegir otra ubicación mediante `--out`. La entrada se valida antes de crear el cliente de S3 o descargar imágenes.

La columna booleana `indices_no_finitos` vale `True` cuando algún índice calculado sobre los píxeles seleccionados, o alguna de sus estadísticas, contiene `inf`, `-inf` o `NaN` (por ejemplo, por una división entre cero). Los valores calculados se conservan: este indicador no descarta filas ni modifica las fórmulas. El resumen de ejecución muestra cuántas filas presentan esta condición.

En filas sin resultado, con pocos píxeles buenos o no procesadas por `--only` / `--limit`, el indicador queda en `False` porque no se calcularon índices. Por lo tanto, `False` por sí solo no garantiza que la fila tenga datos utilizables; también deben revisarse las columnas de resultado y los demás indicadores.
