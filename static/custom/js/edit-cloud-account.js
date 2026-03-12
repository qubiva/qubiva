$(document).ready(function() {
    const projectName = Qubiva.url.projectName();
    const cloudPlatform = Qubiva.url.cloudPlatform();
    const accountId = Qubiva.url.accountId();

    setupEventHandlers();
    Qubiva.variableEntry.init();
    fetchCloudAccountDetails(projectName, cloudPlatform, accountId);
});

function setupEventHandlers() {
    $('#edit-cloud-account-form').off('submit').on('submit', function(event) {
        event.preventDefault();
        updateCloudAccount();
    });

    $('#edit-cloud-account-form').on('input', function() {
        $('#edit-cloud-account-button').prop('disabled', false);
    });

    $('#cloud-platform').on('change', function() {
        updateAuthTypeOptions();
        toggleAuthTypeFields();
    });

    $('#secret-type').on('change', function() {
        toggleAuthTypeFields();
    });

    // Credential method radio button handlers
    $('input[name="credential-method"]').on('change', function() {
        toggleCredentialMethod();
    });

    $(document).on('click', '.toggle-password', function() {
        togglePasswordVisibility(this);
    });
}

function setupCredentialLookup(cloudPlatform) {
    const projectName = Qubiva.url.projectName();
    
    // Destroy existing Select2 if it exists
    if ($('#credential-reference').hasClass('select2-hidden-accessible')) {
        $('#credential-reference').select2('destroy');
    }
    
    $('#credential-reference').select2({
        theme: 'bootstrap4',
        placeholder: 'Search and select a credential...',
        allowClear: true,
        ajax: {
            url: `/api/v1/projects/${projectName}/credentials/search`,
            dataType: 'json',
            delay: 250,
            data: function (params) {
                return {
                    query: params.term || '' // search term
                };
            },
            processResults: function (data) {
                // Filter credentials by cloud platform
                const platformMap = {
                    'aws': ['external_certificate_authority', 'key_pair'],
                    'azure': ['azure_service_principal'],
                    'gcp': ['gcp_service_account']
                };
                
                const allowedTypes = platformMap[cloudPlatform.toLowerCase()] || [];
                
                const filteredResults = data.results.filter(credential => 
                    allowedTypes.includes(credential.credential_type)
                );
                
                return {
                    results: filteredResults.map(credential => ({
                        id: credential.credential_name,
                        text: credential.credential_name
                    }))
                };
            },
            cache: true
        },
        minimumInputLength: 1, // Allow dropdown to open without typing
        templateResult: function(credential) {
            if (credential.loading) {
                return credential.text;
            }
            return $('<span>' + credential.text + '</span>');
        },
        templateSelection: function(credential) {
            return credential.text;
        }
    });
}

function toggleCredentialMethod() {
    const credentialMethod = $('input[name="credential-method"]:checked').val();
    
    if (credentialMethod === 'existing') {
        $('#existing-credential-group').show();
        $('#new-credentials-section').hide();
        
        // Remove required from secret-type when using existing credential
        $('#secret-type').removeAttr('required');
        $('#credential-reference').attr('required', true);
        
        // FORCE the Select2 to refresh and show
        if ($('#credential-reference').hasClass('select2-hidden-accessible')) {
            $('#credential-reference').select2('open').select2('close');
        }
    } else {
        $('#existing-credential-group').hide();
        $('#new-credentials-section').show();
        
        // Add required back to secret-type when providing new credentials
        $('#secret-type').attr('required', true);
        $('#credential-reference').removeAttr('required');
        
        // **NEW: Populate the auth type dropdown when switching to new credentials**
        updateAuthTypeOptions();
        
        // **NEW: Also call toggleAuthTypeFields to hide any visible fields**
        toggleAuthTypeFields();
    }
}

