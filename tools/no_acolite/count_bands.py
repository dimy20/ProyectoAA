from pathlib import Path
from glob import glob

if __name__ == '__main__':
    g = Path()
    total = 0
    for i in range(4):
        path = f"./data/bands/B07-B06-B05-B04-B03-B02-B01-B08-B8A-B09-B10-B11-B12/shard-{i+1}/*.nc"
        res = glob(path)
        print(f"shard-{i} : {len(res)}")
        total += len(res)
    print(f"Total : {total}")