/**
 * Cloud Analyst — Interactive AI Chat for Cloud Infrastructure
 *
 * Handles conversation lifecycle, SSE streaming, tool call rendering,
 * project/scope picking, and markdown rendering via marked.js.
 */

class CloudAnalyst {
    constructor() {
        this.currentConversationId = null;
        this.isStreaming = false;
        this.abortController = null; // for cancelling in-flight SSE requests
        this.accessibleProjects = []; // cached from API

        // DOM elements
        this.$sidebar = $('#conversation-list');
        this.$messages = $('#chat-messages');
        this.$input = $('#chat-input');
        this.$sendBtn = $('#btn-send');
        this.$chatTitle = $('#chat-title');
        this.$scopeBadge = $('#chat-scope-badge');
        this.$podStatus = $('#pod-status');
        this.$welcomeScreen = $('#chat-welcome');

        this._bindEvents();
        this._setInputEnabled(false);
        this._showInputArea(false);
        this.loadConversations();
    }

    _bindEvents() {
        this.$sendBtn.on('click', () => {
            if (this.isStreaming) {
                this.stopStreaming();
            } else {
                this.sendMessage();
            }
        });
        this.$input.on('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                if (!this.isStreaming) this.sendMessage();
            }
        });

        // Auto-resize textarea
        this.$input.on('input', function () {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 120) + 'px';
        });

        // New Chat button opens the project/scope picker modal
        $('#btn-new-chat').on('click', () => this._openNewChatModal());

        // Scope dropdown toggles project/account picker visibility
        $('#nc-scope').on('change', () => {
            const scope = $('#nc-scope').val();
            if (scope === 'org') {
                $('#nc-project-group').hide();
                $('#nc-account-group').hide();
            } else if (scope === 'account') {
                $('#nc-project-group').show();
                $('#nc-account-group').show();
                this._populateAccountDropdown();
            } else {
                // project scope
                $('#nc-project-group').show();
                $('#nc-account-group').hide();
            }
        });

        // Project dropdown repopulates accounts when scope is "account"
        $('#nc-project').on('change', () => {
            if ($('#nc-scope').val() === 'account') {
                this._populateAccountDropdown();
            }
        });

        // Start Chat button in modal
        $('#nc-start-chat').on('click', () => this._startChatFromModal());

        // Delete conversation confirm button
        $('#confirmDeleteConversationBtn').on('click', () => this._confirmDeleteConversation());
    }

    // ── API Methods ─────────────────────────────────────

    async apiCall(method, url, body = null) {
        const opts = {
            method,
            headers: { 'Content-Type': 'application/json' },
        };
        if (body) opts.body = JSON.stringify(body);
        const resp = await fetch(url, opts);
        if (resp.status === 401) {
            window.location.href = '/login';
            return null;
        }
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            const detail = err.detail;
            const msg = typeof detail === 'string' ? detail : JSON.stringify(detail) || 'Request failed';
            throw new Error(msg);
        }
        return resp.json();
    }

    // ── New Chat Modal Flow ──────────────────────────────

    async _openNewChatModal() {
        if (this.isStreaming) return;

        // Show modal immediately with loading state
        $('#new-chat-loading').show();
        $('#new-chat-form').hide();
        $('#nc-no-projects').hide();
        $('#nc-start-chat').prop('disabled', true);
        $('#new-chat-modal').modal('show');

        try {
            const data = await this.apiCall('GET', '/api/v1/analyst/accessible-projects');
            this.accessibleProjects = data.projects || [];
            const hasOrgAccess = data.org_analyst_access || false;

            // Populate project dropdown
            const $projSelect = $('#nc-project');
            $projSelect.empty().append('<option value="">-- Select a project --</option>');

            // Show/hide org scope option based on access
            const $orgOption = $('#nc-scope option[value="org"]');
            if (hasOrgAccess) {
                if (!$orgOption.length) {
                    $('#nc-scope').append('<option value="org">Organization (all projects)</option>');
                }
            } else {
                $orgOption.remove();
            }

            if (this.accessibleProjects.length === 0 && !hasOrgAccess) {
                $('#new-chat-loading').hide();
                $('#new-chat-form').show();
                $('#nc-no-projects').show();
                return;
            }

            for (const proj of this.accessibleProjects) {
                const accountCount = (proj.cloud_accounts || []).length;
                const label = `${proj.project_name} (${accountCount} account${accountCount !== 1 ? 's' : ''})`;
                $projSelect.append(`<option value="${this._escapeAttr(proj.project_name)}">${this._escapeHtml(label)}</option>`);
            }

            // Reset scope to project, show project group, hide account group
            $('#nc-scope').val('project');
            $('#nc-project-group').show();
            $('#nc-account-group').hide();
            $('#nc-start-chat').prop('disabled', false);

            $('#new-chat-loading').hide();
            $('#new-chat-form').show();
        } catch (e) {
            $('#new-chat-loading').hide();
            $('#new-chat-modal').modal('hide');
            this._showToast('Failed to load projects: ' + e.message, 'error');
        }
    }

    _populateAccountDropdown() {
        const projectName = $('#nc-project').val();
        const $acctSelect = $('#nc-account');
        $acctSelect.empty().append('<option value="">-- Select an account --</option>');

        const proj = this.accessibleProjects.find(p => p.project_name === projectName);
        if (!proj) return;

        for (const acct of proj.cloud_accounts || []) {
            const label = acct.alias
                ? `${acct.alias} (${acct.account_id} - ${(acct.cloud_platform || '').toUpperCase()})`
                : `${acct.account_id} (${(acct.cloud_platform || '').toUpperCase()})`;
            $acctSelect.append(
                `<option value="${this._escapeAttr(acct.account_id)}" data-platform="${this._escapeAttr(acct.cloud_platform || '')}">${this._escapeHtml(label)}</option>`
            );
        }
    }

    async _startChatFromModal() {
        const scope = $('#nc-scope').val();
        const projectName = scope === 'org' ? null : $('#nc-project').val();

        if (scope !== 'org' && !projectName) {
            this._showToast('Please select a project', 'error');
            return;
        }

        let accountId = null;
        let cloudPlatform = null;

        if (scope === 'account') {
            const $acctOption = $('#nc-account option:selected');
            accountId = $('#nc-account').val();
            if (!accountId) {
                this._showToast('Please select a cloud account', 'error');
                return;
            }
            cloudPlatform = $acctOption.data('platform') || null;
        }

        $('#nc-start-chat').prop('disabled', true).html('<i class="fas fa-spinner fa-spin mr-1"></i> Creating...');

        try {
            const body = { scope };
            if (projectName) body.project_name = projectName;
            if (cloudPlatform) body.cloud_platform = cloudPlatform;
            if (accountId) body.account_id = accountId;

            const data = await this.apiCall('POST', '/api/v1/analyst/conversations', body);

            $('#new-chat-modal').modal('hide');
            this.currentConversationId = data.conversation_id;
            this.$chatTitle.text('New Conversation');
            this._setScopeBadge(projectName, scope, accountId);
            this.$messages.empty();
            this.$welcomeScreen.hide();
            this.setPodStatus('starting');
            this._showInputArea(true);
            this._setInputEnabled(false);
            this._showWarmingOverlay();
            this.loadConversations();

            this._pollPodStatus(data.conversation_id);
        } catch (e) {
            this._showToast('Failed to create conversation: ' + e.message, 'error');
        } finally {
            $('#nc-start-chat').prop('disabled', false).html('<i class="fas fa-comments mr-1"></i> Start Chat');
        }
    }

    // ── Conversations ────────────────────────────────────

    async loadConversations() {
        try {
            const data = await this.apiCall('GET', '/api/v1/analyst/conversations');
            this.renderConversationList(data.conversations || []);
        } catch (e) {
            console.error('Failed to load conversations:', e);
        }
    }

    async _pollPodStatus(conversationId) {
        for (let i = 0; i < 40; i++) {
            try {
                const data = await this.apiCall(
                    'GET',
                    `/api/v1/analyst/conversations/${conversationId}/status`
                );
                this.setPodStatus(data.status);
                if (data.status === 'ready') {
                    this._hideWarmingOverlay();
                    this._setInputEnabled(true);
                    this.$input.focus();
                    return;
                }
                if (data.status === 'error' || data.status === 'terminated') {
                    this._hideWarmingOverlay();
                    if (data.status === 'error') {
                        this._appendSystemMessage(`Session failed: ${data.error || 'Unknown error'}`);
                    } else {
                        this._appendSystemMessage('Session has ended. Start a new chat to continue.');
                    }
                    return;
                }
            } catch (e) {
                console.error('Pod status poll error:', e);
            }
            await new Promise(r => setTimeout(r, 3000));
        }
        // Timed out waiting for pod
        this._hideWarmingOverlay();
        this._appendSystemMessage('Session took too long to start. Please try again.');
    }

    async loadConversation(conversationId) {
        if (this.isStreaming) return;

        try {
            const data = await this.apiCall(
                'GET',
                `/api/v1/analyst/conversations/${conversationId}`
            );
            this.currentConversationId = conversationId;
            this.$chatTitle.text(data.title || 'Conversation');
            this._setScopeBadge(data.project_name, data.scope, data.account_id);
            this.$welcomeScreen.hide();
            this._showInputArea(true);
            this._setInputEnabled(false);
            this.$messages.empty();

            // Render existing messages (skip system prompt messages)
            for (const msg of data.messages || []) {
                if (msg.role === 'user') {
                    this._appendUserMessage(msg.content);
                } else if (msg.role === 'assistant') {
                    if (msg.tool_calls) {
                        for (const tc of msg.tool_calls) {
                            this._appendToolCallCard(tc.name, tc.arguments, tc.id);
                        }
                    }
                    if (msg.content && msg.content.trim()) {
                        this._appendAssistantMessage(msg.content);
                    }
                } else if (msg.role === 'tool') {
                    this._updateToolCallResult(msg.tool_call_id, msg.name, msg.content);
                }
            }

            this.scrollToBottom();
            this.highlightActiveConversation(conversationId);

            // Check pod status — only enable input if pod is ready
            const status = await this.apiCall(
                'GET',
                `/api/v1/analyst/conversations/${conversationId}/status`
            );
            this.setPodStatus(status.status);
            if (status.status === 'ready') {
                this._setInputEnabled(true);
                this.$input.focus();
            } else if (status.status === 'starting') {
                this._showWarmingOverlay();
                this._pollPodStatus(conversationId);
            } else if (status.status === 'terminated' || status.status === 'error') {
                this._showRestartBanner(conversationId);
            }
        } catch (e) {
            this._showToast('Failed to load conversation: ' + e.message, 'error');
        }
    }

    deleteConversation(conversationId) {
        this._pendingDeleteConversationId = conversationId;
        $('#deleteConversationModal').modal('show');
    }

    async _confirmDeleteConversation() {
        const conversationId = this._pendingDeleteConversationId;
        if (!conversationId) return;
        this._pendingDeleteConversationId = null;
        $('#deleteConversationModal').modal('hide');

        try {
            await this.apiCall('DELETE', `/api/v1/analyst/conversations/${conversationId}`);
            if (this.currentConversationId === conversationId) {
                this.currentConversationId = null;
                this.$messages.empty();
                this.$chatTitle.text('Cloud Analyst');
                this.$scopeBadge.hide();
                this.$welcomeScreen.show();
                this.setPodStatus('');
                this._setInputEnabled(false);
                this._showInputArea(false);
            }
            this.loadConversations();
        } catch (e) {
            this._showToast('Failed to delete conversation: ' + e.message, 'error');
        }
    }

    stopStreaming() {
        if (this.abortController) {
            this.abortController.abort();
            this.abortController = null;
        }
    }

    _setSendButtonMode(mode) {
        if (mode === 'stop') {
            this.$sendBtn
                .removeClass('btn-primary').addClass('btn-danger')
                .html('<i class="fas fa-stop"></i>')
                .prop('disabled', false)
                .attr('title', 'Stop generating');
        } else {
            this.$sendBtn
                .removeClass('btn-danger').addClass('btn-primary')
                .html('<i class="fas fa-paper-plane"></i>')
                .prop('disabled', false)
                .attr('title', 'Send message');
        }
    }

    async sendMessage() {
        const message = this.$input.val().trim();
        if (!message || this.isStreaming) return;

        if (!this.currentConversationId) {
            this._showToast('Please start a new chat first using the New Chat button.', 'info');
            return;
        }

        this.isStreaming = true;
        this.abortController = new AbortController();
        this._setSendButtonMode('stop');
        this.$input.val('').trigger('input');
        this.$welcomeScreen.hide();

        this._appendUserMessage(message);
        this._showTypingIndicator();
        this.scrollToBottom();

        try {
            const response = await fetch(
                `/api/v1/analyst/conversations/${this.currentConversationId}/messages`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message }),
                    signal: this.abortController.signal,
                }
            );

            if (response.status === 401) {
                window.location.href = '/login';
                return;
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let currentAssistantEl = null;
            let assistantContent = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop(); // Keep incomplete line in buffer

                let eventType = '';
                for (const line of lines) {
                    if (line.startsWith('event: ')) {
                        eventType = line.slice(7).trim();
                    } else if (line.startsWith('data: ')) {
                        const data = JSON.parse(line.slice(6));
                        this._hideTypingIndicator();

                        switch (eventType) {
                            case 'pod_status':
                                this.setPodStatus(data.status);
                                if (data.status === 'starting') {
                                    this._showTypingIndicator();
                                }
                                break;

                            case 'tool_start':
                                // Finalize any current assistant bubble before tool card
                                if (currentAssistantEl && !assistantContent.trim()) {
                                    currentAssistantEl.remove();
                                    currentAssistantEl = null;
                                }
                                currentAssistantEl = null;
                                assistantContent = '';
                                this._appendToolCallCard(data.tool, data.arguments, data.id);
                                this.scrollToBottom();
                                break;

                            case 'tool_result':
                                this._updateToolCallResult(data.id, data.tool, data.result);
                                this.scrollToBottom();
                                break;

                            case 'token':
                                if (!currentAssistantEl) {
                                    currentAssistantEl = this._createAssistantBubble();
                                    currentAssistantEl.addClass('streaming');
                                    assistantContent = '';
                                }
                                assistantContent += data.content || '';
                                currentAssistantEl.find('.message-content').html(
                                    marked.parse(assistantContent)
                                );
                                this._cleanEmptyCodeBlocks(currentAssistantEl);
                                this.scrollToBottom();
                                break;

                            case 'content_replace':
                                // Model emitted tool call as text — replace with cleaned content
                                if (currentAssistantEl) {
                                    currentAssistantEl.removeClass('streaming');
                                    assistantContent = data.content || '';
                                    if (assistantContent.trim()) {
                                        currentAssistantEl.find('.message-content').html(
                                            marked.parse(assistantContent)
                                        );
                                        this._cleanEmptyCodeBlocks(currentAssistantEl);
                                    } else {
                                        currentAssistantEl.remove();
                                        currentAssistantEl = null;
                                    }
                                }
                                break;

                            case 'done':
                                // Remove streaming class and empty bubbles
                                if (currentAssistantEl) {
                                    currentAssistantEl.removeClass('streaming');
                                    if (!assistantContent.trim()) {
                                        currentAssistantEl.remove();
                                    } else {
                                        this._cleanEmptyCodeBlocks(currentAssistantEl);
                                    }
                                }
                                currentAssistantEl = null;
                                assistantContent = '';
                                break;

                            case 'error':
                                this._appendSystemMessage(data.message || 'An error occurred');
                                break;
                        }
                    }
                }
            }
        } catch (e) {
            this._hideTypingIndicator();
            if (e.name === 'AbortError') {
                // User clicked stop — add a note
                this._appendSystemMessage('Response stopped by user.');
            } else {
                this._appendSystemMessage('Connection error: ' + e.message);
            }
        } finally {
            this.isStreaming = false;
            this.abortController = null;
            this._setSendButtonMode('send');
            this.$input.focus();
            this.loadConversations(); // Refresh list (title may have changed)
        }
    }

    // ── DOM Rendering ───────────────────────────────────

    renderConversationList(conversations) {
        this.$sidebar.empty();
        if (conversations.length === 0) {
            this.$sidebar.html(
                '<div class="text-center text-muted p-3" style="font-size:0.85rem;">No conversations yet</div>'
            );
            return;
        }

        // Sort by updated_at descending
        conversations.sort((a, b) => {
            const da = a.updated_at ? new Date(a.updated_at) : new Date(0);
            const db = b.updated_at ? new Date(b.updated_at) : new Date(0);
            return db - da;
        });

        for (const conv of conversations) {
            const scopeLabel = conv.scope === 'account'
                ? (conv.cloud_platform || '').toUpperCase()
                : conv.scope === 'project' ? 'Project' : 'Org';
            const projectLabel = conv.scope === 'org'
                ? 'All Projects'
                : (conv.project_name || '');
            const $item = $(`
                <div class="conversation-item ${conv.conversation_id === this.currentConversationId ? 'active' : ''}"
                     data-id="${conv.conversation_id}">
                    <div class="conv-info">
                        <div class="conv-title">${this._escapeHtml(conv.title)}</div>
                        <div class="conv-meta">
                            <span class="conv-project">${this._escapeHtml(projectLabel)}</span>
                            <span class="conv-scope-tag">${scopeLabel}</span>
                        </div>
                    </div>
                    <button class="btn-delete-conv" title="Delete">
                        <i class="fas fa-trash-alt"></i>
                    </button>
                </div>
            `);

            $item.on('click', (e) => {
                if ($(e.target).closest('.btn-delete-conv').length) return;
                this.loadConversation(conv.conversation_id);
            });

            $item.find('.btn-delete-conv').on('click', (e) => {
                e.stopPropagation();
                this.deleteConversation(conv.conversation_id);
            });

            this.$sidebar.append($item);
        }
    }

    highlightActiveConversation(id) {
        this.$sidebar.find('.conversation-item').removeClass('active');
        this.$sidebar.find(`[data-id="${id}"]`).addClass('active');
    }

    _setScopeBadge(projectName, scope, accountId) {
        let label;
        if (scope === 'org') {
            label = 'Organization (all projects)';
        } else if (scope === 'account' && accountId) {
            label = `${projectName} / ${accountId}`;
        } else if (scope === 'project') {
            label = `${projectName} (all accounts)`;
        } else {
            label = projectName || 'Unknown';
        }
        this.$scopeBadge.text(label).show();
    }

    _appendUserMessage(content) {
        const $msg = $(`
            <div class="chat-message user">
                <div class="message-content">${this._escapeHtml(content)}</div>
            </div>
        `);
        this.$messages.append($msg);
    }

    _appendAssistantMessage(content) {
        const $msg = $(`
            <div class="chat-message assistant">
                <div class="message-content">${marked.parse(content)}</div>
            </div>
        `);
        this._cleanEmptyCodeBlocks($msg);
        this.$messages.append($msg);
    }

    _createAssistantBubble() {
        const $msg = $(`
            <div class="chat-message assistant">
                <div class="message-content"></div>
            </div>
        `);
        this.$messages.append($msg);
        return $msg;
    }

    _appendSystemMessage(content) {
        const $msg = $(`
            <div class="chat-message assistant" style="border-color: #f5c6cb; background: #fff5f5;">
                <div class="message-content"><i class="fas fa-exclamation-triangle text-danger mr-1"></i> ${this._escapeHtml(content)}</div>
            </div>
        `);
        this.$messages.append($msg);
        this.scrollToBottom();
    }

    _appendToolCallCard(toolName, args, toolCallId) {
        const iconMap = {
            list_available_accounts: 'fa-cloud',
            connect_account: 'fa-plug',
            search_tables: 'fa-search',
            get_table_schema: 'fa-columns',
            run_query: 'fa-database',
            list_cloud_accounts: 'fa-cloud',
            list_project_workspaces: 'fa-layer-group',
            get_request_history: 'fa-history',
            get_request_details: 'fa-info-circle',
            get_request_logs: 'fa-file-alt',
            get_project_members: 'fa-users',
            get_audit_log: 'fa-clipboard-list',
            list_benchmarks: 'fa-shield-alt',
            run_benchmark: 'fa-shield-alt',
        };
        const icon = iconMap[toolName] || 'fa-cog';

        let argsSummary = '';
        if (args && typeof args === 'object') {
            if (args.sql) {
                argsSummary = `<div class="sql-block">${this._escapeHtml(args.sql)}</div>`;
            } else if (args.keywords) {
                argsSummary = `Keywords: ${args.keywords.join(', ')}`;
            } else if (args.table_name) {
                argsSummary = `Table: ${args.table_name}`;
            } else if (args.platform && args.account_id) {
                argsSummary = `${(args.platform || '').toUpperCase()} / ${args.account_id}`;
            } else if (args.benchmark) {
                argsSummary = `Benchmark: ${args.benchmark}`;
            } else if (args.request_id) {
                argsSummary = `Request: ${args.request_id}`;
            } else if (args.project_name) {
                argsSummary = `Project: ${args.project_name}`;
            }
            if (args.explanation) {
                argsSummary += `<div class="text-muted mt-1">${this._escapeHtml(args.explanation)}</div>`;
            }
        }

        const $card = $(`
            <div class="tool-call-card" data-tool-id="${toolCallId}">
                <div class="tool-call-header">
                    <i class="fas ${icon} tool-icon"></i>
                    <span class="tool-name">${toolName}</span>
                    <span class="tool-status running">
                        <i class="fas fa-spinner fa-spin"></i> Running
                    </span>
                </div>
                <div class="tool-call-body">
                    ${argsSummary}
                    <div class="tool-result-area"></div>
                </div>
            </div>
        `);

        $card.find('.tool-call-header').on('click', function () {
            $(this).next('.tool-call-body').toggleClass('show');
        });

        this.$messages.append($card);
    }

    _updateToolCallResult(toolCallId, toolName, result) {
        const $card = this.$messages.find(`[data-tool-id="${toolCallId}"]`);
        if (!$card.length) return;

        // Parse result if string
        let resultData = result;
        if (typeof result === 'string') {
            try { resultData = JSON.parse(result); } catch (e) { /* keep as string */ }
        }

        const $status = $card.find('.tool-status');
        const $resultArea = $card.find('.tool-result-area');

        if (resultData && resultData.error) {
            $status.removeClass('running').addClass('error')
                .html('<i class="fas fa-times"></i> Error');
            $resultArea.html(`<div class="text-danger">${this._escapeHtml(resultData.error)}</div>`);
            $card.addClass('has-error');
        } else {
            $status.removeClass('running').addClass('done')
                .html('<i class="fas fa-check"></i> Done');

            let summary = '';
            if (resultData && resultData.status === 'connected') {
                summary = `Connected ${resultData.account_id} (${resultData.total_connected} total)`;
            } else if (resultData && resultData.status === 'already_connected') {
                summary = `Already connected: ${resultData.account_id}`;
            } else if (resultData && resultData.row_count !== undefined) {
                summary = `${resultData.row_count} rows returned`;
                if (resultData.truncated) summary += ' (truncated)';
            } else if (resultData && resultData.tables) {
                summary = `${resultData.tables.length} tables found`;
            } else if (resultData && resultData.columns) {
                const colCount = Object.keys(resultData.columns).length;
                summary = `${colCount} columns`;
            } else if (resultData && resultData.projects) {
                summary = `${resultData.projects.length} projects`;
            } else if (resultData && resultData.accounts) {
                summary = `${resultData.accounts.length} accounts`;
            } else if (resultData && resultData.requests) {
                summary = `${resultData.requests.length} requests`;
            } else if (resultData && resultData.benchmarks) {
                summary = `${resultData.benchmarks.length} benchmarks available`;
            } else if (resultData && resultData.summary) {
                const s = resultData.summary;
                summary = `${s.ok || 0} passed, ${s.alarm || 0} failed`;
            } else if (resultData && resultData.members) {
                summary = `${resultData.members.length} members`;
            } else if (resultData && resultData.events) {
                summary = `${resultData.count || resultData.events.length} events`;
            } else if (resultData && resultData.workspaces) {
                summary = `${resultData.workspaces.length} workspaces`;
            } else if (resultData && resultData.logs) {
                const lines = resultData.logs.split('\n').length;
                summary = `${lines} lines${resultData.truncated ? ' (truncated)' : ''}`;
            }

            if (summary) {
                $resultArea.html(`<div class="result-summary">${summary}</div>`);
            }
        }

        // Auto-expand errors so users see what went wrong.
        // Success cards stay collapsed — the header badge is enough.
        if (resultData && resultData.error) {
            $card.find('.tool-call-body').addClass('show');
        }
    }

    _showTypingIndicator() {
        if (this.$messages.find('.typing-indicator').length) return;
        this.$messages.append(`
            <div class="typing-indicator">
                <span></span><span></span><span></span>
            </div>
        `);
        this.scrollToBottom();
    }

    _hideTypingIndicator() {
        this.$messages.find('.typing-indicator').remove();
    }

    setPodStatus(status) {
        if (!status) {
            this.$podStatus.hide();
            return;
        }
        const labels = {
            starting: '<i class="fas fa-spinner fa-spin"></i> Warming up',
            ready: '<i class="fas fa-check-circle"></i> Ready',
            error: '<i class="fas fa-exclamation-circle"></i> Error',
            terminated: '<i class="fas fa-stop-circle"></i> Ended',
        };
        this.$podStatus
            .html(labels[status] || status)
            .removeClass('starting ready error terminated')
            .addClass(status)
            .show();
    }

    _setInputEnabled(enabled) {
        this.$input.prop('disabled', !enabled);
        this.$sendBtn.prop('disabled', !enabled);
        if (enabled) {
            this.$input.attr('placeholder', 'Ask about your cloud infrastructure...');
        } else {
            this.$input.attr('placeholder', 'Waiting for session...');
        }
    }

    _showInputArea(visible) {
        if (visible) {
            $('.chat-input-area').show();
        } else {
            $('.chat-input-area').hide();
        }
    }

    _cleanEmptyCodeBlocks($el) {
        // Remove empty <pre> blocks that render as meaningless black boxes
        if (!$el) return;
        $el.find('pre').each(function () {
            if (!$(this).text().trim()) $(this).remove();
        });
    }

    scrollToBottom() {
        const el = this.$messages[0];
        if (el) el.scrollTop = el.scrollHeight;
    }

    _escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    _escapeAttr(text) {
        if (!text) return '';
        return text.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    _showRestartBanner(conversationId) {
        this._setInputEnabled(false);
        this.$messages.find('.restart-banner').remove();
        this.$messages.append(`
            <div class="restart-banner">
                <div class="restart-content">
                    <i class="fas fa-stop-circle text-muted mb-2" style="font-size:1.5rem;"></i>
                    <div>Session has ended.</div>
                    <button class="btn btn-sm btn-primary mt-2 btn-restart-session">
                        <i class="fas fa-redo mr-1"></i> Restart Session
                    </button>
                </div>
            </div>
        `);
        this.$messages.find('.btn-restart-session').on('click', () => {
            this.restartSession(conversationId);
        });
        this.scrollToBottom();
    }

    async restartSession(conversationId) {
        const $btn = this.$messages.find('.btn-restart-session');
        $btn.prop('disabled', true).html('<i class="fas fa-spinner fa-spin mr-1"></i> Restarting...');

        try {
            await this.apiCall(
                'POST',
                `/api/v1/analyst/conversations/${conversationId}/restart`
            );
            this.$messages.find('.restart-banner').remove();
            this.setPodStatus('starting');
            this._showWarmingOverlay();
            this._pollPodStatus(conversationId);
        } catch (e) {
            $btn.prop('disabled', false).html('<i class="fas fa-redo mr-1"></i> Restart Session');
            this._showToast('Failed to restart session: ' + e.message, 'error');
        }
    }

    _showWarmingOverlay() {
        if (this.$messages.find('.warming-overlay').length) return;
        this.$messages.append(`
            <div class="warming-overlay">
                <div class="warming-content">
                    <i class="fas fa-spinner fa-spin fa-2x mb-3"></i>
                    <div class="warming-text">Setting up your analysis session...</div>
                    <div class="text-muted mt-1" style="font-size:0.85rem;">
                        Installing query engine plugins — cloud accounts will be connected on demand
                    </div>
                </div>
            </div>
        `);
        this.scrollToBottom();
    }

    _hideWarmingOverlay() {
        this.$messages.find('.warming-overlay').remove();
    }

    _showToast(message, type = 'info') {
        if (window.Swal) {
            Swal.fire({
                toast: true,
                position: 'top-end',
                icon: type === 'error' ? 'error' : 'info',
                title: message,
                showConfirmButton: false,
                showCloseButton: true,
            });
        } else {
            alert(message);
        }
    }
}
