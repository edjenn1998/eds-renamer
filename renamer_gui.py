#!/usr/bin/env python3
import sys

if sys.argv[1:2] == ["--cli"]:
    from renamer.cli import main
    raise SystemExit(main(sys.argv[2:]))

from renamer.gui import main
raise SystemExit(main())
