/**
 * Compliance Status Card JavaScript
 * Displays the latest compliance benchmark runs and detailed results for a cloud account
 */

let currentBenchmarkData = null;
let selectedRequestId = null;

$(document).ready(function() {
    loadComplianceStatus();

    $('#refresh-compliance-btn').click(function() {
        loadComplianceStatus();
    });
});

function loadComplianceStatus() {
    $('#compliance-loading').show();
    $('#compliance-no-runs').hide();
    $('#compliance-data').hide();
    $('#benchmark-results-container').hide();

    // Extract project, cloud platform, and account from URL
    const projectName = Qubiva.url.projectName();
    const cloudPlatformType = Qubiva.url.cloudPlatform();
    const accountId = Qubiva.url.accountId();

    const apiUrl = `/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatformType}/${accountId}/runs`;

    $.ajax({
        url: apiUrl,
        method: 'GET',
        data: { page: 1, page_size: 50 }, // Get more runs to find compliance benchmarks
        success: function(data) {
            $('#compliance-loading').hide();

            // Filter for compliance benchmark runs only
            const complianceRuns = data.runs.filter(run =>
                run.request_type === 'query_run' &&
                run.use_auto_benchmark === true &&
                run.benchmark_id != null
            );

            if (complianceRuns.length === 0) {
                $('#compliance-no-runs').show();
            } else {
                // Group by benchmark_id and get the latest run for each
                renderComplianceBadges(complianceRuns, projectName, cloudPlatformType, accountId);
                $('#compliance-data').show();

                // Auto-load latest successful benchmark on page load
                const latestSuccessful = complianceRuns.find(run =>
                    run.state.toLowerCase() === 'benchmark succeeded' ||
                    run.state.toLowerCase() === 'benchmark failed'
                );
                if (latestSuccessful) {
                    loadBenchmarkResults(latestSuccessful.request_id, projectName, cloudPlatformType, accountId);
                }
            }
        },
        error: function(xhr) {
            $('#compliance-loading').hide();
            $('#compliance-no-runs').show();
            console.error('Failed to load compliance status:', xhr);
        }
    });
}

function renderComplianceBadges(complianceRuns, projectName, cloudPlatformType, accountId) {
    // Group runs by benchmark_id and get the latest for each
    const latestByBenchmark = {};

    complianceRuns.forEach(run => {
        const benchmarkId = run.benchmark_id;
        if (!latestByBenchmark[benchmarkId] ||
            new Date(run.requested_on) > new Date(latestByBenchmark[benchmarkId].requested_on)) {
            latestByBenchmark[benchmarkId] = run;
        }
    });

    // Clear existing badges
    $('#compliance-badges').empty();

    // Create a badge for each unique benchmark
    Object.values(latestByBenchmark).forEach(run => {
        const badge = createComplianceBadge(run, projectName, cloudPlatformType, accountId);
        $('#compliance-badges').append(badge);
    });
}