function updateAuthTypeOptions() {
    const cloudPlatform = $('#cloud-platform').val().toLowerCase(); // Ensure lowercase
    const authTypeSelect = $('#secret-type');
    
    console.log('Cloud platform for auth options:', cloudPlatform); // Debug line
    
    authTypeSelect.empty();
    authTypeSelect.append('<option value="" disabled selected>Select Authentication Type</option>');

    if (cloudPlatform === 'aws') {
        authTypeSelect.append('<option value="external_certificate_authority">External Certificate Authority</option>');
        authTypeSelect.append('<option value="key_pair">Access Key Pair</option>');
        console.log('Added AWS options'); // Debug line
    } else if (cloudPlatform === 'azure') {
        authTypeSelect.append('<option value="azure_service_principal">Service Principal</option>');
        console.log('Added Azure options'); // Debug line
    } else if (cloudPlatform === 'gcp') {
        authTypeSelect.append('<option value="gcp_service_account">Service Account</option>');
        console.log('Added GCP options'); // Debug line
    } else {
        console.log('Unknown cloud platform:', cloudPlatform); // Debug line
    }
    
    // Make sure the secret-type-group is shown
    $('#secret-type-group').show();
    
    console.log('Auth type options count:', authTypeSelect.find('option').length); // Debug line
}

function toggleAuthTypeFields() {
    const cloudPlatform = $('#cloud-platform').val().toLowerCase(); // Normalize to lowercase
    const authType = $('#secret-type').val();

    // Hide all platform-specific fields by default
    $('#aws-external-ca-fields, #aws-key-pair-fields, #azure-service-principal-fields, #gcp-service-account-fields').hide();

    // Toggle fields based on platform and auth type
    if (cloudPlatform === 'aws') {
        if (authType === 'external_certificate_authority') {
            $('#aws-external-ca-fields').show();
        } else if (authType === 'key_pair') {
            $('#aws-key-pair-fields').show();
        }
    } else if (cloudPlatform === 'azure') {
        if (authType === 'azure_service_principal') {
            $('#azure-service-principal-fields').show(); // Ensure these fields are visible
        }
    } else if (cloudPlatform === 'gcp') {
        if (authType === 'gcp_service_account') {
            $('#gcp-service-account-fields').show();
        }
    }
}

function fetchCloudAccountDetails(projectName, cloudPlatform, accountId) {
    $.ajax({
        url: `/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatform.toLowerCase()}/${accountId}`, // Convert to lowercase
        method: 'GET',
        success: function(data) {
            populateForm(data);
        },
        error: function(xhr, status, error) {
            console.error('Error fetching cloud account details:', error);
            $('#failureModal').modal('show');
            $('#failureModalMessage').text('Failed to fetch cloud account details. Please try again.');
        }
    });
}

