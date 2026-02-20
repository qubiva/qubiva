$(document).ready(function() {
    const projectName = Qubiva.url.projectName();

    setupEventHandlers();
    togglePlatformFields();

    // Prevent autofill for cloud ID
    $('#cloud-id').attr('autocomplete', 'new-password');

    $('#google-application-credentials, #certificate, #key').css('-webkit-text-security', 'disc').addClass('masked-textarea');

});

function setupEventHandlers() {
    $('#create-cloud-account-form').off('submit').on('submit', function(event) {
        event.preventDefault();
        if (validateForm()) {
            createCloudAccount();
        }
    });

    $('#create-cloud-account-form').on('input', function() {
        $('#create-cloud-account-button').prop('disabled', false);
    });

    $('#cloud-platform').on('change', function() {
        togglePlatformFields();
    });

    $('#secret-type').on('change', toggleSecretFields);

    // Credential method radio button handlers
    $('input[name="credential-method"]').on('change', function() {
        toggleCredentialMethod();
    });

    Qubiva.variableEntry.init();

    $(document).on('click', '.toggle-password', function() {
        togglePasswordVisibility(this);
    });
}

function validateForm() {
    if (!$('#cloud-platform').val()) {
        showError('Please select a cloud platform.');
        return false;
    }

    const credentialMethod = $('input[name="credential-method"]:checked').val();
    
    if (credentialMethod === 'existing') {
        if (!$('#credential-reference').val()) {
            showError('Please select an existing credential.');
            return false;
        }
    } else {
        if (!$('#secret-type').val()) {
            showError('Please select an authentication type.');
            return false;
        }
    }

    const keys = new Set();
    let hasDuplicateKeys = false;
    $('#variables-entries .variable-entry').each(function() {
        const key = $(this).find('input[name="variable-key"]').val().trim();
        if (key) {
            if (keys.has(key)) {
                hasDuplicateKeys = true;
                return false; // Break the loop
            }
            keys.add(key);
        }
    });

    if (hasDuplicateKeys) {
        showError('Duplicate variable keys are not allowed.');
        return false;
    }

    return true;
}

function showError(message) {
    $('#failureModal').modal('show');
    $('#failureModalMessage').text(message);
}

function togglePlatformFields() {
    const cloudPlatform = $('#cloud-platform').val();
    const cloudIdField = $('#cloud-id');
    const cloudIdLabel = $('label[for="cloud-id"]');
    
    // Hide all dependent fields
    $('.form-group:has(#cloud-id), #credential-method-group, #secret-type-group, #aws-external-cert-fields, #aws-access-key-fields, #azure-fields, #gcp-fields').hide();
    
    if (!cloudPlatform) {
        return;
    }

    // Show and update cloud ID field
    $('.form-group:has(#cloud-id)').show();
    
    switch(cloudPlatform) {
        case 'AWS':
            cloudIdLabel.text('AWS Account ID');
            cloudIdField.attr('placeholder', 'Enter 12-digit AWS Account ID');
            break;
        case 'GCP':
            cloudIdLabel.text('Project ID');
            cloudIdField.attr('placeholder', 'Enter GCP Project ID');
            break;
        case 'Azure':
            cloudIdLabel.text('Subscription ID');
            cloudIdField.attr('placeholder', 'Enter Azure Subscription ID');
            break;
    }
    
    $('#credential-method-group').show();
    $('#secret-type-group').show();
    updateSecretTypeOptions(cloudPlatform);
    setupCredentialLookup(cloudPlatform);
    toggleCredentialMethod();
}

function toggleCredentialMethod() {
    const credentialMethod = $('input[name="credential-method"]:checked').val();
    
    if (credentialMethod === 'existing') {
        $('#existing-credential-group').show();
        $('#new-credentials-section').hide();
        
        // Remove required from secret-type when using existing credential
        $('#secret-type').removeAttr('required');
        $('#credential-reference').attr('required', true);
    } else {
        $('#existing-credential-group').hide();
        $('#new-credentials-section').show();
        
        // Add required back to secret-type when providing new credentials
        $('#secret-type').attr('required', true);
        $('#credential-reference').removeAttr('required');
    }
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
                    'AWS': ['external_certificate_authority', 'key_pair'],
                    'Azure': ['azure_service_principal'],
                    'GCP': ['gcp_service_account']
                };
                
                const allowedTypes = platformMap[cloudPlatform] || [];
                
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

