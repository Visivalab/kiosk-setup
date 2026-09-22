#!/usr/bin/env bash
# Pi entry point. From a checkout: sudo ./kiosk.sh
# From GitHub (repo must be public):
#   curl -fsSL https://raw.githubusercontent.com/Visivalab/kiosk-config/master/kiosk.sh | sudo bash
#
# The body lives in main() so a piped invocation can read the whole script
# before stdin is reattached to /dev/tty for the rotation prompt.
set -euo pipefail

ARCHIVE_URL="${PI_KIOSK_ARCHIVE_URL:-https://github.com/Visivalab/kiosk-config/archive/refs/heads/master.tar.gz}"

script_dir() {
  local src="${BASH_SOURCE[0]:-}"
  case "$src" in
    "" | "-" | "bash" | "/dev/stdin" | /dev/fd/* | /proc/self/fd/*)
      return 1
      ;;
  esac
  if [[ ! -f "$src" ]]; then
    return 1
  fi
  cd "$(dirname "$src")" && pwd
}

package_root() {
  local dir="$1"
  local child
  if [[ -d "$dir/pi/src/pi_kiosk" ]]; then
    printf '%s\n' "$dir/pi"
    return 0
  fi
  if [[ -d "$dir/src/pi_kiosk" ]]; then
    printf '%s\n' "$dir"
    return 0
  fi
  for child in "$dir"/* "$dir"/*/*; do
    if [[ -d "$child/src/pi_kiosk" ]]; then
      printf '%s\n' "$child"
      return 0
    fi
  done
  return 1
}

download() {
  local dest="$1" src="$ARCHIVE_URL"
  case "$src" in
    file://*)
      src="${src#file://}"
      ;;
  esac
  if [[ -f "$src" ]]; then
    cp "$src" "$dest"
    return 0
  fi
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$ARCHIVE_URL" -o "$dest"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$dest" "$ARCHIVE_URL"
  else
    echo "Need curl or wget to download pi-kiosk from GitHub." >&2
    return 1
  fi
}

fetch_tree() {
  local work tarball root
  work="$(mktemp -d)"
  tarball="$work/archive.tar.gz"
  if ! download "$tarball"; then
    echo "Failed to download $ARCHIVE_URL" >&2
    echo "If the repo is private, make it public or copy this folder to the Pi." >&2
    rm -rf "$work"
    return 1
  fi
  if ! tar -tzf "$tarball" >/dev/null 2>&1; then
    echo "Download was not a usable tar.gz (is the GitHub repo public?)." >&2
    rm -rf "$work"
    return 1
  fi
  tar -xzf "$tarball" -C "$work"
  rm -f "$tarball"
  if ! root="$(package_root "$work")"; then
    echo "Downloaded archive did not contain pi/src/pi_kiosk." >&2
    rm -rf "$work"
    return 1
  fi
  printf '%s\t%s\n' "$work" "$root"
}

attach_tty() {
  if [[ -t 0 ]]; then
    return 0
  fi
  # Probe first: `[[ -r /dev/tty ]]` can be true even when opening fails.
  if ! { : </dev/tty; } 2>/dev/null; then
    echo "WARN: no terminal detected; the rotation prompt may not work." >&2
    return 0
  fi
  return 10
}

run_wizard() {
  local root="$1" stdin_mode="${2:-inherit}"
  shift
  shift || true
  export PYTHONPATH="$root/src"
  if [[ "${EUID}" -ne 0 ]]; then
    if [[ "$stdin_mode" == "tty" ]]; then
      sudo PYTHONPATH="$PYTHONPATH" python3 -m pi_kiosk "$@" </dev/tty
    else
      sudo PYTHONPATH="$PYTHONPATH" python3 -m pi_kiosk "$@"
    fi
  elif [[ "$stdin_mode" == "tty" ]]; then
    python3 -m pi_kiosk "$@" </dev/tty
  else
    python3 -m pi_kiosk "$@"
  fi
}

main() {
  local root="" work="" status=0 here="" fetched="" stdin_mode="inherit"

  if here="$(script_dir)" && root="$(package_root "$here")"; then
    :
  else
    fetched="$(fetch_tree)"
    work="${fetched%%$'\t'*}"
    root="${fetched#*$'\t'}"
  fi

  if attach_tty; then
    :
  else
    status=$?
    if [[ "$status" -eq 10 ]]; then
      stdin_mode="tty"
      status=0
    fi
  fi
  run_wizard "$root" "$stdin_mode" "$@" || status=$?
  if [[ -n "$work" ]]; then
    rm -rf "$work"
  fi
  return "$status"
}

main "$@"
