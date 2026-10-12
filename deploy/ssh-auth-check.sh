#!/usr/bin/env bash
# Read-only diagnosis for this project's ubuntu key. Never prints private keys/password hashes.
set -u
printf '== account and clock ==\n'
id -un
printf 'HOME=%s\n' "$HOME"
date -u '+UTC=%Y-%m-%d %H:%M:%S'
ubuntu_home=$(getent passwd ubuntu | cut -d: -f6)
printf 'ubuntu_home=%s\n' "$ubuntu_home"
printf '\n== ownership and modes ==\n'
stat -c '%U %G %a %n' "$ubuntu_home" "$ubuntu_home/.ssh" "$ubuntu_home/.ssh/authorized_keys" 2>&1
printf '\n== this project public entry only ==\n'
grep -nF 'medical-aesthetics-demo-2026-10-13' "$ubuntu_home/.ssh/authorized_keys" | cat -v || true
printf '\n== expected public fingerprint ==\n'
ssh-keygen -lf "$ubuntu_home/.ssh/authorized_keys" 2>/dev/null | grep -F 'SHA256:d0tytAMhPlNYLPwCliK6COt1KB6fa1fm5t6f2B6K4Pw' || true
printf '\n== ssh configuration and refusal metadata ==\n'
if sudo -n true 2>/dev/null; then
    sudo -n /usr/sbin/sshd -T 2>/dev/null | grep -E '^(pubkeyauthentication|authorizedkeysfile|strictmodes|pubkeyacceptedalgorithms) '
    sudo -n journalctl -u ssh --since '-10 minutes' --no-pager -o cat 2>/dev/null |
        grep -E 'Authentication refused|bad ownership|bad key options|expired|invalid key|Failed publickey for ubuntu' | tail -n 12
else
    printf 'Passwordless sudo unavailable; no privilege/configuration change attempted.\n'
fi
