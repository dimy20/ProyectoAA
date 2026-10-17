# 03_escenas_l1c_geometria

Decide qué escenas hay que volver a correr por ACOLITE para el dataset nuevo de matchups con geometría, y deja la lista lista para `tools/ac/run_acolite.py`.

## El problema que resuelve

El dataset nuevo (`matchups_registros_finales_geometria.geojson`, 2957 puntos) se parece al anterior (`matchups_registros_finales.geojson`, 2963 puntos), pero no es igual. Correr ACOLITE sobre todo sería caro: cada escena tarda minutos y son ~500 MB de descarga. Por eso se buscan solo las escenas que no tienen un resultado utilizable.

## Paso a paso

1. **Carga.** Lee los matchups nuevos y los anteriores, y los items STAC (`matchup_items_geometria.json`, 536 items).

2. **Escenas nuevas.** Son las que están en los matchups nuevos y no en los anteriores, o sea un `pass_id` que nunca se procesó. Salen 84 escenas con 779 puntos.

3. **Escenas ya procesadas con puntos fuera del recorte.**
   - `run_acolite.py` no procesa la escena entera: la recorta a una caja alrededor de los puntos, más un margen de 0.05°.
   - Si una escena ya procesada ahora tiene puntos que antes no estaban, el L2W recortado puede no cubrirlos.
   - Cada punto se identifica por sus coordenadas UTM redondeadas al decimetro (`clave`). Los puntos nuevos son los que no estaban en los anteriores para ese `pass_id`.
   - Para esos puntos se abren los L2W que ya están en `data/acolite/` y, con `dist_punto_pixeles`, se calcula la distancia al píxel más cercano. Si es mayor a `MAX_DIST_PIXEL_M` (30 m), el punto cae fuera del recorte.
   - Resultado: de 235 puntos nuevos en escenas ya procesadas, 142 quedan fuera, en 26 escenas.

4. **Escenas a correr.** 84 nuevas + 26 con puntos fuera del recorte = 110 de las 518 totales. Se evita reprocesar unas 408.

5. **Búsqueda del L1C en CDSE.** Para cada una de las 110 escenas se usan `sensing_and_tile` y `find_l1c`, las mismas funciones de `09_acolite/descarga_l1c_scenes.ipynb`. Tarda unos 15 minutos.

6. **Chequeo.** Se compara por `(satélite, hora, tile)`, que es como empareja `run_acolite.py`, y se verifica que no falte ninguna escena. Resultado: 110 de 110 encontradas, todas online.

7. **Salida.** `data/nuevos/l1c_scene_products_geometria.csv` con las columnas `name,id,online`. Es el input `--scenes` de `run_acolite.py` (el `Dockerfile.acolite` ya lo copia).

## Diferencias con `09_acolite/descarga_l1c_scenes.ipynb`

- Acá solo se buscan las 110 escenas elegidas, no todas las del dataset.
- Si `find_l1c` no encuentra el producto, se hace `continue`, así que no se mete `None` en la lista.
- `ITEMS_FILE` es un `Path`, por lo que `ITEMS_FILE.name` funciona en el mensaje de aviso.
