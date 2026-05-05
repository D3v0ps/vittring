#!/usr/bin/env python3
"""Verify required DNS records are in place before deployment.

Used by both bootstrap and the GitHub Actions deploy workflow as a
pre-flight gate so we don't issue Let's Encrypt certificates against a
mis-configured domain.
"""

from __future__ import annotations

import socket
import subprocess
import sys


REQUIRED_A_RECORDS = {
    "vittring.karimkhalil.se": "62.238.37.54",
}


def resolve_a(host: str) -> str | None:
    try:
        return socket.gethostbyname(host)
    except socket.gaierror:
        return None


def dig_txt(host: str) -> list[str]:
    try:
        result = subprocess.run(
            ["dig", "+short", "TXT", host], capture_output=True, text=True, check=False
        )
        return [
            line.strip().strip('"') for line in result.stdout.splitlines() if line.strip()
        ]
    except FileNotFoundError:
        return []


def main() -> int:
    failed = False
    for host, expected_ip in REQUIRED_A_RECORDS.items():
        actual = resolve_a(host)
        marker = "OK" if actual == expected_ip else "FAIL"
        print(f"[{marker}] A {host} → {actual} (expected {expected_ip})")
        if actual != expected_ip:
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
