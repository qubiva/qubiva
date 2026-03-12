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

# Your cloud team juggles *five tools*,
# *five logins*, and *five bills*
# — with **zero visibility.**

---

## Every Cloud Team Knows This Pain

You're stitching together a fragile patchwork:

- **IaC execution** — Terraform Cloud, Spacelift, Env0
- **Resource inventory** — AWS Config, Steampipe, manual scripts
- **Compliance** — Prowler, ScoutSuite, spreadsheets
- **Policy enforcement** — OPA, Sentinel, custom glue code
- **Task tracking** — Jira, Asana, yet another tool

Each tool brings its own credentials, RBAC, billing, and learning curve.

**More tools ≠ more visibility.** It's the opposite.

---

## The Real Cost

> **Wasted spend** — *30% of cloud budgets* go to waste due to poor visibility *(Gartner)*

> **Compliance risk** — The average cost of a compliance violation is *$14.8M* *(Ponemon)*

> **Lost productivity** — Platform teams spend *40%+ of their week* context-switching between tools

> **Hiring drag** — Every new tool means more onboarding, training, and maintenance

The more tools you add, the more fragile the stack becomes.

---

<!-- _class: divider -->

# What if one platform replaced them all?

---

<!-- _class: compact -->

## Everything Your Cloud Team Needs

> **IaC Execution** — Run OpenTofu/Terraform plans with state management and real-time logs

> **Cloud Discovery** — Query live resources across all accounts using SQL

> **Compliance** — CIS, SOC 2, HIPAA, PCI DSS, NIST 800-53, and hundreds more benchmarks

> **Policy Enforcement** — OPA/Conftest policy checks before anything deploys

> **Cloud Analyst** — Ask questions about your infrastructure in plain English (AI-powered)

> **Task Management** — Sprints, priorities, assignments, comments, linked tasks

One set of credentials. One RBAC model. One audit trail.

---

## Cloud Analyst — Talk to Your Infrastructure

Ask anything about your cloud in plain English:

> *"Which EC2 instances in us-east-1 are running without encryption?"*

> *"Show me all Azure VMs that haven't been patched in 30 days."*

> *"What's our monthly GCP spend by project?"*

**Bring your own LLM** — OpenAI, Groq, Azure OpenAI, Gemini, and more.
Your data never leaves your cluster. No AI vendor lock-in.

---

## One Pane of Glass — AWS, Azure, GCP

Every capability works identically across all three clouds:

- **IaC Execution** — Plan, apply, and destroy across any provider
- **Resource Discovery** — SQL queries against live resources, any account
- **Compliance** — Industry benchmarks for every cloud, same workflow
- **AI Querying** — Natural language across your entire fleet
- **Credential Management** — One vault, all clouds

No more switching consoles. No more stitching outputs.

---

## Architecture — Built for Kubernetes

```
┌──────────────────────────────────────────────┐
│               Qubiva App                     │
│   FastAPI + Jinja2  │  MongoDB (replica set)  │
│   K8s-native        │  Artifacts on PVC       │
└─────────┬───────────┴──────────┬─────────────┘
          │                      │
     ┌────▼─────┐         ┌─────▼──────┐
     │ IaC      │         │ Discovery  │
     │ Runner   │         │ Runner     │
     │ (K8s     │         │ (K8s       │
     │  Jobs)   │         │  Jobs)     │
     └──────────┘         └────────────┘
```

Runners are **isolated K8s Jobs** — no shared state, no blast radius.
Scales horizontally. Runs on any Kubernetes cluster.

---

<!-- _class: compact -->

## Enterprise Ready — From Day One

- **SAML 2.0 SSO** — Azure AD, Okta, any identity provider
- **RBAC** — Organization and project-level roles with granular permissions
- **Audit Trail** — Every action logged, queryable, exportable
- **Scheduled Automation** — Cron-based discovery, compliance, and IaC runs
- **Email Alerts** — Notifications on cloud resource changes
- **GitHub Integration** — Connect IaC repos via GitHub App

Security isn't an upgrade. **It's included from day one.**

---

## Open Source, On Your Terms

- **Self-hosted** — your Kubernetes cluster, your VPC, your rules
- **No vendor lock-in** — OpenTofu by default, Terraform optional
- **No usage metering** — no per-user, per-run, or per-resource pricing
- **AGPL-3.0 licensed** — free to use, forever

> *"We built the platform we wished existed when managing
> multi-cloud infrastructure across dozens of accounts."*

---

## Business Model

### Community Edition — Free, forever

> The **full platform** — IaC, Discovery, Compliance, Policy, AI Chat, Tasks
> Unlimited users, projects, and cloud accounts
> Self-hosted on any K8s cluster — AGPL-3.0 licensed

### Enterprise — Paid add-ons

> **Cloud AI Governance** — AI-driven policy recommendations and cost optimization
> **Priority support** with SLA
> **Custom integrations** and dedicated onboarding

**Free is not a trial.** The community edition is the real product.

---

## See It Live — Right Now

**One click — fully loaded demo with sample cloud data:**

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/qubiva/qubiva?quickstart=1)

Click **"Create new codespace"**, wait for setup, and the app opens automatically.
If your browser blocks the popup, go to the **Ports** tab and click the URL for port 80.

**Or run locally:**
`git clone https://github.com/qubiva/qubiva.git && cd qubiva && docker compose up`
Open **http://localhost** — login: `admin@qubiva.local` / `Demo@2026`

> Demo uses realistic sample data to emulate a real multi-cloud environment.

---

<!-- _class: cta -->
<!-- _paginate: false -->

# Let's Talk

## vpgvijay@yahoo.com

GitHub: [github.com/qubiva/qubiva](https://github.com/qubiva/qubiva)

Evaluating for your team or exploring an investment —
we'd love to hear from you.
