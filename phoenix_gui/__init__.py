"""Phoenix Wallet graphical interface package.

The package is a self-contained PyQt6 application. It talks to the Phoenix
HTTP proxy (the component between the C++ daemon and the GUI) and never
imports the proxy's cryptography stack, so it can run in its own virtual
environment.
"""

__version__ = "1.0.0"
__app_name__ = "Phoenix Wallet"
__organization__ = "Phoenix"
