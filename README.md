# ComposeMedic

**Find Docker Compose problems before changing your stack.**

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Version](https://img.shields.io/badge/version-0.1.0-orange)
![License](https://img.shields.io/badge/license-MIT-green)
![Docker Compose](https://img.shields.io/badge/Docker%20Compose-v2-2496ED)

ComposeMedic is a small, local-first, read-only CLI for diagnosing Docker Compose projects.

It analyzes Compose configuration and, when requested, the current state of the project's containers.

ComposeMedic is designed to answer four questions:

1. **What is wrong?**
2. **Where is the problem?**
3. **Why does it matter?**
4. **What should you check next?**

It can detect problems such as:

- port collisions;
- undeclared named volumes;
- missing bind mount sources;
- missing environment variables;
- missing or inactive dependencies;
- dependency cycles;
- missing build contexts;
- duplicate container names;
- undeclared networks, configs, and secrets;
- unpinned image tags;
- unhealthy, restarting, exited, paused, or missing containers.

> **Current release: v0.1.0**
>
> A clean report means that no implemented ComposeMedic rule found a problem.
> It does **not** guarantee that the stack or application works correctly.

---

# Read-only by design

ComposeMedic is a diagnostic tool.

It does **not** modify your Compose project.

It does not:

- edit Compose files;
- edit `.env` files;
- automatically fix findings;
- start containers;
- stop containers;
- restart containers;
- remove containers;
- remove volumes;
- remove networks;
- rebuild images;
- pull images;
- read application logs;
- upload your configuration.

Docker-backed modes only read configuration and container status information.

---

# Requirements

- Python 3.10+
- Docker Compose v2 only when using `--resolve` or `--live`

Offline scans do not require Docker.

---

# Installation

Clone the repository:

```sh
git clone https://github.com/MysterGuy/ComposeMedic.git
cd ComposeMedic
```

Install:

```sh
python -m pip install .
```

For development:

```sh
python -m pip install -e .
```

You can also install directly with `pipx`:

```sh
pipx install git+https://github.com/MysterGuy/ComposeMedic.git
```

ComposeMedic v0.1.0 is not currently published on PyPI.

---

# Quick start

Run the included intentionally broken example:

```sh
composemedic -f examples/broken/compose.yaml
```

Example output:

```text
ComposeMedic 0.1.0 | offline | 3 active services

2 errors, 3 warnings, 0 notes

[ERROR] VOLUME_UNDECLARED | database
  services.database.volumes[0]

  A named volume has no top-level declaration.

  Next: Declare it in the top-level volumes section, including external volumes.


[ERROR] PORT_COLLISION | proxy
  services.proxy.ports[0]

  Host port range overlaps an active mapping in service web.

  Next: Use different published ports or non-overlapping host addresses.


[WARNING] BIND_SOURCE_MISSING | web
  services.web.volumes[0]

  The source path does not exist on this machine.

  Next: Create the intended source or correct the mount.
  Confirm it on the Docker host.


[WARNING] DEPENDENCY_HEALTH_UNVERIFIED | web
  services.web.depends_on.database

  A healthy dependency is required, but no active Compose healthcheck is defined.

  Next: Define a healthcheck or verify that the dependency image provides one.


[WARNING] IMAGE_UNPINNED | web
  services.web.image

  The image uses an implicit or explicit latest tag.

  Next: Pin a version or digest to make updates and recovery predictable.
```

Each finding includes:

- severity;
- rule code;
- affected service;
- exact configuration location;
- explanation;
- suggested next step.

---

# Basic usage

Analyze a Compose file:

```sh
composemedic -f compose.yaml
```

Or:

```sh
composemedic -f docker-compose.yml
```

If `-f` is not provided, ComposeMedic searches the current directory in this order:

```text
compose.yaml
compose.yml
docker-compose.yaml
docker-compose.yml
```

So this is also valid:

```sh
composemedic
```

ComposeMedic does not automatically load arbitrary override files.

---

# Analysis modes

ComposeMedic has three main modes:

```text
Offline
Resolve
Live
```

They are intended for different levels of inspection.

---

## Offline mode

```sh
composemedic -f compose.yaml
```

Offline mode is the default.

It analyzes the Compose configuration without calling Docker.

Use it for:

- quick configuration checks;
- development;
- code review;
- CI;
- pre-deployment validation.

It can inspect configuration relationships such as ports, mounts, environment variables, dependencies, resources, and image tags.

Offline mode is intentionally not a complete implementation of the Docker Compose specification.

---

## Resolve mode

```sh
composemedic -f compose.yaml --resolve
```

Resolve mode asks Docker Compose to produce the canonical configuration first.

ComposeMedic uses:

```sh
docker compose config --format json
```

This is useful when your project uses:

- multiple Compose files;
- overrides;
- interpolation;
- profiles;
- `extends`;
- `include`;
- more complex Compose behavior.

Example:

```sh
composemedic \
  -f compose.yaml \
  -f compose.production.yaml \
  --resolve
```

Docker Compose v2 is required.

---

## Live mode

```sh
composemedic -f compose.yaml --live
```

Live mode analyzes the resolved configuration and also checks the current state of project containers.

It can identify states such as:

```text
restarting
exited
failed
unhealthy
paused
dead
created
missing
```

ComposeMedic uses runtime information from:

```sh
docker compose ps --all --format json
```

Live mode does **not** change container state.

Docker Compose v2 and access to the configured Docker daemon are required.

---

# Recommended workflow

Start with an offline scan:

```sh
composemedic -f compose.yaml
```

If the project relies on advanced Compose behavior:

```sh
composemedic -f compose.yaml --resolve
```

If the stack is already running:

```sh
composemedic -f compose.yaml --live
```

Typical flow:

```text
Compose configuration
        |
        v
   Offline scan
        |
        v
   Resolve mode
        |
        v
    Live mode
```

You do not need to use all three modes every time.

---

# What ComposeMedic checks

| Area | Checks |
| --- | --- |
| Ports | Collisions between active services, overlapping allocation ranges, invalid mappings, host networking conflicts |
| Mounts | Missing bind sources, duplicate targets, invalid targets |
| Volumes | Undeclared named volumes |
| Environment | Missing interpolation variables, empty required variables, missing required service env files |
| Dependencies | Missing services, inactive services, dependency cycles, health requirements |
| Configuration | Missing image/build, missing local build context, duplicate container names |
| Networks | Undeclared network references |
| Configs | Undeclared config references |
| Secrets | Undeclared secret references |
| Images | Implicit or explicit `latest` tags |
| Runtime | Restarting, dead, paused, created, exited, failed, unhealthy, or missing containers |

---

# Severity levels

ComposeMedic reports findings as:

```text
ERROR
WARNING
NOTE
```

## ERROR

A configuration problem that is likely to prevent the intended stack from working correctly.

Example:

```text
[ERROR] PORT_COLLISION
```

## WARNING

A suspicious or potentially risky configuration that may still be intentional.

Example:

```text
[WARNING] IMAGE_UNPINNED
```

## NOTE

Lower-priority diagnostic information.

---

# Multiple Compose files

Use multiple `-f` arguments:

```sh
composemedic \
  -f compose.yaml \
  -f compose.production.yaml \
  --resolve
```

Using `--resolve` is recommended when combining multiple Compose files because Docker Compose performs the canonical merge.

---

# Environment files

Specify an environment file:

```sh
composemedic \
  -f compose.yaml \
  --env-file .env.production
```

With Docker resolution:

```sh
composemedic \
  -f compose.yaml \
  --env-file .env.production \
  --resolve
```

Shell environment variables take precedence over interpolation values from `.env`.

Service-level `env_file` values represent container environment variables and are not the same as Compose interpolation variables.

---

# Profiles

Enable one profile:

```sh
composemedic \
  -f compose.yaml \
  --profile workers
```

Example with another profile:

```sh
composemedic \
  -f compose.yaml \
  --profile debug
```

Enable all profiles:

```sh
composemedic \
  -f compose.yaml \
  --profile '*'
```

Inactive profile services are skipped by default.

When all profiles are enabled, ComposeMedic may report conflicts between services that are not normally intended to run together.

---

# Project name

Set an explicit Compose project name:

```sh
composemedic \
  -f compose.yaml \
  -p my-stack
```

This is particularly useful with live mode:

```sh
composemedic \
  -f compose.yaml \
  --live \
  -p my-stack
```

---

# Combining options

Example:

```sh
composemedic \
  -f compose.yaml \
  --env-file .env.production \
  --profile workers \
  --live \
  -p my-stack
```

Another example:

```sh
composemedic \
  -f compose.yaml \
  -f compose.production.yaml \
  --env-file .env.production \
  --profile production \
  --resolve \
  -p production-stack
```

---

# JSON output

Use JSON output for scripts and CI:

```sh
composemedic \
  -f compose.yaml \
  --format json
```

Example with a failure threshold:

```sh
composemedic \
  -f compose.yaml \
  --format json \
  --fail-on warning
```

JSON output can be useful for:

- CI systems;
- automation;
- editor integrations;
- external reporting tools.

---

# Failure thresholds

The default failure threshold is:

```text
error
```

This means warnings alone normally do not produce a failing exit code.

Fail on warnings:

```sh
composemedic \
  -f compose.yaml \
  --fail-on warning
```

Do not fail because of diagnostic findings:

```sh
composemedic \
  -f compose.yaml \
  --fail-on never
```

Operational failures are still reported separately.

---

# Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Scan completed and no finding reached the configured failure threshold |
| `1` | One or more findings reached the configured failure threshold |
| `2` | ComposeMedic could not complete the scan |

Examples of conditions that can return `2` include:

- invalid Compose input;
- failed configuration resolution;
- Docker access failure in Docker-backed modes.

`--fail-on never` disables finding-based failure but does not turn operational errors into success.

---

# CI usage

ComposeMedic can be used as a pre-deployment check.

Example:

```sh
composemedic \
  -f compose.yaml \
  --format json \
  --fail-on warning
```

Typical flow:

```text
Commit
   |
   v
ComposeMedic
   |
   +---- acceptable report ----> continue
   |
   +---- failing findings -----> stop job
```

ComposeMedic complements tests and deployment validation.

It is not a replacement for application tests or integration tests.

---

# GitHub Actions example

```yaml
name: ComposeMedic

on:
  push:
  pull_request:

jobs:
  compose-check:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install ComposeMedic
        run: python -m pip install .

      - name: Scan Compose configuration
        run: composemedic -f compose.yaml --fail-on warning
```

A non-zero exit code causes the job to fail.

---

# Privacy

ComposeMedic is designed for local diagnostics.

It does not intentionally include:

- telemetry;
- analytics;
- AI API calls;
- configuration uploads;
- remote diagnostic storage.

Reports may contain:

- service names;
- variable names;
- rule codes;
- field locations;
- explanations;
- suggestions.

Reports intentionally avoid exposing:

- environment variable values;
- raw `.env` contents;
- raw Compose YAML;
- mount source values;
- image values;
- container commands;
- application logs;
- raw Docker stderr.

Service names and variable names may still be sensitive.

Review reports before sharing them publicly.

---

# Docker-backed behavior

Resolve mode may run:

```sh
docker compose config --format json
```

Live mode may additionally run:

```sh
docker compose ps --all --format json
```

ComposeMedic does **not** intentionally execute lifecycle commands such as:

```sh
docker compose up
docker compose down
docker compose start
docker compose stop
docker compose restart
docker compose rm
```

Docker commands are used only to obtain information required for diagnostics.

---

# Important limitations

ComposeMedic is a focused diagnostic tool.

It is not a complete replacement for Docker Compose validation.

---

## Offline mode

Offline mode supports targeted Compose analysis including:

- YAML anchors;
- basic `.env` literals;
- nested `${...}` operators;
- escaped `$$`;
- profiles;
- common service relationships.

For canonical Docker Compose interpretation, use:

```sh
composemedic -f compose.yaml --resolve
```

---

## Bind mounts

Bind source paths are checked on the machine running ComposeMedic.

If Docker uses a remote host, a local path check cannot prove that the same path exists on that host.

Missing short-syntax bind sources may also be intentional because Docker can create directories in some configurations.

---

## Healthchecks

A Docker image may define its own healthcheck.

Therefore:

```text
DEPENDENCY_HEALTH_UNVERIFIED
```

does not prove that no healthcheck exists.

It means ComposeMedic could not verify the required healthcheck from the active Compose configuration.

---

## Ports

ComposeMedic v0.1.0 focuses primarily on port conflicts inside the analyzed configuration.

It does not provide complete host-wide port detection for:

- unrelated Docker containers;
- other Compose projects;
- host applications;
- operating system processes;
- every IPv4/IPv6 wildcard interaction;
- Swarm scheduling.

---

## Runtime information

Live mode provides a snapshot.

A state such as:

```text
restarting
```

describes the current container state but does not explain the root cause.

ComposeMedic intentionally does not inspect application logs.

---

# Development

Install the repository in editable mode:

```sh
python -m pip install -e .
```

Run the included example:

```sh
composemedic -f examples/broken/compose.yaml
```

Run the tests:

```sh
python -m unittest discover -s tests -v
```

Because the package is installed in editable mode, source code changes can be tested without reinstalling ComposeMedic after every edit.

---

# Command reference

### Offline scan

```sh
composemedic -f compose.yaml
```

### Automatic file discovery

```sh
composemedic
```

### Resolve configuration

```sh
composemedic -f compose.yaml --resolve
```

### Live diagnostics

```sh
composemedic -f compose.yaml --live
```

### Multiple files

```sh
composemedic \
  -f compose.yaml \
  -f compose.production.yaml \
  --resolve
```

### Environment file

```sh
composemedic \
  -f compose.yaml \
  --env-file .env.production
```

### Profile

```sh
composemedic \
  -f compose.yaml \
  --profile workers
```

### All profiles

```sh
composemedic \
  -f compose.yaml \
  --profile '*'
```

### Project name

```sh
composemedic \
  -f compose.yaml \
  -p my-stack
```

### JSON output

```sh
composemedic \
  -f compose.yaml \
  --format json
```

### Fail on warnings

```sh
composemedic \
  -f compose.yaml \
  --fail-on warning
```

### Never fail because of findings

```sh
composemedic \
  -f compose.yaml \
  --fail-on never
```

### CI-friendly JSON report

```sh
composemedic \
  -f compose.yaml \
  --format json \
  --fail-on warning
```

### Full live example

```sh
composemedic \
  -f compose.yaml \
  --env-file .env.production \
  --profile workers \
  --live \
  -p my-stack
```

### Help

```sh
composemedic --help
```

### Run tests

```sh
python -m unittest discover -s tests -v
```

---

# Contributing

Contributions are welcome.

A diagnostic rule should normally include:

1. a reproducible Compose configuration;
2. a stable rule code;
3. the affected field location;
4. a clear explanation;
5. an actionable suggestion;
6. a test that triggers the rule;
7. a similar test that does **not** trigger it.

See:

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [Rule catalog](docs/rules.md)
- [SECURITY.md](SECURITY.md)

Bug reports, tests, documentation improvements, and focused pull requests are welcome.

---

# Roadmap

Possible future directions include:

- detecting ports used by other Compose projects;
- detecting ports used by host processes;
- richer runtime diagnostics;
- reverse proxy diagnostics;
- checks for common self-hosted applications;
- improved CI reporting;
- redacted reports suitable for GitHub issues;
- broader Compose specification coverage.

These are proposed directions, not implemented features.

---

# Project philosophy

ComposeMedic aims to remain:

### Read-only

Diagnostics should not unexpectedly modify a running stack.

### Actionable

Findings should explain both the problem and the next useful step.

### Predictable

Stable rule codes and exit codes make the tool useful for automation.

### Local-first

Compose configuration should not need to leave your machine just to be analyzed.

### Focused

ComposeMedic complements Docker Compose instead of replacing it.

---

# License

MIT.

See [LICENSE](LICENSE).
