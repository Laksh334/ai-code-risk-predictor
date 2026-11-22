"""A2 - Static code analysis: read every Python file of a repo (at any commit) and measure it.

Per file (from that file alone):
  * Python `ast`  - functions, classes, imports, max nesting depth
  * Lizard        - cyclomatic complexity per function, function length, parameters
                    (token based, so it also works on old Python 2 code)
  * Radon         - lines of code / comments, maintainability index, Halstead volume

Repo wide (needs all files together):
  * coupling      - fan-in / fan-out over the internal import graph
  * duplication   - % of a file's lines inside a block that is copy-pasted elsewhere
  * test links    - is there a test file for it / how many test files import it

Files are read straight from Git objects, so any past commit can be analysed without a
checkout - which A3 needs for time-based snapshots.

    python -m pipeline.static_analysis path/to/repo
    python -m pipeline.static_analysis path/to/repo --rev 2016-01-01
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
import warnings
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import lizard
import pandas as pd
from git import Repo
from radon.metrics import h_visit, mi_visit
from radon.raw import analyze as radon_raw

from pipeline.filters import is_source_file
from pipeline.paths import DATA_DIR

MAX_FILE_BYTES = 1_000_000  # skip huge generated/vendored files
DUP_WINDOW = 6  # a copy-paste block = at least 6 identical (normalised) lines

# ---------------------------------------------------------------------------
# Reading files from Git
# ---------------------------------------------------------------------------


def resolve_rev(repo: Repo, rev: str = "HEAD") -> str:
    """Accept a commit/branch/tag, or a date "YYYY-MM-DD" = last commit before that date."""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", rev):
        sha = repo.git.rev_list("-1", f"--before={rev}T00:00:00Z", "HEAD")
        if not sha:
            raise ValueError(f"No commits before {rev}")
        return sha
    return repo.commit(rev).hexsha


def read_python_files(repo_path: str | Path, rev: str = "HEAD") -> tuple[str, dict[str, str]]:
    """Return (commit sha, {path: source}) for every .py file as it was at `rev`."""
    repo = Repo(repo_path)
    sha = resolve_rev(repo, rev)
    files: dict[str, str] = {}
    for item in repo.commit(sha).tree.traverse():
        if item.type == "blob" and is_source_file(item.path) and item.size <= MAX_FILE_BYTES:
            files[item.path] = item.data_stream.read().decode("utf-8", errors="replace")
    return sha, files


# ---------------------------------------------------------------------------
# Per-file metrics
# ---------------------------------------------------------------------------

_BLOCKS = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.Match)
if hasattr(ast, "TryStar"):
    _BLOCKS += (ast.TryStar,)


def max_nesting_depth(node: ast.AST, depth: int = 0) -> int:
    """Deepest stack of if/for/while/try/with/match blocks.
    `elif` is stored as an If inside `orelse`; it is counted at the same depth, not deeper."""
    best = depth
    elif_node = None
    if isinstance(node, ast.If) and len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
        elif_node = node.orelse[0]
    for child in ast.iter_child_nodes(node):
        if child is elif_node:
            best = max(best, max_nesting_depth(child, depth))
        else:
            best = max(best, max_nesting_depth(child, depth + isinstance(child, _BLOCKS)))
    return best


def _safe(fn, default=None):
    try:
        with warnings.catch_warnings():
            # Old code triggers SyntaxWarnings (e.g. "invalid escape sequence") - harmless here.
            warnings.simplefilter("ignore")
            return fn()
    except Exception:  # radon/ast raise many error types on unusual code
        return default


def analyze_source(path: str, code: str) -> dict:
    """All single-file metrics for one Python source file."""
    row: dict = {"file_path": path}

    # Radon raw counts are tokenizer based, so they work even if parsing fails.
    raw = _safe(lambda: radon_raw(code))
    row["loc"] = raw.loc if raw else code.count("\n") + 1
    row["sloc"] = raw.sloc if raw else None
    row["comments"] = (raw.comments + raw.multi) if raw else None
    row["comment_ratio"] = round(row["comments"] / raw.sloc, 3) if raw and raw.sloc else 0.0

    # Lizard: per-function complexity / size.
    funcs = lizard.analyze_file.analyze_source_code(path, code).function_list
    ccn = [f.cyclomatic_complexity for f in funcs]
    nloc = [f.nloc for f in funcs]
    row.update(
        num_functions=len(funcs),
        total_complexity=sum(ccn),
        avg_complexity=round(sum(ccn) / len(ccn), 2) if ccn else 0.0,
        max_complexity=max(ccn, default=0),
        avg_function_length=round(sum(nloc) / len(nloc), 1) if nloc else 0.0,
        max_function_length=max(nloc, default=0),
        max_params=max((f.parameter_count for f in funcs), default=0),
    )

    # Python AST: fails on Python 2 syntax (old snapshots) -> leave those fields empty.
    tree = _safe(lambda: ast.parse(code))
    row["parse_ok"] = tree is not None
    if tree is not None:
        row["num_classes"] = sum(isinstance(n, ast.ClassDef) for n in ast.walk(tree))
        row["num_imports"] = sum(isinstance(n, (ast.Import, ast.ImportFrom)) for n in ast.walk(tree))
        row["max_nesting_depth"] = max_nesting_depth(tree)
        mi = _safe(lambda: mi_visit(code, multi=True))
        row["maintainability"] = round(mi, 2) if mi is not None else None
        hv = _safe(lambda: h_visit(code).total.volume)
        row["halstead_volume"] = round(hv, 1) if hv is not None else None
    else:
        row.update(num_classes=None, num_imports=None, max_nesting_depth=None,
                   maintainability=None, halstead_volume=None)
    return row


# ---------------------------------------------------------------------------
# Repo-wide metrics
# ---------------------------------------------------------------------------


def is_test_file(path: str) -> bool:
    p = PurePosixPath(path)
    return (p.name.startswith("test_") or p.name.endswith("_test.py") or p.name == "conftest.py"
            or any(part in {"test", "tests", "testing"} for part in p.parts[:-1]))


def module_name(path: str) -> str:
    """src/requests/models.py -> requests.models ; pkg/__init__.py -> pkg"""
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[0] in {"src", "lib"}:
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imported_modules(path: str, tree: ast.Module) -> set[str]:
    """Every module name this file imports (relative imports resolved to absolute)."""
    me = module_name(path)
    package = me if path.endswith("__init__.py") else me.rpartition(".")[0]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # from . import x / from ..utils import y
                base = package.split(".") if package else []
                base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
                prefix = ".".join(base + ([node.module] if node.module else []))
            else:
                prefix = node.module or ""
            found.add(prefix)
            found.update(f"{prefix}.{a.name}" if prefix else a.name for a in node.names)
    return found


def coupling_and_tests(files: dict[str, str]) -> pd.DataFrame:
    """fan_out = internal modules a file imports; fan_in = non-test files importing it."""
    by_module = {module_name(p): p for p in files}
    imports: dict[str, set[str]] = {}
    for path, code in files.items():
        tree = _safe(lambda c=code: ast.parse(c))
        if tree is None:
            continue
        targets = set()
        for name in _imported_modules(path, tree):
            # "requests.models.Response" -> longest prefix that is a real module in the repo
            parts = name.split(".")
            for i in range(len(parts), 0, -1):
                hit = by_module.get(".".join(parts[:i]))
                if hit:
                    if hit != path:
                        targets.add(hit)
                    break
        imports[path] = targets

    fan_in: dict[str, int] = defaultdict(int)
    test_importers: dict[str, int] = defaultdict(int)
    for src, targets in imports.items():
        for t in targets:
            if is_test_file(src):
                test_importers[t] += 1
            else:
                fan_in[t] += 1

    test_names = {PurePosixPath(p).name for p in files if is_test_file(p)}
    rows = []
    for path in files:
        stem = PurePosixPath(path).stem
        fo, fi = len(imports.get(path, ())), fan_in[path]
        rows.append({
            "file_path": path,
            "fan_in": fi,
            "fan_out": fo,
            "coupling": fi + fo,
            "instability": round(fo / (fi + fo), 3) if fi + fo else 0.0,
            "is_test_file": is_test_file(path),
            "has_test_file": f"test_{stem}.py" in test_names or f"{stem}_test.py" in test_names,
            "test_importers": test_importers[path],
        })
    return pd.DataFrame(rows)


def _normalise(code: str) -> list[tuple[int, str]]:
    """(line number, text) of meaningful lines: stripped, no blanks/comments/imports."""
    out = []
    for no, line in enumerate(code.splitlines()):
        s = line.strip()
        if s and not s.startswith(("#", "import ", "from ")) and s not in {'"""', "'''", ")", "]", "}"}:
            out.append((no, re.sub(r"\s+", " ", s)))
    return out


