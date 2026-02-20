import logging
from typing import Tuple, List, Union

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


class TagsManager:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.collection_name = 'project_tags'

    async def get_tags(self, project_name: str) -> Tuple[bool, Union[List[str], str]]:
        """Get all tags for a project"""
        try:
            doc = await self.db_manager.find_document(
                self.collection_name,
                {'project_name': project_name}
            )
            # Check if doc exists, if not return empty list
            if doc is None:
                # Return empty list for new projects
                return True, []

            return True, doc.get('tags', [])

        except Exception as e:
            logger.error(f"Failed to get tags for project {project_name}: {str(e)}")
            return False, f"Failed to get tags: {str(e)}"

    async def update_tags(self, project_name: str, new_tags: List[str]) -> Tuple[bool, str]:
        """Update project tags and clean up removed tags from tasks"""
        try:
            # Normalize all tags
            new_tags = [tag.strip().lower() for tag in new_tags if tag.strip()]
            new_tags = list(set(new_tags))  # Remove duplicates

            # Get current tags
            success, current_tags = await self.get_tags(project_name)
            if not success:
                return False, current_tags

            # Find removed tags that need cleanup
            removed_tags = set(current_tags) - set(new_tags)

            # Update project tags in project_tags collection (creating if doesn't exist)
            result = await self.db_manager.update_one_document(
                self.collection_name,
                {'project_name': project_name},
                {'$set': {'tags': new_tags}},
                upsert=True  # Create document if it doesn't exist
            )

            if result['matched_count'] == 0 and result['upserted_id'] is None:
                return False, "Failed to update tags"

            # Clean up removed tags from tasks
            if removed_tags:
                for tag in removed_tags:
                    await self.clean_deleted_tag_from_tasks(project_name, tag)

            return True, "Tags updated successfully"

        except Exception as e:
            logger.error(f"Failed to update tags for project {project_name}: {str(e)}")
            return False, f"Failed to update tags: {str(e)}"

    async def clean_deleted_tag_from_tasks(self, project_name: str, deleted_tag: str) -> Tuple[bool, str]:
        """Remove a specific tag from all tasks that have it"""
        try:
            # Find tasks containing this tag
            tasks = await self.db_manager.find_documents(
                'tasks',
                {
                    'project_name': project_name,
                    'tags': deleted_tag
                }
            )

            # Update each task's tags array
            for task in tasks:
                updated_tags = [tag for tag in task['tags'] if tag != deleted_tag]
                await self.db_manager.update_document(
                    'tasks',
                    {'id': task['id'], 'project_name': project_name},
                    {'tags': updated_tags}
                )

            return True, f"Removed tag '{deleted_tag}' from all tasks"
        except Exception as e:
            logger.error(f"Failed to clean deleted tag '{deleted_tag}' from tasks: {str(e)}")
            return False, str(e)

    async def clean_orphaned_tags(self, project_name: str) -> Tuple[bool, str]:
        """Remove all tags from tasks that aren't in the project tags list"""
        try:
            # Get valid tags
            success, valid_tags = await self.get_tags(project_name)
            if not success:
                return False, valid_tags

            # Find all tasks with tags
            tasks = await self.db_manager.find_documents(
                'tasks',
                {
                    'project_name': project_name,
                    'tags': {'$exists': True}
                }
            )

            # Clean up tasks
            for task in tasks:
                if 'tags' in task:
                    updated_tags = [tag for tag in task['tags'] if tag in valid_tags]
                    await self.db_manager.update_document(
                        'tasks',
                        {'id': task['id'], 'project_name': project_name},
                        {'tags': updated_tags}
                    )

            return True, "Cleaned up orphaned tags from all tasks"
        except Exception as e:
            logger.error(f"Failed to clean orphaned tags: {str(e)}")
            return False, str(e)
