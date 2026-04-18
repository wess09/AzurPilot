import json
import os
from typing import Dict, Any, List, Optional
from module.config.utils import read_file, filepath_args, filepath_i18n

class McpConfigHelper:
    def __init__(self, lang="zh-CN"):
        self.lang = lang
        self.args_data = read_file(filepath_args("args"))
        self.i18n_data = read_file(filepath_i18n(lang))

    def get_tasks(self) -> List[str]:
        """Get all task names from args.json."""
        return list(self.args_data.keys())

    def get_task_details(self, task_name: str) -> Dict[str, Any]:
        """Get flattened metadata for a task, including i18n names and help text."""
        if task_name not in self.args_data:
            return {}

        task_args = self.args_data[task_name]
        task_i18n = self.i18n_data.get("Task", {}).get(task_name, {})
        
        # Structure for AI
        result = {
            "task_name": task_name,
            "display_name": task_i18n.get("name", task_name),
            "help": task_i18n.get("help", ""),
            "groups": {}
        }

        # i18n data for arguments is usually in the top-level of i18n_data[task_name]
        # or in Task[task_name] if it's a generic task descriptor.
        # Actually, ALAS organizes i18n by task-level keys.
        spec_i18n = self.i18n_data.get(task_name, {})

        for group_name, group_data in task_args.items():
            if group_name == "Storage": # Skip storage
                continue
                
            # Resolve group i18n metadata once
            group_meta = spec_i18n.get(group_name, {})
            info = group_meta.get("_info", {})
            group_display = info.get("name", group_name)
            group_help = info.get("help", "")

            group_result = {
                "display_name": group_display,
                "help": group_help,
                "arguments": {}
            }

            for arg_name, arg_meta in group_data.items():
                arg_i18n = spec_i18n.get(group_name, {}).get(arg_name, {})
                
                # Option translations
                options = arg_meta.get("option", [])
                translated_options = {}
                for opt in options:
                    translated_options[str(opt)] = arg_i18n.get(str(opt), str(opt))

                group_result["arguments"][arg_name] = {
                    "display_name": arg_i18n.get("name", arg_name),
                    "help": arg_i18n.get("help", ""),
                    "type": arg_meta.get("type", "input"),
                    "default": arg_meta.get("value"),
                    "options": translated_options if translated_options else None
                }
            
            result["groups"][group_name] = group_result

        return result

    def get_dashboard_resources(self, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract resources from Dashboard section of config data.
        Includes Value, Limit, Total and localized names.
        """
        dashboard = config_data.get("Dashboard", {})
        resources = {}
        
        # Get localized names for Dashboard items
        # Usually found in i18n_data["Gui"]["Dashboard"] or similar
        dashboard_i18n = self.i18n_data.get("Gui", {}).get("Dashboard", {})
        
        for key, data in dashboard.items():
            if not isinstance(data, dict) or "Value" not in data:
                continue
                
            # Try to get a friendly name
            label = dashboard_i18n.get(key, key)
            
            res_item = {
                "label": label,
                "value": data.get("Value"),
            }
            if "Limit" in data:
                res_item["limit"] = data["Limit"]
            if "Total" in data:
                res_item["total"] = data["Total"]
            if "Record" in data:
                res_item["last_update"] = data["Record"]
                
            resources[key] = res_item
            
        return resources
