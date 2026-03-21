param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$CodexExe = Join-Path $RepoRoot ".replayt\tools\codex-cli\node_modules\@openai\codex-win32-x64\vendor\x86_64-pc-windows-msvc\codex\codex.exe"

if (-not (Test-Path $CodexExe)) {
    throw "Local Codex CLI not found at $CodexExe. Install it with: npm install --prefix .replayt\tools\codex-cli @openai/codex"
}

& $CodexExe @Args
exit $LASTEXITCODE
