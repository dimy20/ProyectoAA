"""

Tool para entrenar RandomForestClassifier para cada grupo.

Requisitos:

1. Splits pre generados, disponible en /data.

2. Pasar archivo con resultados de grid search, por lo cual es necesario:
    Ejecutar el grid search para obtener el archivo con resultados o usar un resultado anterior, el mejor resultado hasta el momento esta disponible
    en data/hyperparams.

Opcionalmente se puede pasar --grupo <GRUPO-NOMBRE> para entenar un rf solo para un grupo especifico, por defecto entrena todos.

Cada invocacion crea una corrida nueva en data/datasets/models/rfs/run-<timestamp>/, con un
.joblib por grupo entrenado y un manifest.json con el grid-search-file y los hiperparametros
usados, para poder rastrear de donde salio cada modelo despues.

Uso:
    python -m tools.train_rfs --grid-search-file <FILE>
    python -m tools.train_rfs --grid-search-file <FILE> --grupo LDS
"""

import argparse
from pathlib import Path

from models.core import load_rfs_grid_search_results, print_env_info
from models.rfs import SPLITS_DIR, eval_rf, new_run_dir, train_group, write_run_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Entrena un RandomForest por grupo.")
    parser.add_argument(
        "--grid-search-file",
        required=True,
        help="JSON con los mejores hiperparametros por grupo (formato de tools/sweep_rf_por_grupo.py).",
    )
    parser.add_argument(
        "--grupo",
        default=None,
        help="Grupo especifico a entrenar. Por defecto entrena todos los grupos del grid search file.",
    )
    parser.add_argument(
        "--splits-dir",
        default=SPLITS_DIR,
        type=Path,
        help=f"Carpeta con los splits train/val por grupo. Por defecto {SPLITS_DIR}.",
    )
    return parser.parse_args()


def main() -> None:
    print_env_info()
    args = parse_args()
    best_params = load_rfs_grid_search_results(args.grid_search_file)

    if args.grupo:
        if args.grupo not in best_params:
            raise ValueError(
                f"No hay hiperparametros para el grupo '{args.grupo}' en {args.grid_search_file} "
                f"(grupos disponibles: {sorted(best_params.keys())})"
            )
        grupos = [args.grupo]
    else:
        grupos = list(best_params.keys())

    run_dir = new_run_dir()
    print(f"Corrida: {run_dir}")

    params_usados = {}
    for grupo in grupos:
        params = best_params[grupo]
        print(f"Entrenando {grupo} con params={params}")
        train_group(grupo, params, run_dir, splits_dir=args.splits_dir)
        eval_rf(grupo, run_dir, splits_dir=args.splits_dir, plot=False)
        params_usados[grupo] = params

    manifest_path = write_run_manifest(run_dir, args.grid_search_file, params_usados)
    print(f"Manifest guardado en {manifest_path}")


if __name__ == "__main__":
    main()
