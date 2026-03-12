#!/bin/bash

set -o pipefail  # Make pipes propagate errors

# --- Pool mode: pre-install binaries/plugins and wait for trigger ------------
if [[ "$POOL_MODE" == "true" ]]; then
    echo "=== POOL MODE: Preparing discovery runner pod ==="

    export HOME="/home/runner"
    export STEAMPIPE_INSTALL_DIR="/home/runner"
    export STEAMPIPE_HOME="/home/runner/.steampipe"
    export PATH="/home/runner/bin:$PATH"
    export STEAMPIPE_UPDATE_CHECK=false
    export STEAMPIPE_TELEMETRY=none
    export POWERPIPE_UPDATE_CHECK=false
    export POWERPIPE_TELEMETRY=none

    mkdir -p "$HOME/bin" "$HOME/output" "$STEAMPIPE_HOME/config"

    # Install query engine binary
    SP_VER="${QUERY_ENGINE_VERSION:-latest}"
    if [[ ! -x "$HOME/bin/sp" ]]; then
        echo "Installing query engine ($SP_VER)..."
        cd /tmp
        if [[ "$SP_VER" == "latest" ]]; then
            curl -fsSL "https://github.com/turbot/steampipe/releases/latest/download/steampipe_linux_amd64.tar.gz" -o steampipe.tar.gz
        else
            curl -fsSL "https://github.com/turbot/steampipe/releases/download/${SP_VER}/steampipe_linux_amd64.tar.gz" -o steampipe.tar.gz
        fi
        if [[ $? -eq 0 ]]; then
            tar -xzf steampipe.tar.gz && mv steampipe "$HOME/bin/sp" && chmod +x "$HOME/bin/sp"
            echo "Query engine installed: $(sp --version 2>/dev/null || echo 'ok')"
        else
            echo "Warning: Failed to download query engine"
        fi
        rm -f steampipe.tar.gz
    else
        echo "Query engine binary already present"
    fi

    # Pre-install all cloud plugins (aws, gcp, azure, azuread)
    echo "Pre-installing cloud plugins..."
    for plugin in aws gcp azure; do
        sp plugin install "$plugin" --progress 2>/dev/null || echo "Warning: Failed to install $plugin plugin"
    done
    sp plugin install azuread --progress 2>/dev/null || echo "Warning: Failed to install azuread plugin"

    # Remove default .spc files (will be created per-job with actual credentials)
    rm -f "$STEAMPIPE_HOME/config/aws.spc" "$STEAMPIPE_HOME/config/gcp.spc" "$STEAMPIPE_HOME/config/azure.spc" 2>/dev/null

    # Install compliance engine binary
    PP_VER="${COMPLIANCE_ENGINE_VERSION:-latest}"
    if [[ ! -x "$HOME/bin/pp" ]]; then
        echo "Installing compliance engine ($PP_VER)..."
        if [[ "$PP_VER" == "latest" ]]; then
            curl -fsSL https://raw.githubusercontent.com/vijayvat/powerpipe/main/scripts/install.sh | sh 2>/dev/null
        else
            curl -fsSL https://raw.githubusercontent.com/vijayvat/powerpipe/main/scripts/install.sh | sh -s "$PP_VER" 2>/dev/null
        fi
        find /tmp -name "powerpipe" -type f -exec cp {} "$HOME/bin/pp" \; 2>/dev/null
        chmod +x "$HOME/bin/pp" 2>/dev/null
        echo "Compliance engine installed: $(pp --version 2>/dev/null || echo 'ok')"
    else
        echo "Compliance engine binary already present"
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

    echo "=== POOL MODE: Starting execution ==="
fi

# =============================================================================
# Normal execution starts here (both pool and non-pool modes)
# =============================================================================

# Read environment variables with safe defaults
QUERY_ENGINE_VERSION="${QUERY_ENGINE_VERSION:-latest}"
COMPLIANCE_ENGINE_VERSION="${COMPLIANCE_ENGINE_VERSION:-latest}"
PLUGIN_VERSION="${PLUGIN_VERSION:-latest}"
CLOUD_PLATFORM="$(echo "${CLOUD_PLATFORM}" | tr '[:upper:]' '[:lower:]')"
RUN_TYPE="${RUN_TYPE}"
PROJECT_NAME="${PROJECT_NAME}"
REQUEST_ID="${REQUEST_ID:?REQUEST_ID must be set}"
QUBIVA_API_ENDPOINT="${QUBIVA_API_ENDPOINT}"
USE_AUTO_BENCHMARK="${USE_AUTO_BENCHMARK:-false}"
CUSTOM_BENCHMARK_PATH="${CUSTOM_BENCHMARK_PATH}"
GITHUB_REPO_URL="${GITHUB_REPO_URL}"
GITHUB_BRANCH="${GITHUB_BRANCH:-main}"
GITHUB_TOKEN="${GITHUB_TOKEN}"
CLOUD_QUERIES_PATH="${CLOUD_QUERIES_PATH}"
CLOUD_ACCOUNT_ID="${CLOUD_ACCOUNT_ID}"
MOD_TYPE="${MOD_TYPE}"
BENCHMARK_ID="${BENCHMARK_ID}"
MOD_GITHUB_URL="${MOD_GITHUB_URL}"
MOD_NAME="${MOD_NAME}"
# Note: DISCOVERY_QUERY and COST_QUERY are fetched via HTTP API in run_discovery_mode()
# to avoid environment variable size limits

