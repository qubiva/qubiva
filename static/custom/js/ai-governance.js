/**
 * AI Governance dashboard — client-side logic.
 *
 * Patterns: jQuery $.ajax, Bootstrap modals, toastr for transient notifications.
 * Tabs are lazy-loaded: data fetched on first activation only.
 */

/* ---- Toastr defaults ---- */
if (typeof toastr !== 'undefined') {
    toastr.options = {
        closeButton: true,
        newestOnTop: true,
        positionClass: 'toast-top-right',
        timeOut: 4000,
        showDuration: '300',
        hideDuration: '400',
    };
}

/* ---- State ---- */
const agState = {
    enabled: false,
    healthy: false,
    credentialsLoaded: false,
    modelsLoaded: false,
    keysLoaded: false,
    spendLoaded: false,
    spendLogsPage: 0,
    spendLogsPageSize: 50,
    spendStartDate: null,  // YYYY-MM-DD or null
    spendEndDate: null,    // YYYY-MM-DD or null
    spendTrendChart: null, // Chart.js instance
    credentials: [],       // cached for the model modal dropdown
    providers: [],         // loaded from /api/v1/ai-governance/providers
};

/* ====================================================================
   INIT
==================================================================== */

$(document).ready(function () {
    loadStatus();
    loadProviders();
    bindStaticEvents();
    initSpendDatePicker();

    // Lazy-load tabs on first activation — only when gateway is healthy
    $('a[data-toggle="tab"]').on('shown.bs.tab', function (e) {
        if (!agState.healthy) return;
        const target = $(e.target).attr('href');
        if (target === '#pane-credentials' && !agState.credentialsLoaded) loadCredentials();
        if (target === '#pane-models'      && !agState.modelsLoaded)      loadModels();
        if (target === '#pane-keys'        && !agState.keysLoaded)        loadKeys();
        if (target === '#pane-spend'       && !agState.spendLoaded)       loadSpend();
    });
});

/* ====================================================================
   STATUS
==================================================================== */

function loadStatus() {
    $('#status-loading').show();
    $('#status-content').hide();

    $.ajax({
        url: '/api/v1/ai-governance/status',
        method: 'GET',
        success: function (data) {
            $('#status-loading').hide();
            $('#status-content').show();

            agState.enabled = data.enabled;
            agState.healthy = data.enabled && data.healthy;

            $('#status-enabled').html(
                data.enabled
                    ? '<span class="ag-badge ag-badge-success"><i class="fas fa-check"></i> Enabled</span>'
                    : '<span class="ag-badge ag-badge-muted"><i class="fas fa-minus"></i> Disabled</span>'
            );

            if (data.enabled) {
                const healthHtml = data.healthy
                    ? '<span class="ag-badge ag-badge-success"><i class="fas fa-heartbeat"></i> Healthy</span>'
                    : '<span class="ag-badge ag-badge-danger"><i class="fas fa-exclamation-circle"></i> Unreachable</span>';
                $('#status-health').html(healthHtml);

                if (data.gateway_url) {
                    const isInternal = data.gateway_url.indexOf('.svc.cluster.local') !== -1;
                    const urlLabel = isInternal
                        ? data.gateway_url + ' <span class="text-muted" style="font-size:0.82em;">(in-cluster only)</span>'
                        : data.gateway_url;
                    $('#status-url').html(urlLabel);
                    $('#status-url-row').show();
                }
            } else {
                $('#status-health').html('<span class="ag-badge ag-badge-muted">—</span>');
            }

            // Always show tabs; overlay controls interactivity
            $('#ag-feature-overlay').remove();
            $('#ag-gateway-warning').remove();

            if (!data.enabled) {
                _showTabsOverlay(
                    'fas fa-lock',
                    'AI Gateway not configured',
                    'Enable the AI Gateway in your Helm values to activate model routing, virtual keys and spend tracking.',
                    '<strong>values.yaml</strong>\naiGateway:\n  enabled: true'
                );
            } else if (!data.healthy) {
                _showGatewayWarning('Gateway is unreachable — tab data cannot be loaded. Check pod status and logs.');
            } else {
                // Healthy — load default tab
                loadCredentials();
            }
        },
        error: function (xhr) {
            $('#status-loading').hide();
            toastr.error(extractError(xhr, 'Failed to load gateway status'));
        }
    });
}

function _showTabsOverlay(iconClass, title, body, codeHint) {
    var codeBlock = codeHint ? '<pre>' + escHtml(codeHint) + '</pre>' : '';
    var overlay = $(
        '<div id="ag-feature-overlay" class="ag-feature-overlay">' +
          '<div class="ag-overlay-icon"><i class="' + iconClass + '"></i></div>' +
          '<h5>' + escHtml(title) + '</h5>' +
          '<p>' + escHtml(body) + '</p>' +
          codeBlock +
        '</div>'
    );
    $('#gateway-enabled-section').append(overlay);
}

function _showGatewayWarning(msg) {
    var warn = $(
        '<div id="ag-gateway-warning" class="ag-gateway-warning">' +
          '<i class="fas fa-exclamation-triangle mr-2"></i>' + escHtml(msg) +
        '</div>'
    );
    $('#gateway-enabled-section').prepend(warn);
}

$('#refresh-status-btn').on('click', function () {
    agState.healthy = false;
    agState.credentialsLoaded = false;
    agState.modelsLoaded = false;
    agState.keysLoaded = false;
    agState.spendLoaded = false;
    loadStatus();
});

