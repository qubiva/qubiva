"""Chat Manager — orchestrates AI conversations with tool-calling loop.

Manages conversation lifecycle: create, send messages (with streaming),
list, get history, delete. The LLM is given tools to search cloud
schemas, inspect table columns, and execute live SQL queries against
per-session query pods.
"""
import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import AsyncIterator, List, Optional

from app.llm.base_provider import (
    BaseLLMProvider, LLMMessage, LLMTool, LLMToolCall, LLMProviderConfig,
)
from app.llm.provider_factory import create_provider
from app.cloud_schema import CloudSchemaRegistry
from app.query_session import QuerySessionManager

logger = logging.getLogger('uvicorn.error')

COLLECTION = "analyst_conversations"


@dataclass
class ChatEvent:
    """A single event yielded during streamed chat processing."""
    type: str   # "pod_status", "thinking", "tool_start", "tool_result",
                # "token", "done", "error"
    data: dict


# ── Fallback tool-call extraction for models that emit JSON in text ──

def _extract_tool_calls_from_text(
    content: str, tool_names: List[str]
) -> Optional[List[LLMToolCall]]:
    """Try to extract tool calls from plain text content.

    Some models (especially smaller open-source models) emit tool calls as JSON
    in the text response instead of using the structured tool_calls field.
    This function detects patterns like:
        {"name": "run_query", "arguments": {"sql": "SELECT ..."}}
    """
    if not content:
        return None

    # Look for JSON objects that contain a known tool name
    # Pattern: {"name": "<tool>", "arguments": ...}
    extracted = []
    for match in re.finditer(r'\{[^{}]*"name"\s*:\s*"([^"]+)"[^{}]*"arguments"\s*:', content):
        tool_name = match.group(1)
        if tool_name not in tool_names:
            continue
        # Try to parse the full JSON object starting at match position
        start = match.start()
        obj = _try_parse_json_at(content, start)
        if obj and isinstance(obj, dict) and "name" in obj and "arguments" in obj:
            args = obj["arguments"]
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            extracted.append(LLMToolCall(
                id=f"text_tc_{uuid.uuid4().hex[:8]}",
                name=obj["name"],
                arguments=args if isinstance(args, dict) else {},
            ))

    return extracted if extracted else None


def _try_parse_json_at(text: str, start: int) -> Optional[dict]:
    """Try to parse a JSON object starting at the given position in text."""
    # Find matching closing brace by counting braces
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == '\\' and in_string:
            escape = True
            continue
        if c == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _strip_tool_json_from_text(content: str, tool_names: List[str]) -> str:
    """Remove tool call JSON objects from text content."""
    result = content
    for match in re.finditer(r'\{[^{}]*"name"\s*:\s*"([^"]+)"[^{}]*"arguments"\s*:', content):
        tool_name = match.group(1)
        if tool_name not in tool_names:
            continue
        start = match.start()
        obj = _try_parse_json_at(content, start)
        if obj and isinstance(obj, dict) and "name" in obj:
            # Find the full extent and remove it
            depth = 0
            in_string = False
            escape = False
            for i in range(start, len(content)):
                c = content[i]
                if escape:
                    escape = False
                    continue
                if c == '\\' and in_string:
                    escape = True
                    continue
                if c == '"' and not escape:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        result = result.replace(content[start:i + 1], "", 1)
                        break
    # Strip Python-style function call syntax: tool_name("arg", "arg")
    # Models sometimes print these as text instead of structured tool calls
    tool_pattern = '|'.join(re.escape(n) for n in tool_names)
    result = re.sub(
        rf'(?:```[a-z]*\n)?(?:{tool_pattern})\s*\(.*?\)(?:\n```)?',
        '', result, flags=re.DOTALL,
    )
    # Clean up array brackets left after stripping JSON objects from arrays
    # e.g. [\n  ,\n  ,\n] becomes just whitespace
    result = re.sub(r'\[\s*(?:,\s*)*\]', '', result)
    # Clean up code fences that are now empty or contain only whitespace/punctuation
    result = re.sub(r'```[a-z]*\s*```', '', result)
    # Also handle incomplete/dangling code fences (opening without closing)
    # e.g. ```json\n\n (no closing ```)
    result = re.sub(r'```[a-z]*\s*$', '', result)
    # Handle closing fence without opening
    result = re.sub(r'^\s*```\s*', '', result)
    # Collapse multiple blank lines into at most one
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()


# ── Tool definitions exposed to the LLM ─────────────────────────────

