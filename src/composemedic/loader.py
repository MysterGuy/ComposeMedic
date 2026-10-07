"""Safe YAML loading and limited offline interpolation (values never reported)."""

from pathlib import Path
import re
import yaml


class InputError(ValueError):
    """User-facing errors must not echo input content, environment, or stderr."""


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    # Let YAML merge keys provide defaults, but reject explicit duplicate keys.
    explicit = set()
    for key_node, _ in node.value:
        if key_node.tag == "tag:yaml.org,2002:merge":
            continue
        key = loader.construct_object(key_node, deep=deep)
        try:
            if key in explicit:
                raise InputError(f"Duplicate YAML key at line {key_node.start_mark.line + 1}.")
            explicit.add(key)
        except TypeError:
            raise InputError("Compose mapping keys must be scalar values.") from None
    loader.flatten_mapping(node)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def read_document(path: Path) -> dict:
    try:
        if path.stat().st_size > 2_000_000:
            raise InputError("Compose files larger than 2 MB are not supported.")
        content = path.read_text(encoding="utf-8-sig")
        # Bound alias expansion/recursion rather than trusting arbitrary YAML.
        tokens = list(yaml.scan(content))
        if sum(isinstance(t, yaml.tokens.AliasToken) for t in tokens) > 100:
            raise InputError("Too many YAML aliases (maximum 100).")
        result = yaml.load(content, Loader=UniqueLoader)
    except InputError:
        raise
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        location = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        raise InputError(f"Invalid YAML{location}. Input values are omitted.") from None
    except (OSError, UnicodeError):
        raise InputError("Cannot read the Compose file as UTF-8.") from None
    if not isinstance(result, dict):
        raise InputError("A Compose file must contain a mapping with a services section.")
    return result


def read_env(path: Path) -> dict[str, str]:
    """Basic dotenv literals; advanced quoting/interpolation requires --resolve."""
    try:
        content = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        raise InputError("Cannot read the environment file as UTF-8.") from None
    env = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if not match:
            continue
        key, value = match.groups()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        env[key] = value
    return env


def interpolate(text: str, env: dict[str, str], missing: set[str], depth: int = 0) -> str:
    if depth > 20:
        raise InputError("Interpolation nesting exceeds 20 levels.")
    out, i = [], 0
    while i < len(text):
        if text[i] != "$":
            out.append(text[i]); i += 1; continue
        if text[i:i+2] == "$$":
            out.append("$"); i += 2; continue
        if text[i:i+2] == "${":
            j, balance = i + 2, 1
            while j < len(text) and balance:
                if text[j:j+2] == "${":
                    balance += 1; j += 2; continue
                if text[j] == "}":
                    balance -= 1
                j += 1
            if balance:
                raise InputError("An interpolation expression has an unclosed brace.")
            expr = text[i+2:j-1]
            match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)(?:(:-|:\?|:\+|-|\?|\+)(.*))?", expr, re.S)
            if not match:
                raise InputError("Unsupported interpolation syntax. Use --resolve for Docker's parser.")
            key, operator, fallback = match.groups()
            i = j
        else:
            match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", text[i+1:])
            if not match:
                out.append("$"); i += 1; continue
            key, operator, fallback = match[0], None, None
            i += len(key) + 1
        present = key in env
        nonempty = present and env[key] != ""
        active = nonempty if operator and operator.startswith(":") else present
        if operator in (":-", "-"):
            value = env[key] if active else interpolate(fallback, env, missing, depth + 1)
        elif operator in (":+", "+"):
            value = interpolate(fallback, env, missing, depth + 1) if active else ""
        elif operator in (":?", "?"):
            if not active:
                missing.add(key)
            value = env.get(key, "")
        else:
            if not present:
                missing.add(key)
            value = env.get(key, "")
        out.append(value)
    return "".join(out)


def expand_values(value, env, report, service="project", path="", ancestors=None, depth=0):
    if depth > 60:
        raise InputError("Compose nesting exceeds 60 levels.")
    ancestors = set() if ancestors is None else ancestors
    if isinstance(value, str):
        missing = set()
        result = interpolate(value, env, missing)
        for key in sorted(missing):
            report.add("ENV_UNSET", "error", service, path,
                       f"Interpolation variable {key} is missing or required to be non-empty.",
                       "Set it in the shell or interpolation .env file, or add a default.")
        return result
    if isinstance(value, (dict, list)):
        if id(value) in ancestors:
            raise InputError("Recursive YAML aliases are not supported.")
        branch = ancestors | {id(value)}
        if isinstance(value, list):
            return [expand_values(v, env, report, service, f"{path}[{i}]", branch, depth+1) for i, v in enumerate(value)]
        result = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise InputError("Compose mapping keys must be strings.")
            result[key] = expand_values(child, env, report, key if path == "services" else service,
                                        f"{path}.{key}".lstrip("."), branch, depth+1)
        return result
    return value