/* ====================================================================
   CREDENTIALS
==================================================================== */

function loadCredentials() {
    $('#credentials-loading').show();
    $('#credentials-empty, #credentials-table-wrap').hide();

    $.ajax({
        url: '/api/v1/ai-governance/credentials',
        method: 'GET',
        success: function (data) {
            agState.credentialsLoaded = true;
            agState.credentials = data.credentials || [];
            $('#credentials-loading').hide();
            renderCredentials(agState.credentials);
        },
        error: function (xhr) {
            $('#credentials-loading').hide();
            toastr.error(extractError(xhr, 'Failed to load credentials'));
        }
    });
}

function renderCredentials(list) {
    if (!list.length) {
        $('#credentials-empty').show();
        return;
    }
    const tbody = $('#credentials-tbody').empty();
    list.forEach(function (c) {
        tbody.append(
            '<tr>' +
            '<td>' + escHtml(c.name) + '</td>' +
            '<td><span class="provider-badge">' + escHtml(c.provider) + '</span></td>' +
            '<td>' + escHtml(c.created_by || '—') + '</td>' +
            '<td>' + fmtDate(c.updated_at || c.created_at) + '</td>' +
            '<td>' +
              '<button class="btn btn-warning btn-action mr-1 btn-rotate-cred" ' +
                      'data-id="' + escHtml(c.credential_id) + '" data-name="' + escHtml(c.name) + '" data-provider="' + escHtml(c.provider) + '" title="Rotate key">' +
                '<i class="fas fa-sync-alt"></i>' +
              '</button>' +
              '<button class="btn btn-danger btn-action btn-delete-cred" ' +
                      'data-id="' + escHtml(c.credential_id) + '" data-name="' + escHtml(c.name) + '" title="Delete">' +
                '<i class="fas fa-trash"></i>' +
              '</button>' +
            '</td>' +
            '</tr>'
        );
    });
    $('#credentials-table-wrap').show();
}

// Add credential
$('#btn-add-credential').on('click', function () {
    $('#form-add-credential')[0].reset();
    $('#cred-dynamic-fields').empty();
    $('#modal-add-credential').modal('show');
});

// Provider change → render credential fields
$('#cred-provider').on('change', function () {
    const providerId = $(this).val();
    const provider   = agState.providers.find(function (p) { return p.id === providerId; });
    renderCredentialFields('#cred-dynamic-fields', provider, 'cred-field');
});

$('#btn-save-credential').on('click', function () {
    const name     = $.trim($('#cred-name').val());
    const provider = $('#cred-provider').val();

    if (!name || !provider) {
        toastr.warning('Name and provider are required.');
        return;
    }

    const credentialValues = {};
    let missingRequired = false;
    $('#cred-dynamic-fields [data-cred-param]').each(function () {
        const param = $(this).data('cred-param');
        const val   = $.trim($(this).val());
        credentialValues[param] = val;
        if (!val && $(this).prop('required')) missingRequired = true;
    });

    if (!Object.keys(credentialValues).length) {
        toastr.warning('Select a provider to reveal its credential fields.');
        return;
    }
    if (missingRequired) {
        toastr.warning('All required credential fields must be filled.');
        return;
    }

    $(this).prop('disabled', true).html('<i class="fas fa-spinner fa-spin mr-1"></i> Saving...');

    $.ajax({
        url: '/api/v1/ai-governance/credentials',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ name: name, provider: provider, credential_values: credentialValues }),
        success: function () {
            $('#modal-add-credential').modal('hide');
            toastr.success('Credential saved.');
            agState.credentialsLoaded = false;
            loadCredentials();
        },
        error: function (xhr) {
            toastr.error(extractError(xhr, 'Failed to save credential'));
        },
        complete: function () {
            $('#btn-save-credential').prop('disabled', false).html('<i class="fas fa-save mr-1"></i> Save');
        }
    });
});

// Rotate credential
$(document).on('click', '.btn-rotate-cred', function () {
    const id       = $(this).data('id');
    const name     = $(this).data('name');
    const provider = $(this).data('provider');
    $('#rotate-cred-id').val(id);
    $('#rotate-cred-provider').val(provider);
    $('#rotate-cred-name').text(name);
    const providerDef = agState.providers.find(function (p) { return p.id === provider; });
    renderCredentialFields('#rotate-dynamic-fields', providerDef, 'rotate-field');
    $('#modal-rotate-credential').modal('show');
});

$('#btn-confirm-rotate').on('click', function () {
    const id = $('#rotate-cred-id').val();

    const credentialValues = {};
    let missingRequired = false;
    $('#rotate-dynamic-fields [data-cred-param]').each(function () {
        const param = $(this).data('cred-param');
        const val   = $.trim($(this).val());
        credentialValues[param] = val;
        if (!val) missingRequired = true;
    });

    if (!Object.keys(credentialValues).length || missingRequired) {
        toastr.warning('Enter the new credential value(s).');
        return;
    }

    $(this).prop('disabled', true).html('<i class="fas fa-spinner fa-spin mr-1"></i> Rotating...');

    $.ajax({
        url: '/api/v1/ai-governance/credentials/' + encodeURIComponent(id),
        method: 'PUT',
        contentType: 'application/json',
        data: JSON.stringify({ credential_values: credentialValues }),
        success: function (data) {
            $('#modal-rotate-credential').modal('hide');
            const synced = data.models_synced || 0;
            const failed = data.models_failed || 0;
            toastr.success('Credential rotated. ' + synced + ' model(s) synced' + (failed ? ', ' + failed + ' failed.' : '.'));
        },
        error: function (xhr) {
            toastr.error(extractError(xhr, 'Failed to rotate credential'));
        },
        complete: function () {
            $('#btn-confirm-rotate').prop('disabled', false).html('<i class="fas fa-sync-alt mr-1"></i> Rotate &amp; Sync');
        }
    });
});

