from pymongo import MongoClient
import argparse
from typing import Literal
import geopandas as geo
from shapely.geometry import shape
from dotenv import load_dotenv
import os
load_dotenv(override=True)

COLLECTIONS = [
    "estaciones",
    "puntos_grilla",
    "departamentos",
    "cuencas"
]

URL = os.environ.get("MONGO_URI")
EXPORT_PATH = os.environ.get("EXPORT_PATH", ".")
os.makedirs(EXPORT_PATH, exist_ok=True)

def export_estaciones(client: MongoClient):
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
    df.to_file(os.path.join(EXPORT_PATH, "estaciones.geojson"), driver="GeoJSON")

def export_puntos_grilla(client: MongoClient):
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
    df.to_file(os.path.join(EXPORT_PATH, "puntos_grilla.geojson"), driver="GeoJSON")

def export_departamentos(client: MongoClient):
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
    df.to_file(os.path.join(EXPORT_PATH, "departamentos.geojson"), driver="GeoJSON")

def export_cuencas(client: MongoClient):
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
    df.to_file(os.path.join(EXPORT_PATH, "cuencas.geojson"), driver="GeoJSON")

def handle_mongo_arg(collection_name: Literal["estaciones"]):
    client = MongoClient(URL)
    if collection_name == "estaciones":
        print(f"EXPORTING MONGO COLLECTION {collection_name}")
        export_estaciones(client)
    elif collection_name == "puntos_grilla":
        export_puntos_grilla(client)
    elif collection_name == "departamentos":
        export_departamentos(client)
    elif collection_name == "cuencas":
        export_cuencas(client)

def handle_postgres_arg():
    pass

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog="water-export",
        description="Herramienta para exportar datos de Water-Watch",
    )

    client = MongoClient(URL)
    print(client["grp05db"].list_collection_names())

    parser.add_argument("--db", required=True, choices=["mongo", "postgres"])
    parser.add_argument("--collection", required=True)

    args = parser.parse_args()

    if args.db == "mongo":
        handle_mongo_arg(args.collection)
    elif args.db == "postgres":
        handle_postgres_arg()
