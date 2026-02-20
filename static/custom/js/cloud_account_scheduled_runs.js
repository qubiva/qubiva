$(document).ready(function() {
    let schedulesData = {};
    let currentView = 'grid';
    let itemsPerPage = 10;
    let currentPage = 1;
    let currentFilter = '';
    let deleteScheduleId = '';

    // Get URL parameters
    const projectName = Qubiva.url.projectName();
    const cloudPlatform = Qubiva.url.cloudPlatform();
    const accountId = Qubiva.url.accountId();

    $('#newScheduleBtn').on('click', function(e) {
        e.preventDefault();
        const baseUrl = `/dashboard/projects/${encodeURIComponent(projectName)}/cloud_accounts/${encodeURIComponent(cloudPlatform)}/${encodeURIComponent(accountId)}`;
        window.location.href = baseUrl;
    });

    $('#confirmDeleteBtn').on('click', function() {
        deleteSchedule(deleteScheduleId);
    });

    // Validate and enable delete button when conditions are met
    $('#confirmationScheduleId, #confirmIrreversibleAction').on('input change', function() {
        const inputId = $('#confirmationScheduleId').val();
        const isConfirmed = $('#confirmIrreversibleAction').is(':checked');

        if (inputId === deleteScheduleId && isConfirmed) {
            $('#confirmDeleteBtn').prop('disabled', false);
            $('#confirmationError').addClass('d-none');
        } else {
            $('#confirmDeleteBtn').prop('disabled', true);
            if (inputId !== deleteScheduleId) {
                $('#confirmationError').removeClass('d-none').text('Schedule ID does not match.');
            } else if (!isConfirmed) {
                $('#confirmationError').removeClass('d-none').text('Please confirm that the action is irreversible.');
            } else {
                $('#confirmationError').addClass('d-none');
            }
        }
    });

    function showDeleteConfirmationModal(scheduleId) {
        deleteScheduleId = scheduleId;
        const deleteModal = $('#deleteConfirmationModal');
        $('#scheduleIdDisplay').text(scheduleId);
        $('#confirmationScheduleId').val('');
        $('#confirmIrreversibleAction').prop('checked', false);
        $('#confirmationError').addClass('d-none');
        $('#confirmDeleteBtn').prop('disabled', true);
        
        // Add handlers for close buttons
        deleteModal.find('.close, .btn-secondary').off('click').on('click', function() {
            deleteModal.modal('hide');
            // Reset form state
            $('#confirmationScheduleId').val('');
            $('#confirmIrreversibleAction').prop('checked', false);
            $('#confirmationError').addClass('d-none');
        });
        
        deleteModal.modal('show');
    }

    // Update your showMessageModal function
    function showMessageModal(title, message) {
        const messageModal = $('#messageModal');
        $('#messageModalLabel').text(title);
        $('#messageModalBody').text(message);
        messageModal.modal('show');

        // Add click handlers for close buttons
        messageModal.find('.close, .btn-secondary').on('click', function() {
            messageModal.modal('hide');
        });
    }

    function deleteSchedule(scheduleId) {
        const deleteUrl = `/api/v1/projects/${encodeURIComponent(projectName)}/cloud_accounts/${encodeURIComponent(cloudPlatform)}/${encodeURIComponent(accountId)}/scheduled_runs/${encodeURIComponent(scheduleId)}`;

        $.ajax({
            url: deleteUrl,
            type: 'DELETE',
            success: function() {
                $('#deleteConfirmationModal').modal('hide');
                showMessageModal("Success", "Schedule deleted successfully.");
                fetchSchedules();
            },
            error: function(error) {
                $('#deleteConfirmationModal').modal('hide');
                showMessageModal("Error", Qubiva.extractError(error, 'An error occurred while deleting the schedule. Please try again.'));
            }
        });
    }

    function fetchSchedules() {
        const listUrl = `/api/v1/projects/${encodeURIComponent(projectName)}/cloud_accounts/${encodeURIComponent(cloudPlatform)}/${encodeURIComponent(accountId)}/scheduled_runs/list`;
        
        $.ajax({
            url: listUrl,
            type: 'GET',
            success: function(data) {
                schedulesData = data.schedules.reduce((acc, schedule) => {
                    acc[schedule.schedule_id] = schedule;
                    return acc;
                }, {});
                renderSchedules();
                renderPagination();
            },
            error: function(error) {
                console.error('Error fetching schedules:', error);
                $('#schedules-wrapper').html('<p>No schedules found!</p>');
            }
        });
    }

    function renderSchedules() {
        $('#schedules-wrapper').empty();

        const filteredSchedules = Object.entries(schedulesData).filter(([scheduleId, schedule]) => {
            if (currentFilter && currentFilter !== 'all') {
                return schedule.status === currentFilter;
            }
            const searchTerm = $('#schedule-search-box').val().toLowerCase();
            return schedule.schedule_id.toLowerCase().includes(searchTerm) ||
                schedule.payload.run_type.toLowerCase().includes(searchTerm) ||
                (schedule.payload.git_repo && schedule.payload.git_repo.toLowerCase().includes(searchTerm)) ||
                schedule.frequency.toLowerCase().includes(searchTerm);
        });

        const start = (currentPage - 1) * itemsPerPage;
        const end = start + itemsPerPage;
        const paginatedSchedules = filteredSchedules.slice(start, end);

        if (paginatedSchedules.length === 0) {
            $('#schedules-wrapper').append('<p>No schedules found!</p>');
            return;
        }

        if (currentView === 'grid') {
            paginatedSchedules.forEach(([scheduleId, schedule]) => {
                $('#schedules-wrapper').append(`
                    <div class="col-md-4 mb-3">
                        <div class="card h-100 d-flex flex-column schedule-card">
                            <div class="card-body d-flex flex-column schedule-card-body">
                                <div class="card-text">
                                    <div class="schedule-info-container">
                                        <i class="fas fa-clock schedule-icon"></i>
                                        <span class="schedule-info">${scheduleId}</span>
                                    </div>
                                    <div class="schedule-info-container">
                                        <i class="fas fa-cogs schedule-icon"></i>
                                        <span class="schedule-info">${schedule.payload.run_type}</span>
                                    </div>
                                    ${schedule.payload.git_repo ? `
                                    <div class="schedule-info-container">
                                        <i class="fab fa-github schedule-icon"></i>
                                        <span class="schedule-info">${schedule.payload.git_repo}</span>
                                    </div>
                                    ` : ''}
                                    ${schedule.payload.use_auto_benchmark ? `
                                    <div class="schedule-info-container">
                                        <i class="fas fa-check-circle schedule-icon"></i>
                                        <span class="schedule-info">Auto Benchmark</span>
                                    </div>
                                    ` : ''}
                                    ${schedule.payload.mod_type ? `
                                    <div class="schedule-info-container">
                                        <i class="fas fa-layer-group schedule-icon"></i>
                                        <span class="schedule-info">${schedule.payload.mod_type}</span>
                                    </div>
                                    ` : ''}
                                    ${schedule.payload.benchmark_id ? `
                                    <div class="schedule-info-container">
                                        <i class="fas fa-tag schedule-icon"></i>
                                        <span class="schedule-info">${schedule.payload.benchmark_id}</span>
                                    </div>
                                    ` : ''}
                                    <div class="schedule-info-container">
                                        <i class="fas fa-calendar schedule-icon"></i>
                                        <span class="schedule-info">${schedule.frequency}</span>
                                    </div>
                                    ${schedule.next_execution ? `
                                    <div class="schedule-info-container">
                                        <i class="fas fa-forward schedule-icon"></i>
                                        <span class="schedule-info">Next: ${new Date(schedule.next_execution).toLocaleString()}</span>
                                    </div>
                                    ` : ''}
                                    <div class="schedule-info-container">
                                        <i class="fas fa-info-circle schedule-icon"></i>
                                        <span class="schedule-info">${schedule.status}</span>
                                    </div>
                                </div>
                            </div>
                            <div class="schedule-footer">
                                <a href="#" class="btn btn-link text-primary p-0 schedule-action view-schedule" data-schedule="${scheduleId}">
                                    <i class="fas fa-eye"></i>
                                </a>
                                <a href="#" class="btn btn-link text-danger p-0 delete-schedule schedule-action" data-schedule="${scheduleId}">
                                    <i class="fas fa-trash-alt"></i>
                                </a>
                            </div>
                        </div>
                    </div>
                `);
            });
        } else {
            $('#schedules-wrapper').append('<div class="col-12"><ul class="list-group"></ul></div>');
            paginatedSchedules.forEach(([scheduleId, schedule]) => {
                $('.list-group').append(`
                    <li class="list-group-item d-flex justify-content-between align-items-center schedule-list-item">
                        <div>
                            <div class="schedule-info-container">
                                <i class="fas fa-clock schedule-icon"></i>
                                <span class="schedule-info">${scheduleId}</span>
                            </div>
                            <div class="schedule-info-container">
                                <i class="fas fa-cogs schedule-icon"></i>
                                <span class="schedule-info">${schedule.payload.run_type}</span>
                            </div>
                            ${schedule.payload.git_repo && schedule.payload.git_repo != null && schedule.payload.git_repo.trim() !== '' ? `
                                <div class="schedule-info-container">
                                    <i class="fab fa-github schedule-icon"></i>
                                    <span class="schedule-info">${schedule.payload.git_repo}</span>
                                </div>
                            ` : ''}
                            ${schedule.payload.use_auto_benchmark ? `
                            <div class="schedule-info-container">
                                <i class="fas fa-check-circle schedule-icon"></i>
                                <span class="schedule-info">Auto Benchmark</span>
                            </div>
                            ` : ''}
                            ${schedule.payload.mod_type ? `
                            <div class="schedule-info-container">
                                <i class="fas fa-layer-group schedule-icon"></i>
                                <span class="schedule-info">${schedule.payload.mod_type}</span>
                            </div>
                            ` : ''}
                            ${schedule.payload.benchmark_id ? `
                            <div class="schedule-info-container">
                                <i class="fas fa-tag schedule-icon"></i>
                                <span class="schedule-info">${schedule.payload.benchmark_id}</span>
                            </div>
                            ` : ''}
                            <div class="schedule-info-container">
                                <i class="fas fa-calendar schedule-icon"></i>
                                <span class="schedule-info">${schedule.frequency}</span>
                            </div>
                            ${schedule.next_execution ? `
                            <div class="schedule-info-container">
                                <i class="fas fa-forward schedule-icon"></i>
                                <span class="schedule-info">Next: ${new Date(schedule.next_execution).toLocaleString()}</span>
                            </div>
                            ` : ''}
                            <div class="schedule-info-container">
                                <i class="fas fa-info-circle schedule-icon"></i>
                                <span class="schedule-info">${schedule.status}</span>
                            </div>
                        </div>
                        <div class="schedule-actions-container">
                            <a href="#" class="btn btn-link text-primary p-0 schedule-action view-schedule" data-schedule="${scheduleId}">
                                <i class="fas fa-eye"></i>
                            </a>
                            <a href="#" class="btn btn-link text-danger p-0 delete-schedule schedule-action" data-schedule="${scheduleId}">
                                <i class="fas fa-trash-alt"></i>
                            </a>
                        </div>
                    </li>
                `);
            });
        }

        // Add hover effects
        $('.card, .list-group-item').hover(
            function() { $(this).addClass('hover-effect'); },
            function() { $(this).removeClass('hover-effect'); }
        );

        // Attach event listeners
        $('.view-schedule').on('click', function(e) {
            e.preventDefault();
            const scheduleId = $(this).data('schedule');
            window.location.href = `/dashboard/projects/${encodeURIComponent(projectName)}/cloud_accounts/${encodeURIComponent(cloudPlatform)}/${encodeURIComponent(accountId)}/scheduled_runs/${encodeURIComponent(scheduleId)}`;
        });

        $('.delete-schedule').on('click', function(e) {
            e.preventDefault();
            const scheduleId = $(this).data('schedule');
            showDeleteConfirmationModal(scheduleId);
        });
    }

    function renderPagination() {
        $('#pagination').empty();
        const totalItems = Object.keys(schedulesData).length;
        const totalPages = Math.ceil(totalItems / itemsPerPage);

        for (let i = 1; i <= totalPages; i++) {
            $('#pagination').append(`
                <li class="page-item ${i === currentPage ? 'active' : ''}">
                    <a class="page-link" href="#">${i}</a>
                </li>
            `);
        }

        $('.page-link').on('click', function(e) {
            e.preventDefault();
            currentPage = parseInt($(this).text());
            renderSchedules();
            renderPagination();
        });
    }

    // Event Handlers
    $('#itemsPerPageSelect').on('change', function() {
        itemsPerPage = parseInt($(this).val());
        currentPage = 1;
        renderSchedules();
        renderPagination();
    });

    $('#schedule-search-box').on('keyup input', function() {
        currentPage = 1;
        renderSchedules();
        renderPagination();
    });

    $('#refresh-schedules').on('click', function() {
        fetchSchedules();
    });

    $('#listViewBtn, #gridViewBtn').on('click', function() {
        currentPage = 1;
        currentView = $(this).attr('id') === 'listViewBtn' ? 'list' : 'grid';
        $(this).addClass('active').siblings().removeClass('active');
        renderSchedules();
        renderPagination();
    });

    $('#filterDropdown').on('change', function() {
        currentFilter = $(this).val();
        currentPage = 1;
        renderSchedules();
        renderPagination();
    });

    // Search box clear functionality
    $('#schedule-search-box').on('input', function() {
        const $clearBtn = $(this).siblings('.search-clear-btn');
        $clearBtn.toggle(!!this.value);
    });

    $('.search-clear-btn').on('click', function() {
        $('#schedule-search-box').val('').trigger('input');
        $(this).hide();
    });

    // Initial load
    fetchSchedules();
});