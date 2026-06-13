from pathlib import Path


CONFLICT_MARKERS = ("<<<<<<< ", ">>>>>>> ", "||||||| ")
EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
}
CHECK_SUFFIXES = {
    ".cfg",
    ".env",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}


def _iter_text_files(repo_root: Path):
    for path in repo_root.rglob("*"):
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if not path.is_file() or path.suffix not in CHECK_SUFFIXES:
            continue
        yield path


def test_repository_has_no_unresolved_merge_conflict_markers() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    offenders = []
    for path in _iter_text_files(repo_root):
        try:
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if line.startswith(CONFLICT_MARKERS):
                    offenders.append(f"{path.relative_to(repo_root)}:{line_no}:{line}")
        except UnicodeDecodeError:
            continue

    assert not offenders, "Unresolved merge conflict markers found:\n" + "\n".join(offenders)
