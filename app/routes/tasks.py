"""
Task management routes for Qubiva.

Tasks, sprints, comments, tags, and notification helpers.
"""

import logging
from datetime import datetime
from typing import List, Optional

from anyio import to_thread
from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, HTTPException

from app.deps import (
    authenticator,
    email_service,
    project_manager,
    tags_manager,
    tasks_config,
    get_app_base_url,
)
from app.models import Models
from app.auth_helpers import authenticate_http_user
from app.decorators import permissions

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


# Tasks endpoints
@router.get("/api/v1/tasks/list_status_options")
def get_status_options(user: dict = Depends(authenticate_http_user)):
    logger.debug(tasks_config.get_status_options())
    return tasks_config.get_status_options()


@router.get("/api/v1/tasks/list_task_type_options")
def get_task_type_options():
    return tasks_config.get_task_type_options()


@router.get("/api/v1/tasks/list_priority_options")
def get_priority_options(user: dict = Depends(authenticate_http_user)):
    return tasks_config.get_priority_options()


@router.get("/api/v1/projects/{project_name}/sprints")
async def get_all_sprints(
    project_name: str, user: dict = Depends(authenticate_http_user)
):
    success, result = await tasks_config.get_all_sprints(project_name)

    if not success:
        raise HTTPException(status_code=400, detail=result)

    return {"message": "Sprints fetched successfully", "sprints": result}


@router.post("/api/v1/projects/{project_name}/sprints/create")
async def create_sprint(
    project_name: str,
    sprint_data: Models.SprintCreateRequest,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: [])
):
    success, result = await tasks_config.create_sprint(
        project_name, sprint_data.start_date, sprint_data.end_date, sprint_data.goal
    )
    if not success:
        raise HTTPException(status_code=400, detail=result)

    return {"message": "Sprint created successfully", "sprint": result}


@router.get("/api/v1/projects/{project_name}/sprints/nearest")
async def get_nearest_sprint(
    project_name: str, user: dict = Depends(authenticate_http_user)
):
    success, result = await tasks_config.get_nearest_sprint(project_name)
    if not success:
        raise HTTPException(status_code=400, detail=result)
    return result


@router.get("/api/v1/projects/{project_name}/sprints/{sprint_id}")
async def get_sprint(
    project_name: str, sprint_id: str, user: dict = Depends(authenticate_http_user)
):
    # Fetch sprint details using the get_sprint method in tasks_config
    success, sprint_data = await tasks_config.get_sprint(project_name, sprint_id)

    if not success:
        raise HTTPException(status_code=404, detail=sprint_data)
    return sprint_data


@router.put("/api/v1/projects/{project_name}/sprints/{sprint_id}")
async def edit_sprint(
    project_name: str,
    sprint_id: str,
    sprint_data: Models.SprintUpdateRequest,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: [])
):
    success, result = await tasks_config.edit_sprint(
        project_name,
        sprint_id,
        sprint_data.start_date,
        sprint_data.end_date,
        sprint_data.goal,
    )

    if not success:
        raise HTTPException(status_code=400, detail=result)

    return {"message": "Sprint updated successfully", "sprint": result}


@router.post("/api/v1/projects/{project_name}/tasks/create")
async def create_task(
    project_name: str,
    task_data: Models.TaskCreate,
    background_tasks: BackgroundTasks,
    session_token: Optional[str] = Cookie(None),
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: [])
):
    success, result = await tasks_config.create_task(
        project_name, task_data.model_dump()
    )
    if not success:
        raise HTTPException(status_code=400, detail=result)

    # Send email notification if task is assigned to a user
    if task_data.assignedTo and session_token:
        current_user = await authenticator.get_current_user(session_token)
        assigned_by = current_user.get("username", "Unknown")

        # Queue email notification as background task (non-blocking)
        background_tasks.add_task(
            send_task_assignment_notification,
            project_name,
            result.get('id'),
            task_data.title,
            task_data.description,
            task_data.assignedTo,
            assigned_by
        )

    return {"message": "Task created successfully", "task": result}


