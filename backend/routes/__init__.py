"""
GPI Document Hub - Routes Package

Modular API routers for the Document Hub. Each router is imported directly
by server.py from its own module (e.g. `from routes.documents import
router`), not via this package's namespace - so this __init__.py
deliberately does NOT eagerly import from submodules.

HISTORY / WARNING: this file previously eagerly imported every submodule
here (`from .documents import router, set_db`, etc.), expecting a
`set_db`/`set_dependencies` dependency-injection pattern from the original
orphaned-stub versions of documents.py/dashboard.py/config.py/workflows.py.
Since a package's __init__.py runs on ANY submodule import, that made this
file a hidden, unverified dependency of the whole app: overwriting or
deleting any one of those submodules (as happened during the routes/
migration, see MIGRATION_PROGRESS.md) broke this file's imports and crashed
the entire app at startup (ImportError in __init__.py propagates from
`from routes.auth import router` in server.py, since Python must run
routes/__init__.py first). This is exactly the kind of thing a
grep-based cross-reference check misses, since it doesn't reference any
name inside server.py itself. Fixed by removing the eager imports - keep it
this way unless something is added that genuinely needs a package-level
re-export, and if so, verify it against each submodule's CURRENT API first.
"""

# Import for side effects. This module (from feature/sales-order-intake-
# preflight) registers reviewer endpoints directly onto the existing
# sales_module.sales_router, which server.py already mounts - it doesn't
# depend on documents/workflows/config/dashboard, so it's unaffected by
# the eager-import removal above.
from . import sales_order_review as _sales_order_review  # noqa: F401
