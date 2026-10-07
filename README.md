# ComposeMedic

> Find Docker Compose problems before changing your stack.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Version](https://img.shields.io/badge/version-0.1.0-orange)
![License](https://img.shields.io/badge/license-MIT-green)

**ComposeMedic** is a small, read-only diagnostic CLI for Docker Compose.

It is designed for the moment when:

- a Compose stack refuses to start;
- an update unexpectedly breaks a service;
- two services try to publish the same port;
- a volume, bind mount, dependency, or environment variable is misconfigured;
- a container is unhealthy, restarting, exited, or missing.

ComposeMedic points to the affected field, explains the problem, and suggests what to check next.

It does **not** edit your Compose files, restart containers, read application logs, or upload your configuration.

> **Early release: v0.1.0**
>
> ComposeMedic performs a focused set of diagnostics.  
> A clean report means that none of the implemented checks found a problem — it does not guarantee that the stack will run correctly.

---

## Why ComposeMedic?

Docker Compose errors are not always obvious.

A stack may fail because of something as simple as:

```yaml
ports:
  - "8080:80"
