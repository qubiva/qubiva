# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Qubiva, please report it
responsibly. **Do not open a public GitHub issue.**

Use GitHub's private vulnerability reporting:
**[Report a vulnerability](https://github.com/Qubiva/qubiva/security/advisories/new)**

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We will acknowledge receipt within 48 hours and aim to provide a fix or
mitigation within 7 days for critical issues.

## Supported Versions

| Version | Supported |
|---------|-----------|
| Latest release | Yes |
| Older releases | Best effort |

## Security Practices

- All secrets (database credentials, API keys, encryption keys) are stored in
  Kubernetes Secrets, never in ConfigMaps or code
- Runner pods use dedicated service accounts with minimal RBAC permissions
- Internal API calls between runners and the app use a shared API key
- SAML SSO uses defusedxml for XXE prevention
- CSRF protection on all state-changing endpoints
- Non-root container users in all Docker images
