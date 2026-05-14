#!/bin/bash

# =============================================================================
# Qubiva IaC Runner
#
# Supports both OpenTofu (default) and HashiCorp Terraform as IaC engines.
# Set TF_ENGINE=tofu (default) or TF_ENGINE=terraform via config.
# =============================================================================

# IaC engine selection (tofu or terraform)
TF_ENGINE="${TF_ENGINE:-tofu}"

# --- Pool mode: prepare environment and wait for execution trigger -----------
if [[ "$POOL_MODE" == "true" ]]; then
    echo "=== POOL MODE: Preparing IaC runner pod (engine: $TF_ENGINE) ==="

    # Create directories for runtime use
    mkdir -p /usr/local/terraform-versions 2>/dev/null
    mkdir -p /usr/local/conftest-versions 2>/dev/null

    # IaC engine version is workspace-specific — downloaded on-demand at execution time.
    # Only conftest (config-level default) is worth pre-installing.

    # Pre-install conftest if version specified
    if [[ -n "$POOL_CONFTEST_VERSION" ]]; then
        CONFTEST_DIR="/usr/local/conftest-versions"
        mkdir -p "$CONFTEST_DIR" 2>/dev/null
        CONFTEST_BIN="${CONFTEST_DIR}/conftest_${POOL_CONFTEST_VERSION}"
        if [[ ! -f "$CONFTEST_BIN" ]]; then
            echo "Downloading Conftest $POOL_CONFTEST_VERSION..."
            TMP_DIR=$(mktemp -d)
            cd "$TMP_DIR"
            if [[ "$POOL_CONFTEST_VERSION" == "latest" ]]; then
                ACTUAL_VERSION=$(curl -s https://api.github.com/repos/open-policy-agent/conftest/releases/latest | jq -r '.tag_name' | sed 's/^v//')
            else
                ACTUAL_VERSION="$POOL_CONFTEST_VERSION"
            fi
            if [[ -n "$ACTUAL_VERSION" && "$ACTUAL_VERSION" != "null" ]]; then
                wget -q "https://github.com/open-policy-agent/conftest/releases/download/v${ACTUAL_VERSION}/conftest_${ACTUAL_VERSION}_Linux_x86_64.tar.gz" -O conftest.tar.gz
                if [[ $? -eq 0 ]]; then
                    tar -xzf conftest.tar.gz
                    mv conftest "$CONFTEST_BIN"
                    echo "Conftest $ACTUAL_VERSION: downloaded and cached"
                fi
            fi
            cd /
            rm -rf "$TMP_DIR"
        fi
    fi

    # Signal readiness
    touch /tmp/pool_ready
    echo "=== POOL MODE: Ready. Waiting for execution trigger... ==="

    # Wait for trigger file (created by RunnerPoolManager via exec)
    while [[ ! -f /tmp/start_execution ]]; do
        sleep 1
    done

    echo "=== POOL MODE: Trigger received, loading job environment ==="

    # Source the injected environment variables
    if [[ -f /tmp/job_env.sh ]]; then
        source /tmp/job_env.sh
    fi

    # Re-read TF_ENGINE in case the job overrides it
    TF_ENGINE="${TF_ENGINE:-tofu}"
    echo "=== POOL MODE: Starting execution (engine: $TF_ENGINE) ==="
fi

# =============================================================================
# Normal execution starts here (both pool and non-pool modes)
# =============================================================================

# Read environment variables
TERRAFORM_VERSION=${TERRAFORM_VERSION}
PROJECT_NAME=${PROJECT_NAME}
WORKSPACE_NAME=${WORKSPACE_NAME}
REQUEST_ID=${REQUEST_ID}
QUBIVA_API_ENDPOINT=${QUBIVA_API_ENDPOINT}
GITHUB_REPO=${GITHUB_REPO}
GITHUB_TOKEN=${GITHUB_TOKEN}
GITHUB_BRANCH=${GITHUB_BRANCH}
TF_CONFIG_PATH=${TF_CONFIG_PATH}

REPO_POLICY_PATH=${REPO_POLICY_PATH}
ORG_POLICY_REPO_URL=${ORG_POLICY_REPO_URL}
ORG_POLICY_BRANCH=${ORG_POLICY_BRANCH:-"main"}
ORG_POLICY_TOKEN=${ORG_POLICY_TOKEN}
ORG_POLICY_PATH=${ORG_POLICY_PATH:-"/policies"}
CONFTEST_VERSION=${CONFTEST_VERSION:-"latest"}
INTERNAL_API_KEY="${INTERNAL_API_KEY:-}"
TF_BACKEND_TYPE="${TF_BACKEND_TYPE:-kubernetes}"

CLOUD_PLATFORM=${CLOUD_PLATFORM}

if [[ -n "$GOOGLE_APPLICATION_CREDENTIALS_B64" ]]; then
    if [[ "${CLOUD_PLATFORM,,}" == "gcp" ]]; then
        echo "Setting up GCP credentials..."
        
        mkdir -p /tmp || handle_error "Failed to create /tmp directory"
        
        GOOGLE_CREDENTIALS_FILE=$(mktemp /tmp/google_credentials_XXXXXX.json) || handle_error "Failed to create temporary credentials file"
        chmod 600 "$GOOGLE_CREDENTIALS_FILE" || handle_error "Failed to set permissions on credentials file"
        
        # Ensure cleanup on script exit
        trap 'rm -f "$GOOGLE_CREDENTIALS_FILE"' EXIT
        
        # Base64 decode credentials
        echo "$GOOGLE_APPLICATION_CREDENTIALS_B64" | base64 -d > "$GOOGLE_CREDENTIALS_FILE" || handle_error "Failed to decode GCP credentials"
        
        # Validate JSON and required fields
        if ! jq -e '.type and .project_id and .private_key' "$GOOGLE_CREDENTIALS_FILE" >/dev/null 2>&1; then
            handle_error "Invalid or incomplete GCP credentials JSON"
        fi
        
        export GOOGLE_APPLICATION_CREDENTIALS="$GOOGLE_CREDENTIALS_FILE"
        echo "GCP credentials configured successfully"
    else
        echo "GOOGLE_APPLICATION_CREDENTIALS_B64 is set but cloud platform is not GCP. Skipping."
    fi
fi

if [[ "${CLOUD_PLATFORM,,}" == "gcp" && -z "$GOOGLE_APPLICATION_CREDENTIALS" ]]; then
    handle_error "GCP credentials are required but not provided"
fi

if [[ "$CLOUD_PLATFORM" == "azure" ]]; then
    export ARM_SUBSCRIPTION_ID="$CLOUD_ACCOUNT_ID"
fi

# Function to update error details
function update_error_details() {
    local error_message=$1
    local payload="{\"error_message\": \"$error_message\"}"

    if [[ -n "$QUBIVA_API_ENDPOINT" && -n "$REQUEST_ID" ]]; then
        local retry_count=0
        local max_retries=12
        
        while [ $retry_count -lt $max_retries ]; do
            response=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$QUBIVA_API_ENDPOINT/api/internal/v1/update_request_error_details/$REQUEST_ID" \
                -H "Content-Type: application/json" \
                -H "X-Internal-Api-Key: $INTERNAL_API_KEY" \
                -d "$payload")
            if [ "$response" = "200" ]; then
                return 0
            fi
            echo "Failed to update error details. HTTP status: $response"
            retry_count=$((retry_count+1))
            if [ $retry_count -lt $max_retries ]; then
                echo "Retrying error details update in 5 seconds..."
                sleep 5
            fi
        done
        return 1
    fi
}

# Function to update task state
function update_task_state() {
    local state=$1
    local error_message=$2
    local payload="{\"state\": \"$state\""
    if [[ -n "$error_message" ]]; then
        payload+=", \"error\": \"$error_message\""
    fi
    payload+="}"

    if [[ -n "$QUBIVA_API_ENDPOINT" && -n "$REQUEST_ID" ]]; then
        local retry_count=0
        local max_retries=12
        
        while [ $retry_count -lt $max_retries ]; do
            response=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$QUBIVA_API_ENDPOINT/api/internal/v1/update_request_state/$REQUEST_ID" \
                -H "Content-Type: application/json" \
                -H "X-Internal-Api-Key: $INTERNAL_API_KEY" \
                -d "$payload")
            if [ "$response" = "200" ]; then
                return 0
            fi
            echo "Failed to update state to $state. HTTP status: $response"
            retry_count=$((retry_count+1))
            if [ $retry_count -lt $max_retries ]; then
                echo "Retrying state update in 5 seconds..."
                sleep 5
            fi
        done
        return 1
    fi
}

# Function to handle errors and exit
function handle_error() {
    local error_message=$1
    echo "Error: $error_message"
    update_error_details "$error_message"
    update_task_state "failed" "$error_message"
    exit 1
}

# Start execution - mark as in progress
update_task_state "in progress" || handle_error "Failed to update task state to in progress"

# Download and set up IaC engine
echo "Setting up $TF_ENGINE version ${TERRAFORM_VERSION}..."
TERRAFORM_DIR="/usr/local/terraform-versions"
TERRAFORM_BIN="${TERRAFORM_DIR}/${TF_ENGINE}_${TERRAFORM_VERSION}"

if [ ! -f "$TERRAFORM_BIN" ]; then
    echo "Downloading $TF_ENGINE version ${TERRAFORM_VERSION}..."
    TMP_DIR=$(mktemp -d)
    if [ $? -ne 0 ]; then
        handle_error "Failed to create temporary directory"
    fi

    if ! cd "$TMP_DIR"; then
        handle_error "Failed to change to temporary directory"
    fi

    if [[ "$TF_ENGINE" == "terraform" ]]; then
        if ! wget -q "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" -O engine.zip; then
            handle_error "Failed to download Terraform version ${TERRAFORM_VERSION}"
        fi
    else
        if ! wget -q "https://github.com/opentofu/opentofu/releases/download/v${TERRAFORM_VERSION}/tofu_${TERRAFORM_VERSION}_linux_amd64.zip" -O engine.zip; then
            handle_error "Failed to download OpenTofu version ${TERRAFORM_VERSION}"
        fi
    fi

    if ! unzip -q engine.zip; then
        handle_error "Failed to unzip IaC engine package"
    fi

    if ! mkdir -p "$TERRAFORM_DIR"; then
        handle_error "Failed to create IaC engine directory"
    fi

    # Find the extracted binary (tofu or terraform depending on engine)
    local_bin=$(ls tofu terraform 2>/dev/null | head -1)
    if [[ -z "$local_bin" ]]; then
        handle_error "Could not find extracted binary"
    fi

    if ! mv "$local_bin" "$TERRAFORM_BIN"; then
        handle_error "Failed to move IaC engine binary to destination"
    fi

    rm -f engine.zip
    cd - > /dev/null || handle_error "Failed to return to previous directory"
    rm -rf "$TMP_DIR"
fi

if ! ln -sf "$TERRAFORM_BIN" "/usr/local/bin/$TF_ENGINE"; then
    handle_error "Failed to create $TF_ENGINE symbolic link"
fi

# Verify installation
$TF_ENGINE version
engine_version_exit=$?
if [ $engine_version_exit -ne 0 ]; then
    handle_error "Failed to verify $TF_ENGINE installation (exit code: $engine_version_exit)"
fi

if [[ -n "$REPO_POLICY_PATH" || -n "$ORG_POLICY_REPO_URL" ]]; then
    echo "Setting up Conftest version ${CONFTEST_VERSION}..."
    CONFTEST_DIR="/usr/local/conftest-versions"
    CONFTEST_BIN="${CONFTEST_DIR}/conftest_${CONFTEST_VERSION}"

    if [ ! -f "$CONFTEST_BIN" ]; then
        echo "Downloading Conftest version ${CONFTEST_VERSION}..."
        TMP_DIR=$(mktemp -d)
        if [ $? -ne 0 ]; then
            handle_error "Failed to create temporary directory for Conftest"
        fi

        if ! cd "$TMP_DIR"; then
            handle_error "Failed to change to temporary directory for Conftest"
        fi

        # Handle "latest" version
        if [[ "$CONFTEST_VERSION" == "latest" ]]; then
            ACTUAL_VERSION=$(curl -s https://api.github.com/repos/open-policy-agent/conftest/releases/latest | jq -r '.tag_name' | sed 's/^v//')
            if [[ -z "$ACTUAL_VERSION" || "$ACTUAL_VERSION" == "null" ]]; then
                handle_error "Failed to get latest Conftest version"
            fi
            echo "Latest Conftest version is ${ACTUAL_VERSION}"
        else
            ACTUAL_VERSION="$CONFTEST_VERSION"
        fi

        if ! wget -q "https://github.com/open-policy-agent/conftest/releases/download/v${ACTUAL_VERSION}/conftest_${ACTUAL_VERSION}_Linux_x86_64.tar.gz"; then
            handle_error "Failed to download Conftest version ${ACTUAL_VERSION}"
        fi

        if ! tar -xzf "conftest_${ACTUAL_VERSION}_Linux_x86_64.tar.gz"; then
            handle_error "Failed to extract Conftest package"
        fi

        if ! mkdir -p "$CONFTEST_DIR"; then
            handle_error "Failed to create Conftest directory"
        fi

        if ! mv conftest "$CONFTEST_BIN"; then
            handle_error "Failed to move Conftest binary to destination"
        fi

        rm "conftest_${ACTUAL_VERSION}_Linux_x86_64.tar.gz"
        cd - > /dev/null || handle_error "Failed to return to previous directory"
        rm -rf "$TMP_DIR"
    fi

    if ! ln -sf "$CONFTEST_BIN" /usr/local/bin/conftest; then
        handle_error "Failed to create Conftest symbolic link"
    fi

    conftest --version
    conftest_version_exit=$?
    if [ $conftest_version_exit -ne 0 ]; then
        handle_error "Failed to verify Conftest installation (exit code: $conftest_version_exit)"
    fi
fi

# Clone repository
echo "Cloning repository..."
if [[ -n "$GITHUB_TOKEN" ]]; then
    git clone "https://${GITHUB_TOKEN}@${GITHUB_REPO#https://}" /workspace/repo
    clone_exit=$?
    if [ $clone_exit -ne 0 ]; then
        handle_error "Failed to clone repository using token (exit code: $clone_exit)"
    fi
else
    git clone "$GITHUB_REPO" /workspace/repo
    clone_exit=$?
    if [ $clone_exit -ne 0 ]; then
        handle_error "Failed to clone repository (exit code: $clone_exit)"
    fi
fi

if [[ -n "$GITHUB_BRANCH" ]]; then
    echo "Checking out branch: $GITHUB_BRANCH"
    if ! cd /workspace/repo; then
        handle_error "Failed to navigate to repository directory"
    fi
    
    git checkout "$GITHUB_BRANCH"
    checkout_exit=$?
    if [ $checkout_exit -ne 0 ]; then
        handle_error "Failed to checkout branch: $GITHUB_BRANCH (exit code: $checkout_exit)"
    fi
    
    echo "Successfully checked out branch: $GITHUB_BRANCH"
fi

if [[ -n "$ORG_POLICY_REPO_URL" ]]; then
    echo "Cloning organization policy repository..."
    if [[ -n "$ORG_POLICY_TOKEN" ]]; then
        git clone "https://${ORG_POLICY_TOKEN}@${ORG_POLICY_REPO_URL#https://}" /workspace/org-policies
        org_clone_exit=$?
        if [ $org_clone_exit -ne 0 ]; then
            handle_error "Failed to clone org policy repository using token (exit code: $org_clone_exit)"
        fi
    else
        git clone "$ORG_POLICY_REPO_URL" /workspace/org-policies
        org_clone_exit=$?
        if [ $org_clone_exit -ne 0 ]; then
            handle_error "Failed to clone org policy repository (exit code: $org_clone_exit)"
        fi
    fi

    if [[ -n "$ORG_POLICY_BRANCH" && "$ORG_POLICY_BRANCH" != "main" ]]; then
        echo "Checking out org policy branch: $ORG_POLICY_BRANCH"
        if ! cd /workspace/org-policies; then
            handle_error "Failed to navigate to org policy repository directory"
        fi
        
        git checkout "$ORG_POLICY_BRANCH"
        org_checkout_exit=$?
        if [ $org_checkout_exit -ne 0 ]; then
            handle_error "Failed to checkout org policy branch: $ORG_POLICY_BRANCH (exit code: $org_checkout_exit)"
        fi
        
        echo "Successfully checked out org policy branch: $ORG_POLICY_BRANCH"
        
        # Return to workspace for next steps
        cd /workspace
    fi
fi

# Change to IaC configuration directory
if ! cd "/workspace/repo${TF_CONFIG_PATH:+/$TF_CONFIG_PATH}"; then
    handle_error "Failed to navigate to IaC configuration directory: ${TF_CONFIG_PATH}"
fi

# Create backend.tf based on configured backend type
echo "Creating backend.tf configuration (type: ${TF_BACKEND_TYPE})..."
case "$TF_BACKEND_TYPE" in
    "s3")
        if [[ -z "$TF_BACKEND_BUCKET" || -z "$TF_BACKEND_KEY" ]]; then
            handle_error "S3 backend requires TF_BACKEND_BUCKET and TF_BACKEND_KEY"
        fi
        cat > backend.tf << EOF
terraform {
  backend "s3" {
    bucket         = "${TF_BACKEND_BUCKET}"
    key            = "${TF_BACKEND_KEY}"
    region         = "${AWS_REGION}"
    dynamodb_table = "${TF_STATE_LOCK_TABLE}"
  }
}
EOF
        ;;
    "kubernetes")
        cat > backend.tf << EOF
