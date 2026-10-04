#!/usr/bin/env python3
"""CLI entry point. Usage examples:

  ./rename.py rename *.jpg --name 'clip_##' --number --start 3 --apply
  ./rename.py rename photos/ --recursive --replace vacation trip --case lower
  ./rename.py rename a.txt --cut front 4 --apply
  ./rename.py rename b.txt --regex '^IMG_' 'photo-' --apply
  ./rename.py sessions
  ./rename.py undo -y
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from renamer.cli import main

if __name__ == "__main__":
    sys.exit(main())
