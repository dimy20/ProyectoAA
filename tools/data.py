"""CLI to archive the local data dir to s3 and download the latest checkpoint back."""

import argparse
import boto3
import os
from dotenv import load_dotenv
import zipfile
from datetime import datetime
from pathlib import Path
import time

load_dotenv()


BUCKET_NAME = "proyecto-water-aa"
# el 'src' de lata data
# Este script siempre va utilizar este dir para download/upload.
# todos los datos que se busquen persistir en s3 tiene que estar ahi.
SRC_DATA_DIR = "data" 

def get_s3_client():
  aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"]
  aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"]
  region_name=os.environ.get("AWS_REGION", "us-east-1")

  if not aws_access_key_id or not aws_secret_access_key or not region_name:
    raise RuntimeError("Missing AWS credentials")


  s3 = boto3.client(
    "s3",
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
    region_name=region_name
  )

  return s3


def zip_directory(dirname: Path, zfile: zipfile.ZipFile, base: Path = None):
  base = base or dirname
  for f in dirname.glob("*"):
    if f.is_file():
      zfile.write(f, arcname=f.relative_to(base))
    elif f.is_dir():
      zip_directory(f, zfile, base)

def upload_data_to_s3(s3_client):
  fname = f"{datetime.now().strftime('%Y-%m-%d-%H-%M-%S')}.zip"
  data_dir = Path(SRC_DATA_DIR)

  print(f"Archiving: {fname}")
  with zipfile.ZipFile(fname, "w", zipfile.ZIP_DEFLATED) as f:
    zip_directory(data_dir, f)

  print(f"Uploading {fname} to s3")

  s3_client.upload_file(
    Filename=fname,
    Bucket=BUCKET_NAME,
    Key=f"data_checkpoints/{fname}"
  )

  print("Cleaning up ...")
  Path(fname).unlink(missing_ok=True)

def _get_latest_key(keys: list):
  ans = []
  for k in keys:
    parts = k.split("/")
    date = parts[1][:-4]

    if "-" not in date:
      continue

    year, month, day, hour, min, second = date.split("-")

    dt_object = datetime(
      year=int(year), 
      month=int(month), 
      day=int(day), 
      hour=int(hour), 
      minute=int(min), 
      second=int(second)
    )

    ans.append((dt_object, k))

  ans = sorted(ans, key=lambda kv: kv[0])
  return ans[-1][1]

def _fetch_latest_checkpoint(s3_client) -> tuple[str, str]:
  """Descarga el zip del ultimo checkpoint a cwd y devuelve (key en s3, path local del zip)."""
  res = s3_client.list_objects(
    Bucket=BUCKET_NAME,
    Prefix="data_checkpoints"
  )

  objects = res["Contents"]
  keys = [obj["Key"] for obj in objects]
  latest = _get_latest_key(keys)
  save_name = latest.split("/")[1]

  s3_client.download_file(
    Bucket=BUCKET_NAME,
    Key=latest,
    Filename=save_name
  )

  return latest, save_name


def _select_members(zfile: zipfile.ZipFile, only: list[str] | None) -> list[str]:
  """Filtra los miembros del zip a los que caen bajo alguna de las rutas de `only`
  (relativas a data/, ej: 'bands', 'datasets/splits'). None/vacio = todos los miembros."""
  names = zfile.namelist()
  if not only:
    return names

  prefixes = [p.strip("/") for p in only]
  return [
    n for n in names
    if any(n == p or n.startswith(f"{p}/") for p in prefixes)
  ]


def list_latest(s3_client) -> None:
  """Lista las entradas de primer nivel disponibles en el ultimo checkpoint, sin extraerlas."""
  latest, save_name = _fetch_latest_checkpoint(s3_client)

  with zipfile.ZipFile(save_name, "r") as zfile:
    top_level = sorted({name.split("/")[0] for name in zfile.namelist()})

  Path(save_name).unlink(missing_ok=True)

  print(f"Checkpoint: {latest}")
  for name in top_level:
    print(f"  {name}")


def download_latest(s3_client, output_data_dir: str = SRC_DATA_DIR, only: list[str] | None = None):
  latest, save_name = _fetch_latest_checkpoint(s3_client)

  with zipfile.ZipFile(save_name, "r") as zfile:
    members = _select_members(zfile, only)
    if only and not members:
      available = sorted({n.split("/")[0] for n in zfile.namelist()})
      Path(save_name).unlink(missing_ok=True)
      raise ValueError(
        f"Ninguna de las rutas pedidas {only} existe en {latest}. "
        f"Disponibles (primer nivel): {available}"
      )
    for member in members:
      zfile.extract(member, output_data_dir)

  #delete zip file
  Path(save_name).unlink(missing_ok=True)

def main():
  parser = argparse.ArgumentParser(description="Download/archive data checkpoints to/from s3")
  subparsers = parser.add_subparsers(dest="command", required=True)

  download_parser = subparsers.add_parser("download", help="Download the latest data checkpoint from s3")
  download_parser.add_argument("-o", "--output-dir", default=SRC_DATA_DIR, help="Directory to extract the downloaded data into")
  download_parser.add_argument(
    "--only",
    nargs="+",
    default=None,
    metavar="PATH",
    help=(
      "Extraer solo estas rutas (relativas a data/, ej: --only bands datasets/splits). "
      "Por defecto extrae todo. Usa 'data.py list' para ver que hay disponible."
    ),
  )

  subparsers.add_parser("archive", help="Zip the data dir and upload it to s3")

  subparsers.add_parser("list", help="List the top-level entries in the latest checkpoint, without downloading them")

  args = parser.parse_args()

  s3 = get_s3_client()

  if args.command == "download":
    download_latest(s3, output_data_dir=args.output_dir, only=args.only)
  elif args.command == "archive":
    upload_data_to_s3(s3)
  elif args.command == "list":
    list_latest(s3)

if __name__ == '__main__':
  main()