# Storage configuration (PersistentVolume mounted path)
ARTIFACTS_STORAGE_PATH="${ARTIFACTS_STORAGE_PATH:?ARTIFACTS_STORAGE_PATH must be set}"
ARTIFACTS_PREFIX="${ARTIFACTS_PREFIX:-runs}"
INTERNAL_API_KEY="${INTERNAL_API_KEY:-}"
OUTPUT_DIR="/home/runner/output"

# Set necessary environment variables
export HOME="/home/runner"
export STEAMPIPE_INSTALL_DIR="/home/runner"
export STEAMPIPE_HOME="/home/runner/.steampipe"
export PATH="/home/runner/bin:$PATH"
export STEAMPIPE_UPDATE_CHECK=false
export STEAMPIPE_TELEMETRY=none
export POWERPIPE_UPDATE_CHECK=false
export POWERPIPE_TELEMETRY=none

update_error_details() {
    local error_message="$1"
    local payload=$(jq -n --arg msg "$error_message" '{error_message: $msg}')

    if [[ -n "$QUBIVA_API_ENDPOINT" ]] && [[ -n "$REQUEST_ID" ]]; then
        local retry_count=0
        local max_retries=12
        
        while [[ $retry_count -lt $max_retries ]]; do
            local response
            response=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$QUBIVA_API_ENDPOINT/api/internal/v1/update_request_error_details/$REQUEST_ID" \
                -H "Content-Type: application/json" \
                -H "X-Internal-Api-Key: $INTERNAL_API_KEY" \
                -d "$payload")
            
            if [[ "$response" == "200" ]]; then
                return 0
            fi
            
            echo "Failed to update error details. HTTP status: $response"
            retry_count=$((retry_count + 1))
            
            if [[ $retry_count -lt $max_retries ]]; then
                echo "Retrying error details update in 5 seconds..."
                sleep 5
            fi
        done
        return 1
    fi
}

update_task_state() {
    local state="$1"
    local error_message="$2"
    local payload

    if [[ -n "$error_message" ]]; then
        payload=$(jq -n --arg state "$state" --arg error "$error_message" '{state: $state, error: $error}')
    else
        payload=$(jq -n --arg state "$state" '{state: $state}')
    fi

    if [[ -n "$QUBIVA_API_ENDPOINT" ]] && [[ -n "$REQUEST_ID" ]]; then
        local retry_count=0
        local max_retries=12
        
        while [[ $retry_count -lt $max_retries ]]; do
            local response
            response=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$QUBIVA_API_ENDPOINT/api/internal/v1/update_request_state/$REQUEST_ID" \
                -H "Content-Type: application/json" \
                -H "X-Internal-Api-Key: $INTERNAL_API_KEY" \
                -d "$payload")
            
            if [[ "$response" == "200" ]]; then
                return 0
            fi
            
            echo "Failed to update state to $state. HTTP status: $response"
            retry_count=$((retry_count + 1))
            
            if [[ $retry_count -lt $max_retries ]]; then
                echo "Retrying state update in 5 seconds..."
                sleep 5
            fi
        done
        return 1
    fi
}

