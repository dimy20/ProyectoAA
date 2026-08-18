from pymongo import MongoClient
import argparse
from datetime import date
from typing import Literal
import geopandas as geo
import pandas as pd
from shapely.geometry import shape
from dotenv import load_dotenv
import os
import psycopg
from psycopg.rows import dict_row
load_dotenv(override=True)

COLLECTIONS = [
    "estaciones",
    "puntos_grilla",
    "departamentos",
    "cuencas",
    "sentinel_locations",
]

URL = os.environ.get("MONGO_URI")
EXPORT_PATH = os.environ.get("EXPORT_PATH", ".")
os.makedirs(EXPORT_PATH, exist_ok=True)

def export_estaciones(client: MongoClient, output_dir=None):
    output_dir = output_dir or EXPORT_PATH
    db = client["grp05db"]
    db_estaciones = db["estaciones"]
    all_stations  = db_estaciones.find().to_list()

    estaciones = []
    X = []
    Y = []
    for e in all_stations:
        nombre = e.get("nombre")
        coords = e.get("location").get("coordinates")
        X.append(coords[0])
        Y.append(coords[1])

        if not nombre.startswith("URY"):
            if "G3" in nombre:
                estaciones.append({
                    "nombre": e.get("nombre"),
                    "type": "METEO",
                })
            else:
                estaciones.append({
                    "nombre": e.get("nombre"),
                    "type": "CLIMA"
                })
        else:
            estaciones.append({
                "nombre": e.get("nombre"),
                "type": "GEMS"
            })

    df = geo.GeoDataFrame(
        estaciones,
        geometry=geo.points_from_xy(
            X, Y
        ),
        crs="EPSG:4326"
    )
    df.to_file(os.path.join(output_dir, "estaciones.geojson"), driver="GeoJSON")

def export_puntos_grilla(client: MongoClient, output_dir=None):
    output_dir = output_dir or EXPORT_PATH
    db = client["grp05db"]
    db_grilla = db["puntos_grilla"]
    all_points = db_grilla.find().to_list()

    X = []
    Y = []
    for p in all_points:
        coords = p.get("location").get("coordinates")
        X.append(coords[0])
        Y.append(coords[1])

    df = geo.GeoDataFrame(
        geometry=geo.points_from_xy(
            X, Y
        ),
        crs="EPSG:4326"
    )
    df.to_file(os.path.join(output_dir, "puntos_grilla.geojson"), driver="GeoJSON")

def export_departamentos(client: MongoClient, output_dir=None):
    output_dir = output_dir or EXPORT_PATH
    db = client["grp05db"]
    db_departamentos = db["departamentos"]
    all_departamentos = db_departamentos.find().to_list()

    departamentos = []
    geometries = []
    for d in all_departamentos:
        departamentos.append({
            "nombre": d.get("nombre"),
            "codigo": d.get("codigo"),
        })
        geometries.append(shape(d.get("geometry")))

    df = geo.GeoDataFrame(
        departamentos,
        geometry=geometries,
        crs="EPSG:4326"
    )
    df.to_file(os.path.join(output_dir, "departamentos.geojson"), driver="GeoJSON")

def export_cuencas(client: MongoClient, output_dir=None):
    output_dir = output_dir or EXPORT_PATH
    db = client["grp05db"]
    db_areas = db["areas"]
    # "areas" mezcla las 99 cuencas nombradas con 33563 parcelas de suelo
    # sin nombre (nombre == "SIN_NOMBRE"); solo exportamos las cuencas.
    all_cuencas = db_areas.find({"nombre": {"$ne": "SIN_NOMBRE"}}).to_list()

    cuencas = []
    geometries = []
    for c in all_cuencas:
        cuencas.append({
            "nombre": c.get("nombre"),
        })
        geometries.append(shape(c.get("geometry")))

    df = geo.GeoDataFrame(
        cuencas,
        geometry=geometries,
        crs="EPSG:4326"
    )
    df.to_file(os.path.join(output_dir, "cuencas.geojson"), driver="GeoJSON")

def export_sentinel_locations(client: MongoClient, output_dir=None):
    output_dir = output_dir or EXPORT_PATH
    db = client["grp05db"]
    db_sentinel = db["sentinel_locations"]
    all_locations = db_sentinel.find().to_list()

    locations = []
    geometries = []
    for l in all_locations:
        locations.append({
            "nombre": l.get("nombre"),
        })
        geometries.append(shape(l.get("geometry")))

    df = geo.GeoDataFrame(
        locations,
        geometry=geometries,
        crs="EPSG:4326"
    )
    df.to_file(os.path.join(output_dir, "sentinel_locations.geojson"), driver="GeoJSON")

MONGO_EXPORTERS = {
    "estaciones": export_estaciones,
    "puntos_grilla": export_puntos_grilla,
    "departamentos": export_departamentos,
    "cuencas": export_cuencas,
    "sentinel_locations": export_sentinel_locations,
}

