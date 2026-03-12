$(document).ready(function() {
    let credentialsData = {};  // Store fetched credentials data for filtering
    let currentView = 'grid';  // Default to grid view
    let itemsPerPage = 6;  // Default items per page
    let currentPage = 1;  // Current page
    let currentFilter = ''; // Current filter for search
    let deleteCredentialName = '';
    let platformFilter = '';

    $(document).on('click', '.delete-credential', function(e) {
        e.preventDefault();
        const credentialName = $(this).data('credential');
        console.log(`Clicked delete for credential: ${credentialName}`);
        showDeleteCredentialConfirmationModal(credentialName);
    });

    function showDeleteCredentialConfirmationModal(credentialName) {
        console.log(`Showing confirmation modal for: ${credentialName}`);
        deleteCredentialName = credentialName;

        $('#credentialNameDisplay').text(credentialName);
        $('#confirmationCredentialName').val('');
        $('#confirmCredentialIrreversibleAction').prop('checked', false);
        $('#confirmationCredentialError').addClass('d-none');
        $('#confirmCredentialDeleteBtn').prop('disabled', true);
        
        console.log("Attempting to show modal...");
        $('#deleteCredentialConfirmationModal').modal('show');
    }

    function showMessageModal(title, message) {
        $('#messageModalLabel').text(title);
        $('#messageModalBody').text(message);
        $('#messageModal').modal('show');
    }

    // Close button event for message modal
    $('#messageModal .close, #messageModal .btn-secondary').on('click', function() {
        $('#messageModal').modal('hide');
    });

    function fetchCredentials() {
        // Show loading indicator
        $('#credentials-wrapper').html('<div class="text-center w-100 my-5">Loading...</div>');
     
        const projectName = Qubiva.url.projectName();
        $.ajax({
            url: `/api/v1/projects/${encodeURIComponent(projectName)}/credentials`,
            type: 'GET',
            success: function(data) {
                credentialsData = data.credentials.reduce((acc, credential) => {
                    acc[credential.credential_name] = credential;
                    return acc;
                }, {});
                populatePlatformDropdown(data.credentials);
                renderCredentials();
                renderPagination();
            },
            error: function(error) {
                console.error('Error fetching credentials:', error);
                $('#credentials-wrapper').html('<div class="text-center text-muted py-5 w-100"><i class="fas fa-key fa-2x mb-3 d-block"></i>No credentials found</div>');
            }
        });
     }

    function populatePlatformDropdown(data) {
        // Get unique credential types, filter out null values, and sort
        const platforms = [...new Set(data.map(credential => {
            // Extract platform from credential_type or use a mapping
            if (credential.credential_type === 'external_certificate_authority' || credential.credential_type === 'key_pair') {
                return 'AWS';
            } else if (credential.credential_type === 'azure_service_principal') {
                return 'Azure';
            } else if (credential.credential_type === 'gcp_service_account') {
                return 'GCP';
            }
            return null;
        }))]
            .filter(platform => platform != null)
            .sort();
        
        $('#filterDropdown').empty().append('<option value="all">All Platforms</option>');
        platforms.forEach(platform => {
            $('#filterDropdown').append(`<option value="${platform}">${platform}</option>`);
        });
    }

    function deleteCredential(credentialName) {
        const projectName = Qubiva.url.projectName();
        const deleteUrl = `/api/v1/projects/${encodeURIComponent(projectName)}/credentials/${encodeURIComponent(credentialName)}`;

        $.ajax({
            url: deleteUrl,
            type: 'DELETE',
            success: function() {
                $('#deleteCredentialConfirmationModal').modal('hide');
                showMessageModal("Success", "Credential deleted successfully.");
                fetchCredentials(); // Refresh the list of credentials
            },
            error: function(error) {
                $('#deleteCredentialConfirmationModal').modal('hide');
                showMessageModal("Error", Qubiva.extractError(error, 'An error occurred while deleting the credential. Please try again.'));
            }
        });
    }

    function getCredentialDisplayInfo(credential) {
        let platform = 'Unknown';
        let type = credential.credential_type;
        
        if (credential.credential_type === 'external_certificate_authority') {
            platform = 'AWS';
            type = 'External Certificate Authority';
        } else if (credential.credential_type === 'key_pair') {
            platform = 'AWS';
            type = 'Access Key Pair';
        } else if (credential.credential_type === 'azure_service_principal') {
            platform = 'Azure';
            type = 'Service Principal';
        } else if (credential.credential_type === 'gcp_service_account') {
            platform = 'GCP';
            type = 'Service Account';
        }
        
        return { platform, type };
    }

    function renderCredentials() {
        $('#credentials-wrapper').empty(); // Clear the container first
        
        const filteredCredentials = Object.entries(credentialsData).filter(([credentialName, credential]) => {
            // For search text - match anywhere in the name
            const matchesSearch = credentialName.toLowerCase().includes(currentFilter.toLowerCase());
            
            // For platform filter
            const { platform } = getCredentialDisplayInfo(credential);
            const matchesPlatform = platformFilter === '' || platform === platformFilter;
            
            return matchesSearch && matchesPlatform;
        });
        
        const start = (currentPage - 1) * itemsPerPage;
        const end = start + itemsPerPage;
        const paginatedCredentials = filteredCredentials.slice(start, end);

        if (paginatedCredentials.length === 0) {
            $('#credentials-wrapper').append('<div class="text-center text-muted py-5 w-100"><i class="fas fa-key fa-2x mb-3 d-block"></i>No credentials found</div>');
            return;
        }

        if (currentView === 'grid') {
            paginatedCredentials.forEach(([credentialName, credential]) => {
                const { platform, type } = getCredentialDisplayInfo(credential);
                $('#credentials-wrapper').append(`
                    <div class="col-md-4 mb-3">
                        <div class="card h-100 d-flex flex-column credential-card">
                            <div class="card-body d-flex flex-column credential-card-body">
                                <div class="card-text">
                                    <div class="credential-title-container">
                                        <i class="fas fa-key credential-icon"></i>
                                        <h5 class="card-title credential-title">${credential.credential_name}</h5>
                                    </div>
                                    <div class="credential-platform-container">
                                        <i class="fas fa-cloud credential-icon"></i>
                                        <span class="credential-platform">${platform}</span>
                                    </div>
                                    <div class="credential-type-container">
                                        <i class="fas fa-tag credential-icon"></i>
                                        <span class="credential-type">${type}</span>
                                    </div>
                                </div>
                            </div>
                            <div class="credential-footer">
                                <a data-permission='["project_credential_edit"]' href="/dashboard/projects/${encodeURIComponent(Qubiva.url.projectName())}/credentials/${encodeURIComponent(credentialName)}/edit" class="btn btn-link text-primary p-0 credential-action">
                                    <i class="fas fa-edit"></i>
                                </a>
                                <a data-permission='["project_credential_delete"]' href="#" class="btn btn-link text-danger p-0 delete-credential credential-action" data-credential="${credentialName}">
                                    <i class="fas fa-trash-alt"></i>
                                </a>
                            </div>
                        </div>
                    </div>
                `);
            });
        } else {
            $('#credentials-wrapper').append('<div class="col-12"><ul class="list-group"></ul></div>');
            paginatedCredentials.forEach(([credentialName, credential]) => {
                const { platform, type } = getCredentialDisplayInfo(credential);
                $('.list-group').append(`
                    <li class="list-group-item d-flex justify-content-between align-items-center credential-list-item">
                        <div>
                            <div class="credential-title-container">
                                <i class="fas fa-key credential-icon"></i>
                                <span class="credential-title">${credential.credential_name}</span>
                            </div>
                            <div class="credential-platform-container">
                                <i class="fas fa-cloud credential-icon"></i>
                                <span class="credential-platform">${platform}</span>
                            </div>
                            <div class="credential-type-container">
                                <i class="fas fa-tag credential-icon"></i>
                                <span class="credential-type">${type}</span>
                            </div>
                        </div>
                        <div class="credential-actions-container">
                            <a data-permission='["project_credential_edit"]' href="/dashboard/projects/${encodeURIComponent(Qubiva.url.projectName())}/credentials/${encodeURIComponent(credentialName)}/edit" class="btn btn-link text-primary p-0 credential-action">
                                <i class="fas fa-edit"></i>
                            </a>
                            <a data-permission='["project_credential_delete"]' href="#" class="btn btn-link text-danger p-0 delete-credential credential-action" data-credential="${credentialName}">
                                <i class="fas fa-trash-alt"></i>
                            </a>
                        </div>
                    </li>
                `);
            });
        }

        $('.card, .list-group-item').hover(
            function() { $(this).addClass('hover-effect'); },
            function() { $(this).removeClass('hover-effect'); }
        );

        // Attach delete button click event
        $('.delete-credential').on('click', function(e) {
            e.preventDefault();
            const credentialName = $(this).data('credential');
            console.log(`Clicked delete for credential: ${credentialName}`);
            showDeleteCredentialConfirmationModal(credentialName);
        });
    }

    function renderPagination() {
        $('#pagination').empty();
        const totalItems = Object.keys(credentialsData).length;
        const totalPages = Math.ceil(totalItems / itemsPerPage);

        for (let i = 1; i <= totalPages; i++) {
            $('#pagination').append(`<li class="page-item ${i === currentPage ? 'active' : ''}">
                <a class="page-link" href="#">${i}</a>
            </li>`);
        }

        $('.page-link').on('click', function(e) {
            e.preventDefault();
            currentPage = parseInt($(this).text());
            renderCredentials();
            renderPagination();
        });
    }

    $('#itemsPerPageSelect').on('change', function() {
        itemsPerPage = parseInt($(this).val());
        currentPage = 1;
        renderCredentials();
        renderPagination();
    });

    $('#credential-search-box').on('keyup input', function() {
        currentPage = 1;
        currentFilter = $(this).val().toLowerCase();  // This updates search filter
        renderCredentials();
        renderPagination();
    });

    $('#credential-search-form').on('submit', function(event) {
        event.preventDefault();
        fetchCredentials();
    });

    $('#listViewBtn, #gridViewBtn').on('click', function() {
        currentPage = 1;
        currentView = $(this).attr('id') === 'listViewBtn' ? 'list' : 'grid';
        $(this).addClass('active').siblings().removeClass('active');
        renderCredentials();
        renderPagination();
    });

    $('#filterDropdown').on('change', function() {
        platformFilter = $(this).val() === 'all' ? '' : $(this).val();  // This updates platform filter
        currentPage = 1;
        renderCredentials();
        renderPagination();
    });

    fetchCredentials();

    $('#newCredentialBtn').on('click', function() {
        const projectName = Qubiva.url.projectName();
        if (!projectName) {
            console.error('Unable to determine project name from URL');
            return;
        }
        window.location.href = `/dashboard/projects/${encodeURIComponent(projectName)}/credentials/create`;
    });

    $('#confirmationCredentialName, #confirmCredentialIrreversibleAction').on('input change', function() {
        const inputName = $('#confirmationCredentialName').val();
        const isConfirmed = $('#confirmCredentialIrreversibleAction').is(':checked');

        if (inputName === deleteCredentialName && isConfirmed) {
            $('#confirmCredentialDeleteBtn').prop('disabled', false);
            $('#confirmationCredentialError').addClass('d-none');
        } else {
            $('#confirmCredentialDeleteBtn').prop('disabled', true);

            if (inputName !== deleteCredentialName) {
                $('#confirmationCredentialError').removeClass('d-none').text('Credential name does not match.');
            } else if (!isConfirmed) {
                $('#confirmationCredentialError').removeClass('d-none').text('Please confirm that the action is irreversible.');
            } else {
                $('#confirmationCredentialError').addClass('d-none');
            }
        }
    });

    $('#confirmCredentialDeleteBtn').on('click', function() {
        deleteCredential(deleteCredentialName);
    });

    // Close modal events
    $('#deleteCredentialConfirmationModal .close, #deleteCredentialConfirmationModal .btn-secondary').on('click', function() {
        $('#deleteCredentialConfirmationModal').modal('hide');
    });
});