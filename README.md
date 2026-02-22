# Qubiva

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![CI](https://github.com/Qubiva/qubiva/actions/workflows/ci.yaml/badge.svg)](https://github.com/Qubiva/qubiva/actions/workflows/ci.yaml)

Open-source multi-cloud governance platform. Execute OpenTofu/Terraform with approval workflows, discover cloud resources via SQL, enforce OPA policies and compliance benchmarks, and query your infrastructure with AI (bring your own LLM). Built-in RBAC, SSO, alerts, and automation for AWS, Azure, and GCP.

## Why Qubiva?

Most cloud tools do one thing — IaC execution, compliance scanning, or resource inventory. Qubiva brings them together in a single self-hosted platform with unified credentials, consistent RBAC, and no vendor lock-in.

- **One platform instead of five** — IaC execution, cloud discovery, compliance benchmarks, policy enforcement, and AI-powered querying under one roof
- **Bring your own LLM** — Cloud Analyst works with any OpenAI-compatible API (OpenAI, Anthropic, Groq, Azure OpenAI, and more). No AI vendor lock-in.
- **Self-hosted, open source** — Runs on any Kubernetes cluster. OpenTofu by default, Terraform optional. Apache 2.0 licensed.
- **Enterprise-ready** — SAML 2.0 SSO, organization and project-level RBAC, full audit trail, scheduled automation, and email alerts out of the box

## Features

- **Infrastructure as Code** — Execute OpenTofu/Terraform plans with approval workflows, state management, and run history
- **Cloud discovery** — Query live cloud resources using SQL across all connected accounts
- **Compliance benchmarks** — Run compliance checks against industry standards (CIS, SOC 2, HIPAA, PCI DSS, and more)
- **Policy enforcement** — Conftest/OPA policy checks on infrastructure changes before they deploy
- **Cloud Analyst** — AI-powered chat that queries your cloud infrastructure in natural language (bring your own LLM)
- **Multi-cloud management** — Projects, cloud accounts, workspaces, and shared credentials across AWS, Azure, and GCP
- **Scheduled runs** — Cron-based automation for discovery, compliance, and IaC execution
- **GitHub integration** — Connect GitHub App for IaC template repositories
- **Alerts and notifications** — Configurable cloud resource alerts with email notifications
- **Audit trail** — Full audit log of all user and system actions
- **RBAC** — Organization and project-level roles with granular permissions
- **SSO** — SAML 2.0 single sign-on (Azure AD, Okta, etc.)
- **Real-time logs** — Live log streaming for running jobs with full history via Loki

### Supported clouds

| Capability | AWS | Azure | GCP |
|------------|-----|-------|-----|
| IaC execution (OpenTofu/Terraform) | ✓ | ✓ | ✓ |
| Resource discovery (SQL) | ✓ | ✓ | ✓ |
| Compliance benchmarks | ✓ | ✓ | ✓ |
| AI-powered querying | ✓ | ✓ | ✓ |
| Credential management | ✓ | ✓ | ✓ |

## Architecture

```
┌─────────────────────────────────────────────┐
│              Qubiva App                    │
│  FastAPI + Jinja2 │ MongoDB (replica set)   │
│  K8s-native       │ Artifacts on PVC        │
└────────┬──────────┴──────────┬──────────────┘
         │                     │
    ┌────▼────┐          ┌─────▼─────┐
    │ IaC     │          │ Discovery │
    │ Runner  │          │ Runner    │
    │ (K8s    │          │ (K8s      │
    │  Jobs)  │          │  Jobs)    │
    └─────────┘          └───────────┘
```

- **App** runs as a Deployment — serves UI, API, manages state
- **Runners** are K8s Jobs launched on demand — isolated execution for IaC and cloud queries
- **MongoDB** stores projects, accounts, users, tasks (replica set required for change streams)
- **Loki** aggregates runner logs for retention and history beyond pod lifetime

## Try it

The demo comes pre-loaded with sample projects, cloud accounts (AWS, Azure, GCP), discovery data, compliance benchmarks, and alerts. Everything works out of the box — you don't need real cloud credentials or API keys.

### Option 1: Run in your browser via GitHub Codespaces

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/qubiva/qubiva?quickstart=1)

