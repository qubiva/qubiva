$(document).ready(function() {
    console.log('=== SSO Config Page Loading ===');

    // Load org roles and SSO config
    loadOrgRoles().then(loadSSOConfig);

    // Set SP metadata URL using configured app base URL (falls back to current origin for dev)
    const baseUrl = window.APP_BASE_URL || `${window.location.protocol}//${window.location.host}`;
    const spMetadataUrl = `${baseUrl}/api/v1/sso/metadata`;
    const acsUrl = `${baseUrl}/api/v1/sso/acs`;

    $('#sp-metadata-url').val(spMetadataUrl);
    $('#acs-url').text(acsUrl);

    // Copy SP metadata URL
    $('#copy-sp-metadata').on('click', function() {
        const url = $('#sp-metadata-url').val();
        navigator.clipboard.writeText(url).then(() => {
            $(this).html('<i class="fas fa-check"></i> Copied!');
            setTimeout(() => $(this).html('<i class="fas fa-copy"></i> Copy'), 2000);
        });
    });

    // Copy ACS URL
    $('#copy-acs-url').on('click', function() {
        navigator.clipboard.writeText($('#acs-url').text()).then(() => {
            $(this).html('<i class="fas fa-check"></i>');
            setTimeout(() => $(this).html('<i class="fas fa-copy"></i>'), 2000);
        });
    });

    // Toggle access control options
    $('input[name="access-control-mode"]').on('change', function() {
        $('#domain-whitelist').collapse('hide');
        $('#group-whitelist').collapse('hide');
        if ($(this).val() === 'email_domain') {
            $('#domain-whitelist').collapse('show');
        } else if ($(this).val() === 'group_whitelist') {
            $('#group-whitelist').collapse('show');
        }
    });

    // Toggle group mapping
    $('#group-mapping-enabled').on('change', function() {
        $('#group-mapping-config').collapse($(this).is(':checked') ? 'show' : 'hide');
    });

    // Add group mapping row
    $('#add-group-mapping').on('click', function() {
        addGroupMappingRow();
    });

    // Form submission
    $('#sso-config-form').on('submit', function(e) {
        e.preventDefault();
        saveSSOConfig();
    });

    // Reset form
    $('#reset-sso-config').on('click', function() {
        $('#resetFormModal').modal('show');
    });

    // Reset confirm handler
    $('#confirmResetBtn').on('click', function() {
        $('#resetFormModal').modal('hide');
        loadSSOConfig();
    });

    // Button event bindings (replacing inline onclick)
    $('#check-sso-status').on('click', function(e) { e.preventDefault(); checkSSOStatus($(this)); });
    $('#reparse-metadata').on('click', function(e) { e.preventDefault(); reparseMetadata($(this)); });
    $('#test-sso-login').on('click', function(e) { e.preventDefault(); testSSOLogin($(this)); });
    $('#delete-sso-config').on('click', function(e) { e.preventDefault(); deleteSSOConfig(); });

    // Delete confirm handler
    $('#confirmDeleteBtn').on('click', function() {
        const $btn = $(this);
        $('#deleteConfirmModal').modal('hide');
        setButtonLoading($('#delete-sso-config'), true);

        $.ajax({
            url: '/api/v1/org/sso/config',
            method: 'DELETE',
            success: function(data) {
                showToast('SSO configuration deleted successfully', 'success');
                setTimeout(() => window.location.reload(), 1500);
            },
            error: function(xhr) {
                showToast('Failed to delete SSO config: ' + (xhr.responseJSON?.detail || 'Unknown error'), 'error');
            },
            complete: function() {
                setButtonLoading($('#delete-sso-config'), false);
            }
        });
    });

    // Re-parse confirm handler
    $('#confirmReparseBtn').on('click', function() {
        $('#reparseConfirmModal').modal('hide');
        const $btn = $('#reparse-metadata');
        setButtonLoading($btn, true);

        $.ajax({
            url: '/api/v1/org/sso/reparse-metadata',
            method: 'POST',
            success: function(data) {
                if (data.success) {
                    showToast('Metadata re-parsed successfully', 'success');
                    setTimeout(() => loadSSOConfig(), 1000);
                } else {
                    showToast('Failed to re-parse metadata', 'error');
                }
            },
            error: function(xhr) {
                showToast('Error re-parsing metadata: ' + (xhr.responseJSON?.detail || 'Unknown error'), 'error');
            },
            complete: function() {
                setButtonLoading($btn, false);
            }
        });
    });
});

// ============================================
// Toast Notifications (SweetAlert2)
// ============================================

function showToast(message, type) {
    const iconMap = { success: 'success', error: 'error', warning: 'warning', info: 'info' };
    Swal.fire({
        toast: true,
        position: 'top-end',
        icon: iconMap[type] || 'info',
        title: message,
        showConfirmButton: false,
        showCloseButton: true,
    });
}

// ============================================
// Loading State Helper
// ============================================

function setButtonLoading($btn, loading) {
    if (loading) {
        $btn.data('original-html', $btn.html());
        const label = $btn.text().trim();
        $btn.prop('disabled', true).html('<i class="fas fa-spinner fa-spin mr-1"></i> ' + label + '...');
    } else {
        $btn.prop('disabled', false).html($btn.data('original-html'));
    }
}

