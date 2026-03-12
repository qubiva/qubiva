$(document).ready(function() {
    const projectName = Qubiva.url.projectName();

    fetchProjectDetails(projectName);
    setupEventHandlers();

    Qubiva.variableEntry.init('#edit-project-form');
});

function fetchProjectDetails(projectName) {
    $.ajax({
        url: `/api/v1/projects/${projectName}`,
        method: 'GET',
        dataType: 'json',
        success: function(data) {
            console.log('Fetched Data:', data);  // Log data to ensure it's correct
            populateProjectForm(data);
            initialFormData = getCurrentFormData();
        },
        error: function(error) {
            console.error('Error fetching project details:', error);
        }
    });
}

function populateProjectForm(data) {
    $('#project-name').val(data.project_name);
    $('#project-description').val(data.description);
    $('#members-container').empty();

    data.members.forEach(member => {
        addMember(member.username, member.roles);
    });

    // Populate variables and secrets
    $('#variables-entries').empty();
    if (data.variables) {
        Object.entries(data.variables).forEach(([key, value]) => {
            Qubiva.variableEntry.add(key, value, false, '#edit-project-form');
        });
    }
    if (data.secrets) {
        Object.entries(data.secrets).forEach(([key, value]) => {
            Qubiva.variableEntry.add(key, value, true, '#edit-project-form');
        });
    }

    $('#edit-project-form').off('input').on('input', function() {
        const currentFormData = getCurrentFormData();
        const isFormChanged = JSON.stringify(initialFormData) !== JSON.stringify(currentFormData);
        $('#update-project-button').prop('disabled', !isFormChanged);
    });
}

function getCurrentFormData() {
    const projectDescription = $('#project-description').val();
    const members = [];
    const variables = {};
    const secrets = {};

    $('#members-container .member-entry').each(function() {
        const username = $(this).find('.username').text();
        const roles = $(this).find('.select2bs4').val();
        members.push({ username, roles });
    });

    $('#variables-entries .variable-entry').each(function() {
        const key = $(this).find('input[name="variable-key"]').val();
        const value = $(this).find('input[name="variable-value"]').val();
        const isSecret = $(this).find('input[name="is-secret"]').is(':checked');
        
        if (key) {
            if (isSecret) {
                secrets[key] = value;
            } else {
                variables[key] = value;
            }
        }
    });

    return { description: projectDescription, members, variables, secrets };
}

function addMember(username, roles) {
    if ($('#members-container .username').filter((_, el) => $(el).text() === username).length > 0) {
        return; // User is already added, do not add again
    }

    const memberDiv = $('<div class="member-entry d-flex align-items-center justify-content-between mb-3 p-2 bg-light"></div>');
    const memberSpan = $(`<span class="username" style="width: 150px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${username}</span>`);
    const rolesSelect = $('<select class="form-control select2bs4" multiple="multiple" data-placeholder="Select roles" style="flex: 1; margin-right: 10px;"></select>');
    const removeButton = $('<button class="btn btn-link text-danger remove-user" style="padding: 0; margin-left: 10px;"><i class="fas fa-times"></i></button>');

    memberDiv.append(memberSpan, rolesSelect, removeButton);
    $('#members-container').append(memberDiv);

    fetchRolesAndInitializeSelect2(rolesSelect, roles);

    removeButton.click(function() {
        memberDiv.remove();
        $('#edit-project-form').trigger('input');
    });
}

function fetchRolesAndInitializeSelect2(rolesSelect, selectedRoles) {
    $.ajax({
        url: '/api/v1/projects/roles/list',
        method: 'GET',
        dataType: 'json',
        success: function(roles) {
            roles.forEach(role => {
                const isSelected = selectedRoles.includes(role);
                const option = new Option(role, role, isSelected, isSelected);
                rolesSelect.append(option);
            });

            $(rolesSelect).select2({
                theme: 'bootstrap4',
                dropdownParent: rolesSelect.closest('.member-entry')
            }).trigger('change');
        },
        error: function(error) {
            console.error('Error fetching roles:', error);
        }
    });
}

function setupEventHandlers() {
    $('#edit-project-form').off('submit').on('submit', function(event) {
        event.preventDefault();
        updateProject();
    });

    $('#user-search').on('input', debounce(function() {
        const query = $(this).val().trim();
        if (query.length > 2) {
            searchUsers(query);
        } else {
            $('#user-search-results').empty();
        }
    }, 250));

}

function updateProject() {
    $('#update-project-button').prop('disabled', true);
    $('#spinner').show();

    const projectName = $('#project-name').val();
    const formData = getCurrentFormData();

    // Check if project description is empty
    if (!formData.description.trim()) {
        showError('Project description is required.');
        return;
    }

    // Check for duplicate variable keys
    const allKeys = [...Object.keys(formData.variables), ...Object.keys(formData.secrets)];
    const uniqueKeys = new Set(allKeys);
    if (allKeys.length !== uniqueKeys.size) {
        showError('Duplicate variable keys are not allowed.');
        return;
    }

    $.ajax({
        url: `/api/v1/projects/${projectName}/edit`,
        method: 'PUT',
        contentType: 'application/json',
        data: JSON.stringify(formData),
        success: function(data) {
            $('#successModal').modal('show');
            $('#modalMessage').text(data.message);
            $('#viewProjectButton').off('click').on('click', function() {
                window.location.href = `/dashboard/projects/${projectName}`;
            });
        },
        error: function(xhr) {
            showError(Qubiva.extractError(xhr, 'Failed to update the project. Please try again.'));
        },
        complete: function() {
            $('#update-project-button').prop('disabled', false);
            $('#spinner').hide();
        }
    });
}

function showError(message) {
    $('#failureMessage').text(message);
    $('#failureModal').modal('show');
    $('#update-project-button').prop('disabled', false);
    $('#spinner').hide();
}

function searchUsers(query) {
    $.ajax({
        url: `/api/v1/users/search/?query=${query}`,
        method: 'GET',
        dataType: 'json',
        success: function(data) {
            const resultsContainer = $('#user-search-results');
            resultsContainer.empty();

            data.forEach(user => {
                if ($('#members-container .username').filter((_, el) => $(el).text() === user.username).length > 0) {
                    return; // Skip users that are already added
                }

                const userElement = $(`<div class="user-search-result list-group-item list-group-item-action">${user.username}</div>`);
                userElement.click(function() {
                    addMember(user.username, []);
                    $('#user-search').val('');
                    resultsContainer.empty();
                });
                resultsContainer.append(userElement);
            });
        },
        error: function(error) {
            console.error('Error searching users:', error);
        }
    });
}

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