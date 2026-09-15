"""Launch NUM_SHARDS parallel extract_bands.py workers, one OS process per shard.

Each shard is a fully separate process (python -m tools.extract_bands --shard-id i),
so there's no shared state / thread-safety to worry about between workers. Logs go
to logs/shard-<i>.log since mixing several tqdm bars on one stdout is unreadable.
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.extract_bands import NUM_SHARDS, DEFAULT_BANDS, WINDOW_DEG

LOG_DIR = Path("logs")


def main(bands: str, limit: int | None, window_deg: float) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    procs = []

    for shard_id in range(1, NUM_SHARDS + 1):
        cmd = [
            sys.executable, "-m", "tools.extract_bands",
            "--shard-id", str(shard_id),
            "--bands", bands,
            "--window-deg", str(window_deg),
        ]
        if limit:
            cmd += ["--limit", str(limit)]

        log_path = LOG_DIR / f"shard-{shard_id}.log"
        log_file = open(log_path, "w")
        print(f"launching shard {shard_id} -> {log_path}")
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)
        procs.append((shard_id, proc, log_file))

    failed = []
    for shard_id, proc, log_file in procs:
        code = proc.wait()
        log_file.close()
        status = "ok" if code == 0 else f"FAILED (exit {code})"
        print(f"shard {shard_id}: {status}")
        if code != 0:
            failed.append(shard_id)

    if failed:
        print(f"shards failed: {failed}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bands", type=str, default=",".join(DEFAULT_BANDS))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--window-deg", type=float, default=WINDOW_DEG)
    args = parser.parse_args()

    main(bands=args.bands, limit=args.limit, window_deg=args.window_deg)