// ============================================
// Data Loading
// ============================================

function loadOrgRoles() {
    return $.ajax({
        url: '/api/v1/org/list_org_roles',
        method: 'GET',
        success: function(roles) {
            const select = $('#default-roles');
            select.empty();
            roles.forEach(role => {
                select.append(`<option value="${role}">${role}</option>`);
            });
        },
        error: function(error) {
            console.error('Failed to load org roles:', error);
        }
    });
}

function loadSSOConfig() {
    $.ajax({
        url: '/api/v1/org/sso/config',
        method: 'GET',
        success: function(response) {
            if (response.config) {
                populateForm(response.config);
            } else {
                resetForm();
            }
        },
        error: function(error) {
            console.error('Failed to load SSO config:', error);
            resetForm();
        }
    });
}

function populateForm(config) {
    $('#sso-enabled').prop('checked', config.enabled);
    $('#auto-provision').prop('checked', config.auto_provision !== false);

    if (config.saml_idp_metadata_url) {
        $('#idp-metadata-url').val(config.saml_idp_metadata_url);
    }
    if (config.saml_idp_entity_id) {
        $('#idp-entity-id').val(config.saml_idp_entity_id);
        $('#manual-config').collapse('show');
    }
    if (config.saml_idp_sso_url) {
        $('#idp-sso-url').val(config.saml_idp_sso_url);
    }
    if (config.saml_idp_slo_url) {
        $('#idp-slo-url').val(config.saml_idp_slo_url);
    }
    if (config.saml_idp_cert) {
        $('#idp-cert').val(config.saml_idp_cert);
    }

    // Allow empty default roles
    const sel = $('#default-roles');
    if (Array.isArray(config.default_org_roles) && config.default_org_roles.length > 0) {
        sel.val(config.default_org_roles);
    } else {
        sel.find('option').prop('selected', false);
        sel.val([]);
    }

    // Access control
    const accessControl = config.access_control || {mode: 'open'};
    $(`input[name="access-control-mode"][value="${accessControl.mode}"]`).prop('checked', true).trigger('change');
    if (accessControl.allowed_domains) {
        $('#allowed-domains').val(accessControl.allowed_domains.join(', '));
    }
    if (accessControl.allowed_groups) {
        $('#allowed-groups').val(accessControl.allowed_groups.join(', '));
    }

    // Attribute mapping
    const attrMapping = config.attribute_mapping || {};
    if (attrMapping.email) { $('#attr-email').val(attrMapping.email); }
    if (attrMapping.groups) { $('#attr-groups').val(attrMapping.groups); }

    // Group mapping
    if (config.group_mapping_enabled) {
        $('#group-mapping-enabled').prop('checked', true).trigger('change');
        if (config.group_mapping) {
            $('#group-mapping-container').empty();
            Object.entries(config.group_mapping).forEach(([group, roles]) => {
                addGroupMappingRow(group, roles);
            });
        }
    }
}

function resetForm() {
    const spMetadataUrl = $('#sp-metadata-url').val();
    const acsUrl = $('#acs-url').text();

    $('#sso-config-form')[0].reset();
    $('#sso-enabled').prop('checked', false);
    $('#auto-provision').prop('checked', true);
    $('#default-roles').val([]);
    $('#access-open').prop('checked', true).trigger('change');
    $('#group-mapping-container').empty();

    $('#sp-metadata-url').val(spMetadataUrl);
    $('#acs-url').text(acsUrl);
}

function addGroupMappingRow(groupName = '', roles = []) {
    const rowId = `mapping-${Date.now()}`;
    const row = $(`
        <div class="form-row mb-2" id="${rowId}">
            <div class="col-md-5">
                <input type="text" class="form-control group-name" placeholder="SAML Group Name" value="${groupName}">
            </div>
            <div class="col-md-5">
                <select class="form-control group-roles" multiple>
                    ${$('#default-roles option').map((i, opt) =>
                        `<option value="${opt.value}" ${roles.includes(opt.value) ? 'selected' : ''}>${opt.value}</option>`
                    ).get().join('')}
                </select>
            </div>
            <div class="col-md-2">
                <button type="button" class="btn btn-danger btn-sm remove-mapping" data-row="${rowId}">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
        </div>
    `);

    $('#group-mapping-container').append(row);
    row.find('.remove-mapping').on('click', function() {
        $(`#${$(this).data('row')}`).remove();
    });
}

// ============================================
// Client-Side Validation
// ============================================

