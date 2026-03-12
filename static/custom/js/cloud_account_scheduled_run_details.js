$(function () {
    console.log("=== Initialization Start ===");

    // Extract path parameters
    const projectName = Qubiva.url.projectName();
    const cloudPlatform = Qubiva.url.cloudPlatform();
    const accountId = Qubiva.url.accountId();
    const scheduleId = Qubiva.url.lastSegment();

    console.log("Extracted URL parameters:", {
        projectName,
        cloudPlatform,
        accountId,
        scheduleId,
        fullPath: window.location.pathname
    });

    let currentPage = 1;
    let isToggleInProgress = false;


    // Load schedule details
    function loadScheduleDetails() {
        $.ajax({
            url: `/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatform}/${accountId}/scheduled_runs/${scheduleId}`,
            method: 'GET',
            success: function(schedule) {
                console.log('Received schedule details:', schedule);
                
                $('#schedule-id').text(schedule.schedule_id);
                $('#schedule-requested-by').text(schedule.requested_by || 'N/A');
                $('#schedule-frequency').text(schedule.frequency);
                $('#schedule-next-execution').text(
                    schedule.next_execution ? new Date(schedule.next_execution).toLocaleString() : 'N/A'
                );
                $('#schedule-last-modified').text(new Date(schedule.last_modified).toLocaleString());
                
                // Update toggle and status label
                const $toggle = $('#schedule-status-toggle');
                $toggle.prop('checked', schedule.status === 'enabled');
                $('#schedule-status-label').text(schedule.status === 'enabled' ? 'Enabled' : 'Disabled');
                
                // Update type and run details from payload
                if (schedule.payload) {
                    const p = schedule.payload;
                    $('#schedule-type').text(p.run_type || 'N/A');

                    if (p.run_type === 'benchmark') {
                        $('#schedule-benchmark').text(p.use_auto_benchmark ? 'Yes' : 'No');
                        if (p.use_auto_benchmark && p.mod_type) {
                            $('#schedule-mod-type').text(p.mod_type);
                            $('#schedule-mod-type-row').removeClass('d-none').addClass('d-flex');
                        }
                        if (p.use_auto_benchmark && p.benchmark_id) {
                            $('#schedule-benchmark-id').text(p.benchmark_id);
                            $('#schedule-benchmark-id-row').removeClass('d-none').addClass('d-flex');
                        }
                        if (!p.use_auto_benchmark && p.git_repo) {
                            $('#schedule-git-repo').text(p.git_repo);
                            $('#schedule-git-repo-row').removeClass('d-none').addClass('d-flex');
                        }
                    } else if (p.run_type === 'query') {
                        $('#schedule-benchmark-row').addClass('d-none').removeClass('d-flex');
                        if (p.git_repo) {
                            $('#schedule-git-repo').text(p.git_repo);
                            $('#schedule-git-repo-row').removeClass('d-none').addClass('d-flex');
                        }
                    } else if (p.run_type === 'discovery') {
                        $('#schedule-benchmark-row').addClass('d-none');
                    }
                }

            },
            error: function(xhr) {
                console.error('Failed to load schedule details:', xhr);
                toastr.error('Failed to load schedule details', 'Error');
            }
        });
    }

    // Handle status toggle
    $('#schedule-status-toggle').on('change', function() {
        if (isToggleInProgress) {
            return;
        }

        const newState = $(this).prop('checked') ? 'enabled' : 'disabled';
        isToggleInProgress = true;

        // Disable the toggle while request is in progress
        $(this).prop('disabled', true);

        $.ajax({
            url: `/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatform}/${accountId}/scheduled_runs/${scheduleId}/state`,
            method: 'PUT',
            contentType: 'application/json',
            data: JSON.stringify({ state: newState }),
            success: function(response) {
                console.log('Schedule state updated:', response);
                $('#schedule-status-label').text(newState === 'enabled' ? 'Enabled' : 'Disabled');
                toastr.success(`Schedule ${newState} successfully`);
            },
            error: function(xhr) {
                console.error('Failed to update schedule state:', xhr);
                // Revert the toggle state
                $('#schedule-status-toggle').prop('checked', !$('#schedule-status-toggle').prop('checked'));
                $('#schedule-status-label').text(newState === 'enabled' ? 'Disabled' : 'Enabled');
                toastr.error('Failed to update schedule state', 'Error');
            },
            complete: function() {
                isToggleInProgress = false;
                $('#schedule-status-toggle').prop('disabled', false);
            }
        });
    });

    // Load schedule requests
    function loadScheduleRequests(page = 1) {
        const $requestsList = $('#schedule-requests-list');
        $requestsList.html('<div class="text-center p-3"><i class="fas fa-spinner fa-spin"></i> Loading requests...</div>');

        $.ajax({
            url: `/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatform}/${accountId}/scheduled_runs/${scheduleId}/requests`,
            method: 'GET',
            data: { page: page, page_size: 10 },
            success: function(response) {
                console.log('Received schedule requests:', response);
                currentPage = page;
                updateRequestsList(response.runs || []);
                updatePagination(response.total_pages || 1, page);
            },
            error: function(xhr) {
                console.error('Failed to load schedule requests:', xhr);
                $requestsList.html('<div class="p-3 text-center">Failed to load requests</div>');
                toastr.error('Failed to load schedule requests', 'Error');
            }
        });
    }

    // Update requests list
    function updateRequestsList(requests) {
        const $requestsList = $('#schedule-requests-list');
        $requestsList.empty();

        if (!requests || requests.length === 0) {
            $requestsList.html('<div class="p-3 text-center">No requests found</div>');
            return;
        }

        requests.forEach(function(request) {
            const statusClass = getStatusClass(request.state);
            const statusText = getStatusText(request.state);
            const truncatedId = request.request_id.substring(0, 8) + '...';

            $requestsList.append(`
                <div class="request-item" data-request-id="${request.request_id}">
                    <div class="request-id" title="${request.request_id}">${truncatedId}</div>
                    <div class="request-status-container">
                        <div class="request-status ${statusClass}">${statusText}</div>
                    </div>
                    <div class="request-time">${new Date(request.requested_on).toLocaleString()}</div>
                    <div class="request-actions">
                        <button class="btn btn-primary btn-sm view-logs-btn" data-request-id="${request.request_id}">View Logs</button>
                    </div>
                </div>
            `);
        });
    }

    // Update pagination
    function updatePagination(totalPages, currentPage) {
        const $pagination = $('#pagination-container');
        $pagination.empty();

        if (totalPages <= 1) return;

        const $ul = $('<ul class="pagination justify-content-center"></ul>');

        for (let i = 1; i <= totalPages; i++) {
            const $li = $('<li class="page-item' + (i === currentPage ? ' active' : '') + '"></li>');
            const $a = $('<a class="page-link" href="#"></a>').text(i);
            $a.on('click', function(e) {
                e.preventDefault();
                loadScheduleRequests(i);
            });
            $li.append($a);
            $ul.append($li);
        }

        $pagination.append($ul);
    }

    // Refresh button handler
    $('#refresh-requests').on('click', function() {
        const $button = $(this);
        $button.addClass('rotating');
        loadScheduleRequests(currentPage);
        
        // Remove rotating class after animation completes
        setTimeout(() => {
            $button.removeClass('rotating');
        }, 500);
    });

    // View logs button handler
    $(document).on('click', '.view-logs-btn', function() {
        const requestId = $(this).data('request-id');
        const logsUrl = `/dashboard/projects/${projectName}/cloud_accounts/${cloudPlatform}/${accountId}/scheduled_runs/${scheduleId}/logs/${requestId}`;
        window.location.href = logsUrl;
    });

    // Utility functions
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

    // Initial load
    loadScheduleDetails();
    loadScheduleRequests();
});