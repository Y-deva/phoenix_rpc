"""Allow ``python -m phoenix_gui`` to start the wallet."""

from .app import main

raise SystemExit(main())
