$(document).ready(function() {
    let templatesData = {};
    let currentView = 'grid';
    let itemsPerPage = 6;
    let currentPage = 1;
    let currentFilter = '';
    let selectedTemplate = null;

    const projectName = Qubiva.url.projectName();
    const cloudPlatform = Qubiva.url.cloudPlatform();
    const accountId = Qubiva.url.accountId();

    function getTemplateIdFromUrl() {
        const lastPart = Qubiva.url.lastSegment();
        return lastPart !== 'insights' ? lastPart : null;
    }

    function getFilteredTemplates() {
        return Object.entries(templatesData).filter(([id, template]) => {
            const searchTerm = currentFilter.toLowerCase();
            const templatePlatform = template.cloud_platform || template.cloudPlatform || template.id.split('_')[0];
            
            return templatePlatform.toLowerCase() === cloudPlatform.toLowerCase() && 
                   (template.name.toLowerCase().includes(searchTerm) ||
                    template.description.toLowerCase().includes(searchTerm));
        });
    }

    // New function to update URL
    function updateUrlWithTemplate(templateId) {
        const baseUrl = `/dashboard/projects/${projectName}/cloud_accounts/${cloudPlatform}/${accountId}/insights`;
        const newUrl = templateId ? `${baseUrl}/${templateId}` : baseUrl;
        history.pushState({templateId}, '', newUrl);
    }

    function fetchTemplates() {
        $('#templates-wrapper').html('<div class="text-center w-100 my-5">Loading...</div>');
        $.ajax({
            url: '/api/v1/insights/templates',
            type: 'GET',
            success: function(data) {
                templatesData = data.templates.reduce((acc, template) => {
                    acc[template.id] = template;
                    return acc;
                }, {});
                renderTemplates();
                renderPagination();

                // Check URL for template ID after loading templates
                const urlTemplateId = getTemplateIdFromUrl();
                if (urlTemplateId && templatesData[urlTemplateId]) {
                    showTemplateModal(urlTemplateId, false);
                }
            },
            error: function(error) {
                console.error('Error fetching templates:', error);
                $('#templates-wrapper').html('<p>No templates found!</p>');
            }
        });
    }

    function renderTemplates() {
        console.log('Current cloud platform:', cloudPlatform);
        console.log('Current filter:', currentFilter);
    
        $('#templates-wrapper').empty();
    
        const filteredTemplates = getFilteredTemplates();
        const start = (currentPage - 1) * itemsPerPage;
        const end = start + itemsPerPage;
        const paginatedTemplates = filteredTemplates.slice(start, end);
    
        if (paginatedTemplates.length === 0) {
            $('#templates-wrapper').append('<p>No templates found!</p>');
            return;
        }
    
        if (currentView === 'grid') {
            paginatedTemplates.forEach(([id, template]) => {
                $('#templates-wrapper').append(`
                    <div class="col-md-4 mb-3">
                        <div class="card h-100 template-card" data-template-id="${id}">
                            <div class="card-body">
                                <h5 class="card-title mb-2">${template.name}</h5>
                                <p class="card-description">${template.description}</p>
                                <div class="mt-auto">
                                    <small class="text-muted">
                                        <i class="fas fa-code-branch me-1"></i>
                                        Type: ${template.type === 'query' ? 'Query' : 'Benchmark'}
                                    </small>
                                </div>
                            </div>
                        </div>
                    </div>
                `);
            });
        } else {
            $('#templates-wrapper').append('<div class="col-12"><ul class="list-group"></ul></div>');
            paginatedTemplates.forEach(([id, template]) => {
                $('.list-group').append(`
                    <li class="list-group-item template-item" data-template-id="${id}">
                        <div>
                            <h6 class="mb-0">${template.name}</h6>
                            <p class="description-text mb-1">${template.description}</p>
                            <small class="text-muted">
                                <i class="fas fa-microchip me-1"></i>
                                Type: ${template.type === 'query' ? 'Query' : 'Benchmark'}
                            </small>
                        </div>
                    </li>
                `);
            });
        }
    
        $('.template-card, .template-item').hover(
            function() { $(this).addClass('hover-effect'); },
            function() { $(this).removeClass('hover-effect'); }
        );
    }

    function renderPagination() {
        $('#pagination').empty();
        const filteredTemplates = getFilteredTemplates();
        const totalPages = Math.ceil(filteredTemplates.length / itemsPerPage);
    
        for (let i = 1; i <= totalPages; i++) {
            $('#pagination').append(`
                <li class="page-item ${i === currentPage ? 'active' : ''}">
                    <a class="page-link" href="#">${i}</a>
                    </li>
            `);
        }
    }

    async function showTemplateModal(templateId, updateUrl = true) {
        if (window.statusRefreshInterval) {
            clearInterval(window.statusRefreshInterval);
        }

        if (!templatesData[templateId]) {
            console.error('Template not found:', templateId);
            return;
        }

        selectedTemplate = templatesData[templateId];
        const modal = $('#templateModal');

        $('#templateModalLabel').text(selectedTemplate.name);
        $('.template-type').text(selectedTemplate.type === 'query' ? 'Query' : 'Benchmark');
        $('.template-description').text(selectedTemplate.description);

        if (selectedTemplate.configuration?.query) {
            $('.query-section').removeClass('d-none')
                .find('.query-content').text(selectedTemplate.configuration.query);
        } else {
            $('.query-section').addClass('d-none');
        }

        setPlaceholderContent();
        $('#downloadReportBtn').hide();

        // Reset button state when opening modal for different template
        $('#runAnalysisBtn').prop('disabled', false).text('Run Analysis');

        // Hide any existing alerts
        $('.analysis-alert').removeClass('show').hide();

        if (updateUrl) {
            updateUrlWithTemplate(templateId);
        }

        modal.modal('show');
        await refreshInsightStatus(templateId);

        window.statusRefreshInterval = setInterval(async () => {
            // Only continue polling if this is still the selected template
            if (selectedTemplate && selectedTemplate.id === templateId) {
                const status = $('.metadata-item .metadata-info .metadata-value').eq(2).find('.badge').text();
                if (status === 'completed' || status === 'failed') {
                    clearInterval(window.statusRefreshInterval);
                } else {
                    await refreshInsightStatus(templateId);
                }
            } else {
                clearInterval(window.statusRefreshInterval);
            }
        }, 30000);
    }

    async function refreshInsightStatus(templateId) {
        try {
            const response = await silentFetch(
                `/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatform}/${accountId}/insights/${templateId}/`
            );
            const insight = await response.json();
            
            if (insight.status) {
                // Format status text - capitalize words
                const formattedStatus = insight.status.current_state
                    .split(' ')
                    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
                    .join(' ');

                $('.metadata-item .metadata-info .metadata-value').eq(2).html(`
                    <div>
                        <span class="badge ${getStatusBadgeClass(insight.status.current_state)}">${formattedStatus}</span>
                        ${insight.status.last_updated ? `<div>Last Updated: ${formatDate(insight.status.last_updated)}</div>` : ''}
                        ${insight.status.last_success ? `<div>Last Success: ${formatDate(insight.status.last_success)}</div>` : ''}
                        ${insight.status.last_error ? `<div class="text-danger">Error from previous execution: ${insight.status.last_error}</div>` : ''}
                    </div>
                `);
    
                if (insight.status.current_state === 'benchmark succeeded' ||
                    insight.status.current_state === 'benchmark failed' ||
                    insight.status.current_state === 'completed') {
                    await fetchInsightContent(templateId);
                } else {
                    // Clear any existing content if not completed
                    setPlaceholderContent();
                    $('#downloadReportBtn').hide();
                }
            } else {
                $('.metadata-item .metadata-info .metadata-value').eq(2).html(`
                    <div class="text-muted">Analysis hasn't been run yet</div>
                `);
                // Clear content area and hide download button
                setPlaceholderContent();
                $('#downloadReportBtn').hide();
            }
            
            updateRunButton(insight.status?.current_state || '');
            
        } catch (error) {
            console.error('Error fetching insight status:', error);
            $('.metadata-item .metadata-info .metadata-value').eq(2).html(`
                <div class="text-danger">Failed to fetch status information</div>
            `);
            updateRunButton('failed');
        }
    }

    function getStatusIconClass(status) {
        return {
            'benchmark succeeded': 'text-success',
            'benchmark failed': 'text-warning',
            'execution failed': 'text-danger',
            'running': 'text-primary',
            'queued': 'text-warning',
            'in progress': 'text-primary',
            'timed out': 'text-secondary'
        }[status] || 'text-secondary';
    }

    function updateRunButton(status) {
        const button = $('#runAnalysisBtn');
        const downloadButton = $('#downloadReportBtn');
        
        // Add 'in_progress' to the states where button should be disabled
        if (status === 'running' || status === 'queued' || status === 'in progress') {
            button.prop('disabled', true)
                .html('<span class="spinner-border spinner-border-sm me-2"></span>Analysis in Progress');
            downloadButton.hide();
            return;
        }
        
        switch(status) {
            case 'benchmark succeeded':
            case 'benchmark failed':
            case 'completed':
                button.prop('disabled', false).text('Re-run Analysis');
                downloadButton.show();
                break;
            case 'execution failed':
                button.prop('disabled', false).text('Run Analysis');
                downloadButton.hide();
                break;
            default:
                button.prop('disabled', false).text('Run Analysis');
                downloadButton.hide();
        }
    }

    function getStatusBadgeClass(status) {
        return {
            'benchmark succeeded': 'bg-success',
            'benchmark failed': 'bg-warning',
            'completed': 'bg-success',
            'execution failed': 'bg-danger',
            'running': 'bg-primary',
            'queued': 'bg-info',
            'in progress': 'bg-info',
            'timed out': 'bg-secondary'
        }[status] || 'bg-secondary';
    }

    function formatDate(dateString) {
        return new Date(dateString).toLocaleString();
    }

    async function fetchInsightContent(templateId) {
        try {
            const response = await silentFetch(`/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatform}/${accountId}/insights/${templateId}/content`);

            if (response.ok) {
                const data = await response.json();

                if (data.url) {
                    $('#downloadReportBtn').show();
                    console.log('Download button shown - URL available:', data.url);
                } else {
                    $('#downloadReportBtn').hide();
                    console.log('Download button hidden - No URL in response');
                }
            } else {
                // If 404 or other error, hide download button
                $('#downloadReportBtn').hide();
                console.log('Download button hidden - Response not OK:', response.status);
            }
        } catch (error) {
            console.error("Error while fetching content:", error);
            $('#downloadReportBtn').hide();
        }
    }
    
    
    // Helper function to set placeholder content
    function setPlaceholderContent() {
        $('.markdown-content').html(`
            <div class="text-muted text-center p-4">
                <i class="fas fa-info-circle me-2"></i>
                No analysis results available. Run the analysis to see results here.
            </div>
        `);
    }
    

    async function triggerInsightAnalysis() {
        if (!selectedTemplate) return;

        const alertDiv = $('.analysis-alert');
        const alertMessage = alertDiv.find('.alert-message');
        const button = $('#runAnalysisBtn');

        try {
            // Immediately disable button and change text
            button.prop('disabled', true)
                .html('<span class="spinner-border spinner-border-sm me-2"></span>Analysis in Progress');

            const response = await fetch(
                `/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatform}/${accountId}/insights/${selectedTemplate.id}/trigger`,
                { method: 'POST' }
            );

            if (response.ok) {
                const data = await response.json();

                $('.metadata-item .metadata-info .metadata-value').eq(2).html(`
                    <div>
                        <span class="badge ${getStatusBadgeClass('queued')}">queued</span>
                        <div>Last Updated: ${formatDate(new Date())}</div>
                    </div>
                `);

                alertDiv.removeClass('alert-danger').addClass('alert-success show').fadeIn();
                alertMessage.html(`
                    <i class="fas fa-check-circle me-2"></i>
                    ${data.message || 'Analysis triggered successfully. Click refresh to check status.'}
                `);
                await refreshInsightStatus(selectedTemplate.id);
            } else {
                const errorData = await response.json();
                const errorMessage = errorData.detail || 'Failed to trigger analysis.';

                // Check if it's an OpenAI key error
                if (errorMessage.toLowerCase().includes('openai') && errorMessage.toLowerCase().includes('not found')) {
                    showOpenAIKeyModal();
                    // On error, enable the button and restore original text
                    button.prop('disabled', false).text('Run Analysis');
                    return;
                }

                throw new Error(errorMessage);
            }
        } catch (error) {
            console.error('Error:', error);
            // On error, enable the button and restore original text
            button.prop('disabled', false).text('Run Analysis');

            alertDiv.removeClass('alert-success').addClass('alert-danger show').fadeIn();
            alertMessage.html(`
                <i class="fas fa-exclamation-circle me-2"></i>
                ${error.message}
            `);
        }
    }

    function showOpenAIKeyModal() {
        const settingsUrl = `/dashboard/projects/${projectName}/settings`;

        // Create modal HTML if it doesn't exist
        if ($('#openaiKeyModal').length === 0) {
            const modalHtml = `
                <div class="modal fade" id="openaiKeyModal" tabindex="-1" aria-labelledby="openaiKeyModalLabel" aria-hidden="true">
                    <div class="modal-dialog modal-dialog-centered">
                        <div class="modal-content">
                            <div class="modal-header bg-warning text-dark">
                                <h5 class="modal-title" id="openaiKeyModalLabel">
                                    <i class="fas fa-exclamation-triangle me-2"></i>
                                    OpenAI API Key Required
                                </h5>
                                <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                            </div>
                            <div class="modal-body">
                                <p class="mb-3">
                                    <i class="fas fa-info-circle text-info me-2"></i>
                                    An OpenAI API key is required to run insight analysis. Please configure your API key in the project settings.
                                </p>
                                <div class="alert alert-info mb-0">
                                    <strong>How to configure:</strong>
                                    <ol class="mb-0 mt-2">
                                        <li>Go to Project Settings</li>
                                        <li>Navigate to the "Integrations" or "API Keys" section</li>
                                        <li>Add your OpenAI API key</li>
                                        <li>Save the settings</li>
                                    </ol>
                                </div>
                            </div>
                            <div class="modal-footer">
                                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                                <a href="${settingsUrl}" class="btn btn-primary">
                                    <i class="fas fa-cog me-2"></i>
                                    Go to Settings
                                </a>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            $('body').append(modalHtml);
        }

        // Show the modal
        const modal = new bootstrap.Modal(document.getElementById('openaiKeyModal'));
        modal.show();
    }    

    // Event Listeners
    $(document).on('click', '.page-link', function(e) {
        e.preventDefault();
        currentPage = parseInt($(this).text());
        renderTemplates();
        renderPagination();
    });

    $('#itemsPerPageSelect').on('change', function() {
        itemsPerPage = parseInt($(this).val());
        currentPage = 1;
        renderTemplates();
        renderPagination();
    });

    $('#template-search-box').on('keyup input', function() {
        currentFilter = $(this).val().toLowerCase();
        currentPage = 1;
        renderTemplates();
        renderPagination();
    });

    $('#template-search-form').on('submit', function(event) {
        event.preventDefault();
        fetchTemplates();
    });

    $('#listViewBtn, #gridViewBtn').on('click', function() {
        currentPage = 1;
        currentView = $(this).attr('id') === 'listViewBtn' ? 'list' : 'grid';
        $(this).addClass('active').siblings().removeClass('active');
        renderTemplates();
        renderPagination();
    });

    $(document).on('click', '.template-card, .template-item', function(e) {
        e.preventDefault();
        const templateId = $(this).data('template-id');
        showTemplateModal(templateId);
    });

    $('#runAnalysisBtn').on('click', triggerInsightAnalysis);

    $(document).on('click', '.refresh-results', function() {
        if (selectedTemplate) {
            refreshInsightStatus(selectedTemplate.id);
        }
    });

    $('#downloadReportBtn').on('click', async function() {
        if (!selectedTemplate) return;
        
        try {
            const response = await silentFetch(
                `/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatform}/${accountId}/insights/${selectedTemplate.id}/content`
            );
            const data = await response.json();
            
            if (data.url) {
                const link = document.createElement('a');
                link.href = data.url;
                link.download = `${selectedTemplate.name.toLowerCase().replace(/\s+/g, '_')}_insight.md`;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
            }
        } catch (error) {
            console.error('Error downloading report:', error);
            alert('Error downloading report');
        }
    });

    $('#templateModal').on('hidden.bs.modal', function() {
        $('.analysis-alert').removeClass('show').hide();
        updateUrlWithTemplate(null); // Remove template ID from URL
    });

    window.onpopstate = function(event) {
        const templateId = event.state?.templateId;
        if (templateId && templatesData[templateId]) {
            showTemplateModal(templateId, false);
        } else {
            $('#templateModal').modal('hide');
        }
    };

    fetchTemplates();
});