# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, **do not open a public issue**.

Instead, please report it privately via GitHub's security advisory feature:
**Settings > Security > Advisories > New draft advisory**

## Security Practices

### Secrets Management
- All API keys and credentials are stored in **GitHub Secrets** (encrypted at rest)
- Trading configuration uses **GitHub Variables** (non-sensitive, auditable)
- No secrets are ever logged or written to workflow artifacts
- The `.gitignore` blocks `.env` files and credential files

### Workflow Security
- All workflows use **least-privilege permissions** (`contents: read`)
- The trading workflow requires the `trading` **environment** with deployment protection rules
- Dependabot monitors all dependencies for known vulnerabilities
- TruffleHog scans for accidentally committed secrets

### Trading Safety
- **Dry-run mode** is enabled by default — must be explicitly disabled
- Position limits and cash reserves are enforced in code
- Daily trade limits prevent runaway execution
- Paper trading URL is the default broker endpoint
