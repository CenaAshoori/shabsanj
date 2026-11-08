"""Manage ShabSanj's recurring local ticket refresh on macOS."""

import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys


LABEL = "local.shabsanj.ticket-refresh"
HOURS = (0, 6, 12, 18)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "status", "remove"))
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("This local scheduler uses macOS launchd.")

    root = Path(__file__).resolve().parents[1]
    plist = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{LABEL}"
    launchctl = "/bin/launchctl"

    def unload() -> None:
        loaded = subprocess.run([launchctl, "print", target], capture_output=True)
        if loaded.returncode == 0:
            subprocess.run([launchctl, "bootout", target], check=True)

    if args.action == "status":
        raise SystemExit(subprocess.run([launchctl, "print", target]).returncode)
    if args.action == "remove":
        unload()
        plist.unlink(missing_ok=True)
        return

    log_dir = Path.home() / "Library" / "Logs" / "ShabSanj"
    log_dir.mkdir(parents=True, exist_ok=True)
    plist.parent.mkdir(parents=True, exist_ok=True)
    unload()
    config = {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-m", "backend.crawl_tickets", "--quiet"],
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        "StartCalendarInterval": [{"Hour": hour, "Minute": 0} for hour in HOURS],
        "StandardOutPath": str(log_dir / "ticket-refresh.log"),
        "StandardErrorPath": str(log_dir / "ticket-refresh-errors.log"),
    }
    plist.write_bytes(plistlib.dumps(config))
    subprocess.run([launchctl, "bootstrap", domain, str(plist)], check=True)
    print(f"Ticket refresh installed at six-hour intervals. Logs: {log_dir}")


if __name__ == "__main__":
    main()
