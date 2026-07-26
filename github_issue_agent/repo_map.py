"""A lightweight repository map: file inventory, languages and symbol index.

The map is deliberately small enough to sit in the model's stable context. It
contains no file bodies; the model pulls those in through tools when it needs
them.
"""

from __future__ import annotations

import ast
import re
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

IGNORE_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".idea",
    ".agent_work",
    ".tox",
    "target",
    "vendor",
}

BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".tar",
    ".whl", ".so", ".dylib", ".dll", ".class", ".jar", ".exe", ".bin",
    ".woff", ".woff2", ".ttf", ".mp4", ".mp3", ".pyc",
}

LOCKFILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "Cargo.lock",
    "Gemfile.lock",
    "composer.lock",
    "go.sum",
}

_LANGUAGES = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".kt": "kotlin",
    ".swift": "swift",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".sh": "shell",
    ".md": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".json": "json",
}

_BUILD_FILES = [
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "Makefile",
]

_INSTRUCTION_FILES = [
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    ".github/copilot-instructions.md",
    "README.md",
]

# Regex symbol extraction for the non-Python languages we care about most.
_JS_SYMBOL_RE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?"
    r"(?:(?:async\s+)?function\s+(?P<fn>[A-Za-z_$][\w$]*)"
    r"|class\s+(?P<cls>[A-Za-z_$][\w$]*)"
    r"|(?:const|let|var)\s+(?P<var>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\()",
    re.MULTILINE,
)
_GO_SYMBOL_RE = re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?(?P<fn>[A-Za-z_]\w*)", re.MULTILINE)
_RUST_SYMBOL_RE = re.compile(
    r"^\s*(?:pub\s+)?(?:fn\s+(?P<fn>[a-z_]\w*)|struct\s+(?P<st>[A-Za-z_]\w*)"
    r"|enum\s+(?P<en>[A-Za-z_]\w*)|trait\s+(?P<tr>[A-Za-z_]\w*))",
    re.MULTILINE,
)


def language_of(path: str) -> str:
    return _LANGUAGES.get(Path(path).suffix.lower(), "other")


def is_probably_text(path: Path) -> bool:
    return path.suffix.lower() not in BINARY_SUFFIXES


def iter_repo_files(repo_path: Path, max_files: int = 20_000) -> list[str]:
    """Return repo-relative paths of tracked (or non-ignored) text-ish files."""
    files: list[str] = []
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        files = [line for line in out.splitlines() if line.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        files = []

    if not files:
        for path in sorted(repo_path.rglob("*")):
            if any(part in IGNORE_DIRS for part in path.parts):
                continue
            if path.is_file():
                files.append(str(path.relative_to(repo_path)))
            if len(files) >= max_files:
                break

    return sorted(
        f
        for f in files
        if not any(part in IGNORE_DIRS for part in Path(f).parts)
        and is_probably_text(Path(f))
    )[:max_files]


@dataclass
class FileEntry:
    path: str
    language: str
    symbols: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)


@dataclass
class RepoMap:
    """Navigation-only view of a repository."""

    repo_path: Path
    files: list[FileEntry] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    build_files: list[str] = field(default_factory=list)
    instruction_files: list[str] = field(default_factory=list)
    test_frameworks: list[str] = field(default_factory=list)

    def tree(self, max_entries: int = 300) -> str:
        paths = [f.path for f in self.files]
        shown = paths[:max_entries]
        extra = len(paths) - len(shown)
        text = "\n".join(shown)
        if extra > 0:
            text += f"\n... [{extra} more files; use list_files/search_code to explore]"
        return text

    def symbol_summary(self, max_files: int = 60, max_symbols: int = 8) -> str:
        parts: list[str] = []
        ranked = sorted(self.files, key=lambda f: -len(f.symbols))
        for entry in ranked[:max_files]:
            if not entry.symbols:
                continue
            syms = "\n".join(f"  {s}" for s in entry.symbols[:max_symbols])
            parts.append(f"{entry.path}\n{syms}")
        return "\n\n".join(parts) or "(no symbols indexed)"

    def as_context_block(self) -> str:
        return (
            "<repository_map>\n"
            f"languages: {', '.join(self.languages) or 'unknown'}\n"
            f"build_files: {', '.join(self.build_files) or 'none'}\n"
            f"test_frameworks: {', '.join(self.test_frameworks) or 'unknown'}\n"
            f"instruction_files: {', '.join(self.instruction_files) or 'none'}\n\n"
            "<files>\n"
            f"{self.tree()}\n"
            "</files>\n\n"
            "<symbols>\n"
            f"{self.symbol_summary()}\n"
            "</symbols>\n"
            "</repository_map>"
        )


