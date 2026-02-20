import json


class TerraformVersionManager:
    def __init__(self, json_file_path):
        self.json_file_path = json_file_path
        self.supported_versions = self._load_versions()

    def _load_versions(self):
        with open(self.json_file_path, 'r') as file:
            data = json.load(file)
            return data.get('supported_terraform_versions', [])

    def get_supported_versions(self):
        return self.supported_versions
