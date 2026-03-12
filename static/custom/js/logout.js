document.addEventListener('DOMContentLoaded', function () {
    const logoutLink = document.getElementById('logout-link');
    if (logoutLink) {
        logoutLink.addEventListener('click', function (e) {
            e.preventDefault();
            fetch('/api/v1/web-logout', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                }
            }).finally(() => {
                // Clear regardless of success/failure
                document.cookie = 'session_token=; Path=/; Expires=Thu, 01 Jan 1970 00:00:01 GMT;';
                localStorage.removeItem('returnUrl');
                window.location.href = '/login';
            });
        });
    }
});