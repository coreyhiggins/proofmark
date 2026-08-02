#!/bin/sh
# proofmark installer. Works on Linux, macOS, and WSL.
#
# Read this before you run it. It is short on purpose.
#
#   curl -fsSL https://raw.githubusercontent.com/coreyhiggins/proofmark/main/install.sh -o install.sh
#   less install.sh
#   sh install.sh
#
# It will not run from a pipe unless you pass --yes, because "curl | sh"
# teaches people to execute code they have not read, and the next thing they
# pipe into a shell might not be this.
#
# What it does:
#   1. Installs uv if missing (from astral.sh, the official installer).
#   2. Installs proofmark as an isolated tool, with its own Python.
#   3. Tells you the one command to start it.
#
# It does not use sudo, touch system Python, or write outside ~/.local.

set -eu

REPO="coreyhiggins/proofmark"
ASSUME_YES=0
WITH_EXTRAS="crypto"

for arg in "$@"; do
  case "$arg" in
    --yes|-y) ASSUME_YES=1 ;;
    --minimal) WITH_EXTRAS="" ;;
    --help|-h)
      sed -n '2,25p' "$0" 2>/dev/null || echo "proofmark installer"
      exit 0
      ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

# Refuse to run unread from a pipe.
if [ ! -t 0 ] && [ "$ASSUME_YES" -eq 0 ]; then
  cat >&2 <<'MSG'
This installer is being piped into a shell, so you have not read it.

Download it, read it, then run it:

  curl -fsSL https://raw.githubusercontent.com/coreyhiggins/proofmark/main/install.sh -o install.sh
  less install.sh
  sh install.sh

If you genuinely want to skip that, pass --yes:

  curl -fsSL .../install.sh | sh -s -- --yes
MSG
  exit 1
fi

say() { printf '  %s\n' "$1"; }

echo
echo "proofmark installer"
echo

# ------------------------------------------------------------------- uv ----

if command -v uv >/dev/null 2>&1; then
  say "uv is already installed"
else
  say "installing uv (isolated Python tool manager, from astral.sh)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # uv installs to ~/.local/bin, which may not be on PATH in this shell yet.
  for candidate in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
    [ -d "$candidate" ] && PATH="$candidate:$PATH"
  done
  export PATH
fi

if ! command -v uv >/dev/null 2>&1; then
  echo >&2
  echo "uv installed but is not on PATH in this shell." >&2
  echo "Add this to your shell profile, then run this script again:" >&2
  echo >&2
  echo '  export PATH="$HOME/.local/bin:$PATH"' >&2
  exit 1
fi

# ------------------------------------------------------------ proofmark ----

if [ -n "$WITH_EXTRAS" ]; then
  say "installing proofmark[$WITH_EXTRAS] with its own Python"
  uv tool install --python 3.12 --force "proofmark[$WITH_EXTRAS] @ git+https://github.com/$REPO"
else
  say "installing proofmark (core only, no dependencies)"
  uv tool install --python 3.12 --force "proofmark @ git+https://github.com/$REPO"
fi

# --------------------------------------------------------------- verify ----

if ! command -v proofmark >/dev/null 2>&1; then
  PATH="$HOME/.local/bin:$PATH"
  export PATH
fi

if command -v proofmark >/dev/null 2>&1; then
  echo
  say "installed: $(command -v proofmark)"
  echo
  echo "  Start it with:"
  echo
  echo "      proofmark gui"
  echo
  echo "  That opens a page in your browser. Everything stays on this machine."
  echo
else
  echo
  echo "Installed, but proofmark is not on PATH in this shell." >&2
  echo "Add this to your shell profile and open a new terminal:" >&2
  echo >&2
  echo '  export PATH="$HOME/.local/bin:$PATH"' >&2
  exit 1
fi
