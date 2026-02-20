$(function () {
    console.log("Initializing Cloud Query script");

    const projectName = Qubiva.url.projectName();
    const cloudPlatformType = Qubiva.url.cloudPlatform();
    const accountId = Qubiva.url.accountId();
    let availableBenchmarks = {};
    let discoveryConfigured = false;

    console.log(`Project Name: ${projectName}, Cloud Platform Type: ${cloudPlatformType}, Account ID: ${accountId}`);

    let currentPage = 1;


    // Function to fetch and display cloud account details
    function fetchCloudAccountDetails() {
        const apiUrl = `/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatformType}/${accountId}`;
        console.log('Fetching cloud account details from:', apiUrl);
        
        $.ajax({
            url: apiUrl,
            method: 'GET',
            success: function(response) {
                console.log('Success! Cloud account details:', response);
                if (response) {
                    $('#cloud-platform').text(response.cloud_platform || 'N/A');
                    $('#account-id').text(response.account_id || 'N/A');
                    
                    // Handle authentication type display
                    if (response.credential_reference) {
                        // Using a credential reference - create a clickable link
                        const formattedType = formatAuthType(response.credential_type);
                        const credentialLink = `/dashboard/projects/${projectName}/credentials/${response.credential_reference}/edit`;
                        
                        $('#auth-type').html(`
                            ${formattedType} 
                            (Linked Credential - <a href="${credentialLink}" class="text-primary">${response.credential_reference}</a>)
                        `);
                    } else if (response.auth_secrets?.type) {
                        // Using direct auth_secrets - no link needed
                        $('#auth-type').text(formatAuthType(response.auth_secrets.type));
                    } else {
                        $('#auth-type').text('N/A');
                    }
                } else {
                    console.error('Empty response received');
                    setErrorState();
                }
            },
            error: function(xhr, status, error) {
                console.error('API call failed:', {
                    status: status,
                    error: error,
                    response: xhr.responseText
                });
                setErrorState();
            }
        });
    }

    function fetchCredentialType(credentialName) {
        const credentialApiUrl = `/api/v1/projects/${projectName}/credentials/search`;
        
        $.ajax({
            url: credentialApiUrl,
            method: 'GET',
            data: { query: credentialName },
            success: function(response) {
                console.log('Credential search response:', response);
                
                // Find the exact credential match
                const credential = response.results.find(cred => cred.credential_name === credentialName);
                
                if (credential) {
                    const formattedType = formatAuthType(credential.credential_type);
                    $('#auth-type').text(`${formattedType} (Linked External Credential - ${credentialName})`);
                } else {
                    $('#auth-type').text(`Linked Credential: ${credentialName} (Type Unknown)`);
                }
            },
            error: function(xhr, status, error) {
                console.error('Failed to fetch credential type:', error);
                $('#auth-type').text(`Linked Credential: ${credentialName} (Error)`);
            }
        });
    }

    function formatAuthType(authType) {
        // Convert technical auth type names to user-friendly display names
        const typeMap = {
            'external_certificate_authority': 'External Certificate Authority',
            'key_pair': 'Access Key Pair',
            'azure_service_principal': 'Service Principal',
            'gcp_service_account': 'Service Account'
        };
        
        return typeMap[authType] || authType;
    }
    
    function setErrorState() {
        $('#cloud-platform').text('Error loading');
        $('#account-id').text('Error loading');
        $('#auth-type').text('Error loading');
        toastr.error('Failed to load cloud account details', 'Error');
    }

    // Call the function on page load
    fetchCloudAccountDetails();

    // Initialize Select2 for Git Repository
    $('#git-repo-search').select2({
        theme: 'bootstrap4',
        ajax: {
            url: `/api/v1/projects/${projectName}/git_repos/search`,
            dataType: 'json',
            delay: 250,
            data: function (params) {
                console.log("Search with current value:", $(this).val());
                return {
                    query: params.term
                };
            },
            processResults: function (data) {
                // Transform the data to ensure proper id field
                const results = data.results.map(item => ({
                    id: item.repo_url,  // Use repo_url as the id
                    text: item.text,
                    repo_url: item.repo_url
                }));
                console.log("Transformed results:", results);
                return { results };
            },
            cache: false
        },
        minimumInputLength: 1,
        placeholder: 'Search for a Git repository'
    });

    // ==================== DISCOVERY CONFIGURATION FUNCTIONS ====================

    let dualListboxInitialized = false;

    // Check discovery configuration status on page load
    function checkDiscoveryConfiguration() {
        const apiUrl = `/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatformType}/${accountId}/discovery/config`;
        console.log('Checking discovery configuration from:', apiUrl);
        
        $.ajax({
            url: apiUrl,
            method: 'GET',
            success: function(response) {
                console.log('Discovery configuration:', response);
                
                const selectedCount = response.selected_resource_types ? response.selected_resource_types.length : 0;
                discoveryConfigured = selectedCount > 0;
                
                updateDiscoveryUI(selectedCount);
            },
            error: function(xhr, status, error) {
                console.error('Failed to check discovery configuration:', error);
                discoveryConfigured = false;
                updateDiscoveryUI(0);
            }
        });
    }

    // Update Discovery UI based on configuration status
    function updateDiscoveryUI(selectedCount) {
        const $discoveryRadio = $('#discovery-radio');
        const $discoveryStatus = $('#discovery-status');
        
        if (selectedCount > 0) {
            $discoveryRadio.prop('disabled', false);
            $discoveryStatus
                .removeClass('not-configured')
                .addClass('configured')
                .text(`(${selectedCount} resource type${selectedCount !== 1 ? 's' : ''} selected)`);
        } else {
            $discoveryRadio.prop('disabled', true);
            $discoveryStatus
                .removeClass('configured')
                .addClass('not-configured')
                .text('(Not Configured)');
        }
    }

    // Scroll to discovery config card when configure link is clicked
    $('#configure-discovery-link').on('click', function(e) {
        e.preventDefault();
        console.log('Configure link clicked - scrolling to card');
        
        // Scroll to the discovery config card
        $('html, body').animate({
            scrollTop: $('#discovery-config-card').offset().top - 100
        }, 500);
    });

    // Load Discovery Configuration
    function loadDiscoveryConfiguration() {
        const resourceTypesUrl = `/api/v1/discovery/resource_types/${cloudPlatformType}`;
        
        $.ajax({
            url: resourceTypesUrl,
            method: 'GET',
            success: function(response) {
                console.log('Available resource types:', response);
                populateAndInitializeDualListbox(response.resource_types);
            },
            error: function(xhr, status, error) {
                console.error('Failed to fetch resource types:', error);
                toastr.error('Failed to load available resource types', 'Error');
                // Hide loading and show empty form on error
                $('#discovery-config-loading').hide();
                $('#discovery-config-form').show();
            }
        });
    }

    // Populate select and initialize dual listbox
    function populateAndInitializeDualListbox(resourceTypes) {
        const $select = $('#resource-types-duallistbox');
        $select.empty();
        
        console.log('Populating select with', resourceTypes.length, 'resource types');
        
        // Add all available resource types as options
        resourceTypes.forEach(function(resourceType) {
            const optionText = `${resourceType.table_name} - ${resourceType.description}`;
            $select.append(
                $('<option></option>')
                    .val(resourceType.table_name)
                    .text(optionText)
            );
        });
        
        // Fetch current config and pre-select
        const configUrl = `/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatformType}/${accountId}/discovery/config`;
        
        $.ajax({
            url: configUrl,
            method: 'GET',
            success: function(response) {
                console.log('Current discovery config:', response);
                
                if (response.selected_resource_types && response.selected_resource_types.length > 0) {
                    const selectedTableNames = response.selected_resource_types.map(rt => rt.table_name);
                    $select.val(selectedTableNames);
                    console.log('Pre-selected', selectedTableNames.length, 'resource types');
                }
                
                // Now initialize the dual listbox
                initializeDualListbox();
            },
            error: function(xhr, status, error) {
                console.error('Failed to fetch current config:', error);
                // Still initialize even if we can't get current config
                initializeDualListbox();
            }
        });
    }

    // Initialize Bootstrap Dual Listbox (simple version for non-modal)
    function initializeDualListbox() {
        console.log('Initializing dual listbox...');

        try {
            const $dualListbox = $('#resource-types-duallistbox').bootstrapDualListbox({
                nonSelectedListLabel: 'Available Resource Types',
                selectedListLabel: 'Selected Resource Types',
                preserveSelectionOnMove: 'moved',
                moveOnSelect: false,
                filterTextClear: 'Show all',
                filterPlaceHolder: 'Filter',
                infoText: 'Showing all {0}',
                infoTextFiltered: '<span class="badge badge-warning">Filtered</span> {0} from {1}',
                infoTextEmpty: 'Empty list'
            });

            dualListboxInitialized = true;
            console.log('Dual Listbox initialized successfully');

            // Hide loading, show form
            $('#discovery-config-loading').hide();
            $('#discovery-config-form').show();
        } catch (error) {
            console.error('Error initializing dual listbox:', error);
            // Still hide loading even on error
            $('#discovery-config-loading').hide();
            $('#discovery-config-form').show();
        }
    }

    // Save Discovery Configuration
    $('#save-discovery-config').on('click', function() {
        const selectedResourceTypes = $('#resource-types-duallistbox').val() || [];
        
        console.log('Saving selected resource types:', selectedResourceTypes);
        
        // Allow saving even with 0 resources - this will disable discovery
        
        const configUrl = `/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatformType}/${accountId}/discovery/config`;
        
        $.ajax({
            url: configUrl,
            method: 'PUT',
            contentType: 'application/json',
            data: JSON.stringify({
                selected_resource_types: selectedResourceTypes
            }),
            success: function(response) {
                console.log('Discovery config saved:', response);
                
                if (selectedResourceTypes.length === 0) {
                    toastr.success('Discovery configuration cleared. Discovery option is now disabled.', 'Success');
                } else {
                    toastr.success(`Discovery configuration saved with ${selectedResourceTypes.length} resource type(s)`, 'Success');
                }
                
                // Refresh the discovery configuration status
                checkDiscoveryConfiguration();
            },
            error: function(xhr, status, error) {
                console.error('Failed to save discovery config:', error);
                const errorMessage = xhr.responseJSON?.detail || 'Failed to save configuration';
                toastr.error(errorMessage, 'Error');
            }
        });
    });

    // Check discovery configuration on page load
    checkDiscoveryConfiguration();
    
    // Load discovery configuration on page load
    loadDiscoveryConfiguration();
    
    // Initialize UI state on page load
    function initializeUIState() {
        const runType = $('input[name="run-type"]:checked').val();
        console.log('Initializing UI for run type:', runType);
        
        if (runType === 'benchmark') {
            const benchmarkType = $('input[name="benchmark-type"]:checked').val();
            console.log('Benchmark type:', benchmarkType);
            
            // Show benchmark section
            $('#benchmark-section').show();
            
            if (benchmarkType === 'auto') {
                // Auto benchmark: show mod type, hide git repo
                $('#mod-type-section').show();
                $('#git-repo-section').hide();
                $('#benchmark-select-section').hide();
            } else {
                // Custom benchmark: show git repo, hide mod type
                $('#git-repo-section').show();
                $('#mod-type-section').hide();
                $('#benchmark-select-section').hide();
            }
        } else if (runType === 'query') {
            $('#git-repo-section').show();
            $('#benchmark-section').hide();
            $('#mod-type-section').hide();
            $('#benchmark-select-section').hide();
        } else if (runType === 'discovery') {
            $('#git-repo-section').hide();
            $('#benchmark-section').hide();
            $('#mod-type-section').hide();
            $('#benchmark-select-section').hide();
        }
    }
    
    // Call initialization
    initializeUIState();

    // ==================== END DISCOVERY CONFIGURATION FUNCTIONS ====================

    // Toggle Git Repo and Benchmark Fields Based on Run Type
    $('input[name="run-type"]').on('change', function () {
        const runType = $(this).val();
        
        if (runType === 'discovery') {
            // Discovery mode: hide everything except timeout
            $('#git-repo-section').hide();
            $('#benchmark-section').hide();
            $('#mod-type-section').hide();
            $('#benchmark-select-section').hide();
            
            // Reset selections
            $('#mod-type-select').val('');
            $('#benchmark-select').val('').prop('disabled', true);
            $('#git-repo-search').val(null).trigger('change');
            
        } else if (runType === 'query') {
            $('#git-repo-section').show();
            $('#benchmark-section').hide();
            $('#mod-type-section').hide();
            $('#benchmark-select-section').hide();
            
            // Reset benchmark selections to prevent dirty payload
            $('#mod-type-select').val('');
            $('#benchmark-select').val('').prop('disabled', true);
        } else {
            $('#benchmark-section').show();
            const benchmarkType = $('input[name="benchmark-type"]:checked').val();
            
            if (benchmarkType === 'auto') {
                $('#git-repo-section').hide();
                $('#mod-type-section').show();
                const modType = $('#mod-type-select').val();
                if (modType) {
                    $('#benchmark-select-section').show();
                }
            } else {
                $('#git-repo-section').show();
                $('#mod-type-section').hide();
                $('#benchmark-select-section').hide();
            }
            
            // Reset git repo selection to prevent dirty payload
            $('#git-repo-search').val(null).trigger('change');
        }
    });

    // Toggle between auto and custom benchmark
    $('input[name="benchmark-type"]').on('change', function () {
        const benchmarkType = $(this).val();
        
        if (benchmarkType === 'auto') {
            $('#git-repo-section').hide();
            $('#mod-type-section').show();
            const modType = $('#mod-type-select').val();
            if (modType) {
                $('#benchmark-select-section').show();
            }
            // Reset git repo selection
            $('#git-repo-search').val(null).trigger('change');
        } else {
            $('#git-repo-section').show();
            $('#mod-type-section').hide();
            $('#benchmark-select-section').hide();
            // Reset mod type and benchmark selections
            $('#mod-type-select').val('');
            $('#benchmark-select').val('').prop('disabled', true);
        }
    });

    // When mod type is selected, fetch and populate benchmarks
    $('#mod-type-select').on('change', function() {
        const modType = $(this).val();
        const $benchmarkSelect = $('#benchmark-select');
        
        if (!modType) {
            $('#benchmark-select-section').hide();
            $benchmarkSelect.empty().append('<option value="">Select a benchmark...</option>').prop('disabled', true);
            return;
        }
        
        console.log('Fetching benchmarks for mod type:', modType);
        
        $.ajax({
            url: `/api/v1/discovery/benchmarks/${cloudPlatformType}/${modType}`,
            method: 'GET',
            success: function(response) {
                console.log('Available benchmarks:', response);
                availableBenchmarks = response;
                
                $benchmarkSelect.empty();
                $benchmarkSelect.append('<option value="">Select a benchmark...</option>');
                
                if (response.benchmarks && response.benchmarks.length > 0) {
                    response.benchmarks.forEach(function(benchmark) {
                        $benchmarkSelect.append(
                            $('<option></option>')
                                .val(benchmark.id)
                                .text(benchmark.display)
                        );
                    });
                    
                    $benchmarkSelect.prop('disabled', false);
                    $('#benchmark-select-section').show();
                } else {
                    toastr.info('No benchmarks found for this category', 'Info');
                    $benchmarkSelect.prop('disabled', true);
                    $('#benchmark-select-section').hide();
                }
            },
            error: function(xhr, status, error) {
                console.error('Failed to fetch benchmarks:', error);
                toastr.error('Failed to load benchmarks', 'Error');
                $benchmarkSelect.prop('disabled', true);
                $('#benchmark-select-section').hide();
            }
        });
    });

    function updateExecutionTypeUI() {
        const executionType = $('input[name="execution-type"]:checked').val();
        const runType = $('input[name="run-type"]:checked').val();
        const $executeBtn = $('#execute-btn');
        const $scheduleSection = $('#schedule-section');
        
        // Show/hide schedule section
        if (executionType === 'schedule') {
            $scheduleSection.show();
        } else {
            $scheduleSection.hide();
        }
        
        // Update button text based on execution type and run type
        if (executionType === 'schedule') {
            if (runType === 'discovery') {
                $executeBtn.text('Schedule Discovery');
            } else {
                $executeBtn.text('Schedule Run');
            }
        } else {
            if (runType === 'discovery') {
                $executeBtn.text('Run Discovery');
            } else if (runType === 'query') {
                $executeBtn.text('Run Query');
            } else {
                $executeBtn.text('Run Benchmark');
            }
        }
    }

    // Form Submission
    $('#cloud-query-form').on('submit', function (e) {
        e.preventDefault();

        const runType = $('input[name="run-type"]:checked').val();
        const executionType = $('input[name="execution-type"]:checked').val();
        const scheduleExpression = $('#schedule-expression').val();
        const timeout = $('#task-timeout').val();
        const complianceEngineVersion = $('#compliance-engine-version').val();
        const queryEngineVersion = $('#query-engine-version').val();
        const pluginVersion = $('#plugin-version').val();

        let payload = {};
        let apiUrl = '';

        // Handle Discovery separately (different endpoint and payload)
        if (runType === 'discovery') {
            apiUrl = `/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatformType}/${accountId}/run_discovery`;
            
            // Discovery payload structure
            if (timeout && parseInt(timeout) > 0) {
                payload.task_timeout_hours = parseInt(timeout);
            }
            if (executionType === 'schedule' && scheduleExpression) {
                if (!isValidScheduleExpression(scheduleExpression)) {
                    toastr.error('Invalid schedule expression. Use rate(1 hour), cron(0 12 * * ? *), or simple format (30m, 1h, 1d)', 'Error');
                    return;
                }
                payload.schedule = { frequency: scheduleExpression };
            }
        } 
        // Handle Benchmark and Query (same endpoint, different payloads)
        else {
            apiUrl = `/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatformType}/${accountId}/run_query`;
            
            // Base payload for benchmark/query
            payload = {
                cloud_account: accountId,
                cloud_platform: cloudPlatformType,
                run_type: runType
            };

            // Add optional versions
            if (complianceEngineVersion) {
                payload.compliance_engine_version = complianceEngineVersion;
            }
            if (queryEngineVersion) {
                payload.query_engine_version = queryEngineVersion;
            }
            if (pluginVersion) {
                payload.plugin_version = pluginVersion;
            }

            // Add timeout
            if (timeout && parseInt(timeout) > 0) {
                payload.task_timeout_hours = parseInt(timeout);
            }

            // Add schedule if scheduling
            if (executionType === 'schedule') {
                if (!scheduleExpression) {
                    toastr.error('Please provide a schedule expression', 'Error');
                    return;
                }
                if (!isValidScheduleExpression(scheduleExpression)) {
                    toastr.error('Invalid schedule expression. Use rate(1 hour), cron(0 12 * * ? *), or simple format (30m, 1h, 1d)', 'Error');
                    return;
                }
                payload.schedule = { frequency: scheduleExpression };
            }

            // Add type-specific fields
            if (runType === 'benchmark') {
                const benchmarkType = $('input[name="benchmark-type"]:checked').val();
                
                if (benchmarkType === 'auto') {
                    const modType = $('#mod-type-select').val();
                    const benchmarkId = $('#benchmark-select').val();
                    
                    if (!modType || !benchmarkId) {
                        toastr.error('Please select a benchmark category and specific benchmark', 'Error');
                        return;
                    }
                    
                    payload.use_auto_benchmark = true;
                    payload.mod_type = modType;
                    payload.benchmark_id = benchmarkId;
                } else {
                    const gitRepo = $('#git-repo-search').val();
                    if (!gitRepo || gitRepo === 'Select a Git repository') {
                        toastr.error('Please select a Git repository for custom benchmark', 'Error');
                        return;
                    }
                    payload.git_repo = gitRepo;
                    payload.use_auto_benchmark = false;
                }
            } else if (runType === 'query') {
                const gitRepo = $('#git-repo-search').val();
                if (!gitRepo || gitRepo === 'Select a Git repository') {
                    toastr.error('Please select a Git repository', 'Error');
                    return;
                }
                payload.git_repo = gitRepo;
            }
        }

        console.log('Submitting to:', apiUrl);
        console.log('Payload:', payload);

        // Disable the submit button to prevent double submissions
        const $submitBtn = $('#execute-btn');
        const originalBtnText = $submitBtn.text();
        $submitBtn.prop('disabled', true).html('<i class="fas fa-spinner fa-spin"></i> Submitting...');

        $.ajax({
            url: apiUrl,
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(payload),
            success: function (response) {
                console.log('Execution initiated:', response);

                let message;
                if (executionType === 'schedule') {
                    message = `${runType.charAt(0).toUpperCase() + runType.slice(1)} scheduled successfully.`;
                    // Build link to the schedule details page
                    if (response.data && response.data.schedule_id) {
                        const scheduleUrl = `/dashboard/projects/${projectName}/cloud_accounts/${cloudPlatformType}/${accountId}/scheduled_runs/${response.data.schedule_id}`;
                        message += ` <a href="${scheduleUrl}" class="text-primary">View schedule details</a>`;
                    }
                } else {
                    message = `${runType.charAt(0).toUpperCase() + runType.slice(1)} execution initiated successfully`;
                }

                $('#successModalMessage').html(message);
                $('#successModal').modal('show');

                // Re-enable button
                $submitBtn.prop('disabled', false).text(originalBtnText);

                // Refresh the runs list after a short delay
                setTimeout(function() {
                    refreshQueryRuns(currentPage);
                }, 1000);
            },
            error: function (xhr) {
                console.error('Failed to initiate execution:', xhr.responseText);

                let errorMessage = 'Failed to initiate execution. Please try again.';
                if (xhr.responseJSON && xhr.responseJSON.detail) {
                    const detail = xhr.responseJSON.detail;
                    if (typeof detail === 'string') {
                        errorMessage = detail;
                    } else if (Array.isArray(detail)) {
                        errorMessage = detail.map(function(e) { return e.msg || JSON.stringify(e); }).join('; ');
                    } else {
                        errorMessage = JSON.stringify(detail);
                    }
                }

                $('#failureModalMessage').text(errorMessage);
                $('#failureModal').modal('show');
                
                // Re-enable button
                $submitBtn.prop('disabled', false).text(originalBtnText);
            }
        });
    });

    // Helper function to get cookie value
    function getCookie(name) {
        const value = `; ${document.cookie}`;
        const parts = value.split(`; ${name}=`);
        if (parts.length === 2) return parts.pop().split(';').shift();
        return null;
    }

    // WebSocket connections stored by request type
    let websockets = {};
    let websocketsInitialized = false;

    function setupWebSocket() {
        console.log("Setting up WebSocket connections");

        // Setup WebSocket for query_run (benchmarks and queries)
        setupWebSocketForType('query_run');

        // Setup WebSocket for discovery_run
        setupWebSocketForType('discovery_run');

        websocketsInitialized = true;
    }

    // Update tracked runs for existing WebSocket connections
    function updateTrackedRuns() {
        if (!websocketsInitialized) {
            console.log("WebSockets not initialized yet, setting up...");
            setupWebSocket();
            return;
        }

        console.log("Updating tracked runs for existing WebSocket connections");

        ['query_run', 'discovery_run'].forEach(requestType => {
            const ws = websockets[requestType];

            const runItems = $('.run-item');
            console.log(`Total run items in DOM: ${runItems.length}`);

            // Get ACTIVE run IDs matching this request type (only queued or in progress)
            const activeRunIds = runItems.filter(function() {
                const itemType = $(this).data('request-type');
                if (itemType !== requestType) {
                    return false;
                }

                // Check if this run is active (queued or in progress)
                const $status = $(this).find('.run-status');
                const statusText = $status.text().trim().toLowerCase();
                const hasSpinner = $status.find('.custom-spinner').length > 0;
                const isActive = statusText.includes('in progress') ||
                               statusText.includes('queued') ||
                               hasSpinner;

                console.log(`Run ${$(this).data('request-id')} - Type: ${itemType}, Status: "${statusText}", IsActive: ${isActive}`);
                return isActive;
            }).map(function() {
                return $(this).data('request-id');
            }).get();

            console.log(`Matched ${activeRunIds.length} ACTIVE runs for ${requestType}`);
            console.log(`Active run IDs:`, activeRunIds);

            if (activeRunIds.length === 0) {
                console.log(`No active runs to track for ${requestType}`);
                return;
            }

            const message = {
                type: "update_tracked",
                request_ids: activeRunIds
            };

            if (ws && ws.readyState === WebSocket.OPEN) {
                console.log(`Updating tracked runs for ${requestType}:`, activeRunIds);
                ws.send(JSON.stringify(message));
            } else if (ws && ws.readyState === WebSocket.CONNECTING) {
                console.log(`WebSocket for ${requestType} is connecting, will send update when open`);
                // Queue the message to send when connection opens
                ws.addEventListener('open', function() {
                    console.log(`Sending queued update for ${requestType}:`, activeRunIds);
                    ws.send(JSON.stringify(message));
                }, { once: true });
            } else {
                console.log(`WebSocket for ${requestType} not ready, reconnecting...`);
                setupWebSocketForType(requestType);
            }
        });
    }

    function setupWebSocketForType(requestType) {
        console.log(`Setting up WebSocket connection for type: ${requestType}`);

        try {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const host = window.location.host;
            const wsUrl = `${protocol}//${host}/api/v1/projects/${projectName}/requests/get_status_updates/${requestType}`;
            console.log(`Attempting to connect to WebSocket URL: ${wsUrl}`);

            // Close existing connection if present
            const existingWs = websockets[requestType];
            if (existingWs) {
                console.log(`Found existing WebSocket for ${requestType}. State:`, existingWs.readyState);
                if (existingWs.readyState === WebSocket.OPEN || existingWs.readyState === WebSocket.CONNECTING) {
                    console.log(`Closing existing WebSocket for ${requestType}`);
                    existingWs.close();
                }
            }

            const ws = new WebSocket(wsUrl);

            // Store reference
            websockets[requestType] = ws;
            
            ws.onopen = function() {
                console.log(`WebSocket connection opened for ${requestType}`);
                try {
                    const runItems = $('.run-item');
                    console.log(`Found run items: ${runItems.length}`);

                    // Get ACTIVE run IDs matching this request type (only queued or in progress)
                    const activeRunIds = runItems.filter(function() {
                        const itemType = $(this).data('request-type');
                        if (itemType !== requestType) {
                            return false;
                        }

                        // Check if this run is active (queued or in progress)
                        const $status = $(this).find('.run-status');
                        const statusText = $status.text().trim().toLowerCase();
                        const hasSpinner = $status.find('.custom-spinner').length > 0;
                        const isActive = statusText.includes('in progress') ||
                                       statusText.includes('queued') ||
                                       hasSpinner;

                        console.log(`Run ${$(this).data('request-id')} - Type: ${itemType}, Status: "${statusText}", HasSpinner: ${hasSpinner}, IsActive: ${isActive}`);
                        return isActive;
                    }).map(function() {
                        const requestId = $(this).data('request-id');
                        console.log(`Including active run ID: ${requestId}`);
                        return requestId;
                    }).get();

                    console.log(`Identified ${activeRunIds.length} ACTIVE run IDs for ${requestType}:`, activeRunIds);

                    if (activeRunIds.length > 0) {
                        const message = {
                            type: "update_tracked",
                            request_ids: activeRunIds
                        };
                        console.log(`Sending tracking message for ${requestType}:`, message);
                        ws.send(JSON.stringify(message));
                    } else {
                        console.log(`No active runs found to track for ${requestType}`);
                    }
                } catch (error) {
                    console.error(`Error in WebSocket onopen handler for ${requestType}:`, error);
                }
            };
            
            ws.onmessage = function(event) {
                console.log(`WebSocket message received for ${requestType}:`, event.data);
                try {
                    const data = JSON.parse(event.data);
                    console.log(`Parsed WebSocket message for ${requestType}:`, data);
                    
                    if (data.request_id && data.update) {
                        console.log(`Processing state update for run ${data.request_id}:`, data.update);
                        
                        const $runItem = $(`.run-item[data-request-id="${data.request_id}"]`);
                        console.log(`Found matching run item:`, $runItem.length > 0);
                        
                        if ($runItem.length) {
                            if (data.update.state) {
                                const oldState = $runItem.find('.run-status').text().trim();
                                const newState = data.update.state;
                                console.log(`Updating state for ${data.request_id} from "${oldState}" to "${newState}"`);
                                
                                updateRunItem(data.request_id, data.update);
                            }
                        } else {
                            console.log(`Run item ${data.request_id} not found in DOM`);
                            console.log("Refreshing runs list to catch up with backend state");
                            refreshQueryRuns(currentPage);
                        }
                    } else {
                        console.log(`Received message in unexpected format:`, data);
                    }
                } catch (error) {
                    console.error(`Error processing WebSocket message for ${requestType}:`, error);
                }
            };
            
            ws.onerror = function(error) {
                console.error(`WebSocket Error for ${requestType}:`, error);
            };
            
            ws.onclose = function(event) {
                console.log(`WebSocket closed for ${requestType}:`, event);
                
                if (!window.isUnloading) {
                    console.log(`Scheduling WebSocket reconnection for ${requestType} in 5 seconds`);
                    setTimeout(() => setupWebSocketForType(requestType), 5000);
                }
            };
            
        } catch (error) {
            console.error(`Error in setupWebSocketForType for ${requestType}:`, error);
        }
    }

    function updateRunItem(requestId, update) {
        console.log(`Beginning update for run item ${requestId}:`, update);
        
        const $runItem = $(`.run-item[data-request-id="${requestId}"]`);
        if ($runItem.length) {
            console.log(`Found run item element for ${requestId}`);
            
            if (update.state) {
                const $statusElement = $runItem.find('.run-status');
                const currentState = $statusElement.text().trim();
                const newState = update.state;
                
                console.log(`Updating status from "${currentState}" to "${newState}"`);
                
                const statusClass = getStatusClass(newState);
                const statusText = getStatusText(newState);
                
                console.log(`New status class: ${statusClass}, New status text: ${statusText}`);
                
                $statusElement
                    .removeClass('status-completed status-in-progress status-failed')
                    .addClass(statusClass)
                    .html(statusText);
                
                console.log(`Status updated successfully for ${requestId}`);
            }
        } else {
            console.log(`Could not find run item element for ${requestId}`);
        }
    }

    // Load query runs
    function refreshQueryRuns(page = 1) {
        console.log(`Loading runs for page ${page}`);

        $.ajax({
            url: `/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatformType}/${accountId}/runs`,
            method: 'GET',
            data: { page: page, page_size: 10, _: new Date().getTime() },
            success: function (response) {
                console.log('Received runs:', response);
                currentPage = page;
                updateQueryRunsList(response.runs);
                updatePagination(response.total_pages, page);
                console.log("Updating tracked runs for WebSocket...");
                updateTrackedRuns();
                console.log("WebSocket tracking updated");
            },
            error: function (xhr) {
                console.error('Failed to load runs:', xhr.responseText);
                $('#cloud-queries-list').html('<div class="p-3 text-center">Failed to load runs</div>');
                $('#pagination-container').empty();
                toastr.error('Failed to load runs', 'Error');
            }
        });
    }

    // Update Query Runs List
    function updateQueryRunsList(runs) {
        console.log("Updating runs list with:", runs);
        const $runsList = $('#cloud-queries-list');
        $runsList.empty();

        if (!runs || runs.length === 0) {
            console.log("No runs found");
            $runsList.html('<div class="p-3 text-center">No runs found</div>');
            return;
        }

        runs.forEach(function (run) {
            const statusClass = getStatusClass(run.state);
            const statusText = getStatusText(run.state);

            // Determine display text for "Account • Repo/Type" column
            let gitRepoDisplay;
            if (run.request_type === 'discovery_run') {
                gitRepoDisplay = 'Discovery Run';
            } else if (run.use_auto_benchmark && run.benchmark_id) {
                // Show benchmark details: "cis_v400 (Compliance)"
                const formattedBenchmark = formatBenchmarkName(run.benchmark_id);
                const formattedModType = formatModType(run.mod_type);
                gitRepoDisplay = `${formattedBenchmark} (${formattedModType})`;
            } else if (run.git_repo) {
                gitRepoDisplay = run.git_repo;
            } else {
                gitRepoDisplay = "N/A";
            }

            const truncatedId = run.request_id ? run.request_id.substring(0, 8) + '...' : 'N/A';

            $runsList.append(`
                <div class="run-item" data-request-id="${run.request_id}" data-request-type="${run.request_type}">
                    <div class="run-id" title="${run.request_id}">${truncatedId}</div>
                    <div class="run-account-repo">${run.cloud_account || 'N/A'} • ${gitRepoDisplay || 'N/A'}</div>
                    <div class="run-status-container">
                        <div class="run-status ${statusClass}">${statusText}</div>
                    </div>
                    <div class="run-time">${new Date(run.requested_on).toLocaleString()}</div>
                    <div class="run-actions">
                        <button class="btn btn-primary btn-sm view-logs-btn" data-request-id="${run.request_id}">View Logs</button>
                    </div>
                </div>
            `);
        });
        console.log("Runs list updated");
    }

    // Format benchmark_id: strip underscores, capitalize words
    function formatBenchmarkName(benchmarkId) {
        if (!benchmarkId) return 'N/A';
        // Replace underscores with spaces and capitalize first letter of each word
        return benchmarkId
            .replace(/_/g, ' ')
            .split(' ')
            .map(word => word.charAt(0).toUpperCase() + word.slice(1))
            .join(' ');
    }

    // Format mod_type: capitalize first letter
    function formatModType(modType) {
        if (!modType) return 'N/A';
        // Replace underscores with spaces and capitalize first letter of each word
        return modType
            .replace(/_/g, ' ')
            .split(' ')
            .map(word => word.charAt(0).toUpperCase() + word.slice(1))
            .join(' ');
    }

    // Utilities for Status
    function getStatusClass(status) {
        const normalized = status.toLowerCase();
        if (normalized.includes('succeeded') || normalized === 'completed') return 'status-completed';
        if (normalized.includes('execution') && normalized.includes('failed')) return 'status-failed';
        if (normalized.includes('benchmark') && normalized.includes('failed')) return 'status-warning';
        if (normalized.includes('failed')) return 'status-failed';
        if (normalized.includes('progress') || normalized === 'queued') return 'status-in-progress';
        if (normalized.includes('timed')) return 'status-timeout';
        return '';
    }

    function isValidScheduleExpression(expression) {
        const cronRegex = /^cron\((.+?)\)$/;
        const rateRegex = /^rate\(\d+\s+(minutes?|hours?|days?)\)$/i;
        const simpleRegex = /^\d+[mhd]$/i;
        const stdCronRegex = /^[\d*\/,\-]+\s+[\d*\/,\-]+\s+[\d*\/,\-?]+\s+[\d*\/,\-]+\s+[\d*\/,\-?]+$/;
        return cronRegex.test(expression) || rateRegex.test(expression)
            || simpleRegex.test(expression) || stdCronRegex.test(expression);
    }

    function getStatusText(status) {
        const normalized = status.toLowerCase();
        if (normalized.includes('succeeded')) return 'Benchmark Succeeded';
        if (normalized.includes('benchmark') && normalized.includes('failed')) return 'Benchmark Failed';
        if (normalized.includes('execution') && normalized.includes('failed')) return 'Execution Failed';
        if (normalized === 'completed') return 'Completed';
        if (normalized === 'failed') return 'Failed';
        if (normalized.includes('progress')) return '<span class="custom-spinner"></span> In Progress';
        if (normalized === 'queued') return '<span class="custom-spinner"></span> Queued';
        if (normalized.includes('timed')) return 'Timed Out';
        return status;
    }

    function updatePagination(totalPages, currentPage) {
        const $paginationContainer = $('#pagination-container');
        $paginationContainer.empty();
    
        console.log("Total Pages:", totalPages, "Current Page:", currentPage);
    
        if (totalPages <= 1) {
            console.log("Skipping pagination rendering. Only one page available.");
            return;
        }
    
        const $pagination = $('<ul class="pagination"></ul>');
    
        for (let i = 1; i <= totalPages; i++) {
            const isActive = i === currentPage ? 'active' : '';
            $pagination.append(`
                <li class="page-item ${isActive}">
                    <a class="page-link" href="#" data-page="${i}">${i}</a>
                </li>
            `);
        }
    
        $paginationContainer.append($pagination);
    
        console.log("Pagination rendered:", $pagination.html());
    }

    // View Logs
    $(document).on('click', '.view-logs-btn', function () {
        const requestId = $(this).data('request-id');
        console.log(`View logs clicked for request ID: ${requestId}`);
        const logsUrl = `/dashboard/projects/${projectName}/cloud_accounts/${cloudPlatformType}/${accountId}/logs/${requestId}`;
        window.location.href = logsUrl;
    });

    $(document).on('click', '.page-link', function (e) {
        e.preventDefault();
        const page = $(this).data('page');
        refreshQueryRuns(page);
    });

    // Add event handler for execution type changes
    $('input[name="execution-type"]').on('change', updateExecutionTypeUI);
    
    // Add event handler for run type changes to update button text
    $('input[name="run-type"]').on('change', updateExecutionTypeUI);

    // Set initial state
    updateExecutionTypeUI();

    // Initial load
    console.log("Performing initial load of runs");
    refreshQueryRuns();
    $(window).on('beforeunload', function() {
        window.isUnloading = true;
        // Close all WebSocket connections
        Object.values(websockets).forEach(ws => {
            if (ws) ws.close();
        });
    });
});