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
    allLogs: [],           // all fetched logs (client-side filtering)
    selectedModels: [],    // models selected in create-key modal
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
        if (target === '#pane-credentials'    && !agState.credentialsLoaded)           loadCredentials();
        if (target === '#pane-models'         && !agState.modelsLoaded)                loadModels();
        if (target === '#pane-keys'           && !agState.keysLoaded)                  loadKeys();
        if (target === '#pane-spend'          && !agState.spendLoaded)                 loadSpend();
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
              '<button class="btn btn-link text-danger btn-delete-cred" style="padding:0; margin-left:6px;" ' +
                      'data-id="' + escHtml(c.credential_id) + '" data-name="' + escHtml(c.name) + '" title="Delete">' +
                '<i class="fas fa-times"></i>' +
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
        toastr.error('Name and provider are required.');
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
        toastr.error('Select a provider to reveal its credential fields.');
        return;
    }
    if (missingRequired) {
        toastr.error('All required credential fields must be filled.');
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
        toastr.error('Enter the new credential value(s).');
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
            agState.models = data.models || [];
            $('#models-loading').hide();
            renderModels(agState.models);
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
              '<button class="btn btn-link text-danger p-0 btn-delete-model" ' +
                      'data-id="' + escHtml(modelId) + '" data-name="' + escHtml(m.model_name || '') + '" title="Remove">' +
                '<i class="fas fa-trash-alt"></i>' +
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
        toastr.error('Model alias, provider, and model name are required.');
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
            toastr.error('Select a credential.');
            return;
        }
        if (keySource === 'direct') {
            let missingDirect = false;
            $('#model-direct-fields [data-cred-param]').each(function () {
                if ($(this).prop('required') && !$.trim($(this).val())) missingDirect = true;
            });
            if (missingDirect) {
                toastr.error('Enter the required credential value(s).');
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
        const prefix   = k.key_name || (keyStr ? keyStr.substring(0, 12) + '…' : '—');
        const alias    = k.key_alias || k.alias || '—';
        const budget   = k.max_budget != null ? '$' + parseFloat(k.max_budget).toFixed(2) : '∞';
        const spend    = k.spend != null ? '$' + parseFloat(k.spend).toFixed(4) : '—';
        const rpm      = k.rpm_limit != null ? k.rpm_limit : '∞';
        const tpm      = k.tpm_limit != null ? k.tpm_limit : '∞';
        const models   = (k.models && k.models.length) ? k.models.join(', ') : 'All';

        // Owner column: show project or user binding
        var ownerHtml = '<span class="text-muted" style="font-size:0.8em;">—</span>';
        if (k.key_type === 'project' && k.project_name) {
            ownerHtml = '<a href="/dashboard/projects/' + encodeURIComponent(k.project_name) + '" class="ag-badge ag-badge-muted" style="font-size:0.78em; text-decoration:none;"><i class="fas fa-project-diagram mr-1"></i>' + escHtml(k.project_name) + '</a>';
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
              '<button class="btn btn-link text-primary p-0 mr-2 btn-update-key" ' +
                      'data-id="' + escHtml(keyStr) + '" ' +
                      'data-alias="' + escHtml(alias) + '" ' +
                      'data-budget="' + (k.max_budget != null ? k.max_budget : '') + '" ' +
                      'data-rpm="' + (k.rpm_limit != null ? k.rpm_limit : '') + '" ' +
                      'data-tpm="' + (k.tpm_limit != null ? k.tpm_limit : '') + '" ' +
                      'title="Edit limits">' +
                '<i class="fas fa-edit"></i>' +
              '</button>' +
              '<button class="btn btn-link text-danger p-0 btn-delete-key" ' +
                      'data-id="' + escHtml(keyStr) + '" data-alias="' + escHtml(alias) + '" title="Delete">' +
                '<i class="fas fa-trash-alt"></i>' +
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
    $('#key-project-name, #key-owner-username').val('');
    $('#key-project-search, #key-user-search').val('');
    $('#key-project-results, #key-user-results, #key-models-results').empty().hide();
    $('#key-project-group, #key-user-group').hide();
    _loadModelsMultiselect();
    $('#modal-create-key').modal('show');
});

// Key type toggle — show/hide project or user fields
$('#key-type').on('change', function () {
    const val = $(this).val();
    $('#key-project-group').toggle(val === 'project');
    $('#key-user-group').toggle(val === 'user');
});

function _debounce(fn, ms) {
    let t;
    return function () { clearTimeout(t); t = setTimeout(fn.bind(this, ...arguments), ms); };
}

// Project typeahead
$(document).on('input', '#key-project-search', _debounce(function () {
    const query = $.trim($(this).val());
    const results = $('#key-project-results').empty().hide();
    $('#key-project-name').val('');
    if (query.length < 2) return;
    $.ajax({
        url: '/api/v1/projects/search',
        method: 'GET',
        data: { query: query },
        success: function (data) {
            const projects = data.results || data.projects || [];
            if (!projects.length) {
                results.append('<div class="list-group-item text-muted">No projects found</div>').show();
                return;
            }
            projects.forEach(function (p) {
                const name = p.project_name || p;
                $('<a href="#" class="list-group-item list-group-item-action"></a>')
                    .text(name)
                    .on('click', function (e) {
                        e.preventDefault();
                        $('#key-project-search').val(name);
                        $('#key-project-name').val(name);
                        results.empty().hide();
                    })
                    .appendTo(results);
            });
            results.show();
        }
    });
}, 250));

// User typeahead
$(document).on('input', '#key-user-search', _debounce(function () {
    const query = $.trim($(this).val());
    const results = $('#key-user-results').empty().hide();
    $('#key-owner-username').val('');
    if (query.length < 2) return;
    $.ajax({
        url: '/api/v1/users/search/',
        method: 'GET',
        data: { query: query },
        success: function (data) {
            const users = Array.isArray(data) ? data : (data.users || []);
            if (!users.length) {
                results.append('<div class="list-group-item text-muted">No users found</div>').show();
                return;
            }
            users.forEach(function (u) {
                const username = u.username || u;
                $('<a href="#" class="list-group-item list-group-item-action"></a>')
                    .text(username)
                    .on('click', function (e) {
                        e.preventDefault();
                        $('#key-user-search').val(username);
                        $('#key-owner-username').val(username);
                        results.empty().hide();
                    })
                    .appendTo(results);
            });
            results.show();
        }
    });
}, 250));

// Models typeahead (multi-select via tags)
function _loadModelsMultiselect() {
    $('#key-models-search').val('');
    $('#key-models-results').empty().hide();
    $('#key-models-selected').empty();
    agState.selectedModels = [];
}

$(document).on('input', '#key-models-search', _debounce(function () {
    const query = $.trim($(this).val()).toLowerCase();
    const results = $('#key-models-results').empty().hide();
    if (!query) return;

    function _searchModels(models) {
        const filtered = models.filter(function (m) {
            const alias = m.model_name || m.model_alias || m.id || '';
            return alias.toLowerCase().indexOf(query) !== -1;
        });
        if (!filtered.length) {
            results.append('<div class="list-group-item text-muted">No models found</div>').show();
            return;
        }
        filtered.forEach(function (m) {
            const alias = m.model_name || m.model_alias || m.id || '';
            if (!alias) return;
            $('<a href="#" class="list-group-item list-group-item-action"></a>')
                .text(alias)
                .on('click', function (e) {
                    e.preventDefault();
                    if (agState.selectedModels.indexOf(alias) === -1) {
                        agState.selectedModels.push(alias);
                        $('<span class="badge badge-primary mr-1 mb-1" style="font-size:0.85em; cursor:pointer;"></span>')
                            .text(alias + ' ×')
                            .data('alias', alias)
                            .on('click', function () {
                                const idx = agState.selectedModels.indexOf(alias);
                                if (idx !== -1) agState.selectedModels.splice(idx, 1);
                                $(this).remove();
                            })
                            .appendTo('#key-models-selected');
                    }
                    $('#key-models-search').val('');
                    results.empty().hide();
                })
                .appendTo(results);
        });
        results.show();
    }

    if (agState.models && agState.models.length) {
        _searchModels(agState.models);
    } else {
        $.ajax({
            url: '/api/v1/ai-governance/models',
            method: 'GET',
            success: function (data) {
                agState.models = data.models || [];
                _searchModels(agState.models);
            }
        });
    }
}, 200));

$('#btn-confirm-create-key').on('click', function () {
    const payload = {};
    const alias    = $.trim($('#key-alias').val());
    const keyType  = $('#key-type').val();
    const project  = $('#key-project-name').val();
    const username = $.trim($('#key-owner-username').val());
    const budget   = $('#key-budget').val();
    const rpm      = $('#key-rpm').val();
    const tpm      = $('#key-tpm').val();
    const models   = agState.selectedModels || [];

    if (alias)          payload.alias       = alias;
    if (budget)         payload.max_budget  = parseFloat(budget);
    if (rpm)            payload.rpm_limit   = parseInt(rpm);
    if (tpm)            payload.tpm_limit   = parseInt(tpm);
    if (models.length)  payload.models      = models;

    if (!keyType) { toastr.error('Select a key type.'); return; }

    if (keyType) {
        payload.key_type = keyType;
        if (keyType === 'project') {
            if (!project) { toastr.error('Select a project for this key.'); return; }
            payload.project_name = project;
        } else if (keyType === 'user') {
            if (!username) { toastr.error('Enter a username for this key.'); return; }
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

// Reset key-created modal state on open
$('#modal-key-created').on('show.bs.modal', function () {
    $('#key-copied-confirm').prop('checked', false);
    $('#btn-key-created-done').prop('disabled', true);
});

// Enable Done only after user confirms they copied the key
$('#key-copied-confirm').on('change', function () {
    $('#btn-key-created-done').prop('disabled', !this.checked);
});

// Copy key — also auto-checks the confirm box
$('#btn-copy-key').on('click', function () {
    const text = $('#created-key-value').text();
    navigator.clipboard.writeText(text).then(function () {
        toastr.success('Copied to clipboard.');
        $('#key-copied-confirm').prop('checked', true).trigger('change');
    }).catch(function () {
        toastr.error('Copy failed — select and copy manually.');
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

function normalizeModelName(name) {
    // Collapse double-provider prefix (e.g. groq/groq/llama → groq/llama)
    var parts = name.split('/');
    if (parts.length >= 3 && parts[0] === parts[1]) {
        return parts[0] + '/' + parts.slice(2).join('/');
    }
    return name;
}

function renderSpend(data) {
    const global     = data.global     || {};
    const byModel    = data.by_model   || [];
    const byKey      = data.by_key     || [];
    const byProject  = data.by_project || [];

    // Summary
    const total = global.spend != null ? parseFloat(global.spend).toFixed(4) : '0.0000';
    $('#spend-total').text(total);
    $('#spend-keys-count').text(byKey.length);

    // By model — deduplicate double-prefixed names
    const modelMap = {};
    byModel.forEach(function (m) {
        const name = normalizeModelName(m.model || m.model_name || '');
        if (!modelMap[name]) {
            modelMap[name] = { model: name, spend: 0, total_tokens: 0 };
        }
        modelMap[name].spend       += parseFloat(m.spend || m.total_spend || 0);
        modelMap[name].total_tokens += parseInt(m.total_tokens || 0, 10);
    });
    // Filter out zero-spend entries (auth-failure noise with no real model activity)
    const dedupedByModel = Object.values(modelMap).filter(function (m) { return m.spend > 0; });
    $('#spend-models-count').text(dedupedByModel.length);
    const mTbody = $('#spend-by-model-tbody').empty();
    if (dedupedByModel.length) {
        dedupedByModel.forEach(function (m) {
            mTbody.append(
                '<tr>' +
                '<td>' + escHtml(m.model || '—') + '</td>' +
                '<td>$' + parseFloat(m.spend || 0).toFixed(6) + '</td>' +
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
            const keyPfx = k.key_name || (k.token ? k.token.substring(0, 12) + '…' : '—');
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

    // By project
    const pTbody = $('#spend-by-project-tbody').empty();
    if (byProject.length) {
        byProject.slice().sort(function (a, b) { return b.spend - a.spend; }).forEach(function (p) {
            pTbody.append(
                '<tr>' +
                '<td><a href="/dashboard/projects/' + encodeURIComponent(p.project_name) + '">' + escHtml(p.project_name) + '</a></td>' +
                '<td>' + (p.key_count || 0) + '</td>' +
                '<td>$' + parseFloat(p.spend || 0).toFixed(4) + '</td>' +
                '</tr>'
            );
        });
    } else {
        pTbody.append('<tr><td colspan="3" class="text-center text-muted">No project spend</td></tr>');
    }

    $('#spend-content').show();

    // Load all logs once; chart + table derived client-side
    agState.spendLogsPage = 0;
    loadSpendLogs();
}

function _defaultDateRange() {
    return {
        start: moment().subtract(29, 'days'),
        end:   moment()
    };
}

function initSpendDatePicker() {
    if (typeof $.fn.daterangepicker === 'undefined') return;

    var dflt = _defaultDateRange();
    agState.spendStartDate = dflt.start.format('YYYY-MM-DD');
    agState.spendEndDate   = dflt.end.format('YYYY-MM-DD');

    $('#spend-date-range').daterangepicker({
        startDate: dflt.start,
        endDate:   dflt.end,
        opens: 'left',
        showDropdowns: true,
        maxDate: moment(),
        locale: { format: 'YYYY-MM-DD' }
    });
    $('#spend-date-range').val(agState.spendStartDate + ' \u2013 ' + agState.spendEndDate);

    $('#spend-date-range').on('apply.daterangepicker', function (ev, picker) {
        agState.spendStartDate = picker.startDate.format('YYYY-MM-DD');
        agState.spendEndDate   = picker.endDate.format('YYYY-MM-DD');
        $(this).val(agState.spendStartDate + ' \u2013 ' + agState.spendEndDate);
        agState.spendLogsPage = 0;
        applyLogsFilter();
    });

    $('#btn-spend-date-apply').on('click', function () {
        agState.spendLogsPage = 0;
        applyLogsFilter();
    });

    // Reset button — returns to default 30-day window (not "all time")
    $('#btn-spend-date-clear').on('click', function () {
        var d = _defaultDateRange();
        agState.spendStartDate = d.start.format('YYYY-MM-DD');
        agState.spendEndDate   = d.end.format('YYYY-MM-DD');
        var picker = $('#spend-date-range').data('daterangepicker');
        if (picker) { picker.setStartDate(d.start); picker.setEndDate(d.end); }
        $('#spend-date-range').val(agState.spendStartDate + ' \u2013 ' + agState.spendEndDate);
        agState.spendLogsPage = 0;
        applyLogsFilter();
    });
}

/**
 * Fetch all logs once from the server (no server-side date filter — LiteLLM
 * breaks when both start_date and end_date are supplied).  Date filtering is
 * applied client-side in applyLogsFilter().
 */
function loadSpendLogs() {
    $('#spend-logs-tbody').html('<tr><td colspan="5" class="text-center text-muted"><i class="fas fa-spinner fa-spin"></i></td></tr>');
    $.ajax({
        url: '/api/v1/ai-governance/spend/logs',
        method: 'GET',
        data: { limit: 5000 },
        success: function (data) {
            agState.allLogs = data.logs || [];
            enrichModelTableFromAllLogs();
            applyLogsFilter();
        },
        error: function () {
            $('#spend-logs-tbody').html('<tr><td colspan="5" class="text-center text-danger">Failed to load logs</td></tr>');
        }
    });
}

/**
 * After all logs are fetched, compute per-model token totals and update the
 * Tokens column in the Spend by Model table.  The /global/spend/models endpoint
 * does not return token counts, so we derive them from the log entries.
 */
function enrichModelTableFromAllLogs() {
    const modelTokens = {};
    (agState.allLogs || []).forEach(function (l) {
        if ((l.total_tokens || 0) === 0 && parseFloat(l.spend || 0) === 0) return;
        const name = normalizeModelName(l.model || '');
        if (!name) return;
        modelTokens[name] = (modelTokens[name] || 0) + parseInt(l.total_tokens || 0, 10);
    });
    $('#spend-by-model-tbody tr').each(function () {
        const $tds = $(this).find('td');
        if ($tds.length < 3) return;
        const modelName = $tds.eq(0).text().trim();
        const tokens = modelTokens[modelName];
        $tds.eq(2).text(tokens != null ? tokens.toLocaleString() : '—');
    });
}

/**
 * Filter agState.allLogs client-side by the active date range, then
 * render the paginated table and the trend chart.
 */
function applyLogsFilter() {
    var logs = agState.allLogs;

    if (agState.spendStartDate || agState.spendEndDate) {
        logs = logs.filter(function (l) {
            var d = (l.startTime || l.created_at || '').substring(0, 10);
            if (!d) return false;
            if (agState.spendStartDate && d < agState.spendStartDate) return false;
            if (agState.spendEndDate   && d > agState.spendEndDate)   return false;
            return true;
        });
    }

    renderTrendChart(logs);

    var pageStart = agState.spendLogsPage * agState.spendLogsPageSize;
    renderLogsTable(logs.slice(pageStart, pageStart + agState.spendLogsPageSize));
    renderLogsPagination(logs.length);
}

function renderLogsTable(logs) {
    const tbody = $('#spend-logs-tbody').empty();
    // Filter out auth-failure noise entries (no tokens consumed, no spend)
    const real = logs.filter(function (l) {
        return (l.total_tokens > 0) || (parseFloat(l.spend || 0) > 0);
    });
    if (!real.length) {
        tbody.html('<tr><td colspan="5" class="text-center text-muted">No call logs</td></tr>');
        return;
    }
    real.forEach(function (l) {
        tbody.append(
            '<tr>' +
            '<td><small>' + fmtDate(l.startTime || l.created_at) + '</small></td>' +
            '<td>' + escHtml(normalizeModelName(l.model || '') || '\u2014') + '</td>' +
            '<td><code style="font-size:0.78em;">' + (l.api_key && l.api_key !== 'None' ? escHtml(l.api_key.substring(0, 12) + '\u2026') : '\u2014') + '</code></td>' +
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

    const chartTitle = (agState.spendStartDate && agState.spendEndDate)
        ? 'Daily Spend \u2014 ' + agState.spendStartDate + '  \u2013  ' + agState.spendEndDate
        : 'Daily Spend \u2014 Last 30 Days';

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
                pointRadius: labels.length === 1 ? 5 : 3,
                fill: true,
                tension: 0.3
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { display: false },
                title: {
                    display: true,
                    text: chartTitle,
                    padding: { top: 4, bottom: 14 },
                    font: { size: 13, weight: '600' },
                    color: '#495057'
                },
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
    const next = (agState.spendLogsPage + 1) * agState.spendLogsPageSize < count;

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
    if (agState.spendLogsPage > 0) { agState.spendLogsPage--; applyLogsFilter(); }
});
$(document).on('click', '#logs-next-btn', function (e) {
    e.preventDefault();
    agState.spendLogsPage++;
    applyLogsFilter();
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

