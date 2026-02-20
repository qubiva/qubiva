$(document).ready(function() {
    const projectName = Qubiva.url.projectName();

    setupEventHandlers();
    togglePlatformFields();

    // Prevent autofill for credential name
    $('#credential-name').attr('autocomplete', 'new-password');
});

function setupEventHandlers() {
    $('#create-credential-form').off('submit').on('submit', function(event) {
        event.preventDefault();
        if (validateForm()) {
            createCredential();
        }
    });

    $('#create-credential-form').on('input', function() {
        $('#create-credential-button').prop('disabled', false);
    });

    $('#cloud-platform').on('change', function() {
        togglePlatformFields();
    });

    $('#credential-type').on('change', toggleCredentialFields);

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
    if (!$('#credential-name').val().trim()) {
        showError('Please enter a credential name.');
        return false;
    }

    if (!$('#cloud-platform').val()) {
        showError('Please select a cloud platform.');
        return false;
    }

    if (!$('#credential-type').val()) {
        showError('Please select an authentication type.');
        return false;
    }

    // Validate required fields based on credential type
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

function togglePlatformFields() {
    const cloudPlatform = $('#cloud-platform').val();
    
    // Hide all dependent fields
    $('#credential-type-group, #aws-external-cert-fields, #aws-access-key-fields, #azure-fields, #gcp-fields').hide();
    
    if (!cloudPlatform) {
        return;
    }

    $('#credential-type-group').show();
    updateCredentialTypeOptions(cloudPlatform);
}

function updateCredentialTypeOptions(cloudPlatform) {
    const credentialTypeSelect = $('#credential-type');
    credentialTypeSelect.empty();
    credentialTypeSelect.append('<option value="" disabled selected>Select Authentication Type</option>');
    
    if (cloudPlatform === 'AWS') {
        credentialTypeSelect.append('<option value="external_certificate_authority">External Certificate Authority</option>');
        credentialTypeSelect.append('<option value="key_pair">Access Key Pair</option>');
    } else if (cloudPlatform === 'Azure') {
        credentialTypeSelect.append('<option value="azure_service_principal">Service Principal</option>');
    } else if (cloudPlatform === 'GCP') {
        credentialTypeSelect.append('<option value="gcp_service_account">Service Account</option>');
    }
}

function toggleCredentialFields() {
    const credentialType = $('#credential-type').val();
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

function createCredential() {
    $('#create-credential-button').prop('disabled', true);
    $('#spinner').show();

    const projectName = Qubiva.url.projectName();
    const credentialName = $('#credential-name').val().trim();
    const cloudPlatform = $('#cloud-platform').val();
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

    const credentialData = {
        credential_name: credentialName,
        credential_type: credentialType, // Dynamic based on selected authentication type
        auth_secrets: authSecrets
    };

    $.ajax({
        url: `/api/v1/projects/${projectName}/credentials`,
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(credentialData),
        success: function(data) {
            $('#successModal').modal('show');
            $('#modalMessage').text(data.message);
            $('#viewCredentialButton').text('View Credentials').off('click').on('click', function() {
                window.location.href = `/dashboard/projects/${projectName}/credentials`;
            });

            $('#create-credential-form')[0].reset();
            $('#create-credential-button').prop('disabled', false);
            $('#spinner').hide();
            togglePlatformFields(); // Reset form visibility
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

            $('#create-credential-button').prop('disabled', false);
            $('#spinner').hide();
        }
    });
}