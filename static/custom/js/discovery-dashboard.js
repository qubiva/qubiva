/**
 * Discovery Dashboard JavaScript - UPDATED
 * Added: Cost breakdown table, tag badges, download buttons, historical placeholder
 */

window.dashboardCharts = window.dashboardCharts || {
  costPie: null,
  resourceDonut: null,
  regionBar: null,
  costTrend: null
};

/**
 * Initialize dashboard on page load
 */
$(document).ready(function() {
    // Load dashboard data
    loadDashboard();

    // Refresh button handler
    $('#refresh-dashboard-btn').click(function() {
        loadDashboard();
    });
});

/**
 * Load dashboard data from API
 */
function loadDashboard() {
    // Show loading state
    $('#dashboard-loading').show();
    $('#dashboard-no-data').hide();
    $('#dashboard-content').hide();

    try {
        const projectName = Qubiva.url.projectName();
        const cloudPlatformType = Qubiva.url.cloudPlatform();
        const accountId = Qubiva.url.accountId();

        if (!projectName || !cloudPlatformType || !accountId) {
            $('#dashboard-loading').hide();
            $('#dashboard-no-data').show();
            console.error('Missing path segments:', { projectName, cloudPlatformType, accountId });
            return;
        }

        const apiUrl = `/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatformType}/${accountId}/dashboard`;
        $.ajax({
            url: apiUrl,
            method: 'GET',
            success: function(data) {
                renderDashboard(data);
            },
            error: function(xhr) {
                handleDashboardError(xhr);
            }
        });
    } catch (e) {
        $('#dashboard-loading').hide();
        $('#dashboard-no-data').show();
        console.error('loadDashboard failed:', e);
    }
}

function getCtxOrNull(id) {
  const el = document.getElementById(id);
  return el ? el.getContext('2d') : null;
}

/**
 * Render dashboard with data
 */
function renderDashboard(data) {
    $('#dashboard-loading').hide();
    $('#dashboard-content').show();

    populateSummary(data.summary, data.discovered_at);

    if (data.insights && data.insights.recommendations && data.insights.recommendations.length > 0) {
        populateInsights(data.insights);
    }

    renderCharts(data.chart_data, data.discovery_history);

    populateResourceTable(data.resources);
    
    populateCostTable(data.summary);
}

/**
 * Populate summary info boxes
 */
function populateSummary(summary, discoveredAt) {
    $('#summary-resources').text(summary.total_resources.toLocaleString());
    $('#summary-cost').text(summary.total_cost.toFixed(2));
    
    if (summary.tagging) {
        $('#summary-tagging').text(summary.tagging.compliance_pct + '%');
    }

    const date = new Date(discoveredAt);
    const now = new Date();
    const diffMs = now - date;
    const diffSecs = Math.floor(diffMs / 1000);
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);
    const diffMonths = Math.floor(diffDays / 30);

    let timeAgo;
    if (diffSecs < 60) {
        timeAgo = `${diffSecs}s ago`;
    } else if (diffMins < 60) {
        timeAgo = `${diffMins}m ago`;
    } else if (diffHours < 24) {
        timeAgo = `${diffHours}h ago`;
    } else if (diffDays < 30) {
        timeAgo = `${diffDays}d ago`;
    } else {
        timeAgo = `${diffMonths}M ago`;
    }

    $('#summary-date').text(timeAgo);
}

/**
 * Populate insights section
 */
