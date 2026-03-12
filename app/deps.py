"""
Shared dependencies for Qubiva.

All singleton manager instances and dependency injection functions live here.
Route modules import what they need from this module.
"""

import os
import logging

from dotenv import load_dotenv
from fastapi.templating import Jinja2Templates

from app.database_generic_operator import MongoDBManager
from app.user_authentication import UserAuthentication
from app.kms_manager import KMSManager
from app.project_manager import ProjectManager
from app.project_resource_locator import ProjectResourceLocator
from app.rbac import RBAC
from app.request_manager import RequestTracker
from app.log_streamer import CloudWatchLogStreamer
from app.log_persistence import LogPersistenceService
from app.terraform_versions import TerraformVersionManager
from app.tasks import TasksConfig
from app.email_service import EmailService
from app.scheduler import Scheduler
from app.app_config_manager import ConfigManager
from app.tags_manager import TagsManager
from app.cloud_alerts_manager import CloudAlertManager
from app.alert_configurator import AlertConfigurator
from app.artifacts_downloader import (
    ArtifactsFileHandler,
)
from app.stats import StatsProvider
from app.discovery_manager import DiscoveryManager
from app.discovery_dashboard import DiscoveryDashboard
from app.cloud_schema import CloudSchemaRegistry
from app.query_session import QuerySessionManager
from app.chat_manager import ChatManager
from app.audit_logger import AuditLogger

load_dotenv()
logger = logging.getLogger("uvicorn.error")

# Conditional SSO import - requires python3-saml (xmlsec system dependency)
try:
    from app.sso_manager import SSOManager
    SSO_AVAILABLE = True
except ImportError:
    logger.info("SSO features disabled (python3-saml not installed)")
    SSOManager = None
    SSO_AVAILABLE = False

# ---------------------------------------------------------------------------
# Singleton manager instances
# ---------------------------------------------------------------------------

db_manager = MongoDBManager()
kms_manager = KMSManager()
email_service = EmailService(sender_email="admin@qubiva.io")
scheduler = Scheduler(db_manager, email_service)
rbac = RBAC(ConfigManager)
project_manager = ProjectManager(
    db_manager, kms_manager, email_service, rbac, scheduler
)
project_resource_locator = ProjectResourceLocator(project_manager)
authenticator = UserAuthentication(db_manager, kms_manager)

if SSO_AVAILABLE and SSOManager is not None:
    sso_manager = SSOManager(db_manager, kms_manager, project_manager)
    logger.info("SSO Manager initialized")
else:
    sso_manager = None
    logger.info("SSO Manager disabled (LOCAL_DEV mode or missing dependencies)")

master_admin = os.getenv("MASTER_ADMIN_USER", "admin@qubiva.local")
tf_versions_manager = TerraformVersionManager("app/terraform_versions.json")
request_tracker = RequestTracker(db_manager, email_service)
log_persistence = LogPersistenceService(ConfigManager)
logstreamer = CloudWatchLogStreamer(db_manager, log_persistence=log_persistence)
tasks_config = TasksConfig(db_manager, ConfigManager)
tags_manager = TagsManager(db_manager)
alerts_manager = CloudAlertManager(db_manager, email_service, project_manager)
alert_configurator = AlertConfigurator(project_manager, db_manager)
artifacts_handler = ArtifactsFileHandler()
stats_provider = StatsProvider(
    project_manager=project_manager,
    tasks_manager=tasks_config,
    cloud_alerts_manager=alerts_manager,
    scheduler=scheduler,
    request_tracker=request_tracker,
)
discovery_manager = DiscoveryManager(db_manager, ConfigManager)
discovery_dashboard = DiscoveryDashboard(db_manager, ConfigManager)

audit_logger = AuditLogger(config_manager=ConfigManager)

# Cloud Analyst (AI chat) components
schema_registry = CloudSchemaRegistry()
session_manager = QuerySessionManager(project_manager, ConfigManager)
stats_provider.session_manager = session_manager
chat_manager = ChatManager(
    db_manager=db_manager,
    config_manager=ConfigManager,
    session_manager=session_manager,
    schema_registry=schema_registry,
    project_manager=project_manager,
    rbac=rbac,
    request_tracker=request_tracker,
    log_streamer=logstreamer,
    audit_logger=audit_logger,
)

# Runner pod pools (pre-warmed pods for IaC/discovery batch runs)
from app.runner_pool import RunnerPoolManager, RunnerType

iac_pool_manager = RunnerPoolManager(
    RunnerType.IAC, ConfigManager, tf_versions=tf_versions_manager
)
discovery_pool_manager = RunnerPoolManager(
    RunnerType.DISCOVERY, ConfigManager
)

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

templates = Jinja2Templates(directory="pages/jinja2templates")

# Static content URL for CDN override
static_content_url = os.getenv("STATIC_CONTENT_URL", "")
if static_content_url and not static_content_url.startswith("http"):
    static_content_url = "https://" + static_content_url
templates.env.globals["static_content_url"] = static_content_url
templates.env.globals["app_base_url"] = ""  # Set properly in app.py lifespan

release_version = os.getenv("RELEASE_VERSION", "local-dev")
templates.env.globals["release_version"] = release_version
templates.env.globals["app_banner_message"] = os.getenv("APP_BANNER_MESSAGE", "")


# ---------------------------------------------------------------------------
# Dependency injection functions
# ---------------------------------------------------------------------------

def get_request_tracker():
    return request_tracker


async def get_scheduler():
    return scheduler


async def get_log_streamer():
    return logstreamer


def get_llm_api_key() -> str:
    """Resolve the LLM API key from config and/or environment.

    Checks config ``cloud_analyst.llm.api_key`` first (supports hot-reload),
    then falls back to the env var named in ``cloud_analyst.llm.api_key_env``.
    Returns empty string if neither is set.
    """
    analyst_config = ConfigManager.get_config("cloud_analyst") or {}
    llm_config = analyst_config.get("llm", {})
    api_key = llm_config.get("api_key") or ""
    api_key_env = llm_config.get("api_key_env", "")
    if api_key_env:
        api_key = os.environ.get(api_key_env, "") or api_key
    return api_key


def is_analyst_ready() -> bool:
    """Check if Cloud Analyst is fully configured and ready to use.

    Requires: LLM provider + model + API key (from config or env var).
    """
    analyst_config = ConfigManager.get_config("cloud_analyst") or {}
    llm_config = analyst_config.get("llm", {})
    return bool(
        llm_config.get("provider")
        and llm_config.get("model")
        and get_llm_api_key()
    )


def get_app_base_url() -> str:
    """
    Get the externally-reachable base URL for this Qubiva instance.
    Used for webhook URLs, email links, SAML config, etc.

    Resolution order:
    1. app.base_url from app config (ConfigMap)
    2. DOMAIN env var (backward compat, constructs https://{domain})
    3. None (caller must handle)
    """
    url = ConfigManager.get_config('app', 'base_url')
    if url:
        return url.rstrip('/')
    domain = os.getenv('DOMAIN')
    if domain:
        return f"https://{domain}"
    return None
