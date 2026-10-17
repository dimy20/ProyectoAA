"""Run ACOLITE over every Sentinel-2 L1C scene that has matchups and archive the results to s3.

For each scene in the scenes csv (name, id, online):
  1. take all matchup points of that scene and group them into boxes: points closer than
     --cluster-km (single linkage, 20 km) share a box, so a few scattered points do not
     force one huge box (a 90 km box needed 44 min and ~650 MB, and killed a pod),
  2. download the L1C .SAFE from CDSE (once, even if the scene has several boxes),
  3. run ACOLITE cropped to each box (lat/lon bounding box + margin),
  4. upload the outputs to s3://<bucket>/<prefix>/<pass_id>/ (one box) or
     s3://<bucket>/<prefix>/<pass_id>/parte1/, parte2/, ... (several boxes, numbered west to east),
  5. delete the .SAFE and the local outputs.

Inputs: --scenes (csv) and --matchups (geojson) are required local paths; there is no default and
no fallback to s3.
The matchups file must declare EPSG:32721; missing or different CRS values are rejected.

Boxes whose L2W.nc is already in s3 are skipped, so the script can be re-run to resume. A scene
is done when all its boxes are done; an L2W.nc directly under <pass_id>/ (scenes processed before
the split existed) counts as the whole scene being done. The grouping is deterministic, so it must
be computed from the same matchups file to line up with what is already in s3.

CDSE outages: the token is reused for a few minutes (one identity request per scene at most). If
CDSE is unreachable or rejects authentication (5xx/429 from the download service, any error from
the token endpoint, network errors), scenes are NOT marked failed: the run waits with growing
pauses and retries the same scene. After --max-outage-min without progress the run stops, leaves
the remaining scenes untouched (so a rerun picks them up) and exits with code 2.

Crash guard: before each box a counter is written to <prefix>/_state/attempts/ and reset to 0 when
the box finishes (ok or handled error). It is reset, not deleted: the s3 user may lack DeleteObject. If the process dies hard (e.g. out-of-memory kill) the counter
stays; after MAX_CRASH_ATTEMPTS the box is skipped as `crashed` so a restarting pod does not loop
forever. --retry-crashed ignores the counters.

Parallel runs: launch N processes with SEGMENTO=1..N and the same N_SEGMENTOS=N (default 4). Scene
i of the csv goes to the process with SEGMENTO == i % N + 1 (round-robin), so there is no
coordinator: every process computes its share from the same csv. All N must be launched, with the
same N and the same csv, or scenes are left out. Unset SEGMENTO -> all scenes.

No imagery: when ACOLITE reports that the crop is 100% blackfill (the points lie outside the data
swath) the box is recorded in <prefix>/_state/no_data/ and skipped from then on, without downloading
the scene again.

Example:
    SEGMENTO=2 python tools/ac/run_acolite.py --scenes S.csv --matchups M.geojson --bucket my-bucket --prefix acolite
    python tools/ac/run_acolite.py --scenes S.csv --matchups M.geojson --no-upload --limit 1   # local smoke test
"""

import argparse
import json
import os
import shutil
import sys
import time
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from dotenv import load_dotenv
from pyproj import Transformer
from tqdm.auto import tqdm
import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "external" / "acolite"))
sys.path.insert(0, str(ROOT))

import acolite as ac  # noqa: E402
from core.s3 import DEFAULT_BUCKET, get_s3_client
from core.ac_tools import scene_box, split_points


load_dotenv()

TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
ZIPPER = "https://zipper.dataspace.copernicus.eu/odata/v1/Products({id})/$value"

DEFAULT_WORKDIR = ROOT / "acolite_work"

MATCHUPS_CRS = "EPSG:32721"
DOWNLOAD_RETRIES = 3
N_SEGMENTOS = 4               # default number of parallel processes (env N_SEGMENTOS overrides)
CLUSTER_KM = 20
MAX_CRASH_ATTEMPTS = 2
TOKEN_TTL_S = 8 * 60          # CDSE tokens last ~10 min
OUTAGE_WAIT_START_S = 60      # first pause when CDSE is down; doubles up to OUTAGE_WAIT_MAX_S
OUTAGE_WAIT_MAX_S = 10 * 60

ACOLITE_CONFIG_FILE = os.environ.get("ACOLITE_CONFIG_FILE", None)