def duplication(files: dict[str, str], window: int = DUP_WINDOW) -> dict[str, float]:
    """% of each file's meaningful lines that sit in a `window`-line block also found
    elsewhere (in another file or the same file). Simple hash-based clone detection."""
    normalised = {p: _normalise(c) for p, c in files.items()}
    seen: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for path, lines in normalised.items():
        for i in range(len(lines) - window + 1):
            block = "\n".join(t for _, t in lines[i : i + window])
            seen[hashlib.md5(block.encode()).hexdigest()].append((path, i))

    dup_lines: dict[str, set[int]] = defaultdict(set)
    for spots in seen.values():
        if len(spots) > 1:
            for path, i in spots:
                dup_lines[path].update(range(i, i + window))
    return {p: round(100 * len(dup_lines[p]) / len(lines), 1) if lines else 0.0
            for p, lines in normalised.items()}


# ---------------------------------------------------------------------------
# Whole repository
# ---------------------------------------------------------------------------


def analyze_repository(repo_path: str | Path, rev: str = "HEAD") -> pd.DataFrame:
    """One row per Python file at `rev` with every static metric."""
    sha, files = read_python_files(repo_path, rev)
    if not files:
        return pd.DataFrame()
    df = pd.DataFrame([analyze_source(p, c) for p, c in files.items()])
    df = df.merge(coupling_and_tests(files), on="file_path")
    df["duplication"] = df["file_path"].map(duplication(files))
    df["commit_sha"] = sha
    return df.sort_values("total_complexity", ascending=False).reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Static analysis of every Python file in a repo.")
    ap.add_argument("repo", help="local repo path (use pipeline.git_history to clone a URL)")
    ap.add_argument("--rev", default="HEAD", help="commit, branch, tag or YYYY-MM-DD")
    ap.add_argument("--out", default=str(DATA_DIR / "processed"))
    args = ap.parse_args()

    started = datetime.now(timezone.utc)
    df = analyze_repository(args.repo, args.rev)
    name = Path(args.repo).resolve().name
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{name}_static.csv"
    df.to_csv(target, index=False)
    secs = (datetime.now(timezone.utc) - started).total_seconds()
    print(f"{name} @ {df['commit_sha'].iloc[0][:10]}: {len(df)} files analysed in {secs:.1f}s "
          f"({(~df['parse_ok']).sum()} could not be parsed as Python 3) -> {target}")


if __name__ == "__main__":
    main()
