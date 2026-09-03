"""Every module we import must be one we can count on being there.

Home Assistant installs what `manifest.json` asks for and nothing else. Anything
else our code imports has to come from somewhere we can name — the standard
library, Home Assistant itself, or a package one of our own requirements pulls
in. A module that is merely *usually* present is a bug waiting for the release
that stops shipping it.

That release happened. `voluptuous_serialize` was a Home Assistant core
dependency for years, so `websocket_api.py` imported it and the suite stayed
green — this project's own test environment installs Home Assistant, which
installed it too. Home Assistant 2026.9 dropped it, and the integration stopped
loading on a real installation with `ModuleNotFoundError` before it could
register anything: no agents, no panel, and a `/smartchain` that answered 404.
Nothing in 1603 tests could see it, because the test environment still had the
module.

So the rule here is about *provenance*, not presence: importing a module is not
enough to prove we may. Either `manifest.json` asks for it, or this file names
who supplies it and why that is safe.
"""

import ast
import json
import pathlib
import sys

COMPONENT = pathlib.Path(__file__).parent.parent / "custom_components" / "smartchain"

# Modules we do not declare, each with the reason we are allowed not to. A new
# entry here is a decision to depend on someone else's dependency list, so it
# needs a sentence saying whose.
SUPPLIED_BY_OTHERS = {
    # Home Assistant's own hard requirements: it cannot start without them, so
    # any version of it that runs us has them.
    "aiohttp": "homeassistant core requirement",
    "voluptuous": "homeassistant core requirement",
    "yaml": "homeassistant core requirement (PyYAML)",
    "httpx": "homeassistant core requirement",
    # Pulled in by the langchain packages manifest.json already asks for. It is
    # the reason those packages exist; a langchain that stopped depending on its
    # own core would be a different library.
    "langchain_core": "dependency of the declared langchain-* packages",
    # The default memory backend's maths. Not a Home Assistant requirement, but
    # its module is only imported when a memory store is actually built, so a
    # missing numpy degrades memory rather than stopping setup.
    "numpy": "lazily reached; only a configured memory store imports it",
}


def _third_party_module_level_imports() -> dict[str, set[str]]:
    """Top-level imports only: those are the ones that run at import time.

    An import inside a function fails when that path is taken, which is a
    different and much smaller failure than an integration that will not load.
    `sqlite_vec`, `asyncpg`, `turbojpeg` and the Yandex SDK are deliberately
    written that way and are out of scope here.
    """
    stdlib = set(sys.stdlib_module_names)
    found: dict[str, set[str]] = {}
    for path in sorted(COMPONENT.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in tree.body:  # module level only — not walk()
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for name in names:
                top = name.split(".")[0]
                if top in stdlib or top in ("homeassistant", "custom_components"):
                    continue
                found.setdefault(top, set()).add(f"{path.relative_to(COMPONENT)}:{node.lineno}")
    return found


def _declared() -> set[str]:
    """Requirement strings reduced to importable module names."""
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    out = set()
    for requirement in manifest["requirements"]:
        for separator in (">=", "<=", "==", ">", "<", "~=", "!="):
            requirement = requirement.split(separator)[0]
        out.add(requirement.strip().replace("-", "_").lower())
    return out


def test_every_module_level_import_is_one_we_can_count_on() -> None:
    """The guard. Substitute a wrong value to see it work: drop
    `voluptuous-serialize` from `manifest.json` and this fails, naming
    `websocket_api.py` — which is exactly the failure a real Home Assistant
    reported and this suite did not.
    """
    declared = _declared()
    undeclared = {
        module: sites
        for module, sites in _third_party_module_level_imports().items()
        if module not in declared and module not in SUPPLIED_BY_OTHERS
    }
    assert not undeclared, (
        "imported at module level, but neither declared in manifest.json nor "
        "listed in SUPPLIED_BY_OTHERS with a reason:\n"
        + "\n".join(f"  {mod}: {sorted(sites)}" for mod, sites in sorted(undeclared.items()))
    )


def _all_imports() -> dict[str, set[str]]:
    """Every import, at any depth — lazy ones included.

    A lazy import cannot stop setup, so it is out of scope for the guard above.
    It is exactly in scope here: a requirement we ask Home Assistant to install
    is a promise that some code uses it, and a lazy import is the easiest place
    for that promise to quietly stop being true.
    """
    stdlib = set(sys.stdlib_module_names)
    found: dict[str, set[str]] = {}
    for path in sorted(COMPONENT.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for name in names:
                top = name.split(".")[0]
                if top in stdlib or top in ("homeassistant", "custom_components"):
                    continue
                found.setdefault(top, set()).add(f"{path.relative_to(COMPONENT)}:{node.lineno}")
    return found


def test_every_requirement_is_one_some_code_imports() -> None:
    """The other direction, and the one that caught `yandexcloud`.

    Home Assistant installs everything `manifest.json` lists, on every
    installation, before the integration starts. A requirement nothing imports
    is not merely tidy-up: it is a package the user pays to download for
    nothing, and — worse — it reads as proof that the feature it belongs to has
    its dependency handled. `yandexcloud` was declared for years while the
    Yandex embeddings actually import `yandex_cloud_ml_sdk`, which is a
    different distribution and was declared nowhere, so that provider failed at
    the first call with the very error the requirement looked like it prevented.
    """
    imported = set(_all_imports())
    unused = sorted(module for module in _declared() if module not in imported)
    assert not unused, (
        "declared in manifest.json, imported nowhere — either the code that "
        f"needed it is gone, or the module it provides is not the one we import: {unused}"
    )


def test_the_allowlist_does_not_outlive_its_entries() -> None:
    """An entry that nothing imports any more is a claim no one is checking.

    Kept because the allowlist is the part of this file that ages: a module
    dropped from the code leaves behind a licence to not declare it, and the
    next person reads that licence as a decision rather than a leftover.
    """
    imported = set(_third_party_module_level_imports())
    stale = sorted(set(SUPPLIED_BY_OTHERS) - imported)
    assert not stale, f"listed as supplied by others, but nothing imports them: {stale}"