function updateSecretTypeOptions(cloudPlatform) {
    const secretTypeSelect = $('#secret-type');
    secretTypeSelect.empty();
    secretTypeSelect.append('<option value="" disabled selected>Select Authentication Type</option>');
    
    if (cloudPlatform === 'AWS') {
        secretTypeSelect.append('<option value="external_certificate_authority">External Certificate Authority</option>');
        secretTypeSelect.append('<option value="key_pair">Access Key Pair</option>');
    } else if (cloudPlatform === 'Azure') {
        secretTypeSelect.append('<option value="azure_service_principal">Service Principal</option>');
    } else if (cloudPlatform === 'GCP') {
        secretTypeSelect.append('<option value="gcp_service_account">Service Account</option>');
    }
}

function toggleSecretFields() {
    const secretType = $('#secret-type').val();
    $('#aws-external-cert-fields, #aws-access-key-fields, #azure-fields, #gcp-fields').hide();
    
    if (secretType === 'external_certificate_authority') {
        $('#aws-external-cert-fields').show();
    } else if (secretType === 'key_pair') {
        $('#aws-access-key-fields').show();
    } else if (secretType === 'azure_service_principal') {
        $('#azure-fields').show();
    } else if (secretType === 'gcp_service_account') {
        $('#gcp-fields').show();
    }
}

function createCloudAccount() {
    $('#create-cloud-account-button').prop('disabled', true);
    $('#spinner').show();

    const projectName = Qubiva.url.projectName();
    const cloudPlatform = $('#cloud-platform').val();
    const cloudId = $('#cloud-id').val();
    const credentialMethod = $('input[name="credential-method"]:checked').val();
    
    const variables = {};
    const secrets = {};

    $('#variables-entries .variable-entry').each(function() {
        const key = $(this).find('input[name="variable-key"]').val().trim();
        const value = $(this).find('input[name="variable-value"]').val().trim();
        const isSecret = $(this).find('input[name="is-secret"]').is(':checked');
        
        if (key) {
            if (isSecret) {
                secrets[key] = value;
            } else {
                variables[key] = value;
            }
        }
    });

    let cloudAccount = {
        cloud_platform: cloudPlatform.toLowerCase(),
        account_id: cloudId,
        variables: variables,
        secrets: secrets
    };

    if (credentialMethod === 'existing') {
        // Use credential reference
        cloudAccount.credential_reference = $('#credential-reference').val();
    } else {
        // Use provided auth secrets
        const secretType = $('#secret-type').val();
        const authSecrets = {
            type: secretType
        };

        if (secretType === 'external_certificate_authority') {
            authSecrets.certificate = $('#certificate').val();
            authSecrets.key = $('#key').val();
            authSecrets.profile_arn = $('#profile-arn').val();
            authSecrets.role_arn = $('#role-arn').val();
            authSecrets.trust_anchor_arn = $('#trust-anchor-arn').val();
        } else if (secretType === 'key_pair') {
            authSecrets.access_key_id = $('#access-key-id').val();
            authSecrets.secret_access_key = $('#secret-access-key').val();
        } else if (secretType === 'azure_service_principal') {
            authSecrets.azure_client_id = $('#azure-client-id').val();
            authSecrets.azure_tenant_id = $('#azure-tenant-id').val();
            authSecrets.azure_client_secret = $('#azure-client-secret').val();
        } else if (secretType === 'gcp_service_account') {
            authSecrets.google_application_credentials = $('#google-application-credentials').val();
        }

        cloudAccount.auth_secrets = authSecrets;
    }

    $.ajax({
        url: `/api/v1/projects/${projectName}/add_cloud_account`,
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(cloudAccount),
        success: function(data) {
            $('#successModal').modal('show');
            $('#modalMessage').text(data.message);
            $('#viewProjectButton').text('View Cloud Account').off('click').on('click', function() {
                window.location.href = `/dashboard/projects/${projectName}/cloud_accounts/${cloudPlatform.toLowerCase()}/${cloudId}`;
            });

            $('#create-cloud-account-form')[0].reset();
            $('#create-cloud-account-button').prop('disabled', false);
            $('#spinner').hide();
            
            // Reset Select2
            if ($('#credential-reference').hasClass('select2-hidden-accessible')) {
                $('#credential-reference').val(null).trigger('change');
            }
            
            // Reset form visibility
            togglePlatformFields();
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

            $('#create-cloud-account-button').prop('disabled', false);
            $('#spinner').hide();
        }
    });
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