@router.put("/api/v1/projects/{project_name}/tasks/edit/{task_id}")
async def edit_task(
    project_name: str,
    task_id: str,
    task_data: Models.TaskUpdate,
    background_tasks: BackgroundTasks,
    session_token: Optional[str] = Cookie(None),
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    # Get the existing task to check if assignment changed
    existing_task_success, existing_task = await tasks_config.get_task(project_name, task_id)
    if not existing_task_success:
        raise HTTPException(status_code=404, detail="Task not found")

    # Update the task
    success, result = await tasks_config.update_task(
        project_name, task_id, task_data.model_dump(exclude_unset=True)
    )
    if not success:
        raise HTTPException(status_code=400, detail=result)

    # Check if assignment changed and send notification
    update_dict = task_data.model_dump(exclude_unset=True)
    if 'assignedTo' in update_dict:
        old_assignee = existing_task.get('assignedTo')
        new_assignee = update_dict.get('assignedTo')

        # Send notification only if assignment is new or changed
        if new_assignee and new_assignee != old_assignee and session_token:
            current_user = await authenticator.get_current_user(session_token)
            assigned_by = current_user.get("username", "Unknown")

            # Queue email notification as background task (non-blocking)
            background_tasks.add_task(
                send_task_assignment_notification,
                project_name,
                task_id,
                update_dict.get('title', existing_task.get('title', 'Untitled Task')),
                update_dict.get('description', existing_task.get('description', '')),
                new_assignee,
                assigned_by
            )

    return {"message": "Task updated successfully"}


@router.get("/api/v1/projects/{project_name}/tasks/{task_id}")
async def get_task(
    project_name: str, task_id: str, user: dict = Depends(authenticate_http_user)
):
    success, result = await tasks_config.get_task(project_name, task_id)
    if not success:
        raise HTTPException(status_code=404, detail=result)
    return result


@router.delete("/api/v1/projects/{project_name}/tasks/{task_id}")
async def delete_task(
    project_name: str, task_id: str,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: [])
):
    success, result = await tasks_config.delete_task(project_name, task_id)
    if not success:
        raise HTTPException(status_code=404, detail=result)
    return {"message": result}


@router.get("/api/v1/projects/{project_name}/tasks")
async def get_all_tasks(
    project_name: str,
    sprint_id: Optional[str] = None,
    status: Optional[str] = None,
    user: dict = Depends(authenticate_http_user),
):
    filters = {}
    if sprint_id:
        filters["sprintId"] = sprint_id
    if status:
        filters["status"] = status

    success, result = await tasks_config.get_all_tasks(project_name, filters)
    if not success:
        raise HTTPException(status_code=400, detail=result)
    return result


@router.post("/api/v1/projects/{project_name}/tasks/{task_id}/comments")
async def add_comments(
    project_name: str,
    task_id: str,
    comments: Models.CommentsCreate,
    background_tasks: BackgroundTasks,
    session_token: Optional[str] = Cookie(None),
    user: dict = Depends(authenticate_http_user),
):
    if not session_token:
        raise HTTPException(status_code=401, detail="Authentication required")

    user = await authenticator.get_current_user(session_token)
    username = user.get("username")

    comments_to_add = [
        {"author": username, "content": comment.content, "timestamp": datetime.utcnow()}
        for comment in comments.comments
    ]

    success, result = await tasks_config.add_comments(
        project_name, task_id, comments_to_add
    )
    if not success:
        raise HTTPException(status_code=400, detail=result)

    # Process @mentions and send email notifications asynchronously
    from app.tasks import extract_mentions
    for comment in comments.comments:
        mentioned_users = extract_mentions(comment.content)

        if mentioned_users:
            # Queue email notifications as background tasks (non-blocking)
            background_tasks.add_task(
                send_mention_notifications,
                project_name,
                task_id,
                username,
                comment.content,
                mentioned_users
            )

    return {"message": f"{len(comments_to_add)} comment(s) added successfully"}


@router.get("/api/v1/projects/{project_name}/tasks/{task_id}/comments")
async def get_task_comments(
    project_name: str, task_id: str, user: dict = Depends(authenticate_http_user)
):
    success, result = await tasks_config.get_task_comments(project_name, task_id)
    if not success:
        raise HTTPException(status_code=400, detail=result)
    return result