function createComplianceBadge(run, projectName, cloudPlatformType, accountId) {
    const benchmarkName = formatBenchmarkName(run.benchmark_id);
    const state = run.state.toLowerCase();

    // Determine badge style and icon based on state
    let badgeClass, icon;
    switch(state) {
        case 'benchmark succeeded':
            badgeClass = 'badge-success';
            icon = '<i class="fas fa-check-circle"></i>';
            break;
        case 'benchmark failed':
            badgeClass = 'badge-warning';
            icon = '<i class="fas fa-exclamation-triangle"></i>';
            break;
        case 'execution failed':
        case 'failed':
            badgeClass = 'badge-danger';
            icon = '<i class="fas fa-times-circle"></i>';
            break;
        case 'in progress':
            badgeClass = 'badge-info';
            icon = '<i class="fas fa-spinner fa-spin"></i>';
            break;
        case 'queued':
            badgeClass = 'badge-secondary';
            icon = '<i class="fas fa-clock"></i>';
            break;
        case 'timed out':
            badgeClass = 'badge-secondary';
            icon = '<i class="fas fa-hourglass-end"></i>';
            break;
        default:
            badgeClass = 'badge-secondary';
            icon = '<i class="fas fa-question-circle"></i>';
    }

    // Build logs URL
    const logsUrl = `/dashboard/projects/${projectName}/cloud_accounts/${cloudPlatformType}/${accountId}/logs/${run.request_id}`;

    // Create container wrapper for badge + logs icon (appears as single unit)
    const badgeContainer = $('<span>')
        .addClass('compliance-badge-container')
        .css({
            'display': 'inline-flex',
            'align-items': 'center',
            'margin': '0 5px 5px 0'
        });

    // Create main badge element (left part) - ONLY for viewing results, never navigates
    const badge = $('<span>')
        .addClass(`compliance-badge badge ${badgeClass}`)
        .css({
            'cursor': 'pointer',
            'border-top-right-radius': '0',
            'border-bottom-right-radius': '0',
            'margin': '0'
        })
        .attr('title', `Click to view results for ${benchmarkName}`)
        .attr('data-request-id', run.request_id)
        .html(`${icon} ${benchmarkName}`)
        .click(function() {
            // Handle all states
            if (state === 'benchmark succeeded' || state === 'benchmark failed') {
                loadBenchmarkResults(run.request_id, projectName, cloudPlatformType, accountId);
                // Highlight selected badge container
                $('.compliance-badge-container').removeClass('active-badge');
                $(this).parent().addClass('active-badge');
            } else if (state === 'execution failed' || state === 'failed' || state === 'timed out') {
                // Show no results message
                $('#benchmark-results-container').show();
                $('#benchmark-summary').empty();
                $('#benchmark-title').text('No Results Available');

                // Hide table and show error message
                $('#benchmark-table-container').hide();
                $('#benchmark-error-message').html(
                    '<p class="text-muted text-center">Execution failed before completion. No benchmark results available. Check logs for details.</p>'
                ).show();

                // Highlight selected badge container
                $('.compliance-badge-container').removeClass('active-badge');
                $(this).parent().addClass('active-badge');
            } else {
                // For in-progress or queued - go to logs
                window.location.href = logsUrl;
            }
        });

    // Create logs button (right part - suffix) - ALWAYS navigates to logs
    const logsButton = $('<span>')
        .addClass('badge')
        .css({
            'cursor': 'pointer',
            'border-top-left-radius': '0',
            'border-bottom-left-radius': '0',
            'border-left': '1px solid rgba(0,0,0,0.15)',
            'margin-left': '-6px',
            'padding': '6px 8px',
            'display': 'inline-flex',
            'align-items': 'center',
            'font-size': '0.9rem',
            'line-height': '1',
            'background-color': '#6c757d',
            'color': 'white'
        })
        .attr('title', 'View logs')
        .html('<i class="fas fa-file-alt"></i>')
        .click(function() {
            window.location.href = logsUrl;
        });

    // Assemble the container
    badgeContainer.append(badge);
    badgeContainer.append(logsButton);

    return badgeContainer;
}

function loadBenchmarkResults(requestId, projectName, cloudPlatformType, accountId) {
    selectedRequestId = requestId;

    // Show loading state
    $('#benchmark-results-container').hide();
    $('#compliance-loading').show();

    const apiUrl = `/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatformType}/${accountId}/benchmark_results/${requestId}`;

    $.ajax({
        url: apiUrl,
        method: 'GET',
        success: function(data) {
            $('#compliance-loading').hide();
            currentBenchmarkData = data;
            renderBenchmarkResults(data);
            $('#benchmark-results-container').show();
        },
        error: function(xhr) {
            $('#compliance-loading').hide();
            $('#benchmark-results-container').show();
            $('#benchmark-summary').empty();
            $('#benchmark-title').text('Error Loading Results');

            let errorMsg = 'Unknown error';
            if (xhr.status === 404) {
                errorMsg = 'Benchmark results not found. The results may have been archived or deleted.';
            } else if (xhr.responseJSON?.error) {
                errorMsg = xhr.responseJSON.error;
            } else if (xhr.statusText) {
                errorMsg = xhr.statusText;
            }

            // Hide table and show error message
            $('#benchmark-table-container').hide();
            $('#benchmark-error-message').html(
                '<div class="alert alert-danger"><i class="fas fa-exclamation-triangle"></i> ' +
                errorMsg +
                '</div>'
            ).show();
        }
    });
}

function renderBenchmarkResults(data) {
    // Hide error message and show table
    $('#benchmark-error-message').hide();
    $('#benchmark-table-container').show();

    // Render summary stats
    renderSummaryStats(data.summary);

    // Set benchmark title
    $('#benchmark-title').text(data.benchmark_title || 'Compliance Controls');

    // Prepare controls data - combine failed and all controls
    const allControls = prepareControlsData(data);

    // Render controls table
    populateControlsTable(allControls);
}

