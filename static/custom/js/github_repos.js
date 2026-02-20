$(document).ready(function() {
    let githubReposData = {};  // Store fetched GitHub repositories data for filtering
    let currentView = 'grid';  // Default to grid view
    let itemsPerPage = 6;  // Default items per page
    let currentPage = 1;  // Current page
    let currentFilter = ''; // Current filter for branches
    let deleteRepoName = '';
    let branchFilter = '';

    $(document).on('click', '.delete-repo', function(e) {
        e.preventDefault();
        const repoName = $(this).data('repo');
        console.log(`Clicked delete for repository: ${repoName}`);
        showDeleteRepoConfirmationModal(repoName);
    });

    function showDeleteRepoConfirmationModal(repoName) {
        console.log(`Showing confirmation modal for: ${repoName}`);
        deleteRepoName = repoName;

        $('#repoNameDisplay').text(repoName);
        $('#confirmationRepoName').val('');
        $('#confirmRepoIrreversibleAction').prop('checked', false);
        $('#confirmationRepoError').addClass('d-none');
        $('#confirmRepoDeleteBtn').prop('disabled', true);
        
        console.log("Attempting to show modal...");
        $('#deleteRepoConfirmationModal').modal('show');
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

    function fetchGitHubRepos() {
        // Show loading indicator
        $('#github-repos-wrapper').html('<div class="text-center w-100 my-5">Loading...</div>');
     
        const projectName = Qubiva.url.projectName();
        $.ajax({
            url: `/api/v1/projects/${encodeURIComponent(projectName)}/git_repos`,
            type: 'GET',
            success: function(data) {
                githubReposData = data.reduce((acc, repo) => {
                    acc[repo.repo_name] = repo;
                    return acc;
                }, {});
                populateBranchDropdown(data);
                renderRepos();
                renderPagination();
            },
            error: function(error) {
                console.error('Error fetching GitHub repositories:', error);
                $('#github-repos-wrapper').html('<div class="text-center text-muted py-5 w-100"><i class="fas fa-code-branch fa-2x mb-3 d-block"></i>No repositories found</div>');
            }
        });
     }

    function populateBranchDropdown(data) {
        // Get unique branches, filter out null values, and sort
        const branches = [...new Set(data.map(repo => repo.branch))]
            .filter(branch => branch != null)
            .sort();
        
        $('#filterDropdown').empty().append('<option value="all">All Branches</option>');
        branches.forEach(branch => {
            $('#filterDropdown').append(`<option value="${branch}">${branch}</option>`);
        });
    }

    function deleteGitHubRepository(repoName) {
        const projectName = Qubiva.url.projectName();
        const deleteUrl = `/api/v1/projects/${encodeURIComponent(projectName)}/git_repos/${encodeURIComponent(repoName)}/delete`;

        $.ajax({
            url: deleteUrl,
            type: 'DELETE',
            success: function() {
                $('#deleteRepoConfirmationModal').modal('hide');
                showMessageModal("Success", "GitHub repository deleted successfully.");
                fetchGitHubRepos(); // Refresh the list of repositories
            },
            error: function(error) {
                $('#deleteRepoConfirmationModal').modal('hide');
                showMessageModal("Error", Qubiva.extractError(error, 'An error occurred while deleting the repository. Please try again.'));
            }
        });
    }

    function renderRepos() {
        $('#github-repos-wrapper').empty(); // Clear the container first
        
        const filteredRepos = Object.entries(githubReposData).filter(([repoName, repo]) => {
            // For search text - match anywhere in the name
            const matchesSearch = repoName.toLowerCase().includes(currentFilter.toLowerCase());
            
            // For branch filter
            const matchesBranch = branchFilter === '' || repo.branch === branchFilter;
            
            return matchesSearch && matchesBranch;
        });
        
        const start = (currentPage - 1) * itemsPerPage;
        const end = start + itemsPerPage;
        const paginatedRepos = filteredRepos.slice(start, end);

        if (paginatedRepos.length === 0) {
            $('#github-repos-wrapper').append('<div class="text-center text-muted py-5 w-100"><i class="fas fa-code-branch fa-2x mb-3 d-block"></i>No repositories found</div>');
            return;
        }

        if (currentView === 'grid') {
            paginatedRepos.forEach(([repoName, repo]) => {
                $('#github-repos-wrapper').append(`
                    <div class="col-md-4 mb-3">
                        <div class="card h-100 d-flex flex-column repo-card">
                            <div class="card-body d-flex flex-column repo-card-body">
                                <div class="card-text">
                                    <div class="repo-title-container">
                                        <i class="fab fa-github repo-icon"></i>
                                        <h5 class="card-title repo-title">${repo.repo_name}</h5>
                                    </div>
                                    <div class="repo-branch-container">
                                        <i class="fas fa-code-branch repo-icon"></i>
                                        <span class="repo-branch">${repo.branch || 'default'}</span>
                                    </div>
                                </div>
                            </div>
                            <div class="repo-footer">
                                <a data-permission='["project_git_repo_edit"]' href="/dashboard/projects/${encodeURIComponent(Qubiva.url.projectName())}/git_repos/${encodeURIComponent(repoName)}/edit" class="btn btn-link text-primary p-0 repo-action">
                                    <i class="fas fa-edit"></i>
                                </a>
                                <a data-permission='["project_git_repo_delete"]' href="#" class="btn btn-link text-danger p-0 delete-repo repo-action" data-repo="${repoName}">
                                    <i class="fas fa-trash-alt"></i>
                                </a>
                            </div>
                        </div>
                    </div>
                `);
            });
        } else {
            $('#github-repos-wrapper').append('<div class="col-12"><ul class="list-group"></ul></div>');
            paginatedRepos.forEach(([repoName, repo]) => {
                $('.list-group').append(`
                    <li class="list-group-item d-flex justify-content-between align-items-center repo-list-item">
                        <div>
                            <div class="repo-title-container">
                                <i class="fab fa-github repo-icon"></i>
                                <span class="repo-title">${repo.repo_name}</span>
                            </div>
                            <div class="repo-branch-container">
                                <i class="fas fa-code-branch repo-icon"></i>
                                <span class="repo-branch">${repo.branch || 'default'}</span>
                            </div>
                        </div>
                        <div class="repo-actions-container">
                            <a data-permission='["project_git_repo_edit"]' href="/dashboard/projects/${encodeURIComponent(Qubiva.url.projectName())}/git_repos/${encodeURIComponent(repoName)}/edit" class="btn btn-link text-primary p-0 repo-action">
                                <i class="fas fa-edit"></i>
                            </a>
                            <a data-permission='["project_git_repo_delete"]' href="#" class="btn btn-link text-danger p-0 delete-repo repo-action" data-repo="${repoName}">
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
        $('.delete-repo').on('click', function(e) {
            e.preventDefault();
            const repoName = $(this).data('repo');
            console.log(`Clicked delete for repository: ${repoName}`);
            showDeleteRepoConfirmationModal(repoName);
        });
    }

    function renderPagination() {
        $('#pagination').empty();
        const totalItems = Object.keys(githubReposData).length;
        const totalPages = Math.ceil(totalItems / itemsPerPage);

        for (let i = 1; i <= totalPages; i++) {
            $('#pagination').append(`<li class="page-item ${i === currentPage ? 'active' : ''}">
                <a class="page-link" href="#">${i}</a>
            </li>`);
        }

        $('.page-link').on('click', function(e) {
            e.preventDefault();
            currentPage = parseInt($(this).text());
            renderRepos();
            renderPagination();
        });
    }

    $('#itemsPerPageSelect').on('change', function() {
        itemsPerPage = parseInt($(this).val());
        currentPage = 1;
        renderRepos();
        renderPagination();
    });

    $('#github-repo-search-box').on('keyup input', function() {
        currentPage = 1;
        currentFilter = $(this).val().toLowerCase();  // This updates search filter
        renderRepos();
        renderPagination();
    });

    $('#github-repo-search-form').on('submit', function(event) {
        event.preventDefault();
        fetchGitHubRepos();
    });

    $('#listViewBtn, #gridViewBtn').on('click', function() {
        currentPage = 1;
        currentView = $(this).attr('id') === 'listViewBtn' ? 'list' : 'grid';
        $(this).addClass('active').siblings().removeClass('active');
        renderRepos();
        renderPagination();
    });

    $('#filterDropdown').on('change', function() {
        branchFilter = $(this).val() === 'all' ? '' : $(this).val();  // This updates branch filter
        currentPage = 1;
        renderRepos();
        renderPagination();
    });

    fetchGitHubRepos();

    $('#newRepoBtn').on('click', function() {
        const projectName = Qubiva.url.projectName();
        if (!projectName) {
            console.error('Unable to determine project name from URL');
            return;
        }
        window.location.href = `/dashboard/projects/${encodeURIComponent(projectName)}/git_repos/add`;
    });

    $('#confirmationRepoName, #confirmRepoIrreversibleAction').on('input change', function() {
        const inputName = $('#confirmationRepoName').val();
        const isConfirmed = $('#confirmRepoIrreversibleAction').is(':checked');

        if (inputName === deleteRepoName && isConfirmed) {
            $('#confirmRepoDeleteBtn').prop('disabled', false);
            $('#confirmationRepoError').addClass('d-none');
        } else {
            $('#confirmRepoDeleteBtn').prop('disabled', true);

            if (inputName !== deleteRepoName) {
                $('#confirmationRepoError').removeClass('d-none').text('Repository name does not match.');
            } else if (!isConfirmed) {
                $('#confirmationRepoError').removeClass('d-none').text('Please confirm that the action is irreversible.');
            } else {
                $('#confirmationRepoError').addClass('d-none');
            }
        }
    });

    $('#confirmRepoDeleteBtn').on('click', function() {
        deleteGitHubRepository(deleteRepoName);
    });

    // Close modal events
    $('#deleteRepoConfirmationModal .close, #deleteRepoConfirmationModal .btn-secondary').on('click', function() {
        $('#deleteRepoConfirmationModal').modal('hide');
    });
});
