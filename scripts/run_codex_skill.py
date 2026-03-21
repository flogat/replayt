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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    prompt_path = Path(args.prompt_file).resolve()
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    prompt = prompt_path.read_text(encoding="utf-8")
    binary = ensure_codex_installed()
    env = os.environ.copy()
    extra_path = codex_path_entries(binary)
    if extra_path:
        env["PATH"] = os.pathsep.join([*extra_path, env.get("PATH", "")])
    command = ["exec", "-C", str(repo_root()), "--skip-git-repo-check"]
    if args.model:
        command += ["--model", args.model]
    if args.dangerously_bypass_approvals_and_sandbox:
        command.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        command.append("--full-auto")
    command.append("-")
    result = subprocess.run(
        [str(binary), *command],
        input=prompt,
        text=True,
        encoding="utf-8",
        cwd=repo_root(),
        env=env,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
