$(function() {
    // Parse URL to get project, platform, and account info
    const projectName = Qubiva.url.projectName();
    const cloudPlatform = Qubiva.url.cloudPlatform();
    const accountId = Qubiva.url.accountId();

    // Initialize
    loadAlertConfiguration();

    // Event Listeners
    $('#refresh-account-details-btn').on('click', loadAlertConfiguration);

    function loadAlertConfiguration() {
        console.log('Loading alert configuration...');

        // Show loading state
        $('#alert-config-status').html('<span class="text-muted"><i class="fas fa-spinner fa-spin"></i> Loading...</span>');

        $.ajax({
            url: `/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatform}/${accountId}/alerts/configuration`,
            type: 'GET',
            success: function(data) {
                console.log('Alert configuration loaded:', data);
                if (data.configured) {
                    showConfiguredStatus(data);
                } else {
                    showNotConfiguredStatus();
                }
            },
            error: function(xhr, status, error) {
                console.error('Error loading alert configuration:', error);
                showErrorStatus(xhr.responseJSON?.detail || 'Failed to load configuration');
            }
        });
    }

    function showNotConfiguredStatus() {
        $('#alert-config-status').html(
            '<span class="text-muted">Not Configured (<a href="#" class="configure-link">configure</a>)</span>'
        );
    }

    function showConfiguredStatus(config) {
        const instructions = config.instructions || 'Use this configuration to create alerts in your cloud provider.';

        $('#alert-config-status').html(
            '<span class="text-success"><i class="fas fa-check-circle"></i> Configured ' +
            '(<a href="#" class="remove-link">remove</a>, <a href="#" class="validate-link">validate</a>)</span><br>' +
            `<small class="text-muted">${instructions}</small>`
        );
    }

    function showErrorStatus(errorMessage) {
        // Clean up error message - show only the meaningful part
        let cleanError = errorMessage;
        if (errorMessage.includes(':')) {
            cleanError = errorMessage.split(':').pop().trim();
        }
        // Limit length
        if (cleanError.length > 50) {
            cleanError = cleanError.substring(0, 50) + '...';
        }

        $('#alert-config-status').html(
            '<span class="text-danger"><i class="fas fa-exclamation-circle"></i> Failed</span> ' +
            `<small class="text-muted">${cleanError}</small> ` +
            '<a href="#" class="configure-link" style="margin-left: 5px;"><i class="fas fa-redo"></i> Retry</a>'
        );
    }

    function showConfigureModal(e) {
        e.preventDefault();

        // Show only relevant resource based on cloud platform
        const resourcesList = $('#alert-config-resources-list');
        resourcesList.empty();

        if (cloudPlatform.toLowerCase() === 'aws') {
            resourcesList.html('<p><strong>AWS:</strong> SNS Topic with webhook subscription will be created.</p>');
        } else if (cloudPlatform.toLowerCase() === 'azure') {
            resourcesList.html('<p><strong>Azure:</strong> Action Group with webhook receiver will be created.</p>');
        } else if (cloudPlatform.toLowerCase() === 'gcp') {
            resourcesList.html('<p><strong>GCP:</strong> Notification Channel with webhook will be created.</p>');
        }

        $('#alertConfigModal').modal('show');
    }

    function configureAlerts() {
        console.log('Configuring alerts...');

        // Disable button and show loading
        const btn = $('#confirm-configure-alerts-btn');
        btn.prop('disabled', true).html('<i class="fas fa-spinner fa-spin"></i> Configuring...');

        $.ajax({
            url: `/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatform}/${accountId}/alerts/configure`,
            type: 'POST',
            success: function(data) {
                console.log('Alerts configured successfully:', data);
                $('#alertConfigModal').modal('hide');
                toastr.success('Alerts configured successfully!');
                loadAlertConfiguration(); // Reload to show configured state

                // Reset button
                btn.prop('disabled', false).html('<i class="fas fa-bell"></i> Configure');
            },
            error: function(xhr, status, error) {
                console.error('Error configuring alerts:', error);
                const errorMsg = xhr.responseJSON?.detail || error;
                toastr.error(`Failed to configure alerts: ${errorMsg}`);

                // Reset button
                btn.prop('disabled', false).html('<i class="fas fa-bell"></i> Configure');

                // Close modal and reload status (will show not configured or previous state)
                $('#alertConfigModal').modal('hide');
                loadAlertConfiguration();
            }
        });
    }

    function showRemoveModal(e) {
        e.preventDefault();
        $('#alertRemoveModal').modal('show');
    }

    function confirmRemoveConfiguration() {
        console.log('Removing alert configuration...');

        // Disable button and show loading
        const btn = $('#confirm-remove-alerts-btn');
        btn.prop('disabled', true).html('<i class="fas fa-spinner fa-spin"></i> Removing...');

        $.ajax({
            url: `/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatform}/${accountId}/alerts/configure`,
            type: 'DELETE',
            success: function(data) {
                console.log('Alert configuration removed');
                $('#alertRemoveModal').modal('hide');
                toastr.success('Alert configuration removed successfully');
                loadAlertConfiguration(); // Reload to show not configured state

                // Reset button
                btn.prop('disabled', false).html('Remove');
            },
            error: function(xhr, status, error) {
                console.error('Error removing configuration:', error);
                const errorMsg = xhr.responseJSON?.detail || error;
                toastr.error(`Failed to remove configuration: ${errorMsg}`);

                // Reset button
                btn.prop('disabled', false).html('Remove');
            }
        });
    }

    function validateConfiguration(e) {
        e.preventDefault();

        console.log('Validating alert configuration...');

        // Show loading in link
        $('.validate-link').html('<i class="fas fa-spinner fa-spin"></i> validating...');

        $.ajax({
            url: `/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatform}/${accountId}/alerts/validate`,
            type: 'POST',
            success: function(data) {
                console.log('Validation result:', data);

                if (data.valid) {
                    toastr.success(data.message || 'Alert configuration is valid');
                } else {
                    toastr.warning(data.message || 'Alert configuration is invalid');
                }

                loadAlertConfiguration(); // Reload to show updated state
            },
            error: function(xhr, status, error) {
                console.error('Error validating configuration:', error);
                const errorMsg = xhr.responseJSON?.detail || error;
                toastr.error(`Validation failed: ${errorMsg}`);
                loadAlertConfiguration(); // Reload
            }
        });
    }

    // Event handlers
    $(document).on('click', '.configure-link', showConfigureModal);
    $(document).on('click', '.remove-link', showRemoveModal);
    $(document).on('click', '.validate-link', validateConfiguration);
    $('#confirm-configure-alerts-btn').on('click', configureAlerts);
    $('#confirm-remove-alerts-btn').on('click', confirmRemoveConfiguration);
});
