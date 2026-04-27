import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
SHARED_ROOT = WORKSPACE_ROOT / "shared"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SHARED_ROOT) not in sys.path:
    sys.path.append(str(SHARED_ROOT))
