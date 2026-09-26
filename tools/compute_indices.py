"""Compute water-quality indices for every extracted band sample.

Reads the per-sample .nc crops from data/bands/<all-bands>/shard-*/, runs
s2cloudless on samples that have B10 (can't run it at all on the ones that
don't -- s2cloudless needs B10 regardless of all_bands True/False), and
writes a new geojson with the index columns added to the matchups.
"""

import warnings
from pathlib import Path
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from omnicloudmask import predict_from_array
from s2cloudless import S2PixelCloudDetector

#CLOUD_DETECTOR = "omnicloudmask"  # "s2cloudless" or "omnicloudmask"
CLOUD_DETECTOR = "s2cloudless"  # "s2cloudless" or "omnicloudmask"

DATA = Path("data")
MATCHUPS_FILE = DATA / "registros_limpios_matchups.json"
BANDS_DIR = DATA / "bands" / "B07-B06-B05-B04-B03-B02-B01-B08-B8A-B09-B10-B11-B12"
OUT_FILE = DATA / f"matchup_indices_{CLOUD_DETECTOR}.geojson"

S2_BAND_ORDER = ["B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B09", "B10", "B11", "B12"]

bands_for_index = {
    "ndci": ["B04", "B05"],
    "indice_tres_bandas": ["B04", "B05", "B07"],
    "indice_combinado": ["B05", "B06", "B04", "B02"],
    "compare_green_rededge": ["B03", "B06"],
    "s2_cloudless": ["B01", "B02", "B04", "B05", "B08", "B8A", "B09", "B10", "B11", "B12"],
}

REQUIRED_FOR_INDICES = {"B02", "B03", "B04", "B05", "B06", "B07"}


def normalize_bands():
    unique_bands = set()
    for bands in bands_for_index.values():
        for b in bands:
            unique_bands.add(b)
    return [b for b in S2_BAND_ORDER if b in unique_bands]


NEEDED_BANDS = normalize_bands()
WINDOW_SIZE = 5
HALF_W = WINDOW_SIZE // 2
CLOUD_THRESHOLD = 0.2

OMNICLOUDMASK_BANDS = ["B04", "B03", "B08"]  # red, green, NIR
OMNICLOUDMASK_MIN_SIZE = 32
OMNICLOUDMASK_NODATA = -9999.0
MAX_REMAINING_PIXELS_AFTER_CLOUD_DETECTION = 5

EMPTY_RESULT = {
    "ndci_median": np.nan,
    "ndci_mean": np.nan,
    "ndci_iqr": np.nan,
    "ndci_std": np.nan,
    "indice_tres_bandas_median": np.nan,
    "indice_tres_bandas_mean": np.nan,
    "indice_tres_bandas_iqr": np.nan,
    "indice_tres_bandas_std": np.nan,
    "indice_combinado_median": np.nan,
    "indice_combinado_mean": np.nan,
    "indice_combinado_iqr": np.nan,
    "indice_combinado_std": np.nan,
    "dif_green_rededge_median": np.nan,
    "dif_green_rededge_mean": np.nan,
    "dif_green_rededge_iqr": np.nan,
    "dif_green_rededge_std": np.nan,
    "B02_median": np.nan,
    "B02_mean": np.nan,
    "B03_median": np.nan,
    "B03_mean": np.nan,
    "B04_median": np.nan,
    "B04_mean": np.nan,
    "B05_median": np.nan,
    "B05_mean": np.nan,
    "B06_median": np.nan,
    "B06_mean": np.nan,
    "B07_median": np.nan,
    "B07_mean": np.nan,
    "paso_cloudless": None,
    "n_pixeles_usados": np.nan,
    "ventana_recortada": None,
}


def find_nc_files() -> dict[int, Path]:
    return {int(p.stem): p for p in BANDS_DIR.glob("shard-*/*.nc")}


def nearest_pixel(ds: xr.Dataset, px: float, py: float) -> tuple[int, int]:
    x_idx = int(np.abs(ds["x"].values - px).argmin())
    y_idx = int(np.abs(ds["y"].values - py).argmin())
    return y_idx, x_idx


def clamped_start(center: int, size: int) -> int | None:
    if size < WINDOW_SIZE:
        return None
    start = center - HALF_W
    return max(0, min(start, size - WINDOW_SIZE))


