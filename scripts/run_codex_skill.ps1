param(
    [Parameter(Mandatory = $true)]
    [string]$PromptFile,

    [string]$Model,

    [switch]$DangerouslyBypassApprovalsAndSandbox
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$CodexExe = Join-Path $RepoRoot ".replayt\tools\codex-cli\node_modules\@openai\codex-win32-x64\vendor\x86_64-pc-windows-msvc\codex\codex.exe"

if (-not (Test-Path $PromptFile)) {
    throw "Prompt file not found: $PromptFile"
}

if (-not (Test-Path $CodexExe)) {
    throw "Local Codex CLI not found at $CodexExe. Install it with: npm install --prefix .replayt\tools\codex-cli @openai/codex"
}

$Prompt = Get-Content -Raw -Encoding UTF8 $PromptFile
$Args = @("exec", "-C", $RepoRoot, "--skip-git-repo-check")

if ($Model) {
    $Args += @("--model", $Model)
}

if ($DangerouslyBypassApprovalsAndSandbox) {
    $Args += "--dangerously-bypass-approvals-and-sandbox"
} else {
    $Args += "--full-auto"
}

$Args += "-"

$Prompt | & $CodexExe @Args
exit $LASTEXITCODE
