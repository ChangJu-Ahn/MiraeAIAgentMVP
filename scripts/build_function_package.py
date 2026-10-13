"""Build the dependency-complete ZIP inside the Azure Linux build worker."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def build(root: Path) -> None:
    if not (root / ".python_packages/lib/site-packages/pypdf/__init__.py").is_file():
        raise RuntimeError("Linux Function dependencies are incomplete")
    with ZipFile(root / "function.zip", "w", compression=ZIP_DEFLATED) as archive:
        for name in ("function_app.py", "host.json", "requirements.txt", ".deployment"):
            archive.write(root / name, name)
        for name in ("ingest", "config", ".python_packages"):
            for file in sorted((root / name).rglob("*")):
                if file.is_file() and "__pycache__" not in file.parts and file.suffix != ".pyc":
                    archive.write(file, str(file.relative_to(root)))


if __name__ == "__main__":
    build(Path.cwd())
