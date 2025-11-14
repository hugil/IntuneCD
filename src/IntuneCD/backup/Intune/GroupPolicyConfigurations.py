# -*- coding: utf-8 -*-
from ...intunecdlib.BaseBackupModule import BaseBackupModule


class GroupPolicyConfigurationsBackupModule(BaseBackupModule):
    """A class used to backup Intune Group Policy Configurations

    Attributes:
        CONFIG_ENDPOINT (str): The endpoint to get the data from
        LOG_MESSAGE (str): The message to log when backing up the data
    """

    CONFIG_ENDPOINT = "/beta/deviceManagement/groupPolicyConfigurations"
    LOG_MESSAGE = "Backing up Device Configuration: "

    def __init__(self, *args, **kwargs):
        """Initializes the GroupPolicyConfigurationsBackupModule class

        Args:
            *args: The positional arguments to pass to the base class's __init__ method.
            **kwargs: The keyword arguments to pass to the base class's __init__ method.
        """
        super().__init__(*args, **kwargs)
        self.path = f"{self.path}/Group Policy Configurations/"
        self.audit_filter = "componentName eq 'DeviceConfiguration'"
        self.assignment_endpoint = "deviceManagement/groupPolicyConfigurations/"
        self.assignment_extra_url = "/assignments"

    def main(self) -> dict[str, any]:
        """The main method to backup the Group Policy Configurations

        Returns:
            dict[str, any]: The results of the backup
        """
        try:
            self.graph_data = self.make_graph_request(
                endpoint=self.endpoint + self.CONFIG_ENDPOINT
            )
        except Exception as e:
            self.log(
                tag="error",
                msg=f"Error getting Group Policy Configuration data from {self.endpoint + self.CONFIG_ENDPOINT}: {e}",
            )
            return None

        # Stage 1: Batch fetch all definition values for all policies
        definition_requests = []
        for item in self.graph_data["value"]:
            definition_requests.append({"id": item["id"]})
        
        definitions_map = {}
        if definition_requests:
            definition_responses = self.batch_request(
                data=definition_requests,
                url="/beta/deviceManagement/groupPolicyConfigurations",
                extra_url="/definitionValues?$expand=definition",
                method="GET"
            )
            
            # Build map of policy_id -> definitions
            for response in definition_responses:
                if response.get("body") and response["body"].get("value"):
                    # Extract policy ID from response
                    policy_id = response.get("id", "").split("/")[-2] if "/" in response.get("id", "") else None
                    if policy_id:
                        definitions_map[policy_id] = response["body"]["value"]

        # Stage 2: Collect all presentation requests and batch fetch them
        presentation_requests = []
        policy_definition_map = {}  # Map to track which presentation belongs to which policy/definition
        
        for item in self.graph_data["value"]:
            policy_id = item["id"]
            definitions = definitions_map.get(policy_id, [])
            
            for definition in definitions:
                presentation_requests.append({
                    "id": f"{policy_id}/definitionValues/{definition['id']}"
                })
                # Store mapping for later reconstruction
                key = f"{policy_id}/definitionValues/{definition['id']}"
                policy_definition_map[key] = (policy_id, definition["id"])
        
        presentations_map = {}
        if presentation_requests:
            presentation_responses = self.batch_request(
                data=presentation_requests,
                url="/beta/deviceManagement/groupPolicyConfigurations",
                extra_url="/presentationValues?$expand=presentation",
                method="GET"
            )
            
            # Build map of policy_id/definition_id -> presentations
            for response in presentation_responses:
                if response.get("body") and response["body"].get("value"):
                    # Extract the composite key from response ID
                    response_id = response.get("id", "")
                    # Parse the ID to get policy and definition IDs
                    if "/presentationValues" in response_id:
                        key = response_id.split("/presentationValues")[0]
                        presentations_map[key] = response["body"]["value"]

        # Stage 3: Assemble the data structure
        for item in self.graph_data["value"]:
            policy_id = item["id"]
            definitions = definitions_map.get(policy_id, [])
            item["definitionValues"] = definitions
            
            for definition in item["definitionValues"]:
                key = f"{policy_id}/definitionValues/{definition['id']}"
                definition["presentationValues"] = presentations_map.get(key, [])

        try:
            self.results = self.process_data(
                data=self.graph_data["value"],
                filetype=self.filetype,
                path=self.path,
                name_key="displayName",
                log_message=self.LOG_MESSAGE,
                audit_compare_info={"type": "resourceId", "value_key": "id"},
            )
        except Exception as e:
            self.log(
                tag="error",
                msg=f"Error processing Group Policy Configuration data: {e}",
            )
            return None

        return self.results
