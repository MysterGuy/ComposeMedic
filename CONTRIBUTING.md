# Contributing to ComposeMedic

Thank you for helping make Compose troubleshooting less frustrating.

## Before changing a rule

Open an issue with a minimal, sanitized Compose file, the finding you expected, and what happened instead. Never include real passwords, tokens, private endpoints, or production logs.

Check [the rule catalog](docs/rules.md) and Docker's current Compose specification. A warning should remain a warning when the tool cannot prove a failure. Examples: image-inherited healthchecks, automatically created bind directories, and optional dependencies.

## Local development

Use Python 3.10 or newer in a virtual environment.

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
```

Tests do not need a running Docker engine. Docker query tests use controlled fixtures and verify the read-only command list. CI also validates a real canonical Compose configuration when Docker Compose v2 is available.

## Pull request checklist

- One problem per pull request, with a reproducible fixture.
- A regression test and at least one nearby case that must not trigger the rule.
- Stable diagnostic codes and no raw secrets, values, logs, or stderr in reports.
- No automatic fixes, Docker lifecycle commands, network telemetry, or shell execution.
- Update user-facing documentation when behavior changes.
- Describe any AI assistance and how you verified the result.

Useful first contributions include documentation corrections, minimal regression fixtures, and platform-specific false-positive fixes. Proposed features in the README are not automatically assigned; discuss scope before implementing a large change.
