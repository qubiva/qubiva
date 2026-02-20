/* Qubiva URL helpers — consistent path segment parsing across all pages */

var Qubiva = window.Qubiva || {};

Qubiva.url = (function () {
    'use strict';

    var _segments = null;

    function segments() {
        if (!_segments) {
            _segments = window.location.pathname.split('/');
        }
        return _segments;
    }

    /**
     * Get a named resource from the URL path.
     * URL structure: /dashboard/projects/{project}/workspaces/{workspace}/...
     *                /dashboard/projects/{project}/cloud_accounts/{platform}/{accountId}/...
     *
     * Usage:
     *   Qubiva.url.get('projects')       → project name (decoded)
     *   Qubiva.url.get('workspaces')      → workspace name (decoded)
     *   Qubiva.url.get('cloud_accounts')  → cloud platform (decoded)
     *   Qubiva.url.get('cloud_accounts', 2) → account ID (2nd segment after keyword)
     */
    function get(keyword, offset) {
        var segs = segments();
        var idx = segs.indexOf(keyword);
        if (idx === -1) return null;
        var pos = idx + (offset || 1);
        return pos < segs.length ? decodeURIComponent(segs[pos]) : null;
    }

    /** Shorthand: project name from URL */
    function projectName() {
        return get('projects');
    }

    /** Shorthand: workspace name from URL */
    function workspaceName() {
        return get('workspaces');
    }

    /** Shorthand: cloud platform from URL */
    function cloudPlatform() {
        return get('cloud_accounts');
    }

    /** Shorthand: cloud account ID from URL */
    function accountId() {
        return get('cloud_accounts', 2);
    }

    /** Shorthand: alert ID from URL */
    function alertId() {
        return get('alerts', 2);
    }

    /** Get the last path segment (decoded) */
    function lastSegment() {
        var segs = segments();
        var last = segs[segs.length - 1];
        return last ? decodeURIComponent(last) : null;
    }

    /** Get raw segment by index (decoded) */
    function segment(index) {
        var segs = segments();
        return index < segs.length ? decodeURIComponent(segs[index]) : null;
    }

    return {
        get: get,
        projectName: projectName,
        workspaceName: workspaceName,
        cloudPlatform: cloudPlatform,
        accountId: accountId,
        alertId: alertId,
        lastSegment: lastSegment,
        segment: segment
    };
})();

/* Global Toastr configuration — applied on every page.
 * Alerts stay visible until the user clicks the close button. */
if (typeof toastr !== 'undefined') {
    toastr.options = {
        closeButton: true,
        newestOnTop: true,
        progressBar: false,
        positionClass: 'toast-top-right',
        preventDuplicates: true,
        onclick: null,
        showDuration: '300',
        hideDuration: '300',
        timeOut: '0',
        extendedTimeOut: '0',
        showEasing: 'swing',
        hideEasing: 'linear',
        showMethod: 'fadeIn',
        hideMethod: 'fadeOut'
    };
}

/**
 * Extract a human-readable error message from an AJAX error response.
 * Handles FastAPI's {detail: string|array|object} format safely.
 *
 * Usage:
 *   error: function(xhr) {
 *       showModal('Error', Qubiva.extractError(xhr, 'Default message'));
 *   }
 */
Qubiva.extractError = function (xhr, fallback) {
    'use strict';
    var msg = fallback || 'An unexpected error occurred.';
    try {
        var json = xhr.responseJSON || (typeof xhr === 'object' && xhr.detail !== undefined ? xhr : null);
        if (!json) return msg;
        var detail = json.detail;
        if (detail === undefined || detail === null) return msg;
        if (typeof detail === 'string') return detail;
        if (Array.isArray(detail)) {
            return detail.map(function (e) {
                return typeof e === 'string' ? e : (e.msg || JSON.stringify(e));
            }).join('; ');
        }
        return JSON.stringify(detail);
    } catch (e) {
        return msg;
    }
};
