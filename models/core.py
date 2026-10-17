import os
import pandas as pd
import json
from typing import TypedDict, Dict

class RFParams(TypedDict):
    n_estimators: int
    max_depth: int
    min_samples_leaf: int
    max_features: str
    class_weight: str

RANDOM_STATE = 42
TEST_SIZE = 0.15

ESTADOS_ENCODING = {
    "U": 0,
    "O": 1,
    "M": 2,
    "E": 3
}

GRUPO_SPLIT_DROP_COLUMNS = ["grupo_nombre", "geometry"]
NON_FEATURE_COLUMNS = ["fecha", "chla", "estado_trofico"]

ENV = os.getenv("ENV", "local")
IS_LOCAL = ENV.lower() == "local"

SLURM_JOB_ID = os.getenv("SLURM_JOB_ID", "no_slurm")
SLURM_JOB_NAME = os.getenv("SLURM_JOB_NAME", "no_slurm")
SLURM_CPUS_PER_TASK = int(os.getenv("SLURM_CPUS_PER_TASK", "1"))


def print_env_info() -> None:
    print(f"ENV: {ENV}")
    if not IS_LOCAL:
        print(f"SLURM_JOB_ID: {SLURM_JOB_ID}")
        print(f"SLURM_JOB_NAME: {SLURM_JOB_NAME}")
        print(f"SLURM_CPUS_PER_TASK: {SLURM_CPUS_PER_TASK}")

def remap_class_names(df: pd.DataFrame):
    df["estado_trofico"] = df["estado_trofico"].map(ESTADOS_ENCODING)
    return df

def load_rfs_grid_search_results(fname: str)-> Dict[str, RFParams]:
    with open(fname) as f:
        sweep_resultados = json.load(f)

    # formato nuevo: {"experiment": ..., "grupos": {...}}. formato viejo (sin wrapper de
    # experiment): {grupo: {...}, ...} directo -- se mantiene por compatibilidad.
    grupos = sweep_resultados.get("grupos", sweep_resultados)
    return {grupo: info["params"] for grupo, info in grupos.items()}