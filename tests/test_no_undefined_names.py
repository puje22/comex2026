"""Static check: no function/variable is used without being defined (catches typos and stale references)."""
import ast, builtins, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
bad = []
for fn in ("scraper.py", "analytics.py", "app.py"):
    tree = ast.parse((ROOT / fn).read_text())
    defined = set(dir(builtins)) | {"__file__"}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)): defined.add(n.name)
        elif isinstance(n, ast.Import): defined |= {a.asname or a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom): defined |= {a.asname or a.name for a in n.names}
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)): defined.add(n.id)
        elif isinstance(n, ast.arg): defined.add(n.arg)
        elif isinstance(n, ast.ExceptHandler) and n.name: defined.add(n.name)
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in defined:
            bad.append(f"{fn}:{n.lineno}: undefined name {n.id!r}")
    # functions used from our own modules in app.py must exist
    if fn == "app.py":
        import importlib; sys.path.insert(0, str(ROOT))
        mods = {m: importlib.import_module(m) for m in ("scraper", "analytics")}
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in mods and not hasattr(mods[n.value.id], n.attr):
                bad.append(f"app.py:{n.lineno}: {n.value.id}.{n.attr} does not exist")
assert not bad, "\n".join(bad)
print("no undefined names OK")
