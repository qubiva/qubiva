$(document).ready(function() {
    const projectName = Qubiva.url.projectName();
    const credentialName = Qubiva.url.get('credentials');

    // Call the function to fetch credential details and populate the form
    fetchCredentialDetails(projectName, credentialName);
    
    // Set up event handlers for form submission
    setupEventHandlers();
});

function setupEventHandlers() {
    $('#edit-credential-form').on('submit', function(event) {
        event.preventDefault();
        if (validateForm()) {
            updateCredential();
        }
    });

    $('#credential-type').on('change', function() {
        toggleCredentialFields($(this).val());
    });

    // toggle password visibility for any .toggle-password button
    $(document).on('click', '.toggle-password', function () {
        const selector = $(this).data('target');
        const $input = $(selector);
        if (!$input.length) return;

        if ($input.is('input')) {
            // normal password inputs
            const toText = $input.attr('type') === 'password';
            $input.attr('type', toText ? 'text' : 'password');
        } else if ($input.is('textarea')) {
            // textarea toggle via CSS class
            $input.toggleClass('hide-credentials');
        }

        const $icon = $(this).find('i');
        if ($icon.length) {
            $icon.toggleClass('fa-eye');
            $icon.toggleClass('fa-eye-slash');
        }
        });

}

function validateForm() {
    const credentialType = $('#credential-type').val();
    
    if (credentialType === 'external_certificate_authority') {
        if (!$('#certificate').val().trim() || !$('#key').val().trim()) {
            showError('Certificate and Key are required for External Certificate Authority.');
            return false;
        }
    } else if (credentialType === 'key_pair') {
        if (!$('#access-key-id').val().trim() || !$('#secret-access-key').val().trim()) {
            showError('Access Key ID and Secret Access Key are required.');
            return false;
        }
    } else if (credentialType === 'azure_service_principal') {
        if (!$('#azure-client-id').val().trim() || !$('#azure-tenant-id').val().trim() || !$('#azure-client-secret').val().trim()) {
            showError('Client ID, Tenant ID, and Client Secret are required for Azure Service Principal.');
            return false;
        }
    } else if (credentialType === 'gcp_service_account') {
        if (!$('#google-application-credentials').val().trim()) {
            showError('Application Credentials are required for GCP Service Account.');
            return false;
        }
    }

    return true;
}

function showError(message) {
    $('#failureModal').modal('show');
    $('#failureModalMessage').text(message);
}

function fetchCredentialDetails(projectName, credentialName) {
    fetch(`/api/v1/projects/${projectName}/credentials/${credentialName}`, {
        headers: {
            'X-Requested-With': 'XMLHttpRequest'
        }
    })
        .then(response => response.json())
        .then(data => {
            // Populate the form fields with the data returned from the API
            $('#credential-name').val(data.credential_name);
            
            // Get the actual current auth type from auth_secrets
            const currentAuthType = data.auth_secrets.type;
            
            // Determine cloud platform from the current auth type in auth_secrets
            let cloudPlatform = '';
            if (currentAuthType === 'external_certificate_authority' || currentAuthType === 'key_pair') {
                cloudPlatform = 'AWS';
            } else if (currentAuthType === 'azure_service_principal') {
                cloudPlatform = 'Azure';
            } else if (currentAuthType === 'gcp_service_account') {
                cloudPlatform = 'GCP';
            }
            
            $('#cloud-platform').val(cloudPlatform);
            updateCredentialTypeOptions(cloudPlatform);
            $('#credential-type').val(currentAuthType);
            
            // Show appropriate fields and populate them
            toggleCredentialFields(currentAuthType);
            
            const authSecrets = data.auth_secrets;
            if (currentAuthType === 'external_certificate_authority') {
                $('#certificate').val(authSecrets.certificate || '');
                $('#key').val(authSecrets.key || '');
                $('#profile-arn').val(authSecrets.profile_arn || '');
                $('#role-arn').val(authSecrets.role_arn || '');
                $('#trust-anchor-arn').val(authSecrets.trust_anchor_arn || '');
            } else if (currentAuthType === 'key_pair') {
                $('#access-key-id').val(authSecrets.access_key_id || '');
                $('#secret-access-key').val(authSecrets.secret_access_key || '');
            } else if (currentAuthType === 'azure_service_principal') {
                $('#azure-client-id').val(authSecrets.azure_client_id || '');
                $('#azure-tenant-id').val(authSecrets.azure_tenant_id || '');
                $('#azure-client-secret').val(authSecrets.azure_client_secret || '');
            } else if (currentAuthType === 'gcp_service_account') {
                $('#google-application-credentials').val(authSecrets.google_application_credentials || '');
            }
        })
        .catch(error => {
            console.error('Failed to fetch credential details:', error);
            $('#failureModal').modal('show');
            $('#failureModalMessage').text('Failed to fetch credential details. Please try again.');
        });
}