function renderSummaryStats(summary) {
    $('#benchmark-summary').empty();

    // Set flexbox styling for even distribution
    $('#benchmark-summary').css({
        'display': 'flex',
        'gap': '10px',
        'flex-wrap': 'wrap'
    });

    // Compliance Score Card
    const scoreClass = summary.compliance_score >= 80 ? 'success' :
                      summary.compliance_score >= 50 ? 'warning' : 'danger';

    $('#benchmark-summary').append(`
        <div style="flex: 1; min-width: 150px;">
            <div class="small-box bg-${scoreClass}">
                <div class="inner">
                    <h3>${summary.compliance_score}%</h3>
                    <p>Compliance Score</p>
                </div>
                <div class="icon">
                    <i class="fas fa-chart-pie"></i>
                </div>
            </div>
        </div>
    `);

    // Status breakdown cards
    const statuses = [
        { key: 'alarm', label: 'Failed', icon: 'exclamation-triangle', color: 'danger' },
        { key: 'ok', label: 'Passed', icon: 'check-circle', color: 'success' },
        { key: 'error', label: 'Errors', icon: 'times-circle', color: 'warning' },
        { key: 'skip', label: 'Skipped', icon: 'forward', color: 'secondary' }
    ];

    statuses.forEach(status => {
        $('#benchmark-summary').append(`
            <div style="flex: 1; min-width: 150px;">
                <div class="small-box bg-${status.color}">
                    <div class="inner">
                        <h3>${summary[status.key]}</h3>
                        <p>${status.label}</p>
                    </div>
                    <div class="icon">
                        <i class="fas fa-${status.icon}"></i>
                    </div>
                </div>
            </div>
        `);
    });
}

function prepareControlsData(data) {
    // Backend now returns all controls (both passed and failed)
    const controls = data.failed_controls.map(control => ({
        status: control.status,  // Backend now sends status: 'alarm', 'ok', 'skip', etc.
        control_id: control.control_id,
        title: control.title,
        description: control.description,
        service: control.service,
        article: control.article,
        failed_count: control.total_failed,
        ok_count: control.ok_count || 0,
        skip_count: control.skip_count || 0,
        affected_resources: control.affected_resources || []
    }));

    // Sort controls: failed first, then errors, then passed, then skipped
    const statusOrder = { 'alarm': 1, 'error': 2, 'ok': 3, 'skip': 4, 'info': 5 };
    controls.sort((a, b) => {
        const orderA = statusOrder[a.status] || 999;
        const orderB = statusOrder[b.status] || 999;
        return orderA - orderB;
    });

    return controls;
}

function populateControlsTable(controls) {
    // Destroy existing DataTable if it exists
    if ($.fn.DataTable.isDataTable('#benchmark-controls-table')) {
        $('#benchmark-controls-table').DataTable().destroy();
    }

    $('#benchmark-controls-table tbody').empty();

    controls.forEach(control => {
        const statusBadge = getControlStatusBadge(control.status, control.failed_count);

        // Show resource counts based on status
        let resourcesText = '';
        if (control.failed_count > 0) {
            resourcesText = `<span class="badge badge-danger">${control.failed_count} Failed</span>`;
        } else if (control.ok_count > 0) {
            resourcesText = `<span class="badge badge-success">${control.ok_count} Passed</span>`;
        } else if (control.skip_count > 0) {
            resourcesText = `<span class="badge badge-secondary">${control.skip_count} Skipped</span>`;
        } else {
            resourcesText = `<span class="badge badge-info">0</span>`;
        }

        // Add row with data attribute for expandable details
        const row = $('<tr>')
            .css('cursor', control.affected_resources.length > 0 ? 'pointer' : 'default')
            .attr('data-control-id', control.control_id)
            .append(`<td>${statusBadge}</td>`)
            .append(`<td>${control.title}</td>`)
            .append(`<td>${control.service}</td>`)
            .append(`<td>${resourcesText}</td>`)
            .append(`<td>${control.article}</td>`);

        // Make row clickable if there are affected resources
        if (control.affected_resources.length > 0) {
            row.click(function() {
                toggleResourceDetails(this, control);
            });
        }

        $('#benchmark-controls-table tbody').append(row);
    });

    // Initialize DataTable with export buttons
    $('#benchmark-controls-table').DataTable({
        responsive: false,
        pageLength: 25,
        order: [[0, 'desc']], // Sort by status (failures first)
        dom: 'Bfrtip',
        buttons: [
            {
                extend: 'csv',
                text: '<i class="fas fa-file-csv"></i> CSV',
                className: 'btn btn-sm btn-primary',
                title: 'Compliance Controls',
                exportOptions: {
                    columns: [0, 1, 2, 3, 4]
                }
            },
            {
                extend: 'excel',
                text: '<i class="fas fa-file-excel"></i> Excel',
                className: 'btn btn-sm btn-success',
                title: 'Compliance Controls',
                exportOptions: {
                    columns: [0, 1, 2, 3, 4]
                }
            }
        ],
        language: {
            search: 'Search controls:'
        }
    });
}

