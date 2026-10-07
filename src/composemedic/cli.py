"""ComposeMedic CLI."""

import argparse
import json
import os
from pathlib import Path
import sys

from . import __version__
from .checks import analyze, selected_document
from .docker import compose_prefix, live_checks, resolve
from .loader import InputError, expand_values, read_document, read_env
from .model import Report


def parser():
    p = argparse.ArgumentParser(description="Find Docker Compose problems without changing the stack.")
    p.add_argument("--version", action="version", version=f"ComposeMedic {__version__}")
    p.add_argument("-f", "--file", action="append", dest="files", help="Compose file (repeat with --resolve for overrides)")
    p.add_argument("--project-directory", type=Path, help="Base directory for relative paths and default .env")
    p.add_argument("--env-file", action="append", default=[], help="Interpolation dotenv file (repeat to layer files)")
    p.add_argument("--profile", action="append", default=[], help="Active profile; use '*' for all profiles")
    p.add_argument("-p", "--project-name", help="Compose project name used by --live")
    p.add_argument("--resolve", action="store_true", help="Use Docker Compose v2 to resolve merges and interpolation")
    p.add_argument("--live", action="store_true", help="Also query container status (implies --resolve)")
    p.add_argument("--format", choices=["text", "json"], default="text", help="Report format")
    p.add_argument("--fail-on", choices=["error", "warning", "never"], default="error", help="Findings that return exit code 1")
    return p


def discover_file(cwd: Path) -> Path:
    for name in ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml"):
        path = cwd / name
        if path.is_file():
            return path
    raise InputError("No Compose file found in the current directory. Use -f to select a file.")


def scan(args) -> Report:
    files = [Path(p).resolve() for p in args.files] if args.files else [discover_file(Path.cwd()).resolve()]
    if any(not path.is_file() for path in files):
        raise InputError("A selected Compose file does not exist or is not a file.")
    base = (args.project_directory or files[0].parent).resolve()
    if not base.is_dir():
        raise InputError("The project directory does not exist.")
    env_files = [Path(p).resolve() for p in args.env_file]
    profiles = set(args.profile)
    if not profiles:
        profiles.update(p.strip() for p in os.environ.get("COMPOSE_PROFILES", "").split(",") if p.strip())
    use_docker = args.resolve or args.live
    report = Report(mode="live" if args.live else "resolved" if use_docker else "offline")
    if not use_docker:
        if len(files) != 1:
            raise InputError("Multiple Compose files require --resolve; offline mode does not merge overrides.")
        doc = read_document(files[0])
        raw_services = doc.get("services")
        if "include" in doc or (isinstance(raw_services, dict) and any(isinstance(s, dict) and "extends" in s for s in raw_services.values())):
            raise InputError("include and extends require --resolve for Docker's canonical model.")
        doc = selected_document(doc, profiles)
        env = {}
        if not env_files and (base / ".env").is_file():
            env_files = [base / ".env"]
        for path in env_files:
            env.update(read_env(path))
        env.update(os.environ)
        doc = expand_values(doc, env, report)
        report.limitations.append("Offline mode checks one Compose file with basic dotenv literals. It is not a complete Compose validator; use --resolve for canonical merges, advanced .env syntax, include, and extends.")
    else:
        prefix = compose_prefix(files, base, env_files, profiles, args.project_name)
        doc = selected_document(resolve(prefix, base), profiles)
    analyze(doc, base, report)
    report.limitations.append("Bind paths are checked on this machine, not a remote Docker host. Missing paths may be intentional when Docker creates directories.")
    if args.live:
        live_checks(prefix, base, doc, report)
    else:
        report.limitations.append("Container status and host port occupancy are not checked. Use --live for current-project container status.")
    return report


def render_text(report: Report) -> str:
    data = report.to_dict()
    summary = data["summary"]
    lines = [f"ComposeMedic {__version__} | {report.mode} | {report.services_checked} active services", "",
             f"{summary['error']} errors, {summary['warning']} warnings, {summary['info']} notes", ""]
    for finding in data["findings"]:
        lines.extend([f"[{finding['severity'].upper()}] {finding['code']} | {finding['service']}",
                      f"  {finding['field']}", f"  {finding['message']}", f"  Next: {finding['suggestion']}", ""])
    if not data["findings"]:
        lines.extend(["No findings in the checks performed. This does not prove the stack will start.", ""])
    lines.append("Scope:")
    lines.extend(f"  - {item}" for item in report.limitations)
    lines.append("Read-only: no containers or configuration were changed.")
    return "\n".join(lines)


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        report = scan(args)
    except (InputError, RecursionError) as error:
        message = str(error) if isinstance(error, InputError) else "Input nesting is too deep."
        if args.format == "json":
            print(json.dumps({"schema_version": 1, "tool": "composemedic", "error": {"code": "SCAN_FAILED", "message": message}}, indent=2))
        else:
            print(f"ComposeMedic: {message}", file=sys.stderr)
        return 2
    except (TypeError, ValueError, KeyError, AttributeError):
        message = "Unsupported configuration structure. Validate it with Docker Compose; input values are omitted."
        if args.format == "json":
            print(json.dumps({"schema_version": 1, "tool": "composemedic", "error": {"code": "SCAN_FAILED", "message": message}}, indent=2))
        else:
            print(f"ComposeMedic: {message}", file=sys.stderr)
        return 2
    print(json.dumps(report.to_dict(), indent=2) if args.format == "json" else render_text(report))
    severities = {finding.severity for finding in report.findings}
    return int(args.fail_on != "never" and ("error" in severities or (args.fail_on == "warning" and "warning" in severities)))
