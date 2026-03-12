$(document).ready(function () {
    setupEventHandlers();
    fetchOrgRoles();

    // Initialize Select2 fields and add resize listener for reinitialization
    initializeSelect2();
    $(window).on('resize', function () {
        initializeSelect2(); // Reinitialize Select2 on window resize
    });

    // Add an initial user entry programmatically
        // Add initial user entry programmatically
    if ($('#users-container .user-entry').length === 0) {
        addUserEntry();
        setTimeout(() => {
            $('.select2-search__field').css('width', '100%'); // Ensure placeholder fix applies
        }, 1);
    }
});

function setupEventHandlers() {
    $('#add-user-entry').on('click', function () {
        addUserEntry();
    });

    $('#add-users-form').on('submit', function (event) {
        event.preventDefault();
        submitUsers();
    });

    $(document).on('click', '.remove-user', function () {
        $(this).closest('.user-entry').remove();
    });
}

function fetchOrgRoles() {
    $.ajax({
        url: '/api/v1/org/list_org_roles',
        method: 'GET',
        dataType: 'json',
        success: function (roles) {
            window.availableRoles = roles; // Store roles globally for reuse
            populateAllRoles();
        },
        error: function (error) {
            console.error('Error fetching organization roles:', error);
            showErrorModal('Failed to fetch roles. Please try again.');
        }
    });
}

function populateAllRoles() {
    $('#users-container .user-roles').each(function () {
        populateRoles($(this));
    });
}

function populateRoles(selectElement) {
    selectElement.empty(); // Clear any existing options
    if (window.availableRoles && window.availableRoles.length > 0) {
        window.availableRoles.forEach(function (role) {
            const option = new Option(role, role, false, false);
            selectElement.append(option);
        });
    }
    selectElement.select2({
        theme: 'bootstrap4',
        width: '100%',
        placeholder: 'Select roles'
    });
}

function addUserEntry() {
    const userEntry = $(`
        <div class="user-entry d-flex align-items-center mb-3">
            <input type="email" class="form-control mr-1 user-email" name="username[]" placeholder="User email" required style="min-width: 200px; max-width: 250px; height: 33px; padding: 0.375rem 0.75rem;margin-right: 0.5rem !important; box-sizing: border-box;">
            <select class="form-control select2bs4 user-roles" name="org_roles[]" multiple="multiple" style="min-width: 250px; height: 38px;"></select>
            <button type="button" class="btn btn-link text-danger remove-user" style="padding: 0; margin-left: 10px;">
                <i class="fas fa-times"></i>
            </button>
        </div>
    `);

    $('#users-container').append(userEntry);
    const newSelect = userEntry.find('.user-roles');
    populateRoles(newSelect); // Populate the roles in the new select element

    // Force the placeholder fix for the newly added entry
    setTimeout(() => {
        $('.select2-search__field').css('width', '100%');
    }, 1);
}

function initializeSelect2() {
    $('.user-roles').each(function () {
        if ($(this).hasClass('select2-hidden-accessible')) {
            $(this).select2('destroy'); // Destroy existing Select2 instance
        }
        $(this).select2({
            theme: 'bootstrap4',
            width: '100%',
            placeholder: 'Select roles'
        });

        // Adjust the width of the placeholder field to fit the container
        $(this).on('select2:open', function () {
            setTimeout(function () {
                $('.select2-search__field').css('width', '100%'); // Force width to 100% on open
            }, 1); // Use a small delay to ensure it applies after opening
        });

        $('.select2-search__field').css('width', '100%');
    });
}

function submitUsers() {
    const users = [];
    let hasEmptyEmail = false; // Track if there is an empty email

    $('#users-container .user-entry').each(function () {
        const email = $(this).find('.user-email').val();
        const roles = $(this).find('.user-roles').val() || []; // Ensure roles is an empty array if no selection

        if (!email) {
            hasEmptyEmail = true; // Mark that we found an empty email
            return false; // Break out of `.each` loop
        }

        const user = { username: email };
        if (roles.length > 0) {
            user.org_roles = roles;
        }

        users.push(user);
    });

    if (hasEmptyEmail) {
        showErrorModal('Please enter an email for each user.');
        return; // Stop further execution if there's an empty email
    }

    // Check for duplicate usernames
    const usernames = users.map(user => user.username);
    const uniqueUsernames = new Set(usernames);
    if (usernames.length !== uniqueUsernames.size) {
        showErrorModal('Duplicate email addresses are not allowed.');
        return;
    }

    // Verify that we have users to submit
    if (users.length === 0) {
        showErrorModal('Please add at least one user before submitting.');
        return;
    }

    // Debugging: Log the payload to the console before sending
    const payload = { users: users };
    console.log('Payload being sent:', JSON.stringify(payload, null, 2));

    // Disable submit button to prevent duplicate submissions
    $('#submit-users-button').prop('disabled', true).text('Submitting...');

    // AJAX request to submit users
    $.ajax({
        url: '/api/v1/org/users/add',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(payload), // Ensure that users is included in the payload
        success: function (response) {
            showSuccessModal(response.message);
            $('#userModal').on('hidden.bs.modal', function () {
                resetForm(); // Reset the form after success modal is closed
            });
        },
        error: function (xhr) {
            showErrorModal(Qubiva.extractError(xhr, 'Failed to add users. Please try again.'));
        },
        complete: function () {
            $('#submit-users-button').prop('disabled', false).text('Submit'); // Re-enable submit button
        }
    });
}

function resetForm() {
    $('#users-container').empty();
    addUserEntry(); // Add a single empty user entry
}

function showSuccessModal(message) {
    $('#userModal .modal-title').text('Success');
    $('#userModal .modal-body').html(message);
    $('#userModal').modal('show');
}

function showErrorModal(message) {
    $('#userModal .modal-title').text('Error');
    $('#userModal .modal-body').html(message);
    $('#userModal').modal('show');
}