terraform {
  backend "kubernetes" {
    secret_suffix    = "${TF_BACKEND_KEY:-${PROJECT_NAME}-${WORKSPACE_NAME}}"
    namespace        = "${TF_BACKEND_NAMESPACE:-qubiva}"
    in_cluster_config = true
  }
}
EOF
        ;;
    "local")
        local state_dir="${TF_STATE_PATH:-/app/data/tfstate/${PROJECT_NAME}/${WORKSPACE_NAME}}"
        mkdir -p "$state_dir"
        cat > backend.tf << EOF
terraform {
  backend "local" {
    path = "${state_dir}/terraform.tfstate"
  }
}
EOF
        ;;
    "gcs")
        if [[ -z "$TF_BACKEND_BUCKET" || -z "$TF_BACKEND_KEY" ]]; then
            handle_error "GCS backend requires TF_BACKEND_BUCKET and TF_BACKEND_KEY"
        fi
        cat > backend.tf << EOF
terraform {
  backend "gcs" {
    bucket = "${TF_BACKEND_BUCKET}"
    prefix = "${TF_BACKEND_KEY}"
  }
}
EOF
        ;;
    "azurerm")
        cat > backend.tf << EOF
terraform {
  backend "azurerm" {
    resource_group_name  = "${TF_BACKEND_RESOURCE_GROUP}"
    storage_account_name = "${TF_BACKEND_STORAGE_ACCOUNT}"
    container_name       = "${TF_BACKEND_CONTAINER}"
    key                  = "${TF_BACKEND_KEY}"
  }
}
EOF
        ;;
    *)
        handle_error "Unsupported backend type: $TF_BACKEND_TYPE. Supported: s3, kubernetes, local, gcs, azurerm"
        ;;