fetch_discovery_config() {
    # Fetch discovery configuration from the API
    # to avoid passing large queries via environment variables

    if [[ -z "$QUBIVA_API_ENDPOINT" ]] || [[ -z "$REQUEST_ID" ]]; then
        handle_error "QUBIVA_API_ENDPOINT and REQUEST_ID are required to fetch discovery config"
    fi

    local retry_count=0
    local max_retries=5

    while [[ $retry_count -lt $max_retries ]]; do
        echo "Fetching discovery config from API (attempt $((retry_count + 1))/$max_retries)..."

        local response
        response=$(curl -s -w "\n%{http_code}" -X GET \
            "$QUBIVA_API_ENDPOINT/api/internal/v1/requests/$REQUEST_ID/discovery_config" \
            -H "Content-Type: application/json" \
            -H "X-Internal-Api-Key: $INTERNAL_API_KEY")

        local http_code
        http_code=$(echo "$response" | tail -n1)
        local body
        body=$(echo "$response" | sed '$d')

        if [[ "$http_code" == "200" ]]; then
            # Parse the response to extract discovery_query and cost_query
            DISCOVERY_QUERY=$(echo "$body" | jq -r '.discovery_config.discovery_query // empty')
            COST_QUERY=$(echo "$body" | jq -r '.discovery_config.cost_query // empty')

            if [[ -n "$DISCOVERY_QUERY" ]] && [[ -n "$COST_QUERY" ]]; then
                echo "Successfully fetched discovery configuration"
                return 0
            else
                echo "Failed to parse discovery config from response"
            fi
        else
            echo "Failed to fetch discovery config. HTTP status: $http_code"
        fi

        retry_count=$((retry_count + 1))

        if [[ $retry_count -lt $max_retries ]]; then
            echo "Retrying in 5 seconds..."
            sleep 5
        fi
    done

    handle_error "Failed to fetch discovery config after $max_retries attempts"
}

save_to_storage() {
    local file_path="$1"
    local file_name
    file_name=$(basename "$file_path")
    local dest_dir="${ARTIFACTS_STORAGE_PATH}/${ARTIFACTS_PREFIX}/${REQUEST_ID}"
    local dest_path="${dest_dir}/${file_name}"

    if [[ ! -f "$file_path" ]]; then
        handle_error "Output file not found: $file_path. Query/Benchmark might have failed to generate output."
        return 1
    fi

    if [[ ! -s "$file_path" ]]; then
        handle_error "Output file is empty: $file_path. Query/Benchmark might have failed to generate results."
        return 1
    fi

    echo "Saving results to $dest_path"
    mkdir -p "$dest_dir"
    cp "$file_path" "$dest_path" 2> /tmp/save_error
    local save_exit=$?
    if [[ $save_exit -ne 0 ]]; then
        local error_msg
        error_msg=$(cat /tmp/save_error)
        handle_error "Failed to publish results: $error_msg"
        return 1
    fi

    echo "Successfully Published $file_name"
    return 0
}

handle_error() {
    local error_message="$1"
    echo "Error: $error_message"
    update_error_details "$error_message"
    update_task_state "failed" "$error_message"
    exit 1
}

