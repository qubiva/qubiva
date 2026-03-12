$(document).ready(function() {
  // === initial load ===
  loadGitHubAppStatus();
  let githubAppConfigured = false;


  // toggle private key bullets
  $('#toggle-private-key-visibility').on('click', function() {
    const input = $('#private-key');
    const icon = $('#toggle-private-key-icon');
    if (input.css('-webkit-text-security') === 'disc') {
      input.css('-webkit-text-security', 'none');
      icon.removeClass('fa-eye').addClass('fa-eye-slash');
    } else {
      input.css('-webkit-text-security', 'disc');
      icon.removeClass('fa-eye-slash').addClass('fa-eye');
    }
  });

  // === One form / one submit ===
  $('#github-app-config-form').on('submit', function(e) {
    e.preventDefault();
    saveAndMaybeLink();
  });

  // Open install page from the slug (inline control)
  $('#open-install-url').on('click', function(e) {
    const slug = ($('#app-slug').val() || '').trim();
    if (!slug) {
      e.preventDefault();
      showError('Enter your app slug to open the install page.');
      return;
    }
    $(this).attr('href', `https://github.com/apps/${slug}/installations/new`);
  });

  // Verify & Save mapping without resubmitting credentials
  $('#link-installation-button').on('click', function() {
    if (!githubAppConfigured) {
        showError('First save your GitHub App ID and Private Key. Then you can link an installation.');
        return;
    }
    const installationId = ($('#installation-id').val() || '').trim();
    if (!/^\d+$/.test(installationId)) {
      showError('Installation ID must be a number (e.g., 84275342).');
      return;
    }
    linkInstallation(installationId);
  });

  // (Modal kept, but points to the same actions)
  $('#modal-open-install').on('click', function(e) {
    const slug = ($('#modal-slug').val() || '').trim();
    if (!slug) {
      e.preventDefault();
      showError('Enter your app slug.');
      return;
    }
    $(this).attr('href', `https://github.com/apps/${slug}/installations/new`);
  });

  $('#modal-verify-save').on('click', function() {
    const installationId = ($('#modal-installation-id').val() || '').trim();
    if (!/^\d+$/.test(installationId)) {
      showError('Installation ID must be a number (e.g., 84275342).');
      return;
    }
    linkInstallation(installationId);
  });

  // test connection
  $('#test-connection-button').on('click', testGitHubConnection);

  // delete config
  $('#delete-github-app-button').on('click', showDeleteConfirmationModal);

  // refresh status (modal footer)
  $('#refresh-installations').on('click', function() {
    $('#installationModal').modal('hide');
    loadGitHubAppStatus();
    showSuccess('Refreshed installation status.');
  });

  // ===== Helpers =====
  function showSuccess(message) {
    $('#modalMessage').text(message || 'Operation completed successfully.');
    $('#successModal').modal('show');
  }
  function showError(message) {
    $('#failureModalMessage').text(message || 'An error occurred.');
    $('#failureModal').modal('show');
  }

  // Save credentials; optionally link installation in the same submit
  function saveAndMaybeLink() {
    const appId = ($('#app-id').val() || '').trim();
    const privateKey = ($('#private-key').val() || '').trim();
    const slug = ($('#app-slug').val() || '').trim();
    const installationId = ($('#installation-id').val() || '').trim();

    if (!/^\d+$/.test(installationId)) {
        showError('Installation ID is required and must be a number (e.g., 84275342).');
        return;
    }

    if (!appId || !privateKey) {
      showError('Both App ID and Private Key are required.');
      return;
    }
    if (!/^\d+$/.test(appId)) {
      showError('App ID must be a valid number.');
      return;
    }
    if (!privateKey.includes('BEGIN') || !privateKey.includes('PRIVATE KEY')) {
      showError("Private Key appears invalid. Ensure it's a PEM.");
      return;
    }

    // UI state
    $('#save-github-app-button').prop('disabled', true);
    $('#spinner').show();

    // 1) Save credentials
    $.ajax({
      url: '/api/v1/org/github-app/setup',
      method: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({ app_id: parseInt(appId, 10), private_key: privateKey }),
      success: function(resp) {

        githubAppConfigured = true;
        $('#link-installation-button').prop('disabled', false);
        loadGitHubAppStatus();
        // hide key and reset eye icon
        $('#private-key').val('').css('-webkit-text-security', 'disc');
        $('#toggle-private-key-icon').removeClass('fa-eye-slash').addClass('fa-eye');
        loadGitHubAppStatus();

        // 2) If an Installation ID was provided, link it now
        if (installationId && /^\d+$/.test(installationId)) {
          linkInstallation(installationId, function(ok) {
            if (!ok) return; // error already shown
            // 3) If no installation ID but slug exists, open install page
            if (!installationId && slug) {
              window.open(`https://github.com/apps/${slug}/installations/new`, '_blank', 'noopener');
            }
          });
        } else {
          // No installation provided; optionally open install if slug entered
          if (slug) {
            window.open(`https://github.com/apps/${slug}/installations/new`, '_blank', 'noopener');
            showSuccess((resp.message || 'Saved GitHub App configuration.') + ' A GitHub tab was opened to install your app.');
          } else {
            showSuccess((resp.message || 'Saved GitHub App configuration.') + ' You can paste an Installation ID anytime to link.');
          }
        }
      },
      error: function(xhr) {
        let msg = 'Failed to save GitHub App configuration.';
        try { const r = JSON.parse(xhr.responseText); if (r.detail) msg = r.detail; } catch (_e) {}
        showError(msg);
      },
      complete: function() {
        $('#save-github-app-button').prop('disabled', false);
        $('#spinner').hide();
      }
    });
  }

  // Link installation → calls your callback, stores mapping, refreshes status
  function linkInstallation(installationId, cb) {
    const $linkBtn = $('#link-installation-button');
    $linkBtn.prop('disabled', true).text('Verifying…');

    $.get(`/github/callback?installation_id=${installationId}`)
      .done(function(resp) {
        if (resp && resp.ok) {
          showSuccess(`Linked installation ${installationId} to ${resp.owner}.`);
          loadGitHubAppStatus();
          if (cb) cb(true);
        } else {
          const msg = (resp && resp.message) ? resp.message : 'Verification failed.';
          showError(msg);
          if (cb) cb(false);
        }
      })
      .fail(function(xhr) {
        let msg = 'Verification failed.';
        try { const r = JSON.parse(xhr.responseText); if (r.message) msg = r.message; } catch (e) {}
        showError(msg);
        if (cb) cb(false);
      })
      .always(function() {
        $linkBtn.prop('disabled', false).text('Verify & Save Mapping');
      });
  }

  function testGitHubConnection() {
    const appId = $('#current-app-id').text();
    if (!appId) {
      showError('No GitHub App configured to test.');
      return;
    }
    $('#test-connection-button').prop('disabled', true).text('Testing...');
    $.get('/api/v1/org/github-app/status')
      .done(function(data) {
        if (data.configured && data.installations && data.installations.length > 0) {
          const firstOrg = data.installations[0].org_name;
          $.get(`/api/v1/org/github-app/${firstOrg}/test-auth`)
            .done(function(r) {
              showSuccess(`Connection successful! ${r.message} for ${firstOrg}.`);
            })
            .fail(function(xhr) {
              let msg = 'Authentication test failed. ';
              try { const r = JSON.parse(xhr.responseText); msg += r.detail || 'Check your GitHub App configuration.'; }
              catch (_e) { msg += 'Check your GitHub App configuration.'; }
              showError(msg);
            });
        } else {
          showError('No installations found to test. Install the app to an organization first.');
        }
      })
      .fail(function() {
        showError('Connection test failed. GitHub App not properly configured.');
      })
      .always(function() {
        $('#test-connection-button').prop('disabled', false).text('Test Connection');
      });
  }

    function loadGitHubAppStatus() {
    $('#status-loading').show();
    $('#status-content').hide();

    $.get('/api/v1/org/github-app/status')
        .done(function(data) {
        $('#status-loading').hide();
        $('#status-content').show();

        githubAppConfigured = !!(data && data.configured);

        if (githubAppConfigured) {
            $('#status-not-configured').hide();
            $('#status-configured').show();
            $('#current-app-id').text(data.app_id);
            $('#test-connection-button, #delete-github-app-button').show();
            $('#link-installation-button').prop('disabled', false);   // <-- enable

            const ul = $('#installations-ul').empty();
            if (data.installations && data.installations.length > 0) {
            data.installations.forEach(inst => {
                ul.append(`<li>${inst.org_name} (ID: ${inst.installation_id})</li>`);
            });
            } else {
            ul.append('<li class="text-warning">No installations found. Paste an Installation ID and click “Verify & Save Mapping”.</li>');
            }
        } else {
            $('#status-configured').hide();
            $('#status-not-configured').show();
            $('#test-connection-button, #delete-github-app-button').hide();
            $('#link-installation-button').prop('disabled', true);    // <-- keep disabled
        }
        })
        .fail(function() {
        $('#status-loading').hide();
        $('#status-content').show();
        $('#status-not-configured').show();
        $('#status-configured, #test-connection-button, #delete-github-app-button').hide();
        githubAppConfigured = false;
        $('#link-installation-button').prop('disabled', true);      // <-- keep disabled
        });
    }


  function showDeleteConfirmationModal() {
    $('#confirmationText').val('');
    $('#confirmIrreversible').prop('checked', false);
    $('#confirmationError').addClass('d-none');
    $('#confirmDeleteBtn').prop('disabled', true);
    $('#deleteGitHubAppConfirmationModal').modal('show');
  }

  $('#confirmationText, #confirmIrreversible').on('input change', function() {
    const txt = $('#confirmationText').val();
    const ok = $('#confirmIrreversible').is(':checked');
    if (txt === 'DELETE' && ok) {
      $('#confirmDeleteBtn').prop('disabled', false);
      $('#confirmationError').addClass('d-none');
    } else {
      $('#confirmDeleteBtn').prop('disabled', true);
      if (txt !== 'DELETE') $('#confirmationError').removeClass('d-none').text('You must type DELETE exactly as shown.');
      else if (!ok) $('#confirmationError').removeClass('d-none').text('Please confirm that the action is irreversible.');
      else $('#confirmationError').addClass('d-none');
    }
  });

  $('#confirmDeleteBtn').on('click', function() {
    $('#deleteGitHubAppConfirmationModal').modal('hide');
    $('#delete-github-app-button').prop('disabled', true).text('Deleting...');
    $.ajax({
      url: '/api/v1/org/github-app/delete',
      method: 'DELETE',
      success: function(resp) {
        showSuccess(resp.message);
        $('#app-id').val('');
        $('#private-key').val('').css('-webkit-text-security', 'disc');
        $('#toggle-private-key-icon').removeClass('fa-eye-slash').addClass('fa-eye');
        loadGitHubAppStatus();
      },
      error: function(xhr) {
        let msg = 'Failed to delete GitHub App configuration.';
        try { const r = JSON.parse(xhr.responseText); if (r.detail) msg = r.detail; } catch (_e) {}
        showError(msg);
      },
      complete: function() {
        $('#delete-github-app-button').prop('disabled', false).text('Delete Configuration');
      }
    });
  });
});
