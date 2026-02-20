var paceOptions = {
    ajax: false,
    document: true,
    eventLag: false,
    elements: false, // Disable tracking of HTML elements
    restartOnRequestAfter: false, // Prevent restarting for AJAX requests
    restartOnPushState: false, // Prevent restarting on pushState changes
    target: 'body', // Set a specific target for the progress bar
    hideElement: 'pace-hidden' // Class to add to the body when loading is complete
};

$(document).ready(function() {
    if (window.performance && window.performance.navigation.type == 1) {
        Pace.restart();
    }
    
    // Stop Pace when your custom content is loaded
    $(document).on('DOMContentLoaded', function() {
        Pace.stop();
    });
});