// Delete credential
$(document).on('click', '.btn-delete-cred', function () {
    $('#delete-cred-id').val($(this).data('id'));
    $('#delete-cred-name').text($(this).data('name'));
    $('#modal-delete-credential').modal('show');
});

$('#btn-confirm-delete-credential').on('click', function () {
    const id = $('#delete-cred-id').val();
    $(this).prop('disabled', true).text('Deleting...');

    $.ajax({
        url: '/api/v1/ai-governance/credentials/' + encodeURIComponent(id),
        method: 'DELETE',
        success: function () {
            $('#modal-delete-credential').modal('hide');
            toastr.success('Credential deleted.');
            agState.credentialsLoaded = false;
            loadCredentials();
        },
        error: function (xhr) {
            toastr.error(extractError(xhr, 'Failed to delete credential'));
        },
        complete: function () {
            $('#btn-confirm-delete-credential').prop('disabled', false).text('Delete');
        }
    });
});

/* ====================================================================
   MODELS
==================================================================== */

function loadModels() {
    $('#models-loading').show();
    $('#models-empty, #models-table-wrap').hide();

    $.ajax({
        url: '/api/v1/ai-governance/models',
        method: 'GET',
        success: function (data) {
            agState.modelsLoaded = true;
            $('#models-loading').hide();
            renderModels(data.models || []);
        },
        error: function (xhr) {
            $('#models-loading').hide();
            toastr.error(extractError(xhr, 'Failed to load models'));
        }
    });
}

function renderModels(list) {
    if (!list.length) {
        $('#models-empty').show();
        return;
    }
    const tbody = $('#models-tbody').empty();
    list.forEach(function (m) {
        const params  = m.litellm_params || {};
        const provider = params.litellm_provider || params.custom_llm_provider || m.model_info && m.model_info.provider || '—';
        const model    = params.model || '—';
        const modelId  = m.model_info && m.model_info.id || m.model_id || '';

        tbody.append(
            '<tr>' +
            '<td>' + escHtml(m.model_name || '—') + '</td>' +
            '<td><span class="provider-badge">' + escHtml(provider) + '</span></td>' +
            '<td><code style="font-size:0.8em;">' + escHtml(model) + '</code></td>' +
            '<td>' +
              '<button class="btn btn-danger btn-action btn-delete-model" ' +
                      'data-id="' + escHtml(modelId) + '" data-name="' + escHtml(m.model_name || '') + '" title="Remove">' +
                '<i class="fas fa-trash"></i>' +
              '</button>' +
            '</td>' +
            '</tr>'
        );
    });
    $('#models-table-wrap').show();
}

/* ====================================================================
   PROVIDERS — load from config, drive both dropdowns
==================================================================== */

function loadProviders() {
    $.ajax({
        url: '/api/v1/ai-governance/providers',
        method: 'GET',
        success: function (data) {
            agState.providers = data.providers || [];
            buildProviderDropdown('#model-provider');
            buildProviderDropdown('#cred-provider', true);  // only providers with credential fields
        },
        error: function () {
            // Non-fatal — dropdowns stay empty, user sees placeholder
        }
    });
}

function buildProviderDropdown(selector, filterHasCredentials) {
    const sel = $(selector);
    // preserve first placeholder option
    const placeholder = sel.find('option:first').clone();
    sel.empty().append(placeholder);
    agState.providers.forEach(function (p) {
        if (filterHasCredentials) {
            const hasCredField = (p.fields || []).some(function (f) { return f.credential; });
            if (!hasCredField) return;
        }
        sel.append('<option value="' + escHtml(p.id) + '">' + escHtml(p.label) + '</option>');
    });
}

// Add model
$('#btn-add-model').on('click', function () {
    $('#form-add-model')[0].reset();
    $('#model-dynamic-fields').empty();
    $('#model-direct-fields').empty();
    $('#model-credential-section').hide();
    $('#model-credential-group').show();
    $('#model-direct-key-group').hide();
    $('#key-source-credential').prop('checked', true);
    populateCredentialDropdown(null);
    $('#modal-add-model').modal('show');
});

function populateCredentialDropdown(providerId) {
    const sel = $('#model-credential-select').empty().append('<option value="" disabled selected>Select credential</option>');
    const filtered = (agState.credentials || []).filter(function (c) {
        return !providerId || c.provider === providerId;
    });
    filtered.forEach(function (c) {
        sel.append('<option value="' + escHtml(c.credential_id) + '">' + escHtml(c.name) + ' (' + escHtml(c.provider) + ')</option>');
    });
    if (!filtered.length) {
        const msg = providerId ? 'No credentials for this provider — add one first' : 'No credentials stored — add one first';
        sel.append('<option disabled>' + msg + '</option>');
    }
}

// Provider change → render dynamic fields from schema + filter credential dropdown
$('#model-provider').on('change', function () {
    const providerId = $(this).val();
    const provider   = agState.providers.find(function (p) { return p.id === providerId; });
    renderProviderFields(provider);
    populateCredentialDropdown(providerId);
});

