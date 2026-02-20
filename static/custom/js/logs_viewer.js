$(document).ready(function () {
    const logContainer = document.getElementById('output');
    const ansi_up = new AnsiUp(); 
    const logMessages = []; 
    const maxVisibleLogs = 1000;
    let autoScrollEnabled = true;

    const projectName = Qubiva.url.projectName();

    let reconnectAttempts = 0;
    const maxReconnectAttempts = 3;

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

    const ws = connectWebSocket();

    // Load request details
    function loadRequestDetails() {
        const requestId = getRequestIdFromUrl();
        $.ajax({
            url: `/api/v1/projects/${projectName}/requests/${requestId}`,
            method: 'GET',
            success: function(request) {
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
                
                // Show/hide stop button based on state
                const terminalStates = ['completed', 'benchmark succeeded', 'benchmark failed', 'execution failed', 'failed', 'timed out', 'cancelled'];
                if (terminalStates.includes(request.state.toLowerCase())) {
                    $('#stop-execution').addClass('d-none');
                    checkStopPolling();
                } else {
                    $('#stop-execution').removeClass('d-none');
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

    // Stop polling once terminal state is reached
    function checkStopPolling() {
        const state = $('#request-state').text().toLowerCase();
        const terminalStates = ['completed', 'benchmark succeeded', 'benchmark failed', 'execution failed', 'failed', 'timed out', 'cancelled'];
        if (terminalStates.includes(state)) {
            clearInterval(detailsPoller);
        }
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
});