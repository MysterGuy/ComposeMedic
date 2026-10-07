"""Configuration diagnostics. Findings expose field locations, never field values."""

from dataclasses import dataclass
import ipaddress
from pathlib import Path, PureWindowsPath
import re

from .loader import InputError
from .model import Report


@dataclass(frozen=True)
class Port:
    service: str
    field: str
    ip: str
    start: int
    end: int
    protocol: str
    flexible: bool = False


def port_range(value) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)(?:-(\d+))?", str(value))
    if not match:
        raise ValueError
    start, end = int(match[1]), int(match[2] or match[1])
    if not 1 <= start <= end <= 65535:
        raise ValueError
    return start, end


def parse_port(value, service: str, field: str) -> Port | None:
    flexible = False
    if isinstance(value, dict):
        protocol = value.get("protocol", "tcp")
        host_ip = str(value.get("host_ip") or "0.0.0.0").strip("[]")
        port_range(value.get("target"))
        published = value.get("published")
        if published is None or str(published) == "0":
            return None
        start, end = port_range(published)
        # Long syntax ranges are a pool from which Docker chooses one port.
        flexible = start != end
    elif isinstance(value, (str, int)) and not isinstance(value, bool):
        text = str(value)
        text, _, protocol = text.partition("/")
        protocol = protocol or "tcp"
        ipv6 = re.fullmatch(r"\[([^]]+)\]:(.*)", text)
        if ipv6:
            host_ip, text = ipv6.groups()
            parts = text.split(":")
            if len(parts) != 2:
                raise ValueError
            published, target = parts
        else:
            parts = text.split(":")
            if len(parts) == 1:
                port_range(parts[0]); return None
            if len(parts) == 2:
                host_ip, published, target = "0.0.0.0", *parts
            elif len(parts) == 3:
                host_ip, published, target = parts
                host_ip = host_ip or "0.0.0.0"
            else:
                raise ValueError
        target_range = port_range(target)
        if published in ("", "0"):
            return None
        start, end = port_range(published)
        if end - start != target_range[1] - target_range[0]:
            raise ValueError
    else:
        raise ValueError
    if protocol not in ("tcp", "udp", "sctp"):
        raise ValueError
    ipaddress.ip_address(host_ip)
    return Port(service, field, host_ip, start, end, protocol, flexible)


def ip_overlap(left: str, right: str) -> bool:
    a, b = ipaddress.ip_address(left), ipaddress.ip_address(right)
    # IPv6 wildcard behavior depends on the daemon/kernel; don't claim a collision.
    if a.version != b.version:
        return False
    return a == b or a.is_unspecified or b.is_unspecified


def ports_overlap(a: Port, b: Port) -> bool:
    return a.protocol == b.protocol and ip_overlap(a.ip, b.ip) and max(a.start, b.start) <= min(a.end, b.end)


def selected_document(doc: dict, profiles: set[str]) -> dict:
    services = doc.get("services")
    if not isinstance(services, dict) or not services:
        raise InputError("The services section must be a non-empty mapping.")
    if len(services) > 500:
        raise InputError("At most 500 services are supported.")
    selected = {}
    for name, service in services.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]+", name):
            raise InputError("Service names must use letters, numbers, dots, underscores, or hyphens.")
        if not isinstance(service, dict):
            raise InputError("Each service definition must be a mapping.")
        declared = service.get("profiles", [])
        if not isinstance(declared, list) or not all(isinstance(p, str) for p in declared):
            raise InputError("Service profiles must be a list of strings.")
        if not declared or "*" in profiles or profiles.intersection(declared):
            selected[name] = service
    return {**{k: v for k, v in doc.items() if not str(k).startswith("x-")}, "services": selected}


def local_path(source: str, base: Path) -> Path | None:
    if PureWindowsPath(source).is_absolute() and base.drive == "":
        return None  # Cross-OS paths cannot be checked on this machine.
    path = Path(source).expanduser()
    return path if path.is_absolute() else base / path


def inspect_path(source, base: Path, report: Report, service: str, field: str,
                 code="BIND_SOURCE_MISSING", strict=False):
    if not isinstance(source, str) or not source:
        report.add("MOUNT_INVALID", "error", service, field, "The mount source is empty or invalid.", "Set a valid source for this mount.")
        return
    path = local_path(source, base)
    if path is None:
        report.add("PATH_UNCHECKED", "info", service, field, "This path belongs to another operating system.", "Check the source path on the Docker host.")
        return
    try:
        exists = path.exists()
    except (OSError, ValueError):
        exists = False
    if not exists:
        report.add(code, "error" if strict else "warning", service, field,
                   "The source path does not exist on this machine.",
                   "Create the intended source or correct the mount. Confirm it on the Docker host.")