function renderProviderFields(provider) {
    const container = $('#model-dynamic-fields').empty();
    $('#model-direct-fields').empty();
    if (!provider) {
        $('#model-credential-section').hide();
        return;
    }

    var hasCredentialField = false;

    (provider.fields || []).forEach(function (field) {
        if (field.credential) {
            hasCredentialField = true;
            return; // credential fields rendered into #model-direct-fields below
        }

        const groupId  = 'dynfield-group-' + field.id;
        const inputId  = 'dynfield-' + field.id;
        const required = field.required ? ' <span class="text-danger">*</span>' : '';
        const group    = $('<div class="form-group"></div>').attr('id', groupId);
        const label    = $('<label></label>').attr('for', inputId).html(escHtml(field.label) + required);

        var input;
        if (field.type === 'password') {
            input = $(
                '<div class="input-group">' +
                  '<input type="password" class="form-control" autocomplete="new-password">' +
                  '<div class="input-group-append">' +
                    '<button type="button" class="btn btn-outline-secondary toggle-pw" data-target="' + inputId + '">' +
                      '<i class="fas fa-eye"></i>' +
                    '</button>' +
                  '</div>' +
                '</div>'
            );
            input.find('input').attr({ id: inputId, 'data-litellm-param': field.id, placeholder: field.placeholder || '', required: !!field.required });
        } else {
            input = $('<input class="form-control">').attr({
                type: 'text',
                id: inputId,
                'data-litellm-param': field.id,
                placeholder: field.placeholder || '',
                required: !!field.required,
                autocomplete: 'off',
            });
        }

        group.append(label).append(input);
        container.append(group);
    });

    // Render credential fields for direct-entry section
    if (hasCredentialField) {
        renderCredentialFields('#model-direct-fields', provider, 'model-direct');
    }

    // Show/hide credential section
    $('#model-credential-section').toggle(hasCredentialField);
}

/**
 * Render credential: true fields from a provider schema into a container.
 * Each input gets data-cred-param=field.id for collection into credential_values dict.
 * idPrefix must be unique per modal to avoid conflicting DOM ids.
 */
function renderCredentialFields(containerSelector, provider, idPrefix) {
    const container = $(containerSelector).empty();
    if (!provider) return;
    (provider.fields || []).filter(function (f) { return f.credential; }).forEach(function (field) {
        const inputId  = idPrefix + '-' + field.id;
        const required = field.required ? ' <span class="text-danger">*</span>' : '';
        const group    = $('<div class="form-group"></div>');
        const label    = $('<label></label>').attr('for', inputId).html(escHtml(field.label) + required);

        var input;
        if (field.type === 'password') {
            input = $(
                '<div class="input-group">' +
                  '<input type="password" class="form-control" autocomplete="new-password">' +
                  '<div class="input-group-append">' +
                    '<button type="button" class="btn btn-outline-secondary toggle-pw" data-target="' + inputId + '">' +
                      '<i class="fas fa-eye"></i>' +
                    '</button>' +
                  '</div>' +
                '</div>'
            );
            input.find('input').attr({ id: inputId, 'data-cred-param': field.id, placeholder: field.placeholder || '', required: !!field.required });
        } else {
            input = $('<input class="form-control">').attr({
                type: 'text',
                id: inputId,
                'data-cred-param': field.id,
                placeholder: field.placeholder || '',
                required: !!field.required,
                autocomplete: 'off',
            });
        }

        group.append(label).append(input);
        container.append(group);
    });
}

// Key source toggle
$(document).on('change', 'input[name="key-source"]', function () {
    const direct = $(this).val() === 'direct';
    $('#model-credential-group').toggle(!direct);
    $('#model-direct-key-group').toggle(direct);
});

$('#btn-save-model').on('click', function () {
    const alias      = $.trim($('#model-alias').val());
    const providerId = $('#model-provider').val();
    const model      = $.trim($('#model-name').val());

    if (!alias || !providerId || !model) {
        toastr.warning('Model alias, provider, and model name are required.');
        return;
    }

    const providerDef    = agState.providers.find(function (p) { return p.id === providerId; }) || {};
    const litellmProvider = providerDef.litellmProvider || providerId;

    const litellmParams = {
        model: litellmProvider + '/' + model,
        custom_llm_provider: litellmProvider,
    };

    // Collect dynamic field values
    $('#model-dynamic-fields [data-litellm-param]').each(function () {
        const param = $(this).data('litellm-param');
        const val   = $.trim($(this).val());
        if (val) litellmParams[param] = val;
    });

    // Credential field(s)
    const hasCredSection = $('#model-credential-section').is(':visible');
    const keySource      = $('input[name="key-source"]:checked').val();
    const credentialId   = (hasCredSection && keySource === 'credential') ? $('#model-credential-select').val() : null;

    if (hasCredSection) {
        if (keySource === 'credential' && !credentialId) {
            toastr.warning('Select a credential.');
            return;
        }
        if (keySource === 'direct') {
            let missingDirect = false;
            $('#model-direct-fields [data-cred-param]').each(function () {
                if ($(this).prop('required') && !$.trim($(this).val())) missingDirect = true;
            });
            if (missingDirect) {
                toastr.warning('Enter the required credential value(s).');
                return;
            }
            $('#model-direct-fields [data-cred-param]').each(function () {
                const param = $(this).data('cred-param');
                const val   = $.trim($(this).val());
                if (val) litellmParams[param] = val;
            });
        }
    }

    const payload = { model_name: alias, litellm_params: litellmParams };
    if (credentialId) payload.credential_id = credentialId;

    $(this).prop('disabled', true).html('<i class="fas fa-spinner fa-spin mr-1"></i> Adding...');

    $.ajax({
        url: '/api/v1/ai-governance/models',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(payload),
        success: function () {
            $('#modal-add-model').modal('hide');
            toastr.success('Model added.');
            agState.modelsLoaded = false;
            loadModels();
        },
        error: function (xhr) {
            toastr.error(extractError(xhr, 'Failed to add model'));
        },
        complete: function () {
            $('#btn-save-model').prop('disabled', false).html('<i class="fas fa-save mr-1"></i> Add Model');
        }
    });
});