class CdseUnavailable(Exception):
    """CDSE is down, throttling or rejecting authentication: a retry later may work, and it is
    not the scene's fault."""


_token_cache = {"value": None, "expires": 0.0}


def cdse_token() -> str:
    # reused across scenes: asking for a new token on every attempt hammers the identity service
    if _token_cache["value"] and time.monotonic() < _token_cache["expires"]:
        return _token_cache["value"]
    r = requests.post(TOKEN_URL, data={
        "grant_type": "password",
        "client_id": "cdse-public",
        "username": os.environ["CDSE_USERNAME"],
        "password": os.environ["CDSE_PASSWORD"],
    }, timeout=60)
    r.raise_for_status()
    _token_cache.update(value=r.json()["access_token"], expires=time.monotonic() + TOKEN_TTL_S)
    return _token_cache["value"]


def is_cdse_outage(e: Exception) -> bool:
    if isinstance(e, (requests.ConnectionError, requests.Timeout)):
        return True
    if isinstance(e, requests.HTTPError) and e.response is not None:
        return e.response.status_code in (429, 500, 502, 503, 504) or "identity.dataspace" in (e.response.url or "")
    return False


def download_safe(name: str, product_id: str, safe_dir: Path) -> Path:
    """Download and extract <name>.SAFE into safe_dir. `name` includes the .SAFE suffix."""
    safe_path = safe_dir / name
    if safe_path.exists():
        return safe_path
    safe_dir.mkdir(parents=True, exist_ok=True)
    zip_path = safe_dir / (name + ".zip")

    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {cdse_token()}"  # tokens last ~10 min
    url = ZIPPER.format(id=product_id)
    # follow redirects by hand so the auth header is kept
    r = session.get(url, allow_redirects=False, stream=True, timeout=120)
    while r.status_code in (301, 302, 303, 307, 308):
        url = r.headers["Location"]
        r = session.get(url, allow_redirects=False, stream=True, timeout=120)
    r.raise_for_status()

    total = int(r.headers.get("Content-Length", 0))
    with open(zip_path, "wb") as f, tqdm(total=total, unit="B", unit_scale=True,
                                         desc=name[:38], leave=False) as bar:
        for chunk in r.iter_content(chunk_size=8 * 1024 * 1024):
            f.write(chunk)
            bar.update(len(chunk))

    with zipfile.ZipFile(zip_path) as z:
        z.extractall(safe_dir)
    zip_path.unlink()
    return safe_path


def download_safe_retry(name: str, product_id: str, safe_dir: Path) -> Path:
    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        try:
            return download_safe(name, product_id, safe_dir)
        except (requests.RequestException, zipfile.BadZipFile) as e:
            # a partial download/extract must not be mistaken for a complete SAFE
            shutil.rmtree(safe_dir / name, ignore_errors=True)
            (safe_dir / (name + ".zip")).unlink(missing_ok=True)
            _token_cache["value"] = None  # the failure may be an expired/revoked token
            if attempt == DOWNLOAD_RETRIES:
                if is_cdse_outage(e):
                    raise CdseUnavailable(f"{type(e).__name__}: {e}") from e
                raise
            print(f"  download failed ({e}), retry {attempt}/{DOWNLOAD_RETRIES - 1}")
            time.sleep(10 * attempt)


def scene_key(pass_id: str) -> tuple:
    """(satellite, sensing time, tile). The same acquisition can be reprocessed later,
    which changes the processing baseline / processing time in the product name, so
    matching on the full name misses some scenes."""
    p = pass_id.split("_")
    return p[0], p[2], p[5]


def load_matchups(path: Path) -> pd.DataFrame:
    gdf = gpd.read_file(path)
    if gdf.crs is None or gdf.crs.to_epsg() != 32721:
        raise ValueError(f"{path}: expected CRS {MATCHUPS_CRS}, got {gdf.crs}")
    to_wgs84 = Transformer.from_crs(MATCHUPS_CRS, "EPSG:4326", always_xy=True)
    lon, lat = to_wgs84.transform(gdf.geometry.x.values, gdf.geometry.y.values)
    df = pd.DataFrame({"pass_id": gdf["pass_id"].values, "lat": lat, "lon": lon,
                       "x": gdf.geometry.x.values, "y": gdf.geometry.y.values})
    df["key"] = df["pass_id"].map(scene_key)
    return df


