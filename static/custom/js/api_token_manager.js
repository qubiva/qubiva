document.addEventListener("DOMContentLoaded", () => {
    const tokenListContainer = document.getElementById("api-tokens-list");
    const noTokensMessage = document.getElementById("no-tokens-message");
    const createTokenForm = document.getElementById("create-api-token-form");
    const revocationFeedback = document.getElementById("revocation-feedback");

    // Copy button handler
    document.getElementById('copyTokenButton').addEventListener('click', function() {
        const tokenInput = document.getElementById('apiToken');
        const token = tokenInput.value;
        
        navigator.clipboard.writeText(token).then(() => {
            const button = this;
            const originalContent = button.innerHTML;
            button.innerHTML = '<i class="fas fa-check"></i> Copied!';
            button.classList.replace('btn-outline-secondary', 'btn-success');
            
            setTimeout(() => {
                button.innerHTML = originalContent;
                button.classList.replace('btn-success', 'btn-outline-secondary');
            }, 2000);
        }).catch(err => {
            console.error('Failed to copy text:', err);
        });
    });

    function showSuccessModal(message, token) {
        const modal = $('#apiTokenModal');
        const modalTitle = document.getElementById('apiTokenModalLabel');
        const successContent = document.getElementById('successContent');
        const errorContent = document.getElementById('errorContent');
        const successMessage = document.getElementById('successMessage');
        const tokenInput = document.getElementById('apiToken');
    
        modalTitle.textContent = 'Success';
        successMessage.textContent = message;
        tokenInput.value = token;
        
        successContent.style.display = 'block';
        errorContent.style.display = 'none';
    
        modal.modal('show');
    }
    
    function showErrorModal(message) {
        const modal = $('#apiTokenModal');
        const modalTitle = document.getElementById('apiTokenModalLabel');
        const successContent = document.getElementById('successContent');
        const errorContent = document.getElementById('errorContent');
        const errorMessage = document.getElementById('errorMessage');
    
        modalTitle.textContent = 'Error';
        errorMessage.textContent = message;
        
        successContent.style.display = 'none';
        errorContent.style.display = 'block';
    
        modal.modal('show');
    }

    async function fetchTokens() {
        try {
            const response = await fetch(`/api/v1/api-tokens/list`, {
                method: "GET",
                credentials: "include",
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                },
            });

            if (!response.ok) {
                const textError = await response.text();
                throw new Error("Failed to fetch tokens. Server returned an error.");
            }

            const data = await response.json();
            renderTokenList(data.api_tokens || []);
        } catch (error) {
            tokenListContainer.innerHTML = `
                <div class="alert alert-danger" role="alert">
                    Failed to load tokens: ${error.message}
                </div>`;
        }
    }

    function renderTokenList(tokens) {
        tokenListContainer.innerHTML = "";
        if (tokens.length === 0) {
            noTokensMessage.style.display = "block";
        } else {
            noTokensMessage.style.display = "none";
            tokens.forEach((token) => {
                const tokenElement = document.createElement("div");
                tokenElement.className = "list-group-item d-flex justify-content-between align-items-center";

                // Format expiration info
                let expiryHtml = '';
                if (token.expires_at) {
                    const expiresDate = new Date(token.expires_at + 'Z');
                    const now = new Date();
                    if (token.expired) {
                        expiryHtml = `<span class="badge badge-danger ml-2">Expired</span>
                            <br><small class="text-muted"><strong>Expired:</strong> ${expiresDate.toLocaleString()}</small>`;
                    } else {
                        const diffMs = expiresDate - now;
                        const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
                        const diffHours = Math.floor((diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
                        const remaining = diffDays > 0 ? `${diffDays}d ${diffHours}h` : `${diffHours}h`;
                        expiryHtml = `<span class="badge badge-success ml-2">Active</span>
                            <br><small class="text-muted"><strong>Expires:</strong> ${expiresDate.toLocaleString()} (${remaining} remaining)</small>`;
                    }
                } else {
                    expiryHtml = '<br><small class="text-muted"><strong>Expires:</strong> Unknown</small>';
                }

                tokenElement.innerHTML = `
                    <div>
                        <strong>Token Name:</strong> ${token.token_name} ${expiryHtml.split('<br>')[0]}
                        <br><small class="text-muted"><strong>Created:</strong> ${new Date(token.created_at + 'Z').toLocaleString()}</small>
                        ${expiryHtml.includes('<br>') ? expiryHtml.substring(expiryHtml.indexOf('<br>')) : ''}
                    </div>
                    <button class="btn btn-danger btn-sm revoke-token-button" data-token-name="${token.token_name}">
                        <i class="fas fa-trash"></i> Revoke
                    </button>
                `;
                tokenListContainer.appendChild(tokenElement);
            });

            document.querySelectorAll(".revoke-token-button").forEach((button) => {
                button.addEventListener("click", async (event) => {
                    const tokenName = event.target.closest("button").dataset.tokenName;
                    await revokeToken(tokenName);
                });
            });
        }
    }

    async function revokeToken(tokenName) {
        if (!tokenName) {
            alert("Error: Unable to identify the token to revoke.");
            return;
        }

        try {
            const response = await fetch(`/api/v1/api-tokens/revoke`, {
                method: "POST",
                credentials: "include",
                headers: {
                    "Content-Type": "application/json",
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify({ token_name: tokenName }),
            });

            if (!response.ok) {
                const errorData = await response.json();
                const d = errorData.detail;
                throw new Error(typeof d === 'string' ? d : d ? JSON.stringify(d) : "An unexpected error occurred while revoking the token.");
            }

            revocationFeedback.style.display = "block";
            setTimeout(() => {
                revocationFeedback.style.display = "none";
            }, 3000);

            await fetchTokens();
        } catch (error) {
            alert("Error revoking token: " + error.message);
        }
    }

    createTokenForm.addEventListener("submit", async (event) => {
        event.preventDefault();
    
        const tokenName = document.getElementById("token-name").value.trim();
        const expiryType = document.getElementById("expiry-type").value;
        const expiryValue = parseInt(document.getElementById("expiry-value").value.trim(), 10);
    
        try {
            const isAlphanumeric = /^[a-zA-Z0-9]+$/.test(tokenName);
            if (!isAlphanumeric) {
                throw new Error("Token name must be alphanumeric and cannot contain spaces or special characters.");
            }
    
            if (!tokenName || isNaN(expiryValue) || expiryValue < 1) {
                throw new Error("Invalid input. Please ensure all fields are correctly filled.");
            }
    
            const payload = { token_name: tokenName };
            if (expiryType === "days") {
                payload.expiry_days = expiryValue;
            } else {
                payload.expiry_hours = expiryValue;
            }
    
            const response = await fetch(`/api/v1/api-tokens/generate`, {
                method: "POST",
                credentials: "include",
                headers: {
                    "Content-Type": "application/json",
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify(payload),
            });
        
            const data = await response.json();
            
            if (!response.ok) {
                const d = data.detail;
                throw new Error(typeof d === 'string' ? d : d ? JSON.stringify(d) : "Failed to create token");
            }
        
            showSuccessModal("API token created successfully!", data.api_token);
            await fetchTokens();
            event.target.reset();
        } catch (error) {
            showErrorModal(error.message);
        }
    });

    fetchTokens();
});