// Delete model
$(document).on('click', '.btn-delete-model', function () {
    $('#delete-model-id').val($(this).data('id'));
    $('#delete-model-name').text($(this).data('name'));
    $('#modal-delete-model').modal('show');
});

$('#btn-confirm-delete-model').on('click', function () {
    const id = $('#delete-model-id').val();
    $(this).prop('disabled', true).text('Removing...');

    $.ajax({
        url: '/api/v1/ai-governance/models/' + encodeURIComponent(id),
        method: 'DELETE',
        success: function () {
            $('#modal-delete-model').modal('hide');
            toastr.success('Model removed.');
            agState.modelsLoaded = false;
            loadModels();
        },
        error: function (xhr) {
            toastr.error(extractError(xhr, 'Failed to remove model'));
        },
        complete: function () {
            $('#btn-confirm-delete-model').prop('disabled', false).text('Remove');
        }
    });
});

/* ====================================================================
   VIRTUAL KEYS
==================================================================== */

function loadKeys() {
    $('#keys-loading').show();
    $('#keys-empty, #keys-table-wrap').hide();

    $.ajax({
        url: '/api/v1/ai-governance/keys',
        method: 'GET',
        success: function (data) {
            agState.keysLoaded = true;
            $('#keys-loading').hide();
            renderKeys(data.keys || []);
        },
        error: function (xhr) {
            $('#keys-loading').hide();
            toastr.error(extractError(xhr, 'Failed to load keys'));
        }
    });
}

function renderKeys(list) {
    if (!list.length) {
        $('#keys-empty').show();
        return;
    }
    const tbody = $('#keys-tbody').empty();
    list.forEach(function (k) {
        const keyStr   = k.token || k.key || '';
        const prefix   = keyStr ? keyStr.substring(0, 12) + '…' : '—';
        const alias    = k.key_alias || k.alias || '—';
        const budget   = k.max_budget != null ? '$' + parseFloat(k.max_budget).toFixed(2) : '∞';
        const spend    = k.spend != null ? '$' + parseFloat(k.spend).toFixed(4) : '—';
        const rpm      = k.rpm_limit != null ? k.rpm_limit : '∞';
        const tpm      = k.tpm_limit != null ? k.tpm_limit : '∞';
        const models   = (k.models && k.models.length) ? k.models.join(', ') : 'All';

        // Owner column: show project or user binding
        var ownerHtml = '<span class="text-muted" style="font-size:0.8em;">—</span>';
        if (k.key_type === 'project' && k.project_name) {
            ownerHtml = '<span class="ag-badge ag-badge-muted" style="font-size:0.78em;"><i class="fas fa-project-diagram mr-1"></i>' + escHtml(k.project_name) + '</span>';
        } else if (k.key_type === 'user' && k.owner_username) {
            ownerHtml = '<span class="ag-badge ag-badge-muted" style="font-size:0.78em;"><i class="fas fa-user mr-1"></i>' + escHtml(k.owner_username) + '</span>';
        }

        tbody.append(
            '<tr>' +
            '<td>' + escHtml(alias) + '</td>' +
            '<td>' + ownerHtml + '</td>' +
            '<td><code class="key-value-cell">' + escHtml(prefix) + '</code></td>' +
            '<td>' + budget + '</td>' +
            '<td>' + spend + '</td>' +
            '<td>' + rpm + '</td>' +
            '<td>' + tpm + '</td>' +
            '<td><small>' + escHtml(models) + '</small></td>' +
            '<td>' +
              '<button class="btn btn-primary btn-action mr-1 btn-update-key" ' +
                      'data-id="' + escHtml(keyStr) + '" ' +
                      'data-alias="' + escHtml(alias) + '" ' +
                      'data-budget="' + (k.max_budget != null ? k.max_budget : '') + '" ' +
                      'data-rpm="' + (k.rpm_limit != null ? k.rpm_limit : '') + '" ' +
                      'data-tpm="' + (k.tpm_limit != null ? k.tpm_limit : '') + '" ' +
                      'title="Edit limits">' +
                '<i class="fas fa-edit"></i>' +
              '</button>' +
              '<button class="btn btn-danger btn-action btn-delete-key" ' +
                      'data-id="' + escHtml(keyStr) + '" data-alias="' + escHtml(alias) + '" title="Delete">' +
                '<i class="fas fa-trash"></i>' +
              '</button>' +
            '</td>' +
            '</tr>'
        );
    });
    $('#keys-table-wrap').show();
}

// Create key
$('#btn-create-key').on('click', function () {
    $('#form-create-key')[0].reset();
    $('#key-project-group, #key-user-group').hide();
    _loadProjectsDropdown();
    $('#modal-create-key').modal('show');
});

// Key type toggle — show/hide project or user fields
$('#key-type').on('change', function () {
    const val = $(this).val();
    $('#key-project-group').toggle(val === 'project');
    $('#key-user-group').toggle(val === 'user');
});