setup_query_engine() {
    mkdir -p "$HOME/bin"

    # Skip download if binary already present (e.g., from pool mode pre-install)
    if [[ -x "$HOME/bin/sp" ]]; then
        echo "Query engine binary already installed, skipping download"
    else
        echo "Installing query engine..."
        cd /tmp

        if [[ "$QUERY_ENGINE_VERSION" == "latest" ]]; then
            curl -fsSL "https://github.com/turbot/steampipe/releases/latest/download/steampipe_linux_amd64.tar.gz" -o steampipe.tar.gz 2> /tmp/steampipe_error
        else
            curl -fsSL "https://github.com/turbot/steampipe/releases/download/${QUERY_ENGINE_VERSION}/steampipe_linux_amd64.tar.gz" -o steampipe.tar.gz 2> /tmp/steampipe_error
        fi

        local download_exit=$?
        if [[ $download_exit -ne 0 ]]; then
            local error_msg
            error_msg=$(cat /tmp/steampipe_error)
            handle_error "Failed to download query engine (exit code: $download_exit, error: $error_msg)"
        fi

        tar -xzf steampipe.tar.gz 2> /tmp/steampipe_error
        local extract_exit=$?
        if [[ $extract_exit -ne 0 ]]; then
            local error_msg
            error_msg=$(cat /tmp/steampipe_error)
            handle_error "Failed to extract query engine (exit code: $extract_exit, error: $error_msg)"
        fi

        mv steampipe "$HOME/bin/sp"
        chmod +x "$HOME/bin/sp"
        rm -f steampipe.tar.gz
    fi

    # Create plugin configuration
    if [[ "$CLOUD_PLATFORM" == "aws" ]]; then
        echo "Creating AWS plugin configuration..."
        if ! mkdir -p "$STEAMPIPE_HOME/config"; then
            handle_error "Failed to create query engine config directory"
        fi
        
        cat > "$STEAMPIPE_HOME/config/aws.spc" << EOF
connection "aws" {
    plugin = "aws"
    regions = ["$AWS_REGION"]
}
EOF
        
        if [[ $? -ne 0 ]]; then
            handle_error "Failed to create AWS plugin configuration file"
        fi
    elif [[ "$CLOUD_PLATFORM" == "azure" ]]; then
        echo "Creating Azure plugin configuration..."
        if ! mkdir -p "$STEAMPIPE_HOME/config"; then
            handle_error "Failed to create query engine config directory"
        fi
        cat > "$STEAMPIPE_HOME/config/azure.spc" << EOF
connection "azure" {
    plugin = "azure"
}
EOF
        export AZURE_SUBSCRIPTION_ID="$CLOUD_ACCOUNT_ID"
        export AZURE_CLIENT_ID="$ARM_CLIENT_ID"
        export AZURE_CLIENT_SECRET="$ARM_CLIENT_SECRET"
        export AZURE_TENANT_ID="$ARM_TENANT_ID"

        if [[ $? -ne 0 ]]; then
            handle_error "Failed to create Azure plugin configuration file"
        fi
    elif [[ "$CLOUD_PLATFORM" == "gcp" ]]; then
        echo "Creating GCP plugin configuration..."
        if ! mkdir -p "$STEAMPIPE_HOME/config"; then
            handle_error "Failed to create query engine config directory"
        fi
        
        cat > ~/.steampipe/config/gcp.spc << EOF
connection "gcp" {
    plugin = "gcp"
    project = "$CLOUD_ACCOUNT_ID"
    credentials = "$GOOGLE_CREDENTIALS_FILE"
}
EOF
        
        if [[ $? -ne 0 ]]; then
            handle_error "Failed to create GCP plugin configuration file"
        fi
    fi

    # Install plugin
    echo "Installing and updating query engine plugin for $CLOUD_PLATFORM..."
    if [[ "$PLUGIN_VERSION" == "latest" ]]; then
        sp plugin install "$CLOUD_PLATFORM" --progress &> /tmp/plugin_error
        local install_exit=$?
        if [[ $install_exit -ne 0 ]]; then
            local error_msg
            error_msg=$(cat /tmp/plugin_error)
            handle_error "Failed to install $CLOUD_PLATFORM plugin (exit code: $install_exit, error: $error_msg)"
        fi
        sp plugin update "$CLOUD_PLATFORM" 2> /tmp/plugin_error
        local update_exit=$?
        if [[ $update_exit -ne 0 ]]; then
            local error_msg
            error_msg=$(cat /tmp/plugin_error)
            handle_error "Failed to update $CLOUD_PLATFORM plugin (exit code: $update_exit, error: $error_msg)"
        fi

        # Install azuread if CLOUD_PLATFORM is azure
        if [[ "$CLOUD_PLATFORM" == "azure" ]]; then
            sp plugin install azuread --progress &> /tmp/plugin_error
            local azuread_install_exit=$?
            if [[ $azuread_install_exit -ne 0 ]]; then
                local error_msg
                error_msg=$(cat /tmp/plugin_error)
                handle_error "Failed to install azuread plugin (exit code: $azuread_install_exit, error: $error_msg)"
            fi
        fi
    else
        sp plugin install "$CLOUD_PLATFORM@$PLUGIN_VERSION" --progress &> /tmp/plugin_error
        local install_exit=$?
        if [[ $install_exit -ne 0 ]]; then
            local error_msg
            error_msg=$(cat /tmp/plugin_error)
            handle_error "Failed to install $CLOUD_PLATFORM plugin version $PLUGIN_VERSION (exit code: $install_exit, error: $error_msg)"
        fi

        # Install azuread if CLOUD_PLATFORM is azure
        if [[ "$CLOUD_PLATFORM" == "azure" ]]; then
            sp plugin install azuread --progress &> /tmp/plugin_error
            local azuread_install_exit=$?
            if [[ $azuread_install_exit -ne 0 ]]; then
                local error_msg
                error_msg=$(cat /tmp/plugin_error)
                handle_error "Failed to install azuread plugin (exit code: $azuread_install_exit, error: $error_msg)"
            fi
        fi
    fi
}

