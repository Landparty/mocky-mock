"""`python -m mockymock`: the same CLI as the `mockymock` script."""

import sys

from mockymock.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
