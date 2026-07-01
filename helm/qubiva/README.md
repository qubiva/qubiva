# Qubiva Helm Chart

Open-source multi-cloud governance platform — IaC execution, cloud discovery, compliance benchmarks, policy enforcement, and AI-powered querying across AWS, Azure, and GCP.

Full documentation: [github.com/qubiva/qubiva](https://github.com/qubiva/qubiva)

## Installing

```bash
helm install qubiva oci://ghcr.io/qubiva/charts/qubiva \
  --namespace qubiva --create-namespace
```

Secrets and encryption keys are auto-generated on first install and preserved across upgrades.

Access the dashboard:

```bash
kubectl port-forward -n qubiva svc/qubiva 8000:80
# Open http://localhost:8000 — login: admin@qubiva.local
kubectl get secret qubiva-initial-admin-secret -n qubiva \
  -o jsonpath='{.data.password}' | base64 -d
```

## Key Values

| Value | Default | Description |
|-------|---------|-------------|
| `image.tag` | Chart appVersion | App image tag |
| `replicaCount` | `1` | Number of app replicas |
| `ingress.enabled` | `false` | Enable Ingress |
| `ingress.host` | `qubiva.local` | Ingress hostname |
| `iacEngine` | `tofu` | IaC engine (`tofu` or `terraform`) |
| `mongodb.enabled` | `true` | Deploy bundled MongoDB (dev only) |
| `artifacts.storageSize` | `10Gi` | Run artifact storage |
| `secrets.databaseUrl` | `""` | External MongoDB URL |
| `secrets.localEncryptionKey` | `""` | Fernet key (auto-generated if empty) |
| `secrets.llmApiKey` | `""` | LLM provider API key for Cloud Analyst |
| `cloudAnalyst.llm.provider` | `""` | LLM provider (openai, groq, etc.) |
| `cloudAnalyst.llm.model` | `""` | LLM model name |
| `cloudAnalyst.llm.baseUrl` | `""` | OpenAI-compatible API endpoint |

Full values reference: [helm/qubiva/values.yaml](https://github.com/qubiva/qubiva/blob/main/helm/qubiva/values.yaml)