@router.put("/api/v1/projects/{project_name}/tasks/{task_id}/comments")
async def edit_comment(
    project_name: str,
    task_id: str,
    comment_update: Models.CommentUpdate,
    background_tasks: BackgroundTasks,
    session_token: Optional[str] = Cookie(None),
    user: dict = Depends(authenticate_http_user),
):
    """
    Edit a comment in a task's discussion.
    Only the original author can edit their comment.
    Sends email notifications for NEW mentions only (not existing ones).
    """
    if not session_token:
        raise HTTPException(status_code=401, detail="Authentication required")

    user = await authenticator.get_current_user(session_token)
    username = user.get("username")

    success, result = await tasks_config.edit_comment(
        project_name, task_id, comment_update.comment_timestamp, comment_update.content, username
    )

    if not success:
        raise HTTPException(status_code=400, detail=result)

    # Extract mentions from new and original content to find NEW mentions
    if comment_update.original_content:
        from app.tasks import extract_mentions

        new_mentions = set(extract_mentions(comment_update.content))
        old_mentions = set(extract_mentions(comment_update.original_content))

        # Only notify users who are NEWLY mentioned (not in original comment)
        newly_mentioned_users = list(new_mentions - old_mentions)

        if newly_mentioned_users:
            logger.info(f"Sending notifications for newly mentioned users in edited comment: {newly_mentioned_users}")
            # Send notifications for new mentions only
            background_tasks.add_task(
                send_mention_notifications,
                project_name, task_id, username, comment_update.content, newly_mentioned_users
            )
    else:
        # If original_content not provided, send notifications to all mentions (backward compatibility)
        from app.tasks import extract_mentions
        mentioned_users = extract_mentions(comment_update.content)
        if mentioned_users:
            background_tasks.add_task(
                send_mention_notifications,
                project_name, task_id, username, comment_update.content, mentioned_users
            )

    return {"message": result}


@router.get("/api/v1/projects/{project_name}/tags")
async def get_project_tags(
    project_name: str, user: dict = Depends(authenticate_http_user)
):
    success, result = await tags_manager.get_tags(project_name)
    if not success:
        raise HTTPException(status_code=400, detail=result)
    return {"success": True, "detail": "Tags retrieved successfully", "tags": result}


@router.put("/api/v1/projects/{project_name}/tags/update")
@permissions(["project_edit"])
async def update_tags(
    project_name: str,
    tags_data: Models.TagsUpdate,
    user: dict = Depends(authenticate_http_user),
    user_permissions: List[str] = Depends(lambda: []),
):
    success, message = await tags_manager.update_tags(project_name, tags_data.tags)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"success": True, "detail": message}


# ---- Background task helpers ----

async def send_task_assignment_notification(project_name: str, task_id: str, task_title: str, task_description: str, assigned_to: str, assigned_by: str):
    """
    Background task to send email notification for task assignment.
    This runs asynchronously without blocking the HTTP response.
    """
    try:
        import markdown

        # Get project members to validate assigned user exists in project
        members_success, members = await project_manager.get_project_members(project_name, search_query="")

        if members_success and assigned_to in members:
            try:
                # Convert markdown description to HTML
                html_description = markdown.markdown(
                    task_description[:500] if task_description else "No description provided",
                    extensions=['nl2br', 'fenced_code', 'tables']
                )

                # Username is email in your system
                subject = f"You have been assigned to Task #{task_id}"
                body = email_service.generate_standard_html(
                    title="New Task Assignment",
                    content=f"""
                    <p><strong>Project:</strong> {project_name}</p>
                    <p><strong>Task:</strong> #{task_id}</p>
                    <p><strong>Title:</strong> {task_title}</p>
                    <p><strong>Assigned by:</strong> {assigned_by}</p>
                    <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 20px 0;">
                    <p><strong>Description:</strong></p>
                    <div style="padding: 10px; background-color: #f9f9f9; border-radius: 5px;">
                        {html_description}
                    </div>
                    <p style="margin-top: 20px;"><a href="{get_app_base_url() or ''}/dashboard/projects/{project_name}/tasks/{task_id}" style="color: #007bff; text-decoration: none;">View Task Details</a></p>
                    """
                )
                success, msg = await to_thread.run_sync(
                    email_service.send_email, subject, body, [assigned_to]
                )
                logger.info(f"Task assignment notification sent to {assigned_to} for task {task_id}")
            except Exception as e:
                # Log error but don't fail the background task
                logger.error(f"Failed to send assignment notification to {assigned_to}: {str(e)}")
    except Exception as e:
        logger.error(f"Failed to process assignment notification for task {task_id}: {str(e)}")


