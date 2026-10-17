"""Extrae ventanas alrededor de cada matchup sobre los L2W de ACOLITE y calcula estadisticas de bandas e indices.

Para cada pass_id de los matchups:
  1. baja de s3 los L2W.nc de acolite/<pass_id>/ (uno solo, o uno por parte si la escena fue dividida:
     acolite/<pass_id>/parte1/, parte2/, ...). Lo que ya esta en data/acolite/ no se vuelve a bajar.
  2. para cada punto elige el L2W (la parte) que lo contiene, toma la ventana (2*half+1)^2 alrededor del
     pixel mas cercano y calcula mean/median/iqr/std de cada banda (B02-B07) y de cada indice, sobre los
     pixeles buenos de la ventana (l2_flags == 0 y valores finitos).

Los puntos que no se pueden calcular quedan con todas las columnas en NaN y el motivo en estas columnas:
  sin_resultado:        no hay L2W para la escena, o no hay para la parte donde cae el punto
  pocos_pixeles_buenos: la ventana tiene menos de MIN_PIXELS_VALIDOS pixeles buenos

indices_no_finitos indica si algun indice calculado o sus estadisticas contienen inf, -inf o NaN.

Contrato de entrada: documentacion/matchups_contract.md.

Ejemplo:
    python -m tools.ac.extract_windows --matchups matchups.geojson
    python -m tools.ac.extract_windows --matchups matchups.geojson --only S2B_MSIL1C_20180411T134209 --out /tmp/prueba.csv
    python -m tools.ac.extract_windows --prefix acolite_geometria acolite --matchups data/nuevos/matchups_registros_finales_geometria.geojson --out data/nuevos/matchups_ventanas_geometria.csv
"""

import argparse
import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from dotenv import load_dotenv
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.ac_tools import dist_punto_pixeles, open_l2w
from core.s3 import DEFAULT_BUCKET, get_s3_client

load_dotenv()

DATA = Path("data")
ACOLITE_SAVE_DIR = DATA / "acolite"
OUT_FILE = DATA / "nuevos" / "matchups_ventanas.csv"

PIXEL_BUENO = 0
MIN_PIXELS_VALIDOS = 5
half = 2
# un pixel mide 20 m: si el pixel mas cercano esta mas lejos que esto, el punto no esta en ese L2W
MAX_DIST_PIXEL_M = 30

band_names = ["B02", "B03", "B04", "B05", "B06", "B07"]
index_names = ["ndci", "tres_bandas", "combinado", "green_rededge", "green_red", "mci"]
stats_names = ["mean", "median", "iqr", "std"]

def download_pass_id_files(pass_id_prefix, s3, bucket):
    """Baja los L2W.nc de la escena y devuelve sus paths locales (vacio si la escena no tiene resultado).

    Se conserva la subcarpeta (parte1/, parte2/) porque el nombre del archivo es el mismo en todas
    las partes y se pisarian.
    """
    pass_id_paginator = s3.get_paginator("list_objects_v2")

    pass_id_iterator = pass_id_paginator.paginate(
        Bucket=bucket,
        Prefix=f"{pass_id_prefix}/",
    )

    # cada prefijo se baja a su propia carpeta: una escena puede estar en dos prefijos con recortes distintos
    prefix, pass_id = pass_id_prefix.split("/")
    pass_id_save_path = DATA / prefix / pass_id

    for file in pass_id_iterator:
        for obj in file.get("Contents", []):
            key = obj["Key"]
            if not key.endswith("L2W.nc"):
                continue

            dest = pass_id_save_path / key[len(f"{pass_id_prefix}/"):]
            if dest.exists():
                continue

            os.makedirs(dest.parent, exist_ok=True)
            # a un .part y despues se renombra: un archivo a medias no se confunde con uno completo
            tmp = dest.with_name(dest.name + ".part")
            s3.download_file(Bucket=bucket, Key=key, Filename=tmp)
            os.replace(tmp, dest)

    return sorted(pass_id_save_path.glob("**/*L2W.nc"))

