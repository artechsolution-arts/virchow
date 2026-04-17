import os

__version__ = os.environ.get("VIRCHOW_VERSION", "") or "Development"
