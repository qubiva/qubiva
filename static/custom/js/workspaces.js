$(document).ready(function() {
    let workspacesData = {};
    let currentView = 'grid';
    let itemsPerPage = 10;
    let currentPage = 1;
    let currentFilter = '';
    let workspaceToDelete = null;

    function fetchWorkspaces() {
        const projectName = Qubiva.url.projectName();
        
        // Show loading indicator
        $('#workspaces-wrapper').html('<div class="text-center w-100 my-5">Loading...</div>');
        
        $.ajax({
            url: `/api/v1/projects/${encodeURIComponent(projectName)}/workspaces`,
            type: 'GET',
            success: function(data) {
                workspacesData = data.reduce((acc, workspace) => {
                    acc[workspace.name] = workspace;
                    return acc;
                }, {});
                renderWorkspaces();
                renderPagination();
            },
            error: function(error) {
                console.error('Error fetching workspaces:', error);
                $('#workspaces-wrapper').html('<div class="text-center text-muted py-5 w-100"><i class="fas fa-folder-open fa-2x mb-3 d-block"></i>No workspaces found</div>');
            }
        });
    }

    function attachDeleteEvent() {
        // Event listener for delete buttons
        $('.delete-action').off('click').on('click', function(e) {
            e.preventDefault();
            workspaceToDelete = $(this).data('workspace'); // Get the workspace name
            $('#workspaceNameDisplay').text(workspaceToDelete); // Show the name in modal
            $('#confirmWorkspaceNameInput').val(''); // Clear previous input
            $('#confirmWorkspaceCheck').prop('checked', false); // Reset checkbox
            $('#deleteWorkspaceBtn').prop('disabled', true); // Disable delete button by default
            $('#confirmationError').addClass('d-none'); // Hide error initially
            $('#deleteWorkspaceModal').modal('show'); // Show confirmation modal
        });
    }

    function renderWorkspaces() {
        $('#workspaces-wrapper').empty();
        
        const filteredWorkspaces = Object.entries(workspacesData).filter(([name, workspace]) => {
            return workspace.name.toLowerCase().includes(currentFilter.toLowerCase()) ||
                   (workspace.description && workspace.description.toLowerCase().includes(currentFilter.toLowerCase()));
        });
        
        const start = (currentPage - 1) * itemsPerPage;
        const end = start + itemsPerPage;
        const paginatedWorkspaces = filteredWorkspaces.slice(start, end);
    
        if (paginatedWorkspaces.length === 0) {
            $('#workspaces-wrapper').append('<div class="text-center text-muted py-5 w-100"><i class="fas fa-folder-open fa-2x mb-3 d-block"></i>No workspaces found</div>');
            return;
        }
    
        const projectName = Qubiva.url.projectName();
    
        if (currentView === 'grid') {
            paginatedWorkspaces.forEach(([name, workspace]) => {
                $('#workspaces-wrapper').append(`
                    <div class="col-md-4 mb-3">
                        <div class="card h-100 d-flex flex-column workspace-card">
                            <div class="card-body d-flex flex-column workspace-card-body">
                                <div class="card-text">
                                    <div class="workspace-title-container">
                                        <i class="fas fa-cube workspace-icon"></i>
                                        <h5 class="card-title workspace-title">${workspace.name}</h5>
                                    </div>
                                    <div class="workspace-description-container">
                                        <i class="fas fa-info-circle workspace-icon"></i>
                                        <span class="workspace-description">${workspace.description || 'No description'}</span>
                                    </div>
                                </div>
                            </div>
                            <div class="workspace-footer">
                                <a href="/dashboard/projects/${projectName}/workspaces/${encodeURIComponent(name)}" class="workspace-action view-action" title="View Workspace">
                                    <i class="fas fa-eye"></i>
                                </a>
                                <a href="/dashboard/projects/${projectName}/workspaces/${encodeURIComponent(name)}/edit" class="workspace-action edit-action" title="Edit Workspace">
                                    <i class="fas fa-edit"></i>
                                </a>
                                <button class="workspace-action delete-action" data-workspace="${name}" title="Delete Workspace">
                                    <i class="fas fa-trash-alt"></i>
                                </button>
                            </div>
                        </div>
                    </div>
                `);
            });
        } else {
            $('#workspaces-wrapper').append('<div class="col-12"><ul class="list-group"></ul></div>');
            paginatedWorkspaces.forEach(([name, workspace]) => {
                $('.list-group').append(`
                    <li class="list-group-item d-flex justify-content-between align-items-center workspace-list-item">
                        <div>
                            <div class="workspace-title-container">
                                <i class="fas fa-cube workspace-icon"></i>
                                <span class="workspace-title">${workspace.name}</span>
                            </div>
                            <div class="workspace-description-container">
                                <i class="fas fa-info-circle workspace-icon"></i>
                                <span class="workspace-description">${workspace.description || 'No description'}</span>
                            </div>
                        </div>
                        <div class="workspace-actions-container">
                            <a href="/dashboard/projects/${projectName}/workspaces/${encodeURIComponent(name)}" class="workspace-action view-action" title="View Workspace">
                                <i class="fas fa-eye"></i>
                            </a>
                            <a href="/dashboard/projects/${projectName}/workspaces/${encodeURIComponent(name)}/edit" class="workspace-action edit-action" title="Edit Workspace">
                                <i class="fas fa-edit"></i>
                            </a>
                            <button class="workspace-action delete-action" data-workspace="${name}" title="Delete Workspace">
                                <i class="fas fa-trash-alt"></i>
                            </button>
                        </div>
                    </li>
                `);
            });
        }
    
        $('.card, .list-group-item').hover(
            function() { $(this).addClass('hover-effect'); },
            function() { $(this).removeClass('hover-effect'); }
        );

        attachDeleteEvent();
    }

    function renderPagination() {
        $('#pagination').empty();
        const totalItems = Object.keys(workspacesData).length;
        const totalPages = Math.ceil(totalItems / itemsPerPage);

        for (let i = 1; i <= totalPages; i++) {
            $('#pagination').append(`<li class="page-item ${i === currentPage ? 'active' : ''}">
                <a class="page-link" href="#">${i}</a>
            </li>`);
        }

        $('.page-link').on('click', function(e) {
            e.preventDefault();
            currentPage = parseInt($(this).text());
            renderWorkspaces();
            renderPagination();
        });
    }

    $('#itemsPerPageSelect').on('change', function() {
        itemsPerPage = parseInt($(this).val());
        currentPage = 1;
        renderWorkspaces();
        renderPagination();
    });

    $('#workspace-search-box').on('keyup input', function() {
        currentPage = 1;
        currentFilter = $(this).val();
        renderWorkspaces();
        renderPagination();
    });

    $('#workspace-search-form').on('submit', function(event) {
        event.preventDefault();
        fetchWorkspaces();
    });

    $('#listViewBtn, #gridViewBtn').on('click', function() {
        currentPage = 1;
        currentView = $(this).attr('id') === 'listViewBtn' ? 'list' : 'grid';
        $(this).addClass('active').siblings().removeClass('active');
        renderWorkspaces();
        renderPagination();
    });

    $('#newWorkspaceBtn').on('click', function() {
        const projectName = Qubiva.url.projectName();
        window.location.href = `/dashboard/projects/${projectName}/workspaces/create`;
    });

    // Monitor input and checkbox to enable the delete button and show error messages
    $('#confirmWorkspaceNameInput, #confirmWorkspaceCheck').on('input change', function() {
        const inputName = $('#confirmWorkspaceNameInput').val();
        const isConfirmed = $('#confirmWorkspaceCheck').is(':checked');

        // Check if the input name matches and the checkbox is checked
        if (inputName === workspaceToDelete && isConfirmed) {
            $('#deleteWorkspaceBtn').prop('disabled', false);
            $('#confirmationError').addClass('d-none'); // Hide error message
        } else {
            $('#deleteWorkspaceBtn').prop('disabled', true);

            // Show relevant error messages
            if (inputName !== workspaceToDelete) {
                $('#confirmationError').removeClass('d-none').text('Workspace name does not match.');
            } else if (!isConfirmed) {
                $('#confirmationError').removeClass('d-none').text('Please confirm that the action is irreversible.');
            } else {
                $('#confirmationError').addClass('d-none'); // If no specific error
            }
        }
    });

    // Confirm delete action
    $('#deleteWorkspaceBtn').on('click', function() {
        if (!workspaceToDelete) return; // No workspace selected for deletion
        const projectName = Qubiva.url.projectName();

        // AJAX call to delete the workspace
        $.ajax({
            url: `/api/v1/projects/${encodeURIComponent(projectName)}/workspaces/${encodeURIComponent(workspaceToDelete)}/delete`,
            type: 'DELETE',
            success: function() {
                $('#deleteWorkspaceModal').modal('hide');
                showMessageModal("Success", `Workspace "${workspaceToDelete}" deleted successfully.`);
                fetchWorkspaces();
            },
            error: function() {
                $('#deleteWorkspaceModal').modal('hide');
                showMessageModal("Error", `Failed to delete workspace "${workspaceToDelete}". Please try again.`);
            },
            complete: function() {
                workspaceToDelete = null; // Reset the temporary storage
            }
        });
    });

    // Show success or error message modal
    function showMessageModal(title, message) {
        if (title === "Success") {
            $('#successModalLabel').text(title);
            $('#modalMessage').text(message);
            $('#successModal').modal('show');
        } else {
            $('#failureModalLabel').text(title);
            $('#failureModalMessage').text(message);
            $('#failureModal').modal('show');
        }
    }

    // Close button event for delete modal and success/error modals
    $('#deleteWorkspaceModal .btn-secondary, #deleteWorkspaceModal .close').on('click', function() {
        $('#deleteWorkspaceModal').modal('hide');
    });

    $('#successModal .btn-secondary, #successModal .close').on('click', function() {
        $('#successModal').modal('hide');
    });

    $('#failureModal .btn-secondary, #failureModal .close').on('click', function() {
        $('#failureModal').modal('hide');
    });

    fetchWorkspaces();
});
