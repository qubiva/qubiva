document.addEventListener('DOMContentLoaded', function() {
    
    function preventAutofill() {
        // Target basic form inputs
        const inputs = document.querySelectorAll('input[type="text"], input[type="password"], input[type="email"], input[type="number"], input[type="url"], input[type="tel"], textarea');
        
        inputs.forEach(function(input) {
            // Skip if already readonly or disabled
            if (input.hasAttribute('readonly') || input.disabled) return;
            
            // Add readonly initially
            input.setAttribute('readonly', 'true');
            input.style.backgroundColor = '#ffffff';
            input.setAttribute('data-autofill-readonly', 'true');
            
            // Remove readonly on focus
            input.addEventListener('focus', function() {
                this.removeAttribute('readonly');
            });
            
            // Add anti-autofill attributes
            input.setAttribute('autocomplete', input.type === 'password' ? 'new-password' : 'new-text');
        });
    }
    
    // Add dummy fields to forms
    function addDummyFields() {
        const forms = document.querySelectorAll('form');
        forms.forEach(function(form) {
            if (form.querySelector('.autofill-dummy')) return;
            
            const dummyContainer = document.createElement('div');
            dummyContainer.className = 'autofill-dummy';
            dummyContainer.style.display = 'none';
            
            const dummyText = document.createElement('input');
            dummyText.type = 'text';
            dummyText.name = 'prevent_autofill_text';
            dummyText.autocomplete = 'false';
            dummyText.tabIndex = -1;
            
            const dummyPassword = document.createElement('input');
            dummyPassword.type = 'password';
            dummyPassword.name = 'prevent_autofill_password';
            dummyPassword.autocomplete = 'false';
            dummyPassword.tabIndex = -1;
            
            dummyContainer.appendChild(dummyText);
            dummyContainer.appendChild(dummyPassword);
            form.insertBefore(dummyContainer, form.firstChild);
            
            form.setAttribute('autocomplete', 'off');
        });
    }
    
    // Apply both methods
    preventAutofill();
    addDummyFields();
    
    // Handle dynamic content
    const observer = new MutationObserver(function(mutations) {
        let shouldReapply = false;
        mutations.forEach(function(mutation) {
            if (mutation.type === 'childList' && mutation.addedNodes.length > 0) {
                mutation.addedNodes.forEach(function(node) {
                    if (node.nodeType === 1 && (node.tagName === 'FORM' || node.querySelector('form, input'))) {
                        shouldReapply = true;
                    }
                });
            }
        });
        
        if (shouldReapply) {
            setTimeout(function() {
                preventAutofill();
                addDummyFields();
            }, 100);
        }
    });
    
    observer.observe(document.body, {
        childList: true,
        subtree: true
    });
});