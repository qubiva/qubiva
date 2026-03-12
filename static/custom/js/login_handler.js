// Set up interceptors when document is ready
$(document).ready(function() {
    console.log('Setting up AJAX interceptors...');
    
    // Function to handle redirect
    function redirectToLogin() {
        console.log('Redirecting to login...');
        // Capture current page URL (not API endpoint)
        const currentPath = window.location.pathname;
        if (!currentPath.startsWith('/api/') && currentPath !== '/login') {
            const currentUrl = window.location.pathname + window.location.search;
            const encodedUrl = encodeURIComponent(currentUrl);
            window.location.replace(`/login?next=${encodedUrl}`);
        } else {
            window.location.replace('/login');
        }
        return false;
    }

    // jQuery AJAX interceptor
    $(document).ajaxError(function(event, xhr, settings, error) {
        console.log('AJAX error detected:', {status: xhr.status, url: settings.url});
        if (xhr.status === 401) {
            event.preventDefault();
            redirectToLogin();
        }
    });

    // Fetch API interceptor
    const originalFetch = window.fetch;
    window.fetch = function() {
        console.log('Fetch interceptor - request:', arguments[0]);

        return originalFetch.apply(this, arguments)
            .then(async response => {
                console.log('Fetch interceptor - response status:', response.status);

                // Check for explicit 401 status
                if (response.status === 401) {
                    redirectToLogin();
                    throw new Error('Unauthorized - redirecting to login');
                }

                // Check if we received HTML when expecting JSON (session expired without proper header)
                // Only check for API endpoints to avoid interfering with legitimate HTML requests
                const url = arguments[0];
                const isApiRequest = typeof url === 'string' && url.includes('/api/');

                if (isApiRequest) {
                    const contentType = response.headers.get('content-type');
                    if (contentType && contentType.includes('text/html')) {
                        console.warn('Fetch interceptor - received HTML for API request, likely session expired');
                        redirectToLogin();
                        throw new Error('Session expired - redirecting to login');
                    }
                }

                return response;
            })
            .catch(error => {
                console.error('Fetch interceptor - error:', error);
                throw error;
            });
    };

    // Set up jQuery AJAX defaults
    $.ajaxSetup({
        beforeSend: function(xhr) {
            xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
        }
    });
});