function populateForm(data) {
    const cloudPlatform = data.cloud_platform.toLowerCase();

    // Set Cloud Platform and Account ID
    $('#cloud-platform').val(cloudPlatform);
    $('#cloud-id').val(data.account_id);

    $('#credential-method-group').show();

    // Setup credential lookup for this platform
    setupCredentialLookup(cloudPlatform);

    // Check if this cloud account uses credential reference or direct auth_secrets
    if (data.credential_reference) {
        // Using existing credential
        $('#use-existing-credential').prop('checked', true);
        $('#credential-reference').append(new Option(data.credential_reference, data.credential_reference, true, true));
        toggleCredentialMethod();
    } else if (data.auth_secrets) {
        // Using direct auth secrets
        $('#provide-credentials').prop('checked', true);
        const authType = data.auth_secrets.type;

        // First, call toggleCredentialMethod to show the right sections
        toggleCredentialMethod();

        // Then set the Authentication Type (this must come after toggleCredentialMethod)
        $('#secret-type').val(authType);

        // Toggle fields to display the correct section
        toggleAuthTypeFields();

        // Populate fields for Azure
        if (cloudPlatform === 'azure') {
            if (authType === 'azure_service_principal') {
                $('#azure-client-id').val(data.auth_secrets.azure_client_id || '');
                $('#azure-tenant-id').val(data.auth_secrets.azure_tenant_id || '');
                $('#azure-client-secret').val(data.auth_secrets.azure_client_secret || '');
            }
        }

        // Populate fields for AWS
        if (cloudPlatform === 'aws') {
            if (authType === 'external_certificate_authority') {
                $('#certificate').val(data.auth_secrets.certificate || '');
                $('#key').val(data.auth_secrets.key || '');
                $('#profile-arn').val(data.auth_secrets.profile_arn || '');
                $('#role-arn').val(data.auth_secrets.role_arn || '');
                $('#trust-anchor-arn').val(data.auth_secrets.trust_anchor_arn || '');
            } else if (authType === 'key_pair') {
                $('#access-key-id').val(data.auth_secrets.access_key_id || '');
                $('#secret-access-key').val(data.auth_secrets.secret_access_key || '');
            }
        }

        // Populate fields for GCP
        if (cloudPlatform === 'gcp') {
            if (authType === 'gcp_service_account') {
                $('#google-application-credentials').val(data.auth_secrets.google_application_credentials || '');
            }
        }

        console.log('Auth type set to:', authType); // Debug line
        console.log('Secret type value:', $('#secret-type').val()); // Debug line
    } else {
        // Fallback: no auth method configured
        $('#provide-credentials').prop('checked', true);
        toggleCredentialMethod();
    }

    // Populate Variables and Secrets
    $('#variables-entries').empty();
    for (const [key, value] of Object.entries(data.variables || {})) {
        Qubiva.variableEntry.add(key, value, false);
    }
    for (const [key, value] of Object.entries(data.secrets || {})) {
        Qubiva.variableEntry.add(key, value, true);
    }

    // Initialize sensitive textareas as hidden and minify JSON if needed
    $('#certificate, #key, #google-application-credentials').each(function() {
        const fieldId = $(this).attr('id');
        
        // Minify JSON for GCP credentials
        if (fieldId === 'google-application-credentials' && $(this).val().trim()) {
            try {
                const parsed = JSON.parse($(this).val());
                $(this).val(JSON.stringify(parsed)); // Minified format
            } catch (e) {
                // Not valid JSON, keep as-is
                console.log('Content is not valid JSON, keeping original format');
            }
        }
        
        // Apply masking
        $(this).css('-webkit-text-security', 'disc').addClass('masked-textarea');
    });
}

function updateCloudAccount() {
    $('#edit-cloud-account-button').prop('disabled', true);
    $('#spinner').show();

    const projectName = Qubiva.url.projectName();
    const cloudPlatform = $('#cloud-platform').val();
    const cloudId = $('#cloud-id').val();
    const credentialMethod = $('input[name="credential-method"]:checked').val();
    
    const variables = {};
    const secrets = {};

    // Collect variables and secrets
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

    let updatedAccount = {
        variables: variables,
        secrets: secrets
    };

    if (credentialMethod === 'existing') {
        // Use credential reference - ONLY send credential_reference
        const selectedCredential = $('#credential-reference').val();
        if (!selectedCredential) {
            showError('Please select a credential.');
            $('#edit-cloud-account-button').prop('disabled', false);
            $('#spinner').hide();
            return;
        }
        updatedAccount.credential_reference = selectedCredential;
        // Don't send auth_secrets at all
    } else {
        // Use provided auth secrets - ONLY send auth_secrets
        const authType = $('#secret-type').val();
        if (!authType) {
            showError('Please select an authentication type.');
            $('#edit-cloud-account-button').prop('disabled', false);
            $('#spinner').hide();
            return;
        }
        
        updatedAccount.auth_secrets = {
            type: authType
        };

        // Always include credentials based on the selected platform and auth type
        if (cloudPlatform.toLowerCase() === 'aws') {
            if (authType === 'external_certificate_authority') {
                updatedAccount.auth_secrets.certificate = $('#certificate').val();
                updatedAccount.auth_secrets.key = $('#key').val();
                updatedAccount.auth_secrets.profile_arn = $('#profile-arn').val();
                updatedAccount.auth_secrets.role_arn = $('#role-arn').val();
                updatedAccount.auth_secrets.trust_anchor_arn = $('#trust-anchor-arn').val();
            } else if (authType === 'key_pair') {
                updatedAccount.auth_secrets.access_key_id = $('#access-key-id').val();
                updatedAccount.auth_secrets.secret_access_key = $('#secret-access-key').val();
            }
        } else if (cloudPlatform.toLowerCase() === 'azure') {
            updatedAccount.auth_secrets.azure_client_id = $('#azure-client-id').val();
            updatedAccount.auth_secrets.azure_tenant_id = $('#azure-tenant-id').val();
            updatedAccount.auth_secrets.azure_client_secret = $('#azure-client-secret').val();
        } else if (cloudPlatform.toLowerCase() === 'gcp') {
            updatedAccount.auth_secrets.google_application_credentials = $('#google-application-credentials').val();
        }
        // Don't send credential_reference at all
    }

    console.log('Sending data:', updatedAccount); // Debug line

    // Send data to the backend
    $.ajax({
        url: `/api/v1/projects/${projectName}/cloud_accounts/${cloudPlatform}/${cloudId}/edit`,
        method: 'PUT',
        contentType: 'application/json',
        data: JSON.stringify(updatedAccount),
        success: function(data) {
            $('#successModal').modal('show');
            $('#modalMessage').text(data.message);
            $('#viewProjectButton').text('View Cloud Account').off('click').on('click', function() {
                window.location.href = `/dashboard/projects/${projectName}/cloud_accounts/${cloudPlatform}/${cloudId}`;
            });
            $('#edit-cloud-account-button').prop('disabled', false);
            $('#spinner').hide();
        },
        error: function(xhr, status, error) {
            console.error('Error updating cloud account:', error);
            $('#failureModal').modal('show');
            $('#failureModalMessage').text(xhr.responseJSON?.detail || 'Failed to update cloud account. Please try again.');
            $('#edit-cloud-account-button').prop('disabled', false);
            $('#spinner').hide();
        }
    });
}

