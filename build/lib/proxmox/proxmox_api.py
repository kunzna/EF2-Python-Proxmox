import logging
import json
from proxmoxer import ProxmoxAPI
from .common_functions import common_functions

default_logger = logging.getLogger(__name__)
default_logger.setLevel(logging.INFO)

class ProxmoxClient:
    def __init__(
        self,
        host: str,
        user: str,
        token_name: str,
        token_value: str,
        logger=default_logger,
        verify_ssl=False
    ):
        self.logger = logger

        # Patch: Ensure host is always a string
        if isinstance(host, list):
            if host:
                host = host[0]
            else:
                host = ""
            self.logger.warning(f"Host was provided as a list, converted to string: {host}")

        self.host = host
        self.user = user
        self.token_name = token_name
        self.token_value = token_value
        self.verify_ssl = verify_ssl
        self.api = None  # Will hold the ProxmoxAPI connection

    def initialize_proxmoxapi(self):
        self.logger.info(f"ProxmoxClient - Building Client API Auth")
        self.api = ProxmoxAPI(
            self.host,
            user=self.user,
            token_name=self.token_name,
            token_value=self.token_value,
            verify_ssl=self.verify_ssl
        )
        return self.api

    def get_metrics(self, request):
        try:
            JSON = json.dumps(self.api(request).get())
            if common_functions.is_valid_json(JSON):
                self.logger.info(f"nodeMetricsJSON for '{JSON}' is valid JSON.")
            else:
                self.logger.warning(f"Invalid JSON for nodeMetricsJSON for '{JSON}'.")

        except Exception as e:
            self.logger.error(f"Error fetching node metrics for '{JSON}': {e}")
            JSON = {}  # ✅ Ensure it's defined even on failure

        return JSON

    def get_metrics_2(self, request):       
        try:
            #JSON = self.api(request).get()
            JSON = json.dumps(self.api(request).get())
            if common_functions.is_valid_json(JSON):
                self.logger.info(f"nodeMetricsJSON for '{JSON}' is valid JSON.")
            else:
                self.logger.warning(f"Invalid JSON for nodeMetricsJSON for '{JSON}'.")

        except Exception as e:
            self.logger.error(f"Error fetching node metrics for '{JSON}': {e}")
            JSON = {}  # ✅ Ensure it's defined even on failure

        return JSON

    def __repr__(self):
        return f"Cluster({self.name}"
