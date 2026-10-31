#!/usr/bin/env bash
# Run as the ordinary station user. Administrative rights are requested later.
# The function is called only after this complete script has been received.
opt_station_install() (
    set -eu
    if [ "$(id -u)" -eq 0 ]; then
        printf '%s\n' 'Run this command as the ordinary Pi user, without sudo.' >&2
        exit 1
    fi
    for opt_command in python3 curl sudo; do
        if ! command -v "$opt_command" >/dev/null 2>&1; then
            printf 'Missing prerequisite: %s. Use Raspberry Pi OS 64-bit Trixie.\n' "$opt_command" >&2
            exit 1
        fi
    done
    opt_temporary=$(mktemp -d)
    trap 'rm -rf -- "$opt_temporary"' EXIT
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
        --tlsv1.2 --connect-timeout 15 --max-time 90 --max-filesize 131072 \
        https://raw.githubusercontent.com/Cyril-E/OPT-station/main/deploy/bootstrap.py \
        --output "$opt_temporary/bootstrap.py"
    python3 "$opt_temporary/bootstrap.py" "$@"
)
opt_station_install "$@"
