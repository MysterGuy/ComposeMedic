# Security

ComposeMedic reads local configuration and may read its interpolation environment. Reports deliberately omit values, but identifiers such as service names and variable names remain visible.

Do not post real `.env` files, raw `docker inspect` output, canonical Compose output, or credentials in issues. Use a minimal fixture with invented values.

To report a vulnerability, use GitHub's private vulnerability reporting on this repository if available. If it is unavailable, open an issue requesting a private contact channel **without** disclosing exploit details or sensitive data.

Version 0.1 is an early release. Run it on configuration you trust. It is not a security scanner, sandbox, or proof that an application is safe to deploy.
