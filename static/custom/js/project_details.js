$(document).ready(function() {
    let cloudAccounts = []; // To store cloud accounts for filtering
    let githubRepos = []; // To store GitHub repositories for filtering

    function fetchProjectDetails() {
        const projectName = Qubiva.url.lastSegment();
        $.ajax({
            url: `/api/v1/projects/${encodeURIComponent(projectName)}`,
            type: 'GET',
            success: function(data) {
                if (data) {
                    $('#project-title').text(data.name);
                    $('#project-description').text(data.description);
                }
            },
            error: function() {
                console.error('Error loading project details');
                $('#project-details').html('<p>Error loading project details.</p>');
            }
        });
    }

    function fetchCloudAccounts() {
        const projectName = Qubiva.url.lastSegment();
        $.ajax({
            url: `/api/v1/projects/${encodeURIComponent(projectName)}/cloud_accounts`,
            type: 'GET',
            success: function(data) {
                if (data && data.length > 0) {
                    cloudAccounts = data;
                    applyCloudAccountFilter($('#cloud-account-search-box').val());
                } else {
                    displayNoCloudAccountsMessage(projectName);
                }
            },
            error: function(xhr) {
                if (xhr.status === 404) {
                    displayNoCloudAccountsMessage(projectName);
                } else {
                    console.error('Error loading cloud account details');
                    $('#cloud-accounts-wrapper').html('<p>Error loading cloud account details.</p>');
                }
            }
        });
    }

    function fetchGitHubRepos() {
        const projectName = Qubiva.url.lastSegment();
        $.ajax({
            url: `/api/v1/projects/${encodeURIComponent(projectName)}/git_repos`,
            type: 'GET',
            success: function(data) {
                if (data && data.length > 0) {
                    githubRepos = data;
                    applyGitHubRepoFilter($('#github-repo-search-box').val());
                } else {
                    displayNoGitHubReposMessage(projectName);
                }
            },
            error: function(xhr) {
                if (xhr.status === 404) {
                    displayNoGitHubReposMessage(projectName);
                } else {
                    console.error('Error loading GitHub repository details');
                    $('#github-repos-wrapper').html('<p>Error loading GitHub repository details.</p>');
                }
            }
        });
    }

    function displayNoCloudAccountsMessage(projectName) {
        $('#cloud-accounts-wrapper').html(`
            <div class="text-center">
                <p>No cloud accounts added</p>
                <a href="/dashboard/projects/${encodeURIComponent(projectName)}/cloud_accounts/create" class="btn btn-primary mt-2">Add Cloud Account</a>
            </div>
        `);
    }

    function displayNoGitHubReposMessage(projectName) {
        $('#github-repos-wrapper').html(`
            <div class="text-center">
                <p>No GitHub repositories added</p>
                <a href="/dashboard/projects/${encodeURIComponent(projectName)}/git_repos/add" class="btn btn-primary mt-2">Add GitHub Repository</a>
            </div>
        `);
    }

    function renderCloudAccounts(accounts) {
        $('#cloud-accounts-wrapper').empty();
        accounts.forEach(account => {
            $('#cloud-accounts-wrapper').append(`
                <div class="col-md-4">
                    <div class="card">
                        <div class="card-body">
                            <h5 class="card-title">${account.cloud_platform} Account</h5>
                            <p class="card-text">Account ID: ${account.account_id}</p>
                            <a href="/dashboard/projects/${encodeURIComponent(Qubiva.url.lastSegment())}/cloud_accounts/${account.cloud_platform}/${account.account_id}" class="btn btn-primary">Manage Account</a>
                        </div>
                    </div>
                </div>
            `);
        });
    }

    function renderGitHubRepos(repos) {
        $('#github-repos-wrapper').empty();
        repos.forEach(repo => {
            $('#github-repos-wrapper').append(`
                <div class="col-md-4">
                    <div class="card">
                        <div class="card-body">
                            <h5 class="card-title">Repository: ${repo.repo_name}</h5>
                            <p class="card-text">Branch: ${repo.branch}</p>
                            <p class="card-text">Path: ${repo.path}</p>
                            <a href="/dashboard/projects/${encodeURIComponent(Qubiva.url.lastSegment())}/git_repos/${encodeURIComponent(repo.repo_name)}/edit" class="btn btn-primary">Edit Repository</a>
                        </div>
                    </div>
                </div>
            `);
        });
    }

    function applyCloudAccountFilter(filter = '') {
        const filteredAccounts = cloudAccounts.filter(account => 
            account.cloud_platform.toLowerCase().includes(filter.toLowerCase()) ||
            account.account_id.toLowerCase().includes(filter.toLowerCase())
        );
        renderCloudAccounts(filteredAccounts);
    }

    function applyGitHubRepoFilter(filter = '') {
        const filteredRepos = githubRepos.filter(repo => 
            repo.repo_name.toLowerCase().includes(filter.toLowerCase()) ||
            repo.branch.toLowerCase().includes(filter.toLowerCase()) ||
            repo.path.toLowerCase().includes(filter.toLowerCase())
        );
        renderGitHubRepos(filteredRepos);
    }

    function switchToTab(hash) {
        if (!hash) return; // If there's no hash, do nothing
    
        // Show the correct tab (if using Bootstrap tabs)
        let tabLink = $('.nav-tabs a[href="' + hash + '"]');
        if (tabLink.length) {
            tabLink.tab('show'); // Show the tab
        }
    
        // Add active to the correct sidebar link without affecting parent links
        let sidebarLink = $('.nav-sidebar a[href$="' + hash + '"]');
        if (sidebarLink.length) {
            sidebarLink.closest('li').siblings().find('a').removeClass('active'); // Remove active from siblings
            sidebarLink.addClass('active'); // Add active to the current link
        }
    }
    
    $('#cloud-account-search-form').on('submit', function(event) {
        event.preventDefault();
        applyCloudAccountFilter($('#cloud-account-search-box').val());
    });

    $('#github-repo-search-form').on('submit', function(event) {
        event.preventDefault();
        applyGitHubRepoFilter($('#github-repo-search-box').val());
    });

    $('#cloud-account-search-box').on('input', function() {
        applyCloudAccountFilter($(this).val());
    });

    $('#github-repo-search-box').on('input', function() {
        applyGitHubRepoFilter($(this).val());
    });

    $('#cloud-account-search-button').on('click', function() {
        fetchCloudAccounts();
    });

    $('#github-repo-search-button').on('click', function() {
        fetchGitHubRepos();
    });

    switchToTab(window.location.hash);

    // Bind the hash change event to the switchToTab function
    $(window).on('hashchange', function() {
        switchToTab(window.location.hash);
    });    

    // Initial fetch of project details, cloud accounts, and GitHub repos
    fetchProjectDetails();
    fetchCloudAccounts();
    fetchGitHubRepos();
});
