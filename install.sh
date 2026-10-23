#!/bin/zsh
# Kindle Tools installer for macOS. Safe to run again: finished steps are skipped.
#
#   1. checks for Homebrew and installs libmtp (the USB/MTP library)
#   2. checks for Python 3.10+
#   3. creates .venv in this folder and installs requirements.txt into it
#   4. optionally adds a `kindle` terminal command to ~/.zshrc
#
# Nothing is installed outside this folder except libmtp (via Homebrew).
set -e
DIR="${0:A:h}"

step() { print -P "%F{blue}==>%f %B$1%b"; }
note() { print "    $1"; }
fail() { print -P "%F{red}Error:%f $1"; exit 1; }

[[ "$(uname)" == Darwin ]] || fail "Kindle Tools runs on macOS only."

step "Homebrew"
command -v brew >/dev/null || fail "Homebrew is required. Install it from https://brew.sh, then run this script again."
note "found $(brew --prefix)"

step "libmtp"
if brew list libmtp >/dev/null 2>&1; then
  note "already installed ($(brew list --versions libmtp))"
else
  brew install libmtp
fi

step "Python 3.10+"
PY="$(command -v python3)" || fail "python3 not found. Install it with: brew install python"
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
  || fail "Python 3.10 or newer is required, found $("$PY" --version 2>&1). Install it with: brew install python"
note "$("$PY" --version) at $PY"

step "Virtual environment (.venv)"
if [[ ! -x "$DIR/.venv/bin/python" ]]; then
  "$PY" -m venv "$DIR/.venv"
  note "created"
else
  note "already exists"
fi
"$DIR/.venv/bin/pip" install --quiet --disable-pip-version-check -r "$DIR/requirements.txt"
note "packages from requirements.txt installed"
chmod +x "$DIR/kindle"

step "Terminal command (optional)"
RC="$HOME/.zshrc"
if grep -q "^alias kindle=" "$RC" 2>/dev/null; then
  note "'kindle' is already set up in $RC"
elif read -r "answer?    Add a 'kindle' command to $RC, to start Kindle Tools from any folder? [y/N] " && [[ "$answer" == [yY]* ]]; then
  print -r -- "" >> "$RC"
  print -r -- "# Kindle Tools" >> "$RC"
  print -r -- "alias kindle='\"$DIR/kindle\"'" >> "$RC"
  note "added. Open a new terminal window (or run: source ~/.zshrc)"
else
  note "skipped. Start Kindle Tools with ./kindle from this folder"
fi

print
print -P "%F{green}Done.%f Start Kindle Tools with %B./kindle%b (or %Bkindle%b if you added the command)."
