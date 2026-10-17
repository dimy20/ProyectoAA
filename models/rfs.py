import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, classification_report
import matplotlib.pyplot as plt
import seaborn as sns
import joblib

from models.core import (
    remap_class_names,
    RFParams,
    RANDOM_STATE,
    ESTADOS_ENCODING,
    NON_FEATURE_COLUMNS,
    IS_LOCAL,
    SLURM_CPUS_PER_TASK,
    SLURM_JOB_ID,
)

SPLITS_DIR = Path("data/datasets/splits")
MODELS_DIR = Path("data/models/rfs") if IS_LOCAL else Path("/outputs/models/rfs")
HYPERPARAMS_DIR = Path("data/hyperparams") if IS_LOCAL else Path("/outputs/hyperparams")

INV_ENCODING = {v: k for k, v in ESTADOS_ENCODING.items()}


def random_forest_from_config(config: RFParams) -> RandomForestClassifier:
    n_jobs = -1 if IS_LOCAL else SLURM_CPUS_PER_TASK
    return RandomForestClassifier(random_state=RANDOM_STATE, n_jobs=n_jobs, **config)


def random_forest_from_file(fname: Path) -> RandomForestClassifier:
    rf = joblib.load(fname)
    if not isinstance(rf, RandomForestClassifier):
        raise TypeError(
            f"Expected RandomForestClassifier, got {type(rf).__name__}"
        )
    return rf


def load_split(grupo: str, split: str, splits_dir: Path = SPLITS_DIR) -> tuple[pd.DataFrame, pd.Series]:
    df = pd.read_csv(splits_dir / grupo / f"{split}.csv", index_col=0)
    df = remap_class_names(df)
    X = df.drop(columns=NON_FEATURE_COLUMNS)
    y = df["estado_trofico"]
    return X, y

def list_grupos(splits_dir: Path = SPLITS_DIR) -> list[str]:
    return sorted(p.name for p in splits_dir.iterdir() if p.is_dir())

def model_path(grupo: str, run_dir: Path) -> Path:
    return run_dir / f"rf-{grupo}.joblib"

def new_run_dir(models_dir: Path = MODELS_DIR) -> Path:
    models_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    run_dir = models_dir / f"run-{stamp}"
    suffix = 1
    while run_dir.exists():
        suffix += 1
        run_dir = models_dir / f"run-{stamp}-{suffix}"
    run_dir.mkdir(parents=True)
    return run_dir

def latest_run_dir(models_dir: Path = MODELS_DIR) -> Path:
    runs = sorted(p for p in models_dir.iterdir() if p.is_dir() and p.name.startswith("run-"))
    if not runs:
        raise FileNotFoundError(f"No hay corridas de entrenamiento en {models_dir}")
    return runs[-1]

def write_run_manifest(run_dir: Path, grid_search_file: str, params_by_grupo: dict[str, RFParams]) -> Path:
    """Guarda, junto a los .joblib de la corrida, de donde salieron: que grid-search-file y que
    hiperparametros se uso para cada grupo. Asi cualquier modelo en disco tiene procedencia."""
    manifest = {
        "grid_search_file": str(grid_search_file),
        "random_state": RANDOM_STATE,
        "slurm_job_id": None if IS_LOCAL else SLURM_JOB_ID,
        "grupos": params_by_grupo,
    }
    manifest_path = run_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return manifest_path

def train_group(grupo: str, params: RFParams, run_dir: Path, splits_dir: Path = SPLITS_DIR) -> RandomForestClassifier:
    X_train, y_train = load_split(grupo, "train", splits_dir)

    rf = random_forest_from_config(params)
    rf.fit(X_train, y_train)

    joblib.dump(rf, model_path(grupo, run_dir))
    return rf

def eval_rf(grupo: str, run_dir: Path, splits_dir: Path = SPLITS_DIR, plot: bool = True) -> dict:
    rf = random_forest_from_file(model_path(grupo, run_dir))

    X_train, y_train = load_split(grupo, "train", splits_dir)
    X_val, y_val = load_split(grupo, "val", splits_dir)

    y_train_pred = rf.predict(X_train)
    y_val_pred = rf.predict(X_val)

    labels = sorted(y_val.unique())
    target_names = [INV_ENCODING[c] for c in labels]

    print(f"=== {grupo} (train={len(X_train)}, val={len(X_val)}) ===")
    print(classification_report(y_val, y_val_pred, labels=labels, target_names=target_names, zero_division=0))

    if plot:
        cm = confusion_matrix(y_val, y_val_pred, labels=labels)
        plt.figure(figsize=(5, 4))
        sns.heatmap(cm, annot=True, fmt="d", cmap="Blues", xticklabels=target_names, yticklabels=target_names)
        plt.title(f"{grupo} - Validacion")
        plt.xlabel("Prediccion")
        plt.ylabel("Real")
        plt.show()

    return {
        "grupo": grupo,
        "n_train": len(X_train),
        "n_val": len(X_val),
        "acc_train": accuracy_score(y_train, y_train_pred),
        "acc_val": accuracy_score(y_val, y_val_pred),
    }
