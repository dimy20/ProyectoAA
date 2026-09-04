# INUMET SYNOP CLI

## What is it

A small command-line tool (`tools/inumet.py`) for pulling surface weather
observation data (SYNOP) out of INUMET's public WIS2 API
(`https://w2b.inumet.gub.uy/oapi`) and saving it as a GeoJSON file.

## What it's for

Instead of writing API calls by hand, you can:

- list the available weather stations and their ids,
- list the available measurement parameters (temperature, humidity, wind, etc.),
- download observations for a station over a date range as a ready-to-use
  `.geojson` file (one point Feature per station/timestamp/parameter reading).

## Usage

List all stations (name, WIGOS id, coordinates):

```
uv run tools/inumet.py list-stations
```

List available parameters:

```
uv run tools/inumet.py list-params
```

List parameters with a description of what each one means:

```
uv run tools/inumet.py list-params --describe
```

Download observations for a station and date range:

```
uv run tools/inumet.py download 2026-08-01 2026-08-05 \
    --station-id 0-858-0-A000000000000004 \
    --param air_temp \
    out.geojson
```

Download multiple parameters at once (comma-separated), merged into one file:

```
uv run tools/inumet.py download 2026-08-01 2026-08-05 \
    --station-id 0-858-0-A000000000000004 \
    --param air_temp,rel_humidity,wind_speed \
    out.geojson
```

Dates are `YYYY-MM-DD` and the range is inclusive. Run any command with
`--help` (e.g. `uv run tools/inumet.py download --help`) for the full
list of options.
