import logging
import json
from proxmoxer import ProxmoxAPI
from common_functions import common_functions

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
    
    def get_cluster_status(self):
        try:
            clustersStatusJSON = self.api.cluster.status.get()
            if not clustersStatusJSON or not isinstance(clustersStatusJSON, list):
                raise ValueError("Unexpected response format for cluster status.")
            elif common_functions.is_valid_json(clustersStatusJSON):
                self.logger.info("ClustersStatusJSON is valid JSON.")
            else:
                self.logger.warning("Invalid JSON for clustersStatusJSON.")
        except Exception as e:
            self.logger.error(f"Error fetching cluster status: {e}")
            clustersStatusJSON = []
        self.logger.info(f"Fetch and print cluster status: {clustersStatusJSON}")
        return clustersStatusJSON

    def get_node_status(self):
        try:
            nodesStatusJSON = self.api.nodes.get()
            if not nodesStatusJSON or not isinstance(nodesStatusJSON, list):
                raise ValueError("Unexpected response format for nodes status.")
            elif common_functions.is_valid_json(nodesStatusJSON):
                self.logger.info("nodesStatusJSON is valid JSON.")
            else:
                self.logger.warning("Invalid JSON for nodesStatusJSON.")
        except Exception as e:
            self.logger.error(f"Error fetching nodes status: {e}")
            nodesStatusJSON = []
        self.logger.info(f"CFetch and print node status: {nodesStatusJSON}")
        return nodesStatusJSON
    
    def get_node_info(self, nodeStatusJSON):
        nodeNamesArray = [item['node'] for item in nodeStatusJSON]
        self.logger.info(f"Extracted node names from nodeStatusJSON: {nodeNamesArray}")
        return nodeNamesArray
    
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
