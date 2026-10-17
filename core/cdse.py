"""Discover Sentinel-2 L1C products in the CDSE catalogue."""

import pystac
import requests

CATALOGUE = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"


def sensing_and_tile(item: pystac.Item) -> tuple[str, str]:
    """Return ('20220101T135111', '21HUD') for a Sentinel-2 STAC item.

    Planetary Computer ids look like S2A_MSIL2A_20220101T135111_R024_T21HUD_...,
    the same timestamp as the SAFE name. Otherwise fall back to properties.
    """
    parts = item.id.split("_")
    if len(parts) >= 5 and parts[1].startswith("MSIL"):
        tile = next(p[1:] for p in parts if p.startswith("T") and len(p) == 6)
        return parts[2], tile
    tile = item.properties.get("s2:mgrs_tile") or item.properties.get("grid:code", "").replace("MGRS-", "")
    # datatake sensing start, as used in the SAFE name
    dt = item.properties.get("s2:datatake_id", "")  # e.g. GS2A_20220101T135111_034220_N03.01
    stamp = dt.split("_")[1] if "_" in dt else item.datetime.strftime("%Y%m%dT%H%M%S")
    return stamp, tile


def find_l1c(stamp: str, tile: str) -> dict | None:
    """Query CDSE (anonymous) for the L1C product with this sensing time and tile."""
    flt = (
        "Collection/Name eq 'SENTINEL-2' "
        f"and contains(Name,'MSIL1C_{stamp}') and contains(Name,'_T{tile}_')"
    )
    r = requests.get(CATALOGUE, params={"$filter": flt, "$top": 20}, timeout=60)
    r.raise_for_status()
    products = [p for p in r.json()["value"] if p["Name"].endswith(".SAFE")]
    if not products:
        return None
    # if reprocessed, prefer the most recent processing baseline / production time
    products.sort(key=lambda p: p["Name"].split("_")[3] + p["Name"].split("_")[-1])
    best = products[-1]
    return {"name": best["Name"], "id": best["Id"], "online": best.get("Online", True)}
