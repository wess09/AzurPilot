"""从后端参数模型生成前端类型和可审阅的 API 契约。"""
import json
from pathlib import Path

from module.api.protocol import AuthParams, LauncherTicketParams, SubscribeParams
from module.api.router import Method, Router
from module.api.ws_transport import DATA_TOPICS, FRAME_BYTES, REQUEST_BYTES, RESPONSE_BYTES


def typescript(schema, definitions):
    """将 JSON Schema 定义递归转换为 TypeScript 类型声明字符串。

    Args:
        schema (dict): 字段或对象的 JSON Schema 字典。
        definitions (dict): 包含引用定义 ($defs) 的字典。

    Returns:
        str: TypeScript 类型声明字符串。
    """
    if '$ref' in schema:
        return typescript(definitions[schema['$ref'].split('/')[-1]], definitions)
    if 'anyOf' in schema:
        return ' | '.join(typescript(item, definitions) for item in schema['anyOf'])
    if 'enum' in schema:
        return ' | '.join(json.dumps(item, ensure_ascii=False) for item in schema['enum'])
    kind = schema.get('type')
    if kind == 'array':
        return f'Array<{typescript(schema["items"], definitions)}>'
    if kind == 'object':
        fields = schema.get('properties', {})
        if not fields:
            return 'Record<string, unknown>' if schema.get('additionalProperties') else 'Record<string, never>'
        required = schema.get('required', [])
        return '{ ' + '; '.join(f'{key}{"" if key in required else "?"}: {typescript(value, definitions)}'
                               for key, value in fields.items()) + ' }'
    return {'string': 'string', 'integer': 'number', 'number': 'number',
            'boolean': 'boolean', 'null': 'null'}.get(kind, 'unknown')


def main():
    """扫描后端路由参数模型并导出 generated.ts 与 contract.json 契约文件。"""
    registry = dict(Router(None, None).methods)
    registry['auth.login'] = Method(AuthParams, lambda _: None)
    registry['auth.launcher'] = Method(LauncherTicketParams, lambda _: None, local_only=True)
    registry['events.subscribe'] = Method(SubscribeParams, lambda _: None)
    contracts, lines = {}, ['// 由 dev_tools.export_api_schema 生成，请勿手动编辑。', 'export interface Parameters {']
    data_methods = []
    for name, entry in registry.items():
        schema = entry.params.model_json_schema()
        contracts[name] = {'mutates': entry.mutates, 'params': schema}
        if entry.local_only:
            contracts[name]['localOnly'] = True
        if entry.data_channel:
            if entry.mutates:
                raise ValueError(f'{name}: 写操作必须走操作通道')
            contracts[name]['channel'] = 'data'
            data_methods.append(name)
        lines.append(f'  "{name}": {typescript(schema, schema.get("$defs", {}))}')
    lines.append('}')
    transport = {'frameBytes': FRAME_BYTES, 'requestBytes': REQUEST_BYTES, 'responseBytes': RESPONSE_BYTES,
                 'dataTopics': sorted(DATA_TOPICS)}
    lines.append(f'export const webSocketTransport = {json.dumps(transport)} as const')
    lines.append(f'export const dataMethods = {json.dumps(data_methods)} as const')
    from module.scheduler.models import (ProgramDocument, CardDefinition, PortDefinition, ResourceObservation,
                                        TaskInvocation, TaskOutcome, ProgramState)
    models = {}
    lines.append('export interface SchedulerModels {')
    for model in (ProgramDocument, CardDefinition, PortDefinition, ResourceObservation, TaskInvocation, TaskOutcome, ProgramState):
        schema = model.model_json_schema()
        models[model.__name__] = schema
        lines.append(f'  {model.__name__}: {typescript(schema, schema.get("$defs", {}))}')
    lines.append('}')
    directory = Path(__file__).resolve().parents[1] / 'frontend/src/api'
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'generated.ts').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    from module.api.launcher_protocol import (INCOMING_METHODS, AutostartState, LauncherCommand,
                                             LauncherEvent, LauncherRequest, LauncherResponse)
    launcher = {'version': 2, 'path': '/api/v2/launcher/ws',
                'incoming': {key: model.model_json_schema() for key, model in INCOMING_METHODS.items()},
                'outgoing': {'autostart.get': {'params': {}, 'result': AutostartState.model_json_schema()},
                             'autostart.set': {'params': registry['launcher.autostart.set'].params.model_json_schema(),
                                               'result': AutostartState.model_json_schema()}},
                'request': LauncherRequest.model_json_schema(), 'response': LauncherResponse.model_json_schema(),
                'command': LauncherCommand.model_json_schema(), 'event': LauncherEvent.model_json_schema()}
    (directory / 'contract.json').write_text(json.dumps({'version': 1, 'webSocketTransport': transport,
                                                        'methods': contracts, 'schedulerModels': models,
                                                        'launcher': launcher},
                                                     ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
