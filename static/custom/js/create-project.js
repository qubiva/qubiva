$(document).ready(function() {
    const userSearchInput = document.getElementById('user-search');
    const membersContainer = document.getElementById('members-container');
    const createProjectForm = document.getElementById('create-project-form');
    const addedUsernames = new Set();
    const createProjectButton = document.getElementById('create-project-button');
    const spinner = document.getElementById('spinner');
    const projectModal = $('#projectModal');
    const modalBody = document.getElementById('modalBody');
    const viewProjectLink = document.getElementById('viewProjectLink');

    function initializeSelect2(element) {
        $(element).select2({
            theme: 'bootstrap4',
            dropdownParent: $(element).closest('.member-entry')
        }).on('select2:select select2:unselect', function (e) {
            // Handle Select2 events if needed
        });
    }

    function addUser(user) {
        const memberDiv = document.createElement('div');
        memberDiv.className = 'member-entry d-flex align-items-center justify-content-between mb-3 p-2 bg-light';
        memberDiv.innerHTML = `
            <span class="username" style="width: 150px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${user.username}</span>
            <select class="form-control select2bs4" multiple="multiple" data-placeholder="Select roles" style="flex: 1; margin-right: 10px;"></select>
            <button class="btn btn-link text-danger remove-user" style="padding: 0; margin-left: 10px;">
                <i class="fas fa-times"></i>
            </button>
        `;
        membersContainer.appendChild(memberDiv);
        const rolesSelect = memberDiv.querySelector('.select2bs4');

        fetch('/api/v1/projects/roles/list')
        .then(response => response.json())
        .then(roles => {
            roles.forEach(role => {
                const option = new Option(role, role, false, false);
                rolesSelect.appendChild(option);
            });
            initializeSelect2(rolesSelect);
        }).catch(error => console.error("Error fetching roles: ", error));

        const removeButton = memberDiv.querySelector('.remove-user');
        removeButton.onclick = () => {
            addedUsernames.delete(user.username);
            $(rolesSelect).select2('destroy');
            memberDiv.remove();
        };
    }

    userSearchInput.addEventListener('input', debounce(function() {
        const query = userSearchInput.value.trim();
        if (query.length > 2) {
            fetch(`/api/v1/users/search/?query=${query}`, {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            })
            .then(response => response.json())
            .then(users => {
                const userSearchResults = document.getElementById('user-search-results');
                userSearchResults.innerHTML = '';
                users.forEach(user => {
                    if (!addedUsernames.has(user.username)) {
                        const userElement = document.createElement('div');
                        userElement.className = 'user-search-result list-group-item list-group-item-action';
                        userElement.textContent = user.username;
                        userElement.onclick = () => {
                            addUser(user);
                            addedUsernames.add(user.username);
                            userSearchInput.value = '';
                            userSearchResults.innerHTML = '';
                        };
                        userSearchResults.appendChild(userElement);
                    }
                });
            }).catch(error => console.error("Error in search API: ", error));
        } else {
            document.getElementById('user-search-results').innerHTML = '';
        }
    }, 250));

    Qubiva.variableEntry.init();

    // Prevent autocomplete for project name
    $('#project-name').attr('autocomplete', 'off');

    createProjectForm.addEventListener('submit', function(event) {
        event.preventDefault();

        const projectName = document.getElementById('project-name').value.trim();
        const projectDescription = document.getElementById('project-description').value.trim();

        // Mandate project description
        if (!projectDescription) {
            showModal('Error', 'Project description is required.');
            return;
        }

        const members = Array.from(membersContainer.querySelectorAll('.member-entry')).map(memberEntry => {
            return {
                username: memberEntry.querySelector('span').textContent,
                roles: $(memberEntry.querySelector('.select2bs4')).val()
            };
        });

        const variables = {};
        const secrets = {};
        const keys = new Set();
        let hasDuplicateKeys = false;

        $('#variables-entries .variable-entry').each(function() {
            const key = $(this).find('input[name="variable-key"]').val().trim();
            const value = $(this).find('input[name="variable-value"]').val().trim();
            const isSecret = $(this).find('input[name="is-secret"]').is(':checked');
            
            if (key) {
                if (keys.has(key)) {
                    hasDuplicateKeys = true;
                    return false; // Break the loop
                }
                keys.add(key);
                
                if (isSecret) {
                    secrets[key] = value;
                } else {
                    variables[key] = value;
                }
            }
        });

        if (hasDuplicateKeys) {
            showModal('Error', 'Duplicate variable keys are not allowed.');
            return;
        }

        spinner.style.display = 'inline-block';
        createProjectButton.disabled = true;

        fetch('/api/v1/org/projects/create', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify({
                project_name: projectName,
                description: projectDescription,
                members: members,
                variables: variables,
                secrets: secrets
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.message) {
                console.log('Success:', data.message);
                createProjectForm.reset();
                membersContainer.innerHTML = '';
                addedUsernames.clear();
                $(membersContainer).find('.select2bs4').each(function() {
                    $(this).select2('destroy');
                });
                $('#variables-entries').empty();
                showModal('Success', data.message);
                viewProjectLink.href = `/dashboard/projects/${encodeURIComponent(projectName)}`;
                viewProjectLink.style.display = 'inline-block';
            } else if (data.detail) {
                console.error('Error:', data.detail);
                showModal('Error', Qubiva.extractError(data, 'Failed to create project'));
            }
        })
        .catch(error => {
            console.error('Request failed:', error);
            showModal('Error', 'Failed to create project.');
        })
        .finally(() => {
            spinner.style.display = 'none';
            createProjectButton.disabled = false;
        });
    });

    function showModal(title, message) {
        $('#projectModalLabel').text(title);
        modalBody.textContent = message;
        if (title === 'Error') {
            viewProjectLink.style.display = 'none';
        }
        projectModal.modal('show');
    }
});

function debounce(func, wait, immediate) {
    let timeout;
    return function() {
        const context = this, args = arguments;
        clearTimeout(timeout);
        timeout = setTimeout(() => {
            timeout = null;
            if (!immediate) func.apply(context, args);
        }, wait);
        if (immediate && !timeout) func.apply(context, args);
    };
}