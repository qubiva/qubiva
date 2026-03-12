$(function () {
    console.log("all set and ready!")
    // Get the next parameter from URL query string
    const urlParams = new URLSearchParams(window.location.search);
    let nextUrl = urlParams.get('next');
    // Client-side defense-in-depth: reject suspicious next URLs
    if (nextUrl && (!/^\/[^\/\\]/.test(nextUrl) || nextUrl.includes('://'))) {
        console.warn('Rejected suspicious next URL:', nextUrl);
        nextUrl = null;
    }

    $('#login').validate({
        rules: {
            email: {
                required: true,
                email: true // Ensure this is a valid email format.
            },
            password: {
                required: true
            }
        },
        messages: {
            email: {
                required: "Please enter your registered email address as your username",
                email: "Please enter a valid email address"
            },
            password: {
                required: "Please enter your password"
            }
        },
        errorElement: 'span',
        errorPlacement: function (error, element) {
            error.addClass('invalid-feedback');
            element.closest('.input-group').append(error);
        },
        highlight: function (element, errorClass, validClass) {
            $(element).addClass('is-invalid');
        },
        unhighlight: function (element, errorClass, validClass) {
            $(element).removeClass('is-invalid');
        },
        submitHandler: function (form, event) {
            event.preventDefault(); // Prevent the default form submission
            var $submitButton = $('#login button[type="submit"]'); // Get the submit button
            $submitButton.prop('disabled', true); // Disable the button
            
            const formData = {
                username: $('#email').val(), // Use email input as username
                password: $('#password').val(),
                next: nextUrl  // Include the next URL from query parameter
            };

            $.ajax({
                url: '/api/v1/web-login',
                type: 'POST',
                data: JSON.stringify(formData),
                contentType: 'application/json', // Updated content type
                success: function(response) {
                    // Use the redirect URL from the backend response
                    const redirectUrl = response.redirect_url || '/dashboard';
                    console.log('Redirecting to:', redirectUrl);
                    window.location.href = redirectUrl;
                },
                error: function(xhr) {
                    let errorMsg;
                    if (xhr.status === 401) {
                        errorMsg = "Login failed"; // Specific message for 401 Unauthorized
                    } else {
                        errorMsg = "Service error"; // General error message for other issues
                    }
                    $('#messageArea').html(
                        '<div class="alert alert-danger alert-dismissible fade show mt-2 py-2 px-3" role="alert">' +
                        '<i class="fas fa-exclamation-circle mr-1"></i> ' + errorMsg +
                        '<button type="button" class="close py-2" data-dismiss="alert"><span>&times;</span></button>' +
                        '</div>'
                    );
                },
                complete: function() {
                    $submitButton.prop('disabled', false); // Re-enable the button on complete
                }
            });
        }
    });
});