function _loadProjectsDropdown() {
    const sel = $('#key-project-name').empty().append('<option value="" disabled selected>Loading...</option>');
    $.ajax({
        url: '/api/v1/projects/search',
        method: 'GET',
        data: { query: '' },
        success: function (data) {
            sel.empty().append('<option value="" disabled selected>Select project</option>');
            const projects = data.projects || data || [];
            if (Array.isArray(projects) && projects.length) {
                projects.forEach(function (p) {
                    const name = p.project_name || p;
                    sel.append('<option value="' + escHtml(name) + '">' + escHtml(name) + '</option>');
                });
            } else {
                sel.append('<option disabled>No projects found</option>');
            }
        },
        error: function () {
            sel.empty().append('<option disabled>Failed to load projects</option>');
        }
    });
}

$('#btn-confirm-create-key').on('click', function () {
    const payload = {};
    const alias    = $.trim($('#key-alias').val());
    const keyType  = $('#key-type').val();
    const project  = $('#key-project-name').val();
    const username = $.trim($('#key-owner-username').val());
    const budget   = $('#key-budget').val();
    const rpm      = $('#key-rpm').val();
    const tpm      = $('#key-tpm').val();
    const models   = $.trim($('#key-models').val());

    if (alias)  payload.alias       = alias;
    if (budget) payload.max_budget  = parseFloat(budget);
    if (rpm)    payload.rpm_limit   = parseInt(rpm);
    if (tpm)    payload.tpm_limit   = parseInt(tpm);
    if (models) payload.models      = models.split(',').map(function (s) { return s.trim(); }).filter(Boolean);

    if (keyType) {
        payload.key_type = keyType;
        if (keyType === 'project') {
            if (!project) { toastr.warning('Select a project for this key.'); return; }
            payload.project_name = project;
        } else if (keyType === 'user') {
            if (!username) { toastr.warning('Enter a username for this key.'); return; }
            payload.owner_username = username;
        }
    }

    $(this).prop('disabled', true).html('<i class="fas fa-spinner fa-spin mr-1"></i> Creating...');

    $.ajax({
        url: '/api/v1/ai-governance/keys',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(payload),
        success: function (data) {
            $('#modal-create-key').modal('hide');
            const key = data.key || data.token || '';
            if (key) {
                $('#created-key-value').text(key);
                $('#modal-key-created').modal('show');
            } else {
                toastr.success('Key created.');
            }
            agState.keysLoaded = false;
            loadKeys();
        },
        error: function (xhr) {
            toastr.error(extractError(xhr, 'Failed to create key'));
        },
        complete: function () {
            $('#btn-confirm-create-key').prop('disabled', false).html('<i class="fas fa-plus mr-1"></i> Create Key');
        }
    });
});

// Copy key
$('#btn-copy-key').on('click', function () {
    const text = $('#created-key-value').text();
    navigator.clipboard.writeText(text).then(function () {
        toastr.success('Copied to clipboard.');
    }).catch(function () {
        toastr.warning('Copy failed — select and copy manually.');
    });
});

// Update key
$(document).on('click', '.btn-update-key', function () {
    const $btn = $(this);
    $('#update-key-id').val($btn.data('id'));
    $('#update-key-alias-hidden').val($btn.data('alias'));
    $('#update-key-budget').val($btn.data('budget'));
    $('#update-key-rpm').val($btn.data('rpm'));
    $('#update-key-tpm').val($btn.data('tpm'));
    $('#modal-update-key').modal('show');
});

$('#btn-confirm-update-key').on('click', function () {
    const id      = $('#update-key-id').val();
    const budget  = $('#update-key-budget').val();
    const rpm     = $('#update-key-rpm').val();
    const tpm     = $('#update-key-tpm').val();
    const payload = {};

    if (budget) payload.max_budget = parseFloat(budget);
    if (rpm)    payload.rpm_limit  = parseInt(rpm);
    if (tpm)    payload.tpm_limit  = parseInt(tpm);

    $(this).prop('disabled', true).html('<i class="fas fa-spinner fa-spin mr-1"></i> Saving...');

    $.ajax({
        url: '/api/v1/ai-governance/keys/' + encodeURIComponent(id),
        method: 'PATCH',
        contentType: 'application/json',
        data: JSON.stringify(payload),
        success: function () {
            $('#modal-update-key').modal('hide');
            toastr.success('Key updated.');
            agState.keysLoaded = false;
            loadKeys();
        },
        error: function (xhr) {
            toastr.error(extractError(xhr, 'Failed to update key'));
        },
        complete: function () {
            $('#btn-confirm-update-key').prop('disabled', false).html('<i class="fas fa-save mr-1"></i> Save');
        }
    });
});

// Delete key
$(document).on('click', '.btn-delete-key', function () {
    $('#delete-key-id').val($(this).data('id'));
    $('#delete-key-alias').text($(this).data('alias'));
    $('#modal-delete-key').modal('show');
});

$('#btn-confirm-delete-key').on('click', function () {
    const id = $('#delete-key-id').val();
    $(this).prop('disabled', true).text('Deleting...');

    $.ajax({
        url: '/api/v1/ai-governance/keys/' + encodeURIComponent(id),
        method: 'DELETE',
        success: function () {
            $('#modal-delete-key').modal('hide');
            toastr.success('Key deleted.');
            agState.keysLoaded = false;
            loadKeys();
        },
        error: function (xhr) {
            toastr.error(extractError(xhr, 'Failed to delete key'));
        },
        complete: function () {
            $('#btn-confirm-delete-key').prop('disabled', false).text('Delete');
        }
    });
});