def omnicloudmask_clear_mask(A: xr.DataArray, band2index: dict, H: int, W: int) -> np.ndarray:
    """Clear-pixel mask via omnicloudmask (only needs B04/B03/B08, unlike s2cloudless).

    Our crops never reach the model's 32x32 minimum, so we pad the *full* crop
    with a sentinel and predict, then crop the output back down to the real
    extent. The padded region isn't flagged as invalid by the model on its own,
    so we have to discard it ourselves rather than trust the output there.
    Returns the full (H, W) mask -- windowing happens later, after masking.
    """
    real = np.stack([A[band2index[b]].to_numpy() for b in OMNICLOUDMASK_BANDS]).astype(np.float32)

    pad_h = max(OMNICLOUDMASK_MIN_SIZE, H)
    pad_w = max(OMNICLOUDMASK_MIN_SIZE, W)
    padded = np.full((3, pad_h, pad_w), OMNICLOUDMASK_NODATA, dtype=np.float32)
    padded[:, :H, :W] = real

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pred = predict_from_array(padded, no_data_value=OMNICLOUDMASK_NODATA)

    return pred[0, :H, :W] == 0  # 0 = clear, discard the padded region


def s2cloudless_clear_mask(full: np.ndarray, detector: S2PixelCloudDetector) -> np.ndarray:
    """Clear-pixel mask via s2cloudless, run over the full crop (H, W)."""
    prob = detector.get_cloud_probability_maps(full)
    return np.squeeze(prob < CLOUD_THRESHOLD, axis=0)


def iqr(vals: np.ndarray) -> float:
    """Interquartile range (Q3 - Q1): a spread measure alongside median/mean."""
    q75, q25 = np.percentile(vals, [75, 25])
    return float(q75 - q25)


def mndwi_water_mask(A: xr.DataArray, band2index: dict) -> np.ndarray:
    """Water-pixel mask via MNDWI (Xu 2006): (B03 - B11) / (B03 + B11) > 0 = water."""
    B03 = A[band2index["B03"]].to_numpy()
    B11 = A[band2index["B11"]].to_numpy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        mndwi = (B03 - B11) / (B03 + B11)
    return mndwi > 0


