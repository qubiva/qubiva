$(document).ready(function() {
    let cloudAccountsData = {};  // Store fetched cloud accounts data for filtering
    let currentView = 'grid';  // Default to grid view
    let itemsPerPage = 6;  // Default items per page
    let currentPage = 1;  // Current page
    let currentFilter = ''; // Current filter for platforms
    let deleteAccountId = '';
    let deleteAccountName = '';
    let deleteCloudPlatform = '';

    $('#newAccountBtn').on('click', function(e) {
        e.preventDefault();
        const projectName = Qubiva.url.projectName();
        const newAccountUrl = `/dashboard/projects/${encodeURIComponent(projectName)}/cloud_accounts/create`;
        window.location.href = newAccountUrl;
    });

    $('#confirmDeleteBtn').on('click', function() {
        deleteCloudAccount(deleteAccountId, deleteCloudPlatform);
    });

    // Validate and enable delete button when conditions are met
    $('#confirmationAccountName, #confirmIrreversibleAction').on('input change', function() {
        const inputName = $('#confirmationAccountName').val();
        const isConfirmed = $('#confirmIrreversibleAction').is(':checked');

        if (inputName === deleteAccountName && isConfirmed) {
            $('#confirmDeleteBtn').prop('disabled', false);
            $('#confirmationError').addClass('d-none');
        } else {
            $('#confirmDeleteBtn').prop('disabled', true);

            if (inputName !== deleteAccountName) {
                $('#confirmationError').removeClass('d-none').text('Account name does not match.');
            } else if (!isConfirmed) {
                $('#confirmationError').removeClass('d-none').text('Please confirm that the action is irreversible.');
            } else {
                $('#confirmationError').addClass('d-none');
            }
        }
    });

    function showDeleteConfirmationModal(accountId, accountName, cloudPlatform) {
        deleteAccountId = accountId;
        deleteAccountName = accountName;
        deleteCloudPlatform = cloudPlatform;

        $('#accountNameDisplay').text(accountName);
        $('#confirmationAccountName').val('');
        $('#confirmIrreversibleAction').prop('checked', false);
        $('#confirmationError').addClass('d-none');
        $('#confirmDeleteBtn').prop('disabled', true);
        $('#deleteConfirmationModal').modal('show');
    }

    function showMessageModal(title, message) {
        $('#messageModalLabel').text(title);
        $('#messageModalBody').text(message);
        $('#messageModal').modal('show');
    }

    // Close button event for message modal
    $('#messageModal .btn-secondary, #messageModal .close').on('click', function() {
        $('#messageModal').modal('hide');
    });  

    function deleteCloudAccount(accountId, cloudPlatform) {
        const projectName = Qubiva.url.projectName();
        const deleteUrl = `/api/v1/projects/${encodeURIComponent(projectName)}/cloud_accounts/${encodeURIComponent(cloudPlatform)}/${encodeURIComponent(accountId)}/delete`;

        $.ajax({
            url: deleteUrl,
            type: 'DELETE',
            success: function() {
                $('#deleteConfirmationModal').modal('hide');
                showMessageModal("Success", "Cloud account deleted successfully.");
                fetchCloudAccounts(); // Refresh the data
            },
            error: function(error) {
                $('#deleteConfirmationModal').modal('hide');
                showMessageModal("Error", Qubiva.extractError(error, 'An error occurred while deleting the cloud account. Please try again.'));
            }
        });
    }

    function fetchCloudAccounts() {
        const projectName = Qubiva.url.projectName();
        
        // Show loading indicator
        $('#cloud-accounts-wrapper').html('<div class="text-center w-100 my-5">Loading...</div>');
        
        $.ajax({
            url: `/api/v1/projects/${encodeURIComponent(projectName)}/cloud_accounts`,
            type: 'GET',
            success: function(data) {
                cloudAccountsData = data.reduce((acc, account) => {
                    acc[account.account_id] = account;
                    return acc;
                }, {});
                populatePlatformDropdown(data);
                renderCloudAccounts();
                renderPagination();
            },
            error: function(error) {
                console.error('Error fetching cloud accounts:', error);
                $('#cloud-accounts-wrapper').html('<div class="text-center text-muted py-5 w-100"><i class="fas fa-cloud fa-2x mb-3 d-block"></i>No cloud accounts found</div>');
            }
        });
    }

    function populatePlatformDropdown(data) {
        const platforms = [...new Set(data.map(account => account.cloud_platform))];
        $('#filterDropdown').empty().append('<option value="all">All Platforms</option>');
        platforms.forEach(platform => {
            $('#filterDropdown').append(`<option value="${platform}">${platform}</option>`);
        });
    }

    function renderCloudAccounts() {
        $('#cloud-accounts-wrapper').empty(); // Clear the container first
    
        // Filter cloud accounts based on the current filter
        const filteredAccounts = Object.entries(cloudAccountsData).filter(([accountId, account]) => {
            const searchTerm = currentFilter.toLowerCase();
            return account.cloud_platform.toLowerCase().includes(searchTerm) ||
                   account.account_id.toLowerCase().includes(searchTerm);
        });
    
        // Paginate the filtered results
        const start = (currentPage - 1) * itemsPerPage;
        const end = start + itemsPerPage;
        const paginatedAccounts = filteredAccounts.slice(start, end);
    
        // If no accounts match, display a message
        if (paginatedAccounts.length === 0) {
            $('#cloud-accounts-wrapper').append('<div class="text-center text-muted py-5 w-100"><i class="fas fa-cloud fa-2x mb-3 d-block"></i>No cloud accounts found</div>');
            return;
        }
    
        // Render accounts in grid or list view
        if (currentView === 'grid') {
            paginatedAccounts.forEach(([accountId, account]) => {
                $('#cloud-accounts-wrapper').append(`
                    <div class="col-md-4 mb-3">
                        <div class="card h-100 d-flex flex-column account-card">
                            <div class="card-body d-flex flex-column account-card-body">
                                <div class="card-text">
                                    <div class="account-title-container">
                                        <i class="fas fa-cloud account-icon"></i>
                                        <h5 class="card-title account-title">${account.cloud_platform}</h5>
                                    </div>
                                    <div class="account-id-container">
                                        <i class="fas fa-id-card account-icon"></i>
                                        <span class="account-id">${account.account_id}</span>
                                    </div>
                                </div>
                            </div>
                            <div class="account-footer">
                                <a data-permission='["project_cloud_account_get"]' href="/dashboard/projects/${Qubiva.url.projectName()}/cloud_accounts/${account.cloud_platform}/${encodeURIComponent(accountId)}" class="btn btn-link text-primary p-0 account-action" title="View Account">
                                    <i class="fas fa-eye"></i>
                                </a>
                                <a data-permission='["project_cloud_account_edit"]' href="/dashboard/projects/${Qubiva.url.projectName()}/cloud_accounts/${account.cloud_platform}/${encodeURIComponent(accountId)}/edit" class="btn btn-link text-primary p-0 account-action" title="Edit Account">
                                    <i class="fas fa-edit"></i>
                                </a>
                                <a data-permission='["project_cloud_account_delete"]' href="#" class="btn btn-link text-danger p-0 delete-account account-action" data-account="${accountId}" title="Delete Account">
                                    <i class="fas fa-trash-alt"></i>
                                </a>
                            </div>
                        </div>
                    </div>
                `);
            });
        } else {
            $('#cloud-accounts-wrapper').append('<div class="col-12"><ul class="list-group"></ul></div>');
            paginatedAccounts.forEach(([accountId, account]) => {
                $('.list-group').append(`
                    <li class="list-group-item d-flex justify-content-between align-items-center account-list-item">
                        <div>
                            <div class="account-title-container">
                                <i class="fas fa-cloud account-icon"></i>
                                <span class="account-title">${account.cloud_platform}</span>
                            </div>
                            <div class="account-id-container">
                                <i class="fas fa-id-card account-icon"></i>
                                <span class="account-id">${account.account_id}</span>
                            </div>
                        </div>
                        <div class="account-actions-container">
                            <a data-permission='["project_cloud_account_get"]' href="/dashboard/projects/${Qubiva.url.projectName()}/cloud_accounts/${account.cloud_platform}/${encodeURIComponent(accountId)}" class="btn btn-link text-primary p-0 account-action" title="View Account">
                                <i class="fas fa-eye"></i>
                            </a>
                            <a data-permission='["project_cloud_account_edit"]' href="/dashboard/projects/${Qubiva.url.projectName()}/cloud_accounts/${account.cloud_platform}/${encodeURIComponent(accountId)}/edit" class="btn btn-link text-primary p-0 account-action" title="Edit Account">
                                <i class="fas fa-edit"></i>
                            </a>
                            <a data-permission='["project_cloud_account_delete"]' href="#" class="btn btn-link text-danger p-0 delete-account account-action" data-account="${accountId}" title="Delete Account">
                                <i class="fas fa-trash-alt"></i>
                            </a>
                        </div>
                    </li>
                `);
            });
        }
    
        // Add hover effects
        $('.card, .list-group-item').hover(
            function() { $(this).addClass('hover-effect'); },
            function() { $(this).removeClass('hover-effect'); }
        );
    
        // Attach event listener to delete buttons
        $('.delete-account').on('click', function(e) {
            e.preventDefault();
            const accountId = $(this).data('account');
            const accountName = $(this).closest('.account-card, .account-list-item').find('.account-id').text();
            const cloudPlatform = $(this).closest('.account-card, .account-list-item').find('.account-title').text();
            showDeleteConfirmationModal(accountId, accountName, cloudPlatform);
        });
    }    

    function renderPagination() {
        $('#pagination').empty();
        const totalItems = Object.keys(cloudAccountsData).length;
        const totalPages = Math.ceil(totalItems / itemsPerPage);

        for (let i = 1; i <= totalPages; i++) {
            $('#pagination').append(`<li class="page-item ${i === currentPage ? 'active' : ''}">
                <a class="page-link" href="#">${i}</a>
            </li>`);
        }

        $('.page-link').on('click', function(e) {
            e.preventDefault();
            currentPage = parseInt($(this).text());
            renderCloudAccounts();
            renderPagination();
        });
    }

    $('#itemsPerPageSelect').on('change', function() {
        itemsPerPage = parseInt($(this).val());
        currentPage = 1; // Reset to the first page
        renderCloudAccounts();
        renderPagination();
    });

    $('#cloud-account-search-box').on('keyup input', function() {
        currentFilter = $(this).val().toLowerCase(); // Update currentFilter with the search term
        currentPage = 1; // Reset to the first page
        renderCloudAccounts(); // Re-render the filtered list
        renderPagination(); // Update pagination
    });

    $('#cloud-account-search-form').on('submit', function(event) {
        event.preventDefault();  // Prevent the form from causing a page reload
        fetchCloudAccounts();  // Fetch cloud accounts without reloading the page
    });

    $('#listViewBtn, #gridViewBtn').on('click', function() {
        currentPage = 1; // Reset to first page when switching views
        currentView = $(this).attr('id') === 'listViewBtn' ? 'list' : 'grid';
        $(this).addClass('active').siblings().removeClass('active');
        renderCloudAccounts();
        renderPagination();
    });

    // Filter dropdown for platform filtering
    $('#filterDropdown').on('change', function() {
        currentFilter = $(this).val() === 'all' ? '' : $(this).val();
        currentPage = 1; // Reset to first page when filtering
        renderCloudAccounts();
        renderPagination();
    });

    // Ensure modal close functionality works properly for delete modal
    $('#deleteConfirmationModal .close, #deleteConfirmationModal .btn-secondary').on('click', function() {
        $('#deleteConfirmationModal').modal('hide');
    });

    // Attach event listener to delete buttons
    $(document).on('click', '.delete-account', function(e) {
        e.preventDefault();
        const accountId = $(this).data('account');
        const accountName = $(this).closest('.account-card, .account-list-item').find('.account-id').text();
        const cloudPlatform = $(this).closest('.account-card, .account-list-item').find('.account-title').text();

        showDeleteConfirmationModal(accountId, accountName, cloudPlatform);
    });

    fetchCloudAccounts();
});
