# Installation and environment

Create a venv, `pip install replayt`, then run `replayt doctor`. This page shows shell setup, Windows notes, optional extras, `.env` loading, and common errors.

## Virtual environment (by shell)

```bash
# bash / zsh (macOS, Linux, WSL)
python -m venv .venv
source .venv/bin/activate

# fish
python -m venv .venv
source .venv/bin/activate.fish

# Windows cmd.exe
python -m venv .venv
.venv\Scripts\activate.bat

# Windows PowerShell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

## Install replayt

```bash
pip install replayt
# pip install replayt[yaml]   # .yaml / .yml workflow targets
# pip install -e ".[dev]"      # from a clone: pytest, ruff, PyYAML
```

Optional extras are defined in [`pyproject.toml`](../pyproject.toml): **`[yaml]`** adds PyYAML for YAML workflow targets. **`[dev]`** is for contributors.

## API keys and providers

```bash
export OPENAI_API_KEY=...   # required for workflows that call a model
replayt doctor
```

If you keep secrets in a `.env` file, load them your own way before running replayt. For example, use `export $(grep -v '^#' .env | xargs)`, [direnv](https://direnv.net/) with `.envrc`, or `python-dotenv` in a wrapper script. replayt does not read `.env` on its own, so environment order stays explicit and auditable.

### Loading `.env` files

**bash / zsh:**

```bash
set -a && source .env && set +a
```

**PowerShell:**

```powershell
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
        [System.Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim(), 'Process')
    }
}
```

**direnv** (auto-loads on `cd`):

```bash
# .envrc
dotenv
```

```bash
direnv allow
```

## Check your setup

```bash
replayt doctor
```

`replayt doctor` reports Python version, package version, API key status, provider connectivity, and optional extras.

## Common errors

| Symptom | Fix |
|---------|-----|
| `OPENAI_API_KEY is not set` | Export your key: `export OPENAI_API_KEY=sk-...` (or load from `.env` as above). |
| `ModuleNotFoundError: No module named 'replayt'` | Activate your virtual environment first, then `pip install replayt` or `pip install -e ".[dev]"` from a clone. |
| `python: command not found` or wrong version | Use `python3` explicitly, or check `python --version` (requires Python 3.10+). |
| `pip: command not found` | Use `python -m pip install ...` instead. |
| `SSL: CERTIFICATE_VERIFY_FAILED` (corporate proxy) | Set `REQUESTS_CA_BUNDLE` / `SSL_CERT_FILE` to your corporate CA bundle, or `pip install pip-system-certs`. |
| `yaml_extra: missing` in `replayt doctor` | Install the YAML extra: `pip install replayt[yaml]`. |
| `provider_connectivity: unreachable` | Check `OPENAI_BASE_URL` and network access. Behind a VPN? Try `curl -I $OPENAI_BASE_URL/models`. |