start_query_engine_service() {
    echo "Starting query engine service..."

    local max_start_attempts=2
    local start_attempt=1

    while [[ $start_attempt -le $max_start_attempts ]]; do
        sp service start 2> /tmp/service_error
        local service_start_exit=$?

        if [[ $service_start_exit -eq 0 ]]; then
            # Service start command succeeded, now wait for it to be ready
            echo "Waiting for query engine service to be ready..."
            local max_attempts=12
            local attempt=1

            while [[ $attempt -le $max_attempts ]]; do
                if sp service status | grep -qi "running"; then
                    echo "Query engine service is ready"
                    return 0
                fi

                if [[ $attempt -eq $max_attempts ]]; then
                    if [[ $start_attempt -lt $max_start_attempts ]]; then
                        echo "Query engine service failed to become ready. Retrying service start..."
                        break
                    else
                        handle_error "Query engine service failed to start after 60 seconds (after $max_start_attempts attempts)"
                    fi
                fi

                echo "Waiting for query engine service (attempt $attempt of $max_attempts)..."
                sleep 5
                attempt=$((attempt + 1))
            done
        else
            # Service start command itself failed
            if [[ $start_attempt -lt $max_start_attempts ]]; then
                local error_msg
                error_msg=$(cat /tmp/service_error)
                echo "Failed to start query engine service (attempt $start_attempt of $max_start_attempts, exit code: $service_start_exit, error: $error_msg)"
                echo "Retrying in 10 seconds..."
                sleep 10
            else
                local error_msg
                error_msg=$(cat /tmp/service_error)
                handle_error "Failed to start query engine service after $max_start_attempts attempts (exit code: $service_start_exit, error: $error_msg)"
            fi
        fi

        start_attempt=$((start_attempt + 1))
    done
}

setup_repository() {
    if [[ -n "$GITHUB_REPO_URL" ]]; then
        echo "Cloning GitHub repository: $GITHUB_REPO_URL"
        if ! mkdir -p /workspace/repo; then
            handle_error "Failed to create workspace directory"
        fi
        
        if [[ -n "$GITHUB_TOKEN" ]]; then
            git clone --branch "$GITHUB_BRANCH" "https://${GITHUB_TOKEN}@${GITHUB_REPO_URL#https://}" /workspace/repo 2> /tmp/git_error
            local clone_exit=$?
            if [[ $clone_exit -ne 0 ]]; then
                local error_msg
                error_msg=$(cat /tmp/git_error)
                handle_error "Failed to clone repository with token (exit code: $clone_exit, error: $error_msg)"
            fi
        else
            git clone --branch "$GITHUB_BRANCH" "$GITHUB_REPO_URL" /workspace/repo 2> /tmp/git_error
            local clone_exit=$?
            if [[ $clone_exit -ne 0 ]]; then
                local error_msg
                error_msg=$(cat /tmp/git_error)
                handle_error "Failed to clone repository (exit code: $clone_exit, error: $error_msg)"
            fi
        fi
    fi
}

run_query_mode() {
    if [[ -z "$CLOUD_QUERIES_PATH" ]]; then
        handle_error "CLOUD_QUERIES_PATH is required for query type"
    fi

    if ! cd "/workspace/repo/$CLOUD_QUERIES_PATH"; then
        handle_error "Failed to navigate to queries path: $CLOUD_QUERIES_PATH"
    fi

    echo "Running all SQL queries in the directory..."

    for query_file in *.sql; do
        if [[ -f "$query_file" ]]; then
            echo "Executing query: $query_file"
            local timestamp
            timestamp=$(date +%H%M%S)
            local output_file="${OUTPUT_DIR}/${query_file%.sql}_${timestamp}.csv"
            sp query "$(cat $query_file)" --output csv > "$output_file" 2> /tmp/query_error
            local query_exit=$?
            
            if [[ -f "$output_file" ]]; then
                save_to_storage "$output_file"
            fi

            if [[ $query_exit -ne 0 ]]; then
                local error_msg
                error_msg=$(cat /tmp/query_error)
                handle_error "Query execution failed for file: $query_file (exit code: $query_exit, error: $error_msg)"
            fi
        fi
    done
}

setup_compliance_engine() {
    # Skip download if binary already present (e.g., from pool mode pre-install)
    if [[ -x "$HOME/bin/pp" ]]; then
        echo "Compliance engine binary already installed, skipping download"
        return 0
    fi

    echo "Installing compliance engine..."

    if [[ "$COMPLIANCE_ENGINE_VERSION" == "latest" ]]; then
        curl -fsSL https://raw.githubusercontent.com/vijayvat/powerpipe/main/scripts/install.sh \
        | sh 2> /tmp/powerpipe_error
    else
        curl -fsSL https://raw.githubusercontent.com/vijayvat/powerpipe/main/scripts/install.sh \
        | sh -s "$COMPLIANCE_ENGINE_VERSION" 2> /tmp/powerpipe_error
    fi

    # Find the downloaded binary and copy it to our location
    if find /tmp -name "powerpipe" -type f -exec cp {} "$HOME/bin/pp" \; 2>/dev/null; then
        chmod +x "$HOME/bin/pp"
        echo "Compliance engine installed successfully to $HOME/bin"
    else
        handle_error "Failed to find downloaded compliance engine binary"
    fi
}

