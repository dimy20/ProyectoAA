"""
Barrido de hiperparametros de RandomForestClassifier por grupo (grupo_nombre), usado para
encontrar los mejores hiperparametros por grupo para tools/train_rfs.py.

El grid a barrer no esta hardcodeado: se lee de un JSON de experiments/rfs/ (--experiment),
con el mismo formato que PARAM_GRID (una lista de valores por hiperparametro). Asi se pueden
definir/versionar distintos experimentos como archivos nuevos en experiments/rfs/ sin tocar
este script. experiments/rfs/default.json trae el grid por defecto que se usaba antes.

Para cada grupo prueba todas las combinaciones del grid sobre los splits train/val generados
por notebooks/modelos/split_grupos.ipynb (data/datasets/splits/{grupo}/{train,val}.csv, via
models.rfs.load_split), asi el barrido busca sobre exactamente los mismos datos con los que
despues se entrena/evalua. Se queda con la combinacion que maximiza accuracy en el split de
validacion de ese grupo.

Ademas de imprimir el resultado, cada corrida crea un directorio nuevo en
data/hyperparams/run-<timestamp>/ (nunca pisa una corrida anterior) con un
grid_search-rfs-grupos.json adentro (con una key "experiment" que apunta al JSON de
experiments/rfs/ usado, y una key "grupos" con los resultados), listo para pasarle a
tools/train_rfs.py --grid-search-file.

Se corre como modulo (no como script suelto) para que el import de `models` resuelva, desde la
raiz del repo:

    python -m tools.sweep_rf_por_grupo
    python -m tools.sweep_rf_por_grupo --experiment experiments/rfs/otro_experimento.json
"""

import argparse
import itertools
import json
from pathlib import Path

from sklearn.metrics import accuracy_score

from models.core import RFParams, print_env_info
from models.rfs import HYPERPARAMS_DIR, SPLITS_DIR, list_grupos, load_split, new_run_dir, random_forest_from_config

RESULTS_FILENAME = "grid_search-rfs-grupos.json"

EXPERIMENTS_DIR = Path("experiments/rfs")
DEFAULT_EXPERIMENT = EXPERIMENTS_DIR / "default.json"


def load_param_grid(experiment_path: Path) -> dict[str, list]:
    with open(experiment_path) as f:
        return json.load(f)


def sweep_grupo(grupo: str, param_grid: dict[str, list], splits_dir: Path = SPLITS_DIR) -> tuple[float, RFParams]:
    X_train, y_train = load_split(grupo, "train", splits_dir)
    X_val, y_val = load_split(grupo, "val", splits_dir)

    keys = list(param_grid.keys())
    best_acc, best_params = -1.0, None
    for combo in itertools.product(*param_grid.values()):
        params = dict(zip(keys, combo))
        rf = random_forest_from_config(params)
        rf.fit(X_train, y_train)
        acc = accuracy_score(y_val, rf.predict(X_val))
        if acc > best_acc:
            best_acc, best_params = acc, params
    return best_acc, best_params


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Barrido de hiperparametros de RandomForest por grupo.")
    parser.add_argument(
        "--splits-dir",
        default=SPLITS_DIR,
        type=Path,
        help=f"Carpeta con los splits train/val por grupo. Por defecto {SPLITS_DIR}.",
    )
    parser.add_argument(
        "--experiment",
        default=DEFAULT_EXPERIMENT,
        type=Path,
        help=f"JSON de experiments/rfs/ con el grid a barrear. Por defecto {DEFAULT_EXPERIMENT}.",
    )
    return parser.parse_args()


def main() -> None:
    print_env_info()
    args = parse_args()
    grupos = list_grupos(args.splits_dir)
    param_grid = load_param_grid(args.experiment)

    resultados = {}
    for grupo in grupos:
        best_acc, best_params = sweep_grupo(grupo, param_grid, args.splits_dir)
        print(f"{grupo}: best_acc={best_acc:.4f}  params={best_params}")
        resultados[grupo] = {"best_acc": best_acc, "params": best_params}

    run_dir = new_run_dir(HYPERPARAMS_DIR)
    output_path = run_dir / RESULTS_FILENAME
    with open(output_path, "w") as f:
        json.dump({"experiment": str(args.experiment), "grupos": resultados}, f, indent=2, ensure_ascii=False)
    print(f"\nResultados guardados en {output_path}")


if __name__ == "__main__":
    main()
