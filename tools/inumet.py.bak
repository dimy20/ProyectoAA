import httpx
import json
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Set
import pandas as pd
from tqdm import tqdm
import argparse

URL="https://w2b.inumet.gub.uy/oapi"
#/collections/stations/schema
RIVERA_STATION = "0-858-0-A000000000000004"

VARIABLE_SHORT_NAMES = {
    "air_temperature": "air_temp",
    "dewpoint_temperature": "dewpoint_temp",
    "maximum_temperature_at_height_and_over_period_specified": "air_temp_max",
    "minimum_temperature_at_height_and_over_period_specified": "air_temp_min",
    "relative_humidity": "rel_humidity",
    "non_coordinate_pressure": "station_pressure",
    "pressure_reduced_to_mean_sea_level": "pressure_msl",
    "characteristic_of_pressure_tendency": "pressure_tendency_char",
    "wind_direction": "wind_dir",
    "wind_speed": "wind_speed",
    "maximum_wind_gust_speed": "wind_gust_max",
    "total_precipitation_past24hours": "precip_24h",
    "total_precipitation_or_total_water_equivalent": "precip_water_equiv",
    "cloud_amount": "cloud_amount",
    "cloud_cover_total": "cloud_cover_total",
    "cloud_type": "cloud_type",
    "height_of_base_of_cloud": "cloud_base_height",
    "horizontal_visibility": "visibility_horiz",
    "present_weather": "weather_present",
    "past_weather1": "weather_past1",
    "past_weather2": "weather_past2",
    "state_of_ground": "ground_state",
}

SHORT_TO_LONG_NAME = {short: long for long, short in VARIABLE_SHORT_NAMES.items()}

PARAM_DESCRIPTIONS = {
    "air_temp": "Air temperature at screen height",
    "dewpoint_temp": "Dewpoint temperature at screen height",
    "air_temp_max": "Maximum air temperature over the specified period",
    "air_temp_min": "Minimum air temperature over the specified period",
    "rel_humidity": "Relative humidity",
    "station_pressure": "Atmospheric pressure at station level (not reduced to sea level)",
    "pressure_msl": "Atmospheric pressure reduced to mean sea level",
    "pressure_tendency_char": "Characteristic of pressure tendency (WMO code table 0200)",
    "wind_dir": "Wind direction",
    "wind_speed": "Wind speed",
    "wind_gust_max": "Maximum wind gust speed over the specified period",
    "precip_24h": "Total precipitation over the past 24 hours",
    "precip_water_equiv": "Total precipitation or total water equivalent over the specified period",
    "cloud_amount": "Cloud amount (WMO code table 2700)",
    "cloud_cover_total": "Total cloud cover",
    "cloud_type": "Cloud type (WMO code table)",
    "cloud_base_height": "Height of base of the lowest cloud layer",
    "visibility_horiz": "Horizontal visibility",
    "weather_present": "Present weather code (WMO code table 4677)",
    "weather_past1": "Past weather code, most significant (WMO code table 4561)",
    "weather_past2": "Past weather code, second most significant (WMO code table 4561)",
    "ground_state": "State of the ground (WMO code table 0901)",
}

HTTP_TIMEOUT = 30.0
MAX_RETRIES = 3

def http_get(url: str, params: dict) -> httpx.Response:
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            return httpx.get(url, params=params, timeout=HTTP_TIMEOUT)
        except httpx.TransportError as e:
            last_exc = e
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
    raise last_exc

def to_utc_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def get_params_range(station_id: str, param: str, start: str, end: str, offset:int = 0):
    res = http_get(
        url=f"{URL}/collections/urn:wmo:md:uy-inumet:surface-based-observations.synop/items",
        params={
            "f": "json",
            "crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
            "properties": "name,units,value,reportTime,wigos_station_identifier",
            "wigos_station_identifier": station_id,
            "skipGeometry": True,
            "datetime": f"{start}/{end}",
            "sortby": "reportTime",
            "name": param,
            "offset": offset,
            "limit": 1000
        }
    )
    if res.status_code == 200:
        data = res.json()
        num_matched = data.get("numberMatched")
        num_returned = data.get("numberReturned")
        features = data.get("features")
        return num_returned, num_matched, features
    else:
        print(f"ERROR: {res.content}")
        return None, None, None

def get_station_by_id(station_id: str):
    res = http_get(
        url=f"{URL}/collections/stations/items",
        params={
            "f": "json",
            "wigos_station_identifier": station_id,
            "properties": "name,wigos_station_identifier"
        }
    )
    data = res.json()
    features = data.get("features")
    return features[0]

