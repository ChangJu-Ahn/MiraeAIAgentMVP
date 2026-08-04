import sys
from pathlib import Path

# The Azure Functions app (../function) uses flat module imports
# (e.g. `import chunking`, `import func_config`). Append its directory so the
# demo test suite can import those pure modules. It is appended (not inserted at
# position 0) so any top-level packages keep precedence and are never shadowed
# by a flat module of the same name.
_FUNC_DIR = str(Path(__file__).resolve().parent.parent / "function")
if _FUNC_DIR not in sys.path:
    sys.path.append(_FUNC_DIR)
