$(document).ready(function() {
    let githubAppAvailable = false;
    let availableOrgs = [];
    const projectName = Qubiva.url.projectName();

    // Check GitHub App status on load
    checkGitHubAppStatus();

    // Toggle token visibility (existing code)
    $('#toggle-token-visibility').on('click', function() {
        const tokenField = $('#repo-token');
        const toggleIcon = $('#toggle-token-icon');
        if (tokenField.attr('type') === 'password') {
            tokenField.attr('type', 'text');
            toggleIcon.removeClass('fa-eye').addClass('fa-eye-slash');
        } else {
            tokenField.attr('type', 'password');
            toggleIcon.removeClass('fa-eye-slash').addClass('fa-eye');
        }
    });

    // Repository source change handler
    $('input[name="repo-source"]').on('change', function() {
        const githubPickerGroup = $('#github-picker-group');
        const manualUrlGroup = $('#manual-url-group');
        const repoUrlField = $('#repo-url');
        
        if (this.value === 'github-app') {
            githubPickerGroup.show();
            manualUrlGroup.hide();
            repoUrlField.prop('required', false);
            clearManualFields();
        } else {
            githubPickerGroup.hide();
            manualUrlGroup.show();
            repoUrlField.prop('required', true);
            clearGitHubPickerFields();
        }
    });

    // Automatically populate repository name (existing code)
    $('#repo-url').on('input', function() {
        const url = $(this).val().trim();
        const gitUrlPattern = /^https:\/\/.+\/.+\/.+\.git$/;
        if (gitUrlPattern.test(url)) {
            const urlParts = url.split('/');
            const lastTwoSegments = `${urlParts[urlParts.length - 2]}~${urlParts[urlParts.length - 1].replace('.git', '')}`;
            $('#repo-name').val(lastTwoSegments);
        } else {
            $('#repo-name').val('');
        }
    });

    // Form submission (existing code with jQuery)
    $('#add-github-account-form').on('submit', function(event) {
        event.preventDefault();
        
        const repoSource = $('input[name="repo-source"]:checked').val();
        let repoUrl, repoName;
        
        if (repoSource === 'github-app') {
            const selectedRepo = $('#github-repo-picker').select2('data')[0];
            if (!selectedRepo) {
                alert('Please select a repository');
                return;
            }
            repoUrl = selectedRepo.repo_url;
            repoName = selectedRepo.repo_name;
        } else {
            repoUrl = $('#repo-url').val();
            repoName = $('#repo-name').val();
        }
        
        const workspaceData = {
            repo_url: repoUrl,
            repo_name: repoName,
            branch: $('#branch-name').val() || null,
            terraform_config_path: $('#terraform-config-path').val() || null,
            discovery_queries_path: $('#discovery-queries-path').val() || null,
            custom_benchmark_path: $('#custom-benchmark-path').val() || null,
            policy_governance_path: $('#policy-governance-path').val() || null,
            token: $('#repo-token').val() || null
        };

        $.ajax({
            url: `/api/v1/projects/${projectName}/git_repos/add`,
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(workspaceData),
            success: function(data) {
                if (data.message) {
                    $('#modalMessage').text(data.message);
                    $('#successModal').modal('show');
                    $('#add-github-account-form')[0].reset();
                    // Reset to manual URL mode
                    $('#manual-url-source').prop('checked', true);
                    $('#github-picker-group').hide();
                    $('#manual-url-group').show();
                    $('#repo-url').prop('required', true);
                }
            },
            error: function(xhr) {
                let errorMessage = 'Failed to add GitHub repository. Please try again.';
                try {
                    const response = JSON.parse(xhr.responseText);
                    if (response.detail) {
                        errorMessage = response.detail;
                    }
                } catch (e) {
                    // Use default message
                }
                $('#failureModalMessage').text(errorMessage);
                $('#failureModal').modal('show');
            }
        });
    });

    function checkGitHubAppStatus() {
        $.get('/api/v1/org/github-app/status')
        .done(function(data) {
            const githubAppRadio = $('#github-app-source');
            const githubAppLabel = $('#github-app-label');
            
            if (data.configured && data.installations && data.installations.length > 0) {
                githubAppAvailable = true;
                availableOrgs = data.installations.map(inst => inst.org_name);
                githubAppRadio.prop('disabled', false);
                githubAppLabel.text(`Search from GitHub App (${availableOrgs.length} org(s) available)`);
                initializeGitHubPicker();
            } else {
                githubAppRadio.prop('disabled', true);
                githubAppLabel.text('Search from GitHub App (Not configured)').css('color', '#6c757d');
            }
        })
        .fail(function() {
            $('#github-app-label').text('Search from GitHub App (Error checking status)');
        });
    }

    function initializeGitHubPicker() {
        // COPY the exact pattern from your working Select2
        $('#github-repo-picker').select2({
            theme: 'bootstrap4',
            ajax: {
                url: `/api/v1/org/github-app/${availableOrgs[0]}/repos/search`, // Use first available org
                dataType: 'json',
                delay: 250,
                data: function (params) {
                    console.log("GitHub App search with term:", params.term);
                    return {
                        query: params.term || ''
                    };
                },
                processResults: function (data) {
                    console.log("GitHub App search results:", data);
                    // Transform to match the expected format
                    const results = data.results.map(item => ({
                        id: item.repo_url,  // Use repo_url as id
                        text: item.text,
                        repo_url: item.repo_url,
                        repo_name: item.repo_name
                    }));
                    console.log("Transformed GitHub App results:", results);
                    return { results };
                },
                cache: false
            },
            minimumInputLength: 3, // Allow searching without typing
            placeholder: 'Search repositories from GitHub App...'
        });

        // Handle selection
        $('#github-repo-picker').on('select2:select', function (e) {
            const data = e.params.data;
            console.log("Selected GitHub App repo:", data);
            $('#repo-name').val(data.repo_name);
        });
    }

    function clearManualFields() {
        $('#repo-url').val('');
        $('#repo-name').val('');
    }

    function clearGitHubPickerFields() {
        $('#github-repo-picker').val(null).trigger('change');
        $('#repo-name').val('');
    }
});