async def send_mention_notifications(project_name: str, task_id: str, author_username: str, comment_content: str, mentioned_users: List[str]):
    """
    Background task to send email notifications for @mentions.
    This runs asynchronously without blocking the HTTP response.
    """
    try:
        import markdown
        import re

        # Deduplicate mentioned users (in case user was mentioned multiple times)
        unique_mentioned_users = list(set(mentioned_users))

        # Get project members to validate mentioned users exist in project
        members_success, members = await project_manager.get_project_members(project_name, search_query="")

        if members_success:
            # Filter to only notify valid project members
            valid_mentions = [m for m in unique_mentioned_users if m in members]

            # Send email to each mentioned user
            for mentioned_user in valid_mentions:
                try:
                    # Protect code blocks (triple backticks)
                    code_blocks = []
                    code_counter = 0
                    temp_content = re.sub(r'```[\s\S]*?```', lambda m: f'XCODEBLOCKX{code_counter}XCODEBLOCKX' if not code_blocks.append(m.group(0)) and code_blocks or True else '', comment_content)

                    # Protect inline code (single backticks)
                    inline_code = []

                    def replace_inline(m):
                        inline_code.append(m.group(0))
                        return f'XINLINEX{len(inline_code)-1}XINLINEX'
                    temp_content = re.sub(r'`[^`\n]+?`', replace_inline, temp_content)

                    # Escape HTML in remaining text
                    temp_content = re.sub(r'<(?!https?://)', '&lt;', temp_content)
                    temp_content = temp_content.replace('>', '&gt;')

                    # Restore protected content
                    for i, block in enumerate(code_blocks):
                        temp_content = temp_content.replace(f'XCODEBLOCKX{i}XCODEBLOCKX', block)
                    for i, code in enumerate(inline_code):
                        temp_content = temp_content.replace(f'XINLINEX{i}XINLINEX', code)

                    # Convert markdown to HTML with all necessary extensions
                    html_content = markdown.markdown(
                        temp_content,
                        extensions=[
                            'nl2br',           # Convert newlines to <br>
                            'fenced_code',     # Code blocks with ```
                            'codehilite',      # Syntax highlighting
                            'tables',          # Tables support
                            'sane_lists',      # Better list handling
                        ]
                    )

                    # Handle strikethrough manually (~~text~~ -> <del>text</del>)
                    html_content = re.sub(r'~~([^~]+)~~', r'<del>\1</del>', html_content)

                    # Style @mentions in the rendered HTML
                    html_content = re.sub(
                        r'@([\w.+-]+@[\w.-]+\.[\w]+|[\w]+)',
                        r'<span style="color: #007bff; font-weight: 500; background-color: #e7f3ff; padding: 2px 4px; border-radius: 3px;">@\1</span>',
                        html_content
                    )

                    # Username is email in your system
                    subject = f"You were mentioned in Task #{task_id}"
                    body = email_service.generate_standard_html(
                        title=f"{author_username} mentioned you in a comment",
                        content=f"""
                        <p><strong>Project:</strong> {project_name}</p>
                        <p><strong>Task:</strong> #{task_id}</p>
                        <p><strong>Comment:</strong></p>
                        <blockquote style="border-left: 3px solid #ccc; padding-left: 10px; margin: 10px 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
                            {html_content}
                        </blockquote>
                        <p><a href="{get_app_base_url() or ''}/dashboard/projects/{project_name}/tasks/{task_id}" style="color: #007bff; text-decoration: none;">View Task</a></p>
                        """
                    )
                    success, msg = await to_thread.run_sync(
                        email_service.send_email, subject, body, [mentioned_user]
                    )
                    logger.info(f"Mention notification sent to {mentioned_user} for task {task_id}")
                except Exception as e:
                    # Log error but don't fail the background task
                    logger.error(f"Failed to send mention notification to {mentioned_user}: {str(e)}")
    except Exception as e:
        logger.error(f"Failed to process mention notifications for task {task_id}: {str(e)}")
