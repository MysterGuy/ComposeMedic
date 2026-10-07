# Diagnostic catalog

Codes are stable identifiers for JSON consumers. Severity reflects what the tool can establish, not how alarming a configuration looks.

| Code | Severity | Meaning |
| --- | --- | --- |
| `ENV_UNSET` | error | Interpolation variable missing or empty when required |
| `IMAGE_OR_BUILD_MISSING` | error | No source image or build context |
| `IMAGE_UNPINNED` | warning | Implicit/explicit latest image tag |
| `CONTAINER_NAME_COLLISION` | error | Two active services request the same name |
| `PORT_INVALID` | error | Invalid/unsupported IP, protocol, or port mapping |
| `PORT_COLLISION` | error | Active mappings overlap in host address, port, and protocol |
| `PORT_POOL_OVERLAP` | warning | Allocation range overlaps another mapping; Docker picks the actual port |
| `HOST_NETWORK_PORTS` | error | Published ports combined with host networking |
| `MOUNT_INVALID` | error | Invalid source, target, or syntax |
| `MOUNT_TARGET_DUPLICATE` | error | Multiple mounts target the same container path |
| `BIND_SOURCE_MISSING` | warning/error | Missing local source; error if automatic creation is disabled |
| `VOLUME_UNDECLARED` | error | Named volume has no top-level declaration |
| `MOUNT_TYPE_UNCHECKED` | info | Mount type outside the checker’s coverage |
| `PATH_UNCHECKED` | info | Host path belongs to another operating system |
| `ENV_FILE_MISSING` | error | Required service environment file is absent locally |
| `BUILD_CONTEXT_MISSING` | error | Local build context is absent |
| `DEPENDENCY_MISSING` | error/info | Required/optional dependency is undefined or inactive |
| `DEPENDENCY_HEALTH_UNVERIFIED` | warning | Healthy startup requirement needs an image or Compose healthcheck |
| `DEPENDENCY_CYCLE` | error | Circular dependency among active services |
| `NETWORKS_UNDECLARED` | error | Referenced network has no declaration |
| `SECRETS_UNDECLARED` | error | Referenced secret has no declaration |
| `CONFIGS_UNDECLARED` | error | Referenced config has no declaration |
| `NETWORK_MODE_CONFLICT` | error | networks and network_mode defined together |
| `RESOURCE_FILE_MISSING` | error | Local file used by a secret or config is absent |
| `CONTAINER_FAILED` | error | Runtime state restarting, dead, or removing |
| `CONTAINER_EXITED` | error/info | Container exited with failure/success |
| `CONTAINER_UNHEALTHY` | error | Current health state is unhealthy |
| `CONTAINER_PAUSED` | warning | Container paused |
| `CONTAINER_NOT_STARTED` | warning | Container created but not started |
| `CONTAINER_NOT_FOUND` | info | No container for an active service |

`SCAN_FAILED` is an operational failure code, outside the findings list. It returns exit code 2.

## JSON contract

Successful scans return `schema_version`, `tool`, `version`, `mode`, `services_checked`, `summary`, `findings`, and `limitations`. Each finding contains `code`, `severity`, `service`, `field`, `message`, and `suggestion`. Findings are sorted by severity, service, code, and field.

Do not infer application availability from an empty findings list. Read `mode` and `limitations` when consuming a report. Adding a diagnostic code is additive; changing the structure requires a schema version change.

## Source of truth

The checks follow the [Compose services specification](https://docs.docker.com/reference/compose-file/services/) and [interpolation documentation](https://docs.docker.com/reference/compose-file/interpolation/). Docker's [config command](https://docs.docker.com/reference/cli/docker/compose/config/) supplies the canonical model in resolved mode. The [ps command](https://docs.docker.com/reference/cli/docker/compose/ps/) supplies runtime status; both JSON arrays and JSON Lines are accepted.

## Contributor examples

When reporting a false positive, include the code and the smallest sanitized fixture. For a new diagnostic, add one broken fixture and a nearby valid case. Prefer deterministic checks that can be tested without deploying applications.
