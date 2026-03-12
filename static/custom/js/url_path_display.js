document.addEventListener("DOMContentLoaded", function() {
    const pathSegments = ["You are here:"].concat(
        window.location.pathname.split('/').filter(segment => segment !== "")
    );
    const pathDisplay = document.getElementById('url-path-display');
    
    // Define an array of segments that should not be clickable
    const nonClickableSegments = ['logs', 'aws', 'azure', 'gcp'];

    // Define segments where the NEXT segment should be non-clickable
    const nonClickablePositionAfter = ['git_repos', 'github_repos', 'credentials'];

    // Known route segments get prettified display names.
    // Anything NOT in this map is a dynamic value (project name, repo name, etc.)
    // and is displayed exactly as-is from the URL.
    const displayNameMap = {
        'dashboard': 'Dashboard',
        'projects': 'Projects',
        'create': 'Create',
        'edit': 'Edit',
        'overview': 'Overview',
        'workspaces': 'Workspaces',
        'cloud_accounts': 'Cloud Accounts',
        'git_repos': 'Git Repositories',
        'github_repos': 'Git Repositories',
        'credentials': 'Credentials',
        'tasks': 'Tasks',
        'alerts': 'Alerts',
        'stats': 'Statistics',
        'analyst': 'Cloud Analyst',
        'logs': 'Logs',
        'aws': 'AWS',
        'azure': 'Azure',
        'gcp': 'GCP',
        'add': 'Add',
        'manage-sso': 'Manage Single Sign-On',
        'manage-github-app': 'GitHub App Registration',
        'manage-org-policy': 'Organization Policy',
        'manage-users': 'Manage Users',
        'manage-roles': 'Manage Roles',
    };

    // Get display name: use map for known routes, leave dynamic values untouched
    const getDisplayName = (segment, index) => {
        if (displayNameMap.hasOwnProperty(segment)) {
            return displayNameMap[segment];
        }
        return segment;
    };

    // Helper function to check if a segment should be non-clickable
    const isNonClickable = (segment, index) => {
        // Check if the segment is explicitly listed in nonClickableSegments
        if (nonClickableSegments.includes(segment)) {
            return true;
        }
        
        // Check if the segment follows any of the segments in nonClickablePositionAfter
        if (index > 0 && nonClickablePositionAfter.includes(pathSegments[index - 1])) {
            return true;
        }

        return false;
    };

    if (pathDisplay) {
        pathSegments.forEach((segment, index) => {
            const li = document.createElement('li');
            li.classList.add('breadcrumb-item');

            if (index === 0) {
                // "You are here:" text
                li.classList.add('text-muted');
                li.textContent = segment;
            } else if (index === pathSegments.length - 1) {
                // Last item (current page)
                li.classList.add('active');
                li.setAttribute('aria-current', 'page');
                li.textContent = getDisplayName(segment, index);
            } else if (isNonClickable(segment, index)) {
                // Non-clickable segment based on position or explicit non-clickable list
                li.textContent = getDisplayName(segment, index);
                li.classList.add('text-muted');
            } else {
                // Clickable breadcrumb items
                const link = document.createElement('a');
                link.href = '/' + pathSegments.slice(1, index + 1).join('/');
                link.textContent = getDisplayName(segment, index);
                li.appendChild(link);
            }

            pathDisplay.appendChild(li);
        });
    }

    const lastSegmentSpan = document.getElementById('last-segment');
    if (lastSegmentSpan) {
        const urlSegments = window.location.pathname.split('/').filter(segment => segment !== "");
        const lastSegment = urlSegments[urlSegments.length - 1] || "";
        lastSegmentSpan.textContent = lastSegment;
    }
});