"""Launch NUM_SHARDS parallel extract_bands.py workers, one OS process per shard.

Each shard is a fully separate process (python -m tools.extract_bands --shard-id i),
so there's no shared state / thread-safety to worry about between workers. Logs go
to logs/shard-<i>.log since mixing several tqdm bars on one stdout is unreadable.

A shard that dies before finishing its assigned range (e.g. OOM-killed overnight,
no error of its own) gets restarted automatically -- safe since progress is already
resumable via the .nc files already on disk. "Finished" is detected via a _DONE
marker file that extract_bands.py writes after its loop completes.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.extract_bands import NUM_SHARDS, DEFAULT_BANDS, WINDOW_DEG, DATA

LOG_DIR = Path("logs")
MAX_RETRIES = 5
RETRY_DELAY_SECONDS = 5
POLL_SECONDS = 2


def shard_out_dir(bands: str, shard_id: int) -> Path:
    return DATA / "bands" / "-".join(bands.split(",")) / f"shard-{shard_id}"


def shard_done(bands: str, shard_id: int) -> bool:
    return (shard_out_dir(bands, shard_id) / "_DONE").exists()


def launch_shard(shard_id: int, bands: str, limit: int | None, window_deg: float):
    cmd = [
        sys.executable, "-m", "tools.extract_bands",
        "--shard-id", str(shard_id),
        "--bands", bands,
        "--window-deg", str(window_deg),
    ]
    if limit:
        cmd += ["--limit", str(limit)]

    log_path = LOG_DIR / f"shard-{shard_id}.log"
    log_file = open(log_path, "a")
    proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)
    return proc, log_file


def main(bands: str, limit: int | None, window_deg: float) -> None:
    LOG_DIR.mkdir(exist_ok=True)

    procs = {}
    log_files = {}
    retries = {}

    for shard_id in range(1, NUM_SHARDS + 1):
        proc, log_file = launch_shard(shard_id, bands, limit, window_deg)
        print(f"launching shard {shard_id} -> logs/shard-{shard_id}.log")
        procs[shard_id] = proc
        log_files[shard_id] = log_file
        retries[shard_id] = 0

    gave_up = []
    done = set()

    while len(done) < NUM_SHARDS:
        time.sleep(POLL_SECONDS)

        for shard_id in range(1, NUM_SHARDS + 1):
            if shard_id in done:
                continue

            code = procs[shard_id].poll()
            if code is None:
                continue  # still running

            log_files[shard_id].close()

            if shard_done(bands, shard_id):
                print(f"shard {shard_id}: finished (exit {code})")
                done.add(shard_id)
                continue

            if retries[shard_id] >= MAX_RETRIES:
                print(f"shard {shard_id}: gave up after {MAX_RETRIES} restarts (last exit {code})")
                gave_up.append(shard_id)
                done.add(shard_id)
                continue

            retries[shard_id] += 1
            reason = f"killed by signal {-code}" if code < 0 else f"exit {code}"
            print(f"shard {shard_id}: died before finishing ({reason}), restarting "
                  f"(attempt {retries[shard_id]}/{MAX_RETRIES})")
            time.sleep(RETRY_DELAY_SECONDS)
            proc, log_file = launch_shard(shard_id, bands, limit, window_deg)
            procs[shard_id] = proc
            log_files[shard_id] = log_file

    if gave_up:
        print(f"shards that never finished: {gave_up}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bands", type=str, default=",".join(DEFAULT_BANDS))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--window-deg", type=float, default=WINDOW_DEG)
    args = parser.parse_args()

    main(bands=args.bands, limit=args.limit, window_deg=args.window_deg)
