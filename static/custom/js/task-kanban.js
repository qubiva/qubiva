$(function() {

    const currentUser = (typeof getCurrentUser === 'function') ? getCurrentUser() : 'Anonymous';

    // Helper function to safely parse JSON response and detect login page redirects
    async function safeJsonParse(response) {
        const contentType = response.headers.get('content-type');

        // If we received HTML instead of JSON, it's likely a login page redirect
        if (contentType && contentType.includes('text/html')) {
            console.error('Session expired - received HTML instead of JSON');
            // Redirect to login page or reload to trigger authentication
            window.location.href = '/login?redirect=' + encodeURIComponent(window.location.pathname);
            throw new Error('Session expired. Redirecting to login...');
        }

        // If it's JSON, parse it safely
        if (contentType && contentType.includes('application/json')) {
            return await response.json();
        }

        // Try to parse as JSON, but catch errors
        try {
            return await response.json();
        } catch (error) {
            // If parsing fails, check if response is HTML
            const text = await response.text();
            if (text.trim().startsWith('<!DOCTYPE') || text.trim().startsWith('<html')) {
                console.error('Session expired - received HTML instead of JSON');
                window.location.href = '/login?redirect=' + encodeURIComponent(window.location.pathname);
                throw new Error('Session expired. Redirecting to login...');
            }
            // Re-throw original parsing error if it's not HTML
            throw error;
        }
    }

    // Extract project name from the current URL
    const urlPath = window.location.pathname;
    const pathParts = urlPath.split('/');
    const projectName = pathParts[3];
    const taskUrlPattern = /\/dashboard\/projects\/[^\/]+\/tasks\/(\d+)/;
    const match = window.location.pathname.match(taskUrlPattern);
    let taskToDelete = null;
    let currentTags = [];

    // If a task ID is found in the URL, open the task modal
    if (match && match[1]) {
        const taskId = match[1];
        console.log('Task ID in URL:', taskId); // Log the extracted task ID
        openTaskModal(taskId);
    }

    // Hardcoded discussions (for task modal)
    const discussions = {
        1: [
            { author: 'Alice', content: 'This needs to be fixed ASAP.', timestamp: '2024-09-15 14:30' },
            { author: 'Bob', content: "I'm on it.", timestamp: '2024-09-16 09:00' }
        ]
    };
       

    let currentView = 'grid';  // Default to grid view
    let itemsPerPage = 6;  // Default items per page
    let currentPage = 1;  // Current page
    let currentSprintId = getLatestSprintId();

    let currentSearchRequest = null;  // Add this at the top with other variables

    function performUserSearch(searchTerm, resultsList) {
        resultsList.empty();

        if (searchTerm.length === 0) {
            resultsList.hide();
            return;
        }

        // Abort any in-flight request
        if (currentSearchRequest) {
            currentSearchRequest.abort();
        }

        currentSearchRequest = $.ajax({
            url: `/api/v1/projects/${projectName}/members`,
            data: { search: searchTerm },
            success: function(users) {
                if (users.length > 0) {
                    users.forEach(email => {
                        resultsList.append(`<li class="list-group-item user-search-result">${email}</li>`);
                    });
                    resultsList.show();
                } else {
                    resultsList.hide();
                }
            },
            error: function() {
                resultsList.hide();
            },
            complete: function() {
                currentSearchRequest = null;
            }
        });
    }
    
    async function fetchSprints() {
        try {
            const response = await fetch(`/api/v1/projects/${projectName}/sprints`, {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });
            const data = await safeJsonParse(response);
            return data.sprints; // Assuming the response contains a "sprints" array
        } catch (error) {
            console.error('Failed to fetch sprints:', error);
            return [];
        }
    }

    async function updateSprintAPI(projectName, sprintId, sprintData) {
        try {
            const response = await fetch(`/api/v1/projects/${projectName}/sprints/${sprintId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify(sprintData)
            });
    
            if (!response.ok) {
                const errorData = await safeJsonParse(response);
                const detail = errorData.detail;
                const msg = typeof detail === 'string' ? detail
                    : Array.isArray(detail) ? detail.map(e => e.msg || JSON.stringify(e)).join('; ')
                    : detail ? JSON.stringify(detail) : 'Failed to update sprint';
                throw new Error(msg);
            }
    
            return await safeJsonParse(response);  // Return the response data
        } catch (error) {
            throw new Error(`Error updating sprint: ${error.message}`);
        }
    }

    async function saveSprintChanges(sprintId) {
        const sprintData = {
            start_date: $('#sprint-start-date').val(),
            end_date: $('#sprint-end-date').val(),
            goal: $('#sprint-goal').val()
        };
    
        try {
            // Use the updateSprintAPI function to perform the API operation
            const result = await updateSprintAPI(projectName, sprintId, sprintData);
    
            // Reset the modal after saving changes
            $('#sprint-modal').modal('hide');
            $('#sprint-form')[0].reset();  // Reset the form
            $('#success-modal-message').text('Sprint updated successfully.');
            $('#success-modal').modal('show');
    
            // Use the existing mechanism to update the sprint dropdown
            await populateDropdowns();  // Same as when creating a new sprint
        } catch (error) {
            console.error('Error saving sprint changes:', error);
            $('#failure-modal-message').text(`Error: ${error.message}`);
            $('#failure-modal').modal('show');
        }
    }

    async function fetchStatusOptions() {
        try {
            const response = await fetch('/api/v1/tasks/list_status_options', {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });
            const data = await safeJsonParse(response);
            return data;
        } catch (error) {
            console.error('Failed to fetch status options:', error);
            return [];
        }
    }
    
    async function fetchTaskTypeOptions() {
        try {
            const response = await fetch('/api/v1/tasks/list_task_type_options', {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });
            const data = await safeJsonParse(response);
            return data;
        } catch (error) {
            console.error('Failed to fetch task type options:', error);
            return [];
        }
    }
    
    async function fetchPriorityOptions() {
        try {
            const response = await fetch('/api/v1/tasks/list_priority_options', {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });
            const data = await safeJsonParse(response);
            return data;
        } catch (error) {
            console.error('Failed to fetch priority options:', error);
            return [];
        }
    }

    async function createTaskAPI(taskData) {
        try {
            const response = await fetch(`/api/v1/projects/${projectName}/tasks/create`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify(taskData)
            });
    
            if (!response.ok) {
                const errorData = await safeJsonParse(response);
                const detail = errorData.detail;
                const msg = typeof detail === 'string' ? detail
                    : Array.isArray(detail) ? detail.map(e => e.msg || JSON.stringify(e)).join('; ')
                    : detail ? JSON.stringify(detail) : 'Failed to create task';
                throw new Error(msg);
            }
    
            return await safeJsonParse(response);
        } catch (error) {
            console.error('Error creating task:', error);
            throw error;
        }
    }

    async function updateTaskAPI(taskId, taskData) {
        console.log('Payload being sent to edit task:', JSON.stringify(taskData, null, 2)); // Log payload in a readable format
    
        try {
            const response = await fetch(`/api/v1/projects/${projectName}/tasks/edit/${taskId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify(taskData)
            });
    
            if (!response.ok) {
                const errorData = await safeJsonParse(response);
                const detail = errorData.detail;
                const msg = typeof detail === 'string' ? detail
                    : Array.isArray(detail) ? detail.map(e => e.msg || JSON.stringify(e)).join('; ')
                    : detail ? JSON.stringify(detail) : 'Failed to update task';
                throw new Error(msg);
            }
    
            return await safeJsonParse(response);
        } catch (error) {
            console.error('Error updating task:', error);
            throw error;
        }
    }    

    async function fetchTasksFromAPI(sprintId = null, status = null) {
        try {
            let url = `/api/v1/projects/${projectName}/tasks`;
            const params = new URLSearchParams();
            if (sprintId) params.append('sprint_id', sprintId);
            if (status) params.append('status', status);
            if (params.toString()) url += '?' + params.toString();

            const response = await fetch(url, {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });
            if (!response.ok) {
                throw new Error('Failed to fetch tasks');
            }
            const tasks = await safeJsonParse(response);

            // Debug: Log first task to see structure
            if (tasks.length > 0) {
                console.log('Sample task data:', {
                    id: tasks[0].id,
                    dueDate: tasks[0].dueDate,
                    status: tasks[0].status,
                    is_overdue: tasks[0].is_overdue
                });
            }

            return tasks;
        } catch (error) {
            console.error('Error fetching tasks:', error);
            throw error;
        }
    }
    

    // Update the getLatestSprintId function
    async function getLatestSprintIdold() {
        const sprints = await fetchSprints(); // Fetch the sprint IDs from the API
        
        if (sprints.length === 0) {
            return null; // No sprints available
        }
    
        // Extract the year and number from each sprint ID (assuming the format "YYYY-N")
        const sprintDetails = sprints.map(sprintId => {
            const [year, number] = sprintId.split('-').map(Number);
            return { year, number, id: sprintId };
        });
    
        // Sort by year first (descending) and then by sprint number (descending)
        const latestSprint = sprintDetails.sort((a, b) => {
            if (b.year !== a.year) {
                return b.year - a.year; // Sort by year first
            } else {
                return b.number - a.number; // If years are the same, sort by sprint number
            }
        })[0]; // The first item in the sorted array will be the latest sprint
        console.log("latest sprint id is", latestSprint.id);
        return latestSprint.id;
    }    
    
    async function getLatestSprintId() {
        try {
            const response = await fetch(`/api/v1/projects/${projectName}/sprints/nearest`, {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });            
            
            if (!response.ok) {
                throw new Error(`Failed to fetch nearest sprint: ${response.status} ${response.statusText}`);
            }
    
            // Fetch the response as text
            const sprintId = await safeJsonParse(response);
            
            // Optionally, you can validate if the response should be a valid ID format, e.g., a non-empty string
            if (!sprintId) {
                throw new Error('Sprint ID is empty');
            }
            console.log("latest sprint id is", sprintId);
            return sprintId;
        } catch (error) {
            console.error('Error fetching nearest sprint ID:', error);
            return null;
        }
    }
    
    async function findTaskById(taskId) {
        try {
            const response = await fetch(`/api/v1/projects/${projectName}/tasks/${taskId}`, {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });            
            if (!response.ok) {
                throw new Error('Failed to fetch task');
            }
            return await safeJsonParse(response);
        } catch (error) {
            console.error('Error fetching task:', error);
            return null;
        }
    }

    async function populateDropdowns() {
        const dropdowns = {
            sprint: $('#filter-sprint'),
            status: $('#filter-status'),
            type: $('#filter-task-type'),
            tags: $('#filter-tags'),
            priority: $('#filter-priority'),
        };
    
        // Fetch data
        const statusOptions = await fetchStatusOptions();
        const taskTypeOptions = await fetchTaskTypeOptions();
        const priorityOptions = await fetchPriorityOptions();
        const sprints = await fetchSprints();
        const latestSprintId = await getLatestSprintId();
    
        // Populate sprint filter
        dropdowns.sprint.empty();
        if (latestSprintId) {
            dropdowns.sprint.append(`<option value="${latestSprintId}">Current Sprint (${latestSprintId})</option>`);
        }
        dropdowns.sprint.append('<option value="backlog">Backlog</option>');
        sprints.forEach(sprintId => {
            if (sprintId !== latestSprintId) {
                dropdowns.sprint.append(`<option value="${sprintId}">${sprintId}</option>`);
            }
        });
    
        // Populate status filter
        dropdowns.status.empty();
        dropdowns.status.append('<option value="">All Statuses</option>');
        statusOptions.forEach(status => {
            dropdowns.status.append(`<option value="${status}">${status.replace('_', ' ')}</option>`);
        });
    
        // Populate type filter
        dropdowns.type.empty();
        dropdowns.type.append('<option value="">All Types</option>');
        taskTypeOptions.forEach(type => {
            dropdowns.type.append(`<option value="${type}">${type}</option>`);
        });
    
        // Populate tags filter
        try {
            const tags = await fetchProjectTags();
            dropdowns.tags.empty();
            dropdowns.tags.append('<option value="">All Tags</option>');
            tags.forEach(tag => {
                dropdowns.tags.append(`<option value="${tag}">${tag}</option>`);
            });
        } catch (error) {
            console.error('Error fetching tags:', error);
            dropdowns.tags.empty();
            dropdowns.tags.append('<option value="">All Tags</option>');
        }
    
        // Populate priority filter
        dropdowns.priority.empty();
        dropdowns.priority.append('<option value="">All Priorities</option>');
        priorityOptions.forEach(priority => {
            dropdowns.priority.append(`<option value="${priority}">${priority}</option>`);
        });
    
        // Initialize Select2 for filter dropdowns
        $('.select2:not(#task-modal .select2)').select2({
            theme: 'bootstrap4',
            width: '100%'
        }).on('change', function() {
            currentPage = 1;
            renderTasks($('#tasks-search-box').val());
            renderPagination();
        });
    
        const tasks = await renderTasks($('#tasks-search-box').val());
        renderPagination(tasks);
    }
    
    async function populateTaskModalDropdowns() {
        const dropdowns = {
            sprint: $('#task-sprint'),
            status: $('#task-status'),
            type: $('#task-type'),
            tags: $('#task-tags'),
            priority: $('#task-priority'),
        };
    
        // Fetch all required data
        const statusOptions = await fetchStatusOptions();
        const taskTypeOptions = await fetchTaskTypeOptions();
        const priorityOptions = await fetchPriorityOptions();
        const sprints = await fetchSprints();
        const latestSprintId = await getLatestSprintId();
    
        // Populate sprint dropdown
        dropdowns.sprint.empty();
        if (latestSprintId) {
            dropdowns.sprint.append(`<option value="${latestSprintId}">Current Sprint (${latestSprintId})</option>`);
        }
        dropdowns.sprint.append('<option value="backlog">Backlog</option>');
        sprints.forEach(sprintId => {
            if (sprintId !== latestSprintId) {
                dropdowns.sprint.append(`<option value="${sprintId}">${sprintId}</option>`);
            }
        });
    
        // Populate status dropdown
        dropdowns.status.empty().append('<option value="" disabled selected>Select Status</option>');
        statusOptions.forEach(status => {
            dropdowns.status.append(`<option value="${status}">${status.replace('_', ' ')}</option>`);
        });
    
        // Populate type dropdown
        dropdowns.type.empty().append('<option value="" disabled selected>Select Type</option>');
        taskTypeOptions.forEach(type => {
            dropdowns.type.append(`<option value="${type}">${type}</option>`);
        });
    
        // Populate tags dropdown
        try {
            const tags = await fetchProjectTags();
            dropdowns.tags.empty();
            tags.forEach(tag => {
                dropdowns.tags.append(`<option value="${tag}">${tag}</option>`);
            });
        } catch (error) {
            console.error('Error fetching tags:', error);
            dropdowns.tags.empty().append('<option value="" disabled selected>Select Tags</option>');
        }
    
        // Populate priority dropdown
        dropdowns.priority.empty().append('<option value="" disabled selected>Select Priority</option>');
        priorityOptions.forEach(priority => {
            dropdowns.priority.append(`<option value="${priority}">${priority}</option>`);
        });
    
        // Initialize Select2 for task modal dropdowns
        $('#task-modal .select2').select2({
            theme: 'bootstrap4',
            width: '100%'
        });
    
        $('#task-tags').select2({
            tags: false,
            tokenSeparators: [',', ' '],
            placeholder: "Select or type tags",
            theme: 'bootstrap4',
            allowClear: true
        });
    }
    
    async function renderDefaultLayout() {
        currentView = 'grid';
        $('#gridViewBtn').addClass('active');
        $('#listViewBtn').removeClass('active');
        $('#filter-sprint').val('').trigger('change.select2'); // Reset sprint filter to "All Sprints"
        const tasks = await renderTasks();
        renderPagination(tasks);
    }

    function createUserSearchInput(containerId) {
        const container = $(`#${containerId}`);
        
        if (container.find('.user-search').length === 0) {
            const inputHtml = `
                <div class="user-search-container">
                    <input type="search" class="form-control user-search" placeholder="Search for a user...">
                    <ul class="user-search-results list-group"></ul>
                </div>
            `;
            container.html(inputHtml);
        }
        
        const input = container.find('.user-search');
        const resultsList = container.find('.user-search-results');
    
        input.off('input').on('input', function() {
            const searchTerm = $(this).val().toLowerCase();
            performUserSearch(searchTerm, resultsList);
            
            // Apply filter immediately when input is cleared
            if (searchTerm === '') {
                applyFilter();
            }
        });
    
        resultsList.off('click').on('click', 'li', function() {
            const selectedEmail = $(this).text();
            input.val(selectedEmail);
            resultsList.empty().hide();
            applyFilter();
        });
    
        // Handle clicks outside the search container
        $(document).off('click.userSearch').on('click.userSearch', function(event) {
            if (!$(event.target).closest('.user-search-container').length) {
                resultsList.empty().hide();
            }
        });
    
        // Add keyup event to handle Enter key
        input.off('keyup').on('keyup', function(e) {
            if (e.key === 'Enter') {
                resultsList.empty().hide();
                applyFilter();
            }
        });
    
        function applyFilter() {
            currentPage = 1;
            renderTasks($('#tasks-search-box').val());
            renderPagination();
        }
    }
      
    async function openTaskModal(taskId = null) {
        console.log('openTaskModal called with taskId:', taskId);

        try {
            // Clear previous comment data and reset to Write tab
            $('#new-comment-input').empty();
            $('#new-comment-preview').html('<p class="text-muted">Nothing to preview</p>');
            $('#write-tab').tab('show');  // Switch to Write tab
            $('#discussion-container').empty();  // Clear previous comments

            // Create user search input for task assignment
            createUserSearchInput('task-assigned-container');

            // Populate the dropdowns in the task modal
            await populateTaskModalDropdowns();

            $('#task-title').prop('required', true);
            $('#task-description').prop('required', true);
            $('#task-type').prop('required', true);
            $('#task-status').prop('required', true);
            $('#task-priority').prop('required', true);
            $('#task-sprint').prop('required', true);
            $('#task-due-date').prop('required', false);  // Due date is optional
    
            if (taskId) {
                console.log('Fetching task details for taskId:', taskId);
                const response = await fetch(`/api/v1/projects/${projectName}/tasks/${taskId}`, {
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                });                
                if (!response.ok) {
                    throw new Error('Failed to fetch task details');
                }
    
                const task = await safeJsonParse(response);
                console.log('Task details fetched:', task);
    
                // Set form values
                $('#task-id').val(task.id);
                $('#task-title').val(task.title);
                $('#task-description').val(task.description);
                $('#task-type').val(task.type).trigger('change');
                $('#task-status').val(task.status).trigger('change');
                $('#task-priority').val(task.priority).trigger('change');
                $('#task-assigned-container .user-search').val(task.assignedTo || '');
                $('#task-due-date').val(task.dueDate);
    
                // Handle tags
                const availableTags = await fetchProjectTags();
                const validTaskTags = task.tags.filter(tag => availableTags.includes(tag));
                $('#task-tags').val(validTaskTags).trigger('change');
    
                // Set sprint value
                $('#task-sprint').val(task.sprintId || 'backlog').trigger('change');
                $('#task-modal-title').text(`Task #${task.id}`);
    
                // Handle discussions
                discussions[taskId] = [];
                const commentsResponse = await fetch(`/api/v1/projects/${projectName}/tasks/${taskId}/comments`, {
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                });                
                if (!commentsResponse.ok) {
                    throw new Error('Failed to fetch comments');
                }
                const comments = await commentsResponse.json();
                discussions[taskId] = comments.reverse();
                populateDiscussion(discussions[taskId]);
                $('.discussion-section').show();
    
                // Handle relationships
                $('#task-relationships-container').empty();
                if (task.relationships && task.relationships.length > 0) {
                    task.relationships.forEach(rel => addRelationshipField(rel.relatedTaskId, rel.type));
                }
    
                $('#task-reverse-relationships-container').empty();
                if (task.reverse_relationships && task.reverse_relationships.length > 0) {
                    task.reverse_relationships.forEach(rel => {
                        const isDuplicate = task.relationships.some(
                            directRel => directRel.relatedTaskId === rel.relatedTaskId && 
                            directRel.type === get_opposite_relationship_type(rel.type)
                        );
                        if (!isDuplicate) {
                            addRelationshipField(rel.relatedTaskId, rel.type, true);
                        }
                    });
                    $('#reverse-relationships-group').removeClass('d-none');
                } else {
                    $('#task-reverse-relationships-container').html('<span class="text-muted">None</span>');
                    $('#reverse-relationships-group').removeClass('d-none');
                }
    
                $('#new-comment').val('');
            } else {
                // Handle new task case
                $('#task-form')[0].reset();
                $('#task-id').val('');
                
                const latestSprintId = await getLatestSprintId();
                $('#task-sprint').val(latestSprintId || 'backlog').trigger('change');
                
                $('#task-modal-title').text('New Task');
                $('#task-relationships-container').empty();
                $('#reverse-relationships-group').addClass('d-none');
                $('#task-reverse-relationships-container').empty();
                $('.discussion-section').hide();
            }
    
            $('#task-sprint').prop('disabled', false);
            $('#add-relationship-btn').off('click').on('click', function() {
                addRelationshipField();
            });
    
            $('#task-modal').modal('show');
        } catch (error) {
            console.error('Error in openTaskModal:', error);
            $('#failure-modal-message').text(`Error: ${error.message}`);
            $('#failure-modal').modal('show');
        }
    }    
    
    async function loadComments(taskId) {
        try {
            const response = await fetch(`/api/v1/projects/${projectName}/tasks/${taskId}/comments`, {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });            
            if (!response.ok) {
                throw new Error('Failed to fetch comments');
            }
            const comments = await safeJsonParse(response);
            populateDiscussion(comments);
        } catch (error) {
            console.error('Error fetching comments:', error);
        }
    }

    async function fetchProjectTags() {
        try {
            const response = await fetch(`/api/v1/projects/${projectName}/tags`, {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });            
            if (!response.ok) {
                throw new Error('Failed to fetch tags');
            }
            const data = await safeJsonParse(response);
            return data.tags;
        } catch (error) {
            console.error('Error fetching tags:', error);
            return [];
        }
    }
    
    async function updateProjectTags(tags) {
        try {
            const response = await fetch(`/api/v1/projects/${projectName}/tags/update`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify({ tags })
            });
            
            if (!response.ok) {
                throw new Error('Failed to update tags');
            }
            return await safeJsonParse(response);
        } catch (error) {
            console.error('Error updating tags:', error);
            throw error;
        }
    }
    
    function renderTagsInModal(tags) {
        const container = $('#tags-container');
        container.empty();
        
        tags.forEach(tag => {
            const tagString = String(tag); // Ensure tag is treated as string
            container.append(`
                <div class="badge badge-info m-1 p-2 tag-item">
                    <span class="tag-text">${tagString}</span>
                    <span class="close ml-2" data-tag="${tagString}" style="cursor: pointer; user-select: none;">×</span>
                </div>
            `);
        });
    }
    
    
    $('#save-task').click(async function() {
        const requiredFields = {
            'task-title': 'Title',
            'task-description': 'Description',
            'task-type': 'Type',
            'task-status': 'Status',
            'task-priority': 'Priority',
            'task-sprint': 'Sprint'
            // Due date is optional, not required
        };

        let missingFields = [];
        for (const [id, label] of Object.entries(requiredFields)) {
            const field = $(`#${id}`);
            const value = field.val();
            
            // Special check for text inputs to prevent just spaces
            if (field.is('input[type="text"], textarea')) {
                if (!value || !value.trim()) {
                    missingFields.push(label);
                    field.addClass('is-invalid');
                } else {
                    field.removeClass('is-invalid');
                }
            } else {
                // For other inputs (select dropdowns, date inputs, etc.)
                if (!value) {
                    missingFields.push(label);
                    field.addClass('is-invalid');
                } else {
                    field.removeClass('is-invalid');
                }
            }
        }

        if (missingFields.length > 0) {
            $('#failure-modal-message').html(`Please fill in the following required fields: ${missingFields.join(', ')}`);
            $('#failure-modal').modal('show');
            return;
        }

        let taskId = $('#task-id').val();
        let isNewTask = taskId === '';

        let assignedTo = $('#task-assigned-container .user-search').val().trim();
        
        let taskData = {
            title: $('#task-title').val(),
            description: $('#task-description').val(),
            type: $('#task-type').val(),
            status: $('#task-status').val(),
            priority: $('#task-priority').val(),
            assignedTo: assignedTo === "" ? null : assignedTo,
            dueDate: $('#task-due-date').val(),
            tags: $('#task-tags').val() || [],
            relationships: [],
            sprintId: $('#task-sprint').val() === 'backlog' ? null : $('#task-sprint').val()
        };

        // Gather relationships data
        $('.relationship-field:not(.reverse-relationship)').each(function() {
            const relatedTaskId = $(this).find('.task-search').val();
            const relationType = $(this).find('.relationship-type').val();
            if (relatedTaskId && relationType) {
                taskData.relationships.push({
                    relatedTaskId: relatedTaskId,
                    type: relationType
                });
            }
        });

        try {
            let result;
            if (isNewTask) {
                result = await createTaskAPI(taskData);
                taskId = result.id; // Use the new task ID from the result if creating a new task
            } else {
                result = await updateTaskAPI(taskId, taskData);
            }

            // Handling comments
            const localComments = discussions[taskId] ? discussions[taskId].filter(c => c.isLocal) : [];
            
            if (localComments.length > 0) {
                const commentsToPost = localComments.map(comment => ({ content: comment.content }));
                
                try {
                    const response = await fetch(`/api/v1/projects/${projectName}/tasks/${taskId}/comments`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest'
                        },
                        body: JSON.stringify({ comments: commentsToPost })
                    });

                    if (!response.ok) {
                        throw new Error('Failed to post comments');
                    }

                    // Clear local comments after successful posting
                    discussions[taskId] = discussions[taskId].filter(c => !c.isLocal);
                } catch (error) {
                    console.error('Error posting comments:', error);
                    // Optionally handle the error (e.g., show a message to the user)
                }
            }

            try {
                const fetchCommentsResponse = await fetch(`/api/v1/projects/${projectName}/tasks/${taskId}/comments`, {
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                });                
                if (fetchCommentsResponse.ok) {
                    const fetchedComments = await fetchCommentsResponse.json();
                    discussions[taskId] = fetchedComments;
                } else {
                    throw new Error('Failed to fetch comments');
                }
            } catch (error) {
                console.error('Error fetching comments:', error);
            }

            // Populate the discussion with the newly fetched comments
            populateDiscussion(discussions[taskId]);
            $('body').css('overflow', 'hidden');
            $('#success-modal-message').text(isNewTask ? "Task created successfully." : "Task updated successfully.");
            $('#success-modal').modal('show');
            $('#success-modal').on('hidden.bs.modal', function () {
                $('body').css('overflow', 'auto');  // Restore the scrollbar
            });
            $('#task-modal').modal('hide');

            // After successful save, just refresh everything
            currentPage = 1; // Reset to page 1 to see changes
            await renderTasks($('#tasks-search-box').val());

        } catch (error) {
            console.error('Error during task save:', error);
            $('body').css('overflow', 'hidden');
            $('#failure-modal-message').text(`Error: ${error.message}`);
            $('#failure-modal').modal('show');
            $('#failure-modal').on('hidden.bs.modal', function () {
                $('body').css('overflow', 'auto');  // Restore the scrollbar
            });
        }
    });
    
    function initializeTaskRelationships(existingRelationships) {
        const $container = $('#task-relationships-container');
        $container.empty();
    
        if (existingRelationships.length === 0) {
            addRelationshipField();
        } else {
            existingRelationships.forEach(rel => addRelationshipField(rel.relatedTaskId, rel.type));
        }
    
        $('#add-relationship-btn').off('click').on('click', function() {
            addRelationshipField();
        });
    }

    function addRelationshipField(relatedTaskId = '', relationType = '', isReverse = false) {
        const $container = isReverse ? $('#task-reverse-relationships-container') : $('#task-relationships-container');
        const fieldId = 'task-search-' + Date.now();
        
        // HTML structure with the eye icon
        const fieldHtml = `
            <div class="relationship-field d-flex align-items-center mb-2">
                <select class="form-control relationship-type mr-2" style="flex: 0.5; height: 38px;">
                    <option value="" selected disabled>Select relationship</option>
                    <option value="parent" ${relationType === 'parent' ? 'selected' : ''}>Parent of</option>
                    <option value="child" ${relationType === 'child' ? 'selected' : ''}>Child of</option>
                    <option value="related" ${relationType === 'related' ? 'selected' : ''}>Related to</option>
                    <option value="blocks" ${relationType === 'blocks' ? 'selected' : ''}>Blocks</option>
                    <option value="blocked-by" ${relationType === 'blocked-by' ? 'selected' : ''}>Blocked by</option>
                </select>
                <div class="input-group mr-2" style="flex: 1; margin-bottom: 0px">
                    <input type="text" id="${fieldId}" class="form-control task-search" placeholder="Search task by ID" value="${relatedTaskId}" style="height: 38px;">
                    <div class="input-group-append">
                        <button class="btn btn-outline-secondary clear-search" type="button" title="Clear Task" style="height: 38px;">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                </div>
                <ul class="task-search-results list-group" style="display: none; position: absolute; z-index: 1000; width: 100%;"></ul>
                <button type="button" class="btn btn-outline-secondary open-task-btn" title="View Task" style="height: 38px; margin-left: 10px;" disabled>
                    <i class="fas fa-eye"></i>
                </button>
                <button type="button" class="btn btn-outline-danger remove-relationship" title="Remove Relationship" style="height: 38px; margin-left: 5px;">
                    X
                </button>
            </div>
        `;
    
        const $field = $(fieldHtml);
        $container.append($field);
    
        const $input = $field.find('.task-search');
        const $dropdown = $field.find('.task-search-results');
        const $clearBtn = $field.find('.clear-search');
        const $viewBtn = $field.find('.open-task-btn'); // View button
    
        // Add a visual indicator for reverse relationships
        if (isReverse) {
            $field.addClass('reverse-relationship');
            $field.find('.relationship-type').prop('disabled', true);
            $field.find('.task-search').prop('readonly', true);
            $field.find('.clear-search').prop('disabled', true);
            $field.find('.remove-relationship').prop('disabled', true);
        }
    
        // Clear button functionality
        $clearBtn.on('click', function(e) {
            e.preventDefault();
            $input.val('').removeData('selected-task').focus().trigger('input');
            $dropdown.hide();  // Hide the dropdown when the search is cleared
            $viewBtn.prop('disabled', true);  // Disable the view button when cleared
        });
    
        // On typing, update dropdown
        $input.on('input', async function() {
            if (isReverse) return;  // Don't search for reverse relationships (which are readonly)
        
            const searchTerm = $(this).val().toLowerCase();  // Make the search case-insensitive
            const currentTaskId = $('#task-id').val();
        
            // Hide the dropdown if the search input is cleared
            if (searchTerm === '') {
                $dropdown.hide();  // Hide the dropdown if there's no input
                return;
            }
        
            try {
                // Fetch tasks that match the search term
                const tasks = await fetchTasksFromAPI(null, null, searchTerm);
        
                // Filter the tasks based on the search term (ID or title)
                const matches = tasks
                    .filter(task => 
                        task.id.toString().includes(searchTerm) ||  // Match by task ID
                        task.title.toLowerCase().includes(searchTerm)  // Match by task title
                    )
                    .filter(task => task.id !== currentTaskId)  // Exclude the current task from the results
                    .slice(0, 5);  // Limit to 5 results
        
                // Update the dropdown with matching tasks
                if (matches.length > 0) {
                    $dropdown.html(matches.map(task => 
                        `<li><a href="#" data-task-id="${task.id}">${task.id} - ${task.title}</a></li>`
                    ).join('')).show();
                } else {
                    $dropdown.hide();  // Hide the dropdown if there are no matches
                }
            } catch (error) {
                console.error('Error fetching tasks:', error);
                $dropdown.hide();
            }
        });

    
        // Selecting a result from the dropdown
        $dropdown.on('click', 'a', function(e) {
            e.preventDefault();
            const taskId = $(this).data('task-id');
            $input.val(taskId);
            $input.data('selected-task', taskId);
            $dropdown.hide();
    
            // Enable the view button when a valid task ID is selected
            $viewBtn.prop('disabled', false);
            $viewBtn.data('task-id', taskId);  // Update the button with the new task ID
        });
    
        // Open task modal when view button is clicked
        $viewBtn.on('click', function() {
            const taskId = $(this).data('task-id');
            if (taskId) {
                openTaskModal(taskId);  // Open the related task in a new modal
            }
        });
    
        // Close dropdown when clicking outside
        $(document).on('click', function(e) {
            if (!$(e.target).closest('.relationship-field').length) {
                $dropdown.hide();
            }
        });
    
        // Set initial value if provided and enable the view button
        if (relatedTaskId) {
            $input.data('selected-task', relatedTaskId);
            $viewBtn.prop('disabled', false);  // Enable the button if ID is preset
            $viewBtn.data('task-id', relatedTaskId);  // Set the task ID on the view button directly
        }
    
        // Remove relationship field
        $field.find('.remove-relationship').on('click', function() {
            $field.remove();
        });
    }
    
     
    function addComment(taskId, commentText) {
        const newComment = {
            author: currentUser,
            content: commentText,
            timestamp: null,  // We'll set this to null for unsaved comments
            isLocal: true
        };
    
        if (!discussions[taskId]) {
            discussions[taskId] = [];
        }
    
        discussions[taskId].unshift(newComment);
        populateDiscussion(discussions[taskId]);
    
        $('#new-comment').val('');
    }
    
    function populateDiscussion(comments) {
        const discussionContainer = $('#discussion-container');
        discussionContainer.empty(); // Clear existing comments

        comments.forEach((comment, index) => {
            const timeDisplay = comment.isLocal
                ? 'Not Saved'
                : new Date(comment.timestamp).toLocaleString();

            // Always render markdown (both saved and unsaved)
            const highlightedContent = highlightMentions(comment.content);

            // Show edit button only for saved comments if author
            const isAuthor = comment.author === currentUser;
            const editButton = isAuthor && !comment.isLocal
                ? `<button class="btn btn-sm btn-link edit-comment-btn" data-comment-index="${index}" title="Edit comment">
                       <i class="fas fa-edit"></i>
                   </button>`
                : '';

            // Show delete button for unsaved comments only
            const deleteButton = comment.isLocal
                ? `<button class="btn btn-sm btn-link text-danger delete-unsaved-comment-btn" data-comment-index="${index}" title="Delete">
                       <i class="fas fa-trash"></i>
                   </button>`
                : '';

            // Show "edited" indicator if the comment was edited
            const editedIndicator = comment.is_edited
                ? `<span class="edited-indicator">(edited)</span>`
                : '';

            // Dynamically append each comment
            // Add 'own-comment' class if this is the current user's comment
            const ownCommentClass = isAuthor ? 'own-comment' : '';
            const commentHTML = `
                <div class="comment ${ownCommentClass}" data-comment-index="${index}">
                    <div class="comment-header">
                        <span class="comment-author">${comment.author}</span>
                        <span class="comment-timestamp">${timeDisplay}</span>
                        ${editedIndicator}
                        ${editButton}
                        ${deleteButton}
                    </div>
                    <div class="comment-body">
                        <div class="comment-content">${highlightedContent}</div>
                    </div>
                </div>
            `;

            discussionContainer.append(commentHTML);
        });

        // Attach edit button handlers
        discussionContainer.find('.edit-comment-btn').on('click', function() {
            const commentIndex = $(this).data('comment-index');
            const comment = comments[commentIndex];
            const $commentDiv = $(this).closest('.comment');
            const $commentBody = $commentDiv.find('.comment-body');

            // Replace comment content with contenteditable for editing
            const originalContent = comment.content;

            // For editing, we want to show the raw markdown with @mentions preserved
            // Just escape HTML to prevent injection, but keep the markdown syntax visible
            const htmlContent = $('<div>').text(originalContent).html();

            $commentBody.html(`
                <ul class="nav nav-tabs comment-tabs" id="edit-comment-tabs-${commentIndex}" role="tablist">
                    <li class="nav-item">
                        <a class="nav-link active" data-toggle="tab" href="#edit-write-panel-${commentIndex}" role="tab">Write</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link edit-preview-tab" data-comment-index="${commentIndex}" data-toggle="tab" href="#edit-preview-panel-${commentIndex}" role="tab">Preview</a>
                    </li>
                </ul>
                <div class="tab-content">
                    <div class="tab-pane fade show active" id="edit-write-panel-${commentIndex}" role="tabpanel">
                        <div class="formatting-toolbar" id="edit-comment-toolbar-${commentIndex}">
                            <button type="button" class="btn btn-sm btn-light format-btn" data-format="bold" title="Bold (Ctrl+B)">
                                <i class="fas fa-bold"></i>
                            </button>
                            <button type="button" class="btn btn-sm btn-light format-btn" data-format="italic" title="Italic (Ctrl+I)">
                                <i class="fas fa-italic"></i>
                            </button>
                            <button type="button" class="btn btn-sm btn-light format-btn" data-format="underline" title="Underline (Ctrl+U)">
                                <i class="fas fa-underline"></i>
                            </button>
                            <button type="button" class="btn btn-sm btn-light format-btn" data-format="strikethrough" title="Strikethrough">
                                <i class="fas fa-strikethrough"></i>
                            </button>
                            <span class="toolbar-separator"></span>
                            <button type="button" class="btn btn-sm btn-light format-btn" data-format="ul" title="Bullet List">
                                <i class="fas fa-list-ul"></i>
                            </button>
                            <button type="button" class="btn btn-sm btn-light format-btn" data-format="ol" title="Numbered List">
                                <i class="fas fa-list-ol"></i>
                            </button>
                            <span class="toolbar-separator"></span>
                            <button type="button" class="btn btn-sm btn-light format-btn" data-format="code" title="Inline Code">
                                <i class="fas fa-code"></i>
                            </button>
                            <button type="button" class="btn btn-sm btn-light format-btn" data-format="link" title="Insert Link (Ctrl+K)">
                                <i class="fas fa-link"></i>
                            </button>
                        </div>
                        <div contenteditable="true" class="comment-text-input edit-comment-input" id="edit-comment-input-${commentIndex}" data-placeholder="Edit comment...">${htmlContent}</div>
                    </div>
                    <div class="tab-pane fade" id="edit-preview-panel-${commentIndex}" role="tabpanel">
                        <div class="comment-preview-area" id="edit-comment-preview-${commentIndex}">
                            <p class="text-muted">Nothing to preview</p>
                        </div>
                    </div>
                </div>
                <div style="margin-top: 10px;">
                    <button class="btn btn-sm btn-primary save-comment-btn">Save</button>
                    <button class="btn btn-sm btn-secondary cancel-comment-btn">Cancel</button>
                </div>
            `);

            // Grey out the Save changes button since we're in edit mode
            updateSaveButtonState();

            // Initialize edit mode mention autocomplete AFTER DOM is ready
            setTimeout(() => {
                initEditMentionMode(commentIndex);
            }, 0);

            // Save button handler
            $commentBody.find('.save-comment-btn').on('click', async function() {
                // Get full content from contenteditable (extract text)
                const $editInput = $(`#edit-comment-input-${commentIndex}`);
                const newContent = extractTextFromContenteditable($editInput[0]);

                if (!newContent) {
                    alert('Comment cannot be empty');
                    return;
                }

                if (newContent === originalContent) {
                    // No changes, just restore view
                    $commentBody.html(`<p class="comment-content">${highlightMentions(newContent)}</p>`);
                    // Re-enable Save changes button since we're no longer in edit mode
                    updateSaveButtonState();
                    return;
                }

                try {
                    const taskId = $('#task-id').val();
                    const response = await fetch(`/api/v1/projects/${projectName}/tasks/${taskId}/comments`, {
                        method: 'PUT',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest'
                        },
                        body: JSON.stringify({
                            comment_timestamp: comment.timestamp,  // Use timestamp as unique identifier instead of index
                            content: newContent,
                            original_content: originalContent  // Send original to detect new mentions
                        })
                    });

                    if (!response.ok) {
                        const errorData = await safeJsonParse(response);
                        $('#failure-modal-message').text(errorData.detail || 'Failed to update comment');
                        $('#failure-modal').modal('show');
                        return;
                    }

                    // Update the comment in the discussions array
                    comment.content = newContent;
                    comment.is_edited = true;
                    comment.edited_at = new Date().toISOString();

                    // Refresh the discussion display
                    populateDiscussion(comments);

                    // Re-enable Save changes button since we're no longer in edit mode
                    updateSaveButtonState();
                } catch (error) {
                    console.error('Error updating comment:', error);
                    $('#failure-modal-message').text(`Failed to update comment: ${error.message}`);
                    $('#failure-modal').modal('show');
                }
            });

            // Cancel button handler
            $commentBody.find('.cancel-comment-btn').on('click', function() {
                $commentBody.html(`<p class="comment-content">${highlightMentions(originalContent)}</p>`);
                // Re-enable Save changes button since we're no longer in edit mode
                updateSaveButtonState();
            });
        });

        // Attach delete button handlers for unsaved comments
        discussionContainer.find('.delete-unsaved-comment-btn').on('click', function() {
            const commentIndex = $(this).data('comment-index');
            // Remove from comments array
            comments.splice(commentIndex, 1);
            // Refresh discussion display
            populateDiscussion(comments);
        });

    }

    // Configure marked.js
    marked.setOptions({
        breaks: true,
        gfm: true,
        pedantic: false,
        smartLists: true,
        smartypants: false
    });

    // In marked v15+, HTML escaping is on by default
    // We use marked.use() to ensure it's enabled
    marked.use({
        mangle: false,
        headerIds: false
    });

    // Helper to escape HTML in code blocks
    function escapeCode(str) {
        // Ensure we have a string
        if (str == null || str === undefined) {
            return '';
        }
        if (typeof str !== 'string') {
            str = String(str);
        }
        return str.replace(/[&<>"']/g, function(m) {
            return {
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#039;'
            }[m];
        });
    }

    // Use marked hooks instead of renderer for better compatibility
    marked.use({
        renderer: {
            code(token) {
                // In marked v15+, token is an object with text and lang properties
                let codeText = '';
                let lang = '';

                if (typeof token === 'object' && token !== null) {
                    // Try all possible property names
                    codeText = token.text || token.code || token.raw || '';
                    lang = token.lang || token.language || token.info || '';
                } else if (typeof token === 'string') {
                    // Fallback for older versions
                    codeText = token;
                    lang = arguments[1] || '';
                }

                // Try to apply syntax highlighting WITH the raw code (hljs handles escaping)
                if (typeof hljs !== 'undefined' && lang && hljs.getLanguage(lang)) {
                    try {
                        // hljs.highlight returns already-escaped HTML
                        const highlighted = hljs.highlight(codeText, { language: lang, ignoreIllegals: true }).value;
                        return `<pre><code class="hljs language-${lang}">${highlighted}</code></pre>`;
                    } catch (e) {
                        console.error('Highlight error:', e);
                    }
                }

                // Fallback: escape and return in pre/code tags (for no language or highlight failure)
                const escapedCode = escapeCode(codeText);
                return `<pre><code>${escapedCode}</code></pre>`;
            }
        }
    });

    // Helper function to render markdown and highlight @mentions
    function renderCommentContent(text) {
        if (!text) return '';

        // Step 0: Escape HTML outside of code blocks to prevent raw HTML injection
        // Protect code blocks (triple backticks) and inline code (single backticks)
        const protectedContent = [];
        let protectedCounter = 0;

        // Protect triple backtick code blocks
        text = text.replace(/```[\s\S]*?```/g, (match) => {
            const placeholder = `XPROTECTEDX${protectedCounter}XPROTECTEDX`;
            protectedContent[protectedCounter] = match;
            protectedCounter++;
            return placeholder;
        });

        // Protect inline code (single backticks)
        text = text.replace(/`[^`\n]+?`/g, (match) => {
            const placeholder = `XPROTECTEDX${protectedCounter}XPROTECTEDX`;
            protectedContent[protectedCounter] = match;
            protectedCounter++;
            return placeholder;
        });

        // Now escape HTML entities in the remaining text (outside code blocks and inline code)
        // Preserve markdown autolinks: <https://...> or <http://...>
        text = text.replace(/<(?!https?:\/\/)/g, '&lt;');
        text = text.replace(/>/g, '&gt;');

        // Restore protected content
        protectedContent.forEach((content, index) => {
            text = text.replace(`XPROTECTEDX${index}XPROTECTEDX`, content);
        });

        // Step 1: Temporarily replace @mentions with placeholders to protect them from markdown parser
        const mentionMap = {};
        let mentionCounter = 0;
        const textWithPlaceholders = text.replace(/@([\w.+-]+@[\w.-]+\.[\w]+|[\w]+)/g, (match, username) => {
            const placeholder = `XMENTIONX${mentionCounter}XMENTIONX`;
            mentionMap[placeholder] = username;
            mentionCounter++;
            return placeholder;
        });

        // Step 2: Parse markdown to HTML using marked.js (with syntax highlighting)
        let html = marked.parse(textWithPlaceholders);

        // Step 3: Replace placeholders with styled mention spans (use global replace)
        Object.keys(mentionMap).forEach(placeholder => {
            const username = mentionMap[placeholder];
            // Use split/join for reliable replacement
            html = html.split(placeholder).join(`<span class="mention">@${username}</span>`);
        });

        return html;
    }

    // Keep the old function for backward compatibility (now uses renderCommentContent)
    function highlightMentions(text) {
        return renderCommentContent(text);
    }

    // Helper function to extract mentions from text
    function extract_mentions_from_text(text) {
        const mentions = text.match(/@([\w.+-]+@[\w.-]+\.[\w]+|[\w]+)/g);
        return mentions ? mentions.map(m => m.substring(1)) : [];
    }

    // Initialize mention mode for editing comments (contenteditable version)
    function initEditMentionMode(commentIndex) {
        let editMentionDropdown = null;

        // Handle @mention autocomplete in edit contenteditable
        $(`#edit-comment-input-${commentIndex}`).on('input', function(e) {
            const input = $(this)[0];
            const selection = window.getSelection();

            if (!selection.rangeCount) return;

            const range = selection.getRangeAt(0);
            const textNode = range.startContainer;

            if (textNode.nodeType !== Node.TEXT_NODE) {
                if (editMentionDropdown) {
                    editMentionDropdown.remove();
                    editMentionDropdown = null;
                }
                return;
            }

            const textContent = textNode.textContent;
            const cursorPos = range.startOffset;
            const textBeforeCursor = textContent.substring(0, cursorPos);
            const lastAtIndex = textBeforeCursor.lastIndexOf('@');

            if (lastAtIndex !== -1) {
                const textAfterAt = textBeforeCursor.substring(lastAtIndex + 1);

                if (!textAfterAt.includes(' ') && textAfterAt.length >= 1) {
                    const searchTerm = textAfterAt.toLowerCase();

                    const filteredMembers = projectMembers.filter(member =>
                        member.toLowerCase().includes(searchTerm)
                    );

                if (filteredMembers.length === 0) {
                    if (editMentionDropdown) {
                        editMentionDropdown.remove();
                        editMentionDropdown = null;
                    }
                    return;
                }

                if (!editMentionDropdown) {
                    editMentionDropdown = $('<div class="mention-dropdown"></div>');
                    $('#task-modal .modal-body').append(editMentionDropdown);
                }

                // Position dropdown at cursor location
                const selection = window.getSelection();

                if (selection.rangeCount > 0) {
                    const range = selection.getRangeAt(0);
                    const rect = range.getBoundingClientRect();

                    // Get modal body for position calculation
                    const modalBody = $('#task-modal .modal-body')[0];
                    const modalBodyRect = modalBody.getBoundingClientRect();

                    // Calculate position relative to modal body
                    const top = rect.bottom - modalBodyRect.top + modalBody.scrollTop;
                    const left = rect.left - modalBodyRect.left;

                    editMentionDropdown.css({
                        position: 'absolute',
                        top: top + 'px',
                        left: left + 'px',
                        minWidth: '200px',
                        maxWidth: '400px'
                    });
                } else {
                    // Fallback
                    const $editInput = $(`#edit-comment-input-${commentIndex}`);
                    const inputOffset = $editInput.offset();
                    const modalBodyOffset = $('#task-modal .modal-body').offset();

                    editMentionDropdown.css({
                        position: 'absolute',
                        top: (inputOffset.top - modalBodyOffset.top + 20) + 'px',
                        left: (inputOffset.left - modalBodyOffset.left) + 'px',
                        minWidth: '200px',
                        maxWidth: '400px'
                    });
                }

                // Populate dropdown
                editMentionDropdown.empty();
                filteredMembers.slice(0, 5).forEach(member => {
                    const item = $(`<div class="mention-dropdown-item">${member}</div>`);
                    item.on('click', function() {
                        // Replace @search with styled mention span
                        const beforeAt = textContent.substring(0, lastAtIndex);
                        const afterCursor = textContent.substring(cursorPos);

                        // Create mention span
                        const mentionSpan = document.createElement('span');
                        mentionSpan.className = 'mention';
                        mentionSpan.contentEditable = 'false';
                        mentionSpan.setAttribute('data-username', member);
                        mentionSpan.textContent = '@' + member;

                        // Create text nodes
                        const beforeNode = document.createTextNode(beforeAt);
                        const afterNode = document.createTextNode(' ' + afterCursor);

                        // Replace content
                        const selection = window.getSelection();
                        const range = selection.getRangeAt(0);

                        // Clear the text node content
                        textNode.textContent = '';

                        // Insert nodes
                        const parent = textNode.parentNode || input;
                        if (beforeAt) parent.insertBefore(beforeNode, textNode);
                        parent.insertBefore(mentionSpan, textNode);
                        parent.insertBefore(afterNode, textNode);
                        if (textNode.parentNode) textNode.parentNode.removeChild(textNode);

                        // Set cursor after mention
                        const newRange = document.createRange();
                        newRange.setStart(afterNode, 1);
                        newRange.collapse(true);
                        selection.removeAllRanges();
                        selection.addRange(newRange);

                        input.focus();

                        editMentionDropdown.remove();
                        editMentionDropdown = null;
                    });
                    editMentionDropdown.append(item);
                });
            } else {
                if (editMentionDropdown) {
                    editMentionDropdown.remove();
                    editMentionDropdown = null;
                }
            }
            } else {
                // No @ found or not in mention mode
                if (editMentionDropdown) {
                    editMentionDropdown.remove();
                    editMentionDropdown = null;
                }
            }
        });

        // Close dropdown on Escape
        $(`#edit-comment-input-${commentIndex}`).on('keydown', function(e) {
            if (e.key === 'Escape' && editMentionDropdown) {
                editMentionDropdown.remove();
                editMentionDropdown = null;
            }
        });
    }

    // Add a mention tag in edit mode
    function addEditMentionTag(commentIndex, username, tagsContainer) {
        const currentTags = window[`editMentionTags_${commentIndex}`] || [];

        // Allow duplicate tags, but track them
        currentTags.push(username);
        window[`editMentionTags_${commentIndex}`] = currentTags;

        const tag = $(`
            <span class="mention-tag" data-username="${username}">
                @${username}
                <span class="mention-tag-remove" title="Remove">×</span>
            </span>
        `);

        tag.find('.mention-tag-remove').on('click', function() {
            const tags = window[`editMentionTags_${commentIndex}`] || [];
            // Remove only the first occurrence of this username
            const index = tags.indexOf(username);
            if (index > -1) {
                tags.splice(index, 1);
            }
            window[`editMentionTags_${commentIndex}`] = tags;
            tag.remove();
        });

        tagsContainer.append(tag);
    }

    async function deleteTask(taskId) {
        try {
            const response = await fetch(`/api/v1/projects/${projectName}/tasks/${taskId}`, {
                method: 'DELETE',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });            
    
            if (!response.ok) {
                throw new Error('Failed to delete task');
            }
    
            $('#deleteTaskModal').modal('hide');
            $('#success-modal-message').text('Task deleted successfully.');
            $('#success-modal').modal('show');
            
            // Refresh the task list
            const tasks = await renderTasks($('#tasks-search-box').val());
            renderPagination(tasks);
            
        } catch (error) {
            $('#deleteTaskModal').modal('hide');
            $('#failure-modal-message').text(`Failed to delete task: ${error.message}`);
            $('#failure-modal').modal('show');
        }
    }

    async function renderTasks(filter = '') {
        try {
            $('#tasks-wrapper').html('<div class="text-center w-100 my-5">Loading...</div>');
            
            if (!$('#filter-sprint').val()) {  // If sprint dropdown isn't populated yet
                return [];  // Exit early
            }

            const tasks = await fetchTasksFromAPI();

            // Gather all filter values
            const selectedSprint = $('#filter-sprint').val();
            const selectedTypes = $('#filter-task-type').val() || [];
            const selectedAssignee = $('#filter-assigned-to-container .user-search').val().trim().toLowerCase();
            const selectedStatuses = $('#filter-status').val() || [];
            const selectedPriorities = $('#filter-priority').val() || [];
            const selectedTags = $('#filter-tags').val() || [];

            const filteredTasks = tasks.filter(taskDetails => {
                const matchesSprint = selectedSprint === '' || 
                    (selectedSprint === 'backlog' && !taskDetails.sprintId) || 
                    (selectedSprint !== 'backlog' && taskDetails.sprintId === selectedSprint);

                const matchesAssigned = selectedAssignee === '' || 
                    (taskDetails.assignedTo && taskDetails.assignedTo.toLowerCase() === selectedAssignee);

                const matchesType = selectedTypes.length === 0 || selectedTypes.includes(taskDetails.type);
                const matchesStatus = selectedStatuses.length === 0 || selectedStatuses.includes(taskDetails.status);
                const matchesPriority = selectedPriorities.length === 0 || selectedPriorities.includes(taskDetails.priority);
                const matchesTags = selectedTags.length === 0 || 
                    taskDetails.tags.some(tag => selectedTags.includes(tag)) ||
                    (selectedTags.includes('unassigned') && !taskDetails.assignedTo);

                const matchesSearch = taskDetails.title.toLowerCase().includes(filter.toLowerCase()) ||
                    taskDetails.tags.some(tag => tag.toLowerCase().includes(filter.toLowerCase())) ||
                    taskDetails.id.toString().includes(filter) ||
                    (!taskDetails.assignedTo && 'unassigned'.includes(filter.toLowerCase()));

                return matchesSprint && matchesType && matchesAssigned && matchesStatus && 
                    matchesPriority && matchesTags && matchesSearch;
            });

            // *** FIX: Validate currentPage against actual filtered results ***
            const totalPages = Math.ceil(filteredTasks.length / itemsPerPage);
            if (currentPage > totalPages && totalPages > 0) {
                currentPage = totalPages; // Adjust to last valid page
            } else if (totalPages === 0) {
                currentPage = 1; // Reset to page 1 if no results
            }

            const start = (currentPage - 1) * itemsPerPage;
            const end = start + itemsPerPage;
            const paginatedTasks = filteredTasks.slice(start, end);

            $('#tasks-wrapper').empty();

            if (paginatedTasks.length === 0) {
                if (filteredTasks.length === 0) {
                    $('#tasks-wrapper').append('<div class="col-12"><p>No tasks found matching the current filters.</p></div>');
                } else {
                    // This handles the case where we're on a page that doesn't exist
                    $('#tasks-wrapper').append('<div class="col-12"><p>No tasks on this page. Adjusting...</p></div>');
                    // The page adjustment above should handle this, but just in case
                    setTimeout(() => {
                        renderTasks(filter);
                    }, 100);
                    return filteredTasks;
                }
            } else {
                paginatedTasks.forEach(taskDetails => {
                    const sprintName = taskDetails.sprintId || 'Backlog';
                    const tags = taskDetails.tags.slice();
                    if (!taskDetails.assignedTo) {
                        tags.push('Unassigned');
                    }

                    const taskTitleWithId = `#${taskDetails.id} - ${taskDetails.title}`;

                    if (currentView === 'grid') {
                        $('#tasks-wrapper').append(`
                            <div class="col-md-4 mb-3">
                                <div class="card h-100 d-flex flex-column task-card">
                                    <div class="card-body d-flex flex-column task-card-body">
                                        <div class="card-text">
                                            <div class="task-title-container">
                                                <i class="fas fa-tasks task-icon"></i>
                                                <span class="card-title task-title small-title">${taskTitleWithId}</span>
                                            </div>
                                            <div class="task-description-container">
                                                <i class="fas fa-info-circle task-icon"></i>
                                                <span class="task-description">${taskDetails.description}</span>
                                            </div>
                                            <div class="mt-2">
                                                <span class="badge badge-${getTypeBadgeClass(taskDetails.type)}">${taskDetails.type}</span>
                                                <span class="badge badge-${getPriorityBadgeClass(taskDetails.priority)}">${taskDetails.priority}</span>
                                                ${taskDetails.is_overdue ? '<span class="badge badge-danger"><i class="fas fa-exclamation-triangle"></i> Overdue</span>' : ''}
                                            </div>
                                            <div class="mt-2">
                                                ${tags.map(tag => `<span class="badge badge-info mr-1">${tag}</span>`).join('')}
                                            </div>
                                            <div class="mt-2">
                                                <span class="badge badge-secondary">Sprint: ${sprintName}</span>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="task-footer">
                                        <a href="#" class="btn btn-link text-primary p-0 edit-task task-action" data-task-id="${taskDetails.id}">
                                            <i class="fas fa-edit"></i>
                                        </a>
                                        <a href="#" class="btn btn-link text-danger p-0 delete-task task-action" data-task-id="${taskDetails.id}">
                                            <i class="fas fa-trash-alt"></i>
                                        </a>
                                    </div>
                                </div>
                            </div>
                        `);
                    } else {
                        $('#tasks-wrapper').append(`
                            <div class="col-12">
                                <div class="card task-list-item">
                                    <div class="card-body">
                                        <div class="d-flex justify-content-between">
                                            <div>
                                                <span class="card-title task-title small-title">${taskTitleWithId}</span>
                                                <p class="card-text">${taskDetails.description}</p>
                                                <span class="badge badge-${getTypeBadgeClass(taskDetails.type)}">${taskDetails.type}</span>
                                                <span class="badge badge-${getPriorityBadgeClass(taskDetails.priority)}">${taskDetails.priority}</span>
                                                ${taskDetails.is_overdue ? '<span class="badge badge-danger"><i class="fas fa-exclamation-triangle"></i> Overdue</span>' : ''}
                                                ${tags.map(tag => `<span class="badge badge-info mr-1">${tag}</span>`).join('')}
                                            </div>
                                            <div class="task-actions">
                                                <a href="#" class="btn btn-link text-primary edit-task" data-task-id="${taskDetails.id}">
                                                    <i class="fas fa-edit"></i>
                                                </a>
                                                <a href="#" class="btn btn-link text-danger delete-task" data-task-id="${taskDetails.id}">
                                                    <i class="fas fa-trash-alt"></i>
                                                </a>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        `);
                    }
                });
            }

            // Add hover effects
            $('.task-card, .task-list-item').hover(
                function() { $(this).addClass('hover-effect'); },
                function() { $(this).removeClass('hover-effect'); }
            );

            // Add click events for edit and delete buttons
            $('.edit-task').off('click').on('click', function(e) {
                e.preventDefault();
                const taskId = $(this).data('task-id').toString();
                
                const currentUrl = window.location.pathname;
                const taskUrlPattern = new RegExp(`/tasks/${taskId}$`);
            
                if (!taskUrlPattern.test(currentUrl)) {
                    const newUrl = `${currentUrl}/${taskId}`;
                    window.history.pushState({ taskId }, '', newUrl);
                }
                
                openTaskModal(taskId);
            });

            $('.delete-task').off('click').on('click', function(e) {
                e.preventDefault();
                taskToDelete = $(this).data('task-id');
                $('#deleteTaskId').text(taskToDelete);
                $('#deleteTaskModal').modal('show');
            });

            // *** FIX: Pass filteredTasks to renderPagination, not all tasks ***
            renderPagination(filteredTasks);

            return filteredTasks; // Return filtered tasks, not all tasks
        } catch (error) {
            console.error('Error rendering tasks:', error);
            $('#failure-modal-message').text(`Error: ${error.message}`);
            $('#failure-modal').modal('show');
            return [];
        }
    }
    
    function renderRelationships(relationships) {
        return relationships.map(rel => {
            const relatedTask = findTaskById(rel.relatedTaskId);
            if (!relatedTask) return '';
            return `<span class="relationship-badge">
                ${rel.type}: <a href="#" class="related-task-link" data-task-id="${relatedTask.id}">#${relatedTask.id}</a>
            </span>`;
        }).join('');
    }

    function renderPagination(filteredTasks = []) {
        $('#pagination').empty();
        const totalItems = filteredTasks.length;
        const totalPages = Math.ceil(totalItems / itemsPerPage);

        // Don't show pagination if there's only one page or no items
        if (totalPages <= 1) {
            return;
        }

        // Ensure currentPage is valid
        if (currentPage > totalPages) {
            currentPage = totalPages;
        }
        if (currentPage < 1) {
            currentPage = 1;
        }

        for (let i = 1; i <= totalPages; i++) {
            $('#pagination').append(`
                <li class="page-item ${i === currentPage ? 'active' : ''}">
                    <a class="page-link" href="#" data-page="${i}">${i}</a>
                </li>
            `);
        }

        $('.page-link').off('click').on('click', function(e) {
            e.preventDefault();
            const newPage = parseInt($(this).data('page'));
            if (newPage !== currentPage) {
                currentPage = newPage;
                renderTasks($('#tasks-search-box').val());
            }
        });
    }

    function getTypeBadgeClass(type) {
        const classes = {
            bug: 'danger',
            feature: 'primary',
            improvement: 'success'
        };
        return classes[type] || 'secondary';
    }

    function getPriorityBadgeClass(priority) {
        const classes = {
            high: 'danger',
            medium: 'warning',
            low: 'info'
        };
        return classes[priority] || 'secondary';
    }

 
    // Event Handlers
    $('#new-task-btn').off('click').on('click', function() {
        console.log('New task button clicked');
        openTaskModal();
    });

    $('#create-sprint').click(async function() {
        // Build the sprint data to send
        const newSprint = {
            start_date: $('#sprint-start-date').val(),
            end_date: $('#sprint-end-date').val(),
            goal: $('#sprint-goal').val(),
        };
    
        try {
            // Send the data to the API
            const response = await fetch(`/api/v1/projects/${projectName}/sprints/create`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify(newSprint)
            });            
    
            const data = await safeJsonParse(response);
    
            if (!response.ok) {
                const detail = data.detail;
                const msg = typeof detail === 'string' ? detail
                    : Array.isArray(detail) ? detail.map(e => e.msg || JSON.stringify(e)).join('; ')
                    : detail ? JSON.stringify(detail) : 'Failed to create sprint';
                throw new Error(msg);
            }
    
            $('#sprint-modal').modal('hide');
    
            // Display success modal message, dynamically adding the Sprint ID
            $('#success-modal-message').text(`Sprint "${data.sprint.id}" was created successfully.`);
            $('#success-modal').modal('show');
    
            // Fetch updated sprints from the server and repopulate dropdowns
            await populateDropdowns();
            
        } catch (error) {
            // Display error message in the modal
            $('#failure-modal-message').text(`Error: ${error.message}`);
            $('#failure-modal').modal('show');
        }
    });

    $('#edit-sprint-icon').on('click', async function() {
        const sprintId = $(this).data('sprint-id');
        if (!sprintId) return;  // Do nothing if no sprint is selected
    
        try {
            const response = await fetch(`/api/v1/projects/${projectName}/sprints/${sprintId}`, {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });            
            if (!response.ok) {
                throw new Error('Failed to fetch sprint details');
            }
            const sprintData = await safeJsonParse(response);
    
            // Format the date to YYYY-MM-DD for input fields
            const formattedStartDate = new Date(sprintData.start_date).toISOString().split('T')[0];
            const formattedEndDate = new Date(sprintData.end_date).toISOString().split('T')[0];
    
            // Populate modal form fields with sprint data
            $('#sprint-start-date').val(formattedStartDate);
            $('#sprint-end-date').val(formattedEndDate);
            $('#sprint-goal').val(sprintData.goal);
    
            // Update modal title and button text for edit mode
            $('#sprint-modal .modal-title').text('Edit Sprint');
            $('#create-sprint').text('Save Changes').attr('id', 'save-sprint');  // Change button ID and text
    
            // Add a new event listener for saving changes (remove previous create event if any)
            $('#save-sprint').off('click').on('click', async function() {
                await saveSprintChanges(sprintId);  // Call function to save sprint changes
            });
    
            // Show the modal with the populated data
            $('#sprint-modal').modal('show');
        } catch (error) {
            console.error('Error fetching sprint details:', error);
            $('#failure-modal-message').text(`Error: ${error.message}`);
            $('#failure-modal').modal('show');
        }
    });
    
    
    $('#listViewBtn, #gridViewBtn').on('click', function() {
        currentPage = 1;
        currentView = $(this).attr('id') === 'listViewBtn' ? 'list' : 'grid';
        $(this).addClass('active').siblings().removeClass('active');
        renderTasks($('#tasks-search-box').val());
        renderPagination();
    });

    $('#itemsPerPageSelect').on('change', function() {
        itemsPerPage = parseInt($(this).val());
        currentPage = 1;
        renderTasks($('#tasks-search-box').val());
        renderPagination();
    });

    $(document).on('click', '.related-task-link', function(e) {
        e.preventDefault();
        const taskId = $(this).data('task-id');
        openTaskModal(taskId);
    });

    $(document).on('input', '#user-search', function() {
        const searchTerm = $(this).val().toLowerCase();
        const $results = $('#user-search-results');
        $results.empty();
    
        if (searchTerm.length > 0) {
            const matchingUsers = users.filter(email => email.toLowerCase().includes(searchTerm));
            if (matchingUsers.length > 0) {
                matchingUsers.forEach(email => {
                    $results.append(`<li class="list-group-item user-search-result">${email}</li>`);
                });
                $results.show();
            } else {
                $results.hide();
            }
        } else {
            $results.hide();
        }
    });

    createUserSearchInput('filter-assigned-to-container');
    console.log('Assigned to container content:', $('#filter-assigned-to-container').html());


    // Set up event listeners for user search
    $(document).off('input', '.user-search').on('input', '.user-search', function() {
        performUserSearch($(this));
    });
    
        
    
    
    $(document).on('click', function(e) {
        if (!$(e.target).closest('.user-search-container').length) {
            $('.user-search-results').hide();
        }
    });



    // Initialize Select2 for all dropdowns with the 'select2' class
    $('.select2').select2({
        theme: 'bootstrap4',
        width: '100%'
    }).on('change', function() {
        currentPage = 1;
        renderTasks($('#tasks-search-box').val());
        renderPagination();
    });

    // Task tags initialization
    $('#task-tags').select2({
        tags: false,
        tokenSeparators: [',', ' '],
        placeholder: "Select or type tags",
        theme: 'bootstrap4'
    });

    // Function to check if there's unsaved comment content
    function hasUnsavedComment() {
        // Only check if discussion section is visible (i.e., we're editing an existing task)
        if ($('.discussion-section').is(':visible')) {
            const commentText = getFullCommentText();
            const hasNewComment = commentText !== '';

            // Check if any comment is in edit mode
            const hasEditMode = $('.edit-comment-input').length > 0;

            return hasNewComment || hasEditMode;
        }

        // If discussion section is not visible, no unsaved comments
        return false;
    }

    // Function to update Save changes button state
    function updateSaveButtonState() {
        const $saveBtn = $('#save-task');
        if (hasUnsavedComment()) {
            $saveBtn.prop('disabled', true);
            $saveBtn.attr('title', 'Please post or clear your comment before saving task changes');
            $saveBtn.css('cursor', 'not-allowed');
        } else {
            $saveBtn.prop('disabled', false);
            $saveBtn.attr('title', '');
            $saveBtn.css('cursor', 'pointer');
        }
    }

    // Monitor comment input for changes
    $(document).on('input', '#new-comment', function() {
        updateSaveButtonState();

        // Show/hide clear button based on content
        const commentText = getFullCommentText();
        if (commentText) {
            $('#clear-comment-btn').show();
        } else {
            $('#clear-comment-btn').hide();
        }
    });

    // Handle Preview tab click - render markdown for new comment
    $(document).on('click', '#preview-tab', function(e) {
        const commentText = getFullCommentText();
        const $previewArea = $('#new-comment-preview');

        if (commentText.trim()) {
            // Render markdown to HTML
            const renderedHTML = renderCommentContent(commentText);
            $previewArea.html(`<div class="comment-content">${renderedHTML}</div>`);
        } else {
            $previewArea.html('<p class="text-muted">Nothing to preview</p>');
        }
    });

    // Handle Preview tab click - render markdown for edit comment
    $(document).on('click', '.edit-preview-tab', function(e) {
        const commentIndex = $(this).data('comment-index');
        const $editInput = $(`#edit-comment-input-${commentIndex}`);
        const commentText = extractTextFromContenteditable($editInput[0]);
        const $previewArea = $(`#edit-comment-preview-${commentIndex}`);

        if (commentText.trim()) {
            // Render markdown to HTML
            const renderedHTML = renderCommentContent(commentText);
            $previewArea.html(`<div class="comment-content">${renderedHTML}</div>`);
        } else {
            $previewArea.html('<p class="text-muted">Nothing to preview</p>');
        }
    });

    // Ensure this is within the $(function() { ... }) block
    $('#add-comment-btn').off('click').on('click', function() {
        const taskId = $('#task-id').val();
        const commentText = getFullCommentText();
        if (commentText) {
            addComment(taskId, commentText);
            // Clear contenteditable after posting
            $('#new-comment').html('');
            $('#clear-comment-btn').hide();
            // Re-enable Save button after posting comment
            updateSaveButtonState();
        }
    });

    // Clear comment button handler
    $('#clear-comment-btn').off('click').on('click', function() {
        $('#new-comment').html('');
        $('#clear-comment-btn').hide();
        updateSaveButtonState();
        $('#new-comment').focus();
    });

    // @mention inline functionality
    let mentionDropdown = null;
    let projectMembers = [];

    // Fetch project members for autocomplete
    async function fetchProjectMembers() {
        try {
            const response = await fetch(`/api/v1/projects/${projectName}/members`, {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });
            if (response.ok) {
                const data = await safeJsonParse(response);
                projectMembers = Array.isArray(data) ? data : [];
                console.log('Project members loaded:', projectMembers);
            }
        } catch (error) {
            console.error('Error fetching project members:', error);
        }
    }

    // Initialize project members
    fetchProjectMembers();

    // ============ MARKDOWN FORMATTING TOOLBAR ============

    // Apply markdown formatting to selected text (simple text insertion)
    function applyMarkdownFormat(format, inputId = 'new-comment') {
        const input = document.getElementById(inputId);
        const selection = window.getSelection();

        if (!selection.rangeCount) return;

        const range = selection.getRangeAt(0);

        // Extract text from selection, preserving line breaks
        let selectedText = '';
        const container = range.cloneContents();
        const tempDiv = document.createElement('div');
        tempDiv.appendChild(container);

        // Walk through nodes and extract text with line breaks
        Array.from(tempDiv.childNodes).forEach((node, index) => {
            if (node.nodeType === Node.TEXT_NODE) {
                selectedText += node.textContent;
            } else if (node.nodeType === Node.ELEMENT_NODE) {
                if (node.nodeName === 'BR') {
                    selectedText += '\n';
                } else {
                    selectedText += node.textContent;
                }
            }
            // Add newline between block elements (except the last one)
            if (index < tempDiv.childNodes.length - 1 && node.nodeType === Node.ELEMENT_NODE) {
                const isBlockElement = ['DIV', 'P', 'LI', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6'].includes(node.nodeName);
                if (isBlockElement) {
                    selectedText += '\n';
                }
            }
        });

        let markdownText = '';
        let defaultText = '';

        switch(format) {
            case 'bold':
                defaultText = 'bold text';
                markdownText = `**${selectedText || defaultText}**`;
                break;
            case 'italic':
                defaultText = 'italic text';
                markdownText = `*${selectedText || defaultText}*`;
                break;
            case 'underline':
                defaultText = 'underlined text';
                markdownText = `<u>${selectedText || defaultText}</u>`;
                break;
            case 'strikethrough':
                defaultText = 'strikethrough text';
                markdownText = `~~${selectedText || defaultText}~~`;
                break;
            case 'code':
                defaultText = 'code';
                if (selectedText && selectedText.includes('\n')) {
                    // Multi-line code - use triple backticks
                    markdownText = `\n\`\`\`\n${selectedText}\n\`\`\`\n`;
                } else {
                    // Single line code - use single backticks
                    markdownText = `\`${selectedText || defaultText}\``;
                }
                break;
            case 'ul':
                defaultText = 'list item';
                if (selectedText && selectedText.includes('\n')) {
                    // Multi-line selection - convert each line to list item
                    const lines = selectedText.split('\n').filter(line => line.trim());
                    markdownText = '\n' + lines.map(line => `- ${line.trim()}`).join('\n') + '\n';
                } else {
                    markdownText = `\n- ${selectedText || defaultText}`;
                }
                break;
            case 'ol':
                defaultText = 'list item';
                if (selectedText && selectedText.includes('\n')) {
                    // Multi-line selection - convert each line to numbered list item
                    const lines = selectedText.split('\n').filter(line => line.trim());
                    markdownText = '\n' + lines.map((line, idx) => `${idx + 1}. ${line.trim()}`).join('\n') + '\n';
                } else {
                    markdownText = `\n1. ${selectedText || defaultText}`;
                }
                break;
            case 'link':
                const url = $('#link-url-input').val() || 'https://';
                if (!url || url === 'https://') {
                    showLinkDialog(input, range, selectedText);
                    return;
                }
                defaultText = 'link text';
                markdownText = `[${selectedText || defaultText}](${url})`;
                break;
        }

        if (markdownText) {
            // Insert as plain text
            const textNode = document.createTextNode(markdownText);
            range.deleteContents();
            range.insertNode(textNode);

            // Move cursor after inserted text
            range.setStartAfter(textNode);
            range.collapse(true);
            selection.removeAllRanges();
            selection.addRange(range);

            input.focus();
        }
    }

    // Show link dialog (instead of browser prompt)
    function showLinkDialog(input, range, selectedText) {
        // Create modal dialog
        const dialogHtml = `
            <div class="modal fade" id="link-dialog" tabindex="-1">
                <div class="modal-dialog modal-sm">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">Insert Link</h5>
                            <button type="button" class="close" data-dismiss="modal">&times;</button>
                        </div>
                        <div class="modal-body">
                            <div class="form-group">
                                <label>Link Text</label>
                                <input type="text" class="form-control" id="link-text-input" value="${selectedText || 'link text'}">
                            </div>
                            <div class="form-group">
                                <label>URL</label>
                                <input type="text" class="form-control" id="link-url-input" placeholder="https://" value="https://">
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-dismiss="modal">Cancel</button>
                            <button type="button" class="btn btn-primary" id="insert-link-btn">Insert</button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        // Remove existing dialog if any
        $('#link-dialog').remove();

        // Add to page
        $('body').append(dialogHtml);

        // Show modal
        $('#link-dialog').modal('show');

        // Handle insert
        $('#insert-link-btn').off('click').on('click', function() {
            const linkText = $('#link-text-input').val();
            const linkUrl = $('#link-url-input').val();

            if (linkUrl && linkUrl !== 'https://') {
                const markdownText = `[${linkText}](${linkUrl})`;
                const textNode = document.createTextNode(markdownText);
                range.deleteContents();
                range.insertNode(textNode);

                range.setStartAfter(textNode);
                range.collapse(true);
                const selection = window.getSelection();
                selection.removeAllRanges();
                selection.addRange(range);

                input.focus();
            }

            $('#link-dialog').modal('hide');
        });

        // Clean up on close
        $('#link-dialog').on('hidden.bs.modal', function() {
            $(this).remove();
        });
    }

    // Toolbar button click handlers
    $(document).on('click', '.format-btn', function(e) {
        e.preventDefault();
        const format = $(this).data('format');
        const inputId = $(this).closest('.form-group').find('.comment-text-input').attr('id');
        applyMarkdownFormat(format, inputId);
    });

    // Keyboard shortcuts for formatting
    $(document).on('keydown', '.comment-text-input', function(e) {
        // Check for Ctrl/Cmd key combinations
        if (e.ctrlKey || e.metaKey) {
            let format = null;

            switch(e.key.toLowerCase()) {
                case 'b':
                    format = 'bold';
                    break;
                case 'i':
                    format = 'italic';
                    break;
                case 'u':
                    format = 'underline';
                    break;
                case 'k':
                    format = 'link';
                    break;
            }

            if (format) {
                e.preventDefault();
                applyMarkdownFormat(format, $(this).attr('id'));
            }
        }
    });

    // Strip rich formatting on paste - only keep plain text
    $(document).on('paste', '.comment-text-input', function(e) {
        e.preventDefault();

        // Get plain text from clipboard
        let text = '';
        if (e.originalEvent.clipboardData) {
            text = e.originalEvent.clipboardData.getData('text/plain');
        } else if (window.clipboardData) {
            text = window.clipboardData.getData('Text');
        }

        // Insert plain text at cursor position
        const selection = window.getSelection();
        if (!selection.rangeCount) return;

        const range = selection.getRangeAt(0);
        range.deleteContents();

        const textNode = document.createTextNode(text);
        range.insertNode(textNode);

        // Move cursor to end of inserted text
        range.setStartAfter(textNode);
        range.collapse(true);
        selection.removeAllRanges();
        selection.addRange(range);

        // Trigger input event for Clear button visibility
        $(this).trigger('input');
    });

    // This function is no longer needed with contenteditable inline mentions

    // Get full comment text from contenteditable (extracts plain text with @mentions preserved)
    function getFullCommentText() {
        const $comment = $('#new-comment');
        return extractTextFromContenteditable($comment[0]);
    }

    // Helper function to recursively extract text from contenteditable
    function extractTextFromContenteditable(element) {
        if (!element) return '';

        let text = '';

        // Iterate through child nodes
        Array.from(element.childNodes).forEach(node => {
            if (node.nodeType === Node.TEXT_NODE) {
                // Plain text node
                text += node.textContent;
            } else if (node.nodeType === Node.ELEMENT_NODE) {
                if (node.classList && node.classList.contains('mention')) {
                    // Mention span - preserve as @username
                    text += '@' + node.getAttribute('data-username');
                } else {
                    // For any other element, just get text content (includes markdown syntax)
                    text += extractTextFromContenteditable(node);
                }
            }
        });

        return text.trim();
    }

    // Handle @mention autocomplete in contenteditable comment input
    $('#new-comment').on('input', function(e) {
        const input = $(this)[0];
        const selection = window.getSelection();

        if (!selection.rangeCount) return;

        const range = selection.getRangeAt(0);
        const textNode = range.startContainer;

        if (textNode.nodeType !== Node.TEXT_NODE) {
            // Close dropdown if not in text
            if (mentionDropdown) {
                mentionDropdown.remove();
                mentionDropdown = null;
            }
            updateSaveButtonState();
            return;
        }

        const textContent = textNode.textContent;
        const cursorPos = range.startOffset;
        const textBeforeCursor = textContent.substring(0, cursorPos);
        const lastAtIndex = textBeforeCursor.lastIndexOf('@');

        // Check if we found an @ and there's no space after it
        if (lastAtIndex !== -1) {
            const textAfterAt = textBeforeCursor.substring(lastAtIndex + 1);

            if (!textAfterAt.includes(' ') && textAfterAt.length >= 1) {
                const searchTerm = textAfterAt.toLowerCase();

                const filteredMembers = projectMembers.filter(member =>
                    member.toLowerCase().includes(searchTerm)
                );

            if (filteredMembers.length === 0) {
                if (mentionDropdown) {
                    mentionDropdown.remove();
                    mentionDropdown = null;
                }
                return;
            }

            // Create or update dropdown
            if (!mentionDropdown) {
                mentionDropdown = $('<div class="mention-dropdown"></div>');
                // Append to modal-body for proper absolute positioning
                $('#task-modal .modal-body').append(mentionDropdown);
            }

            // Position dropdown at cursor location
            const selection = window.getSelection();

            if (selection.rangeCount > 0) {
                const range = selection.getRangeAt(0);
                const rect = range.getBoundingClientRect();

                // Get modal body for position calculation
                const modalBody = $('#task-modal .modal-body')[0];
                const modalBodyRect = modalBody.getBoundingClientRect();

                // Calculate position relative to modal body
                const top = rect.bottom - modalBodyRect.top + modalBody.scrollTop;
                const left = rect.left - modalBodyRect.left;

                mentionDropdown.css({
                    position: 'absolute',
                    top: top + 'px',
                    left: left + 'px',
                    minWidth: '200px',
                    maxWidth: '400px'
                });
            } else {
                // Fallback
                const $commentInput = $('#new-comment');
                const inputOffset = $commentInput.offset();
                const modalBodyOffset = $('#task-modal .modal-body').offset();

                mentionDropdown.css({
                    position: 'absolute',
                    top: (inputOffset.top - modalBodyOffset.top + 20) + 'px',
                    left: (inputOffset.left - modalBodyOffset.left) + 'px',
                    minWidth: '200px',
                    maxWidth: '400px'
                });
            }

            // Populate dropdown
            mentionDropdown.empty();
            filteredMembers.slice(0, 5).forEach(member => {
                const item = $(`<div class="mention-dropdown-item">${member}</div>`);
                item.on('click', function() {
                    // Replace @search with styled mention span
                    const beforeAt = textContent.substring(0, lastAtIndex);
                    const afterCursor = textContent.substring(cursorPos);

                    // Create mention span
                    const mentionSpan = document.createElement('span');
                    mentionSpan.className = 'mention';
                    mentionSpan.contentEditable = 'false';
                    mentionSpan.setAttribute('data-username', member);
                    mentionSpan.textContent = '@' + member;

                    // Create text nodes
                    const beforeNode = document.createTextNode(beforeAt);
                    const afterNode = document.createTextNode(' ' + afterCursor);

                    // Replace content
                    const selection = window.getSelection();
                    const range = selection.getRangeAt(0);

                    // Clear the text node content
                    textNode.textContent = '';

                    // Insert nodes
                    const parent = textNode.parentNode || input;
                    if (beforeAt) parent.insertBefore(beforeNode, textNode);
                    parent.insertBefore(mentionSpan, textNode);
                    parent.insertBefore(afterNode, textNode);
                    if (textNode.parentNode) textNode.parentNode.removeChild(textNode);

                    // Set cursor after mention
                    const newRange = document.createRange();
                    newRange.setStart(afterNode, 1);
                    newRange.collapse(true);
                    selection.removeAllRanges();
                    selection.addRange(newRange);

                    input.focus();

                    // Remove dropdown
                    mentionDropdown.remove();
                    mentionDropdown = null;

                    updateSaveButtonState();
                });
                mentionDropdown.append(item);
            });
        } else {
            // Close dropdown if not searching
            if (mentionDropdown) {
                mentionDropdown.remove();
                mentionDropdown = null;
            }
        }
        } else {
            // No @ found or not in mention mode
            if (mentionDropdown) {
                mentionDropdown.remove();
                mentionDropdown = null;
            }
        }
    });

    // Clear content and dropdown when modal closes
    $('#task-modal').on('hidden.bs.modal', function() {
        $('#new-comment').html('');
        if (mentionDropdown) {
            mentionDropdown.remove();
            mentionDropdown = null;
        }
    });

    // Reposition dropdown when modal scrolls
    $('#task-modal .modal-body').on('scroll', function() {
        if (mentionDropdown) {
            const $commentInput = $('#new-comment');
            const inputOffset = $commentInput.offset();
            const modalBodyOffset = $('#task-modal .modal-body').offset();
            const modalScrollTop = $('#task-modal .modal-body').scrollTop();

            mentionDropdown.css({
                top: (inputOffset.top - modalBodyOffset.top + $commentInput.outerHeight() + modalScrollTop + 2) + 'px',
                left: (inputOffset.left - modalBodyOffset.left) + 'px'
            });
        }
    });

    // Close dropdown when clicking outside or pressing Escape
    $(document).on('click', function(e) {
        if (mentionDropdown && !$(e.target).closest('#new-comment, .mention-dropdown').length) {
            mentionDropdown.remove();
            mentionDropdown = null;
        }
    });

    $(document).on('keydown', '#new-comment', function(e) {
        const input = $(this);
        const text = input.val().trim();

        // Handle Escape key to close dropdown
        if (e.key === 'Escape' && mentionDropdown) {
            mentionDropdown.remove();
            mentionDropdown = null;
            return;
        }

        // Handle Space and Enter key to convert typed email/username to tag
        if ((e.key === ' ' || e.key === 'Enter') && text.startsWith('@')) {
            e.preventDefault();

            // Extract the mention (remove @ prefix)
            const mention = text.substring(1);

            if (mention && projectMembers.includes(mention)) {
                addMentionTag(mention);
                input.val('');  // Clear input
            }

            // Close dropdown
            if (mentionDropdown) {
                mentionDropdown.remove();
                mentionDropdown = null;
            }
        }
    });

    $('.filter-item select, #tasks-search-box').on('change input', function() {
        currentPage = 1;
        renderTasks($('#tasks-search-box').val());
        renderPagination();
    });
    
    getLatestSprintId().then(function(latestSprintId) {
        // If there's a valid sprint ID, update the edit button
        if (latestSprintId) {
            $('#edit-sprint-icon').css('color', '#007bff').data('sprint-id', latestSprintId);  // Enable icon and store sprint ID
        } else {
            $('#edit-sprint-icon').css('color', '#ccc').data('sprint-id', null);  // Disable icon if no valid sprint
        }
    }).catch(function(error) {
        console.error('Failed to fetch latest sprint ID:', error);
    });

    // Sprint selection change handler (this part stays the same)
    $('#filter-sprint').on('change', function() {
        const selectedSprint = $(this).val();
        if (selectedSprint && selectedSprint !== 'backlog') {
            $('#edit-sprint-icon').css('color', '#007bff').data('sprint-id', selectedSprint);  // Enable icon and store sprint ID
        } else {
            $('#edit-sprint-icon').css('color', '#ccc').data('sprint-id', null);  // Disable icon if no valid sprint
        }
    });

    

    // Ensure this is added towards the end of your script
    $(document).off('input', '#filter-assigned-to').on('input', '#filter-assigned-to', function() {
        performUserSearch($(this));
    });


    $(document).off('click', '.user-search-result').on('click', '.user-search-result', function() {
        const selectedEmail = $(this).text();
        const $container = $(this).closest('.user-search-container');
        
        $container.find('.user-search').val(selectedEmail);
        $container.find('.user-search-results').hide();
        
        // Trigger change event for any necessary updates
        $container.find('.user-search').trigger('change');
    });
    
    window.addEventListener('popstate', function(event) {
        const taskId = event.state ? event.state.taskId : null;
        if (taskId) {
            openTaskModal(taskId);
        } else {
            $('#task-modal').modal('hide');  // Hide the modal if no task ID is present in state
        }
    });    
    
    // Add the following event listener to handle URL changes on modal close
    $('#task-modal').on('hidden.bs.modal', function () {
        // Clear the tags dropdown to prevent duplicates on next open
        $('#task-tags').empty();

        // Get the current URL and update it to remove the task ID
        const currentUrl = window.location.pathname;
        const newUrl = currentUrl.replace(/\/\d+$/, '');  // Remove the trailing task ID from the URL

        // Update the URL without reloading the page
        window.history.replaceState({}, '', newUrl);
    });

    $('#confirmTaskDelete').on('click', function() {
        if (taskToDelete) {
            deleteTask(taskToDelete);
            taskToDelete = null;
        }
    });

    // Update Tags button click handler
    $('#update-tags-btn').click(async function() {
        try {
            currentTags = await fetchProjectTags();
            renderTagsInModal(currentTags);
            $('#tags-modal').modal('show');
        } catch (error) {
            $('#failure-modal-message').text(`Error: ${error.message}`);
            $('#failure-modal').modal('show');
        }
    });

    // Add new tag button click handler
    $('#add-tag-btn').click(function() {
        const newTag = $('#new-tag').val().trim().toLowerCase();
        console.log('Attempting to add new tag:', newTag);
        console.log('Current tags before adding:', currentTags);
        
        if (newTag && !currentTags.includes(newTag)) {
            currentTags.push(newTag);
            console.log('Current tags after adding:', currentTags);
            renderTagsInModal(currentTags);
            $('#new-tag').val('');
        }
    });

    // Remove tag click handler
    $('#tags-container').on('click', '.close', function(e) {
        e.preventDefault();
        e.stopPropagation();
        const tagToRemove = $(this).data('tag').toString(); // Ensure string comparison
        console.log('Click event triggered on close button');
        console.log('Tag to remove:', tagToRemove);
        console.log('Type of tag to remove:', typeof tagToRemove);
        
        // Modify the filter to ensure string comparison
        currentTags = currentTags.filter(tag => String(tag) !== String(tagToRemove));
        console.log('Current tags after removal:', currentTags);
        renderTagsInModal(currentTags);
    });

    // Save tags click handler
    $('#save-tags').click(async function() {
        try {
            await updateProjectTags(currentTags);
            $('#tags-modal').modal('hide');
            $('#success-modal-message').text('Tags updated successfully.');
            $('#success-modal').modal('show');
            await populateDropdowns(); // Refresh all dropdowns with new tags
        } catch (error) {
            $('#failure-modal-message').text(`Error: ${error.message}`);
            $('#failure-modal').modal('show');
        }
    });

    // Add keypress handler for new tag input
    $('#new-tag').keypress(function(e) {
        if (e.which === 13) { // Enter key
            e.preventDefault();
            $('#add-tag-btn').click();
        }
    });

    // Initialize
    createUserSearchInput();
    renderDefaultLayout();
    populateDropdowns();


    // $('[data-widget="searchbar"]').searchBar();
});