def done_parts(s3, bucket: str, prefix: str, n_parts: int) -> set:
    """1-based numbers of the boxes whose L2W.nc is already in s3.

    L2W is uploaded last, so its presence means the box finished. An L2W directly under
    <prefix>/ is the single-box layout (and scenes processed before the split existed): it
    covers the whole scene.
    """
    pages = s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=f"{prefix}/")
    rel = [o["Key"][len(prefix) + 1:] for page in pages for o in page.get("Contents", [])
           if o["Key"].endswith("_L2W.nc")]
    if any("/" not in r for r in rel):
        return set(range(1, n_parts + 1))
    return {i for i in range(1, n_parts + 1) if any(r.startswith(f"parte{i}/") for r in rel)}


def attempts_key(args, part_id: str) -> str:
    return f"{args.prefix}/_state/attempts/{part_id}.json"


def read_attempts(s3, bucket: str, key: str) -> int:
    try:
        return json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())["attempts"]
    except s3.exceptions.NoSuchKey:
        return 0


def write_attempts(s3, bucket: str, key: str, n: int):
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(
        {"attempts": n, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds")}).encode())


def no_data_key(args, part_id: str) -> str:
    return f"{args.prefix}/_state/no_data/{part_id}.json"


def no_data_parts(s3, args, pass_id: str, n_parts: int) -> set:
    """1-based numbers of the boxes already known to have no imagery (see run_part)."""
    pages = s3.get_paginator("list_objects_v2").paginate(Bucket=args.bucket, Prefix=no_data_key(args, pass_id)[:-len(".json")])
    stems = {o["Key"].rsplit("/", 1)[1][:-len(".json")] for page in pages for o in page.get("Contents", [])}
    return {i for i in range(1, n_parts + 1) if (pass_id if n_parts == 1 else f"{pass_id}_parte{i}") in stems}


def upload_dir(s3, bucket: str, prefix: str, directory: Path):
    # L2W goes last: its presence in s3 is what marks the box as done
    files = sorted((p for p in directory.rglob("*") if p.is_file()),
                   key=lambda p: p.name.endswith("_L2W.nc"))
    for f in files:
        s3.upload_file(str(f), bucket, f"{prefix}/{f.relative_to(directory).as_posix()}")


def acolite_log_text(out_dir: Path) -> str:
    logs = sorted(out_dir.glob("acolite_run_*_log_file.txt"))
    return logs[-1].read_text(errors="replace") if logs else ""


def acolite_log_tail(out_dir: Path, n: int = 15) -> str:
    logs = sorted(out_dir.glob("acolite_run_*_log_file.txt"))
    if not logs:
        return "(no ACOLITE log file found)"
    return "\n".join(logs[-1].read_text(errors="replace").splitlines()[-n:])


class RunLog:
    """One JSON line per scene (status ok | already_in_s3 | no_data | failed | crashed | offline | no_points).

    Written locally and, unless --no-upload, re-uploaded to s3://<bucket>/<prefix>/_logs/ after
    every scene, so what was done survives a container dying mid-run.
    """

    def __init__(self, args, s3):
        seg = os.environ.get("SEGMENTO") or "all"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.name = f"run-segmento{seg}-{stamp}.jsonl"
        self.path = args.workdir / "logs" / self.name
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch()
        self.s3, self.bucket, self.key = s3, args.bucket, f"{args.prefix}/_logs/{self.name}"
        self.counts = {}

    def add(self, row, pass_id, status, reason=None, **extra):
        self.counts[status] = self.counts.get(status, 0) + 1
        rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "scene": row["name"], "pass_id": pass_id, "status": status, "reason": reason, **extra}
        with open(self.path, "a") as f:
            f.write(json.dumps(rec) + "\n")
        self.upload()

    def upload(self):
        if self.s3 is None:
            return
        try:
            self.s3.upload_file(str(self.path), self.bucket, self.key)
        except Exception as e:  # logging must never kill the run
            print(f"  WARNING: could not upload run log: {e}")


def load_acolite_params() -> tuple[dict, float]:
    """Read the ACOLITE_CONFIG_FILE yaml. Returns (settings for ACOLITE, scene_box_margin).

    scene_box_margin is not an ACOLITE setting: it only sizes our own crop box (see scene_box), so it
    is split off here and must not reach acolite_run."""
    if not ACOLITE_CONFIG_FILE:
        raise RuntimeError("ACOLITE_CONFIG_FILE is not set (path to a yaml, e.g. experiments/acolite/setting_original.yaml)")
    with open(ACOLITE_CONFIG_FILE, "r", encoding="utf-8") as f:
        params = dict((yaml.safe_load(f) or {}).get("acolite_params") or {})
    if "scene_box_margin" not in params:
        raise RuntimeError(f"{ACOLITE_CONFIG_FILE}: acolite_params.scene_box_margin is required")
    margin = float(params.pop("scene_box_margin"))
    return params, margin


def run_part(safe_path: Path, pts: pd.DataFrame, out_dir: Path, part_prefix: str, part_id: str,
             args, s3, timings: dict) -> tuple:
    """Run ACOLITE on one box. Returns (status, reason); raises if ACOLITE fails."""
    if s3 is not None:
        key = attempts_key(args, part_id)
        n = read_attempts(s3, args.bucket, key)
        if n >= MAX_CRASH_ATTEMPTS and not args.retry_crashed:
            return "crashed", (f"process died {n} times while on this box (likely out of memory); "
                               f"delete s3://{args.bucket}/{key} or pass --retry-crashed to try again")
        write_attempts(s3, args.bucket, key, n + 1)

    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    try:

        acolite_params, scene_box_margin = load_acolite_params()

        settings = {
            "inputfile": str(safe_path),
            "output": str(out_dir),
            "limit": scene_box(pts, scene_box_margin),
            **acolite_params,
        }

        t0 = time.monotonic()
        ac.acolite.acolite_run(settings=settings)
        timings["acolite_s"] += time.monotonic() - t0

        if not list(out_dir.glob("*_L2W.nc")):
            if "100% blackfill" in acolite_log_text(out_dir):
                reason = "crop is 100% blackfill: no imagery over these points (swath edge)"
                if s3 is not None:
                    s3.put_object(Bucket=args.bucket, Key=no_data_key(args, part_id), Body=json.dumps(
                        {"reason": reason, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds")}).encode())
                return "no_data", reason
            raise RuntimeError("ACOLITE produced no L2W.nc. Last lines of its log:\n" + acolite_log_tail(out_dir))

        if s3 is not None:
            t0 = time.monotonic()
            upload_dir(s3, args.bucket, part_prefix, out_dir)
            timings["upload_s"] += time.monotonic() - t0
        return "ok", None
    finally:
        # reached on any normal exit (not on a hard kill): the box is no longer "in progress".
        # Reset instead of delete: the s3 user may not be allowed to DeleteObject.
        if s3 is not None:
            try:
                write_attempts(s3, args.bucket, attempts_key(args, part_id), 0)
            except Exception as e:
                print(f"  WARNING: could not clear attempts marker: {e}")
            shutil.rmtree(out_dir, ignore_errors=True)


def process_scene(row: pd.Series, points: pd.DataFrame, args, s3) -> dict:
    """Process every box of a scene that is not in s3 yet.

    Returns {"status", "reason", "parts", "timings"}; raises only if the .SAFE cannot be fetched.
    """
    name = row["name"]                     # ...SAFE
    # folder = pass_id as it appears in the matchups (can differ from the scene csv name
    # when the acquisition was reprocessed)
    pass_ids = points["pass_id"].unique()
    if len(pass_ids) != 1:
        raise RuntimeError(f"expected one pass_id for this scene, got {list(pass_ids)}")
    pass_id = pass_ids[0]
    prefix = f"{args.prefix}/{pass_id}"

    parts = split_points(points, args.cluster_km)
    n = len(parts)
    done = done_parts(s3, args.bucket, prefix, n) if s3 is not None else set()
    known_nd = no_data_parts(s3, args, pass_id, n) - done if s3 is not None else set()
    todo = [i for i in range(1, n + 1) if i not in done and i not in known_nd]
    timings = {"download_s": 0.0, "acolite_s": 0.0, "upload_s": 0.0}
    if not todo:
        print("  nothing to do (done or no imagery), skipping")
        return {"status": "no_data" if known_nd else "already_in_s3", "reason": None, "parts": n, "timings": timings}
    if n > 1:
        print(f"  {n} boxes ({len(done)} already in s3), processing {todo}")

    safe_dir = args.workdir / "safe"
    results = {}
    try:
        t0 = time.monotonic()
        safe_path = download_safe_retry(name, row["id"], safe_dir)
        timings["download_s"] = time.monotonic() - t0

        for i in todo:
            label = "" if n == 1 else f"parte{i}"
            out_dir = args.workdir / "out" / pass_id / label
            part_prefix = prefix if n == 1 else f"{prefix}/{label}"
            part_id = pass_id if n == 1 else f"{pass_id}_{label}"
            try:
                results[i] = run_part(safe_path, parts[i - 1], out_dir, part_prefix, part_id, args, s3, timings)
            except Exception as e:  # one bad box must not stop the others
                print(f"  {label or 'scene'} FAILED: {type(e).__name__}: {e}")
                results[i] = ("failed", f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=-4)}")
    finally:
        # the .SAFE is ~500 MB and the outputs are in s3 (or being discarded): never keep them
        shutil.rmtree(safe_dir / name, ignore_errors=True)
        (safe_dir / (name + ".zip")).unlink(missing_ok=True)

    bad = {i: r for i, r in results.items() if r[0] in ("failed", "crashed")}
    status = ("failed" if any(r[0] == "failed" for r in bad.values())
              else "crashed" if bad
              else "ok" if any(r[0] == "ok" for r in results.values()) else "no_data")
    shown = bad or {i: r for i, r in results.items() if r[0] == "no_data"}
    reason = "\n---\n".join(f"{'' if n == 1 else f'parte{i}: '}{r[1]}" for i, r in shown.items()) or None
    return {"status": status, "reason": reason, "parts": n, "timings": timings}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scenes", type=Path, required=True, help="csv with name,id,online")
    p.add_argument("--matchups", type=Path, required=True, help="geojson with pass_id points")
    p.add_argument("--bucket", default=DEFAULT_BUCKET)
    p.add_argument("--prefix", default="acolite", help="s3 key prefix; outputs go to <prefix>/<pass_id>/")
    p.add_argument("--no-upload", action="store_true",
                   help="do not upload to s3 (outputs are kept in <workdir>/out/<pass_id>")
    p.add_argument("--workdir", type=Path, default=DEFAULT_WORKDIR, help="scratch dir for SAFE downloads and outputs")
    p.add_argument("--cluster-km", type=float, default=CLUSTER_KM,
                   help="points closer than this share an ACOLITE box (single linkage); farther groups get their own box")
    p.add_argument("--max-outage-min", type=float, default=90,
                   help="stop the run if CDSE stays unavailable this long (the rest is left for a rerun)")
    p.add_argument("--retry-crashed", action="store_true",
                   help="ignore the crash counters in s3 and try boxes that killed the process before")
    p.add_argument("--limit", type=int, default=None, help="only process the first N scenes")
    p.add_argument("--only", default=None, help="only process scenes whose name contains this string")
    return p.parse_args()


def segment_slice(n: int) -> slice:
    """Rows of the scenes csv handled by $SEGMENTO (1..N), round-robin: row i goes to
    segment i % N + 1. N is $N_SEGMENTOS (default 4). All rows if SEGMENTO is unset."""
    raw = os.environ.get("SEGMENTO")
    if not raw:
        return slice(None)
    total = os.environ.get("N_SEGMENTOS") or str(N_SEGMENTOS)
    if not total.isdigit() or int(total) < 1:
        raise SystemExit(f"N_SEGMENTOS must be a positive integer, got {total!r}")
    total = int(total)
    if raw not in {str(i) for i in range(1, total + 1)}:
        raise SystemExit(f"SEGMENTO must be one of 1..{total}, got {raw!r}")
    return slice(int(raw) - 1, None, total)


def _maybe_terminate_pod():
    RUNPOD_API_KEY = os.environ.get("RUNPOD_API_KEY", None)
    POD_ID = os.environ.get("RUNPOD_POD_ID", None)
    if RUNPOD_API_KEY and POD_ID:
        import runpod
        runpod.api_key = RUNPOD_API_KEY
        runpod.terminate_pod(POD_ID)
            
def main():
    args = parse_args()
    load_acolite_params()  # fail now, not after downloading the first scene
    s3 = None if args.no_upload else get_s3_client()
    scenes = pd.read_csv(args.scenes)
    matchups = load_matchups(args.matchups)

    scenes["key"] = scenes["name"].map(lambda n: scene_key(n[:-len(".SAFE")]))
    missing = set(matchups["key"]) - set(scenes["key"])
    if missing:
        print(f"WARNING: {len(missing)} matchup scenes have no entry in {args.scenes.name}: {sorted(missing)}")
    scenes = scenes.iloc[segment_slice(len(scenes))].copy()  # before --only/--limit: segments stay stable
    if os.environ.get("SEGMENTO"):
        print(f"SEGMENTO={os.environ['SEGMENTO']} of {os.environ.get('N_SEGMENTOS') or N_SEGMENTOS}: {len(scenes)} scenes")
    if args.only:
        scenes = scenes[scenes["name"].str.contains(args.only)]
    if args.limit:
        scenes = scenes.head(args.limit)

    by_scene = {k: g for k, g in matchups.groupby("key")}
    log = RunLog(args, s3)
    print(f"Run log: {log.path}" + (f" -> s3://{args.bucket}/{log.key}" if s3 else ""))
    aborted = False
    for i, (_, row) in enumerate(scenes.iterrows(), 1):
        print(f"[{i}/{len(scenes)}] {row['name']}")
        points = by_scene.get(row["key"])
        if points is None:
            print("  no matchup points for this scene, skipping")
            log.add(row, None, "no_points")
            continue
        pass_id = points["pass_id"].iloc[0]
        if not row["online"]:
            print("  product is offline in CDSE (LTA), skipping")
            log.add(row, pass_id, "offline")
            continue
        waited, pause = 0.0, OUTAGE_WAIT_START_S
        while True:
            try:
                res = process_scene(row, points, args, s3)
                log.add(row, pass_id, res["status"], res["reason"], parts=res["parts"],
                        **{k: round(v, 1) for k, v in res["timings"].items()})
            except CdseUnavailable as e:
                if waited + pause > args.max_outage_min * 60:
                    print(f"  CDSE unavailable for {waited / 60:.0f} min, stopping the run")
                    log.add(row, pass_id, "aborted_cdse_unavailable",
                            f"CDSE unavailable for {waited / 60:.0f} min ({e}); scenes from this one on were not processed")
                    aborted = True
                    break
                print(f"  CDSE unavailable ({e}); waiting {pause:.0f}s and retrying this scene")
                log.add(row, pass_id, "cdse_wait", f"{e}; waited {waited:.0f}s so far, next pause {pause:.0f}s")
                time.sleep(pause)
                waited += pause
                pause = min(pause * 2, OUTAGE_WAIT_MAX_S)
                continue
            except Exception as e:  # keep going: one bad scene must not kill a multi-hour run
                print(f"  FAILED: {type(e).__name__}: {e}")
                log.add(row, pass_id, "failed", f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=-4)}")
            break
        if aborted:
            break

    log.upload()
    print(f"\nDone: {log.counts}")
    with open(log.path) as log_file:
        bad = [r for r in map(json.loads, log_file) if r["status"] in ("failed", "crashed", "offline", "aborted_cdse_unavailable")]
    for r in bad:
        reason_lines = (r["reason"] or "").splitlines()
        reason = reason_lines[0] if reason_lines else "(no reason recorded)"
        print(f"  {r['status']}: {r['pass_id']}: {reason}")
    # run is over and its log is in s3: stop paying for the pod (never with --no-upload,
    # the outputs would only exist on the pod's disk)
    if not args.no_upload:
        # leave a trace in the s3 log (before terminating: the pod may die right after the call)
        env_ok = {k: bool(os.environ.get(k)) for k in ("RUNPOD_POD_ID", "RUNPOD_API_KEY")}
        log.add({"name": None}, None, "pod_terminate", f"requesting termination, env present: {env_ok}")
        try:
            _maybe_terminate_pod()
        except Exception as e:
            print(f"WARNING: could not terminate pod: {type(e).__name__}: {e}")
            log.add({"name": None}, None, "pod_terminate_failed", f"{type(e).__name__}: {e}")
    if aborted:
        sys.exit(2)
    if bad:
        sys.exit(1)  # non-zero so the container/orchestrator shows the run as failed

if __name__ == "__main__":
    main()
