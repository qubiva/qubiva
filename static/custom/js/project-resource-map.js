// project-resource-map.js
class ProjectResourceMap {
    constructor() {
        this.itemsPerPage = 30;
        this.paginatedData = {};
        this.currentData = null;
        this.init();
    }

    async init() {
        try {
            const resourceMap = document.querySelector('.projects-list');
            const taskList = document.querySelector('.task-list');
            
            if (resourceMap) {
                resourceMap.innerHTML = '<div class="text-center w-100 my-5">Loading...</div>';
            }
            if (taskList) {
                taskList.innerHTML = '<div class="text-center w-100 my-5">Loading...</div>';
            }
            const projectName = getProjectName();
            const response = await fetch(`/api/v1/projects/${projectName}/stats`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username: getCurrentUser() })
            });

            if (!response.ok) throw new Error('Failed to fetch stats');
            
            const data = await response.json();
            this.currentData = data.stats;
            this.renderDashboard(this.currentData);
            this.setupEventListeners();
        } catch (error) {
            console.error('Failed to load dashboard:', error);
            this.showError('Failed to load project dashboard data');
        }
    }

    // In renderDashboard function, modify it to:
    // New code to add
    renderDashboard(stats) {
        const hasResources = stats.resources.cloud_accounts?.length > 0 ||
                            stats.resources.workspaces?.length > 0 ||
                            stats.resources.github_repos?.length > 0 ||
                            stats.resources.credentials?.length > 0;
        const hasRunners = stats.runners?.recent?.length > 0 ||
                           Object.values(stats.runners?.pool || {}).some(p => p.enabled);

        // Always render header/description
        this.renderProjectHeader(stats.project_info);

        const resourceMap = document.querySelector('.projects-list');
        if (!hasResources && !hasRunners && resourceMap) {
            resourceMap.innerHTML = `
                <div class="empty-state">
                    <p>No resources available in this project.</p>
                </div>
            `;
        } else {
            this.renderResources(stats.resources, stats.runners);
        }

        // Always render tasks
        this.renderTaskSummary(stats.tasks);
    }

    renderProjectHeader(projectInfo) {
        const header = document.querySelector('.projects-column h2');
        if (!header) return;
        const description = projectInfo.description || 'No description provided';
        header.insertAdjacentHTML('afterend', `
            <div class="project-description${!projectInfo.description ? ' empty' : ''}">
                <p>${description}</p>
            </div>
            <div class="resource-group">
                <h3>
                    <i class="fas fa-user-shield"></i>
                    My roles
                </h3>
                <div class="role-badges">
                    ${projectInfo.user_roles.map(role => 
                        `<span class="role-badge ${role}">${this.formatRoleName(role)}</span>`
                    ).join('')}
                </div>
            </div>
        `);
    }

    renderResources(resources, runners) {
        const resourceMap = document.querySelector('.projects-list');
        if (!resourceMap) return;

        resourceMap.innerHTML = `
            ${this.renderRunnersSection(runners)}
            ${this.renderCloudCredentialsSection(resources.credentials)}
            ${this.renderCloudAccountsSection(resources.cloud_accounts)}
            ${this.renderWorkspacesSection(resources.workspaces)}
            ${this.renderGitHubReposSection(resources.github_repos)}
        `;
    }

    renderCloudCredentialsSection(credentials) {
        if (!credentials?.length) return '';

        const projectName = getProjectName();
        
        // Group credentials by platform and count them
        const credentialCounts = credentials.reduce((counts, credential) => {
            let platform = 'Unknown';
            
            if (credential.credential_type === 'external_certificate_authority' || 
                credential.credential_type === 'key_pair') {
                platform = 'AWS';
            } else if (credential.credential_type === 'azure_service_principal') {
                platform = 'Azure';
            } else if (credential.credential_type === 'gcp_service_account') {
                platform = 'GCP';
            }
            
            counts[platform] = (counts[platform] || 0) + 1;
            return counts;
        }, {});

        // Sort platforms for consistent display
        const sortedPlatforms = Object.keys(credentialCounts).sort();

        return `
            <div class="resource-group">
                <h3>
                    <i class="fas fa-key"></i>
                    <a href="/dashboard/projects/${projectName}/credentials">Cloud Credentials</a>
                    <span class="count">${credentials.length}</span>
                </h3>
                <div class="resource-list">
                    ${sortedPlatforms.map(platform => `
                        <div class="resource-item credential-platform">
                            <i class="fas fa-cloud"></i>
                            <span class="platform-name">${platform}</span>
                            <span class="count">${credentialCounts[platform]}</span>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    renderCloudAccountsSection(accounts) {
        if (!accounts?.length) return '';
    
        const projectName = getProjectName();
        const paginatedAccounts = this.paginateItems(accounts, 'cloud_accounts');
    
        return `
            <div class="resource-group">
                <h3>
                    <i class="fas fa-cloud"></i>
                    <a href="/dashboard/projects/${projectName}/cloud_accounts">Cloud Accounts</a>
                    <span class="count">${accounts.length}</span>
                </h3>
                ${paginatedAccounts.map(account => `
                    <div class="cloud-account">
                        <div class="account-main">
                            <i class="fas fa-cloud"></i>
                            <span class="platform-tag">${account.platform.toUpperCase()}</span>
                            <a href="/dashboard/projects/${projectName}/cloud_accounts/${account.platform}/${account.account_id}">${account.account_id}</a>
                        </div>
                        <div class="account-metrics">
                            <a href="/dashboard/projects/${projectName}/cloud_accounts/${account.platform}/${account.account_id}/alerts"
                               class="metric-item ${account.metrics.alerts.open_count > 0 ? 'has-alerts' : ''}">
                                <i class="fas fa-bell"></i>
                                <span>Alerts</span>
                                <span class="count">${account.metrics.alerts.open_count}</span>
                            </a>
                            <a href="/dashboard/projects/${projectName}/cloud_accounts/${account.platform}/${account.account_id}/scheduled_runs"
                               class="metric-item">
                                <i class="fas fa-clock"></i>
                                <span>Scheduled Runs</span>
                                <div class="metric-info">
                                    <span class="run-status">
                                        <i class="fas fa-check-circle"></i>
                                        ${account.metrics.scheduled_runs.active_count} enabled
                                    </span>
                                    <span class="run-status">
                                        <i class="fas fa-times-circle"></i>
                                        ${account.metrics.scheduled_runs.total_count - account.metrics.scheduled_runs.active_count} disabled
                                    </span>
                                </div>
                            </a>
                        </div>
                    </div>
                `).join('')}
                ${this.renderPagination(accounts.length, 'cloud_accounts')}
            </div>
        `;
    }

    renderWorkspacesSection(workspaces) {
        if (!workspaces?.length) return '';

        const projectName = getProjectName();
        const paginatedWorkspaces = this.paginateItems(workspaces, 'workspaces');

        return `
            <div class="resource-group" data-section="workspaces">
                <h3>
                    <i class="fas fa-folder"></i>
                    <a href="/dashboard/projects/${projectName}/workspaces">Workspaces</a>
                    <span class="count">${workspaces.length}</span>
                </h3>
                <div class="resource-list">
                    ${paginatedWorkspaces.map(workspace => `
                        <a href="/dashboard/projects/${projectName}/workspaces/${workspace.name}" 
                           class="resource-item workspace">
                            <i class="fas fa-folder"></i>
                            <span>${workspace.name}</span>
                        </a>
                    `).join('')}
                </div>
                ${this.renderPagination(workspaces.length, 'workspaces')}
            </div>
        `;
    }

    renderGitHubReposSection(repos) {
        if (!repos?.length) return '';
        const projectName = getProjectName();
        const paginatedRepos = this.paginateItems(repos, 'github_repos');

        return `
            <div class="resource-group" data-section="github_repos">
                <h3>
                    <i class="fab fa-github"></i>
                    <a href="/dashboard/projects/${projectName}/git_repos">Linked Git Repositories</a>
                    <span class="count">${repos.length}</span>
                </h3>
                <div class="resource-list">
                    ${paginatedRepos.map(repo => `
                        <a href="${repo.url}" 
                           target="_blank" 
                           rel="noopener noreferrer" 
                           class="resource-item github-repo">
                            <span>
                                <i class="fab fa-github"></i>
                                ${repo.name.split('~')[1] || repo.name}
                            </span>
                            <i class="fas fa-external-link-alt external"></i>
                        </a>
                    `).join('')}
                </div>
                ${this.renderPagination(repos.length, 'github_repos')}
            </div>
        `;
    }

    renderRunnersSection(runners) {
        if (!runners) return '';

        const pool = runners.pool || {};
        const hasPool = Object.values(pool).some(p => p.enabled);
        const hasRecent = runners.recent?.length > 0;

        if (!hasPool && !hasRecent) return '';

        const projectName = getProjectName();

        // Pool status badges
        const poolStatusHtml = hasPool ? Object.entries(pool)
            .filter(([, p]) => p.enabled)
            .map(([type, p]) => {
                const poolMeta = {
                    terraform:  { label: 'IaC',       icon: 'fa-cube' },
                    discovery:  { label: 'Discovery', icon: 'fa-database' },
                    analyst:    { label: 'Analyst',   icon: 'fa-robot' },
                };
                const meta = poolMeta[type] || { label: type, icon: 'fa-server' };
                const readyCls = p.ready > 0 ? 'pool-ready' : 'pool-empty';
                const parts = [];
                if (p.ready > 0) parts.push(`${p.ready} ready`);
                if (p.busy > 0) parts.push(`${p.busy} busy`);
                if (p.starting > 0) parts.push(`${p.starting} starting`);
                if (parts.length === 0) parts.push('0 ready');

                const mode = p.execution_mode || 'pool_with_fallback';
                let modeHtml = '';
                if (mode === 'pool_only') {
                    modeHtml = `<span class="pool-mode pool-mode-only">pool only</span>`;
                } else {
                    modeHtml = `<span class="pool-mode pool-mode-auto">auto-scale</span>`;
                }

                return `
                    <div class="pool-status-item ${readyCls}">
                        <i class="fas ${meta.icon}"></i>
                        <span class="pool-label">${meta.label}</span>
                        <span class="pool-counts">${parts.join(' / ')}</span>
                        ${modeHtml}
                    </div>
                `;
            }).join('') : '';

        // Mode explanation banner (only when all enabled pools are pool_only and none are ready)
        const enabledPools = Object.entries(pool).filter(([, p]) => p.enabled);
        const allPoolOnly = enabledPools.length > 0 && enabledPools.every(([, p]) => p.execution_mode === 'pool_only');
        const noneReady = enabledPools.every(([, p]) => p.ready === 0 && p.starting === 0);
        const modeBannerHtml = allPoolOnly && noneReady
            ? `<div class="pool-mode-banner"><i class="fas fa-info-circle"></i> All runners are busy or offline. New jobs will wait until a runner becomes available.</div>`
            : '';

        // Recent runs
        const statusConfig = {
            'in progress':        { icon: 'fa-spinner fa-spin', cls: 'running' },
            'queued':             { icon: 'fa-clock',           cls: 'queued' },
            'initializing':       { icon: 'fa-cog fa-spin',     cls: 'running' },
            'completed':          { icon: 'fa-check-circle',    cls: 'completed' },
            'failed':             { icon: 'fa-times-circle',    cls: 'failed' },
            'execution failed':   { icon: 'fa-times-circle',    cls: 'failed' },
            'timed out':          { icon: 'fa-clock',           cls: 'failed' },
            'cancelled':          { icon: 'fa-ban',             cls: 'failed' },
            'benchmark succeeded':{ icon: 'fa-check-circle',    cls: 'completed' },
            'benchmark failed':   { icon: 'fa-times-circle',    cls: 'failed' },
        };

        const recentHtml = hasRecent ? runners.recent.map(run => {
            const cfg = statusConfig[run.state] || { icon: 'fa-circle', cls: '' };
            const typeLabel = run.type === 'terraform' ? 'IaC' : 'Discovery';
            const ago = this.timeAgo(run.requested_on);
            const workspace = run.workspace
                ? `<span class="runner-workspace">${run.workspace}</span>`
                : '';
            return `
                <a href="/dashboard/projects/${projectName}/requests/${run.type}/${run.request_id}"
                   class="resource-item runner-item ${cfg.cls}">
                    <i class="fas ${cfg.icon}"></i>
                    <span class="runner-type">${typeLabel}</span>
                    ${workspace}
                    <span class="runner-state">${run.state}</span>
                    <span class="runner-time">${ago}</span>
                </a>
            `;
        }).join('') : '';

        return `
            <div class="resource-group runners-section">
                <h3>
                    <i class="fas fa-play-circle"></i>
                    Runners
                    <span class="runners-refresh" id="runners-refresh" title="Refresh runner status">
                        <i class="fas fa-sync-alt"></i>
                    </span>
                </h3>
                ${poolStatusHtml ? `<div class="pool-status">${poolStatusHtml}</div>` : ''}
                ${modeBannerHtml}
                ${recentHtml ? `<div class="resource-list">${recentHtml}</div>` : ''}
            </div>
        `;
    }

    timeAgo(dateStr) {
        if (!dateStr) return '';
        try {
            const date = new Date(dateStr);
            const now = new Date();
            const seconds = Math.floor((now - date) / 1000);
            if (seconds < 60) return 'just now';
            const minutes = Math.floor(seconds / 60);
            if (minutes < 60) return `${minutes}m ago`;
            const hours = Math.floor(minutes / 60);
            if (hours < 24) return `${hours}h ago`;
            const days = Math.floor(hours / 24);
            if (days < 30) return `${days}d ago`;
            return date.toLocaleDateString();
        } catch {
            return '';
        }
    }

    renderTaskSummary(tasks) {
        const taskList = document.querySelector('.task-list');
        if (!taskList) return;

        const projectName = getProjectName();
        const statuses = ['todo', 'in_progress', 'blocked'];
        
        // Helper function to truncate text
        const truncateText = (text, maxLength = 55) => {
            return text.length > maxLength ? text.substring(0, maxLength) + '...' : text;
        };

        // Generate task items HTML for each status
        const taskItemsHtml = statuses.map(status => {
            const statusTasks = tasks[status] || [];
            return statusTasks.map(task => {
                const iconClass = {
                    'todo': 'fa-circle',
                    'in_progress': 'fa-clock',
                    'blocked': 'fa-exclamation-circle'
                }[status];

                const statusClass = status.replace('_', '-');
                const truncatedTitle = truncateText(task.title);

                return `
                    <a href="/dashboard/projects/${projectName}/tasks/${task.id}" 
                       class="task-item ${statusClass}">
                        <i class="fas ${iconClass}"></i>
                        <span>Task #${task.id} - ${truncatedTitle}</span>
                    </a>
                `;
            }).join('');
        }).join('');

        // If no tasks, show empty state
        taskList.innerHTML = taskItemsHtml || `
            <div class="text-center text-muted py-4">
                <i class="fas fa-tasks fa-2x mb-3 d-block"></i>No tasks assigned
            </div>
        `;
    }

    paginateItems(items, key) {
        if (!items?.length) return [];
        
        if (!this.paginatedData[key]) {
            this.paginatedData[key] = { currentPage: 1 };
        }
        
        const currentPage = this.paginatedData[key].currentPage;
        const startIndex = (currentPage - 1) * this.itemsPerPage;
        const endIndex = startIndex + this.itemsPerPage;
        
        return items.slice(startIndex, endIndex);
    }

    formatRoleName(role) {
        return role.split('_')
                  .map(word => word.charAt(0).toUpperCase() + word.slice(1))
                  .join(' ');
    }

    renderPagination(totalItems, key) {
        const totalPages = Math.ceil(totalItems / this.itemsPerPage);
        if (totalPages <= 1) return '';

        const currentPage = this.paginatedData[key]?.currentPage || 1;

        return `
            <div class="pagination">
                ${currentPage > 1 ? `
                    <button class="pagination-btn" data-page="${currentPage - 1}" data-key="${key}">
                        <i class="fas fa-chevron-left"></i> Previous
                    </button>
                ` : ''}
                <span class="pagination-info">
                    Page ${currentPage} of ${totalPages}
                </span>
                ${currentPage < totalPages ? `
                    <button class="pagination-btn" data-page="${currentPage + 1}" data-key="${key}">
                        Next <i class="fas fa-chevron-right"></i>
                    </button>
                ` : ''}
            </div>
        `;
    }

    async refreshRunners() {
        const btn = document.getElementById('runners-refresh');
        if (!btn || btn.classList.contains('refreshing')) return;

        btn.classList.add('refreshing');
        try {
            const projectName = getProjectName();
            const response = await fetch(`/api/v1/projects/${projectName}/stats`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username: getCurrentUser() })
            });
            if (!response.ok) throw new Error('Failed to fetch stats');
            const data = await response.json();
            this.currentData = data.stats;
            this.renderResources(this.currentData.resources, this.currentData.runners);
        } catch (error) {
            console.error('Failed to refresh runners:', error);
        } finally {
            const refreshBtn = document.getElementById('runners-refresh');
            if (refreshBtn) refreshBtn.classList.remove('refreshing');
        }
    }

    setupEventListeners() {
        document.addEventListener('click', e => {
            const refreshBtn = e.target.closest('#runners-refresh');
            if (refreshBtn) {
                this.refreshRunners();
                return;
            }

            const paginationBtn = e.target.closest('.pagination-btn');
            if (!paginationBtn) return;

            const key = paginationBtn.dataset.key;
            const page = parseInt(paginationBtn.dataset.page);

            if (!this.paginatedData[key]) {
                this.paginatedData[key] = {};
            }
            this.paginatedData[key].currentPage = page;

            this.renderResources(this.currentData.resources, this.currentData.runners);
        });
    }

    showError(message) {
        const resourceMap = document.querySelector('.resource-overview');
        if (resourceMap) {
            resourceMap.innerHTML = `
                <div class="error-message">
                    <i class="fas fa-exclamation-circle"></i>
                    ${message}
                </div>
            `;
        }
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    new ProjectResourceMap();
});