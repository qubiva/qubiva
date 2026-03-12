---
marp: true
theme: qubiva
paginate: true
footer: "qubiva.io"
---

<!-- _class: lead -->
<!-- _paginate: false -->
<!-- _footer: "" -->

# Qubiva

## One platform to govern all your clouds

---

<!-- _class: statement -->
<!-- _paginate: false -->

# 5 tools. 5 logins. 5 bills.
# **Zero visibility.**

---

## The Problem

Every cloud team stitches together a patchwork of tools:

- One tool for **IaC execution** (Terraform Cloud, Spacelift, Env0)
- Another for **resource inventory** (AWS Config, Steampipe CLI)
- Another for **compliance** (Prowler, ScoutSuite, manual audits)
- Another for **policy enforcement** (OPA, Sentinel, custom scripts)
- Another for **task tracking** (Jira, Asana, spreadsheets)

Each tool has its own credentials, its own RBAC, its own learning curve.

**The result?** Gaps, drift, and no single source of truth.

---

## The Cost of Tool Sprawl

|  | Impact |
|---|---|
| **$** | Gartner: *30% of cloud spend is wasted* due to poor visibility |
| **Risk** | Compliance violations cost $14.8M on average (Ponemon) |
| **Time** | Platform teams spend *40%+ of time* switching between tools |
| **Talent** | Every new tool = onboarding, training, maintenance burden |

The more tools you add, the more fragile the stack becomes.

---

<!-- _class: divider -->

# Meet Qubiva

---

## One Platform. Six Capabilities.

| Capability | What it does |
|---|---|
| **IaC Execution** | Run OpenTofu/Terraform plans with state management and live logs |
| **Cloud Discovery** | Query live resources across all accounts using SQL |
| **Compliance** | Run CIS, SOC 2, HIPAA, PCI DSS, NIST 800-53 benchmarks |
| **Policy Enforcement** | OPA/Conftest policy checks before anything deploys |
| **Cloud Analyst (AI)** | Ask questions about your infrastructure in plain English |
| **Task Management** | Sprints, assignments, priorities, comments, and linked tasks |

All sharing *one set of credentials*, *one RBAC model*, *one audit trail*.

---

## Cloud Analyst — AI-Powered Queries

Ask your infrastructure anything in natural language:

> *"Which EC2 instances in us-east-1 are running without encryption?"*
> *"Show me all Azure VMs that haven't been patched in 30 days"*
> *"What's our monthly GCP spend by project?"*

- Bring your own LLM — works with any OpenAI-compatible API
- OpenAI, Azure OpenAI, Groq, Google Gemini, and more
- Your data stays in your cluster. Always.

**No AI vendor lock-in. No data leaving your perimeter.**

---

## True Multi-Cloud

|  | AWS | Azure | GCP |
|---|:---:|:---:|:---:|
| IaC Execution | ✓ | ✓ | ✓ |
| Resource Discovery | ✓ | ✓ | ✓ |
| Compliance Benchmarks | ✓ | ✓ | ✓ |
| AI-Powered Querying | ✓ | ✓ | ✓ |
| Credential Management | ✓ | ✓ | ✓ |

One pane of glass. All three clouds. No more context switching.

---

## Architecture — Built for Kubernetes

```
┌─────────────────────────────────────────────────┐
│                 Qubiva App                      │
│    FastAPI + Jinja2  │  MongoDB (replica set)   │
│    K8s-native        │  Artifacts on PVC        │
└──────────┬───────────┴───────────┬──────────────┘
           │                       │
      ┌────▼─────┐          ┌─────▼──────┐
      │ IaC      │          │ Discovery  │
      │ Runner   │          │ Runner     │
      │ (K8s     │          │ (K8s       │
      │  Jobs)   │          │  Jobs)     │
      └──────────┘          └────────────┘
```

- Runners launch as **isolated K8s Jobs** — no shared state, no blast radius
- Scales horizontally. Works on any Kubernetes cluster.
- Loki for log aggregation and history

---

## Enterprise Ready — Out of the Box

- **SAML 2.0 SSO** — Azure AD, Okta, any IdP
- **RBAC** — Organization and project-level roles with granular permissions
- **Audit Trail** — Every action logged, queryable, exportable
- **Scheduled Automation** — Cron-based discovery, compliance, and IaC runs
- **Email Alerts** — Configurable notifications for cloud resource changes
- **GitHub Integration** — Connect your IaC template repos via GitHub App

No bolt-on enterprise tier for basic security features.
**Security is included from day one.**

---

## Open Source, Your Terms

- **Self-hosted** — runs on your Kubernetes cluster, your VPC, your rules
- **No vendor lock-in** — OpenTofu by default (open source), Terraform optional
- **No usage metering** — no per-user, per-run, or per-resource pricing
- **AGPL-3.0 licensed** — free to use, forever

> *"We built the platform we wished existed when managing
> multi-cloud infrastructure across dozens of accounts."*

---

## Business Model

### Open Core

| Community (Free) | Enterprise (Paid) |
|---|---|
| Full platform — IaC, Discovery, Compliance, Policy, AI Chat, Tasks | Cloud AI Governance |
| Unlimited users, projects, and cloud accounts | Priority support and SLA |
| Self-hosted on any K8s cluster | Custom integrations |
| AGPL-3.0 licensed | Dedicated onboarding |

**Free is not a demo.** The community edition is the real product.
Enterprise adds specialized capabilities for regulated industries.

---

## Try It Right Now

**One click:**

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/qubiva/qubiva?quickstart=1)

**Or locally:**

```bash
git clone https://github.com/qubiva/qubiva.git
cd qubiva && docker compose up
# Open http://localhost
```

Pre-loaded with sample cloud data. Ready to explore in 2 minutes.

---

<!-- _class: cta -->
<!-- _paginate: false -->

# Let's Talk

## vpgvijay@yahoo.com

GitHub: [github.com/qubiva/qubiva](https://github.com/qubiva/qubiva)

Whether you're evaluating for your team or exploring an investment —
we'd love to hear from you.
