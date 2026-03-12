$(function() {
    // Create Sprint button logic
    $('#create-sprint-btn').click(function() {
        // Reset form for new sprint
        $('#sprint-form')[0].reset();
        $('#sprint-modal').modal('show');
    });

    // Save Sprint button logic
    $('#save-sprint').click(function() {
        const sprintData = {
            name: $('#sprint-name').val(),
            goal: $('#sprint-goal').val(),
            startDate: $('#sprint-start-date').val(),
            endDate: $('#sprint-end-date').val()
        };

        // For now, just log the sprint data (replace this with actual API call)
        console.log('New Sprint:', sprintData);
        $('#sprint-modal').modal('hide');
    });
});
