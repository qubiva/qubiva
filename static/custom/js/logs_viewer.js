$(document).ready(function () {
    const logContainer = document.getElementById('output');
    const ansi_up = new AnsiUp();
    const logMessages = [];
    const maxVisibleLogs = 1000;
    let autoScrollEnabled = true;

    const projectName = Qubiva.url.projectName();
    const workspaceName = Qubiva.url.workspaceName(); // null for non-workspace log pages

    let reconnectAttempts = 0;
    const maxReconnectAttempts = 3;
    let activeSocket = null;
    let wasPlanned = false; // tracks whether we saw the "planned" state

    function connectWebSocket() {
        const wsUrl = `${window.location.protocol === 'https:' ? 'wss://' : 'ws://'}${window.location.host}/api/v1/projects/${projectName}/requests/stream_logs/${getRequestIdFromUrl()}`;
        const socket = new WebSocket(wsUrl);

        socket.onopen = function () {
            reconnectAttempts = 0;
            appendLog("Connected to log stream.", "log-info");
        };

        socket.onmessage = function (event) {
            const log = event.data;
            logMessages.push(log);

            if (logMessages.length > 10000) {
                logMessages.shift();
            }

            appendLog(log);
        };

        socket.onerror = function () {
            // onerror is always followed by onclose, so handle messaging there
        };

        socket.onclose = function (event) {
            if (event.code === 1000) {
                // Normal close (server finished streaming)
                appendLog("Log stream ended.", "log-info");
            } else if (reconnectAttempts < maxReconnectAttempts) {
                reconnectAttempts++;
                appendLog(`Connection lost. Reconnecting (${reconnectAttempts}/${maxReconnectAttempts})...`, "log-warning");
                setTimeout(connectWebSocket, 2000 * reconnectAttempts);
            } else {
                appendLog("Unable to connect to log stream. The task may still be starting. Try refreshing the page.", "log-warning");
            }
        };

        return socket;
    }

    activeSocket = connectWebSocket();

    // Load request details
    function loadRequestDetails() {
        const requestId = getRequestIdFromUrl();
        $.ajax({
            url: `/api/v1/projects/${projectName}/requests/${requestId}`,
            method: 'GET',
            success: function(request) {
                updateTerraformMeta(request);
                $('#request-id').text(request.request_id);
                $('#requested-by').text(request.requested_by || 'N/A');
                $('#requested-on').text(new Date(request.requested_on).toLocaleString());
                $('#request-type').text(request.request_type);

                // Format status - capitalize words and replace underscores with spaces
                const formattedStatus = request.state
                    .split(' ')
                    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
                    .join(' ');
                $('#request-state').text(formattedStatus);
                
                $('.error-details').remove();
                
                // Show/hide stop button and approval panel based on state
                const terminalStates = ['completed', 'benchmark succeeded', 'benchmark failed', 'execution failed', 'failed', 'timed out', 'cancelled', 'rejected', 'approval_timed_out'];
                const state = request.state.toLowerCase();

                if (terminalStates.includes(state)) {
                    $('#stop-execution').addClass('d-none');
                    $('#cancel-queued').addClass('d-none');
                    $('#plan-approval-panel').addClass('d-none');
                    checkStopPolling();
                } else if (state === 'planned') {
                    $('#stop-execution').addClass('d-none');
                    $('#cancel-queued').addClass('d-none');
                    if (workspaceName) {
                        showApprovalPanel(request.request_id);
                        wasPlanned = true;
                    }
                } else if (state === 'queued') {
                    $('#stop-execution').addClass('d-none');
                    $('#cancel-queued').removeClass('d-none');
                    $('#plan-approval-panel').addClass('d-none');
                } else {
                    $('#stop-execution').removeClass('d-none');
                    $('#cancel-queued').addClass('d-none');
                    $('#plan-approval-panel').addClass('d-none');
                    // If we previously saw "planned" and now see "in progress", reconnect WS
                    if (wasPlanned && (state === 'in progress' || state === 'queued')) {
                        wasPlanned = false;
                        appendLog('--- Apply phase started. Reconnecting to log stream... ---', 'log-info');
                        reconnectAttempts = 0;
                        if (activeSocket) {
                            try { activeSocket.close(); } catch(e) {}
                        }
                        activeSocket = connectWebSocket();
                    }
                }

                // Handle artifacts section based on state
                const artifactsStatus = $('#artifacts-status');
                const completedStates = terminalStates;
                
                if (completedStates.includes(request.state.toLowerCase())) {
                    const artifactsUrl = `/api/v1/projects/${projectName}/requests/${requestId}/artifacts`;
                    $.getJSON(artifactsUrl + '/check', function(data) {
                        if (data.available) {
                            artifactsStatus.html(
                                `<a href="${artifactsUrl}" class="text-primary">
                                    <i class="fas fa-download mr-1"></i>Download artifacts generated from this run
                                </a>`
                            );
                        } else {
                            artifactsStatus.text('No downloadable results found');
                        }
                    }).fail(function() {
                        artifactsStatus.text('No downloadable results found');
                    });
                } else {
                    artifactsStatus.text('reload after task completion');
                }
    
                // Your existing error handling
                if (request.error && request.error.trim() !== '') {
                    const errorElement = `
                        <li class="list-group-item error-details">
                            <div class="d-flex align-items-start">
                                <i class="fas fa-exclamation-triangle mr-3 mt-1"></i>
                                <div class="flex-grow-1">
                                    <small class="text-muted d-block">Error Details</small>
                                    <div class="error-details-box">
                                        <pre class="mb-0">${request.error}</pre>
                                    </div>
                                </div>
                            </div>
                        </li>`;
                    $('.list-group').append(errorElement);
                }
            },
            error: function(xhr) {
                console.error('Failed to load request details:', xhr);
            }
        });
    }

    // Call loadRequestDetails when page loads and poll while running
    loadRequestDetails();
    const detailsPoller = setInterval(function() {
        loadRequestDetails();
    }, 5000);

    // Stop polling once a truly terminal state is reached
    function checkStopPolling() {
        const state = $('#request-state').text().toLowerCase();
        const terminalStates = ['completed', 'benchmark succeeded', 'benchmark failed', 'execution failed', 'failed', 'timed out', 'cancelled', 'rejected', 'approval_timed_out'];
        if (terminalStates.includes(state)) {
            clearInterval(detailsPoller);
        }
    }

    // Show the approval panel and load plan output
    function showApprovalPanel(requestId) {
        if ($('#plan-approval-panel').hasClass('d-none')) {
            $('#plan-approval-panel').removeClass('d-none');
        }
        // Store the request_id on the buttons so handlers can read it
        $('#logs-approve-btn, #logs-reject-btn').data('request-id', requestId);
    }

    function appendLog(log, logClass = "log-line") {
        const logLine = document.createElement("div");
        logLine.innerHTML = ansi_up.ansi_to_html(log);
        logLine.classList.add(logClass);
        logContainer.appendChild(logLine);

        if (logContainer.childNodes.length > maxVisibleLogs) {
            logContainer.firstChild.style.display = 'none';
        }

        if (autoScrollEnabled) {
            logContainer.scrollTop = logContainer.scrollHeight;
        }
    }

    logContainer.addEventListener("scroll", function () {
        const isAtBottom = logContainer.scrollTop + logContainer.clientHeight >= logContainer.scrollHeight - 10;
        autoScrollEnabled = isAtBottom;
    });

    function getRequestIdFromUrl() {
        return Qubiva.url.get('logs');
    }

    // Refresh button handler
    $('#refresh-details').on('click', function() {
        const $button = $(this);
        $button.addClass('rotating');
        loadRequestDetails();
        
        // Remove rotating class after animation completes
        setTimeout(() => {
            $button.removeClass('rotating');
        }, 500);
    });

    $('#stop-execution').click(function () {
        $('#stopExecutionModal').modal('show');
    });

    $('#cancel-queued').click(function () {
        const requestId = getRequestIdFromUrl();
        const $button = $('#cancel-queued');
        $button.prop('disabled', true).html('<i class="fas fa-spinner fa-spin mr-1"></i>Cancelling...');
        $.ajax({
            url: `/api/v1/projects/${projectName}/workspaces/${workspaceName}/runs/${requestId}/cancel`,
            method: 'POST',
            contentType: 'application/json',
            success: function() {
                $button.addClass('d-none');
                appendLog("Qubiva: > Queued run cancelled.", "log-warning");
                toastr.success('Queued run cancelled');
                loadRequestDetails();
            },
            error: function(xhr) {
                $button.prop('disabled', false).html('<i class="fas fa-times-circle mr-1"></i>Cancel');
                toastr.error('Failed to cancel: ' + Qubiva.extractError(xhr, 'Unknown error'));
            }
        });
    });

    $('#confirmStopBtn').click(function () {
        $('#stopExecutionModal').modal('hide');

        const requestId = getRequestIdFromUrl();
        const $button = $('#stop-execution');
        $button.prop('disabled', true);
        $button.html('<i class="fas fa-spinner fa-spin mr-1"></i>Stopping...');

        $.ajax({
            url: `/api/v1/projects/${projectName}/requests/${requestId}/stop`,
            method: 'POST',
            contentType: 'application/json',
            success: function() {
                $button.addClass('d-none');
                appendLog("Qubiva: > Execution stopped by user.", "log-warning");
                toastr.success('Execution stopped successfully');
                loadRequestDetails();
            },
            error: function(xhr) {
                $button.prop('disabled', false);
                $button.html('<i class="fas fa-stop-circle mr-1"></i>Stop Execution');
                toastr.error('Failed to stop execution: ' + Qubiva.extractError(xhr, 'Unknown error'));
            }
        });
    });

    $('#download-logs').click(function () {
        const logContent = logMessages.join("\n");
        const blob = new Blob([logContent], { type: "text/plain" });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.style.display = "none";
        a.href = url;

        // Build meaningful filename from request metadata shown on page
        const requestId = (getRequestIdFromUrl() || 'unknown').substring(0, 12);
        const requestType = ($('#request-type').text() || 'run').trim().toLowerCase();
        const dateStr = new Date().toISOString().slice(0, 10);
        a.download = `${requestType}_${requestId}_${dateStr}.log`;

        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
    });

    // ── Plan approval (logs page) ──────────────────────────────────────────
    $('#logs-approve-btn').on('click', function () {
        $('#logsApprovePlanModal').modal('show');
    });

    $('#logsConfirmApproveBtn').on('click', function () {
        $('#logsApprovePlanModal').modal('hide');
        const requestId = $('#logs-approve-btn').data('request-id');
        const $btn = $('#logs-approve-btn');
        $btn.prop('disabled', true).html('<i class="fas fa-spinner fa-spin mr-1"></i>Approving...');
        $.ajax({
            url: `/api/v1/projects/${projectName}/workspaces/${workspaceName}/runs/${requestId}/approve`,
            method: 'POST',
            success: function () {
                toastr.success('Plan approved. Apply phase started.', 'Approved');
                $('#plan-approval-panel').addClass('d-none');
                wasPlanned = true; // so reconnect triggers on next "in progress" poll
            },
            error: function (xhr) {
                $btn.prop('disabled', false).html('<i class="fas fa-check mr-1"></i>Approve &amp; Apply');
                toastr.error(Qubiva.extractError(xhr, 'Failed to approve plan'), 'Error');
            }
        });
    });

    $('#logs-reject-btn').on('click', function () {
        $('#logsRejectPlanModal').modal('show');
    });

    $('#logsConfirmRejectBtn').on('click', function () {
        $('#logsRejectPlanModal').modal('hide');
        const requestId = $('#logs-reject-btn').data('request-id');
        const $btn = $('#logs-reject-btn');
        $btn.prop('disabled', true).html('<i class="fas fa-spinner fa-spin mr-1"></i>Rejecting...');
        $.ajax({
            url: `/api/v1/projects/${projectName}/workspaces/${workspaceName}/runs/${requestId}/reject`,
            method: 'POST',
            success: function () {
                toastr.success('Plan rejected. Workspace unlocked.', 'Rejected');
                $('#plan-approval-panel').addClass('d-none');
            },
            error: function (xhr) {
                $btn.prop('disabled', false).html('<i class="fas fa-times mr-1"></i>Reject Plan');
                toastr.error(Qubiva.extractError(xhr, 'Failed to reject plan'), 'Error');
            }
        });
    });

    $('#logs-plan-output-toggle').on('click', function () {
        const $section = $('#plan-output-section');
        if ($section.hasClass('d-none')) {
            // Load plan output if not yet loaded
            if (!$('#plan-output-text').text().trim()) {
                const requestId = $('#logs-approve-btn').data('request-id');
                $.ajax({
                    url: `/api/v1/projects/${projectName}/workspaces/${workspaceName}/runs/${requestId}/plan`,
                    method: 'GET',
                    success: function (data) {
                        $('#plan-output-text').text(data.plan_output || '(No plan output available)');
                    },
                    error: function () {
                        $('#plan-output-text').text('(Failed to load plan output)');
                    }
                });
            }
            $section.removeClass('d-none');
            $(this).html('<i class="fas fa-eye-slash mr-1"></i>Hide Plan');
        } else {
            $section.addClass('d-none');
            $(this).html('<i class="fas fa-file-alt mr-1"></i>View Plan');
        }
    });

    $('#download-artifacts').click(function() {
        const requestId = getRequestIdFromUrl();
        const $button = $(this);
        const originalText = $button.html();

        // Show loading state
        $button.prop('disabled', true);
        $button.html('<i class="fas fa-spinner fa-spin mr-2"></i>Preparing Download...');

        // PVC-based flow returns file directly (not JSON with download_url)
        const artifactsUrl = `/api/v1/projects/${projectName}/requests/${requestId}/artifacts`;
        window.location.href = artifactsUrl;

        // Restore button state shortly after triggering browser download
        setTimeout(function() {
            $button.prop('disabled', false);
            $button.html(originalText);
        }, 500);
    });

    // ── Terraform Run Metadata card ────────────────────────────────────────
    function updateTerraformMeta(request) {
        if (request.request_type !== 'terraform_run') return;

        $('#tf-run-meta').removeClass('d-none');

        // Status banner
        const state = (request.state || '').toLowerCase();
        const stateMap = {
            'completed':         { cls: 'tf-status-success',   icon: 'fa-check-circle',   text: 'Apply completed successfully' },
            'execution failed':  { cls: 'tf-status-error',     icon: 'fa-times-circle',   text: 'Execution failed' },
            'failed':            { cls: 'tf-status-error',     icon: 'fa-times-circle',   text: 'Execution failed' },
            'rejected':          { cls: 'tf-status-discarded', icon: 'fa-ban',             text: 'Plan discarded' },
            'approval_timed_out':{ cls: 'tf-status-discarded', icon: 'fa-clock',           text: 'Approval timed out — plan discarded' },
            'cancelled':         { cls: 'tf-status-discarded', icon: 'fa-ban',             text: 'Cancelled' },
            'planned':           { cls: 'tf-status-waiting',   icon: 'fa-lock',            text: 'Awaiting plan approval' },
            'in progress':       { cls: 'tf-status-running',   icon: 'fa-spinner fa-spin', text: 'Running...' },
            'queued':            { cls: 'tf-status-running',   icon: 'fa-clock',           text: 'Queued' },
        };
        const si = stateMap[state] || { cls: 'tf-status-running', icon: 'fa-circle', text: request.state };
        $('#tf-status-banner')
            .attr('class', `tf-status-banner ${si.cls} mb-3`)
            .html(`<i class="fas ${si.icon} mr-2"></i>${si.text}`)
            .removeClass('d-none');

        // Plan change summary (structured JSON from terraform show -json)
        const ps = request.plan_summary;
        if (ps && typeof ps === 'object') {
            const add = ps.add || 0, change = ps.change || 0, destroy = ps.destroy || 0, replace = ps.replace || 0;
            if (add + change + destroy + replace > 0) {
                $('#tf-add-count').text(add);
                $('#tf-change-count').text(change);
                $('#tf-destroy-count').text(destroy);
                if (replace > 0) {
                    $('#tf-replace-count').text(replace);
                    $('#tf-replace-badge').removeClass('d-none');
                }
                $('#tf-plan-summary').removeClass('d-none');
                $('#tf-nochange-banner').addClass('d-none');
            } else {
                $('#tf-plan-summary').addClass('d-none');
                $('#tf-nochange-banner').removeClass('d-none');
            }
        }

        // Trigger source badge
        const triggerLabels = {
            'webhook_push': '<span class="badge badge-primary"><i class="fas fa-code-branch mr-1"></i>Push</span>',
            'webhook_pr':   '<span class="badge badge-info"><i class="fas fa-code-branch mr-1"></i>Pull Request</span>',
        };
        $('#tf-trigger-badge').html(
            triggerLabels[request.trigger_source] ||
            '<span class="badge badge-secondary"><i class="fas fa-user mr-1"></i>Manual</span>'
        );

        // Triggered by
        const who = request.triggered_by || request.requested_by || '—';
        if (request.triggered_by) {
            $('#tf-triggered-by').html(`<i class="fab fa-github mr-1 text-muted"></i>${Qubiva.escapeHtml(who)}`);
        } else {
            $('#tf-triggered-by').text(who);
        }

        // Commit SHA with link
        if (request.head_sha) {
            const short = request.head_sha.substring(0, 7);
            const url = request.head_commit_url || '';
            if (url) {
                $('#tf-commit').html(
                    `<a href="${Qubiva.escapeHtml(url)}" target="_blank" rel="noopener">` +
                    `<span class="tf-sha">${short}</span>&nbsp;<i class="fas fa-external-link-alt fa-xs text-muted"></i></a>`
                );
            } else {
                $('#tf-commit').html(`<span class="tf-sha">${short}</span>`);
            }
        } else {
            $('#tf-commit').text('—');
        }

        // Pull Request link (speculative plans)
        if (request.pr_number) {
            const prUrl = request.pr_url || '';
            if (prUrl) {
                $('#tf-pr').html(
                    `<a href="${Qubiva.escapeHtml(prUrl)}" target="_blank" rel="noopener">` +
                    `#${request.pr_number}&nbsp;<i class="fas fa-external-link-alt fa-xs text-muted"></i></a>`
                );
            } else {
                $('#tf-pr').text(`#${request.pr_number}`);
            }
            $('#tf-pr-row').removeClass('d-none');
        }

        // Approved by / at
        if (request.approved_by) {
            const at = request.approved_at ? ' &nbsp;<span class="text-muted">' + new Date(request.approved_at).toLocaleString() + '</span>' : '';
            $('#tf-approved-by').html(
                `<i class="fas fa-check-circle text-success mr-1"></i>${Qubiva.escapeHtml(request.approved_by)}${at}`
            );
            $('#tf-approval-row').removeClass('d-none');
        }

        // Rejected by
        if (request.rejected_by) {
            $('#tf-rejected-by').html(
                `<i class="fas fa-ban text-danger mr-1"></i>${Qubiva.escapeHtml(request.rejected_by)}`
            );
            $('#tf-rejected-row').removeClass('d-none');
        }
    }
});