def _build_tools(scope: str) -> List[LLMTool]:
    """Build the set of LLM tools available for a chat session."""
    tools = [
        LLMTool(
            name="list_available_accounts",
            description=(
                "List cloud accounts the user can access. Returns account IDs, "
                "cloud platforms, project names, and aliases. Use this to show "
                "the user what accounts are available before connecting to them. "
                "This reads metadata from the database — no live cloud connection needed."
            ),
            parameters={
                "type": "object",
                "properties": {},
            },
        ),
        LLMTool(
            name="connect_account",
            description=(
                "Connect a cloud account to this session so you can run queries "
                "against it. You MUST call this before running any SQL query. "
                "Pass the platform (aws/gcp/azure) and account_id. After connecting, "
                "use bare table names in queries (e.g. aws_s3_bucket, NOT "
                "aws_123456789.aws_s3_bucket). Do NOT use schema prefixes."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "platform": {
                        "type": "string",
                        "description": "Cloud platform: aws, gcp, or azure",
                    },
                    "account_id": {
                        "type": "string",
                        "description": "The cloud account ID to connect",
                    },
                },
                "required": ["platform", "account_id"],
            },
        ),
        LLMTool(
            name="search_tables",
            description=(
                "Search for cloud resource tables matching keywords. Use this to "
                "find which tables are available for querying cloud resources. "
                "Returns table names, descriptions, and column counts. "
                "This searches the static schema registry — no connection needed."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Keywords to search for (e.g. ['s3', 'bucket'] "
                            "or ['ec2', 'instance', 'public'])"
                        ),
                    },
                },
                "required": ["keywords"],
            },
        ),
        LLMTool(
            name="get_table_schema",
            description=(
                "Get the full column schema for a specific cloud resource table. "
                "Returns column names, types, and descriptions. Use this "
                "after search_tables to understand the available columns "
                "before writing a query."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "The exact table name (e.g. 'aws_s3_bucket')",
                    },
                },
                "required": ["table_name"],
            },
        ),
        LLMTool(
            name="run_query",
            description=(
                "Execute a SQL query against connected cloud accounts. "
                "You must connect_account first. Use PostgreSQL-compatible "
                "syntax. Always include a LIMIT clause (max 200 rows) and select "
                "only needed columns. Provide a brief explanation of what the query does."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "The SQL query to execute",
                    },
                    "explanation": {
                        "type": "string",
                        "description": "Brief explanation of what this query does",
                    },
                },
                "required": ["sql", "explanation"],
            },
        ),
        LLMTool(
            name="list_project_workspaces",
            description=(
                "List all Terraform workspaces in a project. "
                "Returns workspace names with their cloud account and "
                "Terraform version. At org scope you MUST pass project_name."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": (
                            "Project name to query. Required at org scope, "
                            "optional at project scope (defaults to current project)."
                        ),
                    },
                },
            },
        ),
        LLMTool(
            name="get_request_history",
            description=(
                "Get recent run history for a project. Returns "
                "request IDs, types, status, timestamps, and who requested "
                "them. Use this to audit infrastructure changes and runs. "
                "At org scope you MUST pass project_name."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": (
                            "Project name to query. Required at org scope, "
                            "optional at project scope (defaults to current project)."
                        ),
                    },
                    "request_type": {
                        "type": "string",
                        "description": (
                            "Filter by request type: 'terraform_run' (for "
                            "Terraform plan/apply/destroy), 'query_run' (for "
                            "cloud queries and benchmarks), 'discovery_run' "
                            "(for cloud resource discovery), or leave empty for "
                            "all types"
                        ),
                    },
                    "page": {
                        "type": "integer",
                        "description": "Page number (default 1)",
                    },
                },
            },
        ),
        LLMTool(
            name="get_request_details",
            description=(
                "Get detailed information about a specific run. Returns "
                "full metadata including state, error details, workspace, "
                "cloud account, timing, and for terraform_run the specific "
                "operation (plan/apply/destroy). "
                "At org scope you MUST pass project_name."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "request_id": {
                        "type": "string",
                        "description": "The request ID to look up",
                    },
                    "project_name": {
                        "type": "string",
                        "description": (
                            "Project name. Required at org scope, "
                            "optional at project scope."
                        ),
                    },
                },
                "required": ["request_id"],
            },
        ),
        LLMTool(
            name="get_request_logs",
            description=(
                "Retrieve the execution logs for a specific run. Returns "
                "the full log output from the Terraform or discovery runner "
                "pod. Use this to see what happened during a run — terraform "
                "plan output, apply changes, query results, errors, etc. "
                "At org scope you MUST pass project_name."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "request_id": {
                        "type": "string",
                        "description": "The request ID whose logs to fetch",
                    },
                    "project_name": {
                        "type": "string",
                        "description": (
                            "Project name. Required at org scope, "
                            "optional at project scope."
                        ),
                    },
                },
                "required": ["request_id"],
            },
        ),
        LLMTool(
            name="get_project_members",
            description=(
                "List all members of a project. Returns usernames "
                "(email addresses) of people who have access. "
                "At org scope you MUST pass project_name."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": (
                            "Project name to query. Required at org scope, "
                            "optional at project scope (defaults to current project)."
                        ),
                    },
                },
            },
        ),
        LLMTool(
            name="list_benchmarks",
            description=(
                "List available compliance benchmarks that can be run against "
                "the cloud account. Returns benchmark and control names "
                "(e.g., CIS, NIST, PCI DSS, SOC 2). Use this to discover "
                "which benchmarks are available before running one."
            ),
            parameters={
                "type": "object",
                "properties": {},
            },
        ),
        LLMTool(
            name="get_audit_log",
            description=(
                "Query the audit trail to see who performed configuration "
                "changes in Qubiva. Returns a log of mutations — who "
                "created/updated/deleted projects, cloud accounts, credentials, "
                "workspaces, users, and git repos. Filter by target type, "
                "action, or user. At org scope you MUST pass project_name."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "project_name": {
                        "type": "string",
                        "description": (
                            "Project name to query. Required at org scope, "
                            "optional at project scope (defaults to current project)."
                        ),
                    },
                    "target_type": {
                        "type": "string",
                        "description": (
                            "Filter by resource type: 'project', 'cloud_account', "
                            "'credential', 'workspace', 'user', 'github_repo', "
                            "or leave empty for all"
                        ),
                    },
                    "action": {
                        "type": "string",
                        "description": (
                            "Filter by action: 'create_project', 'update_credential', "
                            "'delete_cloud_account', 'add_member', etc. "
                            "Leave empty for all actions"
                        ),
                    },
                    "user_filter": {
                        "type": "string",
                        "description": "Filter by who performed the action (username/email)",
                    },
                    "days_back": {
                        "type": "integer",
                        "description": "How many days back to search (default 30, max 365)",
                    },
                },
            },
        ),
        LLMTool(
            name="run_benchmark",
            description=(
                "Run a compliance benchmark or control check against the live "
                "cloud infrastructure. Returns a summary of passed/failed/"
                "skipped controls with failure details. Benchmarks evaluate "
                "security and compliance posture (CIS, NIST, PCI DSS, etc.). "
                "Use list_benchmarks first to see available benchmarks. "
                "NOTE: Full benchmark suites can take 2-5 minutes to complete."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "benchmark": {
                        "type": "string",
                        "description": (
                            "The benchmark or control to run (e.g., "
                            "'benchmark.cis_v150', 'control.cis_v150_1_4'). "
                            "Use the name from list_benchmarks."
                        ),
                    },
                },
                "required": ["benchmark"],
            },
        ),
    ]

    return tools


