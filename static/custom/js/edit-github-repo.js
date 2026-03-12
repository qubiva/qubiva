$(document).ready(function() {
    const projectName = Qubiva.url.projectName();
    const repoName = Qubiva.url.get('git_repos');

    // Call the function to fetch GitHub repository details and populate the form
    fetchGithubRepoDetails(projectName, repoName);
    
    // Set up event handlers for form submission and token visibility toggle
    setupEventHandlers();
});

function setupEventHandlers() {
    $('#edit-github-repo-form').on('submit', function(event) {
        event.preventDefault();
        updateGithubRepository();
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
}

function fetchGithubRepoDetails(projectName, repoName) {
    fetch(`/api/v1/projects/${projectName}/git_repos/${repoName}`, {
        headers: {
            'X-Requested-With': 'XMLHttpRequest'
        }
    })
        .then(response => response.json())
        .then(data => {
            // Populate the form fields with the data returned from the API
            $('#repo-name').val(data.repo_name);
            $('#repo-url').val(data.repo_url);
            $('#branch-name').val(data.branch);
            $('#terraform-config-path').val(data.terraform_config_path || ''); // Populate terraform_config_path
            $('#discovery-queries-path').val(data.discovery_queries_path || ''); // Populate discovery_queries_path
            $('#custom-benchmark-path').val(data.custom_benchmark_path || '');
            $('#policy-governance-path').val(data.policy_governance_path || ''); // ADD THIS LINE
            $('#repo-token').val(data.token);

            // Auto-expand source paths card if any paths are configured
            if (data.terraform_config_path || data.discovery_queries_path || data.custom_benchmark_path || data.policy_governance_path) {
                $('#source-paths-card').removeClass('collapsed-card');
                $('#source-paths-card .card-body').show();
                $('#source-paths-card .btn-tool i').removeClass('fa-plus').addClass('fa-minus');
            }
        })
        .catch(error => {
            console.error('Failed to fetch repository details:', error);
            $('#failureModal').modal('show');
            $('#failureModalMessage').text('Failed to fetch GitHub repository details. Please try again.');
        });
}

function updateGithubRepository() {
    $('#edit-github-repo-button').prop('disabled', true);
    $('#spinner').show();

    const projectName = Qubiva.url.projectName();
    const repoName = Qubiva.url.get('git_repos');

    const updatedData = {
        branch: $('#branch-name').val(),
        terraform_config_path: $('#terraform-config-path').val(),
        discovery_queries_path: $('#discovery-queries-path').val(),
        custom_benchmark_path: $('#custom-benchmark-path').val(),
        policy_governance_path: $('#policy-governance-path').val(),
        token: $('#repo-token').val() || null  // Keep null conversion only for token
    };

    fetch(`/api/v1/projects/${projectName}/git_repos/${repoName}/edit`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify(updatedData)
    })
    .then(response => {
        if (!response.ok) {
            // Add this to properly handle non-200 responses
            return response.json().then(err => {
                const d = err.detail;
                throw new Error(typeof d === 'string' ? d : d ? JSON.stringify(d) : 'Failed to update repository');
            });
        }
        return response.json();
    })
    .then(data => {
        $('#successModal').modal('show');
        $('#modalMessage').text(data.message);
    })
    .catch(error => {
        console.error('Error updating GitHub repository:', error);
        $('#failureModal').modal('show');
        $('#failureModalMessage').text(Qubiva.extractError(error, 'Failed to update GitHub repository. Please try again.'));
    })
    .finally(() => {
        $('#edit-github-repo-button').prop('disabled', false);
        $('#spinner').hide();
    });
}
