"""Standalone entry point for the Nuitka-compiled mockymock executable.

Lives outside the mockymock package deliberately, mirroring the sibling
cobol-parser repo's packaging/nuitka_entry.py: Nuitka compiles whichever
file it's pointed at as the onefile's __main__, which runs with no package
context, so a compiled entry point inside the package itself would break on
any relative import anywhere in its call graph. See
scripts/build_executable.sh and PUBLISHING.md.
"""

from mockymock.cli.main import main

if __name__ == "__main__":
    raise SystemExit(main())