esac

if [ $? -ne 0 ]; then
    handle_error "Failed to create backend.tf configuration"
fi

# Phase selection: comma-separated list of phases to execute.
# Defaults to validate,plan,apply if not specified.
TF_PHASES="${TF_PHASES:-validate,plan,apply}"
echo "Executing phases: $TF_PHASES"

# Helper: check if a phase is selected
phase_enabled() { [[ ",$TF_PHASES," == *",$1,"* ]]; }

# Initialize IaC engine (always required)
echo "Initializing $TF_ENGINE..."
$TF_ENGINE init
init_exit=$?
if [ $init_exit -ne 0 ]; then
    handle_error "$TF_ENGINE initialization failed (exit code: $init_exit)"
fi

# Validate
if phase_enabled "validate"; then
    echo "Validating $TF_ENGINE configuration..."
    $TF_ENGINE validate
    validate_exit=$?
    if [ $validate_exit -ne 0 ]; then
        handle_error "$TF_ENGINE validation failed (exit code: $validate_exit)"
    fi
fi

# Refresh (update state to match real infrastructure)
if phase_enabled "refresh"; then
    echo "Refreshing $TF_ENGINE state..."
    $TF_ENGINE apply -refresh-only --auto-approve
    refresh_exit=$?
    if [ $refresh_exit -ne 0 ]; then
        handle_error "$TF_ENGINE refresh failed (exit code: $refresh_exit)"
    fi
