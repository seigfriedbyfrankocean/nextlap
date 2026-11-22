from pathlib import Path
import runpy
import sys

SOURCE_DIR = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(SOURCE_DIR))

if __name__ == "__main__":
    runpy.run_module("build_dataset_openf1_v3", run_name="__main__")
