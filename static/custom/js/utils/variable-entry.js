/* Qubiva variable-entry widget — shared by all create/edit project/workspace/cloud-account pages */

var Qubiva = window.Qubiva || {};

Qubiva.variableEntry = (function ($) {
    'use strict';

    var entryTemplate =
        '<div class="variable-entry mb-2 row align-items-center">' +
            '<div class="col-md-4">' +
                '<input type="text" class="form-control" name="variable-key" placeholder="Enter key" value="{{key}}">' +
            '</div>' +
            '<div class="col-md-4">' +
                '<input type="text" class="form-control variable-value" name="variable-value" placeholder="Enter value" autocomplete="off" data-type="text" value="{{value}}" style="{{style}}">' +
            '</div>' +
            '<div class="col-md-3 d-flex align-items-center">' +
                '<div class="form-check">' +
                    '<input class="form-check-input" type="checkbox" name="is-secret" {{checked}}>' +
                    '<label class="form-check-label ml-1">Mark as secret</label>' +
                '</div>' +
                '<button type="button" class="btn btn-link btn-sm text-danger delete-variable-entry ml-3" style="padding: 0;">' +
                    '<i class="fas fa-times fa-lg"></i>' +
                '</button>' +
            '</div>' +
        '</div>';

    /**
     * Add a variable entry row to the container.
     * @param {string} key - Pre-filled key (default '')
     * @param {string} value - Pre-filled value (default '')
     * @param {boolean} isSecret - Whether to mask the value (default false)
     * @param {string} formSelector - Optional form selector to trigger 'input' event on (for edit pages)
     */
    function add(key, value, isSecret, formSelector) {
        key = key || '';
        value = value || '';
        isSecret = !!isSecret;

        var html = entryTemplate
            .replace('{{key}}', key)
            .replace('{{value}}', value)
            .replace('{{style}}', isSecret ? '-webkit-text-security: disc;' : '')
            .replace('{{checked}}', isSecret ? 'checked' : '');

        $('#variables-entries').append(html);

        if (formSelector) {
            $(formSelector).trigger('input');
        }
    }

    /** Toggle secret masking on a checkbox change */
    function toggleSecret(checkbox) {
        var valueField = $(checkbox).closest('.variable-entry').find('.variable-value');
        if (checkbox.checked) {
            valueField.css('-webkit-text-security', 'disc');
        } else {
            valueField.css('-webkit-text-security', 'none');
        }
    }

    /** Collect all variable entries as { variables: {}, secrets: {} } */
    function collect() {
        var variables = {};
        var secrets = {};
        $('#variables-entries .variable-entry').each(function () {
            var key = $(this).find('[name="variable-key"]').val().trim();
            var value = $(this).find('[name="variable-value"]').val().trim();
            var isSecret = $(this).find('[name="is-secret"]').is(':checked');
            if (key) {
                if (isSecret) {
                    secrets[key] = value;
                } else {
                    variables[key] = value;
                }
            }
        });
        return { variables: variables, secrets: secrets };
    }

    /**
     * Initialize event handlers for variable entries.
     * Call once per page. Handles add button, delete button, and secret toggle.
     * @param {string} formSelector - Optional form selector to trigger 'input' on changes (for edit pages)
     */
    function init(formSelector) {
        $('#add-variable-entry').on('click', function () {
            add('', '', false, formSelector);
        });

        $(document).on('click', '.delete-variable-entry', function () {
            $(this).closest('.variable-entry').remove();
            if (formSelector) {
                $(formSelector).trigger('input');
            }
        });

        $(document).on('change', 'input[name="is-secret"]', function () {
            toggleSecret(this);
        });
    }

    return {
        add: add,
        toggleSecret: toggleSecret,
        collect: collect,
        init: init
    };
})(jQuery);