def procesar_escena(puntos, pass_id, s3, bucket, prefixes):
    mask_escena = puntos["pass_id"] == pass_id
    puntos_escena = puntos[mask_escena]

    # el primer prefijo que tenga resultado para la escena
    for prefix in prefixes:
        l2w_paths = download_pass_id_files(f"{prefix}/{pass_id}", s3, bucket)
        if l2w_paths:
            break
    if not l2w_paths:
        puntos.loc[puntos_escena.index, "sin_resultado"] = True
        return

    # una escena dividida tiene un L2W por parte, uno solo si no
    productos = [open_l2w(path) for path in l2w_paths]

    for idx, p in puntos_escena.iterrows():
        # parte (L2W) con el pixel mas cercano a p
        mejor = None
        for dl in productos:
            d2 = dist_punto_pixeles(p, dl["lat"].values, dl["lon"].values)
            i, j = np.unravel_index(np.nanargmin(d2), d2.shape)
            if mejor is None or d2[i, j] < mejor[0]:
                mejor = (d2[i, j], i, j, dl)
        d2_min, i, j, dl = mejor

        # pasamos a metros
        dist_m = float(np.sqrt(d2_min) * 111_320)

        # si la parte donde cae el punto no tiene L2W, el mas cercano es el de otra parte
        if dist_m > MAX_DIST_PIXEL_M:
            puntos.loc[idx, "sin_resultado"] = True
            continue

        flags = dl["l2_flags"]
        num_rows, num_cols = flags.shape

        # el slice es la ventana al rededor del punto (i, j)
        sl = (slice(max(i - half, 0), min(i + half + 1, num_rows)),
              slice(max(j - half, 0), min(j + half + 1, num_cols)))

        mask_ventana = flags.values[sl] == PIXEL_BUENO
        # l2_flags == 0 no garantiza que las bandas sean finitas
        for banda in band_names:
            mask_ventana &= np.isfinite(dl[banda].values[sl])
        buenos = mask_ventana.sum()

        if buenos < MIN_PIXELS_VALIDOS:
            puntos.loc[idx, "pocos_pixeles_buenos"] = True
            continue

        # stats de cada banda

        for banda in band_names:
            ventana = dl[banda].values[sl]
            ventana = ventana[mask_ventana]

            q25, q75 = np.percentile(ventana, [25, 75]) #
            media = float(np.mean(ventana))
            mediana = float(np.median(ventana))
            iqr = float(q75 - q25)
            std = float(np.std(ventana))

            cols = [f"{banda}_{s}" for s in stats_names]
            puntos.loc[idx, cols] = [media, mediana, iqr, std]

        # indices

        B02 = dl["B02"].values[sl][mask_ventana]
        B03 = dl["B03"].values[sl][mask_ventana]
        B04 = dl["B04"].values[sl][mask_ventana]
        B05 = dl["B05"].values[sl][mask_ventana]
        B06 = dl["B06"].values[sl][mask_ventana]
        B07 = dl["B07"].values[sl][mask_ventana]

        L4, L5, L6 = 665, 705, 740
        ndci = (B05 - B04) / (B05 + B04)
        tres_bandas = B07 * (0.1 * B04 - 0.1 * B05)
        combinado = B05 * (B06 + B04) / B02
        green_rededge = B03 / B06
        green_red = B03 / B04
        MCI = B05 - (B04 + (B06 - B04) * ((L5 - L4) / (L6 - L4)))

        indices = {
            "ndci": ndci,
            "tres_bandas": tres_bandas,
            "combinado": combinado,
            "green_rededge":  green_rededge,
            "green_red": green_red,
            "mci": MCI
        }

        puntos.loc[idx, "indices_no_finitos"] = any(
            not np.isfinite(valores).all() for valores in indices.values()
        )

        for nombre, valores in indices.items():
            q25, q75 = np.percentile(valores, [25, 75])
            media = float(np.mean(valores))
            mediana = float(np.median(valores))
            iqr = float(q75 - q25)
            std = float(np.std(valores))

            cols = [f"{nombre}_{s}" for s in stats_names]
            puntos.loc[idx, cols] = [media, mediana, iqr, std]
            if not np.isfinite([media, mediana, iqr, std]).all():
                puntos.loc[idx, "indices_no_finitos"] = True