def _python_symbols(source: str) -> tuple[list[str], list[str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [], []
    symbols: list[str] = []
    imports: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            symbols.append(f"class {node.name}")
            for child in node.body:
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    symbols.append(f"  def {node.name}.{child.name}")
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            symbols.append(f"def {node.name}")
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return symbols, imports


def _regex_symbols(source: str, language: str) -> list[str]:
    pattern = {
        "javascript": _JS_SYMBOL_RE,
        "typescript": _JS_SYMBOL_RE,
        "go": _GO_SYMBOL_RE,
        "rust": _RUST_SYMBOL_RE,
    }.get(language)
    if pattern is None:
        return []
    found: list[str] = []
    for match in pattern.finditer(source):
        name = next((v for v in match.groupdict().values() if v), None)
        if name:
            found.append(name)
    return found


def _detect_test_frameworks(repo_path: Path, files: list[str]) -> list[str]:
    frameworks: list[str] = []
    names = set(files)
    pyproject = repo_path / "pyproject.toml"
    if any(n.startswith("tests/") or "test_" in Path(n).name for n in names):
        if pyproject.exists() or any(n.endswith(".py") for n in names):
            frameworks.append("pytest")
    package_json = repo_path / "package.json"
    if package_json.exists():
        text = package_json.read_text(encoding="utf-8", errors="replace")
        for candidate in ("vitest", "jest", "mocha", "playwright"):
            if candidate in text:
                frameworks.append(candidate)
    if "go.mod" in names:
        frameworks.append("go test")
    if "Cargo.toml" in names:
        frameworks.append("cargo test")
    return frameworks


def build_repo_map(repo_path: Path, max_indexed_files: int = 1200) -> RepoMap:
    """Index the repository without loading its contents into the prompt."""
    files = iter_repo_files(repo_path)
    entries: list[FileEntry] = []
    languages: dict[str, int] = {}

    for rel in files:
        language = language_of(rel)
        languages[language] = languages.get(language, 0) + 1
        entry = FileEntry(path=rel, language=language)
        if len(entries) < max_indexed_files and language in {
            "python",
            "javascript",
            "typescript",
            "go",
            "rust",
        }:
            try:
                source = (repo_path / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                source = ""
            if language == "python":
                entry.symbols, entry.imports = _python_symbols(source)
            else:
                entry.symbols = _regex_symbols(source, language)
        entries.append(entry)

    ranked_languages = [
        lang
        for lang, _ in sorted(languages.items(), key=lambda kv: -kv[1])
        if lang not in {"other", "markdown", "json", "yaml", "toml"}
    ][:5]

    return RepoMap(
        repo_path=repo_path,
        files=entries,
        languages=ranked_languages,
        build_files=[f for f in _BUILD_FILES if (repo_path / f).exists()],
        instruction_files=[f for f in _INSTRUCTION_FILES if (repo_path / f).exists()],
        test_frameworks=_detect_test_frameworks(repo_path, files),
    )


@lru_cache(maxsize=8)
def cached_repo_map(repo_path: str) -> RepoMap:
    return build_repo_map(Path(repo_path))