Click the button above, then click **"Create new codespace"** on the next page. Wait for the setup to complete — once done, the terminal will show a message with the login credentials. A browser tab will open automatically with the app, or click the **Ports** tab and open the link for port 8000. Free for up to 60 hours/month on any GitHub account.

### Option 2: Run locally with Docker

```bash
git clone https://github.com/qubiva/qubiva.git
cd qubiva
docker compose up
```

Once the containers are up, open **http://localhost:8000**.

### Demo login

`admin@qubiva.local` / `Demo@2026`

> **Note:** The demo runs with pre-loaded sample data for evaluation purposes only. To connect real cloud accounts and run actual infrastructure operations, deploy on Kubernetes using the Helm chart below.

## Deploy (Helm)

```bash
helm install qubiva oci://ghcr.io/qubiva/charts/qubiva \
  --namespace qubiva --create-namespace \
  --set secrets.localEncryptionKey="$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
  --set secrets.localSigningKey="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  --set secrets.jwtSecret="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  --set secrets.internalApiKey="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

Then access the dashboard:

```bash
kubectl port-forward -n qubiva svc/qubiva 8000:80
# Open http://localhost:8000
# Default admin: admin@qubiva.local
# Retrieve password:
kubectl get secret qubiva-initial-admin-secret -n qubiva \
  -o jsonpath='{.data.password}' | base64 -d
```

## Configuration

Qubiva uses a layered configuration system:

1. **Image defaults** — `app_config.default.json` baked into the Docker image
2. **ConfigMap override** — Mount a ConfigMap at `/app/config/app_config.json` (deep-merged on top of defaults)
3. **Environment variables** — Secrets and runtime settings via env vars

### IaC Engine

Default engine is **OpenTofu** (open source). Switch to Terraform by setting:

```json
{
  "terraform": {
    "engine": "terraform"
  }
}
```

### Cloud Analyst (AI Chat)

Bring your own LLM. Supports any OpenAI-compatible API (OpenAI, Groq, Azure OpenAI, Anthropic, etc.).

```json
{
  "cloud_analyst": {
    "enabled": true,
    "llm": {
      "provider": "openai",
      "model": "gpt-4o",
      "base_url": "https://api.openai.com/v1/",
      "api_key_env": "LLM_API_KEY"
    }
  }
}
```

Set the `LLM_API_KEY` environment variable (or Kubernetes secret) to your provider's API key.

## Helm chart values

| Value | Default | Description |
|-------|---------|-------------|
| `image.repository` | `ghcr.io/qubiva/qubiva` | App container image |
| `image.tag` | Chart appVersion | Image tag |
| `ingress.enabled` | `false` | Enable Ingress |
| `ingress.host` | `qubiva.local` | Ingress hostname |
| `iacEngine` | `tofu` | IaC engine (`tofu` or `terraform`) |
| `mongodb.enabled` | `true` | Deploy bundled MongoDB |
| `secrets.*` | (required) | Database URL, encryption keys, API keys |

See [helm/qubiva/values.yaml](helm/qubiva/values.yaml) for the full list.

## Development setup

```bash
# Prerequisites: Python 3.11+, MongoDB 7+ (replica set)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Set `DATABASE_URL`, `LOCAL_ENCRYPTION_KEY`, `LOCAL_SIGNING_KEY`, `JWT_SECRET` as environment variables.

## Project structure

```
app/
  app.py              # FastAPI entry point
  deps.py             # Shared dependencies and managers
  routes/             # 16 route modules
  llm/                # LLM provider abstraction (OpenAI, Anthropic, Azure)
  chat_manager.py     # Cloud Analyst chat orchestration
  runner_pool.py      # Pre-warmed K8s runner pod pools
helm/qubiva/        # Helm chart
k8s/                  # Raw Kubernetes manifests
iac_runner/           # IaC runner Docker image
discovery_runner/     # Discovery/compliance runner Docker image
pages/jinja2templates/# UI templates
static/               # CSS, JS, images
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and pull request guidelines.

## Security

To report a vulnerability, see [SECURITY.md](SECURITY.md).

## License

[Apache License 2.0](LICENSE) — see [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md) for dependency attributions.