run_auto_benchmark() {
    echo "Setting up auto benchmark..."
    local timestamp
    timestamp=$(date +%H%M%S)
    local benchmark_output="${OUTPUT_DIR}/benchmark_${BENCHMARK_ID}_${timestamp}.csv"
    
    if ! mkdir -p dashboards; then
        handle_error "Failed to create dashboards directory"
    fi
    
    cd dashboards || handle_error "Failed to navigate to dashboards directory"
    
    pp mod init 2> /tmp/mod_error
    local init_exit=$?
    if [[ $init_exit -ne 0 ]]; then
        local error_msg
        error_msg=$(cat /tmp/mod_error)
        handle_error "Failed to initialize compliance mod (exit code: $init_exit, error: $error_msg)"
    fi

    # Install mod from provided GitHub URL
    echo "Installing mod from: $MOD_GITHUB_URL"
    pp mod install "$MOD_GITHUB_URL" 2> /tmp/mod_error
    local mod_install_exit=$?
    if [[ $mod_install_exit -ne 0 ]]; then
        local error_msg
        error_msg=$(cat /tmp/mod_error)
        handle_error "Failed to install mod from $MOD_GITHUB_URL (exit code: $mod_install_exit, error: $error_msg)"
    fi

    # Run the specific benchmark with JSON output
    local FULL_BENCHMARK_ID="${MOD_NAME}.benchmark.${BENCHMARK_ID}"
    local json_output="${benchmark_output%.csv}.json"

    echo "Running benchmark: $FULL_BENCHMARK_ID"
    pp benchmark run "$FULL_BENCHMARK_ID" --export "$json_output" --output json 2> /tmp/benchmark_error

    local benchmark_exit=$?

    # Upload JSON output
    if [[ -f "$json_output" ]]; then
        save_to_storage "$json_output"
    fi

    # Handle exit codes:
    # 0 = all checks passed - benchmark succeeded
    # 2 = found violations - benchmark failed (NORMAL)
    # 1 = may be violations OR an update notice on stderr - check if output was produced
    # other = benchmark execution error
    if [[ $benchmark_exit -eq 0 ]]; then
        echo "Benchmark Succeeded: All checks passed (exit code: 0)"
        if ! update_task_state "benchmark succeeded"; then
            handle_error "Failed to update task state to benchmark succeeded"
        fi
        exit 0
    elif [[ $benchmark_exit -eq 2 ]]; then
        echo "Benchmark Failed - found violations/issues (exit code: 2)"
        if ! update_task_state "benchmark failed"; then
            handle_error "Failed to update task state to benchmark failed"
        fi
        exit 0
    elif [[ $benchmark_exit -eq 1 ]] && [[ -f "$json_output" ]] && [[ -s "$json_output" ]]; then
        # Exit code 1 but output was produced - benchmark ran, treat as violations found
        echo "Benchmark completed with exit code 1 but output was produced - treating as benchmark failed"
        if ! update_task_state "benchmark failed"; then
            handle_error "Failed to update task state to benchmark failed"
        fi
        exit 0
    else
        local error_msg
        error_msg=$(cat /tmp/benchmark_error)
        handle_error "Execution Failed (exit code: $benchmark_exit, error: $error_msg)"
    fi
}

