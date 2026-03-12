$(document).ready(function () {
    loadUsers(1); // Load the first page of users

    $('#user-search').on('input', function () {
        const query = $(this).val().toLowerCase();
        filterUsers(query);
    });

    $('#reset-button').on('click', function () {
        $('#user-search').val('');
        resetChanges();
        loadUsers(1); // Reload the full list from the first page
    });

    $('#save-changes-button').on('click', function () {
        saveChanges();
    });

    $(window).on('resize', function() {
        $('.select2bs4').select2({ theme: 'bootstrap4', width: '100%' });
    });

    $('.select2bs4').on('change', function() {
        console.log("selection was made")
        $(this).select2({ theme: 'bootstrap4', width: '100%' });
    });
});

const usersPerPage = 10;
let allUsers = []; // Original list of users
let displayedUsers = []; // Filtered/paginated list
let modifiedUsers = {}; // Track modified users (role changes)
let deletedUsers = new Set(); // Track deleted users by username

function loadUsers(page) {
    const usersContainer = $('#users-container');
    usersContainer.html('<div class="text-center w-100 my-5">Loading...</div>');

    $.ajax({
        url: "/api/v1/users/get_all_users/",
        method: "GET",
        dataType: "json",
        success: function (data) {
            allUsers = JSON.parse(JSON.stringify(data));
            displayedUsers = JSON.parse(JSON.stringify(data));
            renderUsers(page);
            setupPagination();
        },
        error: function (error) {
            console.error("Error fetching users:", error);
            usersContainer.html('<div class="text-center text-danger">Failed to load users</div>');
        }
    });
}

function renderUsers(page) {
    const usersContainer = $('#users-container');
    usersContainer.empty();

    const start = (page - 1) * usersPerPage;
    const end = start + usersPerPage;
    const paginatedUsers = displayedUsers.slice(start, end);

    paginatedUsers.forEach(user => {
        if (deletedUsers.has(user.username)) return; // Skip deleted users

        const userRow = $(`
            <div class="user-entry d-flex align-items-center mb-3" data-username="${user.username}">
                <span class="username" style="min-width: 200px; max-width: 250px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                    ${user.username || 'N/A'}
                </span>
                <select class="form-control select2bs4 user-roles" multiple="multiple" data-placeholder="Select roles" style="min-width: 250px; width: 100%;">
                    ${getRolesOptions(user)}
                </select>
                <button type="button" class="btn btn-link text-danger remove-user" style="padding: 0; margin-left: 10px;">
                    <i class="fas fa-times"></i>
                </button>
            </div>
        `);

        const rolesSelect = userRow.find('.user-roles');
        rolesSelect.select2({ theme: 'bootstrap4', width: '100%' }).val(getModifiedRoles(user.username)).trigger('change');

        rolesSelect.on('select2:select', function() {
            $(this).select2({ theme: 'bootstrap4', width: '100%' });
        });

        rolesSelect.on('change', function () {
            const username = userRow.data('username');
            modifiedUsers[username] = modifiedUsers[username] || {};
            modifiedUsers[username].roles = $(this).val(); // Track role changes
        });

        userRow.find('.remove-user').on('click', function () {
            const username = userRow.data('username');
            deletedUsers.add(username);
            modifiedUsers[username] = null; // Remove from modified if it exists
            userRow.remove(); // Remove the element from the display
        });

        usersContainer.append(userRow);
    });
}

function getRolesOptions(user) {
    const allRoles = ["org_admin", "org_editor", "org_viewer"];
    const userRoles = getModifiedRoles(user.username);
    return allRoles.map(role => {
        const isSelected = userRoles.includes(role);
        return `<option value="${role}" ${isSelected ? "selected" : ""}>${role}</option>`;
    }).join('');
}

function getModifiedRoles(username) {
    // Check modified first
    if (modifiedUsers[username]?.roles) {
        return modifiedUsers[username].roles;
    }
    
    // Find original user
    const originalUser = allUsers.find(user => user.username === username);
    
    // Return roles or empty array
    return originalUser?.org_roles || [];
}

function setupPagination() {
    const totalPages = Math.ceil(displayedUsers.length / usersPerPage);
    const paginationContainer = $('#pagination-container');
    paginationContainer.empty();

    for (let i = 1; i <= totalPages; i++) {
        const pageButton = $(`<button class="btn btn-secondary page-btn mr-1" data-page="${i}">${i}</button>`);
        paginationContainer.append(pageButton);
    }

    $('.page-btn').on('click', function (e) {
        e.preventDefault();
        const page = $(this).data('page');
        renderUsers(page);
    });
}

function filterUsers(query) {
    displayedUsers = allUsers.filter(user => {
        const usernameMatch = user.username && user.username.toLowerCase().includes(query);
        const rolesMatch = user.org_roles && user.org_roles.some(role => role.toLowerCase().includes(query));
        return (usernameMatch || rolesMatch) && !deletedUsers.has(user.username);
    });

    setupPagination();
    renderUsers(1); // Render first page of filtered results
}

function resetChanges() {
    modifiedUsers = {};
    deletedUsers.clear();
    displayedUsers = JSON.parse(JSON.stringify(allUsers)); // Restore the original list
}

function saveChanges() {
    const updatedUsers = [];
    const deletedUsersArray = Array.from(deletedUsers);

    // Disable the submit button to prevent multiple clicks
    $('#save-changes-button').prop('disabled', true);

    // Construct the payload for modified users in the required format
    for (const [username, changes] of Object.entries(modifiedUsers)) {
        if (changes && changes.roles) {  // Ensure roles is defined and is a list
            updatedUsers.push({ username: username, org_roles: changes.roles });
        }
    }

    // Prepare API requests for modified and deleted users
    const promises = [];

    if (updatedUsers.length > 0) {
        promises.push($.ajax({
            url: "/api/v1/org/users/modify-users-org-roles",
            method: "POST",
            contentType: "application/json",
            data: JSON.stringify({ users: updatedUsers }), // Send as a list of user objects
            success: function () {
                console.log("Successfully updated users' roles.");
            },
            error: function (jqXHR) {
                $('#errorMessage').html(Qubiva.extractError(jqXHR, 'Failed to update roles. Please try again.'));
                $('#errorModal').modal('show');
            }
        }));
    }

    if (deletedUsersArray.length > 0) {
        promises.push($.ajax({
            url: "/api/v1/org/users/delete",
            method: "POST",
            contentType: "application/json",
            data: JSON.stringify({ usernames: deletedUsersArray }), // Send as a list of usernames
            success: function () {
                console.log("Successfully deleted users.");
            },
            error: function (jqXHR) {
                $('#errorMessage').html(Qubiva.extractError(jqXHR, 'Failed to delete users. Please try again.'));
                $('#errorModal').modal('show');
            }
        }));
    }

    // Handle results from both API requests
    Promise.all(promises)
        .then(() => {
            $('#successModal').modal('show');
            loadUsers(1); // Reload the list to reflect saved changes
        })
        .catch(error => {
            console.error('Error saving changes:', error);
            $('#errorModal').modal('show');
        })
        .finally(() => {
            // Re-enable the submit button after the request is finished
            $('#save-changes-button').prop('disabled', false);
        });
}