function populateInsights(insights) {
    $('#insights-section').show();
    const content = $('#insights-content');
    content.empty();

    // Show anomalies as alerts
    if (insights.anomalies) {
        const costAnomalies = insights.anomalies.cost_anomalies || [];
        const resourceAnomalies = insights.anomalies.resource_anomalies || [];

        [...costAnomalies, ...resourceAnomalies].forEach(anomaly => {
            const badge = anomaly.severity === 'severe' ? 'badge-danger' : 'badge-warning';
            const alertType = anomaly.severity === 'severe' ? 'danger' : 'warning';
            content.append(`
                <div class="alert alert-${alertType} alert-dismissible">
                    <button type="button" class="close" data-dismiss="alert">&times;</button>
                    <span class="badge ${badge}">${anomaly.severity.toUpperCase()}</span>
                    ${anomaly.message}
                </div>
            `);
        });
    }

    // Show recommendations as professional cards/badges
    if (insights.recommendations && insights.recommendations.length > 0) {
        // Determine overall status
        const hasIssues = insights.anomalies && 
            ((insights.anomalies.cost_anomalies && insights.anomalies.cost_anomalies.length > 0) ||
             (insights.anomalies.resource_anomalies && insights.anomalies.resource_anomalies.length > 0));
        
        insights.recommendations.forEach(rec => {
            // Determine card type based on icon
            let cardClass = 'info';
            let icon = 'fa-info-circle';
            
            if (rec.includes('✅')) {
                cardClass = 'success';
                icon = 'fa-check-circle';
            } else if (rec.includes('⚠️')) {
                cardClass = 'warning';
                icon = 'fa-exclamation-triangle';
            } else if (rec.includes('📈') || rec.includes('📉')) {
                cardClass = 'info';
                icon = 'fa-chart-line';
            } else if (rec.includes('🔮')) {
                cardClass = 'primary';
                icon = 'fa-crystal-ball';
            } else if (rec.includes('💡')) {
                cardClass = 'info';
                icon = 'fa-lightbulb';
            }
            
            // Remove emoji from text (we'll use FontAwesome icons instead)
            const cleanText = rec.replace(/[✅⚠️📈📉🔮💡]/g, '').trim();
            
            content.append(`
                <div class="callout callout-${cardClass} mb-2">
                    <h5><i class="fas ${icon}"></i> ${cleanText}</h5>
                </div>
            `);
        });
    }
}

/**
 * Render all charts
 */
function renderCharts(chartData, discoveryHistory) {
    Object.keys(dashboardCharts).forEach(key => {
        if (dashboardCharts[key]) {
            dashboardCharts[key].destroy();
        }
    });

    if (chartData.cost_pie) {
        dashboardCharts.costPie = renderPieChart('cost-pie-chart', chartData.cost_pie);
    }

    if (chartData.resource_donut) {
        dashboardCharts.resourceDonut = renderDonutChart('resource-donut-chart', chartData.resource_donut);
    }

    if (chartData.region_bar) {
        dashboardCharts.regionBar = renderBarChart('region-bar-chart', chartData.region_bar);
    }

    // Show historical chart or placeholder
    if (chartData.cost_trend_line && discoveryHistory && discoveryHistory.length >= 2) {
        $('#cost-trend-chart').show();
        $('#historical-placeholder').hide();
        dashboardCharts.costTrend = renderLineChart('cost-trend-chart', chartData.cost_trend_line);
    } else {
        $('#cost-trend-chart').hide();
        $('#historical-placeholder').show();
    }
}

/**
 * Render pie chart
 */
function renderPieChart(canvasId, data) {
    const ctx = getCtxOrNull(canvasId);
    if (!ctx) return null;
    return new Chart(ctx, {
        type: 'pie',
        data: data,
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right',
                    labels: { boxWidth: 12, font: { size: 11 } }
                }
            }
        }
    });
}

/**
 * Render donut chart
 */
function renderDonutChart(canvasId, data) {
    const ctx = getCtxOrNull(canvasId);
    if (!ctx) return null;
    return new Chart(ctx, {
        type: 'doughnut',
        data: data,
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right',
                    labels: { boxWidth: 12, font: { size: 11 } }
                }
            }
        }
    });
}

/**
 * Render bar chart
 */
function renderBarChart(canvasId, data) {
    const ctx = getCtxOrNull(canvasId);
    if (!ctx) return null;
    return new Chart(ctx, {
        type: 'bar',
        data: data,
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: { y: { beginAtZero: true } }
        }
    });
}

