from pydantic import BaseModel, Field, EmailStr, model_validator, field_validator, RootModel
from typing import List, Optional, Literal, Dict, Any
from datetime import date
import re


class Models:

    class UserCreateData(BaseModel):
        """Model for a single user's data for the create_users method."""
        username: str = EmailStr
        password: Optional[str] = None
        org_roles: Optional[List[str]] = None

    class CreateUsersRequest(BaseModel):
        """Model for the create_users request, containing a list of users."""
        users: List['Models.UserCreateData']

    class UserRoleUpdateRequest(BaseModel):
        """Model for a single user's role update request."""
        username: str
        org_roles: Optional[List[str]] = None  # Use an empty list or None if there are no roles

    class ModifyOrgUsersRolesRequest(BaseModel):
        """Model for modifying organization roles for multiple users."""
        users: List['Models.UserRoleUpdateRequest']

    class DeleteUsersRequest(BaseModel):
        """Model for deleting multiple users."""
        usernames: List[str]

    class LoginData(BaseModel):
        username: str
        password: str
        next: Optional[str] = None

    class PasswordResetRequest(BaseModel):
        """Model for requesting a password reset link."""
        username: str

    class PasswordResetSubmit(BaseModel):
        """Model for submitting the new password via the reset link."""
        token: str
        new_password: str = Field(..., min_length=8, description="The new password, at least 8 characters long.")

    class MemberData(BaseModel):
        username: str
        roles: List[str]

    class ProjectData(BaseModel):
        project_name: str
        description: str
        members: Optional[List['Models.MemberData']] = Field(default=None, example=[{"username": "user123", "roles": ["admin", "user"]}])
        variables: Optional[Dict[str, str]] = None  # Optional regular variables
        secrets: Optional[Dict[str, str]] = None  # Optional variables marked as secrets

        @field_validator("project_name")
        def validate_project_name(cls, value):
            if not re.match(r"^[a-zA-Z0-9_-]{3,50}$", value):
                raise ValueError(
                    "Project name must be 3-50 characters long and can only contain alphanumeric characters, underscores (_), and hyphens (-). No spaces allowed."
                )
            if value.startswith(("-", "_")) or value.endswith(("-", "_")):
                raise ValueError(
                    "Project name cannot start or end with a hyphen (-) or underscore (_)."
                )
            return value

    class UpdateProjectData(BaseModel):
        project_name: str
        new_description: str

    class UpdateMemberRolesRequest(BaseModel):
        project_name: str
        username: str
        roles: List[str]

    class CloudAccount(BaseModel):
        cloud_platform: str
        account_id: str
        auth_secrets: Optional[Dict[str, str]] = None  # Made optional
        credential_reference: Optional[str] = None     # New field
        auth_secrets: Dict[str, str]  # Renamed from 'secrets' to 'auth_secrets'
        variables: Optional[Dict[str, str]] = None  # Optional regular variables
        secrets: Optional[Dict[str, str]] = None  # Optional variables marked as secrets

        @model_validator(mode="after")
        def validate_auth_method(self):
            if not self.auth_secrets and not self.credential_reference:
                raise ValueError("Either 'auth_secrets' or 'credential_reference' must be provided")
            if self.auth_secrets and self.credential_reference:
                raise ValueError("Cannot specify both 'auth_secrets' and 'credential_reference'")
            return self

    class CloudAccountUpdate(BaseModel):
        auth_secrets: Optional[Dict[str, str]] = None
        credential_reference: Optional[str] = None
        variables: Optional[Dict[str, str]] = None
        secrets: Optional[Dict[str, str]] = None

        @model_validator(mode="after")
        def validate_auth_method(self):
            if not self.auth_secrets and not self.credential_reference:
                raise ValueError("Either 'auth_secrets' or 'credential_reference' must be provided")
            if self.auth_secrets and self.credential_reference:
                raise ValueError("Cannot specify both 'auth_secrets' and 'credential_reference'")
            return self

    class CredentialData(BaseModel):
        credential_name: str
        credential_type: str = "external_certificate_authority"  # For now, only this type
        auth_secrets: Dict[str, str]

        @field_validator("credential_name")
        def validate_credential_name(cls, value):
            if not re.match(r"^[a-zA-Z0-9_-]{3,50}$", value):
                raise ValueError(
                    "Credential name must be 3-50 characters long and can only contain alphanumeric characters, underscores (_), and hyphens (-). No spaces allowed."
                )
            if value.startswith(("-", "_")) or value.endswith(("-", "_")):
                raise ValueError(
                    "Credential name cannot start or end with a hyphen (-) or underscore (_)."
                )
            return value

    class CredentialUpdate(BaseModel):
        auth_secrets: Dict[str, str]

    class ProjectUpdateRequest(BaseModel):
        description: Optional[str]
        members: Optional[List['Models.MemberData']] = Field(default=None)
        variables: Optional[Dict[str, str]] = None
        secrets: Optional[Dict[str, str]] = None

    class GitHubRepoDetails(BaseModel):
        repo_name: str
        repo_url: str
        branch: Optional[str]
        terraform_config_path: Optional[str]
        policy_governance_path: Optional[str]
        discovery_queries_path: Optional[str]
        custom_benchmark_path: Optional[str]  # Added for custom benchmarks
        token: Optional[str] = None

        @field_validator("repo_name")
        def validate_repo_name(cls, repo_name, info):
            repo_url = info.data.get("repo_url")
            if repo_url:
                # Extract the necessary parts from the URL
                match = re.match(r".*/([^/]+)/([^/]+)\.git$", repo_url)
                if match:
                    expected_repo_name = f"{match.group(1)}~{match.group(2)}"
                    if repo_name != expected_repo_name:
                        raise ValueError(
                            f"repo_name must be '{expected_repo_name}' based on the repo_url"
                        )
                else:
                    raise ValueError("Invalid repo_url format")
            return repo_name

    class GitHubRepoUpdate(BaseModel):
        branch: Optional[str]
        terraform_config_path: Optional[str]
        policy_governance_path: Optional[str]
        discovery_queries_path: Optional[str]
        custom_benchmark_path: Optional[str]  # Added for custom benchmarks
        token: Optional[str] = None

    class GitHubRepoDelete(BaseModel):
        repo_name: str

    class CreateWorkspaceModel(BaseModel):
        name: str
        description: Optional[str] = None
        variables: Optional[Dict[str, str]] = None
        secrets: Optional[Dict[str, str]] = None
        terraform_version: str
        github_repo_name: str
        cloud_account: str
        cloud_platform: str
        trigger_branch: Optional[str] = None

        @field_validator("name")
        def validate_name(cls, value):
            if not re.match(r"^[a-zA-Z0-9_-]{3,50}$", value):
                raise ValueError(
                    "Workspace name must be 3-50 characters long and can only contain alphanumeric characters, underscores (_), and hyphens (-). No spaces allowed."
                )
            if value.startswith(("-", "_")) or value.endswith(("-", "_")):
                raise ValueError(
                    "Workspace name cannot start or end with a hyphen (-) or underscore (_)."
                )
            return value

        @field_validator("terraform_version")
        def validate_terraform_version(cls, value):
            # Semantic versioning pattern (e.g., 1.2.3, 0.14.0, 1.0.0-alpha, etc.)
            if not re.match(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9-.]+)?$", value):
                raise ValueError(
                    "Terraform version must follow semantic versioning (e.g., 1.2.3, 0.14.0, or 1.0.0-alpha)."
                )
            return value

    class UpdateWorkspaceModel(BaseModel):
        description: Optional[str] = None
        variables: Optional[Dict[str, str]] = None
        secrets: Optional[Dict[str, str]] = None
        terraform_version: str
        github_repo_name: str
        cloud_account: str
        cloud_platform: str
        trigger_branch: Optional[str] = None

    class OrgPolicyRepoUpdate(BaseModel):
        repo_url: str
        branch: Optional[str]
        token: Optional[str]
        policy_path: Optional[str]
        conftest_version: Optional[str]

    class CloudProviderBase(BaseModel):
        project_id: str
        repo_url: str
        branch: str
        workspace: str
        phases: List[Literal['init', 'plan', 'apply', 'destroy']]
        cloud_provider: Literal['aws', 'azure', 'gcp']

    class AWSCredentials(BaseModel):
        access_key: str
        secret_key: str

    class AzureCredentials(BaseModel):
        pass  # Placeholder for Azure credentials

    class GCPCredentials(BaseModel):
        pass  # Placeholder for GCP credentials

    class TerraformExecuteAWS(CloudProviderBase):
        cloud_provider: Literal['aws'] = 'aws'
        credentials: 'Models.AWSCredentials'

    class TerraformExecuteAzure(CloudProviderBase):
        cloud_provider: Literal['azure'] = 'azure'
        credentials: 'Models.AzureCredentials'

    class TerraformExecutePayload(BaseModel):
        phases: List[str]
        task_timeout_hours: Optional[int] = 2

    class TerraformExecuteGCP(CloudProviderBase):
        cloud_provider: Literal['gcp'] = 'gcp'
        credentials: 'Models.GCPCredentials'

    class UpdateStateRequest(BaseModel):
        state: str

    class UpdateErrorDetailsRequest(BaseModel):
        error_message: str

    class TerraformExecuteRequest(BaseModel):
        aws: Optional['Models.TerraformExecuteAWS'] = None
        azure: Optional['Models.TerraformExecuteAzure'] = None
        gcp: Optional['Models.TerraformExecuteGCP'] = None

    class SprintCreateRequest(BaseModel):
        start_date: str  # In 'YYYY-MM-DD' format
        end_date: str    # In 'YYYY-MM-DD' format
        goal: str

    class SprintUpdateRequest(BaseModel):
        start_date: Optional[str] = None  # In 'YYYY-MM-DD' format
        end_date: Optional[str] = None    # In 'YYYY-MM-DD' format
        goal: Optional[str] = None

        def get_cloud_config(self):
            if self.aws:
                return self.aws
            elif self.azure:
                return self.azure
            elif self.gcp:
                return self.gcp
            else:
                raise ValueError("No valid cloud provider configuration found")

    class TaskBase(BaseModel):
        title: str
        description: str
        type: str
        status: str
        priority: str
        assignedTo: Optional[str]
        dueDate: Optional[date] = None
        tags: List[str]
        relationships: List[dict]
        sprintId: Optional[str]

    class TaskCreate(TaskBase):
        pass

    class TaskUpdate(TaskBase):
        pass

    class CommentCreate(BaseModel):
        content: str

    class CommentsCreate(BaseModel):
        comments: List['Models.CommentCreate']

    class CommentUpdate(BaseModel):
        content: str
        comment_timestamp: str  # Use timestamp as unique identifier instead of index
        original_content: Optional[str] = None  # For detecting new mentions

    class QueryTriggerPayload(BaseModel):
        cloud_account: str
        cloud_platform: str
        run_type: str = Field(..., description="Type of run. Must be either 'query' or 'benchmark'")
        git_repo: Optional[str] = Field(
            None, description="Git repository containing the queries or benchmark configurations."
        )
        use_auto_benchmark: Optional[bool] = Field(
            False, description="Flag to use auto benchmark. Only applicable when run_type is 'benchmark'."
        )

        mod_type: Optional[str] = Field(
            None, description="Mod category: 'compliance' or 'cost'. Required when use_auto_benchmark is True."
        )
        benchmark_id: Optional[str] = Field(
            None, description="Specific benchmark ID (e.g., 'cis_v400', 'pci_dss_v40'). Required when use_auto_benchmark is True."
        )

        query_engine_version: Optional[str] = Field(
            "v2.2.0", description="Version of the query engine to use. Defaults to v2.2.0."
        )
        compliance_engine_version: Optional[str] = Field(
            "v1.4.1", description="Version of the compliance engine to use. Defaults to v1.4.1. Only applicable when run_type is 'benchmark'."
        )
        plugin_version: Optional[str] = Field(
            "1.26.0", description="Version of the cloud platform plugin to use. Defaults to 1.26.0."
        )
        schedule: Optional[Dict] = Field(
            None,
            description=(
                "Schedule configuration. Example: {'frequency': 'rate(1 hour)'} "
                "or {'frequency': 'cron(0 12 * * ? *)'}."
            ),
        )
        task_timeout_hours: Optional[int] = 2

        @model_validator(mode="after")
        def validate_run_type_and_paths(self):
            # Validate run_type is correct
            if self.run_type not in ['query', 'benchmark']:
                raise ValueError("run_type must be either 'query' or 'benchmark'")

            # Validate benchmark mode requirements
            if self.run_type == 'benchmark':
                if self.use_auto_benchmark:
                    # NEW: Require mod_type and benchmark_id for auto benchmark
                    if not self.mod_type:
                        raise ValueError("'mod_type' is required when use_auto_benchmark is True")
                    if not self.benchmark_id:
                        raise ValueError("'benchmark_id' is required when use_auto_benchmark is True")
                    if self.mod_type not in ['compliance', 'cost', 'public_access_risks']:
                        raise ValueError("'mod_type' must be either 'compliance' or 'cost'")
                else:
                    if not self.git_repo:
                        raise ValueError("When not using auto benchmark, 'git_repo' is required")

            # Validate query mode requirements
            if self.run_type == 'query':
                if not self.git_repo:
                    raise ValueError("'git_repo' is required when run_type is 'query'")

            # Validate schedule field
            if self.schedule:
                frequency = self.schedule.get("frequency")
                if not frequency:
                    raise ValueError(
                        "If 'schedule' is provided, it must include a 'frequency' key."
                    )

            return self

    class ScheduleStateUpdate(BaseModel):
        """Model for updating schedule state."""
        state: str = Field(
            ...,
            description="The new state of the schedule",
            pattern="^(enabled|disabled)$"
        )

    class TagsUpdate(BaseModel):
        tags: List[str] = Field(
            ...,  # This means the field is required
            description="Complete list of tags for the project",
            min_items=0,  # Allow empty list for removing all tags
            max_items=100,  # Reasonable limit for number of tags
        )

        @field_validator('tags')
        @classmethod
        def clean_tags(cls, tags: List[str]) -> List[str]:
            # Remove duplicates and empty strings, normalize to lowercase
            cleaned_tags = {tag.strip().lower() for tag in tags if tag.strip()}
            return list(cleaned_tags)

        model_config = {
            "json_schema_extra": {
                "example": {
                    "tags": ["frontend", "backend", "database", "ui", "performance"]
                }
            }
        }

    class GenerateTokenRequest(BaseModel):
        token_name: str = Field(..., pattern=r"^[a-zA-Z0-9]+$", description="Alphanumeric token name without spaces")
        expiry_hours: int | None = Field(default=None, ge=1, le=2160, description="Expiry in hours (1-2160, max 90 days)")
        expiry_days: int | None = Field(default=None, ge=1, le=90, description="Expiry in days (1-90)")

        @model_validator(mode="after")
        def validate_expiry(self):
            if not self.expiry_hours and not self.expiry_days:
                raise ValueError("Either 'expiry_hours' or 'expiry_days' must be provided.")
            if self.expiry_hours and self.expiry_days:
                raise ValueError("Provide only one of 'expiry_hours' or 'expiry_days', not both.")
            return self

    class RevokeTokenRequest(BaseModel):
        token_name: str

    class AlertCreate(RootModel):
        root: Dict[str, Any]

    class ResolveAlert(BaseModel):
        resolved_by: str = Field(..., description="Username of the person resolving the alert")
        resolution_note: str = Field(..., description="Note explaining why the alert was resolved")

    class AlertResponse(BaseModel):
        project_name: str
        cloud_platform: str
        account_id: str
        cloud_alert_id: str
        alert: Dict[str, Any]
        status: str
        created_at: str
        updated_at: str
        resolved_by: Optional[str] = None
        resolved_at: Optional[str] = None
        resolution_note: Optional[str] = None

    class StatusUpdateModel(BaseModel):
        status: str
        error: Optional[str] = None

    class userStats(BaseModel):
        username: str

    class userStatsforProject(BaseModel):
        username: str

    class SSOConfigUpdate(BaseModel):
        """Model for SSO configuration."""
        enabled: bool = Field(..., description="Whether SSO is enabled")
        saml_idp_metadata_url: Optional[str] = Field(None, description="IdP metadata URL (recommended)")
        saml_idp_entity_id: Optional[str] = Field(None, description="IdP entity ID")
        saml_idp_sso_url: Optional[str] = Field(None, description="IdP SSO URL")
        saml_idp_slo_url: Optional[str] = Field(None, description="IdP SLO URL")
        saml_idp_cert: Optional[str] = Field(None, description="IdP X.509 certificate")

        access_control: Optional[Dict[str, Any]] = Field(
            None,
            description="Access control configuration",
            json_schema_extra={
                "example": {
                    "mode": "group_whitelist",
                    "allowed_groups": ["Engineering", "DevOps"]
                }
            }
        )

        attribute_mapping: Optional[Dict[str, str]] = Field(
            None,
            description="SAML attribute mapping",
            json_schema_extra={
                "example": {
                    "email": "email",
                    "groups": "memberOf"
                }
            }
        )

        default_org_roles: Optional[List[str]] = Field(
            None,
            description="Default roles for new SSO users"
        )

        group_mapping_enabled: bool = Field(
            False,
            description="Whether to map SAML groups to org roles"
        )

        group_mapping: Optional[Dict[str, List[str]]] = Field(
            None,
            description="Mapping of SAML groups to org roles",
            json_schema_extra={
                "example": {
                    "Engineering": ["org_editor"],
                    "DevOps": ["org_admin"]
                }
            }
        )

        auto_provision: bool = Field(
            True,
            description="Whether to auto-provision new users on first login"
        )

        @model_validator(mode="after")
        def validate_idp_config(self):
            """Ensure either metadata URL or manual config is provided."""
            if not self.saml_idp_metadata_url:
                if not all([self.saml_idp_entity_id, self.saml_idp_sso_url, self.saml_idp_cert]):
                    raise ValueError(
                        "Must provide either saml_idp_metadata_url OR "
                        "(saml_idp_entity_id, saml_idp_sso_url, saml_idp_cert)"
                    )
            return self

    class SSOLoginRequest(BaseModel):
        """Model for initiating SSO login (currently no params needed)."""

    class DeactivateUserRequest(BaseModel):
        """Model for deactivating a user."""
        username: str = Field(..., description="Email/username of user to deactivate")
        reason: str = Field(..., description="Reason for deactivation")

    class ReactivateUserRequest(BaseModel):
        """Model for reactivating a user."""
        username: str = Field(..., description="Email/username of user to reactivate")

    class DiscoveryConfigUpdate(BaseModel):
        selected_resource_types: List[str]

    class DiscoveryTriggerPayload(BaseModel):
        """Payload for triggering resource discovery"""
        schedule: Optional[Dict] = Field(
            None,
            description="Schedule configuration. Example: {'frequency': '0 2 * * *'}"
        )
        task_timeout_hours: Optional[int] = 2

    class ResourceTypeSelection(BaseModel):
        """Model for selecting resource types to discover."""
        selected_resource_types: List[str] = Field(
            ...,
            description="List of cloud resource table names to query",
            example=["aws_s3_bucket", "aws_ec2_instance", "aws_rds_instance"]
        )

    class DiscoveryConfigRequest(BaseModel):
        """Model for saving discovery configuration."""
        project_name: str
        cloud_platform: Literal["aws", "gcp", "azure"]
        account_id: str
        selected_resource_types: List[str]

    # ==================== Discovery Dashboard Response Models ====================

    class DiscoverySummary(BaseModel):
        """Summary statistics for a discovery."""
        total_resources: int
        total_cost: float
        currency: str = "USD"
        by_type: Dict[str, int] = Field(
            default_factory=dict,
            description="Resource counts by type"
        )
        by_region: Dict[str, int] = Field(
            default_factory=dict,
            description="Resource counts by region"
        )
        by_service_cost: Dict[str, float] = Field(
            default_factory=dict,
            description="Costs by service"
        )
        tagging: Dict[str, Any] = Field(
            default_factory=dict,
            description="Tagging compliance statistics"
        )

    class NormalizedResource(BaseModel):
        """Normalized resource structure."""
        resource_type: str
        resource_id: str
        resource_name: str
        region: str
        tags: Dict[str, str] = Field(default_factory=dict)
        account_id: str

    class Anomaly(BaseModel):
        """Statistical anomaly detection result."""
        metric: str
        severity: Literal["moderate", "severe"]
        direction: Literal["increase", "decrease"]
        current_value: float
        historical_mean: float
        z_score: float
        message: str

    class TrendAnalysis(BaseModel):
        """Trend analysis result."""
        direction: Literal["increasing", "decreasing", "stable"]
        slope: float
        strength: Literal["strong", "moderate", "weak", "none"]
        r_squared: float
        confidence: Literal["high", "moderate", "low"]

    class Insights(BaseModel):
        """Discovery insights with anomalies and trends."""
        anomalies: Dict[str, List['Models.Anomaly']] = Field(
            default_factory=dict,
            description="Detected anomalies"
        )
        trends: Dict[str, Optional['Models.TrendAnalysis']] = Field(
            default_factory=dict,
            description="Trend analysis"
        )
        predictions: Optional[Dict[str, Any]] = Field(
            default=None,
            description="Predictions for next period"
        )
        recommendations: List[str] = Field(
            default_factory=list,
            description="Actionable recommendations"
        )

    class ChartData(BaseModel):
        """Chart.js compatible data structure."""
        labels: List[str]
        datasets: List[Dict[str, Any]]

    class DiscoveryHistoryItem(BaseModel):
        """Single item in discovery history."""
        request_id: str
        discovered_at: str
        total_resources: int
        total_cost: float
        status: Literal["success", "incomplete"]

    class DashboardResponse(BaseModel):
        """Complete dashboard response for a cloud account."""
        cloud_account_id: str
        provider: Literal["aws", "gcp", "azure"]
        request_id: str
        discovered_at: str
        summary: 'Models.DiscoverySummary'
        insights: 'Models.Insights'
        chart_data: Dict[str, 'Models.ChartData']
        resources: List['Models.NormalizedResource'] = Field(
            default_factory=list,
            description="Full list of normalized resources"
        )
        discovery_history: List['Models.DiscoveryHistoryItem'] = Field(
            default_factory=list,
            description="Historical discovery summaries"
        )

    # ==================== Project-Level Dashboard Models ====================

    class AccountSummary(BaseModel):
        """Summary for a single account in project view."""
        account_id: str
        cloud_platform: str
        total_resources: int
        total_cost: float
        last_discovery: Optional[str] = None

    class ProjectDashboardResponse(BaseModel):
        """Aggregated dashboard for entire project (all accounts)."""
        project_id: str
        project_name: str
        cloud_accounts: int
        accounts_with_data: int
        aggregated: Dict[str, Any] = Field(
            description="Aggregated metrics across all accounts"
        )
        insights: Optional['Models.Insights'] = None
        account_details: List['Models.AccountSummary'] = Field(
            default_factory=list,
            description="Per-account summaries"
        )

    # ==================== Comparison Models ====================

    class DiscoveryComparison(BaseModel):
        """Comparison between two discoveries."""
        discovery_1: Dict[str, Any]
        discovery_2: Dict[str, Any]
        changes: Dict[str, Any] = Field(
            description="Calculated differences"
        )

    # ==================== Error Response Models ====================

    class ErrorResponse(BaseModel):
        """Standard error response."""
        success: bool = False
        message: str
        details: Optional[str] = None

    class SuccessResponse(BaseModel):
        """Standard success response."""
        success: bool = True
        message: str
        data: Optional[Any] = None

    # ==================== Query Parameters ====================

    class DiscoveryHistoryParams(BaseModel):
        """Query parameters for discovery history."""
        limit: int = Field(
            default=10,
            ge=1,
            le=50,
            description="Number of historical discoveries to retrieve"
        )

    class ResourceFilterParams(BaseModel):
        """Query parameters for filtering resources."""
        resource_type: Optional[str] = None
        region: Optional[str] = None
        tagged_only: Optional[bool] = None
        search: Optional[str] = None

    # ==================== Statistics Models ====================

    class StatisticalSummary(BaseModel):
        """Statistical summary of discovery history."""
        discoveries_analyzed: int
        cost_statistics: Dict[str, float]
        resource_statistics: Dict[str, float]

    # ==================== Cloud Analyst Models ====================

    class AnalystConversationCreate(BaseModel):
        """Request body for creating a new analyst conversation."""
        project_name: Optional[str] = None  # Required for account/project scope, optional for org
        cloud_platform: Optional[str] = None
        account_id: Optional[str] = None
        scope: Literal["account", "project", "org"] = "account"

    class AnalystMessageRequest(BaseModel):
        """Request body for sending a message in an analyst conversation."""
        message: str = Field(..., max_length=10000)


# Rebuild models with forward references
Models.ProjectData.model_rebuild()
Models.ProjectUpdateRequest.model_rebuild()
Models.TerraformExecuteAWS.model_rebuild()
Models.TerraformExecuteAzure.model_rebuild()
Models.TerraformExecuteGCP.model_rebuild()
Models.TerraformExecuteRequest.model_rebuild()
Models.Anomaly.model_rebuild()
Models.TrendAnalysis.model_rebuild()
Models.Insights.model_rebuild()
Models.ChartData.model_rebuild()
Models.NormalizedResource.model_rebuild()
Models.DiscoverySummary.model_rebuild()
Models.DiscoveryHistoryItem.model_rebuild()
Models.DashboardResponse.model_rebuild()
