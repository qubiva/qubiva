from datetime import datetime
from datetime import date
import logging
import json
import uuid
import re

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


def serialize_date(obj):
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError("Type not serializable")


def is_task_overdue(task: dict) -> bool:
    """
    Check if a task is overdue based on its due_date and status.
    A task is overdue if:
    1. It has a due_date set
    2. The due_date is in the past (< today)
    3. The task status is not 'done'
    """
    # Handle both camelCase (dueDate) and snake_case (due_date) field names
    due_date_value = task.get('dueDate') or task.get('due_date')

    if not due_date_value:
        return False

    if task.get('status') == 'done':
        return False

    try:
        # Parse due_date (handle both string and date objects)
        if isinstance(due_date_value, str):
            due_date = datetime.fromisoformat(due_date_value).date()
        elif isinstance(due_date_value, datetime):
            due_date = due_date_value.date()
        elif isinstance(due_date_value, date):
            due_date = due_date_value
        else:
            return False

        # Compare with today's date
        today = datetime.utcnow().date()
        return due_date < today
    except Exception as e:
        logger.error(f"Error checking if task is overdue: {str(e)}")
        return False


def get_sprint_status(sprint: dict) -> str:
    """
    Get the status of a sprint based on its dates.
    Returns: 'current', 'upcoming', or 'completed'
    """
    if 'start_date' not in sprint or 'end_date' not in sprint:
        return 'unknown'

    try:
        # Parse dates (handle both string and date objects)
        if isinstance(sprint['start_date'], str):
            start_date = datetime.fromisoformat(sprint['start_date']).date()
        elif isinstance(sprint['start_date'], datetime):
            start_date = sprint['start_date'].date()
        elif isinstance(sprint['start_date'], date):
            start_date = sprint['start_date']
        else:
            return 'unknown'

        if isinstance(sprint['end_date'], str):
            end_date = datetime.fromisoformat(sprint['end_date']).date()
        elif isinstance(sprint['end_date'], datetime):
            end_date = sprint['end_date'].date()
        elif isinstance(sprint['end_date'], date):
            end_date = sprint['end_date']
        else:
            return 'unknown'

        # Compare with today's date
        today = datetime.utcnow().date()

        if today < start_date:
            return 'upcoming'
        elif today > end_date:
            return 'completed'
        else:
            return 'current'
    except Exception as e:
        logger.error(f"Error getting sprint status: {str(e)}")
        return 'unknown'


def extract_mentions(content: str) -> list:
    """
    Extract @username mentions from comment content.
    Returns a list of unique usernames mentioned (without the @ symbol).
    Supports both simple usernames and email addresses.
    Examples:
        "@alice please review this" -> ['alice']
        "@bob and @charlie check this out" -> ['bob', 'charlie']
        "@user@example.com check this" -> ['user@example.com']
        "@alice @alice" -> ['alice'] (deduplicated)
    """
    if not content:
        return []

    # Match @username or @email pattern
    # This regex matches: @word or @email@domain.tld
    # Pattern: @ followed by (email pattern OR simple username)
    mentions = re.findall(r'@([\w.+-]+@[\w.-]+\.[\w]+|[\w]+)', content)

    # Return unique mentions (deduplicated)
    return list(set(mentions))


