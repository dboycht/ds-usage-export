#!/usr/bin/env python3
"""ds-usage-export 命令行入口（也可直接运行：python dsu.py …）。"""

import sys

from dsusage.cli import main

if __name__ == "__main__":
    sys.exit(main())
