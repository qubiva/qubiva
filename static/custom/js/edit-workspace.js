$(document).ready(function() {
    const projectName = Qubiva.url.projectName();
    const workspaceName = Qubiva.url.workspaceName();

    initializeGitRepoSelect();
    initializeCloudAccountSelect();
    fetchWorkspaceDetails(projectName, workspaceName);
    setupEventHandlers();
    Qubiva.variableEntry.init('#edit-workspace-form');
});

function initializeGitRepoSelect() {
    const projectName = Qubiva.url.projectName();

    $('#git-repo-search').select2({
        theme: 'bootstrap4',
        ajax: {
            url: `/api/v1/projects/${projectName}/git_repos/search`,
            dataType: 'json',
            delay: 250,
            data: function (params) {
                return {
                    query: params.term
                };
            },
            processResults: function (data) {
                const results = data.results.map(item => ({
                    id: item.repo_name,  // Use repo_name as the ID for workspace
                    text: item.text,
                    repo_name: item.repo_name
                }));
                return { results };
            },
            cache: false
        },
        minimumInputLength: 1,
        placeholder: 'Search for a git repository'
    });
}

function initializeCloudAccountSelect() {
    const projectName = Qubiva.url.projectName();

    $('#cloud-account-search').select2({
        theme: 'bootstrap4',
        ajax: {
            url: `/api/v1/projects/${projectName}/cloud_accounts/search`,
            dataType: 'json',
            delay: 250,
            data: function (params) {
                return {
                    query: params.term
                };
            },
            processResults: function (data) {
                console.log("=== CLOUD ACCOUNT SEARCH API RESPONSE ===");
                console.log("Raw API response:", data);
                
                const results = data.results.map(item => {
                    console.log("Processing item:", item);
                    const mappedItem = {
                        id: item.account_id,  // Use account_id as the id
                        text: item.text,
                        account_id: item.account_id,
                        cloud_platform: item.cloud_platform
                    };
                    console.log("Mapped to:", mappedItem);
                    return mappedItem;
                });
                console.log("Final results:", results);
                return { results };
            },
            cache: false
        },
        minimumInputLength: 1,
        placeholder: 'Search for a cloud account'
    });
}

function fetchWorkspaceDetails(projectName, workspaceName) {
    $.ajax({
        url: `/api/v1/projects/${projectName}/workspaces/${workspaceName}`,
        method: 'GET',
        dataType: 'json',
        success: function(data) {
            populateWorkspaceForm(data);
            initialFormData = getCurrentFormData();
        },
        error: function(error) {
            console.error('Error fetching workspace details:', error);
        }
    });
}

function populateWorkspaceForm(data) {
    console.log("Raw workspace data from API:", JSON.stringify(data, null, 2));
    $('#workspace-name').val(data.name);
    $('#workspace-description').val(data.description);
    $('#variables-entries').empty();

    $('#terraform-version').val(data.terraform_version);

    // Set git repo selection if it exists
    // Set git repo selection if it exists
    if (data.github_repo_name) {
        $('#git-repo-search').empty();
        const option = new Option(data.github_repo_name, data.github_repo_name, true, true);
        $(option).attr('data-repo-name', data.github_repo_name);
        $('#git-repo-search').append(option).trigger('change');
    }

    if (data.cloud_account && data.cloud_platform) {
        const cloudAccountText = `${data.cloud_platform} - ${data.cloud_account}`;
        $('#cloud-account-search').empty();
        const option = new Option(cloudAccountText, data.cloud_account, true, true);
        $(option).attr('data-account-id', data.cloud_account);
        $(option).attr('data-cloud-platform', data.cloud_platform);
        $('#cloud-account-search').append(option).trigger('change');
    }

    $('#trigger-branch').val(data.trigger_branch || '');

    if (data.variables) {
        Object.entries(data.variables).forEach(([key, value]) => {
            Qubiva.variableEntry.add(key, value, false, '#edit-workspace-form');
        });
    }
    if (data.secrets) {
        Object.entries(data.secrets).forEach(([key, value]) => {
            Qubiva.variableEntry.add(key, value, true, '#edit-workspace-form');
        });
    }

    $('#edit-workspace-form').off('input').on('input', function() {
        const currentFormData = getCurrentFormData();
        const isFormChanged = JSON.stringify(initialFormData) !== JSON.stringify(currentFormData);
        $('#update-workspace-button').prop('disabled', !isFormChanged);
    });
}

