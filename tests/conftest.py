import os

# Used to prevent rich from wrapping output
os.environ["TERMINAL_WIDTH"] = "10000"

# Used to prevent rich from forcing color output in CI (like GITHUB_ACTIONS)
os.environ["NO_COLOR"] = "1"
os.environ["TERM"] = "dumb"
os.environ.pop("GITHUB_ACTIONS", None)
os.environ.pop("FORCE_COLOR", None)