run_custom_benchmark() {
    if [[ -z "$CUSTOM_BENCHMARK_PATH" ]]; then
        handle_error "CUSTOM_BENCHMARK_PATH is required when USE_AUTO_BENCHMARK is false"
    fi

    if ! cd "/workspace/repo/$CUSTOM_BENCHMARK_PATH"; then
        handle_error "Failed to navigate to custom benchmark path: $CUSTOM_BENCHMARK_PATH"
    fi

    pp mod init 2> /tmp/mod_error
    local init_exit=$?
    if [[ $init_exit -ne 0 ]]; then
        local error_msg
        error_msg=$(cat /tmp/mod_error)
        handle_error "Failed to initialize compliance mod (exit code: $init_exit, error: $error_msg)"
    fi

    pp mod install . 2> /tmp/mod_error
    local mod_install_exit=$?
    if [[ $mod_install_exit -ne 0 ]]; then
        local error_msg
        error_msg=$(cat /tmp/mod_error)
        handle_error "Failed to install custom mod (exit code: $mod_install_exit, error: $error_msg)"
    fi

    local BENCHMARKS
    BENCHMARKS=$(pp benchmark list | awk '$1=="benchmark"{print $2}')
    if [[ -z "$BENCHMARKS" ]]; then
        handle_error "No benchmarks found in custom mod"
    fi

    while IFS= read -r benchmark; do
        if [[ -n "$benchmark" ]]; then
            # Create sanitized benchmark name for file
            local benchmark_name
            benchmark_name=$(echo "$benchmark" | tr ' /' '_')
            local timestamp
            timestamp=$(date +%H%M%S)
            local json_output="${OUTPUT_DIR}/benchmark_${benchmark_name}_${timestamp}.json"

            echo "Running benchmark: $benchmark"
            pp benchmark run "$benchmark" --export "$json_output" --output json 2> /tmp/benchmark_error

            local benchmark_exit=$?

            if [[ -f "$json_output" ]]; then
                save_to_storage "$json_output"
            fi

            # Handle exit codes same as auto benchmark
            if [[ $benchmark_exit -eq 0 ]]; then
                echo "Benchmark '$benchmark' Succeeded: All checks passed"
                if ! update_task_state "benchmark succeeded"; then
                    handle_error "Failed to update task state to benchmark succeeded"
                fi
                exit 0
            elif [[ $benchmark_exit -eq 2 ]]; then
                echo "Benchmark '$benchmark' Failed - found violations/issues"
                if ! update_task_state "benchmark failed"; then
                    handle_error "Failed to update task state to benchmark failed"
                fi
                exit 0
            elif [[ $benchmark_exit -eq 1 ]] && [[ -f "$json_output" ]] && [[ -s "$json_output" ]]; then
                echo "Benchmark '$benchmark' completed with exit code 1 but output was produced - treating as benchmark failed"
                if ! update_task_state "benchmark failed"; then
                    handle_error "Failed to update task state to benchmark failed"
                fi
                exit 0
            else
                local error_msg
                error_msg=$(cat /tmp/benchmark_error)
                handle_error "Benchmark '$benchmark' execution failed (exit code: $benchmark_exit, error: $error_msg)"
            fi
        fi
    done <<< "$BENCHMARKS"
}

run_benchmark_mode() {
    setup_compliance_engine
    
    if [[ "$USE_AUTO_BENCHMARK" == "true" ]]; then
        run_auto_benchmark
    else
        run_custom_benchmark
    fi
}

run_discovery_mode() {
    echo "Running discovery mode..."

    # Fetch discovery configuration from API instead of environment variables
    # to avoid environment variable size limits
    fetch_discovery_config

    local timestamp
    timestamp=$(date +%Y%m%d_%H%M%S)
    
    # Run resource discovery query
    echo "Running resource discovery query..."
    local resources_file="${OUTPUT_DIR}/resources_${timestamp}.json"
    sp query "$DISCOVERY_QUERY" --output json > "$resources_file" 2> /tmp/discovery_error
    local discovery_exit=$?
    
    if [[ $discovery_exit -ne 0 ]]; then
        local error_msg
        error_msg=$(cat /tmp/discovery_error)
        handle_error "Resource discovery query failed (exit code: $discovery_exit, error: $error_msg)"
    fi
    
    # Run cost discovery query
    echo "Running cost discovery query..."
    local costs_file="${OUTPUT_DIR}/costs_${timestamp}.json"
    sp query "$COST_QUERY" --output json > "$costs_file" 2> /tmp/cost_error
    local cost_exit=$?
    
    if [[ $cost_exit -ne 0 ]]; then
        local error_msg
        error_msg=$(cat /tmp/cost_error)
        handle_error "Cost discovery query failed (exit code: $cost_exit, error: $error_msg)"
    fi
    
    # Combine results into single discovery file
    echo "Combining discovery results..."
    local discovery_file="${OUTPUT_DIR}/discovery_${timestamp}.json"
    jq -s '{discovered_at: (now | todate), resources: .[0], costs: .[1]}' \
        "$resources_file" "$costs_file" > "$discovery_file" 2> /tmp/jq_error
    
    if [[ $? -ne 0 ]]; then
        local error_msg
        error_msg=$(cat /tmp/jq_error)
        handle_error "Failed to combine discovery results (error: $error_msg)"
    fi
    
    # Save combined discovery file to storage
    if [[ -f "$discovery_file" ]]; then
        save_to_storage "$discovery_file"
    else
        handle_error "Discovery file not found: $discovery_file"
    fi
    
    # Clean up intermediate files
    rm -f "$resources_file" "$costs_file"
    
    echo "Discovery completed successfully"
}

