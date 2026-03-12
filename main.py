#!/usr/bin/env python3
"""
main.py - Entry point for Panopticon.

Run with:
    python main.py
or after installing the package:
    panopticon
"""

import sys

from panopticon.app import run

if __name__ == "__main__":
    sys.exit(run(sys.argv))