function getControlStatusBadge(status, failedCount) {
    if (failedCount > 0) {
        return '<span class="badge badge-danger"><i class="fas fa-exclamation-triangle"></i> ALARM</span>';
    } else {
        return '<span class="badge badge-success"><i class="fas fa-check-circle"></i> OK</span>';
    }
}

function toggleResourceDetails(row, control) {
    const $row = $(row);

    // Check if this row already has details expanded
    if ($row.hasClass('details-open')) {
        // Close details: remove next row and remove marker class
        $row.next('.details-row').remove();
        $row.removeClass('details-open');
    } else {
        // Open details: add marker class and insert details row
        $row.addClass('details-open');
        const detailsHtml = renderResourceDetails(control);
        const detailsRow = $('<tr>')
            .addClass('details-row')
            .append(`<td colspan="5" style="background-color: #f4f4f4; padding: 15px;">${detailsHtml}</td>`);

        // Insert after clicked row
        $row.after(detailsRow);
    }
}

function renderResourceDetails(control) {
    let html = `
        <div class="resource-details">
            <h6><i class="fas fa-info-circle"></i> Control Details</h6>
            <p><strong>Description:</strong> ${control.description || 'No description available'}</p>
            <h6><i class="fas fa-server"></i> Affected Resources (${control.affected_resources.length})</h6>
    `;

    if (control.affected_resources.length > 0) {
        html += '<ul class="list-unstyled">';
        control.affected_resources.forEach(resource => {
            const statusIcon = resource.status === 'alarm' ?
                '<i class="fas fa-exclamation-triangle text-danger"></i>' :
                '<i class="fas fa-times-circle text-warning"></i>';
            html += `
                <li style="margin-bottom: 10px; padding: 8px; background: white; border-left: 3px solid #dc3545;">
                    ${statusIcon} <strong>${resource.resource}</strong><br>
                    <small class="text-muted">${resource.reason}</small>
                </li>
            `;
        });
        html += '</ul>';
    } else {
        html += '<p class="text-muted">No affected resources found.</p>';
    }

    html += '</div>';
    return html;
}

function getComplianceStatusBadge(state) {
    const badges = {
        'benchmark succeeded': '<span class="badge badge-success"><i class="fas fa-check-circle"></i> Benchmark Succeeded</span>',
        'benchmark failed': '<span class="badge badge-warning"><i class="fas fa-exclamation-triangle"></i> Benchmark Failed</span>',
        'execution failed': '<span class="badge badge-danger"><i class="fas fa-times-circle"></i> Execution Failed</span>',
        'in progress': '<span class="badge badge-info"><i class="fas fa-spinner fa-spin"></i> In Progress</span>',
        'queued': '<span class="badge badge-secondary"><i class="fas fa-clock"></i> Queued</span>',
        'timed out': '<span class="badge badge-secondary"><i class="fas fa-hourglass-end"></i> Timed Out</span>'
    };

    return badges[state.toLowerCase()] || `<span class="badge badge-secondary">${state}</span>`;
}

// Format benchmark_id: replace underscores with spaces, capitalize words
function formatBenchmarkName(benchmarkId) {
    if (!benchmarkId) return 'N/A';
    return benchmarkId
        .replace(/_/g, ' ')
        .split(' ')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
}

// Format mod_type: replace underscores with spaces, capitalize words
function formatModType(modType) {
    if (!modType) return 'N/A';
    return modType
        .replace(/_/g, ' ')
        .split(' ')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
}