main() {
    # Create output directory if it doesn't exist
    mkdir -p "$OUTPUT_DIR"

    # Start execution - mark as in progress
    update_task_state "in progress" || handle_error "Failed to update task state to in progress"

    # Validate cloud platform
    if [[ "$CLOUD_PLATFORM" != "aws" ]] && [[ "$CLOUD_PLATFORM" != "gcp" ]] && [[ "$CLOUD_PLATFORM" != "azure" ]]; then
        handle_error "Invalid cloud platform: $CLOUD_PLATFORM"
    fi

    # Handle GCP credentials if applicable
    if [[ "$CLOUD_PLATFORM" == "gcp" ]]; then
        if [[ -n "$GOOGLE_APPLICATION_CREDENTIALS_B64" ]]; then
            echo "Setting up GCP credentials..."
            
            # Create temporary file for credentials
            mkdir -p /tmp
            GOOGLE_CREDENTIALS_FILE=$(mktemp /tmp/google_credentials_XXXXXX.json) || handle_error "Failed to create temporary credentials file"
            chmod 600 "$GOOGLE_CREDENTIALS_FILE" || handle_error "Failed to set permissions on credentials file"
            
            # Ensure cleanup on script exit
            trap 'rm -f "$GOOGLE_CREDENTIALS_FILE"' EXIT
            
            # Decode credentials
            echo "$GOOGLE_APPLICATION_CREDENTIALS_B64" | base64 -d > "$GOOGLE_CREDENTIALS_FILE" 2> /tmp/gcp_error
            if [[ $? -ne 0 ]]; then
                local error_msg
                error_msg=$(cat /tmp/gcp_error)
                handle_error "Failed to decode GCP credentials (error: $error_msg)"
            fi
            
            # Validate JSON and required fields
            if ! jq -e '.type and .project_id and .private_key' "$GOOGLE_CREDENTIALS_FILE" >/dev/null 2>&1; then
                handle_error "Invalid or incomplete GCP credentials JSON"
            fi
            
            export GOOGLE_APPLICATION_CREDENTIALS="$GOOGLE_CREDENTIALS_FILE"
            echo "GCP credentials configured successfully"

            # Activate service account first
            echo "Activating GCP service account..."
            gcloud auth activate-service-account --key-file="$GOOGLE_CREDENTIALS_FILE" --quiet 2> /tmp/gcp_error
            if [[ $? -ne 0 ]]; then
                local error_msg
                error_msg=$(cat /tmp/gcp_error)
                handle_error "Failed to activate service account (error: $error_msg)"
            fi

            # Set GCP project non-interactively if provided
            if [[ -n "$CLOUD_ACCOUNT_ID" ]]; then
                echo "Setting GCP project to: $CLOUD_ACCOUNT_ID"
                gcloud config set project "$CLOUD_ACCOUNT_ID" --quiet 2> /tmp/gcp_error
                if [[ $? -ne 0 ]]; then
                    local error_msg
                    error_msg=$(cat /tmp/gcp_error)
                    handle_error "Failed to set GCP project (error: $error_msg)"
                fi
            else
                handle_error "CLOUD_ACCOUNT_ID is required but not set"
            fi
        else
            handle_error "GCP credentials are required but GOOGLE_APPLICATION_CREDENTIALS_B64 is not set"
        fi
    fi

    if [[ "$CLOUD_PLATFORM" == "azure" ]]; then
        # First set the subscription ID
        export ARM_SUBSCRIPTION_ID="$CLOUD_ACCOUNT_ID"
        
        # Validate Azure credentials
        if [[ -z "$ARM_CLIENT_ID" ]] || [[ -z "$ARM_CLIENT_SECRET" ]] || [[ -z "$ARM_TENANT_ID" ]]; then
            handle_error "Azure credentials are required but one or more of ARM_CLIENT_ID, ARM_CLIENT_SECRET, ARM_TENANT_ID is not set"
        fi
        
        if [[ -z "$CLOUD_ACCOUNT_ID" ]]; then
            handle_error "CLOUD_ACCOUNT_ID is required for Azure but not set"
        fi
        
        echo "Azure credentials configured successfully"
    fi

    # Setup query engine and repository
    setup_query_engine
    start_query_engine_service
    setup_repository

    # Execute based on RUN_TYPE
    case "$RUN_TYPE" in
        "query")
            run_query_mode
            ;;
        "benchmark")
            run_benchmark_mode
            ;;
        "discovery")
            run_discovery_mode
            ;;            
        *)
            handle_error "Unsupported run type: $RUN_TYPE. Must be 'query' or 'benchmark'"
            ;;
    esac

    # Success - mark as completed
    if ! update_task_state "completed"; then
        handle_error "Failed to update task state to completed"
    fi

    echo "Task completed successfully. Results saved to ${ARTIFACTS_STORAGE_PATH}/${ARTIFACTS_PREFIX}/${REQUEST_ID}/"
}

# Execute main function
main "$@"