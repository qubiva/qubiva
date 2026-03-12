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

Every cloud team stitches together a patchwork:

- **IaC execution** — Terraform Cloud, Spacelift, Env0
- **Resource inventory** — AWS Config, Steampipe CLI, manual scripts
- **Compliance** — Prowler, ScoutSuite, spreadsheets
- **Policy enforcement** — OPA, Sentinel, custom glue code
- **Task tracking** — Jira, Asana, yet another tool

Each with its own credentials, RBAC, and learning curve.

**The result?** Gaps, drift, and no single source of truth.

---

## The Cost of Tool Sprawl

> **$** Gartner: *30% of cloud spend is wasted* due to poor visibility

> **Risk** Compliance violations cost *$14.8M on average* (Ponemon)

> **Time** Platform teams spend *40%+ of their time* switching context

> **Talent** Every new tool = onboarding, training, maintenance burden

The more tools you add, the more fragile the stack becomes.

---

<!-- _class: divider -->

# Meet Qubiva

---

<!-- _class: compact -->

## One Platform. Six Capabilities.

> **IaC Execution** — Run OpenTofu/Terraform plans with state management and live logs

> **Cloud Discovery** — Query live resources across all accounts using SQL

> **Compliance** — Run CIS, SOC 2, HIPAA, PCI DSS, NIST 800-53 benchmarks

> **Policy Enforcement** — OPA/Conftest policy checks before anything deploys

> **Cloud Analyst (AI)** — Ask questions about your infrastructure in plain English

> **Task Management** — Sprints, assignments, priorities, comments, linked tasks

All sharing *one set of credentials*, *one RBAC model*, *one audit trail*.

---

## Cloud Analyst — AI-Powered Queries

Ask your infrastructure anything:

> *"Which EC2 instances in us-east-1 are running without encryption?"*

> *"Show me all Azure VMs that haven't been patched in 30 days"*

> *"What's our monthly GCP spend by project?"*

- **Bring your own LLM** — OpenAI, Azure OpenAI, Groq, Gemini, and more
- Your data stays in your cluster. Always.

**No AI vendor lock-in. No data leaving your perimeter.**

---

## True Multi-Cloud

Works identically across **AWS**, **Azure**, and **GCP**:

> **IaC Execution** — Plan, apply, and destroy across all three clouds

> **Resource Discovery** — SQL queries against live resources, any account

> **Compliance Benchmarks** — CIS, SOC 2, HIPAA for every cloud

> **AI-Powered Querying** — Natural language across your entire fleet

> **Credential Management** — One vault, all three clouds

One pane of glass. No more context switching.

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
Scales horizontally. Works on any Kubernetes cluster.

---

<!-- _class: compact -->

## Enterprise Ready — Out of the Box

- **SAML 2.0 SSO** — Azure AD, Okta, any identity provider
- **RBAC** — Organization and project-level roles, granular permissions
- **Audit Trail** — Every action logged, queryable, exportable
- **Scheduled Automation** — Cron-based discovery, compliance, IaC runs
- **Email Alerts** — Notifications for cloud resource changes
- **GitHub Integration** — Connect IaC repos via GitHub App

No bolt-on enterprise tier for basic security.
**Security is included from day one.**

---

## Open Source, Your Terms

- **Self-hosted** — your Kubernetes cluster, your VPC, your rules
- **No vendor lock-in** — OpenTofu by default, Terraform optional
- **No usage metering** — no per-user, per-run, or per-resource pricing
- **AGPL-3.0 licensed** — free to use, forever

> *"We built the platform we wished existed when managing
> multi-cloud infrastructure across dozens of accounts."*

---

## Business Model

### Community Edition — Free, forever

> The **full platform**: IaC, Discovery, Compliance, Policy, AI Chat, Tasks
> Unlimited users, projects, and cloud accounts
> Self-hosted on any K8s cluster — AGPL-3.0 licensed

### Enterprise — Paid add-ons

> **Cloud AI Governance** — advanced AI-driven policy and cost optimization
> **Priority support** with SLA
> **Custom integrations** and dedicated onboarding

**Free is not a demo.** The community edition is the real product.

---

## Try It Right Now

**One click — fully loaded demo:**

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/qubiva/qubiva?quickstart=1)

**Or run locally:**

```bash
git clone https://github.com/qubiva/qubiva.git
cd qubiva && docker compose up
```

Open **http://localhost** — pre-loaded with sample cloud data.

---

<!-- _class: cta -->
<!-- _paginate: false -->

# Let's Talk

## vpgvijay@yahoo.com

GitHub: [github.com/qubiva/qubiva](https://github.com/qubiva/qubiva)

Evaluating for your team or exploring an investment —
we'd love to hear from you.