def download_param_observations(station_id: str, station_name: str, long_param_name: str, short_param_name: str,
                                 start: str, end: str, coords) -> list[dict]:
    num_returned, total, features = get_params_range(station_id, long_param_name, start, end)
    if not features:
        return []

    geojson_features = []
    step = num_returned

    offsets = range(0, total, step) if total else []
    for offset in tqdm(offsets, desc=f"Downloading {short_param_name}"):
        if offset > 0:
            _, _, features = get_params_range(station_id, long_param_name, start, end, offset)

        for m in features:
            props = m.get("properties")
            wigos_station_id = props.get("wigos_station_identifier")
            # server drops the wigos_station_identifier filter when combined
            # with `name`, so we filter client-side
            if wigos_station_id != station_id:
                continue

            geojson_features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": coords},
                "properties": {
                    "wigos_station_identifier": station_id,
                    "station_name": station_name,
                    "param": short_param_name,
                    "value": props.get("value"),
                    "units": props.get("units"),
                    "reportTime": props.get("reportTime"),
                }
            })

    return geojson_features

def build_geojson(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}

def list_stations():
    res = http_get(
        url=f"{URL}/collections/stations/items",
        params={
            "f": "json"
        }
    )
    if res.status_code == 200:
        data = res.json()
        for f in data["features"]:
            props = f.get("properties")
            geometry = f.get("geometry")
            coords = geometry.get("coordinates")
            name = props.get("name")
            _id = props.get("id")
            print(f"{name=}, id={_id}, location={coords}")
    else:
        print(f"Error: {res.content}")

def cmd_list_stations(args):
    list_stations()

def cmd_list_params(args):
    for short_name in sorted(PARAM_DESCRIPTIONS):
        if args.describe:
            long_name = SHORT_TO_LONG_NAME[short_name]
            print(f"{short_name} — {long_name} — {PARAM_DESCRIPTIONS[short_name]}")
        else:
            print(short_name)

def cmd_download(args):
    short_params = args.param.split(",")
    unknown = [p for p in short_params if p not in SHORT_TO_LONG_NAME]
    if unknown:
        valid = ", ".join(sorted(PARAM_DESCRIPTIONS))
        sys.exit(f"Unknown param(s): {', '.join(unknown)}\nValid params: {valid}")

    station = get_station_by_id(args.station_id)
    coords = station.get("geometry").get("coordinates")[:2]  # lon, lat only
    station_name = station.get("properties").get("name")

    start = args.start_date.strftime("%Y-%m-%d")
    end = args.end_date.strftime("%Y-%m-%d")

    all_features = []
    for short_param in short_params:
        long_param = SHORT_TO_LONG_NAME[short_param]
        all_features.extend(
            download_param_observations(args.station_id, station_name, long_param, short_param, start, end, coords)
        )

    with open(args.output, "w") as f:
        json.dump(build_geojson(all_features), f, indent=2)

    print(f"station={args.station_id} params={short_params} range={start}/{end} "
          f"features={len(all_features)} -> {args.output}")

def parse_date(s: str) -> datetime:
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid date '{s}', expected YYYY-MM-DD")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog="nueva_api_inumet.py",
        description="Fetch SYNOP surface observations from INUMET's public WIS2 API "
                     "(https://w2b.inumet.gub.uy/oapi) and export them as GeoJSON.",
        epilog="examples:\n"
               "  %(prog)s list-stations\n"
               "  %(prog)s list-params --describe\n"
               "  %(prog)s download 2026-08-01 2026-08-05 \\\n"
               "      --station-id 0-858-0-A000000000000004 \\\n"
               "      --param air_temp,rel_humidity out.geojson\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    sub.add_parser(
        "list-stations",
        help="list all SYNOP stations (name, WIGOS id, lon/lat/elevation)",
        description="List all SYNOP stations known to the API, with their WIGOS id and location.",
    )

    p_params = sub.add_parser(
        "list-params",
        help="list available observation parameters",
        description="List the short parameter names accepted by `download --param`.",
    )
    p_params.add_argument(
        "--describe", action="store_true",
        help="also show the underlying API variable name and a one-line description of each param",
    )

    p_dl = sub.add_parser(
        "download",
        help="download observations for a station and date range as GeoJSON",
        description="Download SYNOP observations for one station over a date range and "
                     "write them to a GeoJSON FeatureCollection (one Feature per "
                     "station/timestamp/parameter reading). Run `list-params` to see valid "
                     "--param values.",
    )
    p_dl.add_argument("start_date", type=parse_date, metavar="START_DATE",
                       help="first day to include, format YYYY-MM-DD")
    p_dl.add_argument("end_date", type=parse_date, metavar="END_DATE",
                       help="last day to include, format YYYY-MM-DD (inclusive)")
    p_dl.add_argument("output", metavar="OUTPUT",
                       help="path to write the resulting GeoJSON file to, e.g. out.geojson")
    p_dl.add_argument("--station-id", required=True, metavar="WIGOS_ID",
                       help="station WIGOS id, e.g. 0-858-0-A000000000000004 (see list-stations)")
    p_dl.add_argument("--param", required=True, metavar="PARAM[,PARAM...]",
                       help="comma-separated short param name(s), e.g. air_temp,rel_humidity "
                            "(see list-params)")

    args = parser.parse_args()

    {
        "list-stations": cmd_list_stations,
        "list-params": cmd_list_params,
        "download": cmd_download,
    }[args.command](args)