def parse_mount(value):
    if isinstance(value, dict):
        kind = value.get("type", "volume")
        return kind, value.get("source"), value.get("target"), bool(value.get("bind", {}).get("create_host_path") is False) if isinstance(value.get("bind"), dict) else False
    if not isinstance(value, str):
        raise ValueError
    # Preserve drive-letter colons in Windows host paths.
    match = re.match(r"^([A-Za-z]:[\\/][^:]*):(.*)$", value)
    if match:
        source, tail = match.groups(); parts = tail.split(":")
    else:
        parts = value.split(":")
        if len(parts) == 1:
            return "volume", None, parts[0], False
        source, parts = parts[0], parts[1:]
    if len(parts) not in (1, 2):
        raise ValueError
    target = parts[0]
    kind = "bind" if source.startswith((".", "/", "~", "\\")) or PureWindowsPath(source).is_absolute() else "volume"
    return kind, source, target, False


def analyze(doc: dict, base: Path, report: Report) -> list[Port]:
    services = doc["services"]
    report.services_checked = len(services)
    if not services:
        report.limitations.append("No services are active for the selected profiles.")
    definitions = {}
    for section in ("volumes", "networks", "secrets", "configs"):
        section_value = doc.get(section) or {}
        if not isinstance(section_value, dict):
            raise InputError(f"The {section} section must be a mapping.")
        definitions[section] = section_value
    ports, containers, graph = [], {}, {}
    for name, service in services.items():
        root = f"services.{name}"
        if not service.get("image") and not service.get("build"):
            report.add("IMAGE_OR_BUILD_MISSING", "error", name, root, "No image or build context is defined.", "Define an image or a build context for this service.")
        image = service.get("image")
        if isinstance(image, str) and "@" not in image and (":" not in image.rsplit("/", 1)[-1] or image.endswith(":latest")):
            report.add("IMAGE_UNPINNED", "warning", name, root + ".image", "The image uses an implicit or explicit latest tag.", "Pin a version or digest to make updates and recovery predictable.")
        container = service.get("container_name")
        if container:
            if not isinstance(container, str):
                raise InputError("container_name must be a string.")
            if container in containers:
                report.add("CONTAINER_NAME_COLLISION", "error", name, root + ".container_name", "Two active services request the same container name.", "Remove container_name or choose distinct names.")
            containers[container] = name
        items = service.get("ports") or []
        if not isinstance(items, list):
            raise InputError("Service ports must be a list.")
        if service.get("network_mode") == "host" and items:
            report.add("HOST_NETWORK_PORTS", "error", name, root + ".ports", "Published ports cannot be combined with host networking.", "Remove published ports or use bridge networking.")
        for index, value in enumerate(items):
            field = f"{root}.ports[{index}]"
            try:
                port = parse_port(value, name, field)
            except (ValueError, TypeError):
                report.add("PORT_INVALID", "error", name, field, "The published port definition is invalid or unsupported.", "Check IP address, protocol, port range, and quoted short syntax.")
                continue
            if not port:
                continue
            for previous in ports:
                if ports_overlap(previous, port):
                    if previous.flexible or port.flexible:
                        report.add("PORT_POOL_OVERLAP", "warning", name, field, "A published port pool overlaps another active mapping.", "Ensure the pool has enough free ports; allocation is decided by Docker.")
                    else:
                        report.add("PORT_COLLISION", "error", name, field, f"Host port range overlaps an active mapping in service {previous.service}.", "Use different published ports or non-overlapping host addresses.")
            ports.append(port)
        mounts = service.get("volumes") or []
        if not isinstance(mounts, list):
            raise InputError("Service volumes must be a list.")
        targets = set()
        for index, mount in enumerate(mounts):
            field = f"{root}.volumes[{index}]"
            try:
                kind, source, target, strict = parse_mount(mount)
                if not isinstance(target, str) or not target or (not target.startswith("/") and not PureWindowsPath(target).is_absolute()):
                    raise ValueError
            except (ValueError, TypeError, AttributeError):
                report.add("MOUNT_INVALID", "error", name, field, "The volume definition or target is invalid.", "Use an absolute container target and valid mount syntax.")
                continue
            if target in targets:
                report.add("MOUNT_TARGET_DUPLICATE", "error", name, field, "Multiple mounts use the same container target.", "Remove the duplicate mount or use a different target.")
            targets.add(target)
            if kind == "bind":
                inspect_path(source, base, report, name, field, strict=strict)
            elif kind == "volume" and source and source not in definitions["volumes"]:
                report.add("VOLUME_UNDECLARED", "error", name, field, "A named volume has no top-level declaration.", "Declare it in the top-level volumes section, including external volumes.")
            elif kind not in ("bind", "volume", "tmpfs", "image", "cluster", "npipe"):
                report.add("MOUNT_TYPE_UNCHECKED", "info", name, field, "This mount type is not checked by ComposeMedic.", "Validate this mount with Docker Compose.")
        env_files = service.get("env_file") or []
        if isinstance(env_files, (str, dict)):
            env_files = [env_files]
        if not isinstance(env_files, list):
            raise InputError("env_file must be a path or list of paths.")
        for index, item in enumerate(env_files):
            source = item.get("path") if isinstance(item, dict) else item
            required = item.get("required", True) if isinstance(item, dict) else True
            if required:
                inspect_path(source, base, report, name, f"{root}.env_file[{index}]", "ENV_FILE_MISSING", True)
        build = service.get("build")
        context = build.get("context", ".") if isinstance(build, dict) else build
        if isinstance(context, str) and context and not re.match(r"(?:[a-z]+://|git@|service:)", context):
            inspect_path(context, base, report, name, root + ".build.context", "BUILD_CONTEXT_MISSING", True)
        depends = service.get("depends_on") or {}
        if isinstance(depends, list):
            depends = {dep: {} for dep in depends}
        if not isinstance(depends, dict) or not all(isinstance(k, str) for k in depends):
            raise InputError("depends_on must be a list or mapping of service names.")
        graph[name] = []
        for dependency, settings in depends.items():
            path = f"{root}.depends_on.{dependency}"
            required = settings.get("required", True) if isinstance(settings, dict) else True
            if dependency not in services:
                report.add("DEPENDENCY_MISSING", "error" if required else "info", name, path, "A dependency is undefined or inactive in the selected profiles.", "Declare and enable the dependency, or make it optional where supported.")
                continue
            graph[name].append(dependency)
            condition = settings.get("condition", "service_started") if isinstance(settings, dict) else "service_started"
            health = services[dependency].get("healthcheck") or {}
            has_health = isinstance(health, dict) and health.get("test") and not health.get("disable") and health.get("test") != ["NONE"] and health.get("test") != "NONE"
            if condition == "service_healthy" and not has_health:
                # An image can define HEALTHCHECK; offline cannot prove absence.
                report.add("DEPENDENCY_HEALTH_UNVERIFIED", "warning", name, path, "A healthy dependency is required, but no active Compose healthcheck is defined.", "Define a healthcheck or verify that the dependency image provides one.")
        for section in ("networks", "secrets", "configs"):
            refs = service.get(section) or []
            if not isinstance(refs, (dict, list)):
                raise InputError(f"Service {section} must be a list or mapping.")
            for ref in refs:
                source = ref.get("source") if isinstance(ref, dict) else ref
                if not isinstance(source, str):
                    raise InputError(f"Invalid service {section} reference.")
                if source not in definitions[section] and not (section == "networks" and source == "default"):
                    report.add(f"{section.upper()}_UNDECLARED", "error", name, f"{root}.{section}", f"A referenced {section} entry has no top-level declaration.", f"Declare the referenced entry in the top-level {section} section.")
        if service.get("network_mode") and service.get("networks"):
            report.add("NETWORK_MODE_CONFLICT", "error", name, root + ".networks", "networks and network_mode are both defined.", "Use networks or network_mode, not both.")
    visited, visiting = set(), set()

    def visit(name):
        if name in visiting:
            report.add("DEPENDENCY_CYCLE", "error", name, f"services.{name}.depends_on", "The active dependency graph contains a cycle.", "Remove the circular startup dependency.")
            return
        if name in visited:
            return
        visiting.add(name)
        for dep in graph.get(name, []):
            visit(dep)
        visiting.remove(name); visited.add(name)

    for name in graph:
        visit(name)
    for section in ("configs", "secrets"):
        for item in definitions[section].values():
            if isinstance(item, dict) and item.get("file") and not item.get("external"):
                inspect_path(item["file"], base, report, "project", section + ".file", "RESOURCE_FILE_MISSING", True)
    return ports
