import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import geopandas as gpd
import numpy as np
import pystac
from dotenv import load_dotenv
from pyproj import Transformer
import odc.stac
import xarray as xr
from tqdm.auto import tqdm
from typing import List

from bands import (
    configure_gdal_env, 
    bands_downsample, 
    compute_reflectance,
    is_valid_band
)

load_dotenv()

DATA = Path("data")
MATCHUPS_FILE = DATA / "registros_limpios_matchups.json"
ITEMS_FILE = DATA / "matchup_items.json"
DEFAULT_BANDS = ["B07", "B06", "B05", "B04", "B03", "B02"]
WINDOW_DEG = 0.005  # ~550m alrededor del punto
NUM_SHARDS = 4

def load_items():
    ic = pystac.ItemCollection.from_file(str(ITEMS_FILE))
    item_by_id = {item.id: item for item in ic}
    return ic, item_by_id

def download(matchups: gpd.GeoDataFrame, bands: List[str], shard_id: int, limit: int | None = None, window_deg: float = WINDOW_DEG) -> None:
    configure_gdal_env()
    to_wgs84 = Transformer.from_crs("EPSG:32721", "EPSG:4326", always_xy=True)

    BASE_DIR = DATA / "bands" / f"-".join(bands)
    OUT_DIR = BASE_DIR

    if shard_id != -1:
        OUT_DIR = OUT_DIR / f"shard-{shard_id}"

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    already_downloaded = set()
    if shard_id == -1:
        # full range (no sharding): also skip anything already fetched by shard workers
        already_downloaded = {p.stem for p in BASE_DIR.glob("shard-*/*.nc")}

    ic, item_by_id = load_items()
    resolution = bands_downsample(bands)

    if limit:
        matchups = matchups.head(limit)

    for index, row in tqdm(matchups.iterrows(), total=len(matchups), desc="Downloading bands", unit="Item"):
        out_path = OUT_DIR / f"{index}.nc"
        if out_path.exists() or str(index) in already_downloaded:
            continue

        item = item_by_id.get(row["pass_id"])
        if item is None:
            raise RuntimeError(f"[{index}] missing item for pass_id={row['pass_id']}, skipping")

        x, y = to_wgs84.transform(row.geometry.x, row.geometry.y)
        bbox = [x - window_deg, y - window_deg, x + window_deg, y + window_deg]

        try:
            ds = odc.stac.load(
                [item],
                bands=bands,
                resolution=resolution,
                bbox=bbox,
                chunks=None,
                resampling="average"
            )
            ds = compute_reflectance(ds, item)
        except Exception as e:
            print(f"[{index}] failed: {e}")
            continue

        ds.to_netcdf(out_path)
        print(f"[{index}] saved {out_path.name}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--bands", type=str, default=",".join(DEFAULT_BANDS)) # lista de bandas a descargar separadas por coma
    parser.add_argument("--window-deg", type=float, default=WINDOW_DEG)
    parser.add_argument("--shard-id", type=int, default=-1)
    #para
    args = parser.parse_args()

    bands = args.bands
    bands = bands.split(",")

    shard_id = args.shard_id

    matchups = gpd.read_file(MATCHUPS_FILE)
    matchups = matchups[matchups["pass_id"].notna()]

    N = matchups.shape[0]
    shard_size = N // NUM_SHARDS

    start_index = 0
    end_index = N+1

    if shard_id != -1:
        if shard_id < 1 or shard_id > NUM_SHARDS:
            parser.error(f"invalid shard_id: {shard_id} can only be one of [1..{NUM_SHARDS}]")

        start_index = (shard_id-1)*shard_size
        end_index = N if shard_id == NUM_SHARDS else shard_id*shard_size


    if shard_id != -1:
        print(f"Downloading shard_id={shard_id}, range = ({start_index}, {end_index})")

    matchups_range = matchups.iloc[start_index:end_index]

    for b in bands:
        if not is_valid_band(b):
            parser.error(f"invalid band: {b}")

    download(matchups_range, bands, shard_id, limit=args.limit, window_deg=args.window_deg)
