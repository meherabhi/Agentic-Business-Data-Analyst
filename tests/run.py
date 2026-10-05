"""Minimal stdlib test runner. Discovers test_*.py in this directory, runs every
function named test_*, and reports pass/fail. No third-party dependencies."""
import importlib.util
import os
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))


def load(path):
    spec = importlib.util.spec_from_file_location(os.path.basename(path)[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    files = sorted(f for f in os.listdir(HERE)
                   if f.startswith("test_") and f.endswith(".py"))
    passed = failed = 0
    for f in files:
        mod = load(os.path.join(HERE, f))
        for name in sorted(dir(mod)):
            if not name.startswith("test_"):
                continue
            fn = getattr(mod, name)
            if not callable(fn):
                continue
            try:
                fn()
                passed += 1
                print(f"  PASS  {f}::{name}")
            except Exception:
                failed += 1
                print(f"  FAIL  {f}::{name}")
                traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