/* ====================================================================
   SPEND
==================================================================== */

function loadSpend() {
    $('#spend-loading').show();
    $('#spend-content').hide();

    $.ajax({
        url: '/api/v1/ai-governance/spend',
        method: 'GET',
        success: function (data) {
            agState.spendLoaded = true;
            $('#spend-loading').hide();
            renderSpend(data);
        },
        error: function (xhr) {
            $('#spend-loading').hide();
            toastr.error(extractError(xhr, 'Failed to load spend data'));
        }
    });
}

function renderSpend(data) {
    const global   = data.global   || {};
    const byModel  = data.by_model || [];
    const byKey    = data.by_key   || [];

    // Summary
    const total = global.spend != null ? parseFloat(global.spend).toFixed(4) : '0.0000';
    $('#spend-total').text(total);
    $('#spend-keys-count').text(byKey.length);
    $('#spend-models-count').text(byModel.length);

    // By model
    const mTbody = $('#spend-by-model-tbody').empty();
    if (byModel.length) {
        byModel.forEach(function (m) {
            mTbody.append(
                '<tr>' +
                '<td>' + escHtml(m.model || m.model_name || '—') + '</td>' +
                '<td>$' + parseFloat(m.spend || 0).toFixed(4) + '</td>' +
                '<td>' + (m.total_tokens || '—') + '</td>' +
                '</tr>'
            );
        });
    } else {
        mTbody.append('<tr><td colspan="3" class="text-center text-muted">No spend data</td></tr>');
    }

    // By key
    const kTbody = $('#spend-by-key-tbody').empty();
    if (byKey.length) {
        byKey.forEach(function (k) {
            const keyPfx = (k.api_key || k.key || '').substring(0, 12) + '…';
            kTbody.append(
                '<tr>' +
                '<td><code>' + escHtml(keyPfx) + '</code></td>' +
                '<td>' + escHtml(k.key_alias || k.alias || '—') + '</td>' +
                '<td>$' + parseFloat(k.spend || 0).toFixed(4) + '</td>' +
                '</tr>'
            );
        });
    } else {
        kTbody.append('<tr><td colspan="3" class="text-center text-muted">No spend data</td></tr>');
    }

    $('#spend-content').show();

    // Load logs (with chart since we default to last 30 days)
    agState.spendLogsPage = 0;
    loadSpendLogs(true);
}

function initSpendDatePicker() {
    if (typeof $.fn.daterangepicker === 'undefined') return;

    // Default to last 30 days
    const defaultStart = moment().subtract(29, 'days');
    const defaultEnd   = moment();
    agState.spendStartDate = defaultStart.format('YYYY-MM-DD');
    agState.spendEndDate   = defaultEnd.format('YYYY-MM-DD');
    $('#spend-date-range').val(defaultStart.format('YYYY-MM-DD') + ' \u2013 ' + defaultEnd.format('YYYY-MM-DD'));

    $('#spend-date-range').daterangepicker({
        startDate: defaultStart,
        endDate:   defaultEnd,
        autoUpdateInput: false,
        opens: 'left',
        showDropdowns: true,
        maxDate: moment(),
        locale: { format: 'YYYY-MM-DD', cancelLabel: 'Clear' }
    });

    $('#spend-date-range').on('apply.daterangepicker', function (ev, picker) {
        agState.spendStartDate = picker.startDate.format('YYYY-MM-DD');
        agState.spendEndDate   = picker.endDate.format('YYYY-MM-DD');
        $(this).val(agState.spendStartDate + ' \u2013 ' + agState.spendEndDate);
    });

    $('#spend-date-range').on('cancel.daterangepicker', function () {
        agState.spendStartDate = null;
        agState.spendEndDate   = null;
        $(this).val('');
    });

    $('#btn-spend-date-apply').on('click', function () {
        agState.spendLogsPage = 0;
        loadSpendLogs(true);
    });

    $('#btn-spend-date-clear').on('click', function () {
        agState.spendStartDate = null;
        agState.spendEndDate   = null;
        $('#spend-date-range').val('');
        $('#spend-chart-row').hide();
        if (agState.spendTrendChart) {
            agState.spendTrendChart.destroy();
            agState.spendTrendChart = null;
        }
        agState.spendLogsPage = 0;
        loadSpendLogs(false);
    });
}

/**
 * Load spend logs.
 * @param {boolean} withChart  When true (date range active), also fetch a
 *                             large batch for the trend chart.
 */
function loadSpendLogs(withChart) {
    const withChartBool = !!withChart;
    const offset = agState.spendLogsPage * agState.spendLogsPageSize;
    $('#spend-logs-tbody').html('<tr><td colspan="5" class="text-center text-muted"><i class="fas fa-spinner fa-spin"></i></td></tr>');

    const params = { limit: agState.spendLogsPageSize, offset: offset };
    if (agState.spendStartDate) params.start_date = agState.spendStartDate;
    if (agState.spendEndDate)   params.end_date   = agState.spendEndDate;

    $.ajax({
        url: '/api/v1/ai-governance/spend/logs',
        method: 'GET',
        data: params,
        success: function (data) {
            const logs = data.logs || [];
            renderLogsTable(logs);
            renderLogsPagination(logs.length);

            if (withChartBool && agState.spendStartDate) {
                // Fetch a large slice for aggregation into the trend chart
                $.ajax({
                    url: '/api/v1/ai-governance/spend/logs',
                    method: 'GET',
                    data: {
                        limit: 5000,
                        offset: 0,
                        start_date: agState.spendStartDate,
                        end_date: agState.spendEndDate
                    },
                    success: function (chartData) {
                        renderTrendChart(chartData.logs || []);
                    }
                });
            } else if (!agState.spendStartDate) {
                $('#spend-chart-row').hide();
            }
        },
        error: function () {
            $('#spend-logs-tbody').html('<tr><td colspan="5" class="text-center text-danger">Failed to load logs</td></tr>');
        }
    });
}

