"""
Qubiva demo data seeder.

Populates MongoDB with realistic demo data for evaluation purposes.
Runs as a one-shot container using the app image (has all dependencies).
Uses pymongo directly — no app imports, no prod code modifications.

Also writes discovery/benchmark artifact JSON files to the artifacts volume
so that dashboards, charts, and compliance views are fully populated.
"""

import os
import sys
import time
import json
from datetime import datetime, timedelta
from cryptography.fernet import Fernet
import pymongo
import bcrypt

DB_URL = os.environ.get("DATABASE_URL", "mongodb://mongodb:27017/qubiva?replicaSet=rs0&directConnection=true")
FERNET_KEY = os.environ.get("LOCAL_ENCRYPTION_KEY", "")
ARTIFACTS_PATH = os.environ.get("ARTIFACTS_STORAGE_PATH", "/app/data/artifacts")
ARTIFACTS_PREFIX = os.environ.get("ARTIFACTS_PREFIX", "query-results")

NOW = datetime.utcnow()


def wait_for_mongo(url, timeout=60):
    """Wait for MongoDB to be ready."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            client = pymongo.MongoClient(url, serverSelectionTimeoutMS=2000)
            client.admin.command("ping")
            return client
        except Exception:
            time.sleep(2)
    print("ERROR: MongoDB not reachable", file=sys.stderr)
    sys.exit(1)


def encrypt(fernet, value):
    return fernet.encrypt(value.encode("utf-8")).decode("utf-8")


def iso(dt):
    return dt.isoformat() + "Z"


def write_artifact(request_id, filename, data):
    """Write a JSON artifact file to the artifacts volume."""
    artifact_dir = os.path.join(ARTIFACTS_PATH, ARTIFACTS_PREFIX, request_id)
    os.makedirs(artifact_dir, exist_ok=True)
    filepath = os.path.join(artifact_dir, filename)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    return filepath


# ═══════════════════════════════════════════════════════════════════════════
# Discovery artifact data generators
# ═══════════════════════════════════════════════════════════════════════════

def aws_discovery_data(discovered_at, resource_count_multiplier=1.0, cost_multiplier=1.0):
    """Generate realistic AWS discovery data."""
    m = resource_count_multiplier
    resources = []

    # EC2 instances
    ec2_instances = [
        ("i-0a1b2c3d4e5f60001", "api-gateway-prod", "us-east-1", {"Environment": "production", "Team": "platform", "CostCenter": "eng-1001"}),
        ("i-0a1b2c3d4e5f60002", "api-gateway-prod-2", "us-east-1", {"Environment": "production", "Team": "platform", "CostCenter": "eng-1001"}),
        ("i-0a1b2c3d4e5f60003", "worker-prod-1", "us-east-1", {"Environment": "production", "Team": "data", "CostCenter": "eng-1002"}),
        ("i-0a1b2c3d4e5f60004", "worker-prod-2", "us-west-2", {"Environment": "production", "Team": "data", "CostCenter": "eng-1002"}),
        ("i-0a1b2c3d4e5f60005", "bastion-host", "us-east-1", {"Environment": "production", "Team": "security"}),
        ("i-0a1b2c3d4e5f60006", "monitoring-server", "us-east-1", {}),
        ("i-0a1b2c3d4e5f60007", "dev-sandbox", "us-west-2", {"Environment": "development"}),
    ]
    for rid, name, region, tags in ec2_instances[:max(3, int(len(ec2_instances) * m))]:
        resources.append({"resource_type": "aws_ec2_instance", "resource_id": rid, "resource_name": name, "region": region, "tags": json.dumps(tags), "account_id": "123456789012"})

    # S3 buckets
    s3_buckets = [
        ("acme-data-lake-prod", "acme-data-lake-prod", "us-east-1", {"Environment": "production", "DataClassification": "confidential"}),
        ("acme-static-assets", "acme-static-assets", "us-east-1", {"Environment": "production", "Team": "frontend"}),
        ("acme-logs-archive", "acme-logs-archive", "us-east-1", {"Environment": "production", "Retention": "365d"}),
        ("acme-terraform-state", "acme-terraform-state", "us-east-1", {"ManagedBy": "terraform"}),
        ("acme-backups-prod", "acme-backups-prod", "us-west-2", {"Environment": "production", "Schedule": "daily"}),
        ("acme-ml-training-data", "acme-ml-training-data", "us-east-1", {}),
    ]
    for rid, name, region, tags in s3_buckets[:max(3, int(len(s3_buckets) * m))]:
        resources.append({"resource_type": "aws_s3_bucket", "resource_id": rid, "resource_name": name, "region": region, "tags": json.dumps(tags), "account_id": "123456789012"})

    # RDS instances
    rds_instances = [
        ("acme-prod-postgres", "acme-prod-postgres", "us-east-1", {"Environment": "production", "Engine": "postgresql", "Team": "platform"}),
        ("acme-analytics-db", "acme-analytics-db", "us-east-1", {"Environment": "production", "Engine": "postgresql", "Team": "data"}),
        ("acme-dev-mysql", "acme-dev-mysql", "us-west-2", {"Environment": "development", "Engine": "mysql"}),
    ]
    for rid, name, region, tags in rds_instances[:max(1, int(len(rds_instances) * m))]:
        resources.append({"resource_type": "aws_rds_db_instance", "resource_id": rid, "resource_name": name, "region": region, "tags": json.dumps(tags), "account_id": "123456789012"})

    # IAM roles
    iam_roles = [
        ("arn:aws:iam::123456789012:role/eks-cluster-role", "eks-cluster-role", "global", {"ManagedBy": "terraform"}),
        ("arn:aws:iam::123456789012:role/eks-node-role", "eks-node-role", "global", {"ManagedBy": "terraform"}),
        ("arn:aws:iam::123456789012:role/lambda-execution-role", "lambda-execution-role", "global", {}),
        ("arn:aws:iam::123456789012:role/ci-cd-deploy-role", "ci-cd-deploy-role", "global", {"Team": "devops"}),
        ("arn:aws:iam::123456789012:role/admin-role", "admin-role", "global", {}),
    ]
    for rid, name, region, tags in iam_roles[:max(2, int(len(iam_roles) * m))]:
        resources.append({"resource_type": "aws_iam_role", "resource_id": rid, "resource_name": name, "region": region, "tags": json.dumps(tags), "account_id": "123456789012"})

    # Security groups
    sgs = [
        ("sg-0a1b2c3d4e5f60001", "eks-cluster-sg", "us-east-1", {"Environment": "production"}),
        ("sg-0a1b2c3d4e5f60002", "rds-postgres-sg", "us-east-1", {"Environment": "production"}),
        ("sg-0a1b2c3d4e5f60003", "bastion-sg", "us-east-1", {"Environment": "production"}),
        ("sg-0a1b2c3d4e5f60004", "alb-public-sg", "us-east-1", {}),
    ]
    for rid, name, region, tags in sgs[:max(2, int(len(sgs) * m))]:
        resources.append({"resource_type": "aws_vpc_security_group", "resource_id": rid, "resource_name": name, "region": region, "tags": json.dumps(tags), "account_id": "123456789012"})

    # Lambda functions
    lambdas = [
        ("acme-webhook-handler", "acme-webhook-handler", "us-east-1", {"Environment": "production", "Team": "platform"}),
        ("acme-image-processor", "acme-image-processor", "us-east-1", {"Environment": "production", "Team": "media"}),
        ("acme-cost-reporter", "acme-cost-reporter", "us-east-1", {"Environment": "production", "Team": "finops"}),
    ]
    for rid, name, region, tags in lambdas[:max(1, int(len(lambdas) * m))]:
        resources.append({"resource_type": "aws_lambda_function", "resource_id": rid, "resource_name": name, "region": region, "tags": json.dumps(tags), "account_id": "123456789012"})

    # EKS cluster
    resources.append({"resource_type": "aws_eks_cluster", "resource_id": "acme-prod-eks", "resource_name": "acme-prod-eks", "region": "us-east-1", "tags": json.dumps({"Environment": "production", "Team": "platform"}), "account_id": "123456789012"})

    # VPCs
    resources.append({"resource_type": "aws_vpc", "resource_id": "vpc-0a1b2c3d4e5f6001", "resource_name": "acme-prod-vpc", "region": "us-east-1", "tags": json.dumps({"Environment": "production", "CIDR": "10.0.0.0/16"}), "account_id": "123456789012"})
    resources.append({"resource_type": "aws_vpc", "resource_id": "vpc-0a1b2c3d4e5f6002", "resource_name": "acme-dev-vpc", "region": "us-west-2", "tags": json.dumps({"Environment": "development"}), "account_id": "123456789012"})

    # Cost data
    cm = cost_multiplier
    costs = [
        {"service": "Amazon Elastic Compute Cloud", "total_cost": round(2847.50 * cm, 2)},
        {"service": "Amazon Relational Database Service", "total_cost": round(1245.00 * cm, 2)},
        {"service": "Amazon Simple Storage Service", "total_cost": round(387.25 * cm, 2)},
        {"service": "Amazon Elastic Kubernetes Service", "total_cost": round(876.00 * cm, 2)},
        {"service": "AWS Lambda", "total_cost": round(124.80 * cm, 2)},
        {"service": "Amazon CloudFront", "total_cost": round(213.60 * cm, 2)},
        {"service": "Amazon Route 53", "total_cost": round(45.20 * cm, 2)},
        {"service": "AWS Key Management Service", "total_cost": round(67.30 * cm, 2)},
        {"service": "Amazon CloudWatch", "total_cost": round(156.40 * cm, 2)},
        {"service": "AWS Data Transfer", "total_cost": round(342.15 * cm, 2)},
    ]

    return {
        "discovered_at": iso(discovered_at),
        "resources": {"rows": resources},
        "costs": {"rows": costs},
    }


def azure_discovery_data(discovered_at):
    """Generate realistic Azure discovery data."""
    resources = [
        {"resource_type": "azure_compute_virtual_machine", "resource_id": "/subscriptions/a1b2c3d4/resourceGroups/acme-prod/providers/Microsoft.Compute/virtualMachines/hub-firewall", "resource_name": "hub-firewall", "region": "eastus", "tags": json.dumps({"Environment": "production", "Team": "networking"}), "account_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"},
        {"resource_type": "azure_compute_virtual_machine", "resource_id": "/subscriptions/a1b2c3d4/resourceGroups/acme-prod/providers/Microsoft.Compute/virtualMachines/ad-controller", "resource_name": "ad-controller", "region": "eastus", "tags": json.dumps({"Environment": "production", "Team": "identity"}), "account_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"},
        {"resource_type": "azure_resource_group", "resource_id": "/subscriptions/a1b2c3d4/resourceGroups/acme-prod", "resource_name": "acme-prod", "region": "eastus", "tags": json.dumps({"Environment": "production"}), "account_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"},
        {"resource_type": "azure_resource_group", "resource_id": "/subscriptions/a1b2c3d4/resourceGroups/acme-networking", "resource_name": "acme-networking", "region": "eastus", "tags": json.dumps({"Environment": "production", "Team": "networking"}), "account_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"},
        {"resource_type": "azure_resource_group", "resource_id": "/subscriptions/a1b2c3d4/resourceGroups/acme-dev", "resource_name": "acme-dev", "region": "westus2", "tags": json.dumps({"Environment": "development"}), "account_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"},
        {"resource_type": "azure_virtual_network", "resource_id": "/subscriptions/a1b2c3d4/resourceGroups/acme-networking/providers/Microsoft.Network/virtualNetworks/hub-vnet", "resource_name": "hub-vnet", "region": "eastus", "tags": json.dumps({"Environment": "production", "Topology": "hub-spoke"}), "account_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"},
        {"resource_type": "azure_virtual_network", "resource_id": "/subscriptions/a1b2c3d4/resourceGroups/acme-networking/providers/Microsoft.Network/virtualNetworks/spoke-prod-vnet", "resource_name": "spoke-prod-vnet", "region": "eastus", "tags": json.dumps({"Environment": "production", "Topology": "hub-spoke"}), "account_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"},
        {"resource_type": "azure_network_security_group", "resource_id": "/subscriptions/a1b2c3d4/resourceGroups/acme-networking/providers/Microsoft.Network/networkSecurityGroups/hub-nsg", "resource_name": "hub-nsg", "region": "eastus", "tags": json.dumps({"Environment": "production"}), "account_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"},
        {"resource_type": "azure_storage_account", "resource_id": "/subscriptions/a1b2c3d4/resourceGroups/acme-prod/providers/Microsoft.Storage/storageAccounts/acmeprodsa", "resource_name": "acmeprodsa", "region": "eastus", "tags": json.dumps({"Environment": "production"}), "account_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"},
        {"resource_type": "azure_key_vault", "resource_id": "/subscriptions/a1b2c3d4/resourceGroups/acme-prod/providers/Microsoft.KeyVault/vaults/acme-prod-kv", "resource_name": "acme-prod-kv", "region": "eastus", "tags": json.dumps({"Environment": "production", "Team": "security"}), "account_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"},
        {"resource_type": "azure_policy_assignment", "resource_id": "/subscriptions/a1b2c3d4/providers/Microsoft.Authorization/policyAssignments/require-tags", "resource_name": "require-tags", "region": "global", "tags": json.dumps({}), "account_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"},
    ]

    costs = [
        {"service": "Virtual Machines", "total_cost": 1450.00},
        {"service": "Storage", "total_cost": 285.50},
        {"service": "Virtual Network", "total_cost": 178.25},
        {"service": "Azure Active Directory", "total_cost": 95.00},
        {"service": "Key Vault", "total_cost": 12.40},
        {"service": "Azure Monitor", "total_cost": 67.80},
        {"service": "Azure Policy", "total_cost": 0.00},
    ]

    return {
        "discovered_at": iso(discovered_at),
        "resources": {"rows": resources},
        "costs": {"rows": costs},
    }


def finops_aws_discovery_data(discovered_at, cost_multiplier=1.0):
    """Generate AWS discovery data for the finops-dashboard project."""
    cm = cost_multiplier
    resources = [
        {"resource_type": "aws_ec2_instance", "resource_id": "i-0f1n2o3p4s5d60001", "resource_name": "finops-collector-1", "region": "eu-west-1", "tags": json.dumps({"Environment": "staging", "Team": "finops"}), "account_id": "987654321098"},
        {"resource_type": "aws_ec2_instance", "resource_id": "i-0f1n2o3p4s5d60002", "resource_name": "finops-api-server", "region": "eu-west-1", "tags": json.dumps({"Environment": "staging", "Team": "finops"}), "account_id": "987654321098"},
        {"resource_type": "aws_s3_bucket", "resource_id": "finops-cost-reports", "resource_name": "finops-cost-reports", "region": "eu-west-1", "tags": json.dumps({"Environment": "staging", "DataType": "cost-reports"}), "account_id": "987654321098"},
        {"resource_type": "aws_s3_bucket", "resource_id": "finops-cur-data", "resource_name": "finops-cur-data", "region": "eu-west-1", "tags": json.dumps({"Environment": "staging", "DataType": "cur"}), "account_id": "987654321098"},
        {"resource_type": "aws_rds_db_instance", "resource_id": "finops-analytics-db", "resource_name": "finops-analytics-db", "region": "eu-west-1", "tags": json.dumps({"Environment": "staging", "Engine": "postgresql"}), "account_id": "987654321098"},
        {"resource_type": "aws_lambda_function", "resource_id": "finops-cost-aggregator", "resource_name": "finops-cost-aggregator", "region": "eu-west-1", "tags": json.dumps({"Environment": "staging", "Team": "finops"}), "account_id": "987654321098"},
        {"resource_type": "aws_lambda_function", "resource_id": "finops-anomaly-detector", "resource_name": "finops-anomaly-detector", "region": "eu-west-1", "tags": json.dumps({"Environment": "staging"}), "account_id": "987654321098"},
        {"resource_type": "aws_vpc", "resource_id": "vpc-0f1n2o3p4s5d6001", "resource_name": "finops-staging-vpc", "region": "eu-west-1", "tags": json.dumps({"Environment": "staging"}), "account_id": "987654321098"},
        {"resource_type": "aws_vpc_security_group", "resource_id": "sg-0f1n2o3p4s5d6001", "resource_name": "finops-api-sg", "region": "eu-west-1", "tags": json.dumps({}), "account_id": "987654321098"},
        {"resource_type": "aws_iam_role", "resource_id": "arn:aws:iam::987654321098:role/finops-read-only", "resource_name": "finops-read-only", "region": "global", "tags": json.dumps({"ManagedBy": "terraform"}), "account_id": "987654321098"},
    ]

    costs = [
        {"service": "Amazon Elastic Compute Cloud", "total_cost": round(645.20 * cm, 2)},
        {"service": "Amazon Relational Database Service", "total_cost": round(312.50 * cm, 2)},
        {"service": "Amazon Simple Storage Service", "total_cost": round(178.30 * cm, 2)},
        {"service": "AWS Lambda", "total_cost": round(45.60 * cm, 2)},
        {"service": "Amazon CloudWatch", "total_cost": round(34.80 * cm, 2)},
        {"service": "AWS Data Transfer", "total_cost": round(89.10 * cm, 2)},
    ]

    return {
        "discovered_at": iso(discovered_at),
        "resources": {"rows": resources},
        "costs": {"rows": costs},
    }


def gcp_discovery_data(discovered_at, cost_multiplier=1.0):
    """Generate realistic GCP discovery data for acme-platform."""
    cm = cost_multiplier
    resources = [
        {"resource_type": "gcp_compute_instance", "resource_id": "projects/acme-prod-123456/zones/us-central1-a/instances/api-server-1", "resource_name": "api-server-1", "region": "us-central1", "tags": json.dumps({"environment": "production", "team": "platform"}), "account_id": "acme-prod-123456"},
        {"resource_type": "gcp_compute_instance", "resource_id": "projects/acme-prod-123456/zones/us-central1-a/instances/api-server-2", "resource_name": "api-server-2", "region": "us-central1", "tags": json.dumps({"environment": "production", "team": "platform"}), "account_id": "acme-prod-123456"},
        {"resource_type": "gcp_compute_instance", "resource_id": "projects/acme-prod-123456/zones/us-east1-b/instances/worker-1", "resource_name": "worker-1", "region": "us-east1", "tags": json.dumps({"environment": "production", "team": "data"}), "account_id": "acme-prod-123456"},
        {"resource_type": "gcp_storage_bucket", "resource_id": "acme-data-warehouse", "resource_name": "acme-data-warehouse", "region": "us-central1", "tags": json.dumps({"environment": "production", "data_classification": "confidential"}), "account_id": "acme-prod-123456"},
        {"resource_type": "gcp_storage_bucket", "resource_id": "acme-tf-state-gcp", "resource_name": "acme-tf-state-gcp", "region": "us-central1", "tags": json.dumps({"managed_by": "terraform"}), "account_id": "acme-prod-123456"},
        {"resource_type": "gcp_storage_bucket", "resource_id": "acme-logs-gcp", "resource_name": "acme-logs-gcp", "region": "us-central1", "tags": json.dumps({"environment": "production", "retention": "365d"}), "account_id": "acme-prod-123456"},
        {"resource_type": "gcp_sql_database_instance", "resource_id": "acme-prod-cloudsql", "resource_name": "acme-prod-cloudsql", "region": "us-central1", "tags": json.dumps({"environment": "production", "engine": "postgresql"}), "account_id": "acme-prod-123456"},
        {"resource_type": "gcp_compute_network", "resource_id": "projects/acme-prod-123456/global/networks/acme-vpc", "resource_name": "acme-vpc", "region": "global", "tags": json.dumps({"environment": "production"}), "account_id": "acme-prod-123456"},
        {"resource_type": "gcp_compute_firewall", "resource_id": "projects/acme-prod-123456/global/firewalls/allow-internal", "resource_name": "allow-internal", "region": "global", "tags": json.dumps({"environment": "production"}), "account_id": "acme-prod-123456"},
        {"resource_type": "gcp_compute_firewall", "resource_id": "projects/acme-prod-123456/global/firewalls/allow-https", "resource_name": "allow-https", "region": "global", "tags": json.dumps({"environment": "production"}), "account_id": "acme-prod-123456"},
        {"resource_type": "gcp_cloudfunctions_function", "resource_id": "projects/acme-prod-123456/locations/us-central1/functions/event-processor", "resource_name": "event-processor", "region": "us-central1", "tags": json.dumps({"environment": "production", "team": "data"}), "account_id": "acme-prod-123456"},
        {"resource_type": "gcp_kms_key", "resource_id": "projects/acme-prod-123456/locations/us-central1/keyRings/acme-keyring/cryptoKeys/app-key", "resource_name": "app-key", "region": "us-central1", "tags": json.dumps({}), "account_id": "acme-prod-123456"},
        {"resource_type": "gcp_iam_role", "resource_id": "projects/acme-prod-123456/roles/appDeployer", "resource_name": "appDeployer", "region": "global", "tags": json.dumps({}), "account_id": "acme-prod-123456"},
    ]

    costs = [
        {"service": "Compute Engine", "total_cost": round(1845.30 * cm, 2)},
        {"service": "Cloud SQL", "total_cost": round(892.40 * cm, 2)},
        {"service": "Cloud Storage", "total_cost": round(234.50 * cm, 2)},
        {"service": "Cloud Functions", "total_cost": round(67.20 * cm, 2)},
        {"service": "Cloud Logging", "total_cost": round(112.80 * cm, 2)},
        {"service": "Networking", "total_cost": round(198.60 * cm, 2)},
        {"service": "Cloud KMS", "total_cost": round(18.90 * cm, 2)},
    ]

    return {
        "discovered_at": iso(discovered_at),
        "resources": {"rows": resources},
        "costs": {"rows": costs},
    }


# ═══════════════════════════════════════════════════════════════════════════
# Benchmark artifact data generators
# ═══════════════════════════════════════════════════════════════════════════

def aws_cis_benchmark_data():
    """Generate realistic CIS AWS Foundations Benchmark v4.0.0 results."""
    return {
        "title": "CIS Amazon Web Services Foundations Benchmark v4.0.0",
        "summary": {
            "status": {
                "alarm": 12,
                "ok": 83,
                "skip": 5,
                "error": 2,
                "info": 3
            }
        },
        "groups": [
            {
                "title": "1 Identity and Access Management",
                "groups": [
                    {
                        "title": "1.1 Maintain current contact details",
                        "controls": [
                            {
                                "control_id": "cis_v400_1_1",
                                "title": "Ensure security contact information is registered",
                                "description": "AWS provides customers with the option of specifying security-specific contact information.",
                                "severity": "medium",
                                "tags": {"service": "iam", "category": "contact"},
                                "summary": {"alarm": 0, "ok": 1, "skip": 0, "error": 0},
                                "results": [
                                    {"resource": "arn:aws:iam::123456789012:root", "status": "ok", "reason": "Security contact is registered"}
                                ]
                            }
                        ]
                    },
                    {
                        "title": "1.4 Ensure no root user account access key exists",
                        "controls": [
                            {
                                "control_id": "cis_v400_1_4",
                                "title": "Ensure no 'root' user account access key exists",
                                "description": "The 'root' user account is the most privileged user in an AWS account.",
                                "severity": "critical",
                                "tags": {"service": "iam", "category": "root_account"},
                                "summary": {"alarm": 1, "ok": 0, "skip": 0, "error": 0},
                                "results": [
                                    {"resource": "arn:aws:iam::123456789012:root", "status": "alarm", "reason": "Root account has active access keys"}
                                ]
                            }
                        ]
                    },
                    {
                        "title": "1.5 Ensure MFA is enabled for the root user account",
                        "controls": [
                            {
                                "control_id": "cis_v400_1_5",
                                "title": "Ensure MFA is enabled for the 'root' user account",
                                "description": "The 'root' user account is the most privileged user in an AWS account.",
                                "severity": "critical",
                                "tags": {"service": "iam", "category": "root_account"},
                                "summary": {"alarm": 1, "ok": 0, "skip": 0, "error": 0},
                                "results": [
                                    {"resource": "arn:aws:iam::123456789012:root", "status": "alarm", "reason": "MFA is not enabled for root account"}
                                ]
                            }
                        ]
                    },
                    {
                        "title": "1.8 Ensure IAM password policy requires minimum length of 14",
                        "controls": [
                            {
                                "control_id": "cis_v400_1_8",
                                "title": "Ensure IAM password policy requires minimum length of 14 or greater",
                                "description": "Password policies are used to enforce password complexity requirements.",
                                "severity": "medium",
                                "tags": {"service": "iam", "category": "password_policy"},
                                "summary": {"alarm": 1, "ok": 0, "skip": 0, "error": 0},
                                "results": [
                                    {"resource": "arn:aws:iam::123456789012:account", "status": "alarm", "reason": "Password minimum length is 8, expected 14"}
                                ]
                            }
                        ]
                    },
                    {
                        "title": "1.10 Ensure multi-factor authentication (MFA) is enabled for all IAM users",
                        "controls": [
                            {
                                "control_id": "cis_v400_1_10",
                                "title": "Ensure multi-factor authentication (MFA) is enabled for all IAM users that have a console password",
                                "description": "MFA adds an extra layer of protection on top of a username and password.",
                                "severity": "high",
                                "tags": {"service": "iam", "category": "mfa"},
                                "summary": {"alarm": 2, "ok": 3, "skip": 0, "error": 0},
                                "results": [
                                    {"resource": "arn:aws:iam::123456789012:user/developer-1", "status": "alarm", "reason": "MFA not enabled for console user"},
                                    {"resource": "arn:aws:iam::123456789012:user/developer-2", "status": "alarm", "reason": "MFA not enabled for console user"},
                                    {"resource": "arn:aws:iam::123456789012:user/admin", "status": "ok", "reason": "MFA enabled"},
                                    {"resource": "arn:aws:iam::123456789012:user/ops-lead", "status": "ok", "reason": "MFA enabled"},
                                    {"resource": "arn:aws:iam::123456789012:user/security-admin", "status": "ok", "reason": "MFA enabled"}
                                ]
                            }
                        ]
                    },
                    {
                        "title": "1.16 Ensure IAM policies that allow full '*:*' administrative privileges are not attached",
                        "controls": [
                            {
                                "control_id": "cis_v400_1_16",
                                "title": "Ensure IAM policies that allow full '*:*' administrative privileges are not attached",
                                "description": "IAM policies should not allow full administrative privileges.",
                                "severity": "high",
                                "tags": {"service": "iam", "category": "access_management"},
                                "summary": {"alarm": 1, "ok": 4, "skip": 0, "error": 0},
                                "results": [
                                    {"resource": "arn:aws:iam::123456789012:policy/LegacyAdminPolicy", "status": "alarm", "reason": "Policy allows *:* administrative access"},
                                    {"resource": "arn:aws:iam::123456789012:policy/EksClusterPolicy", "status": "ok", "reason": "Policy is scoped to specific services"},
                                    {"resource": "arn:aws:iam::123456789012:policy/LambdaExecPolicy", "status": "ok", "reason": "Policy is scoped to specific services"},
                                    {"resource": "arn:aws:iam::123456789012:policy/S3ReadOnlyPolicy", "status": "ok", "reason": "Policy is read-only"},
                                    {"resource": "arn:aws:iam::123456789012:policy/CICDDeployPolicy", "status": "ok", "reason": "Policy is scoped to specific services"}
                                ]
                            }
                        ]
                    }
                ]
            },
            {
                "title": "2 Storage",
                "groups": [
                    {
                        "title": "2.1 Simple Storage Service (S3)",
                        "controls": [
                            {
                                "control_id": "cis_v400_2_1_1",
                                "title": "Ensure S3 Bucket Policy is set to deny HTTP requests",
                                "description": "S3 buckets should deny non-HTTPS requests.",
                                "severity": "medium",
                                "tags": {"service": "s3", "category": "encryption_in_transit"},
                                "summary": {"alarm": 2, "ok": 4, "skip": 0, "error": 0},
                                "results": [
                                    {"resource": "arn:aws:s3:::acme-ml-training-data", "status": "alarm", "reason": "Bucket policy does not deny HTTP requests"},
                                    {"resource": "arn:aws:s3:::acme-data-lake-prod", "status": "alarm", "reason": "Bucket policy does not deny HTTP requests"},
                                    {"resource": "arn:aws:s3:::acme-static-assets", "status": "ok", "reason": "Bucket policy denies HTTP requests"},
                                    {"resource": "arn:aws:s3:::acme-logs-archive", "status": "ok", "reason": "Bucket policy denies HTTP requests"},
                                    {"resource": "arn:aws:s3:::acme-terraform-state", "status": "ok", "reason": "Bucket policy denies HTTP requests"},
                                    {"resource": "arn:aws:s3:::acme-backups-prod", "status": "ok", "reason": "Bucket policy denies HTTP requests"}
                                ]
                            },
                            {
                                "control_id": "cis_v400_2_1_2",
                                "title": "Ensure MFA Delete is enabled on S3 buckets",
                                "description": "MFA Delete requires MFA for object deletion.",
                                "severity": "low",
                                "tags": {"service": "s3", "category": "data_protection"},
                                "summary": {"alarm": 0, "ok": 6, "skip": 0, "error": 0},
                                "results": [
                                    {"resource": "arn:aws:s3:::acme-data-lake-prod", "status": "ok", "reason": "MFA Delete is enabled"},
                                    {"resource": "arn:aws:s3:::acme-static-assets", "status": "ok", "reason": "MFA Delete is enabled"},
                                    {"resource": "arn:aws:s3:::acme-logs-archive", "status": "ok", "reason": "MFA Delete is enabled"},
                                    {"resource": "arn:aws:s3:::acme-terraform-state", "status": "ok", "reason": "MFA Delete is enabled"},
                                    {"resource": "arn:aws:s3:::acme-backups-prod", "status": "ok", "reason": "MFA Delete is enabled"},
                                    {"resource": "arn:aws:s3:::acme-ml-training-data", "status": "ok", "reason": "MFA Delete is enabled"}
                                ]
                            },
                            {
                                "control_id": "cis_v400_2_1_4",
                                "title": "Ensure S3 buckets have server-side encryption enabled",
                                "description": "Amazon S3 provides a variety of server-side encryption options.",
                                "severity": "medium",
                                "tags": {"service": "s3", "category": "encryption_at_rest"},
                                "summary": {"alarm": 1, "ok": 5, "skip": 0, "error": 0},
                                "results": [
                                    {"resource": "arn:aws:s3:::acme-ml-training-data", "status": "alarm", "reason": "Default encryption not enabled"},
                                    {"resource": "arn:aws:s3:::acme-data-lake-prod", "status": "ok", "reason": "SSE-KMS encryption enabled"},
                                    {"resource": "arn:aws:s3:::acme-static-assets", "status": "ok", "reason": "SSE-S3 encryption enabled"},
                                    {"resource": "arn:aws:s3:::acme-logs-archive", "status": "ok", "reason": "SSE-KMS encryption enabled"},
                                    {"resource": "arn:aws:s3:::acme-terraform-state", "status": "ok", "reason": "SSE-KMS encryption enabled"},
                                    {"resource": "arn:aws:s3:::acme-backups-prod", "status": "ok", "reason": "SSE-KMS encryption enabled"}
                                ]
                            }
                        ]
                    }
                ]
            },
            {
                "title": "3 Logging",
                "groups": [
                    {
                        "title": "3.1 Ensure CloudTrail is enabled in all regions",
                        "controls": [
                            {
                                "control_id": "cis_v400_3_1",
                                "title": "Ensure CloudTrail is enabled in all regions",
                                "description": "AWS CloudTrail is a web service that records AWS API calls for your account.",
                                "severity": "high",
                                "tags": {"service": "cloudtrail", "category": "logging"},
                                "summary": {"alarm": 0, "ok": 1, "skip": 0, "error": 0},
                                "results": [
                                    {"resource": "arn:aws:cloudtrail:us-east-1:123456789012:trail/acme-org-trail", "status": "ok", "reason": "Multi-region trail is enabled"}
                                ]
                            }
                        ]
                    },
                    {
                        "title": "3.4 Ensure CloudTrail log file integrity validation is enabled",
                        "controls": [
                            {
                                "control_id": "cis_v400_3_4",
                                "title": "Ensure CloudTrail trails are integrated with CloudWatch Logs",
                                "description": "CloudTrail can be configured to send logs to CloudWatch Logs for real-time analysis.",
                                "severity": "medium",
                                "tags": {"service": "cloudtrail", "category": "monitoring"},
                                "summary": {"alarm": 0, "ok": 1, "skip": 0, "error": 0},
                                "results": [
                                    {"resource": "arn:aws:cloudtrail:us-east-1:123456789012:trail/acme-org-trail", "status": "ok", "reason": "Trail integrated with CloudWatch Logs"}
                                ]
                            }
                        ]
                    }
                ]
            },
            {
                "title": "4 Monitoring",
                "groups": [
                    {
                        "title": "4.3 Ensure a log metric filter and alarm exist for usage of root account",
                        "controls": [
                            {
                                "control_id": "cis_v400_4_3",
                                "title": "Ensure a log metric filter and alarm exist for usage of 'root' account",
                                "description": "Real-time monitoring of API calls can be achieved by directing CloudTrail Logs to CloudWatch Logs.",
                                "severity": "high",
                                "tags": {"service": "cloudwatch", "category": "monitoring"},
                                "summary": {"alarm": 1, "ok": 0, "skip": 0, "error": 0},
                                "results": [
                                    {"resource": "123456789012", "status": "alarm", "reason": "No metric filter/alarm for root account usage"}
                                ]
                            }
                        ]
                    }
                ]
            },
            {
                "title": "5 Networking",
                "groups": [
                    {
                        "title": "5.1 Ensure no Network ACLs allow ingress from 0.0.0.0/0 to remote administration ports",
                        "controls": [
                            {
                                "control_id": "cis_v400_5_1",
                                "title": "Ensure no Network ACLs allow ingress from 0.0.0.0/0 to remote server administration ports",
                                "description": "NACL rules should not allow unrestricted ingress to ports 22 and 3389.",
                                "severity": "high",
                                "tags": {"service": "vpc", "category": "network_security"},
                                "summary": {"alarm": 1, "ok": 3, "skip": 0, "error": 0},
                                "results": [
                                    {"resource": "acl-0dev001", "status": "alarm", "reason": "NACL allows 0.0.0.0/0 ingress to port 22"},
                                    {"resource": "acl-0prod001", "status": "ok", "reason": "No unrestricted admin port ingress"},
                                    {"resource": "acl-0prod002", "status": "ok", "reason": "No unrestricted admin port ingress"},
                                    {"resource": "acl-0prod003", "status": "ok", "reason": "No unrestricted admin port ingress"}
                                ]
                            }
                        ]
                    },
                    {
                        "title": "5.3 Ensure the default security group of every VPC restricts all traffic",
                        "controls": [
                            {
                                "control_id": "cis_v400_5_3",
                                "title": "Ensure the default security group of every VPC restricts all traffic",
                                "description": "Default security groups should restrict all inbound and outbound traffic.",
                                "severity": "medium",
                                "tags": {"service": "vpc", "category": "network_security"},
                                "summary": {"alarm": 1, "ok": 1, "skip": 0, "error": 0},
                                "results": [
                                    {"resource": "sg-default-dev", "status": "alarm", "reason": "Default security group allows inbound traffic"},
                                    {"resource": "sg-default-prod", "status": "ok", "reason": "Default security group restricts all traffic"}
                                ]
                            }
                        ]
                    }
                ]
            }
        ]
    }


def aws_pci_dss_benchmark_data():
    """Generate PCI DSS v4.0 benchmark results for AWS."""
    return {
        "title": "PCI DSS v4.0",
        "summary": {"status": {"alarm": 8, "ok": 62, "skip": 4, "error": 1, "info": 2}},
        "groups": [
            {
                "title": "Requirement 1 - Install and Maintain Network Security Controls",
                "groups": [
                    {"title": "1.2 Network security controls are configured and maintained", "controls": [
                        {"control_id": "pci_dss_v40_1_2_1", "title": "Restrict inbound traffic to only necessary services", "description": "Inbound traffic should be restricted.", "severity": "high", "tags": {"service": "vpc", "category": "network_security"},
                         "summary": {"alarm": 1, "ok": 3, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "sg-0a1b2c3d4e5f60004", "status": "alarm", "reason": "Security group allows unrestricted inbound on port 443 from 0.0.0.0/0"},
                             {"resource": "sg-0a1b2c3d4e5f60001", "status": "ok", "reason": "Inbound restricted to known CIDRs"},
                             {"resource": "sg-0a1b2c3d4e5f60002", "status": "ok", "reason": "Inbound restricted to VPC CIDR"},
                             {"resource": "sg-0a1b2c3d4e5f60003", "status": "ok", "reason": "Inbound restricted to bastion SG"},
                         ]},
                    ]}
                ]
            },
            {
                "title": "Requirement 3 - Protect Stored Account Data",
                "groups": [
                    {"title": "3.5 Primary account number (PAN) is secured wherever it is stored", "controls": [
                        {"control_id": "pci_dss_v40_3_5_1", "title": "Ensure S3 buckets storing PAN data use strong encryption", "description": "Data at rest must be encrypted.", "severity": "critical", "tags": {"service": "s3", "category": "encryption_at_rest"},
                         "summary": {"alarm": 1, "ok": 5, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "arn:aws:s3:::acme-ml-training-data", "status": "alarm", "reason": "No server-side encryption configured"},
                             {"resource": "arn:aws:s3:::acme-data-lake-prod", "status": "ok", "reason": "SSE-KMS encryption enabled"},
                             {"resource": "arn:aws:s3:::acme-logs-archive", "status": "ok", "reason": "SSE-KMS encryption enabled"},
                             {"resource": "arn:aws:s3:::acme-terraform-state", "status": "ok", "reason": "SSE-KMS encryption enabled"},
                             {"resource": "arn:aws:s3:::acme-backups-prod", "status": "ok", "reason": "SSE-KMS encryption enabled"},
                             {"resource": "arn:aws:s3:::acme-static-assets", "status": "ok", "reason": "SSE-S3 encryption enabled"},
                         ]},
                        {"control_id": "pci_dss_v40_3_5_2", "title": "Ensure RDS instances use encryption at rest", "description": "Database storage must be encrypted.", "severity": "critical", "tags": {"service": "rds", "category": "encryption_at_rest"},
                         "summary": {"alarm": 0, "ok": 3, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "acme-prod-postgres", "status": "ok", "reason": "Storage encryption enabled with KMS"},
                             {"resource": "acme-analytics-db", "status": "ok", "reason": "Storage encryption enabled with KMS"},
                             {"resource": "acme-dev-mysql", "status": "ok", "reason": "Storage encryption enabled with default key"},
                         ]},
                    ]}
                ]
            },
            {
                "title": "Requirement 7 - Restrict Access to System Components and Cardholder Data",
                "groups": [
                    {"title": "7.2 Access to system components and data is appropriately defined and assigned", "controls": [
                        {"control_id": "pci_dss_v40_7_2_1", "title": "Ensure IAM policies enforce least privilege", "description": "Access should be limited to what is needed.", "severity": "high", "tags": {"service": "iam", "category": "access_management"},
                         "summary": {"alarm": 2, "ok": 3, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "arn:aws:iam::123456789012:policy/LegacyAdminPolicy", "status": "alarm", "reason": "Policy grants *:* administrative access"},
                             {"resource": "arn:aws:iam::123456789012:role/admin-role", "status": "alarm", "reason": "Role has AdministratorAccess policy attached"},
                             {"resource": "arn:aws:iam::123456789012:role/eks-cluster-role", "status": "ok", "reason": "Role scoped to EKS actions only"},
                             {"resource": "arn:aws:iam::123456789012:role/lambda-execution-role", "status": "ok", "reason": "Role scoped to Lambda/CloudWatch actions"},
                             {"resource": "arn:aws:iam::123456789012:role/ci-cd-deploy-role", "status": "ok", "reason": "Role scoped to deployment actions"},
                         ]},
                    ]}
                ]
            },
            {
                "title": "Requirement 8 - Identify Users and Authenticate Access",
                "groups": [
                    {"title": "8.3 Strong authentication for users and administrators", "controls": [
                        {"control_id": "pci_dss_v40_8_3_6", "title": "Ensure MFA is enabled for all IAM users with console access", "description": "MFA must be enabled for all interactive accounts.", "severity": "critical", "tags": {"service": "iam", "category": "mfa"},
                         "summary": {"alarm": 2, "ok": 3, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "arn:aws:iam::123456789012:user/developer-1", "status": "alarm", "reason": "MFA not enabled"},
                             {"resource": "arn:aws:iam::123456789012:user/developer-2", "status": "alarm", "reason": "MFA not enabled"},
                             {"resource": "arn:aws:iam::123456789012:user/admin", "status": "ok", "reason": "Hardware MFA enabled"},
                             {"resource": "arn:aws:iam::123456789012:user/ops-lead", "status": "ok", "reason": "Virtual MFA enabled"},
                             {"resource": "arn:aws:iam::123456789012:user/security-admin", "status": "ok", "reason": "Hardware MFA enabled"},
                         ]},
                    ]}
                ]
            },
            {
                "title": "Requirement 10 - Log and Monitor All Access",
                "groups": [
                    {"title": "10.2 Audit logs are implemented to support the detection of anomalies", "controls": [
                        {"control_id": "pci_dss_v40_10_2_1", "title": "Ensure CloudTrail is enabled in all regions", "description": "Audit logging must cover all API activity.", "severity": "high", "tags": {"service": "cloudtrail", "category": "logging"},
                         "summary": {"alarm": 0, "ok": 1, "skip": 0, "error": 0},
                         "results": [{"resource": "arn:aws:cloudtrail:us-east-1:123456789012:trail/acme-org-trail", "status": "ok", "reason": "Multi-region trail enabled with log validation"}]},
                        {"control_id": "pci_dss_v40_10_2_2", "title": "Ensure VPC Flow Logs are enabled", "description": "Network flow logs must be captured.", "severity": "high", "tags": {"service": "vpc", "category": "logging"},
                         "summary": {"alarm": 1, "ok": 1, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "vpc-0a1b2c3d4e5f6002", "status": "alarm", "reason": "VPC Flow Logs not enabled on dev VPC"},
                             {"resource": "vpc-0a1b2c3d4e5f6001", "status": "ok", "reason": "VPC Flow Logs enabled and sending to CloudWatch"},
                         ]},
                    ]}
                ]
            },
        ]
    }


def aws_foundational_security_data():
    """Generate AWS Foundational Security Best Practices results."""
    return {
        "title": "AWS Foundational Security Best Practices",
        "summary": {"status": {"alarm": 6, "ok": 45, "skip": 3, "error": 0, "info": 1}},
        "groups": [
            {
                "title": "EC2",
                "controls": [
                    {"control_id": "ec2_1", "title": "EBS snapshots should not be publicly restorable", "description": "EBS snapshots should not be public.", "severity": "critical", "tags": {"service": "ec2", "category": "public_access"},
                     "summary": {"alarm": 0, "ok": 3, "skip": 0, "error": 0},
                     "results": [
                         {"resource": "snap-0a1b2c3d4e5f60001", "status": "ok", "reason": "Snapshot is private"},
                         {"resource": "snap-0a1b2c3d4e5f60002", "status": "ok", "reason": "Snapshot is private"},
                         {"resource": "snap-0a1b2c3d4e5f60003", "status": "ok", "reason": "Snapshot is private"},
                     ]},
                    {"control_id": "ec2_6", "title": "VPC flow logging should be enabled in all VPCs", "description": "Flow logging helps detect anomalous traffic.", "severity": "medium", "tags": {"service": "ec2", "category": "logging"},
                     "summary": {"alarm": 1, "ok": 1, "skip": 0, "error": 0},
                     "results": [
                         {"resource": "vpc-0a1b2c3d4e5f6002", "status": "alarm", "reason": "Flow logging is not enabled"},
                         {"resource": "vpc-0a1b2c3d4e5f6001", "status": "ok", "reason": "Flow logging is enabled"},
                     ]},
                ]
            },
            {
                "title": "S3",
                "controls": [
                    {"control_id": "s3_1", "title": "S3 Block Public Access should be enabled at the account level", "description": "Block public access settings should be enabled.", "severity": "high", "tags": {"service": "s3", "category": "public_access"},
                     "summary": {"alarm": 1, "ok": 0, "skip": 0, "error": 0},
                     "results": [{"resource": "123456789012", "status": "alarm", "reason": "Account-level S3 Block Public Access is not fully enabled"}]},
                    {"control_id": "s3_5", "title": "S3 buckets should require SSL", "description": "Bucket policies should require HTTPS.", "severity": "medium", "tags": {"service": "s3", "category": "encryption_in_transit"},
                     "summary": {"alarm": 2, "ok": 4, "skip": 0, "error": 0},
                     "results": [
                         {"resource": "arn:aws:s3:::acme-ml-training-data", "status": "alarm", "reason": "Bucket policy does not enforce SSL"},
                         {"resource": "arn:aws:s3:::acme-data-lake-prod", "status": "alarm", "reason": "Bucket policy does not enforce SSL"},
                         {"resource": "arn:aws:s3:::acme-static-assets", "status": "ok", "reason": "SSL enforced"},
                         {"resource": "arn:aws:s3:::acme-logs-archive", "status": "ok", "reason": "SSL enforced"},
                         {"resource": "arn:aws:s3:::acme-terraform-state", "status": "ok", "reason": "SSL enforced"},
                         {"resource": "arn:aws:s3:::acme-backups-prod", "status": "ok", "reason": "SSL enforced"},
                     ]},
                ]
            },
            {
                "title": "RDS",
                "controls": [
                    {"control_id": "rds_3", "title": "RDS DB instances should have encryption at-rest enabled", "description": "RDS encryption at rest protects data.", "severity": "medium", "tags": {"service": "rds", "category": "encryption_at_rest"},
                     "summary": {"alarm": 0, "ok": 3, "skip": 0, "error": 0},
                     "results": [
                         {"resource": "acme-prod-postgres", "status": "ok", "reason": "Encryption enabled"},
                         {"resource": "acme-analytics-db", "status": "ok", "reason": "Encryption enabled"},
                         {"resource": "acme-dev-mysql", "status": "ok", "reason": "Encryption enabled"},
                     ]},
                    {"control_id": "rds_2", "title": "RDS DB instances should prohibit public access", "description": "RDS instances should not be publicly accessible.", "severity": "critical", "tags": {"service": "rds", "category": "public_access"},
                     "summary": {"alarm": 1, "ok": 2, "skip": 0, "error": 0},
                     "results": [
                         {"resource": "acme-dev-mysql", "status": "alarm", "reason": "DB instance is publicly accessible"},
                         {"resource": "acme-prod-postgres", "status": "ok", "reason": "Not publicly accessible"},
                         {"resource": "acme-analytics-db", "status": "ok", "reason": "Not publicly accessible"},
                     ]},
                ]
            },
            {
                "title": "Lambda",
                "controls": [
                    {"control_id": "lambda_1", "title": "Lambda function policies should prohibit public access", "description": "Lambda functions should not be publicly invokable.", "severity": "critical", "tags": {"service": "lambda", "category": "public_access"},
                     "summary": {"alarm": 0, "ok": 3, "skip": 0, "error": 0},
                     "results": [
                         {"resource": "acme-webhook-handler", "status": "ok", "reason": "Not publicly accessible"},
                         {"resource": "acme-image-processor", "status": "ok", "reason": "Not publicly accessible"},
                         {"resource": "acme-cost-reporter", "status": "ok", "reason": "Not publicly accessible"},
                     ]},
                ]
            },
        ]
    }


def azure_cis_benchmark_data():
    """Generate CIS Azure Foundations Benchmark v2.1.0 results."""
    return {
        "title": "CIS Microsoft Azure Foundations Benchmark v2.1.0",
        "summary": {"status": {"alarm": 7, "ok": 48, "skip": 3, "error": 1, "info": 2}},
        "groups": [
            {
                "title": "1 Identity and Access Management",
                "groups": [
                    {"title": "1.1 Ensure Security Defaults is enabled on Azure Active Directory", "controls": [
                        {"control_id": "cis_v210_1_1_1", "title": "Ensure Security Defaults is enabled", "description": "Security Defaults provide basic identity security at no extra cost.", "severity": "high", "tags": {"service": "aad", "category": "identity"},
                         "summary": {"alarm": 0, "ok": 1, "skip": 0, "error": 0},
                         "results": [{"resource": "a1b2c3d4-e5f6-7890-abcd-ef1234567890", "status": "ok", "reason": "Security Defaults are enabled"}]},
                    ]},
                    {"title": "1.2 Ensure MFA is enabled for all users in all roles", "controls": [
                        {"control_id": "cis_v210_1_2_1", "title": "Ensure multi-factor authentication is enabled for all privileged users", "description": "MFA should be enabled for privileged roles.", "severity": "critical", "tags": {"service": "aad", "category": "mfa"},
                         "summary": {"alarm": 1, "ok": 2, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "user:service-account-01@acme.onmicrosoft.com", "status": "alarm", "reason": "Service account with Global Admin role does not have MFA"},
                             {"resource": "user:admin@acme.onmicrosoft.com", "status": "ok", "reason": "MFA enabled via Conditional Access"},
                             {"resource": "user:security-admin@acme.onmicrosoft.com", "status": "ok", "reason": "MFA enabled via Conditional Access"},
                         ]},
                    ]},
                ]
            },
            {
                "title": "4 Database Services",
                "groups": [
                    {"title": "4.1 SQL Server", "controls": [
                        {"control_id": "cis_v210_4_1_1", "title": "Ensure SQL server audit is enabled", "description": "Auditing SQL operations is essential for compliance.", "severity": "medium", "tags": {"service": "sql", "category": "logging"},
                         "summary": {"alarm": 0, "ok": 1, "skip": 0, "error": 0},
                         "results": [{"resource": "/subscriptions/a1b2c3d4/providers/Microsoft.Sql/servers/acme-sql-prod", "status": "ok", "reason": "Auditing enabled with 90-day retention"}]},
                    ]},
                ]
            },
            {
                "title": "5 Logging and Monitoring",
                "groups": [
                    {"title": "5.1 Ensure diagnostic settings exist for key services", "controls": [
                        {"control_id": "cis_v210_5_1_1", "title": "Ensure diagnostic setting captures Administrative and Security log categories", "description": "Activity log should capture admin and security events.", "severity": "high", "tags": {"service": "monitor", "category": "logging"},
                         "summary": {"alarm": 1, "ok": 0, "skip": 0, "error": 0},
                         "results": [{"resource": "a1b2c3d4-e5f6-7890-abcd-ef1234567890", "status": "alarm", "reason": "No diagnostic setting captures all required log categories"}]},
                    ]},
                ]
            },
            {
                "title": "6 Networking",
                "groups": [
                    {"title": "6.1 Ensure Network Security Groups", "controls": [
                        {"control_id": "cis_v210_6_1", "title": "Ensure that RDP access from the Internet is evaluated and restricted", "description": "NSGs should not allow unrestricted RDP access.", "severity": "high", "tags": {"service": "network", "category": "network_security"},
                         "summary": {"alarm": 0, "ok": 1, "skip": 0, "error": 0},
                         "results": [{"resource": "/subscriptions/a1b2c3d4/resourceGroups/acme-networking/providers/Microsoft.Network/networkSecurityGroups/hub-nsg", "status": "ok", "reason": "No inbound RDP from 0.0.0.0/0"}]},
                        {"control_id": "cis_v210_6_2", "title": "Ensure that SSH access from the Internet is evaluated and restricted", "description": "NSGs should not allow unrestricted SSH access.", "severity": "high", "tags": {"service": "network", "category": "network_security"},
                         "summary": {"alarm": 0, "ok": 1, "skip": 0, "error": 0},
                         "results": [{"resource": "/subscriptions/a1b2c3d4/resourceGroups/acme-networking/providers/Microsoft.Network/networkSecurityGroups/hub-nsg", "status": "ok", "reason": "No inbound SSH from 0.0.0.0/0"}]},
                    ]},
                    {"title": "6.5 Ensure Network Watcher", "controls": [
                        {"control_id": "cis_v210_6_5", "title": "Ensure Network Watcher is enabled for all regions", "description": "Network Watcher provides monitoring and diagnostic tools.", "severity": "medium", "tags": {"service": "network", "category": "monitoring"},
                         "summary": {"alarm": 1, "ok": 1, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "westus2", "status": "alarm", "reason": "Network Watcher not enabled in westus2"},
                             {"resource": "eastus", "status": "ok", "reason": "Network Watcher enabled"},
                         ]},
                    ]},
                ]
            },
            {
                "title": "7 Virtual Machines",
                "groups": [
                    {"title": "7.1 Ensure managed disks are encrypted", "controls": [
                        {"control_id": "cis_v210_7_1", "title": "Ensure Virtual Machines are utilizing Managed Disks", "description": "VMs should use managed disks for reliability.", "severity": "medium", "tags": {"service": "compute", "category": "encryption_at_rest"},
                         "summary": {"alarm": 0, "ok": 2, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "/subscriptions/a1b2c3d4/resourceGroups/acme-prod/providers/Microsoft.Compute/virtualMachines/hub-firewall", "status": "ok", "reason": "Using managed disks with encryption"},
                             {"resource": "/subscriptions/a1b2c3d4/resourceGroups/acme-prod/providers/Microsoft.Compute/virtualMachines/ad-controller", "status": "ok", "reason": "Using managed disks with encryption"},
                         ]},
                    ]},
                ]
            },
            {
                "title": "8 Key Vault",
                "groups": [
                    {"title": "8.1 Ensure Key Vault is recoverable", "controls": [
                        {"control_id": "cis_v210_8_1", "title": "Ensure that the expiration date is set on all keys and secrets", "description": "Keys and secrets should have expiration dates.", "severity": "medium", "tags": {"service": "keyvault", "category": "key_management"},
                         "summary": {"alarm": 2, "ok": 3, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "acme-prod-kv/keys/app-encryption-key", "status": "alarm", "reason": "Key has no expiration date set"},
                             {"resource": "acme-prod-kv/secrets/db-connection-string", "status": "alarm", "reason": "Secret has no expiration date set"},
                             {"resource": "acme-prod-kv/keys/tls-cert-key", "status": "ok", "reason": "Expiration set to 2026-01-15"},
                             {"resource": "acme-prod-kv/secrets/api-key", "status": "ok", "reason": "Expiration set to 2026-06-01"},
                             {"resource": "acme-prod-kv/secrets/storage-key", "status": "ok", "reason": "Expiration set to 2026-03-15"},
                         ]},
                    ]},
                ]
            },
        ]
    }


def gcp_cis_benchmark_data():
    """Generate CIS GCP Foundations Benchmark v4.0.0 results."""
    return {
        "title": "CIS Google Cloud Platform Foundation Benchmark v4.0.0",
        "summary": {"status": {"alarm": 9, "ok": 52, "skip": 2, "error": 0, "info": 1}},
        "groups": [
            {
                "title": "1 Identity and Access Management",
                "groups": [
                    {"title": "1.1 Ensure IAM best practices", "controls": [
                        {"control_id": "cis_v400_1_4", "title": "Ensure that Service Account has no admin privileges", "description": "Service accounts should not have admin roles.", "severity": "critical", "tags": {"service": "iam", "category": "access_management"},
                         "summary": {"alarm": 1, "ok": 3, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "acme-prod-123456/sa-legacy-pipeline@acme-prod-123456.iam.gserviceaccount.com", "status": "alarm", "reason": "Service account has roles/owner"},
                             {"resource": "acme-prod-123456/sa-deployer@acme-prod-123456.iam.gserviceaccount.com", "status": "ok", "reason": "No admin roles"},
                             {"resource": "acme-prod-123456/sa-reader@acme-prod-123456.iam.gserviceaccount.com", "status": "ok", "reason": "No admin roles"},
                             {"resource": "acme-prod-123456/sa-functions@acme-prod-123456.iam.gserviceaccount.com", "status": "ok", "reason": "No admin roles"},
                         ]},
                        {"control_id": "cis_v400_1_6", "title": "Ensure user-managed service account keys are rotated within 90 days", "description": "Service account keys should be rotated regularly.", "severity": "high", "tags": {"service": "iam", "category": "key_management"},
                         "summary": {"alarm": 2, "ok": 1, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "sa-legacy-pipeline@acme-prod-123456.iam.gserviceaccount.com/key-001", "status": "alarm", "reason": "Key age 214 days exceeds 90 day limit"},
                             {"resource": "sa-deployer@acme-prod-123456.iam.gserviceaccount.com/key-001", "status": "alarm", "reason": "Key age 127 days exceeds 90 day limit"},
                             {"resource": "sa-reader@acme-prod-123456.iam.gserviceaccount.com/key-001", "status": "ok", "reason": "Key age 45 days within limit"},
                         ]},
                    ]},
                ]
            },
            {
                "title": "2 Logging and Monitoring",
                "groups": [
                    {"title": "2.1 Ensure Cloud Audit Logging", "controls": [
                        {"control_id": "cis_v400_2_1", "title": "Ensure Cloud Audit Logging is configured properly", "description": "Audit logs should capture admin activity and data access.", "severity": "high", "tags": {"service": "logging", "category": "logging"},
                         "summary": {"alarm": 1, "ok": 1, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "acme-prod-123456", "status": "alarm", "reason": "Data Access audit logs not enabled for all services"},
                             {"resource": "acme-prod-123456/admin-activity", "status": "ok", "reason": "Admin Activity audit logs enabled"},
                         ]},
                    ]},
                ]
            },
            {
                "title": "3 Networking",
                "groups": [
                    {"title": "3.6 Ensure firewall rules", "controls": [
                        {"control_id": "cis_v400_3_6", "title": "Ensure SSH access is restricted from the internet", "description": "Firewall rules should not allow SSH from 0.0.0.0/0.", "severity": "high", "tags": {"service": "compute", "category": "network_security"},
                         "summary": {"alarm": 0, "ok": 2, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "allow-internal", "status": "ok", "reason": "No SSH from 0.0.0.0/0"},
                             {"resource": "allow-https", "status": "ok", "reason": "Only allows TCP 443"},
                         ]},
                        {"control_id": "cis_v400_3_7", "title": "Ensure RDP access is restricted from the internet", "description": "Firewall rules should not allow RDP from 0.0.0.0/0.", "severity": "high", "tags": {"service": "compute", "category": "network_security"},
                         "summary": {"alarm": 0, "ok": 2, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "allow-internal", "status": "ok", "reason": "No RDP from 0.0.0.0/0"},
                             {"resource": "allow-https", "status": "ok", "reason": "Only allows TCP 443"},
                         ]},
                    ]},
                ]
            },
            {
                "title": "5 Storage",
                "groups": [
                    {"title": "5.1 Ensure Cloud Storage", "controls": [
                        {"control_id": "cis_v400_5_1", "title": "Ensure Cloud Storage buckets are not anonymously or publicly accessible", "description": "Buckets should not be publicly accessible.", "severity": "critical", "tags": {"service": "storage", "category": "public_access"},
                         "summary": {"alarm": 0, "ok": 3, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "acme-data-warehouse", "status": "ok", "reason": "Not publicly accessible"},
                             {"resource": "acme-tf-state-gcp", "status": "ok", "reason": "Not publicly accessible"},
                             {"resource": "acme-logs-gcp", "status": "ok", "reason": "Not publicly accessible"},
                         ]},
                        {"control_id": "cis_v400_5_2", "title": "Ensure Cloud Storage buckets have uniform bucket-level access enabled", "description": "Uniform access simplifies permission management.", "severity": "medium", "tags": {"service": "storage", "category": "access_management"},
                         "summary": {"alarm": 1, "ok": 2, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "acme-data-warehouse", "status": "alarm", "reason": "Uniform bucket-level access not enabled"},
                             {"resource": "acme-tf-state-gcp", "status": "ok", "reason": "Uniform access enabled"},
                             {"resource": "acme-logs-gcp", "status": "ok", "reason": "Uniform access enabled"},
                         ]},
                    ]},
                ]
            },
            {
                "title": "6 Cloud SQL",
                "groups": [
                    {"title": "6.1 Cloud SQL Database Services", "controls": [
                        {"control_id": "cis_v400_6_2", "title": "Ensure Cloud SQL instances are not open to the world", "description": "Cloud SQL should not have 0.0.0.0/0 in authorized networks.", "severity": "critical", "tags": {"service": "sql", "category": "network_security"},
                         "summary": {"alarm": 0, "ok": 1, "skip": 0, "error": 0},
                         "results": [{"resource": "acme-prod-cloudsql", "status": "ok", "reason": "No public IP authorized networks"}]},
                        {"control_id": "cis_v400_6_4", "title": "Ensure Cloud SQL instances are configured with automated backups", "description": "Automated backups ensure data recovery.", "severity": "high", "tags": {"service": "sql", "category": "backup"},
                         "summary": {"alarm": 0, "ok": 1, "skip": 0, "error": 0},
                         "results": [{"resource": "acme-prod-cloudsql", "status": "ok", "reason": "Automated backups enabled with 7-day retention"}]},
                    ]},
                ]
            },
            {
                "title": "7 Cloud KMS",
                "groups": [
                    {"title": "7.1 Key Management", "controls": [
                        {"control_id": "cis_v400_7_2", "title": "Ensure KMS encryption keys are rotated within 365 days", "description": "Encryption keys should be rotated periodically.", "severity": "medium", "tags": {"service": "kms", "category": "key_management"},
                         "summary": {"alarm": 1, "ok": 0, "skip": 0, "error": 0},
                         "results": [{"resource": "acme-keyring/app-key", "status": "alarm", "reason": "Key rotation period not configured"}]},
                    ]},
                ]
            },
        ]
    }


def gcp_nist_benchmark_data():
    """Generate NIST 800-53 Rev 5 benchmark results for GCP."""
    return {
        "title": "NIST 800-53 Revision 5 (GCP)",
        "summary": {"status": {"alarm": 6, "ok": 38, "skip": 3, "error": 0, "info": 1}},
        "groups": [
            {
                "title": "AC Access Control",
                "groups": [
                    {"title": "AC-2 Account Management", "controls": [
                        {"control_id": "nist_800_53_ac_2_gcp", "title": "Ensure service accounts are managed and reviewed", "description": "Unused or over-privileged service accounts should be identified.", "severity": "high", "tags": {"service": "iam", "category": "access_management"},
                         "summary": {"alarm": 1, "ok": 3, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "sa-legacy-pipeline@acme-prod-123456.iam.gserviceaccount.com", "status": "alarm", "reason": "Service account not used in 180+ days"},
                             {"resource": "sa-deployer@acme-prod-123456.iam.gserviceaccount.com", "status": "ok", "reason": "Active within 30 days"},
                             {"resource": "sa-reader@acme-prod-123456.iam.gserviceaccount.com", "status": "ok", "reason": "Active within 30 days"},
                             {"resource": "sa-functions@acme-prod-123456.iam.gserviceaccount.com", "status": "ok", "reason": "Active within 30 days"},
                         ]},
                    ]},
                    {"title": "AC-6 Least Privilege", "controls": [
                        {"control_id": "nist_800_53_ac_6_gcp", "title": "Ensure IAM roles follow least privilege principle", "description": "Roles should not grant broad permissions.", "severity": "high", "tags": {"service": "iam", "category": "access_management"},
                         "summary": {"alarm": 1, "ok": 2, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "sa-legacy-pipeline@acme-prod-123456.iam.gserviceaccount.com", "status": "alarm", "reason": "Has roles/owner — overly broad"},
                             {"resource": "sa-deployer@acme-prod-123456.iam.gserviceaccount.com", "status": "ok", "reason": "Uses custom role with scoped permissions"},
                             {"resource": "sa-reader@acme-prod-123456.iam.gserviceaccount.com", "status": "ok", "reason": "Has roles/viewer only"},
                         ]},
                    ]},
                ]
            },
            {
                "title": "AU Audit and Accountability",
                "groups": [
                    {"title": "AU-2 Audit Events", "controls": [
                        {"control_id": "nist_800_53_au_2_gcp", "title": "Ensure Cloud Audit Logs are enabled for all services", "description": "Admin Activity and Data Access logs should be enabled.", "severity": "high", "tags": {"service": "logging", "category": "logging"},
                         "summary": {"alarm": 1, "ok": 1, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "acme-prod-123456/data-access", "status": "alarm", "reason": "Data Access logs not enabled for Cloud Storage"},
                             {"resource": "acme-prod-123456/admin-activity", "status": "ok", "reason": "Admin Activity logs enabled for all services"},
                         ]},
                    ]},
                    {"title": "AU-12 Audit Generation", "controls": [
                        {"control_id": "nist_800_53_au_12_gcp", "title": "Ensure log sinks are configured for all audit logs", "description": "Audit logs should be exported to a sink for long-term retention.", "severity": "medium", "tags": {"service": "logging", "category": "logging"},
                         "summary": {"alarm": 0, "ok": 1, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "acme-prod-123456/audit-sink", "status": "ok", "reason": "Log sink configured to Cloud Storage bucket"},
                         ]},
                    ]},
                ]
            },
            {
                "title": "SC System and Communications Protection",
                "groups": [
                    {"title": "SC-7 Boundary Protection", "controls": [
                        {"control_id": "nist_800_53_sc_7_gcp", "title": "Ensure VPC firewall rules restrict ingress from 0.0.0.0/0", "description": "Firewall rules should not allow unrestricted access from the internet.", "severity": "critical", "tags": {"service": "compute", "category": "network_security"},
                         "summary": {"alarm": 0, "ok": 2, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "allow-internal", "status": "ok", "reason": "No unrestricted ingress from 0.0.0.0/0"},
                             {"resource": "allow-https", "status": "ok", "reason": "Only allows TCP 443"},
                         ]},
                    ]},
                    {"title": "SC-8 Transmission Confidentiality", "controls": [
                        {"control_id": "nist_800_53_sc_8_gcp", "title": "Ensure Cloud SQL connections require SSL", "description": "Database connections should enforce encryption in transit.", "severity": "high", "tags": {"service": "sql", "category": "encryption_in_transit"},
                         "summary": {"alarm": 1, "ok": 0, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "acme-prod-cloudsql", "status": "alarm", "reason": "SSL not enforced for all connections"},
                         ]},
                    ]},
                    {"title": "SC-28 Protection of Information at Rest", "controls": [
                        {"control_id": "nist_800_53_sc_28_gcp", "title": "Ensure Cloud Storage buckets use customer-managed encryption keys", "description": "CMEK provides additional control over data encryption.", "severity": "medium", "tags": {"service": "storage", "category": "encryption_at_rest"},
                         "summary": {"alarm": 1, "ok": 2, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "acme-data-warehouse", "status": "alarm", "reason": "Using Google-managed encryption key instead of CMEK"},
                             {"resource": "acme-tf-state-gcp", "status": "ok", "reason": "CMEK configured"},
                             {"resource": "acme-logs-gcp", "status": "ok", "reason": "CMEK configured"},
                         ]},
                    ]},
                ]
            },
            {
                "title": "IA Identification and Authentication",
                "groups": [
                    {"title": "IA-5 Authenticator Management", "controls": [
                        {"control_id": "nist_800_53_ia_5_gcp", "title": "Ensure service account keys are rotated within 90 days", "description": "Service account keys should be rotated regularly.", "severity": "high", "tags": {"service": "iam", "category": "key_management"},
                         "summary": {"alarm": 1, "ok": 1, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "sa-legacy-pipeline/key-001", "status": "alarm", "reason": "Key age 214 days exceeds 90 day limit"},
                             {"resource": "sa-reader/key-001", "status": "ok", "reason": "Key age 45 days within limit"},
                         ]},
                    ]},
                ]
            },
        ]
    }


def azure_nist_benchmark_data():
    """Generate NIST 800-53 Rev 5 benchmark results for Azure."""
    return {
        "title": "NIST 800-53 Revision 5 (Azure)",
        "summary": {"status": {"alarm": 5, "ok": 41, "skip": 2, "error": 0, "info": 1}},
        "groups": [
            {
                "title": "AC Access Control",
                "groups": [
                    {"title": "AC-2 Account Management", "controls": [
                        {"control_id": "nist_800_53_ac_2_azure", "title": "Ensure guest users are reviewed regularly", "description": "Guest accounts in Azure AD should be reviewed and removed when no longer needed.", "severity": "medium", "tags": {"service": "aad", "category": "identity"},
                         "summary": {"alarm": 1, "ok": 2, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "user:vendor-contractor@external.com", "status": "alarm", "reason": "Guest user inactive for 120+ days"},
                             {"resource": "user:partner-integration@partner.com", "status": "ok", "reason": "Active within 30 days"},
                             {"resource": "user:auditor@audit-firm.com", "status": "ok", "reason": "Active within 30 days"},
                         ]},
                    ]},
                    {"title": "AC-6 Least Privilege", "controls": [
                        {"control_id": "nist_800_53_ac_6_azure", "title": "Ensure custom RBAC roles are reviewed", "description": "Custom roles should follow the principle of least privilege.", "severity": "high", "tags": {"service": "rbac", "category": "access_management"},
                         "summary": {"alarm": 0, "ok": 2, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "acme-deployer-role", "status": "ok", "reason": "Scoped to resource group only"},
                             {"resource": "acme-reader-role", "status": "ok", "reason": "Read-only permissions"},
                         ]},
                    ]},
                ]
            },
            {
                "title": "AU Audit and Accountability",
                "groups": [
                    {"title": "AU-6 Audit Review, Analysis, and Reporting", "controls": [
                        {"control_id": "nist_800_53_au_6_azure", "title": "Ensure Activity Log alerts are configured for key operations", "description": "Alerts should notify admins of security-relevant operations.", "severity": "medium", "tags": {"service": "monitor", "category": "logging"},
                         "summary": {"alarm": 1, "ok": 2, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "alert:delete-security-solution", "status": "alarm", "reason": "No Activity Log alert for deleting Security Solution"},
                             {"resource": "alert:create-policy-assignment", "status": "ok", "reason": "Alert configured"},
                             {"resource": "alert:create-update-nsg", "status": "ok", "reason": "Alert configured"},
                         ]},
                    ]},
                ]
            },
            {
                "title": "SC System and Communications Protection",
                "groups": [
                    {"title": "SC-7 Boundary Protection", "controls": [
                        {"control_id": "nist_800_53_sc_7_azure", "title": "Ensure NSGs restrict inbound traffic to necessary ports only", "description": "Network Security Groups should not allow unrestricted access.", "severity": "high", "tags": {"service": "network", "category": "network_security"},
                         "summary": {"alarm": 0, "ok": 1, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "/subscriptions/a1b2c3d4/resourceGroups/acme-networking/providers/Microsoft.Network/networkSecurityGroups/hub-nsg", "status": "ok", "reason": "All rules scoped to specific CIDR ranges"},
                         ]},
                    ]},
                    {"title": "SC-8 Transmission Confidentiality", "controls": [
                        {"control_id": "nist_800_53_sc_8_azure", "title": "Ensure HTTPS-only access is enforced on Storage Accounts", "description": "Storage accounts should require HTTPS for all access.", "severity": "high", "tags": {"service": "storage", "category": "encryption_in_transit"},
                         "summary": {"alarm": 0, "ok": 2, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "acmeproddata", "status": "ok", "reason": "HTTPS-only enabled"},
                             {"resource": "acmelogsarchive", "status": "ok", "reason": "HTTPS-only enabled"},
                         ]},
                    ]},
                    {"title": "SC-28 Protection of Information at Rest", "controls": [
                        {"control_id": "nist_800_53_sc_28_azure", "title": "Ensure Storage Account encryption uses customer-managed keys", "description": "CMEK provides enhanced control over data encryption.", "severity": "medium", "tags": {"service": "storage", "category": "encryption_at_rest"},
                         "summary": {"alarm": 1, "ok": 1, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "acmeproddata", "status": "alarm", "reason": "Using Microsoft-managed key instead of CMEK"},
                             {"resource": "acmelogsarchive", "status": "ok", "reason": "CMEK configured via Key Vault"},
                         ]},
                    ]},
                ]
            },
            {
                "title": "IA Identification and Authentication",
                "groups": [
                    {"title": "IA-2 Identification and Authentication", "controls": [
                        {"control_id": "nist_800_53_ia_2_azure", "title": "Ensure MFA is enabled for all users", "description": "Multi-factor authentication should be required for all users.", "severity": "critical", "tags": {"service": "aad", "category": "mfa"},
                         "summary": {"alarm": 1, "ok": 2, "skip": 0, "error": 0},
                         "results": [
                             {"resource": "user:service-account-01@acme.onmicrosoft.com", "status": "alarm", "reason": "MFA not enforced for service account"},
                             {"resource": "user:admin@acme.onmicrosoft.com", "status": "ok", "reason": "MFA enabled via Conditional Access"},
                             {"resource": "user:security-admin@acme.onmicrosoft.com", "status": "ok", "reason": "MFA enabled via Conditional Access"},
                         ]},
                    ]},
                ]
            },
        ]
    }


# ═══════════════════════════════════════════════════════════════════════════
# Main seed function
# ═══════════════════════════════════════════════════════════════════════════

def seed(db, fernet):
    # Skip if already seeded
    if db.projects.count_documents({}) > 0:
        print("Demo data already exists, skipping.")
        return

    audit = {"created_at": iso(NOW), "updated_at": iso(NOW), "created_by": "admin@qubiva.local", "updated_by": "admin@qubiva.local"}

    # ── Admin user ──────────────────────────────────────────────────────
    if db.users.count_documents({"username": "admin@qubiva.local"}) == 0:
        db.users.insert_one({
            "username": "admin@qubiva.local",
            "hashed_password": bcrypt.hashpw(b"Demo@2026", bcrypt.gensalt(rounds=12)).decode(),
            "projects": ["acme-platform", "finops-dashboard"],
            "org_roles": ["org_admin"],
            **audit,
        })
        print("  Created admin user")

    # ── Users ───────────────────────────────────────────────────────────
    demo_users = [
        {"username": "sarah@example.com", "org_roles": ["org_editor"], "projects": ["acme-platform"]},
        {"username": "james@example.com", "org_roles": ["org_viewer"], "projects": ["acme-platform", "finops-dashboard"]},
    ]
    for u in demo_users:
        if db.users.count_documents({"username": u["username"]}) == 0:
            db.users.insert_one({
                "username": u["username"],
                "hashed_password": bcrypt.hashpw(b"Demo@2026", bcrypt.gensalt(rounds=12)).decode(),
                "projects": u["projects"],
                "org_roles": u["org_roles"],
                **audit,
            })
    print("  Created demo users")

    # ── Projects ────────────────────────────────────────────────────────
    db.projects.insert_many([
        {
            "project_name": "acme-platform",
            "description": "Core cloud infrastructure for the ACME platform — multi-region EKS, RDS, S3, and supporting services.",
            "members": [
                {"username": "admin@qubiva.local", "roles": ["admin"]},
                {"username": "sarah@example.com", "roles": ["editor"]},
                {"username": "james@example.com", "roles": ["viewer"]},
            ],
            "variables": {"environment": "production", "region": "us-east-1", "cost_center": "eng-1001"},
            "secrets": {},
            **audit,
        },
        {
            "project_name": "finops-dashboard",
            "description": "FinOps cost visibility and optimization across all cloud accounts.",
            "members": [
                {"username": "admin@qubiva.local", "roles": ["admin"]},
                {"username": "james@example.com", "roles": ["editor"]},
            ],
            "variables": {"environment": "staging", "budget_alert_threshold": "80"},
            "secrets": {},
            **audit,
        },
    ])
    print("  Created projects")

    # ── Cloud accounts ──────────────────────────────────────────────────
    db.cloud_accounts.insert_many([
        {
            "project_name": "acme-platform",
            "cloud_platform": "aws",
            "account_id": "123456789012",
            "auth_secrets": {
                "type": "key_pair",
                "access_key_id": encrypt(fernet, "AKIAIOSFODNN7EXAMPLE"),
                "secret_access_key": encrypt(fernet, "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"),
            },
            "variables": {"region": "us-east-1"},
            "secrets": {},
            **audit,
        },
        {
            "project_name": "acme-platform",
            "cloud_platform": "azure",
            "account_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "auth_secrets": {
                "type": "azure_service_principal",
                "azure_client_id": "11111111-2222-3333-4444-555555555555",
                "azure_tenant_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "azure_client_secret": encrypt(fernet, "demo~secret~value~EXAMPLE"),
            },
            "variables": {"subscription": "Production"},
            "secrets": {},
            **audit,
        },
        {
            "project_name": "acme-platform",
            "cloud_platform": "gcp",
            "account_id": "acme-prod-123456",
            "auth_secrets": {
                "type": "gcp_service_account",
                "gcp_project_id": "acme-prod-123456",
                "gcp_service_account_key": encrypt(fernet, '{"type":"service_account","project_id":"acme-prod-123456"}'),
            },
            "variables": {"region": "us-central1"},
            "secrets": {},
            **audit,
        },
        {
            "project_name": "finops-dashboard",
            "cloud_platform": "aws",
            "account_id": "987654321098",
            "auth_secrets": {
                "type": "key_pair",
                "access_key_id": encrypt(fernet, "AKIAI44QH8DHBEXAMPLE"),
                "secret_access_key": encrypt(fernet, "je7MtGbClwBF/2Zp9Utk/h3yCo8nvbEXAMPLEKEY"),
            },
            "variables": {"region": "eu-west-1"},
            "secrets": {},
            **audit,
        },
    ])
    print("  Created cloud accounts")

    # ── Workspaces ──────────────────────────────────────────────────────
    db.workspaces.insert_many([
        {
            "project_name": "acme-platform",
            "name": "network-prod",
            "description": "Production VPC, subnets, NAT gateways, and transit gateway.",
            "variables": {"vpc_cidr": "10.0.0.0/16"},
            "secrets": {},
            "terraform_version": "1.9.0",
            "github_repo_name": "",
            "cloud_account": "123456789012",
            "cloud_platform": "aws",
            "tf_backend_type": "kubernetes",
            "tf_backend_statefile_path": "acme-platform/network-prod",
            "locked": False,
            **audit,
        },
        {
            "project_name": "acme-platform",
            "name": "eks-cluster",
            "description": "EKS cluster with managed node groups and add-ons.",
            "variables": {"cluster_version": "1.30", "node_instance_type": "m6i.xlarge"},
            "secrets": {},
            "terraform_version": "1.9.0",
            "github_repo_name": "",
            "cloud_account": "123456789012",
            "cloud_platform": "aws",
            "tf_backend_type": "kubernetes",
            "tf_backend_statefile_path": "acme-platform/eks-cluster",
            "locked": False,
            **audit,
        },
        {
            "project_name": "acme-platform",
            "name": "azure-landing-zone",
            "description": "Azure landing zone — resource groups, policies, and networking.",
            "variables": {"location": "eastus"},
            "secrets": {},
            "terraform_version": "1.9.0",
            "github_repo_name": "",
            "cloud_account": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "cloud_platform": "azure",
            "tf_backend_type": "kubernetes",
            "tf_backend_statefile_path": "acme-platform/azure-landing-zone",
            "locked": False,
            **audit,
        },
        {
            "project_name": "finops-dashboard",
            "name": "cost-collector",
            "description": "Lambda functions and S3 buckets for CUR data collection and aggregation.",
            "variables": {"cur_bucket": "finops-cur-data"},
            "secrets": {},
            "terraform_version": "1.9.0",
            "github_repo_name": "",
            "cloud_account": "987654321098",
            "cloud_platform": "aws",
            "tf_backend_type": "kubernetes",
            "tf_backend_statefile_path": "finops-dashboard/cost-collector",
            "locked": False,
            **audit,
        },
    ])
    print("  Created workspaces")

    # ── Tasks (acme-platform) ────────────────────────────────────────────
    acme_tasks = [
        {"id": "ACME-1", "title": "Upgrade EKS to 1.31", "description": "Cluster upgrade from 1.30 to 1.31 with zero-downtime rolling update.", "type": "task", "status": "in_progress", "priority": "high", "assignedTo": "admin@qubiva.local", "dueDate": iso(NOW + timedelta(days=7))},
        {"id": "ACME-2", "title": "Enable GuardDuty across all regions", "description": "Enable AWS GuardDuty in all active regions for threat detection.", "type": "task", "status": "todo", "priority": "medium", "assignedTo": "admin@qubiva.local", "dueDate": iso(NOW + timedelta(days=14))},
        {"id": "ACME-3", "title": "Migrate RDS to Aurora Serverless v2", "description": "Move PostgreSQL RDS to Aurora Serverless v2 for cost optimization and auto-scaling.", "type": "task", "status": "todo", "priority": "low", "assignedTo": "sarah@example.com", "dueDate": None},
        {"id": "ACME-4", "title": "Fix S3 bucket policy for public access", "description": "Remediate public access findings from compliance scan on data-lake bucket.", "type": "bug", "status": "done", "priority": "critical", "assignedTo": "sarah@example.com", "dueDate": iso(NOW - timedelta(days=3))},
        {"id": "ACME-5", "title": "Set up Azure landing zone networking", "description": "Deploy hub-spoke VNet topology with peering and NSG rules.", "type": "task", "status": "in_progress", "priority": "high", "assignedTo": "james@example.com", "dueDate": iso(NOW + timedelta(days=10))},
        {"id": "ACME-6", "title": "Review IAM policies for least privilege", "description": "Audit and tighten IAM roles across all AWS accounts.", "type": "task", "status": "blocked", "priority": "high", "assignedTo": "admin@qubiva.local", "dueDate": iso(NOW + timedelta(days=5))},
    ]
    for t in acme_tasks:
        db.tasks.insert_one({**t, "project_name": "acme-platform", "tags": [], "relationships": [], "sprintId": None, **audit})
    print("  Created acme-platform tasks")

    # ── Tasks (finops-dashboard) ─────────────────────────────────────────
    finops_tasks = [
        {"id": "FIN-1", "title": "Set up CUR data pipeline", "description": "Configure AWS Cost and Usage Report export to S3 and Lambda aggregation.", "type": "task", "status": "done", "priority": "high", "assignedTo": "admin@qubiva.local", "dueDate": iso(NOW - timedelta(days=5))},
        {"id": "FIN-2", "title": "Build cost anomaly detection", "description": "Implement Z-score based anomaly detection on daily cost data.", "type": "task", "status": "in_progress", "priority": "high", "assignedTo": "admin@qubiva.local", "dueDate": iso(NOW + timedelta(days=3))},
        {"id": "FIN-3", "title": "Create budget alert thresholds", "description": "Set up alerts when spending exceeds 80% and 100% of monthly budget.", "type": "task", "status": "todo", "priority": "medium", "assignedTo": "james@example.com", "dueDate": iso(NOW + timedelta(days=10))},
        {"id": "FIN-4", "title": "Fix duplicate cost entries in EU region", "description": "Lambda aggregator is double-counting some eu-west-1 line items.", "type": "bug", "status": "todo", "priority": "high", "assignedTo": "james@example.com", "dueDate": iso(NOW + timedelta(days=2))},
    ]
    for t in finops_tasks:
        db.tasks.insert_one({**t, "project_name": "finops-dashboard", "tags": [], "relationships": [], "sprintId": None, **audit})
    print("  Created finops-dashboard tasks")

    # ── IaC run history ─────────────────────────────────────────────────
    iac_runs = [
        {"request_id": "run-001", "project_name": "acme-platform", "workspace_name": "network-prod", "phases": ["init", "plan", "apply"], "state": "completed", "offset_days": -14},
        {"request_id": "run-002", "project_name": "acme-platform", "workspace_name": "eks-cluster", "phases": ["init", "plan", "apply"], "state": "completed", "offset_days": -10},
        {"request_id": "run-003", "project_name": "acme-platform", "workspace_name": "network-prod", "phases": ["init", "plan", "apply"], "state": "completed", "offset_days": -7},
        {"request_id": "run-004", "project_name": "acme-platform", "workspace_name": "eks-cluster", "phases": ["init", "plan", "apply"], "state": "failed", "offset_days": -5, "error": "Error: creating EKS Node Group: operation error EKS: CreateNodegroup, ResourceLimitExceededException"},
        {"request_id": "run-005", "project_name": "acme-platform", "workspace_name": "eks-cluster", "phases": ["init", "plan"], "state": "completed", "offset_days": -3},
        {"request_id": "run-006", "project_name": "acme-platform", "workspace_name": "azure-landing-zone", "phases": ["init", "plan", "apply"], "state": "completed", "offset_days": -2},
        {"request_id": "run-007", "project_name": "acme-platform", "workspace_name": "network-prod", "phases": ["init", "plan"], "state": "completed", "offset_days": -1},
        {"request_id": "run-008", "project_name": "finops-dashboard", "workspace_name": "cost-collector", "phases": ["init", "plan", "apply"], "state": "completed", "offset_days": -8},
        {"request_id": "run-009", "project_name": "finops-dashboard", "workspace_name": "cost-collector", "phases": ["init", "plan", "apply"], "state": "completed", "offset_days": -2},
    ]
    for r in iac_runs:
        run_time = NOW + timedelta(days=r["offset_days"])
        db.requests.insert_one({
            "request_id": r["request_id"],
            "requested_by": "admin@qubiva.local",
            "requested_on": iso(run_time),
            "request_type": "terraform_run",
            "state": r["state"],
            "project_name": r["project_name"],
            "workspace_name": r["workspace_name"],
            "phases": r["phases"],
            "terraform_version": "1.9.0",
            "logs": None,
            "job_name": None,
            "error": r.get("error"),
        })
    print("  Created IaC run history")

    # ── AWS Discovery runs (acme-platform) — 4 runs for trend charts ───
    aws_disc_runs = [
        {"request_id": "disc-aws-001", "offset_days": -28, "res_mult": 0.80, "cost_mult": 0.88},
        {"request_id": "disc-aws-002", "offset_days": -21, "res_mult": 0.85, "cost_mult": 0.92},
        {"request_id": "disc-aws-003", "offset_days": -14, "res_mult": 0.92, "cost_mult": 0.96},
        {"request_id": "disc-aws-004", "offset_days": -7,  "res_mult": 0.96, "cost_mult": 0.98},
        {"request_id": "disc-aws-005", "offset_days": -1,  "res_mult": 1.00, "cost_mult": 1.00},
    ]
    for d in aws_disc_runs:
        run_time = NOW + timedelta(days=d["offset_days"])
        db.requests.insert_one({
            "request_id": d["request_id"],
            "requested_by": "admin@qubiva.local",
            "requested_on": iso(run_time),
            "request_type": "discovery_run",
            "state": "completed",
            "project_name": "acme-platform",
            "cloud_account": "123456789012",
            "cloud_platform": "aws",
            "run_type": "discovery",
            "git_repo": None,
            "use_auto_benchmark": False,
            "mod_type": None,
            "benchmark_id": None,
            "query_engine_version": "v2.2.0",
            "compliance_engine_version": "v1.4.1",
            "plugin_version": "1.26.0",
            "logs": None,
            "job_name": None,
            "error": None,
        })
        # Write discovery artifact files
        disc_data = aws_discovery_data(run_time, d["res_mult"], d["cost_mult"])
        write_artifact(d["request_id"], f"discovery_{d['request_id']}.json", disc_data)
    print("  Created AWS discovery runs + artifacts (acme-platform)")

    # ── Azure Discovery runs (acme-platform) ────────────────────────────
    azure_disc_runs = [
        {"request_id": "disc-azure-001", "offset_days": -14},
        {"request_id": "disc-azure-002", "offset_days": -1},
    ]
    for d in azure_disc_runs:
        run_time = NOW + timedelta(days=d["offset_days"])
        db.requests.insert_one({
            "request_id": d["request_id"],
            "requested_by": "admin@qubiva.local",
            "requested_on": iso(run_time),
            "request_type": "discovery_run",
            "state": "completed",
            "project_name": "acme-platform",
            "cloud_account": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "cloud_platform": "azure",
            "run_type": "discovery",
            "git_repo": None,
            "use_auto_benchmark": False,
            "mod_type": None,
            "benchmark_id": None,
            "query_engine_version": "v2.2.0",
            "compliance_engine_version": "v1.4.1",
            "plugin_version": "1.26.0",
            "logs": None,
            "job_name": None,
            "error": None,
        })
        disc_data = azure_discovery_data(run_time)
        write_artifact(d["request_id"], f"discovery_{d['request_id']}.json", disc_data)
    print("  Created Azure discovery runs + artifacts (acme-platform)")

    # ── GCP Discovery runs (acme-platform) ──────────────────────────────
    gcp_disc_runs = [
        {"request_id": "disc-gcp-001", "offset_days": -21, "cost_mult": 0.92},
        {"request_id": "disc-gcp-002", "offset_days": -14, "cost_mult": 0.97},
        {"request_id": "disc-gcp-003", "offset_days": -7,  "cost_mult": 1.03},
        {"request_id": "disc-gcp-004", "offset_days": -1,  "cost_mult": 1.00},
    ]
    for d in gcp_disc_runs:
        run_time = NOW + timedelta(days=d["offset_days"])
        db.requests.insert_one({
            "request_id": d["request_id"],
            "requested_by": "admin@qubiva.local",
            "requested_on": iso(run_time),
            "request_type": "discovery_run",
            "state": "completed",
            "project_name": "acme-platform",
            "cloud_account": "acme-prod-123456",
            "cloud_platform": "gcp",
            "run_type": "discovery",
            "git_repo": None,
            "use_auto_benchmark": False,
            "mod_type": None,
            "benchmark_id": None,
            "query_engine_version": "v2.2.0",
            "compliance_engine_version": "v1.4.1",
            "plugin_version": "0.44.0",
            "logs": None,
            "job_name": None,
            "error": None,
        })
        disc_data = gcp_discovery_data(run_time, d["cost_mult"])
        write_artifact(d["request_id"], f"discovery_{d['request_id']}.json", disc_data)
    print("  Created GCP discovery runs + artifacts (acme-platform)")

    # ── FinOps Discovery runs ───────────────────────────────────────────
    finops_disc_runs = [
        {"request_id": "disc-fin-001", "offset_days": -21, "cost_mult": 0.90},
        {"request_id": "disc-fin-002", "offset_days": -14, "cost_mult": 0.95},
        {"request_id": "disc-fin-003", "offset_days": -7,  "cost_mult": 1.02},
        {"request_id": "disc-fin-004", "offset_days": -1,  "cost_mult": 1.00},
    ]
    for d in finops_disc_runs:
        run_time = NOW + timedelta(days=d["offset_days"])
        db.requests.insert_one({
            "request_id": d["request_id"],
            "requested_by": "admin@qubiva.local",
            "requested_on": iso(run_time),
            "request_type": "discovery_run",
            "state": "completed",
            "project_name": "finops-dashboard",
            "cloud_account": "987654321098",
            "cloud_platform": "aws",
            "run_type": "discovery",
            "git_repo": None,
            "use_auto_benchmark": False,
            "mod_type": None,
            "benchmark_id": None,
            "query_engine_version": "v2.2.0",
            "compliance_engine_version": "v1.4.1",
            "plugin_version": "1.26.0",
            "logs": None,
            "job_name": None,
            "error": None,
        })
        disc_data = finops_aws_discovery_data(run_time, d["cost_mult"])
        write_artifact(d["request_id"], f"discovery_{d['request_id']}.json", disc_data)
    print("  Created FinOps discovery runs + artifacts")

    # ── Benchmark runs ─────────────────────────────────────────────────
    benchmark_runs = [
        # acme-platform / AWS / CIS v4.0.0 (2 runs — history)
        {"request_id": "bench-aws-cis-001", "offset_days": -14, "project": "acme-platform", "account": "123456789012", "platform": "aws", "benchmark_id": "cis_v400", "state": "benchmark failed", "data_fn": aws_cis_benchmark_data},
        {"request_id": "bench-aws-cis-002", "offset_days": -1,  "project": "acme-platform", "account": "123456789012", "platform": "aws", "benchmark_id": "cis_v400", "state": "benchmark failed", "data_fn": aws_cis_benchmark_data},
        # acme-platform / AWS / PCI DSS v4.0
        {"request_id": "bench-aws-pci-001", "offset_days": -7,  "project": "acme-platform", "account": "123456789012", "platform": "aws", "benchmark_id": "pci_dss_v40", "state": "benchmark failed", "data_fn": aws_pci_dss_benchmark_data},
        # acme-platform / AWS / Foundational Security
        {"request_id": "bench-aws-fsbp-001", "offset_days": -3, "project": "acme-platform", "account": "123456789012", "platform": "aws", "benchmark_id": "foundational_security", "state": "benchmark failed", "data_fn": aws_foundational_security_data},
        # acme-platform / Azure / CIS v2.1.0 (2 runs — history)
        {"request_id": "bench-az-cis-001",  "offset_days": -10, "project": "acme-platform", "account": "a1b2c3d4-e5f6-7890-abcd-ef1234567890", "platform": "azure", "benchmark_id": "cis_v210", "state": "benchmark failed", "data_fn": azure_cis_benchmark_data},
        {"request_id": "bench-az-cis-002",  "offset_days": -2,  "project": "acme-platform", "account": "a1b2c3d4-e5f6-7890-abcd-ef1234567890", "platform": "azure", "benchmark_id": "cis_v210", "state": "benchmark failed", "data_fn": azure_cis_benchmark_data},
        # acme-platform / GCP / CIS v4.0.0
        {"request_id": "bench-gcp-cis-001", "offset_days": -8,  "project": "acme-platform", "account": "acme-prod-123456", "platform": "gcp", "benchmark_id": "cis_v400", "state": "benchmark failed", "data_fn": gcp_cis_benchmark_data},
        {"request_id": "bench-gcp-cis-002", "offset_days": -1,  "project": "acme-platform", "account": "acme-prod-123456", "platform": "gcp", "benchmark_id": "cis_v400", "state": "benchmark failed", "data_fn": gcp_cis_benchmark_data},
        # acme-platform / GCP / NIST 800-53 Rev 5
        {"request_id": "bench-gcp-nist-001", "offset_days": -6, "project": "acme-platform", "account": "acme-prod-123456", "platform": "gcp", "benchmark_id": "nist_800_53_rev_5", "state": "benchmark failed", "data_fn": gcp_nist_benchmark_data},
        {"request_id": "bench-gcp-nist-002", "offset_days": -1, "project": "acme-platform", "account": "acme-prod-123456", "platform": "gcp", "benchmark_id": "nist_800_53_rev_5", "state": "benchmark failed", "data_fn": gcp_nist_benchmark_data},
        # acme-platform / Azure / NIST 800-53 Rev 5
        {"request_id": "bench-az-nist-001", "offset_days": -5, "project": "acme-platform", "account": "a1b2c3d4-e5f6-7890-abcd-ef1234567890", "platform": "azure", "benchmark_id": "nist_800_53_rev_5", "state": "benchmark failed", "data_fn": azure_nist_benchmark_data},
        # finops-dashboard / AWS / CIS v4.0.0
        {"request_id": "bench-fin-cis-001", "offset_days": -5,  "project": "finops-dashboard", "account": "987654321098", "platform": "aws", "benchmark_id": "cis_v400", "state": "benchmark failed", "data_fn": aws_cis_benchmark_data},
        # finops-dashboard / AWS / PCI DSS v4.0
        {"request_id": "bench-fin-pci-001", "offset_days": -2,  "project": "finops-dashboard", "account": "987654321098", "platform": "aws", "benchmark_id": "pci_dss_v40", "state": "benchmark failed", "data_fn": aws_pci_dss_benchmark_data},
    ]
    for b in benchmark_runs:
        run_time = NOW + timedelta(days=b["offset_days"])
        db.requests.insert_one({
            "request_id": b["request_id"],
            "requested_by": "admin@qubiva.local",
            "requested_on": iso(run_time),
            "request_type": "query_run",
            "state": b["state"],
            "project_name": b["project"],
            "cloud_account": b["account"],
            "cloud_platform": b["platform"],
            "run_type": "benchmark",
            "git_repo": None,
            "use_auto_benchmark": True,
            "mod_type": "compliance",
            "benchmark_id": b["benchmark_id"],
            "query_engine_version": "v2.2.0",
            "compliance_engine_version": "v1.4.1",
            "plugin_version": "1.26.0",
            "logs": None,
            "job_name": None,
            "error": None,
        })
        bench_data = b["data_fn"]()
        write_artifact(b["request_id"], f"benchmark_{b['request_id']}.json", bench_data)
    print(f"  Created {len(benchmark_runs)} benchmark runs + artifacts")

    # ── Discovery configs ───────────────────────────────────────────────
    db.discovery_configs.insert_many([
        {
            "project_name": "acme-platform",
            "cloud_platform": "aws",
            "account_id": "123456789012",
            "selected_resource_types": [
                "aws_ec2_instance", "aws_s3_bucket", "aws_rds_db_instance",
                "aws_iam_role", "aws_vpc_security_group", "aws_lambda_function",
                "aws_eks_cluster", "aws_vpc"
            ],
            **audit,
        },
        {
            "project_name": "acme-platform",
            "cloud_platform": "azure",
            "account_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "selected_resource_types": [
                "azure_compute_virtual_machine", "azure_resource_group",
                "azure_virtual_network", "azure_network_security_group",
                "azure_storage_account", "azure_key_vault", "azure_policy_assignment"
            ],
            **audit,
        },
        {
            "project_name": "acme-platform",
            "cloud_platform": "gcp",
            "account_id": "acme-prod-123456",
            "selected_resource_types": [
                "gcp_compute_instance", "gcp_storage_bucket", "gcp_sql_database_instance",
                "gcp_compute_network", "gcp_compute_firewall", "gcp_cloudfunctions_function",
                "gcp_kms_key", "gcp_iam_role"
            ],
            **audit,
        },
        {
            "project_name": "finops-dashboard",
            "cloud_platform": "aws",
            "account_id": "987654321098",
            "selected_resource_types": [
                "aws_ec2_instance", "aws_s3_bucket", "aws_rds_db_instance",
                "aws_lambda_function", "aws_vpc", "aws_vpc_security_group", "aws_iam_role"
            ],
            **audit,
        },
    ])
    print("  Created discovery configs")

    # ── Alerts (acme-platform) ──────────────────────────────────────────
    alerts = [
        # AWS alerts — open
        {
            "project_name": "acme-platform",
            "cloud_platform": "aws",
            "account_id": "123456789012",
            "cloud_alert_id": "aws_123456789012_us-east-1_HighCPUUtilization-EKS",
            "alert": {
                "AlarmName": "HighCPUUtilization-EKS",
                "AlarmDescription": "EKS cluster node group CPU utilization exceeded 85% for 10 minutes",
                "AWSAccountId": "123456789012",
                "Region": "us-east-1",
                "NewStateValue": "ALARM",
                "OldStateValue": "OK",
                "NewStateReason": "Threshold Crossed: 1 out of the last 1 datapoints [89.2] was >= 85.0",
                "MetricName": "CPUUtilization",
                "Namespace": "AWS/EC2",
            },
            "status": "open",
            "created_at": iso(NOW - timedelta(hours=6)),
            "updated_at": iso(NOW - timedelta(hours=6)),
            "resolved_at": None,
            "resolved_by": None,
            "resolution_note": None,
            "resolution_history": [],
        },
        {
            "project_name": "acme-platform",
            "cloud_platform": "aws",
            "account_id": "123456789012",
            "cloud_alert_id": "aws_123456789012_us-east-1_RDS-FreeStorageSpace",
            "alert": {
                "AlarmName": "RDS-FreeStorageSpace",
                "AlarmDescription": "RDS instance acme-prod-postgres free storage space below 10GB",
                "AWSAccountId": "123456789012",
                "Region": "us-east-1",
                "NewStateValue": "ALARM",
                "OldStateValue": "OK",
                "NewStateReason": "Threshold Crossed: 1 out of the last 1 datapoints [8.5 GB] was <= 10.0",
                "MetricName": "FreeStorageSpace",
                "Namespace": "AWS/RDS",
            },
            "status": "open",
            "created_at": iso(NOW - timedelta(hours=12)),
            "updated_at": iso(NOW - timedelta(hours=12)),
            "resolved_at": None,
            "resolved_by": None,
            "resolution_note": None,
            "resolution_history": [],
        },
        {
            "project_name": "acme-platform",
            "cloud_platform": "aws",
            "account_id": "123456789012",
            "cloud_alert_id": "aws_123456789012_us-east-1_UnauthorizedAPICall",
            "alert": {
                "AlarmName": "UnauthorizedAPICall",
                "AlarmDescription": "Detected unauthorized API calls from IAM user developer-2",
                "AWSAccountId": "123456789012",
                "Region": "us-east-1",
                "NewStateValue": "ALARM",
                "OldStateValue": "OK",
                "NewStateReason": "Threshold Crossed: unauthorized API calls detected",
                "MetricName": "UnauthorizedAttemptCount",
                "Namespace": "CloudTrailMetrics",
            },
            "status": "open",
            "created_at": iso(NOW - timedelta(hours=2)),
            "updated_at": iso(NOW - timedelta(hours=2)),
            "resolved_at": None,
            "resolved_by": None,
            "resolution_note": None,
            "resolution_history": [],
        },
        # AWS alert — resolved
        {
            "project_name": "acme-platform",
            "cloud_platform": "aws",
            "account_id": "123456789012",
            "cloud_alert_id": "aws_123456789012_us-east-1_HighNetworkOut",
            "alert": {
                "AlarmName": "HighNetworkOut",
                "AlarmDescription": "Unusual outbound network traffic from api-gateway-prod",
                "AWSAccountId": "123456789012",
                "Region": "us-east-1",
                "NewStateValue": "OK",
                "OldStateValue": "ALARM",
                "NewStateReason": "Network traffic returned to normal levels",
                "MetricName": "NetworkOut",
                "Namespace": "AWS/EC2",
            },
            "status": "resolved",
            "created_at": iso(NOW - timedelta(days=2)),
            "updated_at": iso(NOW - timedelta(days=1)),
            "resolved_at": iso(NOW - timedelta(days=1)),
            "resolved_by": "auto-resolved",
            "resolution_note": "Automatically resolved by cloud platform",
            "resolution_history": [],
        },
        # Azure alert — open
        {
            "project_name": "acme-platform",
            "cloud_platform": "azure",
            "account_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "cloud_alert_id": "azure__subscriptions_a1b2c3d4_resourceGroups_acme-prod_alerts_HighMemory",
            "alert": {
                "AlarmName": "VM High Memory Usage",
                "AlarmDescription": "hub-firewall VM memory utilization above 90% for 15 minutes",
                "summary": "VM High Memory Usage - hub-firewall",
                "severity": "Sev2",
                "monitor_condition": "fired",
            },
            "status": "open",
            "created_at": iso(NOW - timedelta(hours=3)),
            "updated_at": iso(NOW - timedelta(hours=3)),
            "resolved_at": None,
            "resolved_by": None,
            "resolution_note": None,
            "resolution_history": [],
        },
        # Azure alert — resolved
        {
            "project_name": "acme-platform",
            "cloud_platform": "azure",
            "account_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "cloud_alert_id": "azure__subscriptions_a1b2c3d4_resourceGroups_acme-networking_alerts_NSGDeny",
            "alert": {
                "AlarmName": "NSG Deny Spike",
                "AlarmDescription": "Unusual number of NSG deny events on hub-nsg",
                "summary": "NSG Deny Spike - hub-nsg",
                "severity": "Sev3",
                "monitor_condition": "resolved",
            },
            "status": "resolved",
            "created_at": iso(NOW - timedelta(days=3)),
            "updated_at": iso(NOW - timedelta(days=2)),
            "resolved_at": iso(NOW - timedelta(days=2)),
            "resolved_by": "sarah@example.com",
            "resolution_note": "Traced to deployment pipeline retries. NSG rules updated.",
            "resolution_history": [],
        },
        # GCP alert — open
        {
            "project_name": "acme-platform",
            "cloud_platform": "gcp",
            "account_id": "acme-prod-123456",
            "cloud_alert_id": "gcp_acme-prod-123456_us-central1_CloudSQLHighCPU",
            "alert": {
                "AlarmName": "Cloud SQL High CPU",
                "AlarmDescription": "Cloud SQL instance acme-prod-cloudsql CPU utilization above 85% for 15 minutes",
                "summary": "Cloud SQL High CPU - acme-prod-cloudsql",
                "severity": "WARNING",
                "monitor_condition": "firing",
            },
            "status": "open",
            "created_at": iso(NOW - timedelta(hours=4)),
            "updated_at": iso(NOW - timedelta(hours=4)),
            "resolved_at": None,
            "resolved_by": None,
            "resolution_note": None,
            "resolution_history": [],
        },
    ]
    db.alerts.insert_many(alerts)
    print("  Created alerts")

    # ── Alerts (finops-dashboard) ───────────────────────────────────────
    finops_alerts = [
        {
            "project_name": "finops-dashboard",
            "cloud_platform": "aws",
            "account_id": "987654321098",
            "cloud_alert_id": "aws_987654321098_eu-west-1_BudgetThreshold80",
            "alert": {
                "AlarmName": "BudgetThreshold80",
                "AlarmDescription": "Monthly spending has exceeded 80% of the $2,000 budget",
                "AWSAccountId": "987654321098",
                "Region": "eu-west-1",
                "NewStateValue": "ALARM",
                "OldStateValue": "OK",
                "NewStateReason": "Current spend $1,642 exceeds 80% threshold of $2,000 budget",
                "MetricName": "EstimatedCharges",
                "Namespace": "AWS/Billing",
            },
            "status": "open",
            "created_at": iso(NOW - timedelta(hours=18)),
            "updated_at": iso(NOW - timedelta(hours=18)),
            "resolved_at": None,
            "resolved_by": None,
            "resolution_note": None,
            "resolution_history": [],
        },
    ]
    db.alerts.insert_many(finops_alerts)
    print("  Created finops alerts")

    # ── Update admin user's project list ────────────────────────────────
    db.users.update_one(
        {"username": "admin@qubiva.local"},
        {"$set": {"projects": ["acme-platform", "finops-dashboard"]}}
    )

    print("\nDemo data seeded successfully.")
    print(f"  Artifacts written to: {ARTIFACTS_PATH}/{ARTIFACTS_PREFIX}/")


if __name__ == "__main__":
    if not FERNET_KEY:
        print("ERROR: LOCAL_ENCRYPTION_KEY not set", file=sys.stderr)
        sys.exit(1)

    fernet = Fernet(FERNET_KEY.encode())
    client = wait_for_mongo(DB_URL)
    db = client.get_default_database()
    seed(db, fernet)
