let githubAppAvailable = false;
let availableOrgs = [];

$(document).ready(function() {
    // Check GitHub App status on load
    checkGitHubAppStatus();

    // Load existing org policy repo configuration when page loads
    fetchOrgPolicyRepo();

    // Set up event handlers for form submission and token visibility toggle
    setupEventHandlers();
});

function setupEventHandlers() {
    $('#org-policy-repo-form').on('submit', function(event) {
        event.preventDefault();
        saveOrgPolicyRepo();
    });

    $('#toggle-token-visibility').on('click', function() {
        const tokenInput = $('#repo-token');
        const tokenIcon = $('#toggle-token-icon');
        if (tokenInput.attr('type') === 'password') {
            tokenInput.attr('type', 'text');
            tokenIcon.removeClass('fa-eye').addClass('fa-eye-slash');
        } else {
            tokenInput.attr('type', 'password');
            tokenIcon.removeClass('fa-eye-slash').addClass('fa-eye');
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
}

function fetchOrgPolicyRepo() {
    fetch('/api/v1/org/policy-repo', {
        headers: {
            'X-Requested-With': 'XMLHttpRequest'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.repo) {
            // Populate the form fields with existing data
            $('#repo-url').val(data.repo.repo_url || '');
            $('#branch-name').val(data.repo.branch || '');
            $('#policy-path').val(data.repo.policy_path || '');
            $('#conftest-version').val(data.repo.conftest_version || '');
            $('#repo-token').val(data.repo.token || '');
        }
        // If no repo data, form remains empty (new configuration)
    })
    .catch(error => {
        console.error('Failed to fetch org policy repo:', error);
        // Don't show error modal for fetch - user might be creating new config
    });
}

function saveOrgPolicyRepo() {
    $('#save-org-policy-button').prop('disabled', true);
    $('#spinner').show();

    const repoSource = $('input[name="repo-source"]:checked').val();
    let repoUrl;

    if (repoSource === 'github-app') {
        const selectedRepo = $('#github-repo-picker').select2('data')[0];
        if (!selectedRepo) {
            alert('Please select a repository');
            $('#save-org-policy-button').prop('disabled', false);
            $('#spinner').hide();
            return;
        }
        repoUrl = selectedRepo.repo_url;
    } else {
        repoUrl = $('#repo-url').val();
    }

    const formData = {
        repo_url: repoUrl,
        branch: $('#branch-name').val() || null,
        policy_path: $('#policy-path').val() || null,
        conftest_version: $('#conftest-version').val() || null,
        token: $('#repo-token').val() || null
    };

    fetch('/api/v1/org/policy-repo', {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify(formData)
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(err => {
                const d = err.detail;
                throw new Error(typeof d === 'string' ? d : d ? JSON.stringify(d) : 'Failed to save policy repository');
            });
        }
        return response.json();
    })
    .then(data => {
        $('#successModal').modal('show');
        $('#modalMessage').text(data.message);
    })
    .catch(error => {
        console.error('Error saving org policy repository:', error);
        $('#failureModal').modal('show');
        $('#failureModalMessage').text(Qubiva.extractError(error, 'Failed to save organization policy repository. Please try again.'));
    })
    .finally(() => {
        $('#save-org-policy-button').prop('disabled', false);
        $('#spinner').hide();
    });
}

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
    $('#github-repo-picker').select2({
        theme: 'bootstrap4',
        ajax: {
            url: `/api/v1/org/github-app/${availableOrgs[0]}/repos/search`,
            dataType: 'json',
            delay: 250,
            data: function (params) {
                return {
                    query: params.term || ''
                };
            },
            processResults: function (data) {
                const results = data.results.map(item => ({
                    id: item.repo_url,
                    text: item.text,
                    repo_url: item.repo_url,
                    repo_name: item.repo_name
                }));
                return { results };
            },
            cache: false
        },
        minimumInputLength: 0,
        placeholder: 'Search repositories from GitHub App...'
    });

    // Handle selection
    $('#github-repo-picker').on('select2:select', function (e) {
        const data = e.params.data;
        console.log("Selected GitHub App repo for org policy:", data);
    });
}

function clearManualFields() {
    $('#repo-url').val('');
}

function clearGitHubPickerFields() {
    $('#github-repo-picker').val(null).trigger('change');
}