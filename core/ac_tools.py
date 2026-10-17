import xarray as xr
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage

BAND_NAMES_MAPPING = {
    "rhow_443":  "B01", # no
    "rhow_492":  "B02",
    "rhow_560":  "B03",
    "rhow_665":  "B04",
    "rhow_704":  "B05",
    "rhow_740":  "B06",
    "rhow_783":  "B07",
    "rhow_833":  "B08", # no
    "rhow_865":  "B8A", # no
    "rhow_1614": "B11", # no
    "rhow_2202": "B12", # no
}

def nombres_bandas(dl):
    # S2A, S2B y S2C tienen longitudes de onda centrales distintas (rhow_443 en S2A, rhow_442 en S2B, ...):
    # cada rhow_<nm> se asigna a la banda nominal mas cercana
    nominales = {int(k.split("_")[1]): v for k, v in BAND_NAMES_MAPPING.items()}
    return {
        v: nominales[min(nominales, key=lambda nm: abs(nm - int(v.split("_")[1])))]
        for v in dl.data_vars if v.startswith("rhow_")
    }

def open_l2w(l2w_path: str):
    dl = xr.open_dataset(l2w_path)
    dl = dl.rename(nombres_bandas(dl))
    # se carga una vez: sino cada dl[banda].values lee y descomprime la banda entera de nuevo
    dl = dl.load()
    dl.close()
    return dl

def dist_punto_pixeles(p, lat_pixels, lon_pixels):
    # aproximación equirectangular
    d2 = (lat_pixels - p["lat"]) ** 2 + ((lon_pixels - p["lon"]) * np.cos(np.radians(p["lat"]))) ** 2
    return d2


def scene_box(points: pd.DataFrame, margin: float) -> list:
    return [points["lat"].min() - margin, points["lon"].min() - margin,
            points["lat"].max() + margin, points["lon"].max() + margin]


def split_points(points: pd.DataFrame, cluster_km: float) -> list:
    """Group a scene's points into boxes: single-linkage clusters whose nearest points are closer
    than cluster_km (distances in UTM metres). Boxes are ordered west to east (then south to
    north), so the numbering is stable for the same points."""
    if len(points) == 1:
        return [points]
    labels = fcluster(linkage(points[["x", "y"]].values / 1e3, "single"), t=cluster_km, criterion="distance")
    groups = [points[labels == lab] for lab in sorted(set(labels))]
    return sorted(groups, key=lambda g: (g["x"].min(), g["y"].min()))

