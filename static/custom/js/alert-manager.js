$(function() {
    // Constants
    const ITEMS_PER_PAGE = 20;
    let currentPage = 1;
    let currentAlert = null;
    const projectName = Qubiva.url.projectName();
    const cloudPlatform = Qubiva.url.cloudPlatform();
    const accountId = Qubiva.url.accountId();
    const alertId = Qubiva.url.alertId();
    const baseUrl = window.location.pathname.split('/').slice(0, 8).join('/'); // URL without alert ID

    $('#alert-modal').on('hidden.bs.modal', function() {
        // Always reset the URL to the base URL without the alert ID
        history.pushState(null, '', baseUrl);
    });
    

    if (alertId) {
        // Open the modal for the specific alert ID
        openAlertModal(alertId);
    } else {
        // Load the general alerts list if no alert ID is present
        loadAlerts();
    }

    console.log("Alert manager initialized");

    // Initialize
    loadAlerts();
    setupEventListeners();

    function setupEventListeners() {
        // Initialize daterangepicker
        console.log("Setting up event listeners");
        console.log("jQuery loaded:", typeof $ !== 'undefined');
        console.log("moment loaded:", typeof moment !== 'undefined');
        console.log("daterangepicker loaded:", typeof $.fn.daterangepicker !== 'undefined');
        console.log("time-range element exists:", $('#time-range').length);

        $('#time-range').daterangepicker({
            timePicker: true,
            autoUpdateInput: false,
            opens: 'left',  // Open the picker to the left
            showDropdowns: true,  // Allow month/year dropdown selection
            locale: {
                format: 'YYYY-MM-DD HH:mm',
                cancelLabel: 'Clear',
                applyLabel: 'Apply',
            }
        });

        // Handle apply and cancel events for daterangepicker
        $('#time-range').on('apply.daterangepicker', function(ev, picker) {
            $(this).val(picker.startDate.format('YYYY-MM-DD HH:mm') + ' - ' + picker.endDate.format('YYYY-MM-DD HH:mm'));
            currentPage = 1;
            loadAlerts();
        });
        
        $('#time-range').on('cancel.daterangepicker', function(ev, picker) {
            $(this).val('');
            currentPage = 1;
            loadAlerts();
        });

        // Status filter change handler
        $('#status-filter').on('change', function() {
            currentPage = 1;
            loadAlerts();
        });

        // Refresh button handler
        $('#refresh-alerts').on('click', loadAlerts);

        // Copy JSON button handler
        $('#copy-json').on('click', copyJsonToClipboard);

        // Resolution form handler
        $('#resolve-alert-form').on('submit', function(e) {
            e.preventDefault();
            resolveAlert();
        });
    }

    async function loadAlerts() {
        try {
            const timeRangeValue = $('#time-range').val();
            const status = $('#status-filter').val();
            
            showLoadingState();
            console.log("Loading alerts with filters:", { timeRangeValue, status }); // Debug log

            // Construct query parameters
            let queryParams = new URLSearchParams({
                page: currentPage,
                page_size: ITEMS_PER_PAGE
            });

            // Only add status if it's not "all"
            if (status !== 'all') {
                queryParams.append('status', status);
            }

            // Add time range if selected
            if (timeRangeValue) {
                const picker = $('#time-range').data('daterangepicker');
                // Format dates in ISO format for API
                const startTime = picker.startDate.toISOString();
                const endTime = picker.endDate.toISOString();
                console.log("Date range:", { startTime, endTime }); // Debug log
                queryParams.append('start_time', startTime);
                queryParams.append('end_time', endTime);
            }

            const baseUrl = `/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatform}/${accountId}/alerts`;
            const response = await fetch(
                `${baseUrl}?${queryParams.toString()}`,
                {
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                }
            );

            if (response.status === 404) {
                renderEmptyState('No alerts found');
                updatePagination({ total_items: 0, total_pages: 0, has_next: false, has_previous: false });
                hideLoadingState();
                return;
            }

            if (!response.ok) {
                throw new Error('Failed to fetch alerts');
            }

            const data = await response.json();
            
            if (!data.alerts || data.alerts.length === 0) {
                renderEmptyState('No alerts found for the selected filters');
            } else {
                renderAlerts(data.alerts);
            }
            
            updatePagination(data.pagination);
            hideLoadingState();
        } catch (error) {
            renderEmptyState('Failed to load alerts: ' + error.message);
            hideLoadingState();
        }
    }

    function renderAlerts(alerts) {
        const tbody = $('#alerts-body');
        tbody.empty();

        alerts.forEach(alert => {
            const summary = getAlertSummary(alert.alert);
            const row = $('<tr>').html(`
                <td title="${alert.cloud_alert_id}">${alert.cloud_alert_id}</td>
                <td title="${summary}">${summary}</td>
                <td>
                    <span class="badge badge-${getStatusBadgeClass(alert.status)}">
                        ${alert.status}
                    </span>
                </td>
                <td>${formatDate(alert.created_at)}</td>
                <td class="text-right" style="width: 100px; white-space: nowrap;">
                    ${alert.status === 'open' ? `
                        <button class="btn btn-sm btn-warning resolve-alert" data-alert-id="${alert.cloud_alert_id}">
                            <i class="fas fa-check"></i>
                        </button>
                    ` : ''}
                    <button class="btn btn-sm btn-info view-alert" data-alert-id="${alert.cloud_alert_id}">
                        <i class="fas fa-eye"></i>
                    </button>
                </td>
            `);

            tbody.append(row);
        });
    
        // Rest of the click handlers remain the same
        $('.view-alert').on('click', function() {
            const alertId = $(this).data('alert-id');
            const alertUrl = `/dashboard/projects/${projectName}/cloud_accounts/${cloudPlatform}/${accountId}/alerts/${alertId}`;
            history.pushState(null, '', alertUrl);
            openAlertModal(alertId);
        });
    
        $('.resolve-alert').on('click', function() {
            const alertId = $(this).data('alert-id');
            openAlertModal(alertId, true);
        });
    }

    function renderEmptyState(message) {
        const tbody = $('#alerts-body');
        tbody.html(`
            <tr>
                <td colspan="7" class="text-center py-4">
                    <div class="alert alert-info mb-0">
                        <i class="fas fa-info-circle mr-2"></i>${message}
                    </div>
                </td>
            </tr>
        `);
    }

    async function openAlertModal(alertId, showResolutionForm = false) {
        try {
            const response = await fetch(
                `/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatform}/${accountId}/alerts/${alertId}`,
                {
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                }
            );

            if (!response.ok) {
                throw new Error('Failed to fetch alert details');
            }

            const alert = await response.json();
            currentAlert = alert;

            const modalTitle = showResolutionForm ? 'Resolve Alert' : 'Alert Details';
            $('#alert-modal-title').text(modalTitle);

            // Populate modal fields
            $('#modal-alert-id').text(alert.cloud_alert_id);
            $('#modal-alert-status').html(
                `<span class="badge badge-${getStatusBadgeClass(alert.status)}">${alert.status}</span>`
            );
            $('#modal-alert-platform').text(alert.cloud_platform.toUpperCase());
            $('#modal-alert-account').text(alert.account_id);
            $('#modal-alert-created').text(formatDate(alert.created_at));

            // Format and display JSON
            const formattedJson = JSON.stringify(alert.alert, null, 2);
            $('#raw-alert-json').text(formattedJson);

            // Show/hide resolution form
            $('#resolution-form-section').toggle(alert.status === 'open' && showResolutionForm);

            // Render timeline
            renderTimeline(alert);

            // Show modal
            $('#alert-modal').modal({
                backdrop: true,  // Allow closing on outside click
                keyboard: true   // Allow closing via Esc key
            }).on('shown.bs.modal', function () {
                $(this).find('.modal-body').css('overflow-y', 'auto'); // Ensure scrollability
            });

        } catch (error) {
            showError('Failed to load alert details: ' + error.message);
        }
    }

    function renderTimeline(alert) {
        const timeline = $('#alert-timeline');
        timeline.empty();

        // Collect all timeline events
        const events = [];

        // 1. Alert Created
        events.push({
            timestamp: alert.created_at,
            type: 'created',
            icon: 'fas fa-bell',
            title: 'Alert Created',
            body: null
        });

        // 2. Process resolution history (if exists)
        if (alert.resolution_history && alert.resolution_history.length > 0) {
            alert.resolution_history.forEach(historyItem => {
                // Add resolved event
                events.push({
                    timestamp: historyItem.resolved_at,
                    type: 'resolved',
                    icon: 'fas fa-check',
                    title: 'Alert Resolved',
                    body: `<strong>Resolved by:</strong> ${historyItem.resolved_by}<br><strong>Resolution Note:</strong> ${historyItem.resolution_note}`
                });

                // Add reopened event if it exists
                if (historyItem.reopened_at) {
                    events.push({
                        timestamp: historyItem.reopened_at,
                        type: 'reopened',
                        icon: 'fas fa-redo',
                        title: 'Alert Reopened',
                        body: 'Alert was automatically reopened due to recurring issue'
                    });
                }
            });
        }

        // 3. Current resolution state (if resolved and not in history)
        if (alert.status === 'resolved' && alert.resolved_at) {
            // Check if this resolution is already in the history to avoid duplicates
            const isAlreadyInHistory = alert.resolution_history && 
                alert.resolution_history.some(item => item.resolved_at === alert.resolved_at);
            
            if (!isAlreadyInHistory) {
                events.push({
                    timestamp: alert.resolved_at,
                    type: 'resolved',
                    icon: 'fas fa-check',
                    title: 'Alert Resolved',
                    body: `<strong>Resolved by:</strong> ${alert.resolved_by}<br><strong>Resolution Note:</strong> ${alert.resolution_note}`
                });
            }
        }

        // Sort events by timestamp
        events.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));

        // Render timeline items
        events.forEach(event => {
            const timelineItem = $(`
                <div class="timeline-item">
                    <span class="time">
                        <i class="fas fa-clock"></i> ${formatDate(event.timestamp)}
                    </span>
                    <div>
                        <i class="${event.icon}"></i>
                        <span class="timeline-header">${event.title}</span>
                    </div>
                    ${event.body ? `<div class="timeline-body">${event.body}</div>` : ''}
                </div>
            `);
            
            timeline.append(timelineItem);
        });
    }

    function retainModalFocus(modalId) {
        $(modalId).modal('handleUpdate').focus();
    }
    

    async function resolveAlert() {
        if (!currentAlert) return;
    
        try {
            const resolutionNote = $('#resolution-note').val().trim();
            if (!resolutionNote) {
                $('#error-modal-message').text('Resolution note is required');
                $('#error-modal').modal('show');
                return;
            }
    
            const response = await fetch(
                `/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatform}/${accountId}/alerts/${currentAlert.cloud_alert_id}/resolve`,
                {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: JSON.stringify({
                        resolved_by: getCurrentUser(),
                        resolution_note: resolutionNote
                    })
                }
            );
    
            if (!response.ok) {
                const errorData = await response.json();
                $('#error-modal-message').text(errorData.detail || 'Failed to resolve alert');
                $('#error-modal').modal('show');
                return;
            }
    
            showSuccess('Alert resolved successfully');
            $('#alert-modal').modal('hide');
            loadAlerts();
        } catch (error) {
            $('#error-modal-message').text(error.message);
            $('#error-modal').modal('show');
        }
    }
    
    function copyJsonToClipboard() {
        const jsonText = $('#raw-alert-json').text();
        navigator.clipboard.writeText(jsonText).then(
            () => {
                // Show temporary success message
                const $btn = $('#copy-json');
                const originalHtml = $btn.html();
                $btn.html('<i class="fas fa-check"></i> Copied!');
                setTimeout(() => {
                    $btn.html(originalHtml);
                }, 2000);
            },
            () => showError('Failed to copy to clipboard')
        );
    }

    function updatePagination(paginationData) {
        const pagination = $('#alerts-pagination');
        pagination.empty();

        // Update showing count
        const start = paginationData.total_items === 0 ? 0 : (currentPage - 1) * ITEMS_PER_PAGE + 1;
        $('#showing-start').text(start);
        $('#showing-end').text(Math.min(currentPage * ITEMS_PER_PAGE, paginationData.total_items));
        $('#total-alerts').text(paginationData.total_items);

        if (paginationData.total_pages <= 1) return;

        // Previous page button
        if (paginationData.has_previous) {
            pagination.append(`
                <li class="page-item">
                    <a class="page-link" href="#" data-page="${currentPage - 1}">&laquo;</a>
                </li>
            `);
        }

        // Page numbers
        for (let i = 1; i <= paginationData.total_pages; i++) {
            pagination.append(`
                <li class="page-item ${i === currentPage ? 'active' : ''}">
                    <a class="page-link" href="#" data-page="${i}">${i}</a>
                </li>
            `);
        }

        // Next page button
        if (paginationData.has_next) {
            pagination.append(`
                <li class="page-item">
                    <a class="page-link" href="#" data-page="${currentPage + 1}">&raquo;</a>
                </li>
            `);
        }

        // Add click handlers
        $('.page-link').on('click', function(e) {
            e.preventDefault();
            currentPage = $(this).data('page');
            loadAlerts();
        });
    }

    // Utility Functions
    function getStatusBadgeClass(status) {
        return status === 'open' ? 'warning' : 'success';
    }

    function getAlertSummary(alertData) {
        if (typeof alertData === 'object') {
            // Check if backend already provided a summary field (preferred)
            if (alertData.summary) {
                return alertData.summary;
            }

            // AWS CloudWatch Alarm
            if (alertData.AlarmName) {
                return alertData.AlarmName;
            }
            // AWS EventBridge
            if (alertData.detail) {
                return alertData.detail.title || alertData.detail.description || JSON.stringify(alertData).substring(0, 100) + '...';
            }
            // Azure
            if (alertData.data?.essentials?.alertRule) {
                return alertData.data.essentials.alertRule;
            }

            // GCP - More robust summary extraction
            if (alertData.incident && alertData.incident.incident_id) {
                // Try combined policy + resource first
                if (alertData.incident.policy_name && alertData.incident.resource_display_name) {
                    return `${alertData.incident.policy_name} - ${alertData.incident.resource_display_name}`;
                }

                // Fall back to individual fields
                return alertData.incident.policy_name ||
                    alertData.incident.condition_name ||
                    alertData.incident.resource_display_name ||
                    `GCP Incident ${alertData.incident.incident_id}`;
            }

            // Default fallback
            return JSON.stringify(alertData).substring(0, 100) + '...';
        }
        return 'No summary available';
    }

    function formatDate(dateString) {
        const date = new Date(dateString);
        return date.toLocaleString('default', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    }

    function showLoadingState() {
        $('#alerts-body').html('<tr><td colspan="5" class="text-center">Loading alerts...</td></tr>');
    }

    function hideLoadingState() {
        // This is handled by renderAlerts
    }

    function showSuccess(message) {
        $('#success-modal-message').text(message);
        $('#success-modal').modal('show');
    }

    function showError(message) {
        $('#error-modal-message').text(message);
        $('#error-modal').modal({
            backdrop: 'static',
            keyboard: false
        });
    }

    function getCurrentUser() {
        return currentUser;
    }

    $('#error-modal').on('hidden.bs.modal', function() {
        if ($('#alert-modal').hasClass('show')) {
            $('body').addClass('modal-open');
        }
    });

    $('#time-range').on('apply.daterangepicker', function(ev, picker) {
        $(this).val(picker.startDate.format('YYYY-MM-DD HH:mm') + ' - ' + picker.endDate.format('YYYY-MM-DD HH:mm'));
        currentPage = 1;
        loadAlerts();
    });
    
    $('#time-range').on('cancel.daterangepicker', function(ev, picker) {
        $(this).val('');
        currentPage = 1;
        loadAlerts();
    });
});