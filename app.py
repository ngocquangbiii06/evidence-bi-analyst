"""Local UI launcher. Data never enters a global Streamlit cache."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from bi_analyst.ui import main  # noqa: E402

if __name__ == "__main__":
    main()