function validateForm() {
    let valid = true;
    // Clear previous validation states
    $('.is-invalid').removeClass('is-invalid');

    const enabled = $('#sso-enabled').is(':checked');
    if (!enabled) return true; // Nothing to validate if SSO is disabled

    const metadataUrl = $('#idp-metadata-url').val().trim();
    const entityId = $('#idp-entity-id').val().trim();
    const ssoUrl = $('#idp-sso-url').val().trim();
    const cert = $('#idp-cert').val().trim();

    // Must have metadata URL OR all 3 manual fields
    if (!metadataUrl && (!entityId || !ssoUrl || !cert)) {
        if (!metadataUrl) $('#idp-metadata-url').addClass('is-invalid');
        if (!entityId) $('#idp-entity-id').addClass('is-invalid');
        if (!ssoUrl) $('#idp-sso-url').addClass('is-invalid');
        if (!cert) $('#idp-cert').addClass('is-invalid');
        showToast('Provide either a metadata URL or complete manual configuration (Entity ID, SSO URL, Certificate)', 'warning');
        valid = false;
    }

    // If metadata URL provided, enforce HTTPS
    if (metadataUrl && !metadataUrl.startsWith('https://')) {
        $('#idp-metadata-url').addClass('is-invalid');
        showToast('Metadata URL must use HTTPS', 'warning');
        valid = false;
    }

    // Access control mode-specific validation
    const mode = $('input[name="access-control-mode"]:checked').val();
    if (mode === 'email_domain') {
        const domains = $('#allowed-domains').val().trim();
        if (!domains) {
            $('#allowed-domains').addClass('is-invalid');
            showToast('At least one email domain is required for Email Domain access control', 'warning');
            valid = false;
        }
    } else if (mode === 'group_whitelist') {
        const groups = $('#allowed-groups').val().trim();
        if (!groups) {
            $('#allowed-groups').addClass('is-invalid');
            showToast('At least one group is required for Group Whitelist access control', 'warning');
            valid = false;
        }
    }

    return valid;
}

// ============================================
// Save Configuration
// ============================================

function saveSSOConfig() {
    if (!validateForm()) return;

    const config = {
        enabled: $('#sso-enabled').is(':checked'),
        saml_idp_metadata_url: $('#idp-metadata-url').val() || null,
        saml_idp_entity_id: $('#idp-entity-id').val() || null,
        saml_idp_sso_url: $('#idp-sso-url').val() || null,
        saml_idp_slo_url: $('#idp-slo-url').val() || null,
        saml_idp_cert: $('#idp-cert').val() || null,
        default_org_roles: $('#default-roles').val() || [],
        auto_provision: $('#auto-provision').is(':checked'),
        group_mapping_enabled: $('#group-mapping-enabled').is(':checked'),
        group_mapping: {},
        access_control: {
            mode: $('input[name="access-control-mode"]:checked').val()
        },
        attribute_mapping: {
            email: $('#attr-email').val() || 'email',
            groups: $('#attr-groups').val() || 'groups'
        }
    };

    // Access control details
    if (config.access_control.mode === 'email_domain') {
        const domains = $('#allowed-domains').val();
        config.access_control.allowed_domains = domains ? domains.split(',').map(d => d.trim()).filter(Boolean) : [];
    } else if (config.access_control.mode === 'group_whitelist') {
        const groups = $('#allowed-groups').val();
        config.access_control.allowed_groups = groups ? groups.split(',').map(g => g.trim()).filter(Boolean) : [];
    }

    // Group mapping
    if (config.group_mapping_enabled) {
        $('#group-mapping-container .form-row').each(function() {
            const groupName = $(this).find('.group-name').val().trim();
            const roles = $(this).find('.group-roles').val() || [];
            if (groupName && roles.length > 0) {
                config.group_mapping[groupName] = roles;
            }
        });
    }

    const $btn = $('#save-sso-config');
    setButtonLoading($btn, true);

    $.ajax({
        url: '/api/v1/org/sso/config',
        method: 'PUT',
        contentType: 'application/json',
        data: JSON.stringify(config),
        success: function(response) {
            showToast(response.message || 'SSO configuration saved successfully', 'success');
        },
        error: function(xhr) {
            showToast(xhr.responseJSON?.detail || 'Failed to save SSO configuration', 'error');
        },
        complete: function() {
            setButtonLoading($btn, false);
        }
    });
}

// ============================================
// Operations
// ============================================

function checkSSOStatus($btn) {
    setButtonLoading($btn, true);

    $.ajax({
        url: '/api/v1/org/sso/debug',
        method: 'GET',
        success: function(data) {
            if (data.status === 'ready') {
                showToast('SSO is fully configured and ready to use', 'success');
            } else {
                showToast('SSO configuration incomplete: ' + data.message, 'warning');
            }
        },
        error: function() {
            showToast('Failed to check SSO status', 'error');
        },
        complete: function() {
            setButtonLoading($btn, false);
        }
    });
}

function reparseMetadata($btn) {
    $('#reparseConfirmModal').modal('show');
}

function testSSOLogin($btn) {
    setButtonLoading($btn, true);

    $.ajax({
        url: '/api/v1/org/sso/debug',
        method: 'GET',
        success: function(data) {
            if (data.status !== 'ready') {
                showToast('SSO is not fully configured yet. Complete the configuration first.', 'warning');
                return;
            }
            $('#testSSOModal').modal('show');
        },
        error: function() {
            showToast('Failed to check SSO status', 'error');
        },
        complete: function() {
            setButtonLoading($btn, false);
        }
    });
}

function deleteSSOConfig() {
    $('#deleteConfirmModal').modal('show');
}
