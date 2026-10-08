from pathlib import Path
import tomllib


def test_function_dependencies_use_the_verified_lock_versions():
    root = Path(__file__).resolve().parents[2]
    locked = {p["name"]: p["version"] for p in tomllib.loads((root / "uv.lock").read_text())["package"]}
    requirements = (root / "functions/ingestion/requirements.txt").read_text().splitlines()
    for line in requirements:
        name = line.split("==")[0]
        assert name in locked, f"Function dependency must use an exact locked version: {line}"
        assert line == f"{name}=={locked[name]}"