/**
 * Render line chart
 */
function renderLineChart(canvasId, data) {
    const ctx = getCtxOrNull(canvasId);
    if (!ctx) return null;
    return new Chart(ctx, {
        type: 'line',
        data: data,
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: true } },
            scales: { y: { beginAtZero: true } }
        }
    });
}

/**
 * Populate resource table with DataTables and download buttons
 */
function populateResourceTable(resources) {
    if ($.fn.DataTable.isDataTable('#resources-table')) {
        $('#resources-table').DataTable().destroy();
    }

    $('#resources-table tbody').empty();

    resources.forEach(resource => {
        let tagsBadges = '';
        if (Object.keys(resource.tags).length > 0) {
            tagsBadges = Object.entries(resource.tags)
                .map(([k, v]) => `<span class="badge badge-secondary mr-1">${k}: ${v}</span>`)
                .join('');
        } else {
            tagsBadges = '<span class="badge badge-light">No tags</span>';
        }
        
        $('#resources-table tbody').append(`
            <tr>
                <td>${resource.resource_type}</td>
                <td>${resource.resource_name}</td>
                <td>${resource.region}</td>
                <td>${tagsBadges}</td>
            </tr>
        `);
    });

    // Initialize DataTable with download buttons
    $('#resources-table').DataTable({
        responsive: false,
        pageLength: 25,
        order: [[0, 'asc']],
        dom: 'Bfrtip',
        buttons: [
            {
                extend: 'csv',
                text: '<i class="fas fa-file-csv"></i> CSV',
                className: 'btn btn-sm btn-primary',
                exportOptions: {
                    columns: [0, 1, 2]  // Exclude tags column (has HTML)
                }
            },
            {
                extend: 'excel',
                text: '<i class="fas fa-file-excel"></i> Excel',
                className: 'btn btn-sm btn-success',
                exportOptions: {
                    columns: [0, 1, 2]
                }
            }
        ],
        language: {
            search: 'Search resources:'
        }
    });
}

/**
 * Populate cost breakdown table
 */
function populateCostTable(summary) {
    if ($.fn.DataTable.isDataTable('#costs-table')) {
        $('#costs-table').DataTable().destroy();
    }

    $('#costs-table tbody').empty();

    const costByService = summary.by_service_cost || {};
    const resourcesByType = summary.by_type || {};
    const totalCost = summary.total_cost || 0;

    // Create rows
    Object.entries(costByService).forEach(([service, cost]) => {
        const percentage = totalCost > 0 ? ((cost / totalCost) * 100).toFixed(1) : '0.0';
        
        // Try to match service to resource count (rough estimate)
        const resourceCount = resourcesByType[service] || '-';
        
        $('#costs-table tbody').append(`
            <tr>
                <td>${service}</td>
                <td>$${cost.toFixed(2)}</td>
                <td>${percentage}%</td>
            </tr>
        `);
    });

    // Initialize DataTable with download buttons
    $('#costs-table').DataTable({
        responsive: false,
        pageLength: 25,
        order: [[1, 'desc']],  // Sort by cost descending
        dom: 'Bfrtip',
        buttons: [
            {
                extend: 'csv',
                text: '<i class="fas fa-file-csv"></i> CSV',
                className: 'btn btn-sm btn-primary'
            },
            {
                extend: 'excel',
                text: '<i class="fas fa-file-excel"></i> Excel',
                className: 'btn btn-sm btn-success'
            }
        ],
        language: {
            search: 'Search services:'
        }
    });
}

/**
 * Handle dashboard errors
 */
function handleDashboardError(xhr) {
    $('#dashboard-loading').hide();

    if (xhr.status === 404) {
        $('#dashboard-no-data').show();
    } else {
        toastr.error('Failed to load dashboard data. Please try again.', 'Error');
        console.error('Dashboard error:', xhr);
    }
}