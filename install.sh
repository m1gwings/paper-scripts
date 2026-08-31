cat > install.sh <<'EOF'
#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(
    cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1
    pwd
)"

echo "Installing personal scripts from:"
echo "    $SCRIPT_DIR"
echo

chmod +x \
    "$SCRIPT_DIR/paper" \
    "$SCRIPT_DIR/paper-init" \
    "$SCRIPT_DIR/install.sh"

EXPECTED_DIR="$HOME/.local/bin"

if [[ "$SCRIPT_DIR" != "$EXPECTED_DIR" ]]; then
    echo "WARNING:"
    echo
    echo "This repository is normally cloned directly into:"
    echo
    echo "    $EXPECTED_DIR"
    echo
    echo "Current location:"
    echo
    echo "    $SCRIPT_DIR"
    echo
fi

if [[ ":$PATH:" != *":$EXPECTED_DIR:"* ]]; then
    BASHRC="$HOME/.bashrc"
    PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'

    echo
    echo "$EXPECTED_DIR is not currently on PATH."

    if ! grep -Fqx "$PATH_LINE" "$BASHRC" 2>/dev/null; then
        echo
        echo "Adding the following line to $BASHRC:"
        echo
        echo "    $PATH_LINE"

        {
            echo
            echo "# Personal executable scripts"
            echo "$PATH_LINE"
        } >> "$BASHRC"
    fi

    echo
    echo "Reload your shell with:"
    echo
    echo "    source ~/.bashrc"
else
    echo "$EXPECTED_DIR is already on PATH. [OK]"
fi

echo
echo "Checking useful commands:"
echo

if command -v git >/dev/null 2>&1; then
    echo "  git      [OK]"
else
    echo "  git      [MISSING - required]"
fi

if command -v gh >/dev/null 2>&1; then
    echo "  gh       [OK]"
else
    echo "  gh       [MISSING - required by paper-init]"
fi

if command -v code >/dev/null 2>&1; then
    echo "  code     [OK]"
else
    echo "  code     [MISSING - optional, used by 'paper open']"
fi

if command -v latexmk >/dev/null 2>&1; then
    echo "  latexmk  [OK]"
else
    echo "  latexmk  [MISSING - optional, used by 'paper build']"
fi

echo
echo "Installation complete."
echo
echo "Try:"
echo
echo "    paper help"
echo "    paper examples"
EOF
