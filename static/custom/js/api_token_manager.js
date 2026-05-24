document.addEventListener("DOMContentLoaded", () => {
    const tokensLoading   = document.getElementById("tokens-loading");
    const tokensEmpty     = document.getElementById("tokens-empty");
    const tokenListWrap   = document.getElementById("api-tokens-list-wrap");
    const tokenList       = document.getElementById("api-tokens-list");
    const revocationFb    = document.getElementById("revocation-feedback");

    // ----------------------------------------------------------------
    // Open create modal
    // ----------------------------------------------------------------
    function openCreateModal() {
        document.getElementById("create-api-token-form").reset();
        $("#modal-create-api-token").modal("show");
    }

    document.getElementById("btn-open-create-token").addEventListener("click", openCreateModal);
    document.getElementById("btn-open-create-token-empty").addEventListener("click", openCreateModal);

    // ----------------------------------------------------------------
    // Confirm create
    // ----------------------------------------------------------------
    document.getElementById("btn-confirm-create-api-token").addEventListener("click", async () => {
        const btn        = document.getElementById("btn-confirm-create-api-token");
        const tokenName  = document.getElementById("token-name").value.trim();
        const expiryType = document.getElementById("expiry-type").value;
        const expiryVal  = parseInt(document.getElementById("expiry-value").value.trim(), 10);

        if (!/^[a-zA-Z0-9]+$/.test(tokenName)) {
            alert("Token name must be alphanumeric (no spaces or special characters).");
            return;
        }
        if (!tokenName || isNaN(expiryVal) || expiryVal < 1) {
            alert("Please fill in all fields correctly.");
            return;
        }

        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin mr-1"></i> Creating...';

        const payload = { token_name: tokenName };
        if (expiryType === "days") { payload.expiry_days  = expiryVal; }
        else                       { payload.expiry_hours = expiryVal; }

        try {
            const resp = await fetch("/api/v1/api-tokens/generate", {
                method: "POST",
                credentials: "include",
                headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
                body: JSON.stringify(payload),
            });
            const data = await resp.json();
            if (!resp.ok) {
                const d = data.detail;
                throw new Error(typeof d === "string" ? d : d ? JSON.stringify(d) : "Failed to create token");
            }
            $("#modal-create-api-token").modal("hide");
            showSuccessModal(data.api_token);
            await fetchTokens();
        } catch (err) {
            alert("Error: " + err.message);
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-plus mr-1"></i> Create Token';
        }
    });

    // ----------------------------------------------------------------
    // Success modal
    // ----------------------------------------------------------------
    function showSuccessModal(token) {
        const modal = $("#apiTokenModal");
        document.getElementById("apiTokenModalLabel").textContent = "Token Created";
        document.getElementById("apiToken").value = token;
        document.getElementById("successContent").style.display = "block";
        document.getElementById("errorContent").style.display   = "none";
        modal.modal("show");
    }

    // Copy button
    document.getElementById("copyTokenButton").addEventListener("click", function () {
        const val = document.getElementById("apiToken").value;
        navigator.clipboard.writeText(val).then(() => {
            const btn = this;
            btn.innerHTML = '<i class="fas fa-check mr-1"></i> Copied';
            btn.classList.replace("btn-outline-secondary", "btn-success");
            setTimeout(() => {
                btn.innerHTML = '<i class="fas fa-copy mr-1"></i> Copy';
                btn.classList.replace("btn-success", "btn-outline-secondary");
            }, 2000);
        }).catch(() => {});
    });

    // ----------------------------------------------------------------
    // Fetch & render tokens
    // ----------------------------------------------------------------
    async function fetchTokens() {
        tokensLoading.style.display  = "block";
        tokensEmpty.style.display    = "none";
        tokenListWrap.style.display  = "none";

        try {
            const resp = await fetch("/api/v1/api-tokens/list", {
                method: "GET",
                credentials: "include",
                headers: { "X-Requested-With": "XMLHttpRequest" },
            });
            if (!resp.ok) throw new Error("Failed to fetch tokens.");
            const data = await resp.json();
            renderTokenList(data.api_tokens || []);
        } catch (err) {
            tokenList.innerHTML = `<div class="alert alert-danger m-3">Failed to load tokens: ${err.message}</div>`;
            tokenListWrap.style.display = "block";
        } finally {
            tokensLoading.style.display = "none";
        }
    }

    function renderTokenList(tokens) {
        tokenList.innerHTML = "";
        if (!tokens.length) {
            tokensEmpty.style.display = "block";
            return;
        }

        tokenListWrap.style.display = "block";
        tokens.forEach((token) => {
            const el = document.createElement("div");
            el.className = "list-group-item d-flex justify-content-between align-items-start mb-2";

            let expiryHtml = "";
            if (token.expires_at) {
                const expiresDate = new Date(token.expires_at + "Z");
                const now = new Date();
                if (token.expired) {
                    expiryHtml = `<span class="badge badge-danger ml-1">Expired</span>` +
                                 `<br><small class="text-muted"><strong>Expired:</strong> ${expiresDate.toLocaleString()}</small>`;
                } else {
                    const diffMs   = expiresDate - now;
                    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
                    const diffHrs  = Math.floor((diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
                    const remaining = diffDays > 0 ? `${diffDays}d ${diffHrs}h` : `${diffHrs}h`;
                    expiryHtml = `<span class="badge badge-success ml-1">Active</span>` +
                                 `<br><small class="text-muted"><strong>Expires:</strong> ${expiresDate.toLocaleString()} (${remaining} remaining)</small>`;
                }
            } else {
                expiryHtml = `<br><small class="text-muted"><strong>Expires:</strong> Unknown</small>`;
            }

            const badge = expiryHtml.split("<br>")[0];
            const meta  = expiryHtml.includes("<br>") ? expiryHtml.substring(expiryHtml.indexOf("<br>")) : "";

            el.innerHTML = `
                <div>
                    <strong>${escHtml(token.token_name)}</strong>${badge}
                    <br><small class="text-muted"><strong>Created:</strong> ${new Date(token.created_at + "Z").toLocaleString()}</small>
                    ${meta}
                </div>
                <button class="btn btn-danger btn-sm revoke-token-button" data-token-name="${escHtml(token.token_name)}">Revoke</button>`;
            tokenList.appendChild(el);
        });

        document.querySelectorAll(".revoke-token-button").forEach((btn) => {
            btn.addEventListener("click", (e) => {
                const name = e.currentTarget.dataset.tokenName;
                document.getElementById("revoke-api-token-name").textContent = name;
                document.getElementById("btn-confirm-revoke-api-token").dataset.tokenName = name;
                $("#modal-revoke-api-token").modal("show");
            });
        });
    }

    // Confirmation modal — confirm revoke
    document.getElementById("btn-confirm-revoke-api-token").addEventListener("click", async function () {
        const name = this.dataset.tokenName;
        this.disabled = true;
        this.textContent = "Revoking...";
        $("#modal-revoke-api-token").modal("hide");
        await revokeToken(name);
        this.disabled = false;
        this.textContent = "Revoke";
    });

    // ----------------------------------------------------------------
    // Revoke
    // ----------------------------------------------------------------
    async function revokeToken(tokenName) {
        if (!tokenName) return;
        try {
            const resp = await fetch("/api/v1/api-tokens/revoke", {
                method: "POST",
                credentials: "include",
                headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
                body: JSON.stringify({ token_name: tokenName }),
            });
            if (!resp.ok) {
                const err = await resp.json();
                const d = err.detail;
                throw new Error(typeof d === "string" ? d : d ? JSON.stringify(d) : "Error revoking token");
            }
            revocationFb.style.display = "block";
            setTimeout(() => { revocationFb.style.display = "none"; }, 3000);
            await fetchTokens();
        } catch (err) {
            alert("Error revoking token: " + err.message);
        }
    }

    // ----------------------------------------------------------------
    // Helpers
    // ----------------------------------------------------------------
    function escHtml(str) {
        if (str == null) return "";
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    fetchTokens();
});
