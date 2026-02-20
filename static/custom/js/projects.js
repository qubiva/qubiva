$(document).ready(function() {
    let projectsData = {};  // Store fetched projects data for filtering
    let currentView = 'grid';  // Default to grid view
    let itemsPerPage = 6;  // Default items per page
    let currentPage = 1;  // Current page
    let deleteProjectName = '';

    function fetchProjects() {
        // Show loading indicators for both grid and list views
        const loadingHtml = '<div class="text-center w-100 my-5">Loading...</div>';
        $('#qubiva-projects-wrapper').html(loadingHtml);
    
        $.ajax({
            url: '/api/v1/projects',
            type: 'GET',
            success: function(data) {
                projectsData = data;
                renderProjects($('#qubiva-projects-search-box').val(), projectsData);
                renderPagination(projectsData);
            },
            error: function(error) {
                console.error('Error fetching projects:', error);
                $('#qubiva-projects-wrapper').html('<div class="text-center text-muted py-5 w-100"><i class="fas fa-project-diagram fa-2x mb-3 d-block"></i>No projects found</div>');
            }
        });
    }

    function renderProjects(filter = '', projectsData) {
        $('#qubiva-projects-wrapper').empty(); // Clear the container first
        
        // Calculate the starting and ending indices for the current page
        const start = (currentPage - 1) * itemsPerPage;
        const end = start + itemsPerPage;
        const filteredProjects = Object.entries(projectsData).filter(([projectName]) =>
            projectName.toLowerCase().includes(filter.toLowerCase())
        );
        const paginatedProjects = filteredProjects.slice(start, end);

        if (paginatedProjects.length === 0) {
            $('#qubiva-projects-wrapper').append('<div class="text-center text-muted py-5 w-100"><i class="fas fa-project-diagram fa-2x mb-3 d-block"></i>No projects found</div>');
            return;
        }

        if (currentView === 'grid') {
            paginatedProjects.forEach(([projectName, projectDetails]) => {
                const encodedProjectName = encodeURIComponent(projectName);
                $('#qubiva-projects-wrapper').append(`
                    <div class="col-md-4 mb-3">
                        <div class="card h-100 d-flex flex-column project-card">
                            <div class="card-body d-flex flex-column project-card-body">
                                <div class="card-text">
                                    <div class="project-title-container">
                                        <i class="fas fa-project-diagram project-icon"></i>
                                        <h5 class="card-title project-title">${projectName}</h5>
                                    </div>
                                    <div class="project-description-container">
                                        <i class="fas fa-info-circle project-icon"></i>
                                        <span class="project-description">${projectDetails.description}</span>
                                    </div>
                                </div>
                            </div>
                            <div class="project-footer">
                                <a data-permission='["project_get"]' href="/dashboard/projects/${encodedProjectName}" class="btn btn-link text-primary p-0 project-action" title="View Project">
                                    <i class="fas fa-eye"></i>
                                </a>
                                <a data-permission='["project_edit"]' href="/dashboard/projects/${encodedProjectName}/edit" class="btn btn-link text-primary p-0 project-action" title="Edit Project">
                                    <i class="fas fa-edit"></i>
                                </a>
                                <a href="#" data-permission='["org_project_delete"]' class="btn btn-link text-danger p-0 delete-project project-action" data-project="${projectName}" title="Delete Project">
                                    <i class="fas fa-trash-alt"></i>
                                </a>
                            </div>
                        </div>
                    </div>
                `);
            });
        } else {
            $('#qubiva-projects-wrapper').append('<div class="col-12"><ul class="list-group"></ul></div>');
            paginatedProjects.forEach(([projectName, projectDetails]) => {
                const encodedProjectName = encodeURIComponent(projectName);
                $('.list-group').append(`
                    <li class="list-group-item d-flex justify-content-between align-items-center project-list-item">
                        <div>
                            <div class="project-title-container">
                                <i class="fas fa-project-diagram project-icon"></i>
                                <span class="project-title">${projectName}</span>
                            </div>
                            <div class="project-description-container">
                                <i class="fas fa-info-circle project-icon"></i>
                                <span class="project-description">${projectDetails.description}</span>
                            </div>
                        </div>
                        <div class="project-actions-container">
                            <a data-permission='["project_get"]' href="/dashboard/projects/${encodedProjectName}" class="btn btn-link text-primary p-0 project-action" title="View Project">
                                <i class="fas fa-eye"></i>
                            </a>
                            <a data-permission='["project_edit"]' href="/dashboard/projects/${encodedProjectName}/edit" class="btn btn-link text-primary p-0 project-action" title="Edit Project">
                                <i class="fas fa-edit"></i>
                            </a>
                            <a href="#" data-permission='["org_project_delete"]' class="btn btn-link text-danger p-0 delete-project project-action" data-project="${projectName}" title="Delete Project">
                                <i class="fas fa-trash-alt"></i>
                            </a>
                        </div>
                    </li>
                `);
            });
        }

        // Add hover effects
        $('.card, .list-group-item').hover(
            function() {
                $(this).addClass('hover-effect');
            },
            function() {
                $(this).removeClass('hover-effect');
            }
        );

        // Add click event for delete button
        $('.delete-project').on('click', function(e) {
            e.preventDefault();
            const projectName = $(this).data('project');
            console.log(`Delete project: ${projectName}`);
        });
    }

    function renderPagination(projectsData) {
        $('#pagination').empty();
        const totalItems = Object.keys(projectsData).length;
        const totalPages = Math.ceil(totalItems / itemsPerPage);

        for (let i = 1; i <= totalPages; i++) {
            $('#pagination').append(`<li class="page-item ${i === currentPage ? 'active' : ''}">
                <a class="page-link" href="#">${i}</a>
            </li>`);
        }

        $('.page-link').on('click', function(e) {
            e.preventDefault();
            currentPage = parseInt($(this).text());
            renderProjects($('#qubiva-projects-search-box').val(), projectsData);
            renderPagination(projectsData);
        });
    }

    // Function to show the delete confirmation modal
    function showDeleteProjectConfirmationModal(projectName) {
        console.log(`Attempting to show modal for project: ${projectName}`); // Debugging log
        deleteProjectName = projectName;

        $('#projectNameDisplay').text(projectName);
        $('#confirmationProjectName').val('');
        $('#confirmProjectIrreversibleAction').prop('checked', false);
        $('#confirmationProjectError').addClass('d-none');
        $('#confirmProjectDeleteBtn').prop('disabled', true);

        // Show the modal using Bootstrap's modal method
        $('#deleteProjectConfirmationModal').modal('show');
    }

    // Function to show message modal
    function showMessageModal(title, message) {
        $('#messageModalLabel').text(title);
        $('#messageModalBody').text(message);
        $('#messageModal').modal('show');
    }

    // Function to delete a project
    function deleteProject(projectName) {
        $.ajax({
            url: `/api/v1/org/projects/${encodeURIComponent(projectName)}/delete`,
            type: 'DELETE',
            success: function() {
                $('#deleteProjectConfirmationModal').modal('hide');
                showMessageModal("Success", "Project deleted successfully.");
                fetchProjects(); // Refresh the list of projects
            },
            error: function(error) {
                $('#deleteProjectConfirmationModal').modal('hide');
                let errorMessage = 'An error occurred while deleting the project. Please try again.';
                if (error.responseJSON && error.responseJSON.detail) {
                    errorMessage = error.responseJSON.detail;
                }
                showMessageModal("Error", errorMessage);
            }
        });
    }

    // Bind click event to show confirmation modal
    $(document).on('click', '.delete-project', function(e) {
        e.preventDefault();
        const projectName = $(this).data('project');
        console.log(`Delete project: ${projectName}`); // Debugging log
        showDeleteProjectConfirmationModal(projectName);
    });

    // Validate the delete confirmation inputs
    $('#confirmationProjectName, #confirmProjectIrreversibleAction').on('input change', function() {
        const inputName = $('#confirmationProjectName').val();
        const isConfirmed = $('#confirmProjectIrreversibleAction').is(':checked');

        if (inputName === deleteProjectName && isConfirmed) {
            $('#confirmProjectDeleteBtn').prop('disabled', false);
            $('#confirmationProjectError').addClass('d-none');
        } else {
            $('#confirmProjectDeleteBtn').prop('disabled', true);
            if (inputName !== deleteProjectName) {
                $('#confirmationProjectError').removeClass('d-none').text('Project name does not match.');
            } else if (!isConfirmed) {
                $('#confirmationProjectError').removeClass('d-none').text('Please confirm that the action is irreversible.');
            } else {
                $('#confirmationProjectError').addClass('d-none');
            }
        }
    });

    // Handle the delete confirmation button click
    $('#confirmProjectDeleteBtn').on('click', function() {
        deleteProject(deleteProjectName);
    });

    // Close modal events
    $('#deleteProjectConfirmationModal .close, #deleteProjectConfirmationModal .btn-secondary').on('click', function() {
        $('#deleteProjectConfirmationModal').modal('hide');
    });

    $('#itemsPerPageSelect').on('change', function() {
        itemsPerPage = parseInt($(this).val());
        currentPage = 1; // Reset to the first page
        renderProjects($('#qubiva-projects-search-box').val(), projectsData);
        renderPagination(projectsData);
    });

    // Bind the keyup event for real-time filtering
    $('#qubiva-projects-search-box').on('keyup', function() {
        currentPage = 1; // Reset to first page when filtering
        renderProjects($(this).val(), projectsData);
        renderPagination(projectsData);
    });

    // Bind the input event to detect changes including the clear button click
    $('#qubiva-projects-search-box').on('input', function() {
        currentPage = 1; // Reset to first page when filtering
        renderProjects($(this).val(), projectsData);
        renderPagination(projectsData);
    });

    // Bind the form submit event to fetch projects without reloading the page
    $('#project-search-form').on('submit', function(event) {
        event.preventDefault();  // Prevent the form from causing a page reload
        fetchProjects();  // Fetch projects without reloading the page
    });

    // Toggle between list and grid view
    $('#listViewBtn, #gridViewBtn').on('click', function() {
        currentPage = 1; // Reset to first page when switching views
        currentView = $(this).attr('id') === 'listViewBtn' ? 'list' : 'grid';
        $(this).addClass('active').siblings().removeClass('active');
        renderProjects($('#qubiva-projects-search-box').val(), projectsData);
        renderPagination(projectsData);
    });

    // Initial fetch to display projects on page load
    fetchProjects();
});
