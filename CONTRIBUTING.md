# Contributing to Qubiva

Thanks for your interest in contributing to Qubiva! This document covers
the basics you need to get started.

## Contributor License Agreement (CLA)

By submitting a pull request, you agree to the following:

1. You grant Qubiva (the project owner) a perpetual, worldwide, non-exclusive,
   royalty-free, irrevocable license to use, reproduce, modify, sublicense,
   and distribute your contributions under any license, including proprietary
   licenses for commercial offerings built on top of Qubiva.

2. You confirm that you have the right to grant the above license and that
   your contribution does not violate any third-party rights.

3. Your contributions to this repository remain publicly available under the
   [AGPL-3.0 license](LICENSE) for the open-source community.

This CLA ensures the project owner can offer commercial add-ons (such as
enterprise features) on top of the open-source core without being restricted
by contributions from others. The open-source version always stays AGPL-3.0.

## Getting Started

1. Fork the repository
2. Clone your fork locally
3. Create a feature branch from `main`
4. Make your changes
5. Submit a pull request

## Development Setup

```bash
# Prerequisites: Python 3.11+, MongoDB 7+ (replica set mode)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Set required environment variables
export DATABASE_URL="mongodb://localhost:27017/qubiva?replicaSet=rs0"
export LOCAL_ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
export LOCAL_SIGNING_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export INTERNAL_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"

python main.py
```

## Running Tests

```bash
pip install pytest pytest-asyncio httpx
pytest tests/ -v
```

## Code Style

- Python: follow PEP 8, max line length 120 characters
- JavaScript: use `var` declarations (ES5 compatible for AdminLTE pages)
- HTML: Jinja2 templates in `pages/jinja2templates/`
- Run `flake8 app/ --max-line-length=120 --extend-ignore=E501,W503` before submitting

## Pull Request Guidelines

- Keep PRs focused — one feature or fix per PR
- Include a clear description of what changed and why
- Add tests for new functionality when possible
- Ensure CI passes (lint, test, Docker build, Helm lint)

## Reporting Issues

- Use GitHub Issues for bug reports and feature requests
- Include steps to reproduce for bugs
- Mention your deployment method (Helm, raw K8s manifests, local dev)

## License

By contributing, you agree that your contributions will be licensed under the
[GNU Affero General Public License v3.0](LICENSE) and that the CLA above applies.
