$(function () {
  $('#registerForm').validate({
      rules: {
          email: {
              required: true,
              email: true
          },
          password: {
              required: true,
              minlength: 5
          },
          retype_password: {
              required: true,
              minlength: 5,
              equalTo: "#password"
          },
          terms: {
              required: true
          }
      },
      messages: {
          email: {
              required: "Please enter an email address",
              email: "Please enter a valid email address"
          },
          password: {
              required: "Please enter a password",
              minlength: "Your password must be at least 5 characters long"
          },
          retype_password: {
              required: "Please retype the password",
              minlength: "Your password must be at least 5 characters long",
              equalTo: "Please enter the same password as above"
          },
          terms: "Please accept our terms"
      },
      errorElement: 'span',
      errorPlacement: function (error, element) {
          error.addClass('invalid-feedback');
          if (element.is(":checkbox")) {
              error.insertAfter(element.next('label'));
          } else {
              element.closest('.input-group').append(error);
          }
      },
      highlight: function (element, errorClass, validClass) {
          $(element).addClass('is-invalid');
      },
      unhighlight: function (element, errorClass, validClass) {
          $(element).removeClass('is-invalid');
      },
      submitHandler: function (form, event) {
        event.preventDefault(); // Prevent the default form submission
        const formData = {
            email: $('#email').val(),
            password: $('#password').val(),
            terms: $('#agreeTerms').is(':checked')
        };
    
        // Send data as JSON
        fetch('/auth/register', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(formData)
        })
        .then(response => response.json())
        .then(data => {
            if (data.detail === "REGISTER_USER_ALREADY_EXISTS") {
                // Handle specific error for user already exists
                $('#messageArea').html('<p>Email already in use!</p>');
                $('#messageArea').css('color', 'red');
            } else {
                // Handle general success case
                $('#messageArea').html('<p>Registration successful!</p>');
                $('#messageArea').css('color', 'green');
            }
        })
        .catch((error) => {
            console.error('Error:', error);
            $('#messageArea').text('Registration failed: ' + error.message);
            $('#messageArea').css('color', 'red');
        });
      }    
    });
  });
