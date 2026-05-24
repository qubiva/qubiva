/**
 * Session Manager
 * Handles session monitoring, countdown timer, and session renewal
 */

$(document).ready(function() {
    console.log('Session Manager: Initializing...');

    let sessionInfo = null;
    let timerInterval = null;
    let secondsRemaining = 0; // Count down from server-provided duration

    // Set to true to always show timer (for testing)
    const TEST_MODE = true;  // TODO: Set to false in production

    const SHOW_TIMER_THRESHOLD = TEST_MODE ? 3600 : (10 * 60); // Show timer when 10 minutes remaining (or always in test mode)
    const SHOW_RENEWAL_THRESHOLD = TEST_MODE ? 3600 : (5 * 60); // Show renewal button when 5 minutes remaining (or always in test mode)

    /**
     * Fetch current session information from server
     */
    async function fetchSessionInfo() {
        try {
            console.log('Session Manager: Fetching session info...');
            const response = await fetch('/api/v1/session/info', {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                },
                cache: 'no-store'
            });

            console.log('Session Manager: Response status:', response.status);

            if (response.ok) {
                sessionInfo = await response.json();
                console.log('Session Manager: Session info received:', sessionInfo);

                // Initialize countdown from server-provided seconds remaining
                secondsRemaining = sessionInfo.seconds_remaining || 0;
                console.log('Session Manager: Starting countdown from:', secondsRemaining, 'seconds');

                updateSessionDisplay();
            } else if (response.status === 401) {
                // Session expired, will be handled by login_handler.js
                console.log('Session Manager: Session expired (401)');
                stopSessionMonitoring();
            }
        } catch (error) {
            console.error('Session Manager: Error fetching session info:', error);
        }
    }

    /**
     * Countdown timer - decrements every second
     */
    function tickCountdown() {
        if (secondsRemaining > 0) {
            secondsRemaining--;
        }
        updateSessionDisplay();
    }

    /**
     * Format seconds into MM:SS format
     */
    function formatTime(seconds) {
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }

    /**
     * Update the session timer display
     */
    function updateSessionDisplay() {
        const pill = $('#session-cta-pill');
        const timerText = $('#session-timer-text');

        // Still respect your TEST_MODE thresholds
        const shouldShowTimer = TEST_MODE
            ? (secondsRemaining > 0)
            : (secondsRemaining > 0 && secondsRemaining <= SHOW_TIMER_THRESHOLD);

        // “critical” look when close to expiry (uses your renewal threshold)
        const isCriticalWindow = (secondsRemaining > 0 && secondsRemaining <= SHOW_RENEWAL_THRESHOLD);

        // Show/hide the single pill
        if (shouldShowTimer) {
            pill.removeClass('d-none');
        } else {
            pill.addClass('d-none');
        }

        // Update countdown text (MM:SS)
        const mins = Math.floor(secondsRemaining / 60);
        const secs = secondsRemaining % 60;
        timerText.text(`${String(mins).padStart(2,'0')}:${String(secs).padStart(2,'0')}`);

        // Toggle stronger visual state near expiry
        const pillBox = pill.find('.session-pill');
        if (isCriticalWindow) {
            pillBox.addClass('session-pill--critical');
        } else {
            pillBox.removeClass('session-pill--critical');
        }
    }


    /**
     * Renew the current session
     */
    async function renewSession() {
        const renewBtn = $('#renew-session-btn');
        const renewIcon = renewBtn.find('i');
        const hadIcon = renewIcon.length > 0;
        const originalClass = hadIcon ? renewIcon.attr('class') : null;

        // Visual feedback
        if (hadIcon) renewIcon.removeClass().addClass('fas fa-spinner fa-spin');
        renewBtn.css('pointer-events', 'none');

        try {
            const res = await fetch('/api/v1/session/renew', {
                method: 'POST',
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                credentials: 'same-origin' // ensure cookies go with request
            });

            console.log('[session] renew response status =', res.status);

            if (!res.ok) {
                let msg = 'Failed to renew session. Please try again.';
                if (res.status === 403) {
                    const err = await res.json().catch(() => ({}));
                    msg = err.detail || 'Maximum renewals exceeded. Please log in again.';
                }
                showNotification('error', 'Renewal Failed', msg);
                return;
            }

            const data = await res.json();
            console.log('[session] renew payload =', data);

            // Reset countdown from server immediately
            if (typeof data.seconds_remaining === 'number') {
                secondsRemaining = data.seconds_remaining;
            }

            showNotification('success', 'Session renewed',
                `You have ${data.renewals_remaining} renewal${data.renewals_remaining !== 1 ? 's' : ''} remaining.`);

            updateSessionDisplay();
        } catch (err) {
            console.error('[session] renew exception', err);
            showNotification('error', 'Renewal Error', 'An error occurred while renewing your session.');
        } finally {
            if (hadIcon) renewIcon.removeClass().addClass(originalClass);
            renewBtn.css('pointer-events', 'auto');
        }
    }


    /**
     * Show notification toast
     */
    function showNotification(type, title, message) {
        const iconMap = {
            success: 'fas fa-check-circle',
            error: 'fas fa-exclamation-circle',
            warning: 'fas fa-exclamation-triangle',
            info: 'fas fa-info-circle'
        };

        const colorMap = {
            success: '#28a745',
            error: '#dc3545',
            warning: '#ffc107',
            info: '#17a2b8'
        };

        // Create toast notification
        const toast = $(`
            <div class="toast" role="alert" style="position: fixed; top: 70px; right: 20px; z-index: 9999; min-width: 300px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                <div class="toast-header" style="background-color: ${colorMap[type]}; color: white; border-bottom: none;">
                    <i class="${iconMap[type]}" style="margin-right: 8px;"></i>
                    <strong class="mr-auto">${title}</strong>
                    <button type="button" class="ml-2 mb-1 close" data-dismiss="toast" style="color: white;">
                        <span>&times;</span>
                    </button>
                </div>
                <div class="toast-body" style="background-color: white; color: #212529; border-top: none;">
                    ${message}
                </div>
            </div>
        `);

        $('body').append(toast);
        toast.toast({ autohide: true, delay: 5000 });
        toast.toast('show');

        // Remove from DOM after hidden
        toast.on('hidden.bs.toast', function() {
            $(this).remove();
        });
    }

    /**
     * Start session monitoring
     */
    function startSessionMonitoring() {
        // Initial fetch only - no polling!
        fetchSessionInfo();

        // Start countdown timer (updates every second)
        timerInterval = setInterval(tickCountdown, 1000);
    }

    /**
     * Stop session monitoring
     */
    function stopSessionMonitoring() {
        if (timerInterval) {
            clearInterval(timerInterval);
            timerInterval = null;
        }
        $('#session-cta-pill').addClass('d-none');
    }

    // Event handler for renewal button (delegated - survives re-render/show/hide)
    $(document).off('click', '#renew-session-btn');
    $(document).on('click', '#renew-session-btn', function(e) {
        e.preventDefault();
        e.stopPropagation();
        console.log('[session] renew clicked'); // debug
        renewSession();
    });


    // Start monitoring when page loads
    startSessionMonitoring();

    // Stop monitoring when user logs out or navigates away
    $(window).on('beforeunload', function() {
        stopSessionMonitoring();
    });
});