function updateCredentialTypeOptions(cloudPlatform) {
    const credentialTypeSelect = $('#credential-type');
    credentialTypeSelect.empty();
    credentialTypeSelect.append('<option value="" disabled>Select Authentication Type</option>');
    
    if (cloudPlatform === 'AWS') {
        credentialTypeSelect.append('<option value="external_certificate_authority">External Certificate Authority</option>');
        credentialTypeSelect.append('<option value="key_pair">Access Key Pair</option>');
    } else if (cloudPlatform === 'Azure') {
        credentialTypeSelect.append('<option value="azure_service_principal">Service Principal</option>');
    } else if (cloudPlatform === 'GCP') {
        credentialTypeSelect.append('<option value="gcp_service_account">Service Account</option>');
    }
}

function toggleCredentialFields(credentialType) {
    $('#aws-external-cert-fields, #aws-access-key-fields, #azure-fields, #gcp-fields').hide();
    
    if (credentialType === 'external_certificate_authority') {
        $('#aws-external-cert-fields').show();
    } else if (credentialType === 'key_pair') {
        $('#aws-access-key-fields').show();
    } else if (credentialType === 'azure_service_principal') {
        $('#azure-fields').show();
    } else if (credentialType === 'gcp_service_account') {
        $('#gcp-fields').show();
    }
}

function updateCredential() {
    $('#edit-credential-button').prop('disabled', true);
    $('#spinner').show();

    const projectName = Qubiva.url.projectName();
    const credentialName = Qubiva.url.get('credentials');
    const credentialType = $('#credential-type').val();
    
    const authSecrets = {
        type: credentialType
    };

    if (credentialType === 'external_certificate_authority') {
        authSecrets.certificate = $('#certificate').val();
        authSecrets.key = $('#key').val();
        authSecrets.profile_arn = $('#profile-arn').val();
        authSecrets.role_arn = $('#role-arn').val();
        authSecrets.trust_anchor_arn = $('#trust-anchor-arn').val();
    } else if (credentialType === 'key_pair') {
        authSecrets.access_key_id = $('#access-key-id').val();
        authSecrets.secret_access_key = $('#secret-access-key').val();
    } else if (credentialType === 'azure_service_principal') {
        authSecrets.azure_client_id = $('#azure-client-id').val();
        authSecrets.azure_tenant_id = $('#azure-tenant-id').val();
        authSecrets.azure_client_secret = $('#azure-client-secret').val();
    } else if (credentialType === 'gcp_service_account') {
        authSecrets.google_application_credentials = $('#google-application-credentials').val();
    }

    const updatedData = {
        auth_secrets: authSecrets
    };

    $.ajax({
        url: `/api/v1/projects/${projectName}/credentials/${credentialName}`,
        method: 'PUT',
        contentType: 'application/json',
        data: JSON.stringify(updatedData),
        success: function(data) {
            $('#successModal').modal('show');
            $('#modalMessage').text(data.message);
            
            // Refresh the form with updated data
            const projectName = Qubiva.url.projectName();
            const credentialName = Qubiva.url.get('credentials');
            fetchCredentialDetails(projectName, credentialName);
        },
        error: function(xhr, status, error) {
            console.error('Error response:', xhr.responseText);
            console.error('Error details:', status, error);

            let errorMessage = 'An unknown error occurred.';
            try {
                const response = JSON.parse(xhr.responseText);
                if (response.detail) {
                    errorMessage = response.detail;
                }
            } catch (e) {
                errorMessage = xhr.responseText || 'An unknown error occurred.';
            }

            showError(errorMessage);
        },
        complete: function() {
            $('#edit-credential-button').prop('disabled', false);
            $('#spinner').hide();
        }
    });
}