fi

# Plan (required for apply and destroy too)
if phase_enabled "plan" || phase_enabled "apply" || phase_enabled "destroy"; then
    echo "Generating $TF_ENGINE plan..."
    if phase_enabled "destroy"; then
        $TF_ENGINE plan -destroy -out=tfplan
    else
        $TF_ENGINE plan -out=tfplan
    fi
    plan_exit=$?
    if [ $plan_exit -ne 0 ]; then
        handle_error "$TF_ENGINE plan failed (exit code: $plan_exit)"
    fi

    # Run policy governance checks if configured (only when plan ran)
    if [[ -n "$REPO_POLICY_PATH" || -n "$ORG_POLICY_REPO_URL" ]]; then
        echo "Running policy governance checks..."

        POLICY_DIRS=()

        if [[ -n "$ORG_POLICY_REPO_URL" ]]; then
            ORG_POLICY_FULL_PATH="/workspace/org-policies${ORG_POLICY_PATH:+/$ORG_POLICY_PATH}"
            if [[ -d "$ORG_POLICY_FULL_PATH" ]]; then
                POLICY_DIRS+=("$ORG_POLICY_FULL_PATH")
                echo "Added org-level policies from: $ORG_POLICY_FULL_PATH"
            else
                echo "Warning: Org policy path not found: $ORG_POLICY_FULL_PATH"
            fi
        fi

        if [[ -n "$REPO_POLICY_PATH" ]]; then
            if [[ "$REPO_POLICY_PATH" == /* ]]; then
                REPO_POLICY_FULL_PATH="/workspace/repo${REPO_POLICY_PATH}"
            else
                REPO_POLICY_FULL_PATH="/workspace/repo${TF_CONFIG_PATH:+/$TF_CONFIG_PATH}/${REPO_POLICY_PATH}"
            fi

            if [[ -d "$REPO_POLICY_FULL_PATH" ]]; then
                POLICY_DIRS+=("$REPO_POLICY_FULL_PATH")
                echo "Added repo-level policies from: $REPO_POLICY_FULL_PATH"
            else
                echo "Warning: Repo policy path not found: $REPO_POLICY_FULL_PATH"
            fi
        fi

        if [[ ${#POLICY_DIRS[@]} -gt 0 ]]; then
            echo "Running Conftest with ${#POLICY_DIRS[@]} policy directory(ies)..."

            $TF_ENGINE show -json tfplan > tfplan.json
            show_exit=$?
            if [ $show_exit -ne 0 ]; then
                handle_error "Failed to convert plan to JSON (exit code: $show_exit)"
            fi

            CONFTEST_CMD="conftest test tfplan.json"
            for policy_dir in "${POLICY_DIRS[@]}"; do
                CONFTEST_CMD+=" --policy $policy_dir"
            done

            echo "Running: $CONFTEST_CMD"

            conftest_output=$(eval $CONFTEST_CMD 2>&1)
            conftest_exit=$?

            echo "$conftest_output"

            if [ $conftest_exit -ne 0 ]; then
                if echo "$conftest_output" | grep -q "no policies found"; then
                    echo "Warning: No valid policy files found in policy directories - skipping policy checks"
                else
                    handle_error "Policy governance checks failed - plan violates policies (exit code: $conftest_exit)"
                fi
            else
                echo "Policy governance checks passed successfully!"
            fi
        else
            echo "Warning: No valid policy directories found, skipping policy checks"
        fi
    fi
fi

# Apply
if phase_enabled "apply" && ! phase_enabled "destroy"; then
    echo "Applying $TF_ENGINE configuration..."
    $TF_ENGINE apply --auto-approve tfplan
    apply_exit=$?
    if [ $apply_exit -ne 0 ]; then
        handle_error "$TF_ENGINE apply failed (exit code: $apply_exit)"
    fi
fi

# Destroy
if phase_enabled "destroy"; then
    echo "Destroying $TF_ENGINE resources..."
    $TF_ENGINE apply --auto-approve tfplan
    destroy_exit=$?
    if [ $destroy_exit -ne 0 ]; then
        handle_error "$TF_ENGINE destroy failed (exit code: $destroy_exit)"
    fi
fi

# Success - mark as completed
update_task_state "completed" || handle_error "Failed to update task state to completed"
echo "Task completed successfully."
