import pystac
import xarray as xr
import os

BAND_RESOLUTION = {
    "B01": 60, "B02": 10, "B03": 10, "B04": 10, "B05": 20, "B06": 20, "B07": 20,
    "B08": 10, "B8A": 20, "B09": 60, "B10": 60, "B11": 20, "B12": 20,
}

def bands_downsample(bands: list[str]) -> int:
    return max(BAND_RESOLUTION[b] for b in bands)

def is_valid_band(band: str) -> bool:
    return band in BAND_RESOLUTION

COPERNICUS_S3_HOST = "eodata.dataspace.copernicus.eu"

def configure_gdal_env() -> None:
    os.environ["AWS_ACCESS_KEY_ID"] = os.environ["CDSE_S3_ACCESS_KEY"]
    os.environ["AWS_SECRET_ACCESS_KEY"] = os.environ["CDSE_S3_SECRET_KEY"]
    os.environ["AWS_S3_ENDPOINT"] = COPERNICUS_S3_HOST
    os.environ["AWS_VIRTUAL_HOSTING"] = "FALSE"
    os.environ.pop("AWS_REGION", None)
    os.environ.pop("AWS_NO_SIGN_REQUEST", None)

def compute_reflectance(ds: xr.Dataset, item: pystac.Item) -> xr.Dataset:
    corrected = {}
    ds.data_vars
    for band in ds.data_vars:

        asset = item.assets[band]
        scale = asset.extra_fields.get("raster:scale", 1.0)
        offset = asset.extra_fields.get("raster:offset", 0.0)

        corrected[band] = ds[band] * scale + offset

    return ds.assign(**corrected)