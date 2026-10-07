# ComposeMedic

**Find the problem before changing your Docker Compose stack.**

ComposeMedic is a small, read-only CLI for the moment when a Compose stack refuses to start, an update breaks a service, or two containers want the same port.

It points to the affected field, explains the finding, and suggests the next check. It does not restart containers, edit files, read application logs, or upload configuration.

> **Early release: v0.1.0.** Useful checks, explicit limits. No findings means no problems found by these checks—not a guarantee that the stack works.

## Try it

Requires Python 3.10+. Offline scans do not require Docker.

```sh
git clone https://github.com/MysterGuy/ComposeMedic.git
cd ComposeMedic
python -m pip install .
composemedic -f examples/broken/compose.yaml
```

Or install directly from this repository:

```sh
pipx install git+https://github.com/MysterGuy/ComposeMedic.git
```

The project is not published on PyPI yet; `pip install composemedic` is not an installation route for this release.

## A report you can act on

```text
[ERROR] PORT_COLLISION | proxy
  services.proxy.ports[0]
  Host port range overlaps an active mapping in service web.
  Next: Use different published ports or non-overlapping host addresses.

[WARNING] BIND_SOURCE_MISSING | web
  services.web.volumes[0]
  The source path does not exist on this machine.
  Next: Create the intended source or correct the mount. Confirm it on the Docker host.
```

The original Compose file remains unchanged. Environment values and raw Docker output are omitted from reports.

## Scan your stack

```sh
# One local file; no Docker calls
composemedic -f compose.yaml

# JSON for scripts and CI
composemedic -f compose.yaml --format json --fail-on warning

# Docker's canonical model: overrides, include, extends, and interpolation
composemedic -f compose.yaml -f compose.production.yaml --resolve

# Current container status; also resolves the configuration
composemedic -f compose.yaml --live

# Explicit environment file, profile, and project name
composemedic -f compose.yaml --env-file .env.production --profile workers --live -p my-stack
```

Docker-backed modes require Docker Compose v2. `--resolve` runs `docker compose config --format json`; `--live` additionally runs `docker compose ps --all --format json`. No lifecycle command is issued.

Without `-f`, ComposeMedic searches only the current directory for `compose.yaml`, `compose.yml`, `docker-compose.yaml`, or `docker-compose.yml`, in that order. It does not automatically load override files. Select them explicitly with `-f` and `--resolve`.

## What it checks

| Area | Checks |
| --- | --- |
| Ports | Collisions between active services, overlapping allocation pools, invalid mappings, host networking conflicts |
| Mounts | Missing bind sources, undeclared named volumes, duplicate targets, invalid targets |
| Environment | Missing interpolation variables, required variables that are empty, missing required service env files |
| Dependencies | Missing or inactive services, dependency cycles, unverified healthcheck requirements |
| Configuration | Missing image/build, missing local build context, duplicate container names, undeclared networks/configs/secrets |
| Updates | Implicit or explicit `latest` image tags |
| Runtime | Restarting, dead, paused, created, failed/exited, unhealthy, or missing current-project containers |

Inactive profiles are skipped by default. Use `--profile debug` to enable one, or `--profile '*'` to check all. A collision found with all profiles enabled may not apply when those profiles are deployed separately.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Scan completed and no findings meet the failure threshold |
| `1` | Findings meet `--fail-on` (default: `error`) |
| `2` | Scan could not complete: input, configuration resolution, or Docker access failed |

Use `--fail-on warning` to fail on warnings and errors. `--fail-on never` still returns `2` if the scan cannot complete. JSON operational failures have an `error` object instead of a normal `findings` report.

## Privacy and read-only behavior

- All processing happens locally. There is no telemetry, analytics, AI API, or outbound HTTP client.
- Reports contain rule codes, service names, field locations, explanations, and suggestions. They do not include environment values, image values, mount paths, container commands, raw YAML, application logs, or raw Docker stderr.
- The input `.env` and canonical Docker configuration are read in memory when needed. They are never saved by ComposeMedic.
- Docker commands use an argument list with `shell=False`, a timeout, and no lifecycle actions. Docker may use the daemon configured in your existing context.
- Service names and variable names remain visible. Review a report before sharing it if these identifiers are sensitive.

## Limits worth knowing

- Offline mode is a targeted diagnostic tool, not a complete implementation of the Compose specification. It reads one file, YAML anchors, basic `.env` literals, nested `${...}` operators, and escaped `$$`. For advanced dotenv quoting/interpolation or merged projects, use `--resolve`.
- Shell variables override the interpolation `.env`. Service `env_file` values are container environment, not interpolation variables.
- File existence is checked on the machine running ComposeMedic. It cannot establish filesystem availability or permissions on a remote Docker host.
- Missing short-syntax bind paths are warnings: Docker can intentionally create these directories. Long syntax with `create_host_path: false` makes a missing source an error.
- A healthcheck can come from an image. A missing Compose healthcheck is a warning to verify it, not proof that no healthcheck exists.
- Published-port collisions are checked within the active configuration. Host processes, other Compose projects, Swarm scheduling, and cross-family IPv4/IPv6 wildcard behavior are not checked in v0.1.
- Runtime status is a snapshot. It does not prove a historical restart loop or explain the underlying failure.
- The scanner bounds input size, nesting, and aliases, but does not promise to safely analyze arbitrary hostile Compose files.

## Contribute a diagnostic

Good contributions begin with a reproducible configuration and an expected finding. Each rule needs a stable code, a field location, an actionable suggestion, and a test for a similar configuration that should **not** trigger it.

See [CONTRIBUTING.md](CONTRIBUTING.md), [the rule catalog](docs/rules.md), and [SECURITY.md](SECURITY.md). Bug reports and small, focused pull requests are welcome.

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
```

## Next candidates

These are proposed directions, not implemented features:

- Ports owned by other projects and host processes.
- Application-specific checks for reverse proxies and common self-hosted services.
- A redacted report format suitable for GitHub issue attachments.

## License

MIT. See [LICENSE](LICENSE).

Built with AI assistance; behavior is covered by automated tests. Contributions are reviewed against reproducible cases.
