"""Double-click launcher: starts the desktop buddy.

    python run.py            desktop buddy
    python run.py --cli      terminal instead
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if __name__ == "__main__":
    if "--cli" in sys.argv:
        from vb.cli import main
        sys.argv.remove("--cli")
        raise SystemExit(main())
    from vb.app import main
    raise SystemExit(main())