function renderLogsTable(logs) {
    const tbody = $('#spend-logs-tbody').empty();
    if (!logs.length) {
        tbody.html('<tr><td colspan="5" class="text-center text-muted">No call logs</td></tr>');
        return;
    }
    logs.forEach(function (l) {
        tbody.append(
            '<tr>' +
            '<td><small>' + fmtDate(l.startTime || l.created_at) + '</small></td>' +
            '<td>' + escHtml(l.model || '\u2014') + '</td>' +
            '<td><code style="font-size:0.78em;">' + escHtml((l.api_key || '').substring(0, 12) + '\u2026') + '</code></td>' +
            '<td>' + (l.total_tokens || '\u2014') + '</td>' +
            '<td>$' + parseFloat(l.spend || 0).toFixed(6) + '</td>' +
            '</tr>'
        );
    });
}

function renderTrendChart(logs) {
    // Aggregate spend by calendar day
    const dailySpend = {};
    logs.forEach(function (l) {
        const raw = l.startTime || l.created_at || '';
        if (!raw) return;
        const day = raw.substring(0, 10); // YYYY-MM-DD
        dailySpend[day] = (dailySpend[day] || 0) + parseFloat(l.spend || 0);
    });

    const labels = Object.keys(dailySpend).sort();
    const values = labels.map(function (d) { return dailySpend[d]; });

    // Destroy existing chart instance before re-creating
    if (agState.spendTrendChart) {
        agState.spendTrendChart.destroy();
        agState.spendTrendChart = null;
    }

    if (!labels.length) {
        $('#spend-chart-row').hide();
        return;
    }

    $('#spend-chart-row').show();
    const ctx = document.getElementById('spend-trend-chart').getContext('2d');
    agState.spendTrendChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Daily Spend (USD)',
                data: values,
                borderColor: '#007bff',
                backgroundColor: 'rgba(0,123,255,0.08)',
                borderWidth: 2,
                pointRadius: 3,
                fill: true,
                tension: 0.3
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: function (ctx) {
                            return '$' + ctx.parsed.y.toFixed(6);
                        }
                    }
                }
            },
            scales: {
                x: { ticks: { maxTicksLimit: 14 } },
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: function (v) { return '$' + v.toFixed(4); }
                    }
                }
            }
        }
    });
}

function renderLogsPagination(count) {
    const container = $('#spend-logs-pagination').empty();
    const prev = agState.spendLogsPage > 0;
    const next = count === agState.spendLogsPageSize;

    if (!prev && !next) return;

    const ul = $('<ul class="pagination pagination-sm mb-0"></ul>');
    ul.append(
        '<li class="page-item ' + (prev ? '' : 'disabled') + '">' +
        '<a class="page-link" id="logs-prev-btn" href="#">&laquo; Prev</a></li>'
    );
    ul.append(
        '<li class="page-item ' + (next ? '' : 'disabled') + '">' +
        '<a class="page-link" id="logs-next-btn" href="#">Next &raquo;</a></li>'
    );
    container.append(ul);
}

$(document).on('click', '#logs-prev-btn', function (e) {
    e.preventDefault();
    if (agState.spendLogsPage > 0) { agState.spendLogsPage--; loadSpendLogs(!!agState.spendStartDate); }
});
$(document).on('click', '#logs-next-btn', function (e) {
    e.preventDefault();
    agState.spendLogsPage++;
    loadSpendLogs(false);
});

$('#btn-refresh-spend').on('click', function () {
    agState.spendLoaded = false;
    if (agState.spendTrendChart) {
        agState.spendTrendChart.destroy();
        agState.spendTrendChart = null;
    }
    loadSpend();
});

/* ====================================================================
   SHARED HELPERS & STATIC EVENTS
==================================================================== */

function bindStaticEvents() {
    // Password show/hide toggle
    $(document).on('click', '.toggle-pw', function () {
        const targetId = $(this).data('target');
        const input    = $('#' + targetId);
        const icon     = $(this).find('i');
        if (input.attr('type') === 'password') {
            input.attr('type', 'text');
            icon.removeClass('fa-eye').addClass('fa-eye-slash');
        } else {
            input.attr('type', 'password');
            icon.removeClass('fa-eye-slash').addClass('fa-eye');
        }
    });

    // Clear modals on hide
    $('.modal').on('hidden.bs.modal', function () {
        $(this).find('input[type="password"]').attr('type', 'password');
        $(this).find('.toggle-pw i').removeClass('fa-eye-slash').addClass('fa-eye');
    });
}

function escHtml(str) {
    if (str == null) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function fmtDate(val) {
    if (!val) return '—';
    try {
        const d = new Date(val);
        if (isNaN(d)) return String(val);
        return d.toLocaleString();
    } catch (e) { return String(val); }
}

function extractError(xhr, fallback) {
    try {
        const body = JSON.parse(xhr.responseText);
        return body.detail || body.message || fallback;
    } catch (e) { return fallback; }
}
