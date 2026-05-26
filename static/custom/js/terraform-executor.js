$(function () {
    console.log("Initializing Terraform Executor script");
    
    const projectName = Qubiva.url.projectName();
    const workspaceName = Qubiva.url.workspaceName();
    console.log(`Project Name: ${projectName}, Workspace Name: ${workspaceName}`);

    loadWorkspaceDetails(projectName, workspaceName);

    let currentPage = 1;
    let websocket;

    function loadWorkspaceLockStatus() {
        $.ajax({
            url: `/api/v1/projects/${projectName}/workspaces/${workspaceName}/lock-status`,
            method: 'GET',
            success: function(response) {
                console.log('Initial lock status:', response);
                updateLockToggle(response);
            },
            error: function(xhr) {
                console.error('Failed to get initial lock status:', xhr.responseText);
                $('#workspace-lock-status').text('Error loading status');
            }
        });
    }

    $('#workspace-lock-toggle').on('change', function() {
        const $toggle = $(this);
        const isChecked = $toggle.is(':checked');
        
        if (isChecked) {
            // User wants to lock workspace
            lockWorkspace();
        } else {
            // User wants to unlock workspace
            checkAndUnlockWorkspace();
        }
    });

    function lockWorkspace() {
        $('#workspace-lock-status').text('Locking...');
        
        // Note: You may need to add a lock endpoint, or just show a message
        // For now, let's just show that manual locking isn't implemented yet
        toastr.info('Workspaces are automatically locked during terraform runs. However a workspace locked by terraform run can be forcefully unlocked.', 'Info');
        $('#workspace-lock-toggle').prop('checked', false); // Revert for now
        updateLockToggle({ is_locked: false });
    }

    function checkAndUnlockWorkspace() {
        // Disable toggle during check
        $('#workspace-lock-toggle').prop('disabled', true);
        $('#workspace-lock-status').text('Checking...');
        
        $.ajax({
            url: `/api/v1/projects/${projectName}/workspaces/${workspaceName}/lock-status`,
            method: 'GET',
            success: function(response) {
                if (!response.is_locked) {
                    toastr.info('Workspace is already unlocked', 'Status');
                    updateLockToggle(response);
                } else if (response.request_details) {
                    handleUnlockConfirmation(response.request_details);
                } else {
                    // Unlock without strong warning
                    forceUnlockWorkspace();
                }
            },
            error: function(xhr) {
                console.error('Failed to check lock status:', xhr.responseText);
                toastr.error('Failed to check workspace status', 'Error');
            },
            complete: function() {
                $('#workspace-lock-toggle').prop('disabled', false);
            }
        });
    }

    function updateLockToggle(response) {
        const $toggle = $('#workspace-lock-toggle');
        const $status = $('#workspace-lock-status');
        
        if (response.is_locked) {
            $toggle.prop('checked', true);
            if (response.request_details) {
                const state = response.request_details.state;
                const requestId = response.request_details.request_id;
                const shortId = requestId.substring(0, 8);
                const logsUrl = `/dashboard/projects/${projectName}/workspaces/${workspaceName}/logs/${requestId}`;
                
                if (state === 'in progress' || state === 'queued') {
                    $status.html(`🔒 Locked by <strong>${state}</strong> run (<a href="${logsUrl}" target="_blank" class="text-primary">${shortId}...</a>)`);
                    $status.removeClass('text-success text-warning').addClass('text-danger');
                } else {
                    $status.html(`🔒 Locked by <strong>completed</strong> run (<a href="${logsUrl}" target="_blank" class="text-primary">${shortId}...</a>)`);
                    $status.removeClass('text-success text-danger').addClass('text-warning');
                }
            } else {
                $status.html('🔒 Locked');
                $status.addClass('text-warning');
            }
        } else {
            $toggle.prop('checked', false);
            $status.html('🔓 Available');
            $status.removeClass('text-danger text-warning').addClass('text-success');
        }
        
        $toggle.prop('disabled', false);
    }

    function handleUnlockConfirmation(requestDetails) {
        const requestId = requestDetails.request_id;
        const requestedBy = requestDetails.requested_by || 'Unknown';
        const requestState = requestDetails.state || 'Unknown';
        const shortId = requestId.substring(0, 8);
        const logsUrl = `/dashboard/projects/${projectName}/workspaces/${workspaceName}/logs/${requestId}`;
        
        let modalContent;
        if (requestState === 'in progress' || requestState === 'queued') {
            modalContent = `
                <div class="alert alert-danger">
                    <strong>WARNING:</strong> This workspace is locked by an ACTIVE terraform run!
                </div>
                <table class="table table-sm">
                    <tr><td><strong>Request ID:</strong></td><td><a href="${logsUrl}" target="_blank" class="text-primary">${shortId}...</a></td></tr>
                    <tr><td><strong>Status:</strong></td><td><span class="badge badge-warning">${requestState}</span></td></tr>
                    <tr><td><strong>Started by:</strong></td><td>${requestedBy}</td></tr>
                    <tr><td><strong>Started:</strong></td><td>${new Date(requestDetails.requested_on).toLocaleString()}</td></tr>
                </table>
                <p class="text-danger"><strong>Force unlocking may cause issues with the running terraform process.</strong></p>
            `;
        } else {
            modalContent = `
                <p>Workspace is locked by completed run <a href="${logsUrl}" target="_blank" class="text-primary">${shortId}...</a></p>
                <p>Do you want to unlock the workspace?</p>
            `;
        }
        
        // Set modal content
        $('#unlockConfirmModalBody').html(modalContent);
        
        // Show modal
        $('#unlockConfirmModal').modal('show');
        
        // Handle confirm button click
        $('#confirmUnlockBtn').off('click').on('click', function() {
            $('#unlockConfirmModal').modal('hide');
            forceUnlockWorkspace();
        });
        
        // Handle modal dismiss (cancel) - reset toggle
        $('#unlockConfirmModal').off('hidden.bs.modal').on('hidden.bs.modal', function() {
            // Check if unlock was not confirmed (modal was just closed/cancelled)
            if ($('#workspace-lock-status').text() !== 'Unlocking...') {
                // Reset toggle to locked position
                $('#workspace-lock-toggle').prop('checked', true);
                updateLockToggle({ 
                    is_locked: true, 
                    request_details: requestDetails 
                });
            }
        });
    }

    // REPLACE the forceUnlockWorkspace function with this:

    function forceUnlockWorkspace() {
        $('#workspace-lock-status').text('Unlocking...');
        
        $.ajax({
            url: `/api/v1/projects/${projectName}/workspaces/${workspaceName}/force-unlock`,
            method: 'POST',
            success: function(response) {
                console.log('Force unlock response:', response);
                toastr.success('Workspace unlocked successfully', 'Success');
                
                setTimeout(() => {
                    loadWorkspaceLockStatus();
                }, 500);
            },
            error: function(xhr) {
                console.error('Failed to force unlock:', xhr.responseText);
                let errorMessage = 'Failed to unlock workspace';
                if (xhr.responseJSON && xhr.responseJSON.detail) {
                    errorMessage = xhr.responseJSON.detail;
                }
                toastr.error(errorMessage, 'Error');
                
                // On error, refresh status to show current state
                loadWorkspaceLockStatus();
            }
        });
    }


    function loadWorkspaceDetails(projectName, workspaceName) {
        console.log(`Loading workspace details for ${projectName}/${workspaceName}`);
        
        // Get workspace details
        $.ajax({
            url: `/api/v1/projects/${projectName}/workspaces/${workspaceName}`,
            method: 'GET',
            success: function(workspaceData) {
                console.log('Workspace data:', workspaceData);
                
                // Update IaC engine version
                $('#iac-version').text(workspaceData.terraform_version || 'N/A');

                // Update cloud account details
                $('#cloud-platform').text(workspaceData.cloud_platform || 'N/A');
                
                if (workspaceData.cloud_account && workspaceData.cloud_platform) {
                    const accountLink = `/dashboard/projects/${projectName}/cloud_accounts/${workspaceData.cloud_platform}/${workspaceData.cloud_account}`;
                    $('#account-link').attr('href', accountLink).text(workspaceData.cloud_account);
                } else {
                    $('#account-link').text('N/A').removeAttr('href');
                }
                
                // Get git repo details
                if (workspaceData.github_repo_name) {
                    $.ajax({
                        url: `/api/v1/projects/${projectName}/git_repos/${workspaceData.github_repo_name}`,
                        method: 'GET',
                        success: function(repoData) {
                            console.log('Repo data:', repoData);
                            
                            // Update git repo details
                            if (repoData.repo_url) {
                                $('#repo-link').attr('href', repoData.repo_url).text(repoData.repo_name || workspaceData.github_repo_name);
                            } else {
                                $('#repo-link').text(repoData.repo_name || workspaceData.github_repo_name).removeAttr('href');
                            }
                            
                            $('#git-branch').text(repoData.branch || 'N/A');
                        },
                        error: function(xhr) {
                            console.error('Failed to load git repo details:', xhr.responseText);
                            $('#repo-link').text(workspaceData.github_repo_name).removeAttr('href');
                            $('#git-branch').text('N/A');
                        }
                    });
                } else {
                    $('#repo-link').text('N/A').removeAttr('href');
                    $('#git-branch').text('N/A');
                }
            },
            error: function(xhr) {
                console.error('Failed to load workspace details:', xhr.responseText);
                $('#cloud-platform').text('Error');
                $('#iac-version').text('Error');
                $('#account-link').text('Error').removeAttr('href');
                $('#repo-link').text('Error').removeAttr('href');
                $('#git-branch').text('Error');
            }
        });
    }

    loadWorkspaceLockStatus();
    
    // Form submission with phase validation
    $('#terraform-form').on('submit', function(e) {
        e.preventDefault();

        if ($('input[name="terraform-phases"]:checked').length === 0) {
            toastr.error('Please select at least one Terraform phase');
            return false;
        }

        console.log("Form submitted");
        
        var $submitButton = $('#execute-btn');
        var $spinner = $('<span class="spinner-border spinner-border-sm ml-2" role="status" aria-hidden="true"></span>');
        
        $submitButton.prop('disabled', true).append($spinner);
        

        // Collect selected Terraform phases
        var selectedPhases = [];
        $('input[name="terraform-phases"]:checked').each(function() {
            selectedPhases.push($(this).val());
        });

        var timeoutValue = $('#task-timeout').val().trim();
        var parsedTimeout = timeoutValue ? parseInt(timeoutValue) : null;

        if (timeoutValue && (isNaN(parsedTimeout) || parsedTimeout <= 0)) {
            toastr.error('Task timeout must be a positive number', 'Validation Error');
            $submitButton.prop('disabled', false);
            $spinner.remove();
            return;
        }

        var requestData = {
            phases: selectedPhases,
            task_timeout_hours: parsedTimeout
        };
        console.log("Request Data:", requestData);

        $.ajax({
            url: `/api/v1/projects/${projectName}/workspaces/${workspaceName}/execute`,
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(requestData),
            success: function(response) {
                console.log("Terraform execution initiated successfully:", response);
                toastr.success(`Terraform execution initiated. Request ID: ${response.request_id}`, 'Success');
                
                let retryCount = 0;
                const maxRetries = 5;
                const retryInterval = 2000; // 2 seconds

                function retryLoadRuns() {
                    console.log(`Attempting to load runs (Retry ${retryCount + 1}/${maxRetries})`);
                    loadTerraformRuns(1, function(success) {
                        if (!success && retryCount < maxRetries) {
                            retryCount++;
                            console.log(`Load unsuccessful, retrying in ${retryInterval}ms`);
                            setTimeout(retryLoadRuns, retryInterval);
                        } else if (!success) {
                            console.log("Max retries reached, couldn't load updated runs");
                        } else {
                            console.log("Runs loaded successfully after retries");
                            // Smooth scroll to the runs list
                            $('html, body').animate({
                                scrollTop: $("#terraform-runs-list").offset().top - 20
                            }, 1000);
                        }
                    });
                }

                retryLoadRuns();
            },
            error: function(xhr) {
                console.error("Error initiating Terraform execution:", xhr);
                let errorMessage = 'Failed to initiate Terraform execution';
                
                // Handle array of validation error messages from API
                if (xhr.responseJSON && xhr.responseJSON.detail) {
                    if (Array.isArray(xhr.responseJSON.detail)) {
                        // Join each error message with a newline
                        errorMessage = xhr.responseJSON.detail.map(err => err.msg).join('\n');
                    } else {
                        // Single error message
                        errorMessage = xhr.responseJSON.detail;
                    }
                }
                
                toastr.error(errorMessage, 'Error');
            },
            complete: function() {
                $submitButton.prop('disabled', false);
                $spinner.remove();
            }
        });
    });

    // Load Terraform runs
    function loadTerraformRuns(page = 1, callback) {
        console.log(`Loading Terraform runs for page ${page}`);
        $.ajax({
            url: `/api/v1/projects/${projectName}/workspaces/${workspaceName}/runs`,
            method: 'GET',
            data: { page: page, page_size: 10, _: new Date().getTime() },
            success: function(response) {
                console.log('Received Terraform runs:', response);
                currentPage = page;
                updateRunsList(response.runs);
                updatePagination(response.total_pages, page);
                setupWebSocket();
                if (callback) callback(true);
            },
            error: function(xhr) {
                console.error('Failed to load Terraform runs:', xhr.responseText);
                $('#terraform-runs-list').html('<div class="p-3 text-center">Failed to load Terraform runs</div>');
                $('#pagination-container').empty();
                toastr.error('Failed to load Terraform runs', 'Error');
                if (callback) callback(false);
            }
        });
    }

    // Update runs list
    function updateRunsList(runs) {
        console.log("Updating runs list with:", runs);
        var $runsList = $('#terraform-runs-list');
        $runsList.empty();
        
        if (!runs || runs.length === 0) {
            console.log("No runs found");
            $runsList.html('<div class="p-3 text-center">No Terraform runs found</div>');
            return;
        }
        
        runs.forEach(function(run) {
            var statusClass = getStatusClass(run.state);
            var statusText = getStatusText(run.state);
            var truncatedId = run.request_id ? run.request_id.substring(0, 8) + '...' : 'N/A';
            var isSpeculative = !!run.is_speculative;
            var isPlanned = run.state === 'planned' && !isSpeculative;

            // Source badge: webhook push, webhook PR (speculative), or manual
            var sourceBadge = '';
            if (run.trigger_source === 'webhook_pr' || isSpeculative) {
                var prLabel = run.pr_number ? `PR #${run.pr_number}` : 'PR';
                sourceBadge = `<span class="badge badge-info ml-1" title="Speculative plan triggered by pull request"><i class="fab fa-github mr-1"></i>${prLabel} · Speculative</span>`;
            } else if (run.trigger_source === 'webhook_push') {
                var shaLabel = run.head_sha ? run.head_sha.substring(0, 7) : '';
                sourceBadge = `<span class="badge badge-secondary ml-1" title="Triggered by GitHub push${shaLabel ? ' · ' + shaLabel : ''}"><i class="fab fa-github mr-1"></i>Push${shaLabel ? ' · ' + shaLabel : ''}</span>`;
            }

            var approvalActions = isPlanned ? `
                <button class="btn btn-success btn-sm approve-run-btn ml-1" data-request-id="${run.request_id}" title="Approve plan and proceed with apply">Approve</button>
                <button class="btn btn-danger btn-sm reject-run-btn ml-1" data-request-id="${run.request_id}" title="Reject plan">Reject</button>
                <button class="btn btn-secondary btn-sm view-plan-btn ml-1" data-request-id="${run.request_id}" title="View plan output">Plan Output</button>
            ` : '';

            $runsList.append(`
                <div class="run-item" data-request-id="${run.request_id}" data-is-speculative="${isSpeculative}">
                    <div class="run-id" title="${run.request_id}">${truncatedId}</div>
                    <div class="run-account-repo">
                        ${run.requested_by_user || run.requested_by || 'Unknown User'} •
                        ${run.phases ? run.phases.join(', ') : 'Standard Run'}
                        ${sourceBadge}
                    </div>
                    <div class="run-status-container">
                        <div class="run-status ${statusClass}">${statusText}</div>
                    </div>
                    <div class="run-time">${new Date(run.requested_on).toLocaleString()}</div>
                    <div class="run-actions">
                        <button class="btn btn-primary btn-sm view-logs-btn" data-request-id="${run.request_id}">View Logs</button>
                        ${approvalActions}
                    </div>
                </div>
                ${isPlanned ? `<div class="plan-output-panel collapse" id="plan-output-${run.request_id}"><pre class="plan-output-text bg-dark text-light p-3 m-2 rounded" style="max-height:400px;overflow:auto;white-space:pre-wrap;font-size:0.8em;">Loading plan output...</pre></div>` : ''}
            `);
        });
        console.log("Runs list updated");
    }
    
    function getStatusClass(status) {
        const normalized = status.toLowerCase();
        if (normalized.includes('succeeded') || normalized === 'completed') return 'status-completed';
        if (normalized.includes('execution') && normalized.includes('failed')) return 'status-failed';
        if (normalized.includes('benchmark') && normalized.includes('failed')) return 'status-warning';
        if (normalized.includes('failed')) return 'status-failed';
        if (normalized.includes('progress') || normalized === 'queued') return 'status-in-progress';
        if (normalized.includes('timed') || normalized === 'approval_timed_out') return 'status-timeout';
        if (normalized === 'planned') return 'status-planned';
        if (normalized === 'rejected') return 'status-failed';
        return '';
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
        if (normalized.includes('timed') || normalized === 'approval_timed_out') return 'Approval Timed Out';
        if (normalized === 'planned') return '<i class="fas fa-lock mr-1"></i> Awaiting Approval';
        if (normalized === 'rejected') return 'Rejected';
        return status;
    }

    // Update pagination
    function updatePagination(totalPages, currentPage) {
        var $paginationContainer = $('#pagination-container');
        $paginationContainer.empty();
        
        if (totalPages <= 1) return;
    
        var $pagination = $('<ul class="pagination"></ul>');
        
        for (let i = 1; i <= totalPages; i++) {
            $pagination.append(`
                <li class="page-item ${i === currentPage ? 'active' : ''}">
                    <a class="page-link" href="#" data-page="${i}">${i}</a>
                </li>
            `);
        }
        
        $paginationContainer.append($pagination);
    }

    function setupWebSocket() {
        console.log("Setting up WebSocket connection");
        try {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const host = window.location.host;
            const wsUrl = `${protocol}//${host}/api/v1/projects/${projectName}/requests/get_status_updates/terraform_run`;
            console.log("Attempting to connect to WebSocket URL:", wsUrl);
    
            if (websocket) {
                console.log("Found existing WebSocket connection. State:", 
                    websocket.readyState === 0 ? "CONNECTING" :
                    websocket.readyState === 1 ? "OPEN" :
                    websocket.readyState === 2 ? "CLOSING" :
                    websocket.readyState === 3 ? "CLOSED" : "UNKNOWN");
                    
                if (websocket.readyState === WebSocket.OPEN || websocket.readyState === WebSocket.CONNECTING) {
                    console.log("Closing existing WebSocket connection");
                    websocket.close();
                }
            }
        
            websocket = new WebSocket(wsUrl);
        
            websocket.onopen = function() {
                console.log("WebSocket connection successfully opened");
                try {
                    const runItems = $('.run-item');
                    console.log("Found run items:", runItems.length);
                    
                    const activeRunIds = runItems.filter(function() {
                        const $status = $(this).find('.run-status');
                        const statusText = $status.text().trim().toLowerCase();
                        const hasSpinner = $status.find('.custom-spinner').length > 0;
                        const isActive = statusText.includes('in progress') ||
                                       statusText.includes('queued') ||
                                       statusText.includes('awaiting approval') ||
                                       $status.hasClass('status-planned') ||
                                       hasSpinner;
                        console.log(`Run item status check - Text: "${statusText}", HasSpinner: ${hasSpinner}, IsActive: ${isActive}`);
                        return isActive;
                    }).map(function() {
                        const requestId = $(this).data('request-id');
                        console.log(`Including active run ID: ${requestId}`);
                        return requestId;
                    }).get();
        
                    console.log("Identified active run IDs:", activeRunIds);
                    
                    if (activeRunIds.length > 0) {
                        const message = {
                            type: "update_tracked",
                            request_ids: activeRunIds
                        };
                        console.log("Sending tracking message:", message);
                        websocket.send(JSON.stringify(message));
                    } else {
                        console.log("No active runs found to track");
                    }
                } catch (error) {
                    console.error("Error in WebSocket onopen handler:", error, error.stack);
                }
            };
    
            websocket.onmessage = function(event) {
                console.log("Raw WebSocket message received:", event.data);
                try {
                    const data = JSON.parse(event.data);
                    console.log("Parsed WebSocket message:", data);
                    
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
                            loadTerraformRuns(currentPage);
                        }
                    } else {
                        console.log("Received message in unexpected format:", data);
                    }
                } catch (error) {
                    console.error("Error processing WebSocket message:", error, error.stack);
                }
            };
    
            websocket.onerror = function(error) {
                console.error('WebSocket Error:', error);
                console.log('WebSocket State:', {
                    readyState: websocket.readyState === 0 ? "CONNECTING" :
                               websocket.readyState === 1 ? "OPEN" :
                               websocket.readyState === 2 ? "CLOSING" :
                               websocket.readyState === 3 ? "CLOSED" : "UNKNOWN",
                    url: wsUrl
                });
            };
    
            websocket.onclose = function(event) {
                console.log('WebSocket closed:', {
                    code: event.code,
                    reason: event.reason,
                    wasClean: event.wasClean,
                    readyState: websocket.readyState
                });
                
                if (!window.isUnloading) {
                    console.log('Scheduling WebSocket reconnection in 5 seconds');
                    setTimeout(setupWebSocket, 5000);
                }
            };
    
        } catch (error) {
            console.error("Error in setupWebSocket:", error, error.stack);
        }
    }

    function updateRunItem(requestId, update) {
        console.log(`Beginning update for run item ${requestId}:`, update);

        const $runItem = $(`.run-item[data-request-id="${requestId}"]`);
        if ($runItem.length) {
            console.log(`Found run item element for ${requestId}`);

            if (update.state) {
                const newState = update.state;
                const statusClass = getStatusClass(newState);
                const statusText = getStatusText(newState);

                $runItem.find('.run-status')
                    .removeClass('status-completed status-in-progress status-failed status-planned status-timeout')
                    .addClass(statusClass)
                    .html(statusText);

                // When a planned run transitions to another state, remove approval buttons
                if (newState !== 'planned') {
                    $runItem.find('.approve-run-btn, .reject-run-btn, .view-plan-btn').remove();
                    $(`#plan-output-${requestId}`).remove();
                } else if ($runItem.find('.approve-run-btn').length === 0 && $runItem.data('is-speculative') !== true && $runItem.attr('data-is-speculative') !== 'true') {
                    // Transitioned INTO planned (non-speculative) — add approval buttons dynamically
                    $runItem.find('.run-actions').append(`
                        <button class="btn btn-success btn-sm approve-run-btn ml-1" data-request-id="${requestId}">Approve</button>
                        <button class="btn btn-danger btn-sm reject-run-btn ml-1" data-request-id="${requestId}">Reject</button>
                        <button class="btn btn-secondary btn-sm view-plan-btn ml-1" data-request-id="${requestId}">Plan Output</button>
                    `);
                    $runItem.after(`<div class="plan-output-panel collapse" id="plan-output-${requestId}"><pre class="plan-output-text bg-dark text-light p-3 m-2 rounded" style="max-height:400px;overflow:auto;white-space:pre-wrap;font-size:0.8em;">Loading plan output...</pre></div>`);
                }

                console.log(`Status updated successfully for ${requestId}`);
            }
        } else {
            console.log(`Could not find run item element for ${requestId}`);
        }
    }

    // ── Approve / Reject / Plan Output ─────────────────────────────────────────

    var _pendingApprovalId = null;
    var _pendingRejectId = null;

    $(document).on('click', '.approve-run-btn', function() {
        _pendingApprovalId = $(this).data('request-id');
        $('#approveConfirmModal').modal('show');
    });

    $('#confirmApproveBtn').on('click', function() {
        $('#approveConfirmModal').modal('hide');
        if (!_pendingApprovalId) return;
        var requestId = _pendingApprovalId;
        _pendingApprovalId = null;

        var $btn = $(`.approve-run-btn[data-request-id="${requestId}"]`);
        $btn.prop('disabled', true).text('Approving...');

        $.ajax({
            url: `/api/v1/projects/${projectName}/workspaces/${workspaceName}/runs/${requestId}/approve`,
            method: 'POST',
            success: function() {
                toastr.success('Plan approved. Apply phase started.', 'Approved');
                $btn.closest('.run-item').find('.approve-run-btn, .reject-run-btn, .view-plan-btn').remove();
                $(`#plan-output-${requestId}`).remove();
            },
            error: function(xhr) {
                var msg = (xhr.responseJSON && xhr.responseJSON.detail) ? xhr.responseJSON.detail : 'Failed to approve plan';
                toastr.error(msg, 'Error');
                $btn.prop('disabled', false).text('Approve');
            }
        });
    });

    $(document).on('click', '.reject-run-btn', function() {
        _pendingRejectId = $(this).data('request-id');
        $('#rejectConfirmModal').modal('show');
    });

    $('#confirmRejectBtn').on('click', function() {
        $('#rejectConfirmModal').modal('hide');
        if (!_pendingRejectId) return;
        var requestId = _pendingRejectId;
        _pendingRejectId = null;

        var $btn = $(`.reject-run-btn[data-request-id="${requestId}"]`);
        $btn.prop('disabled', true).text('Rejecting...');

        $.ajax({
            url: `/api/v1/projects/${projectName}/workspaces/${workspaceName}/runs/${requestId}/reject`,
            method: 'POST',
            success: function() {
                toastr.success('Plan rejected. Workspace unlocked.', 'Rejected');
                $btn.closest('.run-item').find('.approve-run-btn, .reject-run-btn, .view-plan-btn').remove();
                $(`#plan-output-${requestId}`).remove();
            },
            error: function(xhr) {
                var msg = (xhr.responseJSON && xhr.responseJSON.detail) ? xhr.responseJSON.detail : 'Failed to reject plan';
                toastr.error(msg, 'Error');
                $btn.prop('disabled', false).text('Reject');
            }
        });
    });

    $(document).on('click', '.view-plan-btn', function() {
        var requestId = $(this).data('request-id');
        var $panel = $(`#plan-output-${requestId}`);

        if ($panel.hasClass('show')) {
            $panel.removeClass('show');
            return;
        }

        $panel.addClass('show');
        var $pre = $panel.find('.plan-output-text');

        // Only fetch if not already loaded
        if ($pre.data('loaded')) return;

        $.ajax({
            url: `/api/v1/projects/${projectName}/workspaces/${workspaceName}/runs/${requestId}/plan`,
            method: 'GET',
            success: function(resp) {
                $pre.text(resp.plan_output || '(No plan output available)');
                $pre.data('loaded', true);
            },
            error: function(xhr) {
                var msg = (xhr.responseJSON && xhr.responseJSON.detail) ? xhr.responseJSON.detail : 'Failed to load plan output';
                $pre.text('Error: ' + msg);
            }
        });
    });

    // View logs
    $(document).on('click', '.view-logs-btn', function() {
        var requestId = $(this).data('request-id');
        console.log(`View logs clicked for request ID: ${requestId}`);
        
        // Construct the new URL
        var logsUrl = `/dashboard/projects/${projectName}/workspaces/${workspaceName}/logs/${requestId}`;
        
        // Navigate to the new URL
        window.location.href = logsUrl;
    });

    // Pagination click event
    $(document).on('click', '.page-link', function(e) {
        e.preventDefault();        
        var page = $(this).data('page');
        loadTerraformRuns(page);
    });

    // Initial load
    console.log("Performing initial load of Terraform runs");
    loadTerraformRuns();
    $(window).on('beforeunload', function() {
        window.isUnloading = true;
        if (websocket) {
            console.log("Closing WebSocket due to page unload");
            websocket.close();
        }
    });
});