def _build_system_prompt(
    scope: str,
    project_name: Optional[str],
    user: str = "",
    cloud_platform: Optional[str] = None,
    account_id: Optional[str] = None,
    connected_accounts: Optional[List[dict]] = None,
    available_accounts: Optional[List[dict]] = None,
) -> str:
    """Build the system prompt for the LLM."""
    if scope == "account":
        scope_desc = f"a single {(cloud_platform or '').upper()} cloud account (ID: {account_id})"
    elif scope == "project":
        scope_desc = f"all cloud accounts in the '{project_name}' project"
    elif scope == "org":
        scope_desc = "all cloud accounts across all projects the user has access to"
    else:
        scope_desc = "a cloud account"

    context_lines = [f"- You are speaking with: {user}", f"- Scope: {scope_desc}"]
    if project_name:
        context_lines.append(f"- Project: {project_name}")
    if cloud_platform:
        context_lines.append(f"- Primary platform: {cloud_platform.upper()}")
    context_block = "\n".join(context_lines)

    # Available accounts — pre-injected so the model knows exact IDs
    if available_accounts:
        acct_lines = "\n".join(
            f"  - account_id: {a['account_id']}, platform: {a.get('cloud_platform', a.get('platform', ''))}, "
            f"project: {a.get('project_name', project_name or 'unknown')}"
            + (f", alias: {a['alias']}" if a.get('alias') else "")
            for a in available_accounts
        )
        available_block = f"\n\n## Available Accounts (pre-loaded — do NOT call list_available_accounts)\nThese are the ONLY valid account IDs. NEVER guess or make up account IDs.\n{acct_lines}"
    else:
        available_block = "\n\n## Available Accounts (pre-loaded — do NOT call list_available_accounts)\nNo cloud accounts are configured yet. The user needs to add cloud accounts to their project(s) before cloud resources can be queried. You can still help with Category B tools (Terraform runs, workspaces, members, audit logs)."

    # Connected accounts status
    connected_block = ""
    if connected_accounts:
        acct_lines = "\n".join(
            f"  - {a['account_id']} ({a['platform']}) — connection: {a['platform']}_{a['account_id'].replace('-', '_').replace(':', '_')}"
            for a in connected_accounts
        )
        connected_block = f"\n\n## Currently Connected Accounts\n{acct_lines}"
    else:
        connected_block = "\n\n## Currently Connected Accounts\nNone yet. Use `connect_account` before running queries."

    # Scope-specific instructions
    if scope == "account":
        scope_instructions = (
            f"You are scoped to a single account: {account_id} ({(cloud_platform or '').upper()}). "
            f"Connect this account using connect_account(platform=\"{(cloud_platform or 'aws').lower()}\", account_id=\"{account_id}\") "
            f"before running any queries."
        )
    elif scope == "project":
        scope_instructions = (
            f"You are scoped to project '{project_name}'. The available accounts are listed above. "
            "Use `connect_account` with the EXACT account_id from the list above. "
            "Ask the user which account(s) to analyze, or connect the relevant ones based on their question."
        )
    else:  # org
        scope_instructions = (
            "You are at organization level. The available accounts are listed above. "
            "Use `connect_account` with the EXACT account_id from the list above. "
            "NEVER guess account IDs. Ask the user what they want to investigate, then connect the relevant accounts."
        )

    prompt = f"""You are a Cloud Infrastructure Analyst assistant. You help users understand, audit, and optimize their cloud infrastructure by querying live data and Qubiva platform data.

## Current Context
{context_block}
{available_block}
{connected_block}

## Scope Instructions
{scope_instructions}

## CRITICAL Rules
1. NEVER guess or fabricate account IDs. Only use IDs from the "Available Accounts" list.
2. NEVER print tool calls as text. Do not write function call syntax. JUST CALL the tool.
3. Call ONE tool at a time. Wait for the result before calling the next.
4. ALWAYS call `connect_account` BEFORE `run_query`.
5. When the user says "stop" or changes topic, acknowledge and move on.
6. If a tool fails, explain the error in plain English. Do not retry with the same arguments.
7. For multi-part questions, handle them ONE STEP at a time. Do NOT plan all steps upfront — execute each step, see the result, then proceed.
8. ACT IMMEDIATELY. Never say "let me do X" and then stop. Always execute the tool call in the same response. If you plan to call a tool, CALL IT — do not wait for user confirmation.

## Two Categories of Data — NEVER mix them

**Category A: Live Cloud Resources (use `run_query` with SQL)**
S3 buckets, EC2 instances, IAM users, VPCs, security groups, etc.
Requires: connect_account first, then search_tables → get_table_schema → run_query.

**Category B: Qubiva Platform Data (use dedicated tools, NO SQL)**
Terraform runs, workspaces, project members, audit logs, run logs.
These are NOT queryable via SQL. There are NO SQL tables for them.
Use: `get_request_history`, `get_request_details`, `get_request_logs`, `list_project_workspaces`, `get_project_members`, `get_audit_log`.

## Tools

### Cloud Account Connection
- `connect_account(platform, account_id)` — REQUIRED before any SQL query
- `list_available_accounts` — already called at startup; only call again if user adds new accounts mid-conversation

### Cloud Resource Queries (Category A — SQL)
- `search_tables(keywords)` — find cloud resource tables
- `get_table_schema(table_name)` — column details for a table
- `run_query(sql, explanation)` — execute SQL against connected accounts

### Qubiva Platform (Category B — NO SQL)
- `list_project_workspaces(project_name)` — list Terraform workspaces
- `get_request_history(project_name, request_type)` — list runs. Returns request_id, state, type, who, when
- `get_request_details(request_id, project_name)` — full details of one run
- `get_request_logs(request_id, project_name)` — execution logs of a run
- `get_project_members(project_name)` — team members
- `get_audit_log(project_name)` — who changed what in Qubiva config

**IMPORTANT**: All Category B tools require `project_name`. The project name is already shown in the "Current Context" and "Available Accounts" sections above — always use it.

## How to Answer "Show me the latest Terraform run"
1. Call `get_request_history(project_name="<project>", request_type="terraform_run")` — gets recent runs
2. Call `get_request_details(request_id=<id from step 1>, project_name="<project>")` — full details
3. Call `get_request_logs(request_id=<same id>, project_name="<project>")` — execution logs
Do NOT use `run_query` for this. Terraform data is NOT queryable via SQL.

## SQL Guidelines
- PostgreSQL syntax, always include LIMIT (max 200)
- Select specific columns, not SELECT *
- ALWAYS use bare table names: `aws_s3_bucket`, `aws_ec2_instance` — NO schema prefix
- Do NOT use `aws_all.table_name` or `aws_546288497174.table_name` — those will fail
- The bare table name automatically routes to the connected account(s)

## Response Guidelines
- Use markdown: headers, bullets, tables
- Present query results as markdown tables
- Highlight security issues and actionable recommendations
- Never fabricate data"""

    return prompt


# ── Chat Manager ─────────────────────────────────────────────────────

