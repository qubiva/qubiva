$(document).ready(function() {
    $('.btn-sidebar').on('click', function() {
        let $input = $(this).closest('.input-group').find('.form-control-sidebar');
        $input.val('');  // Clears the input field
        $input.trigger('input');  // Trigger input event if there’s any script dependent on it
        $('.sidebar-search-results').removeClass('show');  // Hide search results
        console.log('Input cleared:', $input.val());  // Confirm that the input is cleared
    });
});
