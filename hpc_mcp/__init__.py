"""Importing this package registers every onboarded facility.

Every directory under facilities/ containing a facility.py is imported
(triggering its config.register_facility() + registry.register_backend()
calls) — a new facility PR that adds facilities/<slug>/facility.py needs no
edit here to be picked up; that's deliberate, so parallel facility PRs don't
conflict on this file. Every hpc_mcp entry point (hpc_server, docs_server,
doctor, ingest) imports hpc_mcp first (even just for this side effect)
before doing anything that needs a registered facility.
"""
import importlib
import pkgutil

import facilities

for _mod in pkgutil.iter_modules(facilities.__path__):
    if not _mod.ispkg:
        continue  # skip registry.py itself — only facility subpackages
    try:
        importlib.import_module(f"facilities.{_mod.name}.facility")
    except ModuleNotFoundError:
        continue  # a facilities/ subdirectory with no facility.py (e.g. __pycache__)
