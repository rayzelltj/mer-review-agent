import os
import sys


# Ensure `src/backend` is on sys.path so imports like `import common...` work,
# even when pytest's rootdir is the repository root (repo-level pytest.ini).
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

