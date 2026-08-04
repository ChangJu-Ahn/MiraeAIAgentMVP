import sys
from pathlib import Path

# The Azure Functions app uses flat imports (e.g. `import chunking`). Expose its
# pure modules to the repo test suite by putting the app root on sys.path.
_FUNC_DIR = Path(__file__).resolve().parent.parent / "functions" / "blob_to_search"
if str(_FUNC_DIR) not in sys.path:
    sys.path.insert(0, str(_FUNC_DIR))
