"""Entry point: `python3 -m bakeoff <command>` from the lang/ directory."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