def process_row(index, row, nc_files: dict[int, Path], detector: Optional[S2PixelCloudDetector]) -> dict:
    result = dict(EMPTY_RESULT)

    path = nc_files.get(index)
    if path is None:
        return result

    ds = xr.open_dataset(path)
    try:
        available_bands = [b for b in NEEDED_BANDS if b in ds.data_vars]
        if not REQUIRED_FOR_INDICES.issubset(available_bands):
            return result
        if "B11" not in available_bands:
            return result  # needed for the MNDWI water mask

        H, W = ds.sizes["y"], ds.sizes["x"]
        y_idx, x_idx = nearest_pixel(ds, row.geometry.x, row.geometry.y)

        y0 = clamped_start(y_idx, H)
        x0 = clamped_start(x_idx, W)
        if y0 is None or x0 is None:
            return result  # crop smaller than the window, can't build a full one

        result["ventana_recortada"] = (y0 != y_idx - HALF_W) or (x0 != x_idx - HALF_W)

        A = ds[available_bands].isel(time=0).to_dataarray()
        band2index = {name: i for i, name in enumerate(available_bands)}

        # 1. cloud detector -- runs over the FULL crop, not the window
        if CLOUD_DETECTOR == "s2cloudless":
            has_b10 = "B10" in available_bands
            if has_b10:
                full = np.expand_dims(A.to_numpy().transpose(1, 2, 0), axis=0)  # (band,y,x) -> (1,y,x,band)
                cloud_mask = s2cloudless_clear_mask(full, detector)
                result["paso_cloudless"] = True
            else:
                cloud_mask = np.ones((H, W), dtype=bool)
                result["paso_cloudless"] = False
        elif CLOUD_DETECTOR == "omnicloudmask":
            if not set(OMNICLOUDMASK_BANDS).issubset(available_bands):
                return result
            cloud_mask = omnicloudmask_clear_mask(A, band2index, H, W)
            result["paso_cloudless"] = True
        else:
            raise ValueError(f"unknown CLOUD_DETECTOR: {CLOUD_DETECTOR!r}")

        # 2. water mask -- also over the FULL crop
        water_mask = mndwi_water_mask(A, band2index)

        combined_mask = cloud_mask & water_mask

        # 3. window -- only now do we restrict to the point's neighborhood
        window = A[:, y0:y0 + WINDOW_SIZE, x0:x0 + WINDOW_SIZE].to_numpy()
        window = window.transpose(1, 2, 0)  # (band, y, x) -> (y, x, band)
        window = np.expand_dims(window, axis=0)
        window_mask = combined_mask[y0:y0 + WINDOW_SIZE, x0:x0 + WINDOW_SIZE]

        pix = window[:, window_mask]

        result["n_pixeles_usados"] = int(pix.shape[1])

        if pix.shape[1] < MAX_REMAINING_PIXELS_AFTER_CLOUD_DETECTION:
            return result

        def band(name):
            return pix[0, :, band2index[name]]

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            B02, B03, B04, B05, B06, B07 = (band(n) for n in ("B02", "B03", "B04", "B05", "B06", "B07"))

            ndci_vals = (B05 - B04) / (B05 + B04)
            tres_bandas_vals = B07 * (0.1 * B04 - 0.1 * B05)
            combinado_vals = B05 * (B06 + B04) / B02
            green_rededge_vals = B03 / B06

            result["ndci_median"] = float(np.median(ndci_vals))
            result["ndci_mean"] = float(np.mean(ndci_vals))
            result["ndci_iqr"] = iqr(ndci_vals)
            result["ndci_std"] = float(np.std(ndci_vals))
            result["indice_tres_bandas_median"] = float(np.median(tres_bandas_vals))
            result["indice_tres_bandas_mean"] = float(np.mean(tres_bandas_vals))
            result["indice_tres_bandas_iqr"] = iqr(tres_bandas_vals)
            result["indice_tres_bandas_std"] = float(np.std(tres_bandas_vals))
            result["indice_combinado_median"] = float(np.median(combinado_vals))
            result["indice_combinado_mean"] = float(np.mean(combinado_vals))
            result["indice_combinado_iqr"] = iqr(combinado_vals)
            result["indice_combinado_std"] = float(np.std(combinado_vals))
            result["dif_green_rededge_median"] = float(np.median(green_rededge_vals))
            result["dif_green_rededge_mean"] = float(np.mean(green_rededge_vals))
            result["dif_green_rededge_iqr"] = iqr(green_rededge_vals)
            result["dif_green_rededge_std"] = float(np.std(green_rededge_vals))

            # raw calibrated bands too, not just the derived index formulas --
            # lets a model find its own combinations instead of only the hand-crafted ones
            for name, vals in (("B02", B02), ("B03", B03), ("B04", B04), ("B05", B05), ("B06", B06), ("B07", B07)):
                result[f"{name}_median"] = float(np.median(vals))
                result[f"{name}_mean"] = float(np.mean(vals))

        return result
    finally:
        ds.close()


def main() -> None:
    matchups = gpd.read_file(MATCHUPS_FILE)
    matchups["sample_id"] = matchups.index  # GeoJSON has no index concept -- preserve it as a real column,
                                             # since it no longer matches file row-order once rows get dropped
    nc_files = find_nc_files()
    detector = None
    if CLOUD_DETECTOR == "s2cloudless":
        detector = S2PixelCloudDetector(threshold=CLOUD_THRESHOLD, average_over=0, dilation_size=0, all_bands=True)

    print(f"cloud detector: {CLOUD_DETECTOR}")
    records = [process_row(index, row, nc_files, detector) for index, row in matchups.iterrows()]

    result_df = pd.DataFrame(records, index=matchups.index)
    out = matchups.join(result_df)

    before = len(out)
    out = out[~(out["n_pixeles_usados"] < MAX_REMAINING_PIXELS_AFTER_CLOUD_DETECTION)]
    print(f"dropped {before - len(out)} rows below MAX_REMAINING_PIXELS_AFTER_CLOUD_DETECTION={MAX_REMAINING_PIXELS_AFTER_CLOUD_DETECTION}")

    out.to_file(OUT_FILE, driver="GeoJSON")
    print(f"wrote {OUT_FILE} ({len(out)} rows)")


if __name__ == "__main__":
    main()
