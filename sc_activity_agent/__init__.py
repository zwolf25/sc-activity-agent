__version__ = "0.8.0"

import os

PACKAGED = os.environ.get("SC_AGENT_PACKAGED") == "1"  # set by the desktop app shell that bundles this program
