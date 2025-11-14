# -*- coding: utf-8 -*-
from ...intunecdlib.BaseBackupModule import BaseBackupModule


class RolesBackupModule(BaseBackupModule):
    """A class used to backup Intune Roles

    Attributes:
        CONFIG_ENDPOINT (str): The endpoint to get the data from
        LOG_MESSAGE (str): The message to log when backing up the data
    """

    CONFIG_ENDPOINT = "/beta/deviceManagement/roleDefinitions"
    LOG_MESSAGE = "Backing up Role: "

    def __init__(self, *args, **kwargs):
        """Initializes the RolesBackupModule class

        Args:
            *args: The positional arguments to pass to the base class's __init__ method.
            **kwargs: The keyword arguments to pass to the base class's __init__ method.
        """
        super().__init__(*args, **kwargs)
        self.path = f"{self.path}/Roles/"
        self.audit_filter = "componentName eq 'RoleBasedAccessControl'"

    def _get_group_names(self, item) -> list:
        """Gets the group names from the group ids

        Args:
            item (dict): The group ids

        Returns:
            list: The group names
        """
        groups = []

        for group in item:
            try:
                group_name = self.make_graph_request(
                    endpoint=f"https://graph.microsoft.com/beta/groups/{group}",
                    params={"$select": "displayName"},
                )
            except Exception as e:
                self.log(
                    tag="error",
                    msg=f"Error getting group data from {self.endpoint + self.CONFIG_ENDPOINT}: {e}",
                )
                return None

            if group_name:
                group_name = group_name["displayName"]
                groups.append(group_name)

        return groups

    def main(self) -> dict[str, any]:
        """The main method to backup the Roles

        Returns:
            dict[str, any]: The results of the backup
        """
        try:
            self.graph_data = self.make_graph_request(
                endpoint=self.endpoint + self.CONFIG_ENDPOINT,
                params={"$filter": "isBuiltIn eq false"},
            )
        except Exception as e:
            self.log(
                tag="error",
                msg=f"Error getting Role data from {self.endpoint + self.CONFIG_ENDPOINT}: {e}",
            )
            return None

        if "assignments" not in self.exclude:
            # Stage 1: Batch fetch all role assignments
            role_ids = [{"id": item["id"]} for item in self.graph_data["value"]]
            
            assignments_map = {}
            if role_ids:
                assignment_responses = self.batch_request(
                    data=role_ids,
                    url="/beta/deviceManagement/roleDefinitions",
                    extra_url="/roleAssignments",
                    method="GET"
                )
                
                # Build map of role_id -> assignments
                for response in assignment_responses:
                    if response.get("body") and response["body"].get("value"):
                        role_id = response.get("id", "").split("/")[-2] if "/" in response.get("id", "") else None
                        if role_id:
                            assignments_map[role_id] = response["body"]["value"]
            
            # Stage 2: Collect all assignment IDs and batch fetch their details
            assignment_ids = []
            role_assignment_mapping = {}  # Map assignment_id -> role_id
            
            for item in self.graph_data["value"]:
                assignments = assignments_map.get(item["id"], [])
                for assignment in assignments:
                    assignment_ids.append({"id": assignment["id"]})
                    role_assignment_mapping[assignment["id"]] = item["id"]
            
            assignment_details_map = {}
            if assignment_ids:
                assignment_detail_responses = self.batch_request(
                    data=assignment_ids,
                    url="/beta/deviceManagement/roleAssignments",
                    extra_url="",
                    method="GET"
                )
                
                for response in assignment_detail_responses:
                    if response.get("body"):
                        assignment_data = response["body"]
                        assignment_details_map[assignment_data["id"]] = assignment_data
            
            # Stage 3: Collect all group IDs (scopeMembers and members)
            group_ids = set()
            for assignment_data in assignment_details_map.values():
                if assignment_data.get("scopeMembers"):
                    group_ids.update(assignment_data["scopeMembers"])
                if assignment_data.get("members"):
                    group_ids.update(assignment_data["members"])
            
            # Stage 4: Batch fetch all group names
            group_names_map = {}
            if group_ids:
                group_list = [{"id": group_id} for group_id in group_ids]
                group_responses = self.batch_request(
                    data=group_list,
                    url="/beta/groups",
                    extra_url="?$select=displayName",
                    method="GET"
                )
                
                for response in group_responses:
                    if response.get("body"):
                        group_data = response["body"]
                        group_names_map[group_data["id"]] = group_data["displayName"]
            
            # Stage 5: Assemble the data
            for item in self.graph_data["value"]:
                assignments = assignments_map.get(item["id"], [])
                
                if assignments:
                    item["roleAssignments"] = []
                    for assignment in assignments:
                        assignment_detail = assignment_details_map.get(assignment["id"])
                        if assignment_detail:
                            self.remove_keys(assignment_detail)
                            
                            # Replace group IDs with names
                            if assignment_detail.get("scopeMembers"):
                                assignment_detail["scopeMembers"] = [
                                    group_names_map.get(group_id, group_id)
                                    for group_id in assignment_detail["scopeMembers"]
                                ]
                            
                            if assignment_detail.get("members"):
                                assignment_detail["members"] = [
                                    group_names_map.get(group_id, group_id)
                                    for group_id in assignment_detail["members"]
                                ]
                            
                            # Remove resourceScopes
                            assignment_detail.pop("resourceScopes", None)
                            
                            item["roleAssignments"].append(assignment_detail)

        # Clean up role data
        for item in self.graph_data["value"]:
            item.pop("permissions", None)
            item["rolePermissions"][0].pop("actions", None)

        # Skip assignments for this module
        self.has_assignments = False

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
            self.log(tag="error", msg=f"Error processing Role data: {e}")
            return None

        return self.results
