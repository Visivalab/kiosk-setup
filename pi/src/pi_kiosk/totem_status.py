from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import SplitResult, urlsplit, urlunsplit

from pi_kiosk.host import TotemStatusReporterConfig

STATUS_PORT = 8080
STATUS_SCRIPT_PATH = Path("/usr/local/lib/pi-kiosk/totem-status.py")
STATUS_CONFIG_PATH = Path("/etc/pi-kiosk/totem-status.json")
STATUS_SERVICE_PATH = Path("/etc/systemd/system/pi-kiosk-totem-status.service")
STATUS_TIMER_PATH = Path("/etc/systemd/system/pi-kiosk-totem-status.timer")
STATUS_SERVICE_NAME = STATUS_SERVICE_PATH.name
STATUS_TIMER_NAME = STATUS_TIMER_PATH.name


def derive_status_url(register_url: str) -> str | None:
    parsed = urlsplit(register_url)
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return None
    parts = [*parts[:-1], "totem-status"]
    updated = SplitResult(
        scheme=parsed.scheme,
        netloc=parsed.netloc,
        path="/" + "/".join(parts),
        query="",
        fragment="",
    )
    return urlunsplit(updated)


def status_script_path() -> Path:
    return STATUS_SCRIPT_PATH


def status_config_path() -> Path:
    return STATUS_CONFIG_PATH


def status_service_path() -> Path:
    return STATUS_SERVICE_PATH


def status_timer_path() -> Path:
    return STATUS_TIMER_PATH


def reporter_config_json(config: TotemStatusReporterConfig) -> str:
    return json.dumps(
        {
            "endpointUrl": config.endpoint_url,
            "token": config.token,
            "totemId": config.totem_id,
            "totemType": config.totem_type,
            "desktopUser": config.desktop_user,
            "port": STATUS_PORT,
        },
        indent=2,
    ) + "\n"


def reporter_script() -> str:
    return """#!/usr/bin/env python3
from __future__ import annotations

import json
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, request

def _load_config(path: str) -> dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _labwc_running(user: str) -> bool:
    result = subprocess.run(
        ["ps", "-u", user, "-o", "comm="],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return False
    return any(line.strip() == "labwc" for line in result.stdout.splitlines())


def _port_listening(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sock.close()


def _facts(config: dict[str, object]) -> tuple[bool, bool]:
    user = str(config["desktopUser"])
    port = int(config.get("port", 8080))
    kiosk_running = _labwc_running(user)
    webapp_running = _port_listening(port)
    return kiosk_running, webapp_running


def _machine_name(config: dict[str, object]) -> str:
    value = socket.gethostname().strip()
    if value:
        return value
    return str(config["totemId"])


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: totem-status.py <config-path>", file=sys.stderr)
        return 1

    config = _load_config(argv[1])
    kiosk_running, webapp_running = _facts(config)
    payload = {
        "totem_id": config["totemId"],
        "totem_type": config["totemType"],
        "machineName": _machine_name(config),
        "checkedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "kiosk_running": kiosk_running,
        "webapp_running": webapp_running,
    }
    req = request.Request(
        str(config["endpointUrl"]),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config['token']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=5) as response:
            status = response.getcode()
    except error.HTTPError as exc:
        print(f"Totem status update failed with HTTP {exc.code}.", file=sys.stderr)
        return 1
    except error.URLError as exc:
        print(f"Totem status update failed: {exc.reason}.", file=sys.stderr)
        return 1

    if status < 200 or status >= 300:
        print(f"Totem status update failed with HTTP {status}.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
"""


def service_unit() -> str:
    return "\n".join(
        [
            "[Unit]",
            "Description=pi-kiosk hourly totem status reporter",
            "Wants=network-online.target",
            "After=network-online.target",
            "",
            "[Service]",
            "Type=oneshot",
            (
                f"ExecStart=/usr/bin/python3 {status_script_path()} "
                f"{status_config_path()}"
            ),
            "",
        ]
    )


def timer_unit() -> str:
    return "\n".join(
        [
            "[Unit]",
            "Description=Run pi-kiosk totem status reporter every hour",
            "",
            "[Timer]",
            "OnBootSec=5min",
            "OnUnitActiveSec=1h",
            "Persistent=true",
            "Unit=pi-kiosk-totem-status.service",
            "",
            "[Install]",
            "WantedBy=timers.target",
            "",
        ]
    )
