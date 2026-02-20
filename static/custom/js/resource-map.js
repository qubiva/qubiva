// resource-map.js
class ResourceMap {
    constructor() {
        this.itemsPerPage = 30;
        this.paginatedData = {};
        this.currentData = null;
        this.init();
    }

    async init() {
        try {
            const resourceMap = document.querySelector('#resourceMap');
            const taskList = document.querySelector('.task-list');
            
            if (resourceMap) {
                resourceMap.innerHTML = '<div class="text-center w-100 my-5">Loading...</div>';
            }
            if (taskList) {
                taskList.innerHTML = '<div class="text-center w-100 my-5">Loading...</div>';
            }
    
            const response = await fetch('/api/v1/stats/user', {
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
            this.showError('Failed to load dashboard data');
        }
    }

    renderDashboard(stats) {
        if (stats.projects?.length > 0) {
            const welcomeMessage = document.querySelector('.welcome-message');
            if (welcomeMessage) {
                welcomeMessage.style.display = 'none';
            }
        }

        this.renderQuickAccess(stats.projects);
        this.renderProjects(stats.projects);
    }

    setupEventListeners() {
        // Project expand/collapse - modified for accordion behavior
        document.querySelectorAll('.project-header').forEach(header => {
            header.addEventListener('click', (e) => {
                if (e.target.closest('a')) return;
                
                const projectItem = header.closest('.project-item');
                const isCurrentlyExpanded = projectItem.classList.contains('expanded');
                
                // Collapse all projects first
                document.querySelectorAll('.project-item').forEach(item => {
                    item.classList.remove('expanded');
                });
                
                // If the clicked project wasn't expanded, expand it
                if (!isCurrentlyExpanded) {
                    projectItem.classList.add('expanded');
                }
            });
        });

        // Pagination - keep existing code
        document.addEventListener('click', e => {
            const btn = e.target.closest('.pagination-btn');
            if (!btn) return;

            const key = btn.dataset.key;
            const page = parseInt(btn.dataset.page);
            const projectItem = btn.closest('.project-item');
            const projectName = projectItem?.dataset.projectName;

            if (!this.paginatedData[key]) {
                this.paginatedData[key] = {};
            }
            this.paginatedData[key].currentPage = page;

            if (projectName) {
                this.updateSection(key, projectName);
            }
        });
    }

    renderQuickAccess(projects) {
        const activeTasks = this.collectActiveTasks(projects);
        const quickAccessSection = document.querySelector('.quick-access');
        const taskList = document.querySelector('.task-list');
    
        if (!taskList) return;

        if (activeTasks.length === 0) {
            taskList.innerHTML = '<div class="text-center text-muted py-4"><i class="fas fa-tasks fa-2x mb-3 d-block"></i>No tasks assigned</div>';
            return;
        }
    
        taskList.innerHTML = activeTasks.map(task => {
            // Get proper icon and status text based on task state
            let icon, statusText;
            switch(task.status) {
                case 'blocked':
                    icon = 'fa-exclamation-circle';
                    statusText = 'Blocked';
                    break;
                case 'todo':
                    icon = 'fa-circle';
                    statusText = 'To Do';
                    break;
                case 'in_progress':
                    icon = 'fa-clock';
                    statusText = 'In Progress';
                    break;
                default:
                    icon = 'fa-circle';
                    statusText = task.status;
            }
    
            return `
                <a href="/dashboard/projects/${task.projectName}/tasks/${task.id}" 
                class="resource-item task-item ${task.status}">
                    <div class="task-main-content">
                        <i class="fas ${icon}"></i>
                        <span class="task-identifier">${task.projectName} - Task #${task.id}</span>
                        <span class="task-separator">-</span>
                        <span class="task-description">${task.title || ''}</span>
                    </div>
                    <span class="status">${statusText}</span>
                </a>
            `;
        }).join('');
    }

    renderProjects(projects) {
        const projectsList = document.querySelector('.projects-list');
        if (!projectsList) return;

        if (!projects?.length) {
            projectsList.innerHTML = '<div class="text-center text-muted py-4"><i class="fas fa-project-diagram fa-2x mb-3 d-block"></i>No projects available. Contact your admin for access.</div>';
            return;
        }

        projectsList.innerHTML = projects.map((project, index) =>
            this.renderProject(project, index === 0)).join('');
    }

    async refreshData() {
        try {
            const response = await fetch('/api/v1/stats/user', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username: getCurrentUser() })
            });
    
            if (!response.ok) throw new Error('Failed to fetch stats');
            
            const data = await response.json();
            this.currentData = data.stats;
            this.renderDashboard(this.currentData);
        } catch (error) {
            console.error('Failed to refresh dashboard:', error);
        }
    }

    renderProject(project, isFirst) {
        const hasAnyResources = project.credentials?.length > 0 ||
                              project.cloud_accounts?.length > 0 || 
                              project.workspaces?.length > 0 || 
                              project.github_repos?.length > 0;

        return `
            <div class="project-item ${isFirst ? 'expanded' : ''}" data-project="${project.project_name}">
                <div class="project-header">
                    <div class="project-header-top">
                        <i class="fas fa-chevron-right project-expand-icon"></i>
                        <a href="/dashboard/projects/${project.project_name}" class="project-name">
                            ${project.project_name}
                        </a>
                    </div>
                    <div class="role-badges-container">
                        <div class="role-badges-label">My roles:</div>
                        <div class="role-badges">
                            ${this.renderRoleBadges(project.roles)}
                        </div>
                    </div>
                </div>
                <div class="project-content">
                    ${hasAnyResources ? `
                        ${this.renderCredentialsSection(project)}
                        ${this.renderCloudAccountsSection(project)}
                        ${this.renderWorkspacesSection(project)}
                        ${this.renderGitHubReposSection(project)}
                    ` : `
                        <div class="empty-state">
                            <p class="text-gray-500 text-sm py-4 px-6">
                                No resources available in this project.
                            </p>
                        </div>
                    `}
                </div>
            </div>
        `;
    }

    renderRoleBadges(roles) {
        const sortedRoles = roles.sort((a, b) => {
            const adminPriority = role => role.includes('admin') ? 0 : 
                                       role.includes('editor') ? 1 : 2;
            return adminPriority(a) - adminPriority(b);
        });

        return sortedRoles.map(role => `
            <span class="role-badge ${role}">${this.formatRoleName(role)}</span>
        `).join('');
    }

    formatRoleName(role) {
        return role.split('_')
                  .map(word => word.charAt(0).toUpperCase() + word.slice(1))
                  .join(' ');
    }

    renderCredentialsSection(project) {
        if (!project.credentials?.length) return '';

        // Group credentials by platform
        const credentialsByPlatform = project.credentials.reduce((groups, credential) => {
            let platform = 'Unknown';
            
            if (credential.credential_type === 'external_certificate_authority' || 
                credential.credential_type === 'key_pair') {
                platform = 'AWS';
            } else if (credential.credential_type === 'azure_service_principal') {
                platform = 'Azure';
            } else if (credential.credential_type === 'gcp_service_account') {
                platform = 'GCP';
            }
            
            if (!groups[platform]) {
                groups[platform] = 0;
            }
            groups[platform]++;
            return groups;
        }, {});

        const sortedPlatforms = Object.keys(credentialsByPlatform).sort();

        return `
            <div class="resource-group" data-section="credentials">
                <h3>
                    <i class="fas fa-key"></i>
                    <a href="/dashboard/projects/${project.project_name}/credentials" class="section-header-link">
                        Cloud Credentials
                    </a>
                    <span class="count">${project.credentials.length}</span>
                </h3>
                <div class="resource-list">
                    ${sortedPlatforms.map(platform => `
                        <div class="resource-item credential-platform">
                            <i class="fas fa-cloud"></i>
                            <span class="platform-name">${platform}</span>
                            <span class="count">${credentialsByPlatform[platform]}</span>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    renderCloudAccountsSection(project) {
        if (!project.cloud_accounts?.length) return '';

        const paginatedAccounts = this.paginateItems(project.cloud_accounts, 'cloud_accounts');

        return `
            <div class="resource-group" data-section="cloud_accounts">
                <h3>
                    <i class="fas fa-cloud"></i>
                    <a href="/dashboard/projects/${project.project_name}/cloud_accounts" class="section-header-link">
                        Cloud Accounts
                    </a>
                    <span class="count">${project.cloud_accounts.length}</span>
                </h3>
                <div class="resource-list">
                    ${paginatedAccounts.map(account => `
                        <a href="/dashboard/projects/${project.project_name}/cloud_accounts/${account.cloud_platform}/${account.account_id}" 
                           class="resource-item cloud-account">
                            <i class="fas fa-cloud"></i>
                            <span>${account.cloud_platform.toUpperCase()}: ${account.account_id}</span>
                        </a>
                    `).join('')}
                </div>
                ${this.renderPagination(project.cloud_accounts.length, 'cloud_accounts')}
            </div>
        `;
    }

    renderWorkspacesSection(project) {
        if (!project.workspaces?.length) return '';
    
        const paginatedWorkspaces = this.paginateItems(project.workspaces, 'workspaces');
    
        return `
            <div class="resource-group" data-section="workspaces">
                <h3>
                    <i class="fas fa-folder"></i>
                    <a href="/dashboard/projects/${project.project_name}/workspaces" class="section-header-link">
                        Workspaces
                    </a>
                    <span class="count">${project.workspaces.length}</span>
                </h3>
                <div class="resource-list">
                    ${paginatedWorkspaces.map(workspace => {
                        // Ensure we have a valid workspace name
                        const workspaceName = workspace.name || workspace;
                        return `
                            <a href="/dashboard/projects/${project.project_name}/workspaces/${workspaceName}" 
                               class="resource-item workspace">
                                <i class="fas fa-folder"></i>
                                <span>${workspaceName}</span>
                            </a>
                        `;
                    }).join('')}
                </div>
                ${this.renderPagination(project.workspaces.length, 'workspaces')}
            </div>
        `;
    }

    renderGitHubReposSection(project) {
        if (!project.github_repos?.length) return '';

        const paginatedRepos = this.paginateItems(project.github_repos, 'github_repos');

        return `
            <div class="resource-group" data-section="github_repos">
                <h3>
                    <i class="fab fa-github"></i>
                    <a href="/dashboard/projects/${project.project_name}/git_repos" class="section-header-link">
                        Linked Git Repositories
                    </a>
                    <span class="count">${project.github_repos.length}</span>
                </h3>
                <div class="resource-list">
                    ${paginatedRepos.map(repo => `
                        <a href="${repo.repo_url}" 
                           target="_blank" 
                           rel="noopener noreferrer" 
                           class="resource-item github-repo">
                            <span>
                                <i class="fab fa-github"></i>
                                ${repo.repo_name.split('~')[1] || repo.repo_name}
                            </span>
                            <i class="fas fa-external-link-alt external"></i>
                        </a>
                    `).join('')}
                </div>
                ${this.renderPagination(project.github_repos.length, 'github_repos')}
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

    updateSection(key, projectName) {
        const projectEl = document.querySelector(`[data-project="${projectName}"]`);
        if (!projectEl) return;

        const section = projectEl.querySelector(`[data-section="${key}"]`);
        if (!section) return;

        const project = this.currentData.projects.find(p => p.project_name === projectName);
        if (!project) return;

        let newHtml = '';
        switch(key) {
            case 'credentials':
                newHtml = this.renderCredentialsSection(project);
                break;
            case 'workspaces':
                newHtml = this.renderWorkspacesSection(project);
                break;
            case 'github_repos':
                newHtml = this.renderGitHubReposSection(project);
                break;
            case 'cloud_accounts':
                newHtml = this.renderCloudAccountsSection(project);
                break;
        }

        if (newHtml) {
            section.outerHTML = newHtml;
        }
    }

    getActiveTasks(tasks) {
        const activeTasks = [];
        Object.entries(tasks).forEach(([status, ids]) => {
            if (status !== 'done' && status !== 'cancelled') {
                ids.forEach(id => activeTasks.push({ id, status }));
            }
        });
        return activeTasks;
    }

    collectActiveTasks(projects) {
        return projects.reduce((acc, project) => {
            console.log("DEBUG - Processing project:", project.project_name);
            console.log("DEBUG - Project tasks:", JSON.stringify(project.tasks, null, 2));
            const projectTasks = [];
            Object.entries(project.tasks).forEach(([status, taskData]) => {
                if (status !== 'done' && status !== 'cancelled') {
                    taskData.forEach(task => {
                        console.log("DEBUG - Individual task:", task);
                        projectTasks.push({
                            id: task.id || task,  // handle both object and ID-only cases
                            status,
                            projectName: project.project_name,
                            title: task.title || ''  // add description
                        });
                    });
                }
            });
            return [...acc, ...projectTasks];
        }, []);
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
    new ResourceMap();
});