"""Fixture comuni. Aggiunge la radice del repo al path (i moduli sono top-level)."""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# WeasyPrint richiede librerie di sistema (Pango) assenti su Windows: se non si
# importa, si usa un finto modulo così api_server resta importabile nei test.
try:
    import weasyprint  # noqa: F401
except (ImportError, OSError):
    stub = types.ModuleType("weasyprint")
    stub.HTML = object
    sys.modules["weasyprint"] = stub