def handle_mongo_arg(collection_name: str):
    client = MongoClient(URL)
    print(f"EXPORTING MONGO COLLECTION {collection_name}")
    MONGO_EXPORTERS[collection_name](client)

def export_gemsparams(client, output_dir=None):
    output_dir = output_dir or EXPORT_PATH
    with client.cursor() as cur:
        cur.execute("SELECT * FROM gemsparams;")
        rows = cur.fetchall()
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(output_dir, "gemsparams.csv"), index=False)

def export_paraminumet(client, output_dir=None):
    output_dir = output_dir or EXPORT_PATH
    with client.cursor() as cur:
        cur.execute("SELECT * FROM paraminumet;")
        rows = cur.fetchall()
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(output_dir, "paraminumet.csv"), index=False)

def export_registrotempprec(client, output_dir=None):
    output_dir = output_dir or EXPORT_PATH
    with client.cursor() as cur:
        cur.execute("SELECT * FROM registrotempprec;")
        rows = cur.fetchall()
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(output_dir, "registrotempprec.csv"), index=False)

def export_puntomedicion(client, output_dir=None):
    output_dir = output_dir or EXPORT_PATH
    with client.cursor() as cur:
        cur.execute("SELECT * FROM puntomedicion;")
        rows = cur.fetchall()
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(output_dir, "puntomedicion.csv"), index=False)

def export_sentinel_params(client, output_dir=None):
    output_dir = output_dir or EXPORT_PATH
    with client.cursor() as cur:
        cur.execute("SELECT * FROM sentinel_params;")
        rows = cur.fetchall()
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(output_dir, "sentinel_params.csv"), index=False)

def export_oseparam(client, output_dir=None):
    output_dir = output_dir or EXPORT_PATH
    with client.cursor() as cur:
        cur.execute("SELECT * FROM oseparam;")
        rows = cur.fetchall()
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(output_dir, "oseparam.csv"), index=False)

def export_reclamosose(client, output_dir=None):
    output_dir = output_dir or EXPORT_PATH
    with client.cursor() as cur:
        cur.execute("SELECT * FROM reclamosose;")
        rows = cur.fetchall()
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(output_dir, "reclamosose.csv"), index=False)

def export_erosion_cuenca(client, output_dir=None):
    output_dir = output_dir or EXPORT_PATH
    with client.cursor() as cur:
        cur.execute("SELECT * FROM erosion_cuenca;")
        rows = cur.fetchall()
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(output_dir, "erosion_cuenca.csv"), index=False)

def export_erosion_suelos(client, output_dir=None):
    output_dir = output_dir or EXPORT_PATH
    with client.cursor() as cur:
        cur.execute("SELECT * FROM erosion_suelos;")
        rows = cur.fetchall()
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(output_dir, "erosion_suelos.csv"), index=False)

POSTGRES_EXPORTERS = {
    "gemsparams": export_gemsparams,
    "paraminumet": export_paraminumet,
    "registrotempprec": export_registrotempprec,
    "puntomedicion": export_puntomedicion,
    "sentinel_params": export_sentinel_params,
    "oseparam": export_oseparam,
    "reclamosose": export_reclamosose,
    "erosion_cuenca": export_erosion_cuenca,
    "erosion_suelos": export_erosion_suelos,
}

def handle_postgres_arg(collection_name: str):
    client = psycopg.connect(
        os.environ.get("POSTGRES_URL"),
        row_factory=dict_row
    )
    print(f"EXPORTING POSTGRES TABLE {collection_name}")
    POSTGRES_EXPORTERS[collection_name](client)

def export_all():
    output_dir = os.path.join(EXPORT_PATH, f"waterwatch_{date.today().isoformat()}")
    os.makedirs(output_dir, exist_ok=True)

    mongo_client = MongoClient(URL)
    for name, fn in MONGO_EXPORTERS.items():
        print(f"EXPORTING MONGO COLLECTION {name}")
        fn(mongo_client, output_dir=output_dir)

    postgres_client = psycopg.connect(
        os.environ.get("POSTGRES_URL"),
        row_factory=dict_row
    )
    for name, fn in POSTGRES_EXPORTERS.items():
        print(f"EXPORTING POSTGRES TABLE {name}")
        fn(postgres_client, output_dir=output_dir)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog="water-export",
        description="Herramienta para exportar datos de Water-Watch",
    )

    parser.add_argument("--db", choices=["mongo", "postgres"])
    parser.add_argument("--collection")
    parser.add_argument("--all", action="store_true")

    args = parser.parse_args()

    if args.all:
        export_all()
    elif args.db and args.collection:
        if args.db == "mongo":
            handle_mongo_arg(args.collection)
        elif args.db == "postgres":
            handle_postgres_arg(args.collection)
    else:
        parser.error("--db and --collection are required unless --all is given")
