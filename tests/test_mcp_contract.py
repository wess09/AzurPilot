"""MCP 注册表、协议结果和旧名称兼容边界。"""
import unittest
from unittest.mock import Mock

import jsonschema

import mcp_server_sse as mcp
from module.mcp.registry import LEGACY_REGISTRY, TOOL_REGISTRY, tool_definitions
from module.mcp.tools import Tools


def schema_nodes(node):
    """遍历 Schema 树，产出所有处于 Schema 位置的节点。

    ``additionalProperties`` 的布尔值是开关而非属性 Schema，故不展开。
    """
    if not isinstance(node, dict):
        yield node
        return
    yield node
    for key in ('properties', 'patternProperties', '$defs', 'definitions'):
        value = node.get(key)
        if isinstance(value, dict):
            for child in value.values():
                yield from schema_nodes(child)
    for key in ('items', 'not', 'if', 'then', 'else', 'contains', 'propertyNames'):
        if key in node:
            yield from schema_nodes(node[key])
    for key in ('anyOf', 'oneOf', 'allOf'):
        for child in node.get(key) or []:
            yield from schema_nodes(child)


class McpContractTest(unittest.IsolatedAsyncioTestCase):
    def test_schema_properties_are_objects_for_client_compatibility(self):
        """布尔 Schema / const 会让部分客户端拒绝整份 tools/list 响应。"""
        for tool in tool_definitions(allow_legacy=True):
            for label, schema in (('inputSchema', tool.inputSchema),
                                  ('outputSchema', tool.outputSchema)):
                for node in schema_nodes(schema):
                    with self.subTest(tool=tool.name, schema=label):
                        self.assertIsInstance(node, dict)
                        self.assertNotIn('const', node)

    def test_default_registry_has_only_stable_azurpilot_names(self):
        tools = tool_definitions()
        names = [tool.name for tool in tools]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(name.startswith('azurpilot_') for name in names))
        self.assertNotIn('azurpilot_clear_scheduler_queue', names)
        self.assertNotIn('clear_scheduler_queue', names)
        self.assertEqual(names, [spec.name for spec in TOOL_REGISTRY])
        for tool in tools:
            with self.subTest(tool=tool.name):
                self.assertIsNotNone(tool.outputSchema)
                self.assertFalse(tool.inputSchema.get('additionalProperties', True))
                self.assertIsNotNone(tool.annotations)
                self.assertFalse(tool.annotations.openWorldHint)
                jsonschema.validators.validator_for(tool.inputSchema).check_schema(tool.inputSchema)
                jsonschema.validators.validator_for(tool.outputSchema).check_schema(tool.outputSchema)

    def test_legacy_names_are_centralized_and_opt_in(self):
        default = {tool.name for tool in tool_definitions()}
        compatible = {tool.name for tool in tool_definitions(allow_legacy=True)}
        legacy = {spec.name for spec in LEGACY_REGISTRY}
        self.assertTrue(legacy.isdisjoint(default))
        self.assertTrue(legacy <= compatible)
        self.assertIn('update_alas', legacy)
        self.assertIn('clear_scheduler_queue', legacy)
        self.assertTrue(all(tool.name.startswith('azurpilot_')
                            for tool in tool_definitions() if tool.name in default))

    async def test_protocol_input_error_is_structured_and_correctable(self):
        tools = Tools()
        token = mcp.active_tools.set(tools)
        try:
            result = await mcp.call_tool('azurpilot_patch_config', {
                'instance': 'demo', 'revision': '0' * 64,
                'changes': [{'path': 'Main.Option.Count', 'value': 4}],
                'unknown': True,
            })
        finally:
            mcp.active_tools.reset(token)
            await tools.close()
        self.assertTrue(result.isError)
        self.assertEqual('INVALID_PARAMS', result.structuredContent['error']['code'])
        self.assertEqual('additionalProperties', result.structuredContent['error']['details']['rule'])
        self.assertEqual('azurpilot_patch_config', result.structuredContent['next_step']['tool'])

    async def test_protocol_success_has_text_structured_content_and_valid_output(self):
        runtime = Mock()
        runtime.instances.return_value = [{'name': 'demo', 'status': 'stopped', 'currentTask': None}]
        tools = Tools(Mock(), runtime)
        token = mcp.active_tools.set(tools)
        try:
            result = await mcp.call_tool('azurpilot_list_instances', {})
        finally:
            mcp.active_tools.reset(token)
            await tools.close()
        self.assertFalse(result.isError)
        self.assertIn('demo(stopped)', result.content[0].text)
        self.assertEqual('demo', result.structuredContent['instances'][0]['name'])
        definition = next(tool for tool in tool_definitions() if tool.name == 'azurpilot_list_instances')
        jsonschema.validate(result.structuredContent, definition.outputSchema)

    async def test_error_envelope_is_valid_against_output_schema(self):
        """客户端会用同一份 outputSchema 校验 isError=true 的 structuredContent。"""
        tools = Tools()
        token = mcp.active_tools.set(tools)
        try:
            result = await mcp.call_tool('azurpilot_get_task_schema', {'task': '__missing__'})
        finally:
            mcp.active_tools.reset(token)
            await tools.close()
        self.assertTrue(result.isError)
        definition = next(tool for tool in tool_definitions()
                          if tool.name == 'azurpilot_get_task_schema')
        jsonschema.validate(result.structuredContent, definition.outputSchema)
        self.assertEqual('NOT_FOUND', result.structuredContent['error']['code'])
        self.assertIn('下一步', result.content[0].text)

    def test_failed_status_and_error_fields_declared_for_every_tool(self):
        for tool in tool_definitions(allow_legacy=True):
            with self.subTest(tool=tool.name):
                self.assertIn('failed', tool.outputSchema['properties']['status']['enum'])
                for field in ('error', 'next_step', 'operation_id', 'deduplicated'):
                    self.assertIn(field, tool.outputSchema['properties'])
                # 失败信封不应因 additionalProperties: false 被客户端拒绝
                jsonschema.validate({
                    'status': 'failed',
                    'error': {'code': 'DEVICE_IN_USE', 'message': '设备被占用',
                              'retryable': False, 'outcome_certain': True},
                    'next_step': {'tool': 'azurpilot_get_context', 'reason': '确认状态'},
                    'operation_id': '0' * 32,
                    'deduplicated': True,
                }, tool.outputSchema)

    async def test_old_name_is_not_callable_on_default_endpoint(self):
        tools = Tools()
        token = mcp.active_tools.set(tools)
        try:
            result = await mcp.call_tool('list_instances', {})
        finally:
            mcp.active_tools.reset(token)
            await tools.close()
        self.assertTrue(result.isError)
        self.assertEqual('UNKNOWN_TOOL', result.structuredContent['error']['code'])


if __name__ == '__main__':
    unittest.main()