function showError(message) {
    $('#failureModal').modal('show');
    $('#failureModalMessage').text(message);
}

function togglePasswordVisibility(button) {
    const targetId = $(button).data('target');
    const targetField = $('#' + targetId);
    const icon = $(button).find('i');
    
    if (targetField.length === 0) {
        console.error('Target field not found:', targetId);
        return;
    }
    
    if (targetField.is('textarea')) {
        const currentStyle = targetField.css('-webkit-text-security');
        if (currentStyle === 'disc') {
            // Show the text (formatted)
            let content = targetField.val();
            
            // Try to format JSON if it's the GCP credentials field
            if (targetId === 'google-application-credentials' && content.trim()) {
                try {
                    const parsed = JSON.parse(content);
                    content = JSON.stringify(parsed, null, 2); // Pretty format with 2-space indentation
                    targetField.val(content);
                } catch (e) {
                    // Not valid JSON, keep as-is
                    console.log('Content is not valid JSON, keeping original format');
                }
            }
            
            targetField.css('-webkit-text-security', 'none');
            targetField.removeClass('masked-textarea');
            icon.removeClass('fa-eye').addClass('fa-eye-slash');
        } else {
            // Hide the text (minified for JSON)
            let content = targetField.val();
            
            // Try to minify JSON if it's the GCP credentials field
            if (targetId === 'google-application-credentials' && content.trim()) {
                try {
                    const parsed = JSON.parse(content);
                    content = JSON.stringify(parsed); // Minified format (no spaces/newlines)
                    targetField.val(content);
                } catch (e) {
                    // Not valid JSON, keep as-is
                    console.log('Content is not valid JSON, keeping original format');
                }
            }
            
            targetField.css('-webkit-text-security', 'disc');
            targetField.addClass('masked-textarea');
            icon.removeClass('fa-eye-slash').addClass('fa-eye');
        }
    } else {
        // For input elements (same as before)
        const currentType = targetField.attr('type');
        if (currentType === 'password') {
            targetField.attr('type', 'text');
            icon.removeClass('fa-eye').addClass('fa-eye-slash');
        } else {
            targetField.attr('type', 'password');
            icon.removeClass('fa-eye-slash').addClass('fa-eye');
        }
    }
}