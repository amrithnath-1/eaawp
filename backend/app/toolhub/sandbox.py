"""
Isolated execution of generated tool code.

Two independent layers, both always applied:
1. Static checks (check_code): parsed with `ast`; only a run(inputs) function, helper functions and constants at top
   level; imports only from an allowlist of pure-computation modules; no eval/exec/compile/open/__import__/getattr/
   globals/…; no names or attributes starting with "_" (blocks dunder escapes such as ().__class__.__subclasses__);
   no classes, async, global/nonlocal; size limit.
2. Process isolation (run): a separate `python -I -S -B` process with an EMPTY environment (no secrets, no
   DATABASE_URL), an empty temporary working directory, restricted builtins and an import hook (see _sandbox_runner),
   OS limits on CPU time, memory, open files, written file size and child processes, a wall-clock timeout and
   input/output size caps. The child never imports EAAWP code and has no database handle.
"""
from __future__ import annotations

import ast
import asyncio
import json
import os
import pathlib
import sys
import tempfile
import time
from dataclasses import dataclass

RUNNER = pathlib.Path(__file__).with_name("_sandbox_runner.py")
ALLOWED_MODULES = frozenset({"math", "statistics", "json", "re", "datetime", "decimal", "fractions", "collections",
                             "itertools", "functools", "string", "operator", "heapq", "bisect", "textwrap",
                             "calendar", "unicodedata", "random"})
FORBIDDEN_NAMES = frozenset({"eval", "exec", "compile", "open", "__import__", "globals", "locals", "vars", "getattr",
                             "setattr", "delattr", "input", "breakpoint", "help", "exit", "quit", "memoryview",
                             "type", "object", "super", "classmethod", "staticmethod", "property", "dir", "id",
                             "bytearray", "bytes", "print", "os", "sys", "subprocess", "socket", "importlib",
                             "builtins", "__builtins__", "file", "reload",
                             # attribute access by string: str.format / format_map / string.Formatter read any
                             # attribute; operator.attrgetter / methodcaller read AND call them (sandbox escape route)
                             "format", "format_map", "vformat", "Formatter", "attrgetter", "methodcaller"})
MAX_CODE_CHARS = 20_000
MAX_INPUT_CHARS = 500_000
CPU_SECONDS = 3
WALL_SECONDS = 6.0
MEMORY_BYTES = 512 * 1024 * 1024


def check_code(code: str) -> list[str]:
    """Reasons the code may not run (empty list = passes the static checks)."""
    if not isinstance(code, str) or not code.strip():
        return ["no code"]
    if len(code) > MAX_CODE_CHARS:
        return [f"code longer than {MAX_CODE_CHARS} characters"]
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"syntax error: {exc.msg} (line {exc.lineno})"]
    problems: list[str] = []
    has_run = False
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            has_run = has_run or (node.name == "run" and len(node.args.args) == 1)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            pass
        elif isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) for t in node.targets):
            pass
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            pass    # docstring
        else:
            problems.append(f"line {node.lineno}: only functions, imports and constants are allowed at top level")
    if not has_run:
        problems.append("the tool must define run(inputs)")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in ALLOWED_MODULES:
                    problems.append(f"line {node.lineno}: import of '{a.name}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "").split(".")[0] not in ALLOWED_MODULES:
                problems.append(f"line {node.lineno}: import from '{node.module}' is not allowed")
            for a in node.names:
                if a.name == "*" or a.name.startswith("_") or a.name in FORBIDDEN_NAMES:
                    problems.append(f"line {node.lineno}: importing '{a.name}' is not allowed")
        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES or node.id.startswith("_"):
                problems.append(f"line {node.lineno}: use of '{node.id}' is not allowed")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_") or node.attr in FORBIDDEN_NAMES:
                problems.append(f"line {node.lineno}: attribute '{node.attr}' is not allowed")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and "__" in node.value:
            problems.append(f"line {node.lineno}: text containing '__' is not allowed")
        elif isinstance(node, (ast.ClassDef, ast.AsyncFunctionDef, ast.Await, ast.Global, ast.Nonlocal,
                               ast.AsyncFor, ast.AsyncWith)):
            problems.append(f"line {node.lineno}: {type(node).__name__} is not allowed")
        elif isinstance(node, ast.FunctionDef) and node.name.startswith("_"):
            problems.append(f"line {node.lineno}: function names may not start with '_'")
    return list(dict.fromkeys(problems))[:20]


@dataclass
class RunResult:
    ok: bool
    output: object = None
    error: str = ""
    duration_ms: int = 0
    timed_out: bool = False


def _limits() -> None:     # runs in the child before exec (POSIX only)
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
    try:
        resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
    except (ValueError, OSError):
        pass
    os.setsid()


def _run_sync(code: str, inputs: object) -> RunResult:
    problems = check_code(code)
    if problems:
        return RunResult(ok=False, error="sandbox rejected the code: " + "; ".join(problems))
    payload = json.dumps({"code": code, "inputs": inputs}, default=str)
    if len(payload) > MAX_INPUT_CHARS + MAX_CODE_CHARS:
        return RunResult(ok=False, error="input too large for the sandbox")
    import subprocess
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="eaawp-sbx-") as cwd:
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-S", "-B", str(RUNNER)], input=payload, capture_output=True, text=True,
                timeout=WALL_SECONDS, cwd=cwd, env={},
                preexec_fn=_limits if os.name == "posix" else None,
            )
        except subprocess.TimeoutExpired:
            return RunResult(ok=False, error=f"timed out after {WALL_SECONDS:.0f} s", timed_out=True,
                             duration_ms=int((time.monotonic() - t0) * 1000))
    ms = int((time.monotonic() - t0) * 1000)
    if proc.returncode != 0 and not proc.stdout:
        reason = "CPU or memory limit reached" if proc.returncode < 0 else f"exited with code {proc.returncode}"
        return RunResult(ok=False, error=f"sandbox process {reason}", duration_ms=ms,
                         timed_out=proc.returncode in (-24, -9))
    try:
        res = json.loads(proc.stdout or "{}")
    except ValueError:
        return RunResult(ok=False, error="sandbox output was not valid JSON", duration_ms=ms)
    if res.get("ok"):
        return RunResult(ok=True, output=res.get("output"), duration_ms=ms)
    return RunResult(ok=False, error=str(res.get("error") or "failed")[:500], duration_ms=ms)


async def run(code: str, inputs: object) -> RunResult:
    """Run generated code on `inputs` in the sandbox (off the event loop)."""
    return await asyncio.get_running_loop().run_in_executor(None, _run_sync, code, inputs)
