import os
import logging
import json
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ReturnDocument

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


class MongoDBManager:
    def __init__(self):
        DATABASE_URL = os.getenv("DATABASE_URL")
        logger.debug(DATABASE_URL)

        if not DATABASE_URL:
            raise EnvironmentError("Required environment variable 'DATABASE_URL' is not set.")

        try:
            self.client = AsyncIOMotorClient(DATABASE_URL)
        except Exception:
            raise EnvironmentError("Unable to initialize connection with database {DATABASE_URL}")

        current_dir = os.path.dirname(__file__)
        database_config_path = os.path.join(current_dir, 'database_config.json')

        with open(database_config_path, 'r') as file:
            config = json.load(file)

        self.db = self.client[config["database"]]
        self.collections = config["collections"]

    def _ensure_timestamps(self, document: dict, is_new: bool = True) -> dict:
        """
        Safely ensure timestamps exist in document without modifying existing ones.
        """
        current_time = datetime.utcnow()

        # For new documents, add created_at if it doesn't exist
        if is_new and 'created_at' not in document:
            document['created_at'] = current_time

        # Always update updated_at
        document['updated_at'] = current_time

        return document

    async def get_collection_names(self):
        return list(self.collections.values())

    async def initialize_collections(self):
        existing_collections = await self.db.list_collection_names()
        for collection_key, collection_name in self.collections.items():
            if collection_name not in existing_collections:
                await self.db.create_collection(collection_name)
                print(f"Created collection: {collection_name}")

    async def insert_document(self, collection_name, document):
        """
        Insert a single document, adding timestamps if they don't exist.
        Preserves any existing timestamps.
        """
        doc_to_insert = self._ensure_timestamps(document.copy(), is_new=True)
        collection = self.db[collection_name]
        result = await collection.insert_one(doc_to_insert)
        return result.inserted_id

    async def find_document(self, collection_name, query):
        collection = self.db[collection_name]
        document = await collection.find_one(query)
        if document:
            document.pop('_id', None)
        return document

    async def find_documents(self, collection_name, query):
        collection = self.db[collection_name]
        documents = await collection.find(query).to_list(length=None)
        for document in documents:
            document.pop('_id', None)
        return documents

    async def find_all(self, collection_name):
        collection = self.db[collection_name]
        documents = await collection.find({}).to_list(length=None)
        for document in documents:
            document.pop('_id', None)
        return documents

    async def update_document(self, collection_name, query, new_values):
        """
        Update a document while preserving MongoDB update operators and adding timestamp.
        """
        collection = self.db[collection_name]

        # Handle different types of updates while preserving operators
        if isinstance(new_values, dict) and any(k.startswith('$') for k in new_values.keys()):
            # If using MongoDB operators, add timestamp to $set
            update_op = new_values.copy()
            if '$set' not in update_op:
                update_op['$set'] = {}
            update_op['$set']['updated_at'] = datetime.utcnow()
        else:
            # Direct field updates
            timestamped_values = self._ensure_timestamps(new_values.copy(), is_new=False)
            update_op = {'$set': timestamped_values}

        result = await collection.update_one(query, update_op)
        return result.modified_count

    async def update_one_document(self, collection_name, filter, update, upsert=False):
        """
        Update or insert a single document while handling timestamps appropriately.
        """
        collection = self.db[collection_name]

        # Handle different types of updates
        if isinstance(update, dict) and any(k.startswith('$') for k in update.keys()):
            update_op = update.copy()
            if '$set' not in update_op:
                update_op['$set'] = {}
            update_op['$set']['updated_at'] = datetime.utcnow()

            # For upserts, ensure created_at is set if document doesn't exist
            if upsert and 'created_at' not in update_op.get('$set', {}):
                update_op['$setOnInsert'] = update_op.get('$setOnInsert', {})
                update_op['$setOnInsert']['created_at'] = datetime.utcnow()
        else:
            # Direct field updates
            timestamped_values = self._ensure_timestamps(update.copy(), is_new=upsert)
            update_op = {'$set': timestamped_values}

        result = await collection.update_one(filter, update_op, upsert=upsert)
        return {
            "matched_count": result.matched_count,
            "modified_count": result.modified_count,
            "upserted_id": str(result.upserted_id) if result.upserted_id else None
        }

    async def delete_document(self, collection_name, query):
        collection = self.db[collection_name]
        result = await collection.delete_one(query)
        return result.deleted_count

    async def delete_documents(self, collection_name, query):
        collection = self.db[collection_name]
        result = await collection.delete_many(query)
        return result.deleted_count

    async def find_documents_with_array_match(self, collection_name, array_field, match_criteria):
        collection = self.db[collection_name]
        query = {array_field: {'$elemMatch': match_criteria}}
        documents = await collection.find(query).to_list(length=None)
        for document in documents:
            document.pop('_id', None)
        return documents

    async def update_array_field(self, collection_name, query, array_field, array_data):
        """
        Update an array field while maintaining timestamp.
        """
        collection = self.db[collection_name]
        update = {
            '$set': {
                array_field: array_data,
                'updated_at': datetime.utcnow()
            }
        }
        result = await collection.update_one(query, update)
        return {
            "matched_count": result.matched_count,
            "modified_count": result.modified_count
        }

    async def find_documents_regex(self, collection_name, query_fields, search_term, additional_filters=None):
        """
        Search documents using regex on specified fields.

        Args:
            collection_name: Name of the collection
            query_fields: List of field names to search in
            search_term: Term to search for
            additional_filters: Additional MongoDB query filters
        """
        collection = self.db[collection_name]

        # Build regex query
        regex_query = {'$regex': search_term, '$options': 'i'}
        or_conditions = [{field: regex_query} for field in query_fields]

        # Combine with additional filters if provided
        if additional_filters:
            query = {'$and': [additional_filters, {'$or': or_conditions}]}
        else:
            query = {'$or': or_conditions}

        documents = await collection.find(query).to_list(length=None)
        for document in documents:
            document.pop('_id', None)
        return documents

    async def count_documents(self, collection_name, query=None):
        """
        Count documents in a collection matching the query.

        Args:
            collection_name: Name of the collection
            query: MongoDB query filter (optional)
        """
        collection = self.db[collection_name]
        if query is None:
            query = {}
        return await collection.count_documents(query)

    async def find_one_and_update(self, collection_name, filter, update, upsert=False, return_new=True):
        """
        Atomic find-and-update operation. Returns the document before or after update.
        Used for distributed locks and compare-and-swap patterns.
        """
        collection = self.db[collection_name]

        if isinstance(update, dict) and any(k.startswith('$') for k in update.keys()):
            update_op = update.copy()
            if '$set' not in update_op:
                update_op['$set'] = {}
            update_op['$set']['updated_at'] = datetime.utcnow()
            if upsert:
                update_op.setdefault('$setOnInsert', {})['created_at'] = datetime.utcnow()
        else:
            timestamped_values = self._ensure_timestamps(update.copy(), is_new=upsert)
            update_op = {'$set': timestamped_values}

        result = await collection.find_one_and_update(
            filter,
            update_op,
            upsert=upsert,
            return_document=ReturnDocument.AFTER if return_new else ReturnDocument.BEFORE,
        )
        if result:
            result.pop('_id', None)
        return result

    async def find_documents_with_projection(self, collection_name, query, projection=None):
        """
        Find documents with specific field projection.

        Args:
            collection_name: Name of the collection
            query: MongoDB query filter
            projection: Fields to include/exclude
        """
        collection = self.db[collection_name]
        cursor = collection.find(query, projection)
        documents = await cursor.to_list(length=None)
        for document in documents:
            document.pop('_id', None)
        return documents
