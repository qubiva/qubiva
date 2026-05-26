"""
GitHub Webhook Dispatcher for Qubiva.

Routes push and pull_request events to workspace-level IaC runs.

Push events:
  - Matched against workspaces where trigger_branch == pushed branch AND
    changed files overlap with terraform_config_path.
  - Queues a plan+apply run (approval gate still applies).

Pull request events (opened / synchronize / reopened):
  - Runs a speculative plan-only run that does NOT lock the workspace.
  - On completion, updates a GitHub Check Run.

Pull request event (closed + merged):
  - Treated as a push to the base branch (deduped by head_sha).
"""
import asyncio
import logging
from typing import Optional

logger = logging.getLogger("uvicorn.error")


class WebhookDispatcher:
    """Dispatch GitHub webhook events to workspace runs."""

    async def dispatch(self, event_type: str, payload: dict):
        try:
            if event_type == "push":
                await self._handle_push(payload)
            elif event_type == "pull_request":
                await self._handle_pull_request(payload)
            else:
                logger.debug("Webhook: ignoring event type '%s'", event_type)
        except Exception as exc:
            logger.error("WebhookDispatcher.dispatch error (event=%s): %s", event_type, exc)

    # ------------------------------------------------------------------
    # Push event
    # ------------------------------------------------------------------

    async def _handle_push(self, payload: dict):
        ref = payload.get("ref", "")
        if not ref.startswith("refs/heads/"):
            return  # Tags or other refs — ignore
        pushed_branch = ref[len("refs/heads/"):]

        repo_full_name = payload.get("repository", {}).get("full_name", "")
        head_sha = payload.get("after") or payload.get("head_commit", {}).get("id", "")
        triggered_by = (
            payload.get("pusher", {}).get("name")
            or payload.get("sender", {}).get("login", "")
        )
        head_commit_url = (
            payload.get("head_commit", {}).get("url", "")
            or (f"https://github.com/{repo_full_name}/commit/{head_sha}" if repo_full_name and head_sha else "")
        )

        # Collect all file paths changed in this push
        changed_paths = set()
        for commit in payload.get("commits", []):
            for f in commit.get("added", []) + commit.get("modified", []) + commit.get("removed", []):
                changed_paths.add(f)

        if not changed_paths and not head_sha:
            return  # No useful data

        logger.info(
            "Webhook push: %s branch=%s sha=%s changed=%d files",
            repo_full_name, pushed_branch, head_sha[:8] if head_sha else "?", len(changed_paths),
        )

        from app.deps import project_manager, db_manager, queue_manager, request_tracker
        from app.iac_executor import IaCJobTrigger
        from app.deps import log_persistence, iac_pool_manager, ConfigManager
        from app.auth.cloud_auth import MultiCloudAuthentication
        import uuid
        from datetime import datetime, timezone

        # Find workspaces matching this repo + trigger branch
        workspaces = await db_manager.find_documents(
            "workspaces",
            {"trigger_branch": pushed_branch},
        )
        if not workspaces:
            return

        for workspace in workspaces:
            ws_repo = workspace.get("github_repo_name")
            if not ws_repo:
                continue

            # Match by repo name (last segment of full_name) or full match.
            # Qubiva stores repo names with '~' as org/repo separator (e.g. "myorg~myrepo"),
            # so normalize to '/' before comparing against GitHub's "org/repo" full_name.
            repo_name_segment = repo_full_name.split("/")[-1] if "/" in repo_full_name else repo_full_name
            ws_repo_normalized = ws_repo.replace("~", "/")
            if ws_repo_normalized != repo_full_name and ws_repo != repo_name_segment:
                continue

            # Path diffing: check if any changed file is under terraform_config_path
            tf_config_path = None
            try:
                success, run_details = await project_manager.get_terraform_run_details(
                    project_name=workspace["project_name"],
                    workspace_name=workspace["name"],
                )
                if success:
                    tf_config_path = (run_details.get("github_repo") or {}).get("terraform_config_path", "")
            except Exception:
                pass

            if changed_paths and tf_config_path:
                # Normalize path (strip leading /)
                tf_path = tf_config_path.lstrip("/")
                if not any(p.startswith(tf_path) for p in changed_paths):
                    logger.debug(
                        "Webhook push: no changed files under '%s' for %s/%s — skipping",
                        tf_config_path, workspace["project_name"], workspace["name"],
                    )
                    continue

            logger.info(
                "Webhook push: triggering plan+apply for %s/%s",
                workspace["project_name"], workspace["name"],
            )

            await self._queue_webhook_run(
                project_name=workspace["project_name"],
                workspace_name=workspace["name"],
                phases=["init", "plan", "apply"],
                trigger_source="webhook_push",
                head_sha=head_sha,
                triggered_by=triggered_by,
                head_commit_url=head_commit_url,
                repo_full_name=repo_full_name,
                db_manager=db_manager,
                project_manager=project_manager,
                request_tracker=request_tracker,
                queue_manager=queue_manager,
                log_persistence=log_persistence,
                iac_pool_manager=iac_pool_manager,
                ConfigManager=ConfigManager,
            )

    # ------------------------------------------------------------------
    # Pull request event
    # ------------------------------------------------------------------

    async def _handle_pull_request(self, payload: dict):
        action = payload.get("action", "")
        if action not in ("opened", "synchronize", "reopened", "closed"):
            return

        pr = payload.get("pull_request", {})
        merged = payload.get("pull_request", {}).get("merged", False)

        # Merged PR → treat as a push to the base branch
        if action == "closed" and merged:
            await self._handle_merged_pr_as_push(payload)
            return

        if action == "closed":
            return  # Closed without merge — nothing to do

        repo_full_name = payload.get("repository", {}).get("full_name", "")
        head_sha = pr.get("head", {}).get("sha", "")
        pr_number = pr.get("number")
        base_branch = pr.get("base", {}).get("ref", "")
        triggered_by = pr.get("user", {}).get("login", "") or payload.get("sender", {}).get("login", "")
        pr_url = pr.get("html_url", "")
        head_commit_url = f"https://github.com/{repo_full_name}/commit/{head_sha}" if repo_full_name and head_sha else ""

        logger.info(
            "Webhook PR #%s (%s): %s sha=%s",
            pr_number, repo_full_name, action, head_sha[:8] if head_sha else "?",
        )

        from app.deps import project_manager, db_manager, queue_manager, request_tracker
        from app.deps import log_persistence, iac_pool_manager, ConfigManager

        # Find workspaces matching this repo (any trigger_branch that matches base branch)
        workspaces = await db_manager.find_documents(
            "workspaces",
            {},  # look at all workspaces; filter by repo below
        )
        if not workspaces:
            return

        repo_name_segment = repo_full_name.split("/")[-1] if "/" in repo_full_name else repo_full_name

        for workspace in workspaces:
            ws_repo = workspace.get("github_repo_name")
            if not ws_repo:
                continue
            ws_repo_normalized = ws_repo.replace("~", "/")
            if ws_repo_normalized != repo_full_name and ws_repo != repo_name_segment:
                continue
            # Only run speculative plan for workspaces whose trigger_branch is the PR base branch
            if workspace.get("trigger_branch") != base_branch:
                continue

            logger.info(
                "Webhook PR: speculative plan for %s/%s",
                workspace["project_name"], workspace["name"],
            )

            await self._queue_webhook_run(
                project_name=workspace["project_name"],
                workspace_name=workspace["name"],
                phases=["init", "plan"],
                trigger_source="webhook_pr",
                head_sha=head_sha,
                pr_number=pr_number,
                is_speculative=True,
                triggered_by=triggered_by,
                head_commit_url=head_commit_url,
                pr_url=pr_url,
                repo_full_name=repo_full_name,
                db_manager=db_manager,
                project_manager=project_manager,
                request_tracker=request_tracker,
                queue_manager=queue_manager,
                log_persistence=log_persistence,
                iac_pool_manager=iac_pool_manager,
                ConfigManager=ConfigManager,
            )

    async def _handle_merged_pr_as_push(self, payload: dict):
        pr = payload.get("pull_request", {})
        base_ref = pr.get("base", {}).get("ref", "")
        head_sha = pr.get("merge_commit_sha") or pr.get("head", {}).get("sha", "")
        repo_full_name = payload.get("repository", {}).get("full_name", "")

        # Simulate a push payload and re-dispatch
        fake_push = {
            "ref": f"refs/heads/{base_ref}",
            "after": head_sha,
            "repository": {"full_name": repo_full_name},
            "commits": [],  # No path filtering for merged PRs (assume all paths changed)
        }
        await self._handle_push(fake_push)

    # ------------------------------------------------------------------
    # Shared: create request doc and trigger execution
    # ------------------------------------------------------------------

    async def _queue_webhook_run(
        self,
        project_name: str,
        workspace_name: str,
        phases: list,
        trigger_source: str,
        head_sha: str = "",
        pr_number: Optional[int] = None,
        is_speculative: bool = False,
        triggered_by: str = "",
        head_commit_url: str = "",
        pr_url: str = "",
        repo_full_name: str = "",
        **deps,
    ):
        db_manager = deps["db_manager"]
        project_manager = deps["project_manager"]
        request_tracker = deps["request_tracker"]
        queue_manager = deps["queue_manager"]
        log_persistence = deps["log_persistence"]
        iac_pool_manager = deps["iac_pool_manager"]
        ConfigManager = deps["ConfigManager"]

        from app.auth.cloud_auth import MultiCloudAuthentication
        from app.iac_executor import IaCJobTrigger
        from datetime import datetime, timezone
        import uuid

        request_id = str(uuid.uuid4())
        requested_on = datetime.now(timezone.utc).isoformat()

        # Create request document
        request_doc = {
            "request_id": request_id,
            "requested_by": "webhook",
            "requested_on": requested_on,
            "request_type": "terraform_run",
            "state": "queued",
            "project_name": project_name,
            "workspace_name": workspace_name,
            "phases": phases,
            "trigger_source": trigger_source,
            "head_sha": head_sha,
            "pr_number": pr_number,
            "is_speculative": is_speculative,
            "triggered_by": triggered_by,
            "head_commit_url": head_commit_url,
            "pr_url": pr_url,
            "repo_full_name": repo_full_name,
        }
        await db_manager.insert_document("requests", request_doc)
        await request_tracker.broadcast_update(request_id, request_doc)

        # Create GitHub Check Run if we have a head SHA and can resolve the repo full name
        if head_sha:
            try:
                ws = await db_manager.find_document(
                    "workspaces", {"project_name": project_name, "name": workspace_name}
                )
                ws_repo = (ws or {}).get("github_repo_name", "")
                check_run_repo = None
                if ws_repo:
                    if "/" in ws_repo:
                        check_run_repo = ws_repo
                    else:
                        repo_doc = await db_manager.find_document(
                            "github_repos", {"project_name": project_name, "repo_name": ws_repo}
                        )
                        repo_url = (repo_doc or {}).get("repo_url", "")
                        if "github.com/" in repo_url:
                            check_run_repo = repo_url.split("github.com/")[-1].rstrip("/")
                            if check_run_repo.endswith(".git"):
                                check_run_repo = check_run_repo[:-4]
                if check_run_repo:
                    run_name = "Qubiva / terraform plan" if is_speculative else "Qubiva / terraform plan+apply"
                    check_run_id = await project_manager.create_check_run(
                        repo_full_name=check_run_repo,
                        head_sha=head_sha,
                        name=run_name,
                        status="queued",
                        conclusion=None,
                        title="Queued",
                        summary="Terraform run queued.",
                    )
                    if check_run_id:
                        await db_manager.update_document(
                            "requests",
                            {"request_id": request_id},
                            {"check_run_id": check_run_id, "check_run_repo": check_run_repo},
                        )
            except Exception as exc:
                logger.debug("Failed to create check run for %s: %s", request_id, exc)

        # For speculative runs, skip workspace lock and run directly
        if is_speculative:
            try:
                success, run_details = await project_manager.get_terraform_run_details(
                    project_name=project_name,
                    workspace_name=workspace_name,
                )
                if not success:
                    raise RuntimeError(f"Failed to fetch run details: {run_details}")

                if run_details.get("github_repo", {}).get("repo_url"):
                    github_token, _ = await project_manager.get_github_token_for_container_run(
                        repo_url=run_details["github_repo"]["repo_url"],
                        repo_details=run_details["github_repo"],
                    )
                    run_details["github_repo"]["token"] = github_token

                cloudauth = MultiCloudAuthentication(
                    cloud_platform=run_details["cloud_platform"],
                    project_manager=project_manager,
                    project_name=project_name,
                    account_id=run_details["cloud_account"],
                )
                await cloudauth.initialize()
                run_details["auth_env_vars"] = await cloudauth.get_auth_env_vars()

                iac_trigger = IaCJobTrigger(
                    request_tracker=request_tracker,
                    request_id=request_id,
                    project_manager=project_manager,
                    log_persistence=log_persistence,
                    pool_manager=iac_pool_manager,
                    config_manager=ConfigManager,
                    queue_manager=queue_manager,
                )
                # Force plan-only, skip lock acquisition for speculative runs
                result = await iac_trigger.trigger_terraform_command(
                    project_name=project_name,
                    workspace_name=workspace_name,
                    run_details=run_details,
                    phases=["init", "plan"],
                    request_id=request_id,
                    plan_request_id=None,
                    is_speculative=True,
                )
                if result.get("status") not in ("error",):
                    await request_tracker.update_request_state(request_id, "in progress")
            except Exception as exc:
                logger.error("Speculative run %s failed to start: %s", request_id, exc)
                await request_tracker.update_request_state(request_id, "failed")
            return

        # Non-speculative: attempt to start immediately (or queue if workspace busy)
        try:
            success, run_details = await project_manager.get_terraform_run_details(
                project_name=project_name,
                workspace_name=workspace_name,
            )
            if not success:
                raise RuntimeError(f"Failed to fetch run details: {run_details}")

            if run_details.get("github_repo", {}).get("repo_url"):
                github_token, _ = await project_manager.get_github_token_for_container_run(
                    repo_url=run_details["github_repo"]["repo_url"],
                    repo_details=run_details["github_repo"],
                )
                run_details["github_repo"]["token"] = github_token

            cloudauth = MultiCloudAuthentication(
                cloud_platform=run_details["cloud_platform"],
                project_manager=project_manager,
                project_name=project_name,
                account_id=run_details["cloud_account"],
            )
            await cloudauth.initialize()
            run_details["auth_env_vars"] = await cloudauth.get_auth_env_vars()

            iac_trigger = IaCJobTrigger(
                request_tracker=request_tracker,
                request_id=request_id,
                project_manager=project_manager,
                log_persistence=log_persistence,
                pool_manager=iac_pool_manager,
                config_manager=ConfigManager,
                queue_manager=queue_manager,
            )
            result = await iac_trigger.trigger_terraform_command(
                project_name=project_name,
                workspace_name=workspace_name,
                run_details=run_details,
                phases=phases,
                request_id=request_id,
            )
            if result.get("status") == "error":
                logger.error("Webhook run %s failed to start: %s", request_id, result.get("error"))
                return
            if result.get("status") == "queued":
                logger.info("Webhook run %s queued for %s/%s (workspace busy)", request_id, project_name, workspace_name)
                return
            # Started successfully
            await request_tracker.update_request_state(request_id, "in progress")
            logger.info("Webhook run %s started for %s/%s", request_id, project_name, workspace_name)
        except Exception as exc:
            logger.error("Webhook run %s failed to start: %s", request_id, exc)
            await request_tracker.update_request_state(request_id, "failed")