function getCurrentFormData() {
    const description = $('#workspace-description').val();
    const terraformVersion = $('#terraform-version').val();
    const gitRepoData = $('#git-repo-search').select2('data')[0];
    let githubRepoName = null;
    if (gitRepoData) {
        // Try to get from HTML attribute first (pre-populated), then from select2 data (newly selected)
        githubRepoName = $('#git-repo-search option:selected').attr('data-repo-name') || gitRepoData.repo_name || gitRepoData.id;
    }
    const cloudAccountData = $('#cloud-account-search').select2('data')[0];
    let cloudAccount = null;
    let cloudPlatform = null;
    if (cloudAccountData) {
        // Try to get from HTML attribute first (pre-populated), then from select2 data (newly selected)
        cloudAccount = $('#cloud-account-search option:selected').attr('data-account-id') || cloudAccountData.account_id || cloudAccountData.id;
        cloudPlatform = $('#cloud-account-search option:selected').attr('data-cloud-platform') || cloudAccountData.cloud_platform;
    }

    console.log("=== getCurrentFormData DEBUG ===");
    console.log("gitRepoData:", gitRepoData);
    console.log("githubRepoName extracted:", githubRepoName);
    console.log("cloudAccountData:", cloudAccountData);
    console.log("cloudAccount extracted:", cloudAccount);
    console.log("cloudPlatform extracted:", cloudPlatform);


    const variables = {};
    const secrets = {};

    $('#variables-entries .variable-entry').each(function() {
        const key = $(this).find('input[name="variable-key"]').val();
        const value = $(this).find('input[name="variable-value"]').val();
        const isSecret = $(this).find('input[name="is-secret"]').is(':checked');
        
        if (key) {
            if (isSecret) {
                secrets[key] = value;
            } else {
                variables[key] = value;
            }
        }
    });

    return {
        description,
        terraform_version: terraformVersion,
        github_repo_name: githubRepoName,
        cloud_account: cloudAccount,
        cloud_platform: cloudPlatform,
        trigger_branch: $('#trigger-branch').val().trim() || null,
        variables,
        secrets
    };
}
function setupEventHandlers() {
    $('#edit-workspace-form').off('submit').on('submit', function(event) {
        event.preventDefault();
        updateWorkspace();
    });

}

function updateWorkspace() {
    $('#update-workspace-button').prop('disabled', true);
    $('#spinner').show();

    const projectName = Qubiva.url.projectName();
    const workspaceName = $('#workspace-name').val();
    const formData = getCurrentFormData();

    console.log("=== EDIT WORKSPACE DEBUG ===");
    console.log("Git repo select2 data:", $('#git-repo-search').select2('data'));
    console.log("Cloud account select2 data:", $('#cloud-account-search').select2('data'));
    console.log("Final formData being sent:", JSON.stringify(formData, null, 2));

    if (!formData.github_repo_name) {
        $('#failureModal').modal('show');
        $('#failureModalMessage').text('Please select a Git repository.');
        $('#update-workspace-button').prop('disabled', false);
        $('#spinner').hide();
        return;
    }

    if (!formData.cloud_account) {
        $('#failureModal').modal('show');
        $('#failureModalMessage').text('Please select a cloud account.');
        $('#update-workspace-button').prop('disabled', false);
        $('#spinner').hide();
        return;
    }

    $.ajax({
        url: `/api/v1/projects/${projectName}/workspaces/${workspaceName}/edit`,
        method: 'PUT',
        contentType: 'application/json',
        data: JSON.stringify(formData),
        success: function(data) {
            $('#successModal').modal('show');
            $('#modalMessage').text(data.message);
            $('#viewWorkspaceButton').off('click').on('click', function() {
                window.location.href = `/dashboard/projects/${projectName}/workspaces/${workspaceName}`;
            });
            initialFormData = getCurrentFormData();
        },
        error: function(xhr) {
            $('#failureModalMessage').text(Qubiva.extractError(xhr, 'Failed to update the workspace. Please try again.'));
            $('#failureModal').modal('show');
        },
        complete: function() {
            $('#update-workspace-button').prop('disabled', false);
            $('#spinner').hide();
        }
    });
}