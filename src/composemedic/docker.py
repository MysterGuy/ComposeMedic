"""Read-only, shell-free Docker commands. Never report raw output or stderr."""

import json
from pathlib import Path
import subprocess

from .loader import InputError


class DockerError(InputError):
    pass


def run_readonly(args: list[str], cwd: Path) -> str:
    if args[:2] != ["docker", "compose"] or not (args[-3:] == ["config", "--format", "json"] or args[-4:] == ["ps", "--all", "--format", "json"]):
        raise DockerError("Refusing a command outside the read-only Compose query allowlist.")
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=30,
                                check=False, shell=False)
    except FileNotFoundError:
        raise DockerError("Docker CLI was not found. Install Docker Compose v2 or run an offline scan.") from None
    except subprocess.TimeoutExpired:
        raise DockerError("The read-only Docker query timed out after 30 seconds.") from None
    except OSError:
        raise DockerError("Could not run the read-only Docker query.") from None
    if result.returncode:
        raise DockerError("Docker could not read this project. Check Compose v2, daemon access, and configuration with docker compose config. Raw stderr is omitted to protect secrets.")
    if len(result.stdout) > 20_000_000:
        raise DockerError("Docker output exceeds the 20 MB limit.")
    return result.stdout


def compose_prefix(files: list[Path], base: Path, env_files: list[Path], profiles: set[str], project: str | None):
    args = ["docker", "compose", "--project-directory", str(base)]
    for path in files:
        args.extend(["-f", str(path)])
    for path in env_files:
        args.extend(["--env-file", str(path)])
    for profile in sorted(profiles):
        args.extend(["--profile", profile])
    if project:
        args.extend(["--project-name", project])
    return args


def resolve(prefix: list[str], base: Path) -> dict:
    # config renders a model; no up, run, pull, build, exec, or writes are issued.
    output = run_readonly([*prefix, "config", "--format", "json"], base)
    try:
        doc = json.loads(output)
    except json.JSONDecodeError:
        raise DockerError("Docker returned invalid configuration JSON.") from None
    if not isinstance(doc, dict):
        raise DockerError("Docker returned an unexpected configuration model.")
    return doc


def parse_records(text: str) -> list[dict]:
    if not text.strip():
        return []
    try:
        if text.lstrip().startswith("["):
            records = json.loads(text)
        else:
            records = [json.loads(line) for line in text.splitlines() if line.strip()]
    except json.JSONDecodeError:
        raise DockerError("Docker returned invalid container status JSON.") from None
    if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
        raise DockerError("Docker returned unexpected container status records.")
    return records


def live_checks(prefix: list[str], base: Path, doc: dict, report) -> None:
    rows = parse_records(run_readonly([*prefix, "ps", "--all", "--format", "json"], base))
    seen = set()
    for row in rows:
        service = row.get("Service")
        if service not in doc["services"]:
            continue
        seen.add(service)
        field = f"services.{service}"
        state, health = row.get("State"), row.get("Health")
        if state in ("restarting", "dead", "removing"):
            report.add("CONTAINER_FAILED", "error", service, field, "A service container is restarting, dead, or being removed.", "Review its local logs and recent changes; ComposeMedic does not restart it.")
        elif state == "exited":
            exit_code = row.get("ExitCode", 0)
            report.add("CONTAINER_EXITED", "error" if exit_code not in (0, "0", None) else "info", service, field,
                       "A service container has exited with a failure." if exit_code not in (0, "0", None) else "A service container exited successfully; it may be a one-shot job.",
                       "Check whether this service should stay running or complete once.")
        elif state == "paused":
            report.add("CONTAINER_PAUSED", "warning", service, field, "A service container is paused.", "Confirm that pausing it was intentional.")
        elif state == "created":
            report.add("CONTAINER_NOT_STARTED", "warning", service, field, "A service container exists but has not started.", "Review the deployment state and dependency conditions.")
        if health == "unhealthy":
            report.add("CONTAINER_UNHEALTHY", "error", service, field + ".healthcheck", "A service container reports unhealthy.", "Review the healthcheck and application logs locally.")
    for service in sorted(set(doc["services"]) - seen):
        report.add("CONTAINER_NOT_FOUND", "info", service, f"services.{service}", "No container was found for this active service.", "This may be an undeployed service; verify the Compose project name.")
    report.limitations.append("Runtime status is a snapshot, not a restart-history analysis. Ports held by host processes or other projects are not checked.")
