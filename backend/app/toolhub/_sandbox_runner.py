"""
Sandbox child process. Started by app.toolhub.sandbox with `python -I -S -B`, an EMPTY environment, an empty
temporary working directory and OS resource limits. Reads {"code", "inputs"} as JSON on stdin, runs the code's
run(inputs) with a restricted set of builtins and an import hook that only allows pure-computation modules, and
writes {"ok": true, "output": ...} or {"ok": false, "error": ...} as JSON on stdout.

This file must stay free of project imports: the child never loads EAAWP code, settings, secrets or the database.
"""
import json
import sys

ALLOWED_MODULES = {"math", "statistics", "json", "re", "datetime", "decimal", "fractions", "collections",
                   "itertools", "functools", "string", "operator", "heapq", "bisect", "textwrap", "calendar",
                   "unicodedata", "random"}

SAFE_BUILTINS = {name: __builtins__[name] if isinstance(__builtins__, dict) else getattr(__builtins__, name)
                 for name in ("abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float",
                          "frozenset", "int", "isinstance", "len", "list", "map", "max", "min",
                          "pow", "range", "repr", "reversed", "round", "set", "slice", "sorted", "str", "sum",
                          "tuple", "zip", "ValueError", "TypeError", "KeyError", "IndexError",
                          "ZeroDivisionError", "ArithmeticError", "Exception", "StopIteration", "True",
                          "False", "None", "chr", "ord", "hash", "iter", "next")
                 if (name in __builtins__ if isinstance(__builtins__, dict) else hasattr(__builtins__, name))}


def _import(name, globals=None, locals=None, fromlist=(), level=0):
    if level != 0 or name.split(".")[0] not in ALLOWED_MODULES:
        raise ImportError(f"import of '{name}' is not allowed in the sandbox")
    return __import__(name, globals, locals, fromlist, level)


def main() -> None:
    req = json.loads(sys.stdin.read() or "{}")
    builtins = dict(SAFE_BUILTINS)
    builtins["__import__"] = _import
    env = {"__builtins__": builtins, "__name__": "generated_tool"}
    try:
        exec(compile(req["code"], "<generated tool>", "exec"), env)   # code already passed the static checks
        out = env["run"](req.get("inputs") or {})
        text = json.dumps({"ok": True, "output": out}, default=str)
    except BaseException as exc:   # noqa: BLE001 - report every failure as data, never crash silently
        text = json.dumps({"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:500]}"})
    sys.stdout.write(text[:1_000_000])


if __name__ == "__main__":
    main()