def load_matchups(path: Path) -> pd.DataFrame:
    """Validate the matchup contract and prepare points for window extraction.

    Additional attributes are preserved. Geometry is converted to WGS84 lon/lat;
    delta is a nonnegative numeric duration in seconds, rounded as before.
    """
    matchups = gpd.read_file(path)
    missing = {"pass_id", "delta"} - set(matchups.columns)
    if missing:
        raise ValueError(f"{path}: missing required columns: {', '.join(sorted(missing))}")
    if matchups.crs is None:
        raise ValueError(f"{path}: geometry must have a declared CRS")
    geometry = matchups.geometry
    if (geometry.isna() | geometry.is_empty | ~geometry.is_valid | (geometry.geom_type != "Point")).any():
        raise ValueError(f"{path}: every geometry must be a nonempty, valid Point")
    if not matchups["pass_id"].map(
        lambda value: isinstance(value, str) and bool(value.strip())
        and value not in {".", ".."} and "/" not in value and "\\" not in value
    ).all():
        raise ValueError(f"{path}: pass_id must be a nonblank scene folder name without path separators")
    delta = matchups["delta"]
    if (not pd.api.types.is_numeric_dtype(delta.dtype)
            or pd.api.types.is_bool_dtype(delta.dtype)
            or not np.isfinite(delta).all() or (delta < 0).any()):
        raise ValueError(f"{path}: delta must contain finite, nonnegative numbers in seconds")
    matchups = matchups.to_crs("EPSG:4326")
    matchups["lon"] = matchups.geometry.x
    matchups["lat"] = matchups.geometry.y
    if (not np.isfinite(matchups[["lon", "lat"]].to_numpy()).all()
            or not matchups["lon"].between(-180, 180).all()
            or not matchups["lat"].between(-90, 90).all()):
        raise ValueError(f"{path}: geometry must transform to finite WGS84 coordinates within lon/lat bounds")
    puntos = pd.DataFrame(matchups.drop(columns=matchups.geometry.name))
    puntos["delta"] = pd.to_timedelta(puntos["delta"], unit="s").dt.round("s")
    return puntos


def main():
    parser = argparse.ArgumentParser(description="Extrae ventanas de los L2W de ACOLITE en los puntos de los matchups")
    parser.add_argument("--matchups", type=Path, required=True, help="archivo de puntos con CRS, pass_id y delta numerico en segundos (ver documentacion/matchups_contract.md)")
    parser.add_argument("--out", type=Path, default=OUT_FILE)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--prefix", nargs="+", default=["acolite"], help="prefijos de s3 donde buscar cada escena, en orden de prioridad")
    parser.add_argument("--only", default=None, help="solo los pass_id que contienen este texto")
    parser.add_argument("--limit", type=int, default=None, help="solo las primeras N escenas")
    args = parser.parse_args()

    try:
        puntos = load_matchups(args.matchups)
    except ValueError as exc:
        parser.error(str(exc))

    # todas las columnas de entrada: los puntos que no se calculan quedan en NaN
    for nombre in band_names + index_names:
        for s in stats_names:
            puntos[f"{nombre}_{s}"] = np.nan
    puntos["sin_resultado"] = False
    puntos["pocos_pixeles_buenos"] = False
    puntos["indices_no_finitos"] = False

    pass_ids = puntos["pass_id"].unique()
    if args.only:
        pass_ids = [p for p in pass_ids if args.only in p]
    if args.limit:
        pass_ids = pass_ids[:args.limit]

    s3 = get_s3_client()
    for n, pass_id in enumerate(pass_ids, 1):
        print(f"[{n}/{len(pass_ids)}] {pass_id}")
        procesar_escena(puntos, pass_id, s3, args.bucket, args.prefix)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    puntos.to_csv(args.out, index_label="matchup_index")

    con_datos = puntos["B02_mean"].notna()
    sin_resultado = puntos["sin_resultado"]
    pocos = puntos["pocos_pixeles_buenos"]
    print(f"\n{args.out}: {len(puntos)} puntos")
    print(f"  con datos: {int(con_datos.sum())}")
    print(f"  sin_resultado: {int(sin_resultado.sum())}")
    print(f"  pocos_pixeles_buenos: {int(pocos.sum())}")
    print(f"  indices_no_finitos: {int(puntos['indices_no_finitos'].sum())}")
    print(f"  no procesados (--only/--limit): {int((~(con_datos | sin_resultado | pocos)).sum())}")


if __name__ == "__main__":
    main()