class ChatManager:
    """Manages AI analyst conversations with tool-calling orchestration."""

    def __init__(
        self,
        db_manager,
        config_manager,
        session_manager: QuerySessionManager,
        schema_registry: CloudSchemaRegistry,
        project_manager,
        rbac=None,
        request_tracker=None,
        log_streamer=None,
        audit_logger=None,
    ):
        self.db = db_manager
        self.config_manager = config_manager
        self.session_manager = session_manager
        self.schema_registry = schema_registry
        self.project_manager = project_manager
        self.rbac = rbac
        self.request_tracker = request_tracker
        self.log_streamer = log_streamer
        self.audit_logger = audit_logger
        self._provider: Optional[BaseLLMProvider] = None

    async def _check_project_access(self, username: str, project_name: str, org_roles: Optional[List[str]] = None) -> bool:
        """Check if user has analyst permission on the given project.

        Org admins bypass project-level checks. Regular users must have
        the 'project_analyst_use' permission on the project.
        """
        if org_roles and "org_admin" in org_roles:
            return True

        if not self.rbac:
            return True  # No RBAC configured, allow

        try:
            user_roles = await self.project_manager.get_user_roles_by_project(username, project_name)
            if not user_roles:
                return False
            has_access, _ = self.rbac.check_permissions(
                ["project_analyst_use"], user_roles, org_roles or []
            )
            return has_access
        except Exception as e:
            logger.warning("RBAC check failed for %s on %s: %s", username, project_name, e)
            return False

    async def _get_user_accessible_projects(self, username: str) -> List[str]:
        """Get list of project names the user has access to.

        Uses get_project_details_for_projects which respects membership.
        Returns project names as a list of strings.
        """
        try:
            # Check if user is org admin (wildcard access)
            user_doc = await self.db.find_document("users", {"username": username})
            org_roles = (user_doc or {}).get("org_roles", [])
            is_org_admin = "org_admin" in org_roles

            success, project_details = await self.project_manager.get_project_details_for_projects(
                username, project_names=None, is_org_user=is_org_admin,
            )
            if not success or not project_details:
                return []
            return list(project_details.keys())
        except Exception as e:
            logger.warning("Failed to get accessible projects for %s: %s", username, e)
            return []

    async def _get_provider(self) -> BaseLLMProvider:
        """Get or create the LLM provider from config."""
        if self._provider is not None:
            return self._provider

        analyst_config = self.config_manager.get_config("cloud_analyst") or {}
        llm_config = analyst_config.get("llm", {})

        # Resolve API key from config or env var
        from app.deps import get_llm_api_key
        api_key = get_llm_api_key()

        config = LLMProviderConfig(
            provider=llm_config.get("provider", "openai"),
            model=llm_config.get("model", "gpt-4o"),
            api_key=api_key,
            base_url=llm_config.get("base_url"),
            max_tokens=llm_config.get("max_tokens", 4096),
            temperature=llm_config.get("temperature", 0.1),
        )

        self._provider = create_provider(config)
        return self._provider

    async def create_conversation(
        self,
        user: str,
        project_name: Optional[str] = None,
        cloud_platform: Optional[str] = None,
        account_id: Optional[str] = None,
        scope: str = "account",
        org_roles: Optional[List[str]] = None,
    ) -> str:
        """Create a new analyst conversation and start its query session pod.

        Returns the conversation_id.
        """
        # RBAC check based on scope
        if scope == "org":
            # Org scope requires org_analyst_use permission
            if not self._check_org_analyst_access(org_roles):
                raise PermissionError(
                    "Access denied: you do not have org-level analyst permission"
                )
        else:
            # Account/project scope requires project_analyst_use
            if not project_name:
                raise ValueError("project_name is required for account/project scope")
            if not await self._check_project_access(user, project_name, org_roles):
                raise PermissionError(
                    f"Access denied: you do not have analyst permission on project '{project_name}'"
                )

        # For account scope, cloud_platform is required
        if scope == "account" and not cloud_platform:
            raise ValueError("cloud_platform is required for account scope")

        # Auto-detect cloud platform hint from project accounts (for plugin pre-install)
        platform_hint = cloud_platform
        if not platform_hint and project_name:
            platform_hint = await self._detect_platform(project_name)

        # Enforce max concurrent sessions per user
        session_config = (
            self.config_manager.get_config("cloud_analyst") or {}
        ).get("session", {})
        max_concurrent = session_config.get("max_concurrent_chats", 3)
        active_count = self.session_manager.count_active_sessions(user)
        if active_count >= max_concurrent:
            raise ValueError(
                f"You have {active_count} active chat sessions "
                f"(max {max_concurrent}). Close or wait for an idle "
                f"session to expire before starting a new one."
            )

        conversation_id = str(uuid.uuid4())

        doc = {
            "conversation_id": conversation_id,
            "user": user,
            "project_name": project_name,
            "cloud_platform": cloud_platform,
            "account_id": account_id,
            "scope": scope,
            "title": None,
            "messages": [],
            "pod_name": f"analyst-{conversation_id[:12].lower().replace('-', '')}",
        }
        await self.db.insert_document(COLLECTION, doc)

        # Start the session pod (lazy connect — no credentials at startup)
        await self.session_manager.create_session_pod(
            conversation_id=conversation_id,
            cloud_platform=platform_hint,
            user=user,
        )

        return conversation_id

    def _check_org_analyst_access(self, org_roles: Optional[List[str]]) -> bool:
        """Check if user has org-level analyst permission."""
        if not org_roles:
            return False
        if "org_admin" in org_roles:
            return True

        if not self.rbac:
            return True

        has_access, _ = self.rbac.check_permissions(
            ["org_analyst_use"], [], org_roles
        )
        return has_access

    async def send_message(
        self,
        conversation_id: str,
        user_message: str,
        user: str,
        org_roles: Optional[List[str]] = None,
    ) -> AsyncIterator[ChatEvent]:
        """Process a user message and stream back the AI response.

        Yields ChatEvent objects for real-time UI updates via SSE.
        """
        # Load conversation
        conv = await self.db.find_document(
            COLLECTION, {"conversation_id": conversation_id}
        )
        if not conv:
            yield ChatEvent(type="error", data={"message": "Conversation not found"})
            return
        if conv["user"] != user:
            yield ChatEvent(type="error", data={"message": "Access denied"})
            return

        # RBAC check: verify user still has access
        if conv["scope"] == "org":
            if not self._check_org_analyst_access(org_roles):
                yield ChatEvent(type="error", data={"message": "Access denied: you no longer have org-level analyst permission"})
                return
        elif conv.get("project_name"):
            if not await self._check_project_access(user, conv["project_name"], org_roles):
                yield ChatEvent(type="error", data={"message": "Access denied: you no longer have analyst permission on this project"})
                return

        # Wait for pod readiness
        pod_status = await self.session_manager.get_session_status(conversation_id)
        if pod_status == "starting":
            yield ChatEvent(type="pod_status", data={"status": "starting"})
            for _ in range(40):  # Up to ~120 seconds
                await asyncio.sleep(3)
                pod_status = await self.session_manager.get_session_status(
                    conversation_id
                )
                if pod_status != "starting":
                    break
            yield ChatEvent(type="pod_status", data={"status": pod_status})

        if pod_status == "error":
            error_msg = await self.session_manager.get_session_error(conversation_id)
            yield ChatEvent(type="error", data={
                "message": f"Session pod failed: {error_msg}"
            })
            return

        if pod_status == "terminated":
            # Auto-recreate pod for resumed conversations (lazy connect)
            yield ChatEvent(type="pod_status", data={"status": "starting"})
            await self.session_manager.create_session_pod(
                conversation_id=conversation_id,
                cloud_platform=conv.get("cloud_platform"),
                user=user,
            )
            for _ in range(40):
                await asyncio.sleep(3)
                pod_status = await self.session_manager.get_session_status(
                    conversation_id
                )
                if pod_status != "starting":
                    break
            yield ChatEvent(type="pod_status", data={"status": pod_status})
            if pod_status != "ready":
                error_msg = await self.session_manager.get_session_error(conversation_id)
                yield ChatEvent(type="error", data={
                    "message": f"Failed to resume session: {error_msg}"
                })
                return

        # Clean up incomplete messages from a previous aborted response.
        # When the user clicks "stop", partial assistant/tool messages may be
        # left in the history.  Only clean up if the last message indicates an
        # incomplete response (tool result without follow-up, or assistant with
        # only tool_calls and no content).  A completed response ends with an
        # assistant message that has content text.
        messages_list = conv.get("messages", [])
        if messages_list:
            last = messages_list[-1]
            last_role = last.get("role")
            is_incomplete = (
                last_role == "tool"
                or (last_role == "assistant" and last.get("tool_calls") and not last.get("content"))
            )
            if is_incomplete:
                original_len = len(messages_list)
                while messages_list and messages_list[-1].get("role") != "user":
                    messages_list.pop()
                if len(messages_list) != original_len:
                    logger.info(
                        "Cleaned up %d trailing incomplete messages from conversation %s",
                        original_len - len(messages_list),
                        conversation_id[:12],
                    )
                    await self.db.update_document(
                        COLLECTION,
                        {"conversation_id": conversation_id},
                        {"messages": messages_list},
                    )

        # Append user message to conversation
        user_msg = {"role": "user", "content": user_message}
        await self._append_message(conversation_id, user_msg)

        # Auto-generate title from first message
        if not conv.get("title"):
            title = user_message[:80]
            if len(user_message) > 80:
                title += "..."
            await self.db.update_document(
                COLLECTION,
                {"conversation_id": conversation_id},
                {"title": title},
            )

        # Build message history for LLM
        conv = await self.db.find_document(
            COLLECTION, {"conversation_id": conversation_id}
        )
        session_config = (
            self.config_manager.get_config("cloud_analyst") or {}
        ).get("session", {})
        max_history = session_config.get("max_history_messages", 50)
        max_tool_calls = session_config.get("max_tool_calls_per_turn", 5)

        # Fetch available accounts so the model knows the exact IDs
        fake_conv = {
            "scope": conv["scope"],
            "user": conv.get("user", ""),
            "project_name": conv.get("project_name"),
        }
        available_accounts_data = await self._tool_list_available_accounts(fake_conv)
        available_accounts = available_accounts_data.get("accounts", [])

        # Build system prompt with current connected accounts status
        connected = self.session_manager.get_connected_accounts(conversation_id)
        system_prompt = _build_system_prompt(
            scope=conv["scope"],
            project_name=conv.get("project_name"),
            user=conv.get("user", ""),
            cloud_platform=conv.get("cloud_platform"),
            account_id=conv.get("account_id"),
            connected_accounts=connected,
            available_accounts=available_accounts,
        )

        messages = [LLMMessage(role="system", content=system_prompt)]
        for msg in conv.get("messages", [])[-max_history:]:
            messages.append(LLMMessage(
                role=msg["role"],
                content=msg.get("content"),
                tool_calls=msg.get("tool_calls"),
                tool_call_id=msg.get("tool_call_id"),
                name=msg.get("name"),
            ))

        tools = _build_tools(conv["scope"])
        tool_names = [t.name for t in tools]
        provider = await self._get_provider()

        # Tool-calling loop with streaming
        tool_call_count = 0
        recent_tool_errors = []  # track (tool_name, error_msg) to detect loops
        while tool_call_count <= max_tool_calls:
            # Stream the LLM response
            accumulated_content = ""
            accumulated_tool_calls = []  # structured tool calls from stream
            has_yielded_tokens = False

            try:
                async for chunk in provider.chat_completion_stream(messages, tools):
                    # Stream text tokens to client in real-time
                    if chunk.content:
                        accumulated_content += chunk.content
                        yield ChatEvent(type="token", data={"content": chunk.content})
                        has_yielded_tokens = True

                    # Collect structured tool calls (emitted at end of stream)
                    if chunk.tool_calls:
                        accumulated_tool_calls = chunk.tool_calls
            except Exception as e:
                logger.error("LLM call failed: %s (type=%s)", e, type(e).__name__)
                if hasattr(e, 'response') and hasattr(e.response, 'text'):
                    logger.error("LLM error response body: %s", e.response.text[:2000])
                elif hasattr(e, 'body'):
                    logger.error("LLM error body: %s", str(e.body)[:2000])
                yield ChatEvent(type="error", data={"message": f"AI error: {e}"})
                return

            # Check for text-based tool calls (fallback for smaller models)
            if not accumulated_tool_calls and accumulated_content:
                extracted = _extract_tool_calls_from_text(accumulated_content, tool_names)
                if extracted:
                    # Clean the JSON out of the streamed text
                    clean_content = _strip_tool_json_from_text(
                        accumulated_content, tool_names
                    ).strip()
                    # Tell the UI to replace the streamed content (remove JSON)
                    if has_yielded_tokens:
                        yield ChatEvent(type="content_replace", data={
                            "content": clean_content
                        })
                    accumulated_content = clean_content
                    # Convert extracted tool calls to the same format
                    for tc in extracted:
                        accumulated_tool_calls.append({
                            "id": tc.id,
                            "name": tc.name,
                            "arguments": tc.arguments,
                        })

            # Normalise tool call objects
            tool_call_objs = []
            for tc_data in accumulated_tool_calls:
                if isinstance(tc_data, LLMToolCall):
                    tool_call_objs.append(tc_data)
                else:
                    tool_call_objs.append(LLMToolCall(
                        id=tc_data.get("id", f"tc_{uuid.uuid4().hex[:8]}"),
                        name=tc_data.get("name", ""),
                        arguments=tc_data.get("arguments", {}),
                    ))

            # Handle tool calls — execute ONE at a time to prevent
            # small models from hallucinating multiple simultaneous calls
            if tool_call_objs:
                tool_call_count += 1
                # Only take the first tool call
                tool_call_objs = tool_call_objs[:1]

                # Store assistant message with tool calls
                assistant_msg = {
                    "role": "assistant",
                    "content": accumulated_content or None,
                    "tool_calls": [
                        {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                        for tc in tool_call_objs
                    ],
                }
                await self._append_message(conversation_id, assistant_msg)
                messages.append(LLMMessage(
                    role="assistant",
                    content=accumulated_content or None,
                    tool_calls=tool_call_objs,
                ))

                # Execute each tool call
                for tc in tool_call_objs:
                    yield ChatEvent(type="tool_start", data={
                        "tool": tc.name,
                        "arguments": tc.arguments,
                        "id": tc.id,
                    })

                    result = await self._execute_tool(
                        conversation_id, conv, tc
                    )

                    yield ChatEvent(type="tool_result", data={
                        "tool": tc.name,
                        "id": tc.id,
                        "result": result,
                    })

                    # Track errors for loop detection
                    error_msg = result.get("error") if isinstance(result, dict) else None
                    if error_msg:
                        recent_tool_errors.append((tc.name, error_msg))

                    # Store tool result message
                    tool_msg = {
                        "role": "tool",
                        "content": json.dumps(result) if isinstance(result, (dict, list)) else str(result),
                        "tool_call_id": tc.id,
                        "name": tc.name,
                    }
                    await self._append_message(conversation_id, tool_msg)
                    messages.append(LLMMessage(
                        role="tool",
                        content=tool_msg["content"],
                        tool_call_id=tc.id,
                        name=tc.name,
                    ))

                # Detect repeated errors — if the same tool returned the same
                # error 2+ times, inject a stop message and break the loop
                if len(recent_tool_errors) >= 2:
                    last = recent_tool_errors[-1]
                    repeated = sum(1 for e in recent_tool_errors if e == last)
                    if repeated >= 2:
                        logger.warning(
                            "Tool %s failed %d times with same error in conversation %s, stopping loop",
                            last[0], repeated, conversation_id[:12],
                        )
                        yield ChatEvent(type="error", data={
                            "message": "The operation failed repeatedly. Check the error details above and try rephrasing your question."
                        })
                        return

                # Loop back to get the next LLM response
                continue

            # No tool calls — final text response (already streamed)
            # Strip any function-call-like text the model printed instead of
            # actually calling tools (common with smaller models)
            content = _strip_tool_json_from_text(
                accumulated_content, tool_names
            ).strip()
            if content != accumulated_content.strip() and has_yielded_tokens:
                yield ChatEvent(type="content_replace", data={
                    "content": content
                })
            if content:
                assistant_msg = {
                    "role": "assistant",
                    "content": content,
                }
                await self._append_message(conversation_id, assistant_msg)

            yield ChatEvent(type="done", data={})
            return

        # Exceeded tool call limit
        yield ChatEvent(type="token", data={
            "content": "\n\n*I've done as much as I can in one go. "
                       "Please ask a follow-up for anything I missed.*"
        })
        yield ChatEvent(type="done", data={})

    async def _execute_tool(
        self,
        conversation_id: str,
        conv: dict,
        tool_call: LLMToolCall,
    ) -> dict:
        """Execute a single tool call and return the result."""
        args = tool_call.arguments
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                return {"error": f"Invalid tool arguments: {args}"}

        # Determine platform for schema searches — use connected accounts or conv hint
        connected = self.session_manager.get_connected_accounts(conversation_id)
        platform = conv.get("cloud_platform")
        if not platform and connected:
            platform = connected[0]["platform"]

        if tool_call.name == "list_available_accounts":
            return await self._tool_list_available_accounts(conv)

        elif tool_call.name == "connect_account":
            return await self._tool_connect_account(conversation_id, conv, args)

        elif tool_call.name == "search_tables":
            keywords = args.get("keywords", [])
            results = self.schema_registry.search_tables(
                platform, keywords, limit=15
            )
            return {"tables": results}

        elif tool_call.name == "get_table_schema":
            table_name = args.get("table_name", "")
            schema = self.schema_registry.get_table_schema(platform, table_name)
            if schema:
                return schema
            return {"error": f"Table '{table_name}' not found in schema registry"}

        elif tool_call.name == "run_query":
            sql = args.get("sql", "")
            explanation = args.get("explanation", "")
            result = await self.session_manager.execute_query(
                conversation_id, sql
            )
            if result.error:
                return {"error": result.error, "sql": sql}
            return {
                "columns": result.columns,
                "rows": result.rows,
                "row_count": result.row_count,
                "truncated": result.truncated,
                "sql": sql,
                "explanation": explanation,
            }

        elif tool_call.name == "list_cloud_accounts":
            # Legacy alias — redirect to list_available_accounts
            return await self._tool_list_available_accounts(conv)

        elif tool_call.name == "list_project_workspaces":
            project = args.get("project_name") or conv.get("project_name")
            if not project:
                return {"error": "project_name is required. Call list_available_accounts first — it returns a 'projects' list with all accessible project names."}
            try:
                result = await self.project_manager.list_workspaces(project)
                workspaces = result
                if isinstance(result, tuple):
                    _, workspaces = result
                sanitized = [
                    {
                        "workspace_name": w.get("name") or w.get("workspace_name"),
                        "terraform_version": w.get("terraform_version", ""),
                        "cloud_platform": w.get("cloud_platform", ""),
                        "account_id": w.get("cloud_account", "") if isinstance(w.get("cloud_account"), str) else w.get("cloud_account", {}).get("account_id", ""),
                        "github_repo": w.get("github_repo_name", ""),
                    }
                    for w in (workspaces or [])
                ]
                return {"workspaces": sanitized}
            except Exception as e:
                return {"error": f"Failed to list workspaces: {e}"}

        elif tool_call.name == "get_request_history":
            if not self.request_tracker:
                return {"error": "Request history is not available"}
            project = args.get("project_name") or conv.get("project_name")
            if not project:
                return {"error": "project_name is required. Call list_available_accounts first — it returns a 'projects' list with all accessible project names."}
            try:
                req_type = args.get("request_type") or None
                page = args.get("page", 1)
                success, result = await self.request_tracker.list_requests(
                    project_name=project,
                    request_type=req_type,
                    page=page,
                    page_size=15,
                )
                if not success:
                    return {"error": str(result)}
                runs = result.get("runs", [])
                sanitized = [
                    {
                        "request_id": r.get("request_id"),
                        "request_type": r.get("request_type"),
                        "state": r.get("state"),
                        "requested_by": r.get("requested_by"),
                        "requested_on": str(r.get("requested_on", "")),
                        "workspace_name": r.get("workspace_name", ""),
                        "cloud_platform": r.get("cloud_platform", ""),
                        "account_id": r.get("account_id", ""),
                    }
                    for r in runs
                ]
                return {
                    "requests": sanitized,
                    "total": result.get("total", 0),
                    "page": result.get("page", 1),
                    "total_pages": result.get("total_pages", 1),
                }
            except Exception as e:
                return {"error": f"Failed to get request history: {e}"}

        elif tool_call.name == "get_request_details":
            if not self.request_tracker:
                return {"error": "Request details are not available"}
            project = args.get("project_name") or conv.get("project_name")
            if not project:
                return {"error": "project_name is required. Use get_request_history with a project_name first to find request IDs."}
            try:
                request_id = args.get("request_id", "")
                success, result = await self.request_tracker.get_request_details(request_id)
                if not success:
                    return {"error": str(result)}
                # Verify the request belongs to the resolved project
                if result.get("project_name") != project:
                    return {"error": "Request not found in the specified project"}
                details = {
                    "request_id": result.get("request_id"),
                    "request_type": result.get("request_type"),
                    "state": result.get("state"),
                    "requested_by": result.get("requested_by"),
                    "requested_on": str(result.get("requested_on", "")),
                    "workspace_name": result.get("workspace_name", ""),
                    "cloud_platform": result.get("cloud_platform", ""),
                    "account_id": result.get("account_id", ""),
                    "error": result.get("error"),
                    "completed_on": str(result.get("completed_on", "")),
                }
                # Include terraform-specific fields
                if result.get("terraform_operation"):
                    details["terraform_operation"] = result["terraform_operation"]
                if result.get("terraform_version"):
                    details["terraform_version"] = result["terraform_version"]
                # Include run type for query/benchmark runs
                if result.get("run_type"):
                    details["run_type"] = result["run_type"]
                if result.get("benchmark_id"):
                    details["benchmark_id"] = result["benchmark_id"]
                return details
            except Exception as e:
                return {"error": f"Failed to get request details: {e}"}

        elif tool_call.name == "get_request_logs":
            request_id = args.get("request_id", "")
            if not request_id:
                return {"error": "request_id is required"}
            project = args.get("project_name") or conv.get("project_name")
            if not project:
                return {"error": "project_name is required. Use get_request_history with a project_name first to find request IDs."}
            # Verify the request belongs to the resolved project
            if self.request_tracker:
                try:
                    success, result = await self.request_tracker.get_request_details(request_id)
                    if not success:
                        return {"error": str(result)}
                    if result.get("project_name") != project:
                        return {"error": "Request not found in the specified project"}
                except Exception:
                    pass
            # Fetch logs
            if not self.log_streamer:
                return {"error": "Log retrieval is not available"}
            try:
                log_text = await self.log_streamer.get_full_logs(request_id)
                if not log_text:
                    return {"error": "No logs found for this request. The logs may have expired or the run may not have produced output."}
                # Truncate if too long for LLM context
                max_log_chars = 15000
                truncated = len(log_text) > max_log_chars
                if truncated:
                    log_text = log_text[:max_log_chars] + "\n... [logs truncated]"
                return {
                    "request_id": request_id,
                    "logs": log_text,
                    "truncated": truncated,
                }
            except Exception as e:
                return {"error": f"Failed to retrieve logs: {e}"}

        elif tool_call.name == "get_project_members":
            project = args.get("project_name") or conv.get("project_name")
            if not project:
                return {"error": "project_name is required. Call list_available_accounts first — it returns a 'projects' list with all accessible project names."}
            try:
                result = await self.project_manager.get_project_members(project)
                members = result
                if isinstance(result, tuple):
                    _, members = result
                return {"members": members or []}
            except Exception as e:
                return {"error": f"Failed to get project members: {e}"}

        elif tool_call.name == "get_audit_log":
            if not self.audit_logger:
                return {"error": "Audit log is not available"}
            project = args.get("project_name") or conv.get("project_name")
            if not project:
                return {"error": "project_name is required. Call list_available_accounts first — it returns a 'projects' list with all accessible project names."}
            try:
                target_type = args.get("target_type", "")
                action_filter = args.get("action", "")
                user_filter = args.get("user_filter", "")
                days_back = min(args.get("days_back", 30), 365)
                events = await self.audit_logger.query_events(
                    project_name=project,
                    target_type=target_type,
                    action=action_filter,
                    user=user_filter,
                    limit=50,
                    days_back=days_back,
                )
                return {
                    "events": events,
                    "count": len(events),
                    "project": project,
                    "filters": {
                        "target_type": target_type or "all",
                        "action": action_filter or "all",
                        "user": user_filter or "all",
                        "days_back": days_back,
                    },
                }
            except Exception as e:
                return {"error": f"Failed to query audit log: {e}"}

        elif tool_call.name == "list_benchmarks":
            result = await self.session_manager.exec_in_pod(
                conversation_id,
                ["/bin/sh", "-c",
                 "cd /home/runner/workspace && sp check list 2>&1"],
                timeout=30,
            )
            if "error" in result:
                return result
            output = result.get("output", "")
            if not output.strip():
                return {"error": "No benchmarks available. The compliance mod may still be installing — try again in a moment."}
            # Parse the list output into structured entries
            benchmarks = []
            for line in output.strip().splitlines():
                line = line.strip()
                if not line or line.startswith("BENCHMARK") or line.startswith("---"):
                    continue
                benchmarks.append(line)
            return {"benchmarks": benchmarks}

        elif tool_call.name == "run_benchmark":
            benchmark = args.get("benchmark", "").strip()
            if not benchmark:
                return {"error": "benchmark name is required"}
            # Validate benchmark name to prevent command injection
            if not re.match(r'^[a-zA-Z0-9_.]+$', benchmark):
                return {"error": "Invalid benchmark name — only letters, numbers, underscores, and dots are allowed"}
            session_config = (
                self.config_manager.get_config("cloud_analyst") or {}
            ).get("session", {})
            bench_timeout = session_config.get("benchmark_timeout_seconds", 300)

            result = await self.session_manager.exec_in_pod(
                conversation_id,
                ["/bin/sh", "-c",
                 f"cd /home/runner/workspace && sp check {benchmark} --output json --progress=false 2>&1"],
                timeout=bench_timeout,
            )
            if "error" in result:
                return result
            output = result.get("output", "")
            # Try to parse as JSON and extract summary
            try:
                data = json.loads(output)
                return self._extract_benchmark_summary(data)
            except (json.JSONDecodeError, ValueError):
                # Return raw output (possibly an error message from the query engine)
                if len(output) > 15000:
                    output = output[:15000] + "\n... [output truncated]"
                return {"raw_output": output}

        return {"error": f"Unknown tool: {tool_call.name}"}

    def _extract_benchmark_summary(self, data: dict) -> dict:
        """Extract a concise summary from benchmark check JSON output."""
        summary_raw = data.get("summary", {})
        status_counts = summary_raw.get("status", {})
        result = {
            "title": data.get("title", data.get("name", "")),
            "status": data.get("status", ""),
            "summary": {
                "total": status_counts.get("total", 0),
                "ok": status_counts.get("ok", 0),
                "alarm": status_counts.get("alarm", 0),
                "error": status_counts.get("error", 0),
                "skip": status_counts.get("skip", 0),
                "info": status_counts.get("info", 0),
            },
        }

        # Collect failed controls (alarm + error status)
        failed = []
        self._collect_failed_controls(data, failed)

        result["failed_controls"] = failed[:50]
        if len(failed) > 50:
            result["total_failures"] = len(failed)
            result["note"] = f"Showing 50 of {len(failed)} failed controls"
        return result

    def _collect_failed_controls(self, node: dict, failed: list):
        """Recursively collect failed controls from benchmark JSON."""
        if node.get("type") == "control" and node.get("status") in ("alarm", "error"):
            # Gather sample failure reasons from results
            reasons = []
            for r in (node.get("results") or [])[:5]:
                if r.get("status") in ("alarm", "error"):
                    reasons.append({
                        "status": r.get("status"),
                        "reason": r.get("reason", ""),
                        "resource": r.get("resource", ""),
                    })
            failed.append({
                "name": node.get("name", ""),
                "title": node.get("title", ""),
                "status": node.get("status"),
                "failed_resources": len([
                    r for r in (node.get("results") or [])
                    if r.get("status") in ("alarm", "error")
                ]),
                "sample_failures": reasons,
            })
            return

        for child in node.get("children", []):
            self._collect_failed_controls(child, failed)

    @staticmethod
    def _extract_accounts(result) -> list:
        """Safely extract account list from get_cloud_accounts_by_project_name.

        The method returns either a list, or a tuple (bool, list|str).
        When no accounts exist it returns (False, "error message").
        """
        if isinstance(result, list):
            return result
        if isinstance(result, tuple):
            ok, data = result
            if ok and isinstance(data, list):
                return data
        return []

    async def _tool_list_available_accounts(self, conv: dict) -> dict:
        """Handle the list_available_accounts tool call."""
        try:
            scope = conv.get("scope", "account")
            user = conv.get("user", "")

            if scope == "org":
                # Org scope: list accounts from all projects the user has access to
                all_accounts = []
                user_projects = await self._get_user_accessible_projects(user)
                for proj_name in user_projects:
                    accounts = self._extract_accounts(
                        await self.project_manager.get_cloud_accounts_by_project_name(proj_name)
                    )
                    for a in accounts:
                        all_accounts.append({
                            "account_id": a.get("account_id"),
                            "cloud_platform": a.get("cloud_platform"),
                            "alias": a.get("alias", ""),
                            "project_name": proj_name,
                        })
                return {"accounts": all_accounts, "projects": user_projects, "scope": "org"}
            else:
                # Project/account scope: list accounts from this project
                project_name = conv.get("project_name", "")
                accounts = self._extract_accounts(
                    await self.project_manager.get_cloud_accounts_by_project_name(project_name)
                )
                sanitized = [
                    {
                        "account_id": a.get("account_id"),
                        "cloud_platform": a.get("cloud_platform"),
                        "alias": a.get("alias", ""),
                        "project_name": project_name,
                    }
                    for a in accounts
                ]
                return {"accounts": sanitized, "projects": [project_name], "scope": scope}
        except Exception as e:
            return {"error": f"Failed to list accounts: {e}"}

    async def _tool_connect_account(
        self, conversation_id: str, conv: dict, args: dict
    ) -> dict:
        """Handle the connect_account tool call."""
        platform = args.get("platform", "").lower()
        account_id = args.get("account_id", "")

        if not platform or not account_id:
            return {"error": "Both platform and account_id are required"}
        if platform not in ("aws", "gcp", "azure"):
            return {"error": f"Unsupported platform: {platform}. Use aws, gcp, or azure."}

        # Determine which project this account belongs to
        project_name = conv.get("project_name")
        if not project_name:
            # Org scope — need to find which project this account belongs to
            project_name = await self._find_project_for_account(
                conv.get("user", ""), platform, account_id
            )
            if not project_name:
                return {"error": f"Account {account_id} not found in any accessible project"}

        result = await self.session_manager.connect_account(
            conversation_id=conversation_id,
            platform=platform,
            account_id=account_id,
            project_name=project_name,
        )
        return result

    async def _find_project_for_account(
        self, user: str, platform: str, account_id: str
    ) -> Optional[str]:
        """Find which project a cloud account belongs to (for org scope)."""
        try:
            user_projects = await self._get_user_accessible_projects(user)
            for proj_name in user_projects:
                accounts = self._extract_accounts(
                    await self.project_manager.get_cloud_accounts_by_project_name(proj_name)
                )
                for a in accounts:
                    if (a.get("account_id") == account_id
                            and a.get("cloud_platform", "").lower() == platform):
                        return proj_name
        except Exception as e:
            logger.warning("Failed to find project for account %s: %s", account_id, e)
        return None

    async def _detect_platform(self, project_name: str) -> Optional[str]:
        """Detect the cloud platform(s) from a project's cloud accounts.

        Returns a single platform name if all accounts share the same
        platform, or ``"all"`` when accounts span multiple platforms so
        the session pod pre-installs every plugin at startup.
        """
        try:
            accounts = self._extract_accounts(
                await self.project_manager.get_cloud_accounts_by_project_name(project_name)
            )
            if accounts:
                platforms = [a.get("cloud_platform", "").lower() for a in accounts if a.get("cloud_platform")]
                if platforms:
                    unique = set(platforms)
                    if len(unique) > 1:
                        return "all"
                    return unique.pop()
        except Exception as e:
            logger.warning("Failed to detect platform for project %s: %s", project_name, e)
        return None

    async def _append_message(self, conversation_id: str, message: dict):
        """Append a message to the conversation's message history in MongoDB.

        Uses $slice to cap stored messages and prevent document bloat.
        The LLM already only sees the last max_history_messages (default 50),
        but this ensures the MongoDB doc itself doesn't grow unbounded.
        """
        session_config = (
            self.config_manager.get_config("cloud_analyst") or {}
        ).get("session", {})
        max_stored = session_config.get("max_stored_messages", 200)

        await self.db.update_document(
            COLLECTION,
            {"conversation_id": conversation_id},
            {"$push": {"messages": {"$each": [message], "$slice": -max_stored}}},
        )

    async def list_conversations(
        self,
        user: str,
        project_name: Optional[str] = None,
        scope: Optional[str] = None,
    ) -> List[dict]:
        """List conversations for a user, optionally filtered by project or scope."""
        query = {"user": user}
        if project_name:
            query["project_name"] = project_name
        if scope:
            query["scope"] = scope

        convs = await self.db.find_documents(COLLECTION, query)
        return [
            {
                "conversation_id": c["conversation_id"],
                "title": c.get("title") or "New conversation",
                "project_name": c["project_name"],
                "cloud_platform": c["cloud_platform"],
                "scope": c["scope"],
                "created_at": c.get("created_at", ""),
                "updated_at": c.get("updated_at", ""),
                "message_count": len(c.get("messages", [])),
            }
            for c in convs
        ]

    async def get_conversation_history(
        self, conversation_id: str, user: str
    ) -> Optional[dict]:
        """Get full conversation history."""
        conv = await self.db.find_document(
            COLLECTION, {"conversation_id": conversation_id}
        )
        if not conv or conv["user"] != user:
            return None

        # Filter out system messages — only return user-visible messages
        visible_messages = [
            m for m in conv.get("messages", [])
            if m.get("role") in ("user", "assistant", "tool")
        ]

        return {
            "conversation_id": conv["conversation_id"],
            "title": conv.get("title") or "New conversation",
            "project_name": conv["project_name"],
            "cloud_platform": conv["cloud_platform"],
            "account_id": conv.get("account_id"),
            "scope": conv["scope"],
            "messages": visible_messages,
            "created_at": conv.get("created_at", ""),
            "updated_at": conv.get("updated_at", ""),
        }

    async def delete_conversation(self, conversation_id: str, user: str) -> bool:
        """Delete a conversation and destroy its session pod."""
        conv = await self.db.find_document(
            COLLECTION, {"conversation_id": conversation_id}
        )
        if not conv or conv["user"] != user:
            return False

        # Destroy the session pod
        await self.session_manager.destroy_session_pod(conversation_id)

        # Delete from MongoDB
        await self.db.delete_document(
            COLLECTION, {"conversation_id": conversation_id}
        )
        return True

    async def restart_session(self, conversation_id: str, user: str) -> bool:
        """Restart the session pod for an existing conversation."""
        conv = await self.db.find_document(
            COLLECTION, {"conversation_id": conversation_id}
        )
        if not conv or conv["user"] != user:
            return False

        # Detect platform hint for plugin pre-install
        platform_hint = conv.get("cloud_platform")
        if not platform_hint and conv.get("project_name"):
            platform_hint = await self._detect_platform(conv["project_name"])

        # Destroy existing pod (if any) and create a fresh one (lazy connect)
        await self.session_manager.destroy_session_pod(conversation_id)
        await self.session_manager.create_session_pod(
            conversation_id=conversation_id,
            cloud_platform=platform_hint,
            user=user,
        )
        return True

    async def cleanup_old_conversations(self):
        """Delete conversations exceeding age or per-user count limits.

        Configurable via cloud_analyst.conversation_retention in app config:
          max_age_days: delete conversations older than this (default 30)
          max_per_user: keep only the most recent N per user (default 50)
        """
        retention_config = (
            self.config_manager.get_config("cloud_analyst") or {}
        ).get("conversation_retention", {})
        max_age_days = retention_config.get("max_age_days", 30)
        max_per_user = retention_config.get("max_per_user", 50)

        deleted_count = 0

        # 1. Delete conversations older than max_age_days
        cutoff = datetime.utcnow() - timedelta(days=max_age_days)
        old_convs = await self.db.find_documents(
            COLLECTION, {"created_at": {"$lt": cutoff}}
        )
        for conv in old_convs:
            cid = conv["conversation_id"]
            await self.session_manager.destroy_session_pod(cid)
            await self.db.delete_document(COLLECTION, {"conversation_id": cid})
            deleted_count += 1

        # 2. Per-user count cap — keep only the most recent max_per_user
        pipeline = [
            {"$group": {"_id": "$user", "count": {"$sum": 1}}},
            {"$match": {"count": {"$gt": max_per_user}}},
        ]
        try:
            col_name = self.db.collections.get(COLLECTION, COLLECTION)
            col = self.db.db[col_name]
            async for user_doc in col.aggregate(pipeline):
                username = user_doc["_id"]
                # Find conversations for this user, sorted oldest first
                user_convs = await self.db.find_documents(
                    COLLECTION,
                    {"user": username},
                    sort=[("created_at", 1)],
                )
                excess = len(user_convs) - max_per_user
                for conv in user_convs[:excess]:
                    cid = conv["conversation_id"]
                    await self.session_manager.destroy_session_pod(cid)
                    await self.db.delete_document(COLLECTION, {"conversation_id": cid})
                    deleted_count += 1
        except Exception as e:
            logger.warning("Per-user conversation cleanup failed: %s", e)

        if deleted_count > 0:
            logger.info("Cleaned up %d old analyst conversations", deleted_count)
