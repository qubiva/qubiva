$(document).ready(function() {
    const projectName = Qubiva.url.projectName();

    setupEventHandlers();
    
    // EXACT COPY from working terraform executor
    $('#git-repo-search').select2({
        theme: 'bootstrap4',
        ajax: {
            url: `/api/v1/projects/${projectName}/git_repos/search`,
            dataType: 'json',
            delay: 250,
            data: function (params) {
                console.log("Search with current value:", $(this).val());
                return {
                    query: params.term
                };
            },
            processResults: function (data) {
                // Transform the data to ensure proper id field
                const results = data.results.map(item => ({
                    id: item.repo_url,  // Use repo_url as the id
                    text: item.text,
                    repo_url: item.repo_url,
                    repo_name: item.repo_name  
                }));
                console.log("Transformed results:", results);
                return { results };
            },
            cache: false
        },
        minimumInputLength: 1,
        placeholder: 'Search for a git repository'
    });
    // Add this AFTER the git-repo-search select2 initialization
    $('#cloud-account-search').select2({
        theme: 'bootstrap4',
        ajax: {
            url: `/api/v1/projects/${projectName}/cloud_accounts/search`,
            dataType: 'json',
            delay: 250,
            data: function (params) {
                console.log("Search with current value:", $(this).val());
                return {
                    query: params.term
                };
            },
            processResults: function (data) {
                // Transform the data to ensure proper id field
                const results = data.results.map(item => ({
                    id: item.account_id,  // Use account_id as the id
                    text: item.text,
                    account_id: item.account_id,
                    cloud_platform: item.cloud_platform
                }));
                console.log("Transformed results:", results);
                return { results };
            },
            cache: false
        },
        minimumInputLength: 1,
        placeholder: 'Search for a cloud account'
    });
});

function setupEventHandlers() {
    $('#create-workspace-form').off('submit').on('submit', function(event) {
        event.preventDefault();
        createWorkspace();
    });

    $('#create-workspace-form').on('input', function() {
        $('#create-workspace-button').prop('disabled', false);
    });

    Qubiva.variableEntry.init();
}

function createWorkspace() {
    $('#create-workspace-button').prop('disabled', true);
    $('#spinner').show();

    const projectName = Qubiva.url.projectName();
    const workspaceName = $('#workspace-name').val();
    const workspaceDescription = $('#workspace-description').val();
    const terraformVersion = $('#terraform-version').val();
    
    // EXACT COPY from working terraform executor
    var gitRepoData = $('#git-repo-search').select2('data')[0];
    console.log("Git Repo Data:", gitRepoData);
    var gitRepoValue = gitRepoData ? gitRepoData.repo_url : null;
    var gitRepoName = gitRepoData ? gitRepoData.repo_name : null;

    if (!gitRepoName) {
        $('#failureModal').modal('show');
        $('#failureModalMessage').text('Please select a Git repository.');
        $('#create-workspace-button').prop('disabled', false);
        $('#spinner').hide();
        return;
    }

    var cloudAccountData = $('#cloud-account-search').select2('data')[0];
    console.log("Cloud Account Data:", cloudAccountData);
    var cloudAccountValue = cloudAccountData ? cloudAccountData.account_id : null;
    var cloudPlatformValue = cloudAccountData ? cloudAccountData.cloud_platform : null;

    if (!cloudPlatformValue && cloudAccountData) {
        // Extract from the text which should be "platform - account_id"
        const textParts = cloudAccountData.text.split(' - ');
        if (textParts.length >= 2) {
            cloudPlatformValue = textParts[0];
        }
    }

    if (!cloudAccountValue) {
        $('#failureModal').modal('show');
        $('#failureModalMessage').text('Please select a cloud account.');
        $('#create-workspace-button').prop('disabled', false);
        $('#spinner').hide();
        return;
    }
    
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

    const workspaceData = {
        name: workspaceName,
        description: workspaceDescription,
        terraform_version: terraformVersion,
        github_repo_name: gitRepoName,
        cloud_account: cloudAccountValue,
        cloud_platform: cloudPlatformValue,
        trigger_branch: $('#trigger-branch').val().trim() || null,
        variables: variables,
        secrets: secrets
    };

    console.log("Final workspaceData being sent:", JSON.stringify(workspaceData, null, 2));


    $.ajax({
        url: `/api/v1/projects/${projectName}/workspaces/create`,
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(workspaceData),
        success: function(data) {
            $('#successModal').modal('show');
            $('#modalMessage').text(data.message);
            $('#viewWorkspaceButton').text('View Workspace').off('click').on('click', function() {
                window.location.href = `/dashboard/projects/${projectName}/workspaces/${workspaceName}`;
            });

            $('#create-workspace-form')[0].reset();
            $('#variables-entries').empty();
            $('#git-repo-search').val(null).trigger('change');
            $('#cloud-account-search').val(null).trigger('change');
            $('#create-workspace-button').prop('disabled', false);
            $('#spinner').hide();
        },
        error: function(xhr, status, error) {
            console.error('Error response:', xhr.responseText);
            let errorMessage = 'An unknown error occurred.';
            try {
                const response = JSON.parse(xhr.responseText);
                if (response.detail) {
                    errorMessage = response.detail;
                }
            } catch (e) {
                errorMessage = xhr.responseText || 'An unknown error occurred.';
            }

            $('#failureModal').modal('show');
            $('#failureModalMessage').text(errorMessage);

            $('#create-workspace-button').prop('disabled', false);
            $('#spinner').hide();
        }
    });
}