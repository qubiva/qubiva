document.addEventListener('DOMContentLoaded', function () {
    const userPermissions = window.userPermissions || [];
    
    // Log user permissions at the start
    console.log('User Permissions:', userPermissions);

    function hasPermission(requiredPermissions) {
        console.log('Checking required permissions:', requiredPermissions);
    
        return requiredPermissions.every(permission => {
            console.log(`Checking if user has permission: ${permission}`);
    
            // If global wildcard '*' is present, grant permission
            if (userPermissions.includes('*')) {
                console.log(`Global wildcard '*' found, permission granted for ${permission}`);
                return true;
            }
    
            // Check if the exact permission exists
            if (userPermissions.includes(permission)) {
                console.log(`Permission granted for ${permission}`);
                return true;
            }
    
            // Check if a specific wildcard permission exists
            const wildcardMatch = userPermissions.some(userPermission => {
                const [base, wildcard] = userPermission.split('_');
                const match = wildcard === '*' && permission.startsWith(base + '_');
                if (match) {
                    console.log(`Permission granted for ${permission} through wildcard: ${userPermission}`);
                }
                return match;
            });
    
            if (!wildcardMatch) {
                console.log(`Permission denied for ${permission}`);
            }
    
            return wildcardMatch;
        });
    }
    
    function applyPermissions() {
        document.querySelectorAll('[data-permission]').forEach(element => {
            const requiredPermissions = JSON.parse(element.getAttribute('data-permission'));
            console.log('Element:', element);
            console.log('Required Permissions for Element:', requiredPermissions);

            if (!hasPermission(requiredPermissions)) {
                console.log('Restricting element due to insufficient permissions:', element);
                // CHANGED: Instead of hiding, add restricted class and disable interactions
                element.classList.add('permission-restricted');
                element.style.pointerEvents = 'none';
                
                // ADDED: Disable all form elements within the restricted element
                element.querySelectorAll('button, input, select, textarea, a').forEach(formElement => {
                    formElement.disabled = true;
                    if (formElement.tagName.toLowerCase() === 'a') {
                        formElement.style.pointerEvents = 'none';
                    }
                });
                
                // ADDED: Optional title to show why it's disabled
                element.setAttribute('title', 'Insufficient permissions');
            } else {
                console.log('Displaying element:', element);
            }
        });
    }

    // Apply permissions after all other scripts have run
    applyPermissions();
});

// ADDED: New CSS styles for restricted state
const style = document.createElement('style');
style.textContent = `
    .permission-restricted {
        opacity: 0.5;
        cursor: not-allowed !important;
        filter: grayscale(1);
        user-select: none;
        -webkit-user-select: none;
    }

    .permission-restricted * {
        cursor: not-allowed !important;
    }

    .permission-restricted button,
    .permission-restricted input,
    .permission-restricted select,
    .permission-restricted textarea,
    .permission-restricted a {
        opacity: 0.7;
    }
`;
document.head.appendChild(style);