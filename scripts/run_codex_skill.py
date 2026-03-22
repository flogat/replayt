#!/usr/bin/env python3
"""Run a generated skill prompt through the repo-local Codex CLI install."""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
from pathlib import Path

PACKAGE_BY_TARGET = {
    ("Windows", "AMD64"): ("@openai/codex-win32-x64", "x86_64-pc-windows-msvc", "codex.exe"),
    ("Windows", "ARM64"): ("@openai/codex-win32-arm64", "aarch64-pc-windows-msvc", "codex.exe"),
    ("Linux", "x86_64"): ("@openai/codex-linux-x64", "x86_64-unknown-linux-musl", "codex"),
    ("Linux", "aarch64"): ("@openai/codex-linux-arm64", "aarch64-unknown-linux-musl", "codex"),
    ("Darwin", "x86_64"): ("@openai/codex-darwin-x64", "x86_64-apple-darwin", "codex"),
    ("Darwin", "arm64"): ("@openai/codex-darwin-arm64", "aarch64-apple-darwin", "codex"),
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt-file", required=True, help="Path to the generated skill prompt file.")
    parser.add_argument(
        "--skill-root",
        help=(
            "Optional skill directory (validated and used for defaults). "
            "Skill text is already embedded in generated prompts; current `codex exec` does not take "
            "`--skill-root`, so this is not forwarded to the Codex CLI."
        ),
    )
    parser.add_argument("--model", help="Optional Codex model override.")
    parser.add_argument(
        "--dangerously-bypass-approvals-and-sandbox",
        action="store_true",
        help="Pass through Codex's dangerous non-sandboxed mode.",
    )
    return parser.parse_args(argv)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def codex_install_root() -> Path:
    return repo_root() / ".replayt" / "tools" / "codex-cli"


def default_skill_root() -> Path:
    return repo_root() / ".cursor" / "skills"


def resolve_skill_root(raw_path: str | None) -> Path | None:
    candidate = (raw_path or "").strip()
    if candidate:
        path = Path(candidate).expanduser()
        if not path.is_absolute():
            path = (repo_root() / path).resolve()
        else:
            path = path.resolve()
    else:
        path = default_skill_root().resolve()
        if not path.exists():
            env_root = os.environ.get("SKILL_ROOT", "").strip()
            if not env_root:
                return None
            path = Path(env_root).expanduser()
            if not path.is_absolute():
                path = (repo_root() / path).resolve()
            else:
                path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(f"Skill root not found: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"Skill root is not a directory: {path}")
    return path


def codex_binary_path() -> Path:
    key = (platform.system(), platform.machine())
    if key not in PACKAGE_BY_TARGET:
        raise RuntimeError(f"Unsupported platform for local Codex CLI install: {key[0]} {key[1]}")
    package_name, target_triple, binary_name = PACKAGE_BY_TARGET[key]
    return (
        codex_install_root()
        / "node_modules"
        / package_name
        / "vendor"
        / target_triple
        / "codex"
        / binary_name
    )


def ensure_codex_installed() -> Path:
    binary = codex_binary_path()
    if binary.exists():
        return binary
    install_root = codex_install_root()
    install_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["npm", "install", "--prefix", str(install_root), "@openai/codex"],
        check=True,
        cwd=repo_root(),
    )
    if not binary.exists():
        raise RuntimeError(f"Codex CLI install completed but binary was not found at {binary}")
    return binary


def codex_path_entries(binary: Path) -> list[str]:
    arch_root = binary.parent.parent
    path_dir = arch_root / "path"
    entries: list[str] = []
    if path_dir.exists():
        entries.append(str(path_dir))
    return entries


def _venv_bin_dir() -> Path:
    if os.name == "nt":
        return repo_root() / ".venv" / "Scripts"
    return repo_root() / ".venv" / "bin"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    prompt_path = Path(args.prompt_file).resolve()
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    prompt = prompt_path.read_text(encoding="utf-8")
    skill_root = resolve_skill_root(args.skill_root)
    binary = ensure_codex_installed()
    env = os.environ.copy()
    extra_path = codex_path_entries(binary)
    venv_bin = _venv_bin_dir()
    if venv_bin.exists():
        extra_path.insert(0, str(venv_bin))
        env["VIRTUAL_ENV"] = str(venv_bin.parent)
    if extra_path:
        env["PATH"] = os.pathsep.join([*extra_path, env.get("PATH", "")])
    command = ["exec", "-C", str(repo_root()), "--skip-git-repo-check"]
    if args.model:
        command += ["--model", args.model]
    # `codex exec` no longer supports `--skill-root` (removed in recent Codex CLI). Skills are either
    # inlined in the prompt by skill_release_loop or read from paths under the repo working root.
    if skill_root is not None:
        try:
            skill_root.resolve().relative_to(repo_root().resolve())
        except ValueError:
            command += ["--add-dir", str(skill_root)]
    if args.dangerously_bypass_approvals_and_sandbox:
        command.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        command.append("--full-auto")
    command.append("-")
    # Pass UTF-8 bytes so Windows does not use the console code page (e.g. cp1252) for stdin.
    result = subprocess.run(
        [str(binary), *command],
        input=prompt.encode("utf-8"),
        cwd=repo_root(),
        env=env,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
