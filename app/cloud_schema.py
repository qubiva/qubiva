"""Cloud schema registry — provides table/column metadata for AI tool calling.

Loads static JSON schema catalogs from app/schemas/ and exposes search
and lookup methods used by the Chat Manager's LLM tools.
"""
import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger('uvicorn.error')

# Map cloud platform names to query engine plugin prefixes
PLATFORM_PLUGIN_MAP = {
    "aws": "aws",
    "gcp": "gcp",
    "azure": "azure",
}


class CloudSchemaRegistry:
    """In-memory registry of cloud table schemas loaded from JSON files."""

    def __init__(self, schemas_dir: Optional[str] = None):
        if schemas_dir is None:
            schemas_dir = os.path.join(os.path.dirname(__file__), "schemas")
        self._schemas_dir = schemas_dir
        # platform -> { table_name -> { description, columns: { col -> {type, description} } } }
        self._tables: Dict[str, Dict[str, dict]] = {}
        self._loaded = False

    def load_schemas(self):
        """Load all schema JSON files from the schemas directory."""
        schemas_path = Path(self._schemas_dir)
        if not schemas_path.exists():
            logger.warning("Schemas directory not found: %s", self._schemas_dir)
            self._loaded = True
            return

        for json_file in schemas_path.glob("*_tables.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                plugin = data.get("plugin", json_file.stem.replace("_tables", ""))
                tables = data.get("tables", {})
                self._tables[plugin] = tables
                logger.info(
                    "Loaded %d table schemas for plugin '%s' from %s",
                    len(tables), plugin, json_file.name,
                )
            except Exception as e:
                logger.error("Failed to load schema file %s: %s", json_file, e)

        self._loaded = True

    def _ensure_loaded(self):
        if not self._loaded:
            self.load_schemas()

    def get_supported_platforms(self) -> List[str]:
        """Return list of platforms that have schemas loaded."""
        self._ensure_loaded()
        return list(self._tables.keys())

    def get_all_table_names(self, platform: str) -> List[str]:
        """Return all table names for a given platform."""
        self._ensure_loaded()
        plugin = PLATFORM_PLUGIN_MAP.get(platform, platform)
        tables = self._tables.get(plugin, {})
        return sorted(tables.keys())

    def search_tables(
        self,
        platform: Optional[str],
        keywords: List[str],
        limit: int = 15,
    ) -> List[dict]:
        """Search tables by keywords against table names and descriptions.

        If platform is None, searches across all loaded platforms.
        Returns a list of matches with table name, description, and relevance score.
        """
        self._ensure_loaded()

        if platform:
            plugin = PLATFORM_PLUGIN_MAP.get(platform, platform)
            tables = self._tables.get(plugin, {})
        else:
            # Search across all platforms
            tables = {}
            for p_tables in self._tables.values():
                tables.update(p_tables)

        if not tables:
            return []

        # Normalise keywords for matching
        keywords_lower = [k.lower() for k in keywords if k.strip()]
        if not keywords_lower:
            return []

        scored = []
        for table_name, table_info in tables.items():
            score = 0
            name_lower = table_name.lower()
            desc_lower = (table_info.get("description", "") or "").lower()
            col_names = " ".join(
                (table_info.get("columns", {}) or {}).keys()
            ).lower()

            for kw in keywords_lower:
                # Exact substring in table name scores highest
                if kw in name_lower:
                    score += 10
                # Word boundary match in table name
                if re.search(r'\b' + re.escape(kw) + r'\b', name_lower.replace("_", " ")):
                    score += 5
                # Match in description
                if kw in desc_lower:
                    score += 3
                # Match in column names
                if kw in col_names:
                    score += 1

            if score > 0:
                scored.append({
                    "table": table_name,
                    "description": table_info.get("description", ""),
                    "column_count": len(table_info.get("columns", {})),
                    "score": score,
                })

        scored.sort(key=lambda x: x["score"], reverse=True)
        # Drop internal score from output
        results = scored[:limit]
        for r in results:
            del r["score"]
        return results

    def get_table_schema(self, platform: Optional[str], table_name: str) -> Optional[dict]:
        """Get full schema for a specific table.

        If platform is None, searches across all loaded platforms.
        Returns dict with 'description' and 'columns' keys, or None if not found.
        """
        self._ensure_loaded()
        if platform:
            plugin = PLATFORM_PLUGIN_MAP.get(platform, platform)
            tables = self._tables.get(plugin, {})
            table = tables.get(table_name)
        else:
            # Search across all platforms
            table = None
            for p_tables in self._tables.values():
                if table_name in p_tables:
                    table = p_tables[table_name]
                    break
        if table is None:
            return None
        return {
            "table": table_name,
            "description": table.get("description", ""),
            "columns": table.get("columns", {}),
        }
