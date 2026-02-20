$(document).ready(function() {
    let allData = {}; // Store all fetched data

    function initializeDataTables() {
        if ($.fn.DataTable.isDataTable('#resourcesDataTable')) {
            $('#resourcesDataTable').DataTable().clear().destroy(); // Ensure to destroy before reinitialization
        }
        $("#resourcesDataTable").DataTable({
            "responsive": false, 
            "lengthChange": true, 
            "autoWidth": false,
            "dom": 'Bfrtip',
            "scrollX": true,
            "buttons": [
                "copy", "csv", "excel", "pdf", "print", "colvis"
            ]
        }).buttons().container().appendTo('#resourcesDataTable_wrapper .col-md-6:eq(0)');
    }

    $('#requestsDataTable').on('click', '.load-data', function() {
        var requestId = $(this).data('id');
        loadResourceData(requestId);
    });

    function loadResourceData(requestId) {
        console.log('Loading data for request ID:', requestId);
        $('#currentRequestId').text('(Request ID: ' + requestId + ')'); // Update the display for request ID
        $.ajax({
            url: '/api/v1/resources',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ request_id: requestId }),
            dataType: 'json',
            success: function(data) {
                allData = data;
                if (Object.keys(data).length > 0) {
                    populateDropdown(data);
                    $('#resourceContainer').show();
                    $('#noDataMessage').hide();
                    $('html, body').animate({
                        scrollTop: $('#resourcesDataTableWrapper').offset().top
                    }, 1000); // Smooth scroll to the resourcesDataTableWrapper
                } else {
                    $('#resourceContainer').hide();
                    $('#noDataMessage').show();
                }
            },
            error: function(error) {
                console.error('Error loading data:', error);
                $('#resourceContainer').hide();
                $('#noDataMessage').show();
            }
        });
    }

    function populateDropdown(data) {
        var $select = $('#resourceTypeSelect');
        $select.empty();
        $select.append($('<option>').text('Select Resource Type'));
        $.each(data, function(key) {
            if (typeof key === 'string') {
                $select.append($('<option>').val(key).text(key.toUpperCase()));
            }
        });

        $select.change(function() {
            var resourceType = $(this).val();
            if (data[resourceType]) {
                populateTable(data[resourceType], resourceType);
            }
        });
    }

    function populateTable(items, resourceType) {
        var $table = $('#resourcesDataTable');
        $table.DataTable().clear().destroy(); // Clear and destroy the existing DataTable
        $table.empty(); // Ensure the table is completely emptied

        var $thead = $('<thead>').append('<tr>');
        var $tbody = $('<tbody>');
        var $tfoot = $('<tfoot>').append('<tr>');

        if (items.length > 0) {
            var firstItem = items[0];
            Object.keys(firstItem).forEach(function(key) {
                $thead.find('tr').append($('<th>').text(key));
                $tfoot.find('tr').append($('<th>').text(key));
            });

            items.forEach(function(item) {
                var $row = $('<tr>');
                Object.keys(firstItem).forEach(function(key) {
                    $row.append($('<td>').text(item[key]));
                });
                $tbody.append($row);
            });
        } else {
            var colCount = Object.keys(firstItem || {}).length;
            $tbody.append('<tr><td colspan="' + colCount + '">No data available in table</td></tr>');
        }

        $table.append($thead).append($tbody).append($tfoot);
        initializeDataTables(); // Initialize DataTables with the new table structure
    }
});
