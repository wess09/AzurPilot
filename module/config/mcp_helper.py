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
        """获取 args.json 中所有任务名称。"""
        return list(self.args_data.keys())

    def get_task_details(self, task_name: str) -> Dict[str, Any]:
        """获取任务的扁平化元数据，包括国际化名称和帮助文本。"""
        if task_name not in self.args_data:
            return {}

        task_args = self.args_data[task_name]
        task_i18n = self.i18n_data.get("Task", {}).get(task_name, {})
        
        # 供 AI 使用的结构化数据
        result = {
            "task_name": task_name,
            "display_name": task_i18n.get("name", task_name),
            "help": task_i18n.get("help", ""),
            "groups": {}
        }

        # 参数的国际化数据通常位于 i18n_data[task_name] 的顶层，
        # 或位于 Task[task_name]（通用任务描述符）。
        # AzurPilot 按任务级键组织国际化数据。
        spec_i18n = self.i18n_data.get(task_name, {})

        for group_name, group_data in task_args.items():
            if group_name == "Storage":  # 跳过 Storage 组
                continue
                
            # 解析组的国际化元数据
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
                
                # 选项翻译
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
        从配置数据的 Dashboard 部分提取资源信息。

        包含 Value、Limit、Total 及本地化名称。
        """
        dashboard = config_data.get("Dashboard", {})
        resources = {}
        
        # 获取 Dashboard 项的本地化名称
        # 通常位于 i18n_data["Gui"]["Dashboard"] 中
        dashboard_i18n = self.i18n_data.get("Gui", {}).get("Dashboard", {})
        
        for key, data in dashboard.items():
            if not isinstance(data, dict) or "Value" not in data:
                continue
                
            # 尝试获取友好的显示名称
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