class TasksConfig:
    def __init__(self, db_manager, config_manager):
        self.db_manager = db_manager
        self.config_manager = config_manager

    def _get_task_config(self):
        task_config = self.config_manager.get_config('task_management')
        if not task_config:
            raise ValueError("Failed to load task management configuration")
        return task_config

    def get_status_options(self):
        return self._get_task_config().get("status_options", [])

    def get_task_type_options(self):
        return self._get_task_config().get("task_type_options", [])

    def get_priority_options(self):
        return self._get_task_config().get("priority_options", [])

    async def get_sprint(self, project_name, sprint_id: str):
        """
        Fetch sprint details for a given sprint ID in a project.
        """
        try:
            # Find the sprint by project name and sprint ID
            sprint = await self.db_manager.find_document('sprints', {'project_name': project_name, 'id': sprint_id})
            if not sprint:
                return False, f"Sprint with ID {sprint_id} not found in project {project_name}"

            # Add computed sprint status (backend computation, no browser burden)
            sprint['status'] = get_sprint_status(sprint)

            return True, sprint

        except Exception as e:
            logger.error(f"Failed to get sprint '{sprint_id}' in project {project_name}: {str(e)}")
            return False, f"Failed to get sprint: {str(e)}"

    async def get_all_sprints(self, project_name):
        try:
            # Fetch all sprints from the database using db_manager
            sprints = await self.db_manager.find_documents('sprints', {'project_name': project_name})

            # Extract and return the 'id' field for each sprint
            sprint_ids = [sprint['id'] for sprint in sprints if 'id' in sprint]

            return True, sprint_ids

        except Exception as e:
            logger.error(f"Failed to fetch sprints for project {project_name}: {str(e)}")
            return False, f"Failed to fetch sprints: {str(e)}"

    async def create_sprint(self, project_name, start_date: str, end_date: str, goal: str):
        try:
            saved_args = {**locals()}  # Updated to make a copy per loco.loop
            print("saved_args is", saved_args)
            # Parse the provided dates
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')

            # Validate the start and end dates
            if start_dt > end_dt:
                return False, "Start date cannot be later than end date"

            # Check for overlapping sprints
            overlapping_sprints = await self.db_manager.find_documents(
                'sprints',
                {
                    'project_name': project_name,
                    '$or': [
                        {'start_date': {'$lte': end_dt, '$gte': start_dt}},  # Overlaps start date
                        {'end_date': {'$gte': start_dt, '$lte': end_dt}},    # Overlaps end date
                        {'start_date': {'$lte': start_dt}, 'end_date': {'$gte': end_dt}}  # Contains the new sprint
                    ]
                }
            )

            if overlapping_sprints:
                return False, "Sprint dates overlap with an existing sprint in this project"

            # Generate sprint ID in the format <sprint year>-<number>
            sprint_year = start_dt.year
            sprints_in_year = await self.db_manager.find_documents(
                'sprints',
                {'project_name': project_name, 'id': {'$regex': f"^{sprint_year}-"}}
            )

            # Sort the sprints manually by ID in descending order
            sprints_in_year_sorted = sorted(sprints_in_year, key=lambda x: x['id'], reverse=True)

            if sprints_in_year_sorted:
                # Increment the number from the latest sprint ID
                latest_id = sprints_in_year_sorted[0]['id']
                sprint_number = int(latest_id.split('-')[1]) + 1
            else:
                # Start with 1 if no sprints exist
                sprint_number = 1

            sprint_id = f"{sprint_year}-{sprint_number}"

            # Create a new sprint document
            sprint_data = {
                'id': sprint_id,  # Use the generated sprint ID
                'project_name': project_name,
                'start_date': serialize_date(start_dt),  # Serialize the start date
                'end_date': serialize_date(end_dt),      # Serialize the end date
                'goal': goal,
                'created_at': serialize_date(datetime.utcnow()),  # Serialize the created_at field
                'updated_at': serialize_date(datetime.utcnow())   # Serialize the updated_at field
            }

            # Insert the new sprint into the "sprints" collection
            await self.db_manager.insert_document('sprints', sprint_data)
            sprint_data.pop('_id', None)  # Remove the MongoDB-specific _id field
            return True, sprint_data

        except Exception as e:
            logger.error(f"Failed to create sprint for project {project_name}: {str(e)}")
            return False, f"Failed to create sprint: {str(e)}"

    async def get_nearest_sprint(self, project_name):
        """
        Get the current sprint based on the current date. If no current sprint is found,
        return the next nearest sprint. If no sprints exist, return the latest or last sprint,
        and if no sprints are there at all, return None.
        """
        try:
            # Get the current date
            current_date = datetime.utcnow().date()

            # Query to find all sprints for the project
            sprints = await self.db_manager.find_documents(
                'sprints',
                {
                    'project_name': project_name
                }
            )

            if not sprints:
                return False, None

            # Convert date fields to datetime.date objects for comparison
            for sprint in sprints:
                if isinstance(sprint['start_date'], str):
                    sprint['start_date'] = datetime.fromisoformat(sprint['start_date']).date()
                elif isinstance(sprint['start_date'], datetime):
                    sprint['start_date'] = sprint['start_date'].date()

                if isinstance(sprint['end_date'], str):
                    sprint['end_date'] = datetime.fromisoformat(sprint['end_date']).date()
                elif isinstance(sprint['end_date'], datetime):
                    sprint['end_date'] = sprint['end_date'].date()

            # Filter and find the current sprint
            current_sprint = next(
                (sprint for sprint in sprints if sprint['start_date'] <= current_date <= sprint['end_date']),
                None
            )

            if current_sprint:
                return True, current_sprint['id']

            # If no current sprint, find the next upcoming sprint
            next_sprint = min(
                (sprint for sprint in sprints if sprint['start_date'] > current_date),
                key=lambda x: x['start_date'],
                default=None
            )

            if next_sprint:
                return True, next_sprint['id']

            # If no upcoming sprints, find the last or latest sprint
            last_sprint = max(
                (sprint for sprint in sprints if sprint['end_date'] < current_date),
                key=lambda x: x['end_date'],
                default=None
            )

            if last_sprint:
                return True, last_sprint['id']

            # If no sprints are available, return None
            return False, None

        except Exception as e:
            logger.error(f"Failed to get current or nearest sprint for project {project_name}: {str(e)}")
            return False, f"Failed to get sprint: {str(e)}"

    async def edit_sprint(self, project_name, sprint_id: str, start_date: str = None, end_date: str = None, goal: str = None):
        try:
            # Prepare the update data
            update_data = {'updated_at': datetime.utcnow()}

            if start_date:
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                update_data['start_date'] = start_dt

            if end_date:
                end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                update_data['end_date'] = end_dt

            if 'start_date' in update_data and 'end_date' in update_data:
                # Validate the start and end dates
                if update_data['start_date'] > update_data['end_date']:
                    return False, "Start date cannot be later than end date"

                # Check for overlapping sprints excluding the current sprint being edited
                overlapping_sprints = await self.db_manager.find_documents(
                    'sprints',
                    {
                        'project_name': project_name,
                        'id': {'$ne': sprint_id},  # Exclude the current sprint
                        '$or': [
                            {'start_date': {'$lte': update_data['end_date'], '$gte': update_data['start_date']}},  # Overlaps start date
                            {'end_date': {'$gte': update_data['start_date'], '$lte': update_data['end_date']}},    # Overlaps end date
                            {'start_date': {'$lte': update_data['start_date']}, 'end_date': {'$gte': update_data['end_date']}}  # Contains the new dates
                        ]
                    }
                )

                if overlapping_sprints:
                    return False, "Sprint dates overlap with an existing sprint in this project"

            if goal is not None:
                update_data['goal'] = goal

            # Update the sprint in the "sprints" collection
            result = await self.db_manager.update_one_document(
                'sprints',
                {'id': sprint_id, 'project_name': project_name},
                {'$set': update_data}
            )

            if result['matched_count'] == 0:
                return False, f"Sprint with ID {sprint_id} not found in project {project_name}"
            if result['modified_count'] > 0:
                updated_sprint = await self.db_manager.find_document('sprints', {'id': sprint_id, 'project_name': project_name})
                return True, updated_sprint
            return False, "No changes were made to the sprint"

        except Exception as e:
            logger.error(f"Failed to edit sprint '{sprint_id}' in project {project_name}: {str(e)}")
            return False, f"Failed to edit sprint: {str(e)}"

    async def generate_task_id(self):
        """Generate a unique task ID (5-7 digit random number)"""
        while True:
            task_id = str(uuid.uuid4().int)[:7]  # Get first 7 digits of UUID
            if len(task_id) >= 5 and not await self.task_id_exists(task_id):
                return task_id

    async def task_id_exists(self, task_id):
        """Check if a task ID already exists in the database"""
        existing_task = await self.db_manager.find_document('tasks', {'id': task_id})
        return existing_task is not None

    async def create_task(self, project_name, task_data):
        try:
            task_id = await self.generate_task_id()
            task_data['id'] = task_id
            task_data['project_name'] = project_name
            task_data['created_at'] = datetime.utcnow()
            task_data['updated_at'] = datetime.utcnow()

            # Convert date objects to strings
            for key, value in task_data.items():
                if isinstance(value, date):
                    task_data[key] = serialize_date(value)

            # Validate and process relationships
            if 'relationships' in task_data:
                valid, message = await self.validate_relationships(project_name, task_data['relationships'], task_id)
                if not valid:
                    return False, message

            # Insert the new task
            await self.db_manager.insert_document('tasks', json.loads(json.dumps(task_data, default=serialize_date)))
            return True, task_data

        except Exception as e:
            logger.error(f"Failed to create task in project {project_name}: {str(e)}")
            return False, f"Failed to create task: {str(e)}"

    async def delete_task(self, project_name, task_id):
        """
        Delete a task and clean up all its relationships in other tasks.

        Args:
            project_name (str): The name of the project the task belongs to
            task_id (str): The ID of the task to delete

        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            # First check if the task exists
            task = await self.db_manager.find_document('tasks', {'id': task_id, 'project_name': project_name})
            if not task:
                return False, f"Task with ID {task_id} not found in project {project_name}"

            # Find all tasks that have relationships with this task
            related_tasks = await self.db_manager.find_documents_with_array_match(
                'tasks',
                'relationships',
                {'relatedTaskId': task_id}
            )

            # Update each related task
            for related_task in related_tasks:
                # Filter out relationships to the task being deleted
                updated_relationships = [
                    rel for rel in related_task.get('relationships', [])
                    if rel['relatedTaskId'] != task_id
                ]

                # Update the task with the filtered relationships
                await self.db_manager.update_array_field(
                    'tasks',
                    {'id': related_task['id'], 'project_name': project_name},
                    'relationships',
                    updated_relationships
                )

            # Delete associated discussions/comments
            await self.db_manager.delete_document('discussions', {'task_id': task_id, 'project_name': project_name})

            # Delete the task itself
            result = await self.db_manager.delete_document('tasks', {'id': task_id, 'project_name': project_name})

            if result > 0:
                return True, f"Task {task_id} and all its relationships have been deleted successfully"
            return False, "Failed to delete task"

        except Exception as e:
            logger.error(f"Failed to delete task '{task_id}' in project {project_name}: {str(e)}")
            return False, f"Failed to delete task: {str(e)}"

    async def update_task(self, project_name, task_id, update_data):
        try:
            existing_task = await self.db_manager.find_document('tasks', {'id': task_id, 'project_name': project_name})
            if not existing_task:
                return False, f"Task with ID {task_id} not found in project {project_name}"

            update_data['updated_at'] = datetime.utcnow()

            # Convert date objects to strings or datetime objects
            for key, value in update_data.items():
                if isinstance(value, date):
                    update_data[key] = serialize_date(value)

            # Validate and process relationships if they're being updated
            if 'relationships' in update_data:
                valid, message = await self.validate_relationships(project_name, update_data['relationships'], task_id)
                if not valid:
                    return False, message

            # Update the task
            result = await self.db_manager.update_document('tasks', {'id': task_id, 'project_name': project_name}, update_data)
            if result > 0:
                return True, "Task updated successfully"
            return False, "No changes were made to the task"

        except Exception as e:
            logger.error(f"Failed to update task '{task_id}' in project {project_name}: {str(e)}")
            return False, f"Failed to update task: {str(e)}"

    async def get_task(self, project_name, task_id):
        try:
            task = await self.db_manager.find_document('tasks', {'id': task_id, 'project_name': project_name})
            if not task:
                return False, f"Task with ID {task_id} not found in project {project_name}"

            # Fetch and include reverse relationships
            reverse_relationships = await self.get_reverse_relationships(project_name, task_id)

            # Check for duplicate relationships (remove reverse relationships that already exist as direct)
            direct_relationships = {rel['relatedTaskId']: rel['type'] for rel in task.get('relationships', [])}
            filtered_reverse_relationships = []

            for reverse_rel in reverse_relationships:
                related_id = reverse_rel['relatedTaskId']
                reverse_type = reverse_rel['type']

                # Check if a reverse relationship is the opposite of a direct relationship
                if related_id not in direct_relationships or direct_relationships[related_id] != self.get_opposite_relationship_type(reverse_type):
                    filtered_reverse_relationships.append(reverse_rel)

            task['reverse_relationships'] = filtered_reverse_relationships

            # Add computed overdue status (backend computation, no browser burden)
            task['is_overdue'] = is_task_overdue(task)

            return True, task

        except Exception as e:
            logger.error(f"Failed to get task '{task_id}' in project {project_name}: {str(e)}")
            return False, f"Failed to get task: {str(e)}"

    async def get_all_tasks(self, project_name, filters=None):
        try:
            query = filters or {}
            query['project_name'] = project_name
            tasks = await self.db_manager.find_documents('tasks', query)

            # Fetch reverse relationships for each task and compute overdue status
            for task in tasks:
                reverse_relationships = await self.get_reverse_relationships(project_name, task['id'])
                task['reverse_relationships'] = reverse_relationships
                # Add computed overdue status (backend computation, no browser burden)
                task['is_overdue'] = is_task_overdue(task)

            return True, tasks

        except Exception as e:
            logger.error(f"Failed to get tasks for project {project_name}: {str(e)}")
            return False, f"Failed to get tasks: {str(e)}"

    async def validate_relationships(self, project_name, relationships, current_task_id):
        seen_task_ids = set()

        for relationship in relationships:
            related_task_id = relationship['relatedTaskId']

            if related_task_id in seen_task_ids:
                return False, f"Duplicate relationship found with task ID {related_task_id}"
            seen_task_ids.add(related_task_id)

            if related_task_id == current_task_id:
                return False, "A task cannot have a relationship with itself"

            related_task = await self.db_manager.find_document('tasks', {'id': related_task_id, 'project_name': project_name})
            if not related_task:
                return False, f"Related task with ID {related_task_id} not found in project {project_name}"

            # Check for cyclic relationships
            if await self.is_cyclic_relationship(project_name, current_task_id, related_task_id, relationship['type']):
                return False, "Cyclic relationship detected"

        return True, "Relationships are valid"

    async def is_cyclic_relationship(self, project_name, task_id, related_task_id, relationship_type):
        # Implement logic to detect cyclic relationships
        # This is a simplified check and may need to be more comprehensive
        if relationship_type in ['parent', 'child']:
            related_task = await self.db_manager.find_document('tasks', {'id': related_task_id, 'project_name': project_name})
            if related_task and 'relationships' in related_task:
                for rel in related_task['relationships']:
                    if rel['relatedTaskId'] == task_id and rel['type'] == ('child' if relationship_type == 'parent' else 'parent'):
                        return True
        return False

    async def get_reverse_relationships(self, project_name, task_id):
        all_tasks = await self.db_manager.find_documents('tasks', {'project_name': project_name})
        reverse_relationships = []
        for task in all_tasks:
            if 'relationships' in task:
                for rel in task['relationships']:
                    if rel['relatedTaskId'] == task_id:
                        reverse_rel_type = self.get_opposite_relationship_type(rel['type'])
                        reverse_relationships.append({
                            'relatedTaskId': task['id'],
                            'type': reverse_rel_type
                        })
        return reverse_relationships

    def get_opposite_relationship_type(self, rel_type):
        opposites = {
            'parent': 'child',
            'child': 'parent',
            'blocks': 'blocked-by',
            'blocked-by': 'blocks',
            'related': 'related'
        }
        return opposites.get(rel_type, rel_type)

    async def add_comments(self, project_name, task_id, comments):
        try:
            # Check if a discussion document exists for the task
            discussion = await self.db_manager.find_document('discussions', {'task_id': task_id, 'project_name': project_name})

            if discussion:
                # Update the existing document by appending the new comments
                await self.db_manager.update_one_document(
                    'discussions',
                    {'task_id': task_id, 'project_name': project_name},
                    {'$push': {'comments': {'$each': comments}}}
                )
            else:
                # Create a new discussion document for the task
                discussion_data = {
                    'task_id': task_id,
                    'project_name': project_name,
                    'comments': comments,
                }
                await self.db_manager.insert_document('discussions', discussion_data)

            return True, f"{len(comments)} comment(s) added successfully"

        except Exception as e:
            logger.error(f"Failed to add comments to task '{task_id}' in project {project_name}: {str(e)}")
            return False, f"Failed to add comments: {str(e)}"

    async def get_task_comments(self, project_name, task_id):
        try:
            # Fetch the discussion document
            discussion = await self.db_manager.find_document('discussions', {'task_id': task_id, 'project_name': project_name})

            if not discussion:
                return True, []  # Return an empty list if no comments are found

            # Return the comments sorted by timestamp
            sorted_comments = sorted(discussion.get('comments', []), key=lambda x: x['timestamp'], reverse=False)

            return True, sorted_comments

        except Exception as e:
            logger.error(f"Failed to get comments for task '{task_id}' in project {project_name}: {str(e)}")
            return False, f"Failed to get comments: {str(e)}"

    async def edit_comment(self, project_name, task_id, comment_timestamp, new_content, editor_username):
        """
        Edit a specific comment in a task's discussion.
        Only the original author can edit their comment.

        Args:
            project_name: The project name
            task_id: The task ID
            comment_timestamp: The timestamp of the comment (unique identifier)
            new_content: The new content for the comment
            editor_username: The username of the person attempting to edit

        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            # Fetch the discussion document
            discussion = await self.db_manager.find_document('discussions', {'task_id': task_id, 'project_name': project_name})

            if not discussion:
                return False, f"No discussion found for task {task_id}"

            comments = discussion.get('comments', [])

            # Find comment by timestamp instead of index
            # Parse the incoming timestamp string to datetime for comparison
            from dateutil import parser as dateutil_parser
            try:
                incoming_ts = dateutil_parser.parse(comment_timestamp)
            except (ValueError, TypeError):
                return False, f"Invalid timestamp format: {comment_timestamp}"

            comment_index = None
            for idx, comment in enumerate(comments):
                comment_ts = comment.get('timestamp')
                # Compare datetime objects directly
                if isinstance(comment_ts, datetime):
                    if comment_ts == incoming_ts:
                        comment_index = idx
                        break
                # Fallback: compare as strings if stored as string
                elif str(comment_ts) == str(comment_timestamp):
                    comment_index = idx
                    break

            if comment_index is None:
                logger.error(f"Comment not found. Looking for: {incoming_ts}, Available: {[c.get('timestamp') for c in comments]}")
                return False, f"Comment not found with timestamp: {comment_timestamp}"

            # Validate that the editor is the original author
            comment = comments[comment_index]
            logger.debug("Editing comment: " + str(comment))
            logger.debug("Editor username: " + str(editor_username))
            if comment['author'] != editor_username:
                return False, "You can only edit your own comments"

            # Update the comment content and add edited timestamp
            comments[comment_index]['content'] = new_content
            comments[comment_index]['edited_at'] = datetime.utcnow()
            comments[comment_index]['is_edited'] = True

            # Update the discussion document
            result = await self.db_manager.update_one_document(
                'discussions',
                {'task_id': task_id, 'project_name': project_name},
                {'$set': {'comments': comments}}
            )

            if result['modified_count'] > 0:
                return True, "Comment updated successfully"
            return False, "Failed to update comment"

        except Exception as e:
            logger.error(f"Failed to edit comment for task '{task_id}' in project {project_name}: {str(e)}")
            return False, f"Failed to edit comment: {str(e)}"
