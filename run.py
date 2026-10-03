"""Source checkout launcher, independent of editable-install .pth handling."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

if __name__ == "__main__":
    from bi_analyst.cli import main

    raise SystemExit(main())
