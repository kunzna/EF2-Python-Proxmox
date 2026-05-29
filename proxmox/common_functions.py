import json

class common_functions:

    @staticmethod
    def is_valid_json(data):
        try:
            json.dumps(data)  # Check if it can be serialized
            json.loads(json.dumps(data))  # Optional: round-trip check
            return True
        except (TypeError, ValueError):
            return False