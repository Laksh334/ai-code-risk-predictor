"""Which files the pipeline analyses. Shared by A1 (history) and A2 (static analysis)
so both produce exactly the same set of files."""

from pathlib import PurePosixPath

# Third-party code copied into a repo. The team doesn't maintain it, so predicting its
# risk is meaningless - and it can be huge (e.g. chardet's frequency tables).
VENDOR_DIRS = {
    "vendor", "vendored", "_vendor", "third_party", "thirdparty", "externals",
    "site-packages", "node_modules", ".venv", "venv",
}


def is_vendored(path: str) -> bool:
    parts = PurePosixPath(path).parts[:-1]
    # "pkg/packages/..." is the old requests/pip vendoring style; a top-level
    # "packages/" folder is usually a monorepo, so only nested ones count.
    return any(p in VENDOR_DIRS for p in parts) or "packages" in parts[1:]


def is_source_file(path: str, extensions: tuple[str, ...] = (".py",)) -> bool:
    return path.endswith(extensions) and not is_vendored(path)
