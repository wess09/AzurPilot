"""调度图和运行记录的原生表编解码。"""
from module.persistence.database import register_instance
from module.persistence.snapshots import insert, load_row, save_row
from module.persistence.values import normalize, read_value, scalar, write_value

RECORD_NAMES = ('lastExecuted', 'rotation', 'cooldowns', 'quotas', 'results', 'lastResult')
RESULT_FIELDS = (('task', 'task', 'T'), ('status', 'status', 'T'),
                 ('reason', 'reason', 'T'), ('finishedAt', 'finished_at', 'T'))
RUNTIME_TABLES = ('scheduler_state_variables', 'scheduler_runtime', 'scheduler_counters',
                  'scheduler_times', 'scheduler_results', 'scheduler_observations', 'scheduler_record_extensions')


def numeric_columns(value):
    """返回调度变量允许使用的数值列定义。"""
    if type(value) is int:
        return {'kind': 'int', 'int_value': value, 'real_value': None, 'text_value': None} if -(2 ** 63) <= value < 2 ** 63 else {
            'kind': 'bigint', 'int_value': None, 'real_value': None, 'text_value': str(value)}
    if type(value) is float and scalar(value, 'R')[0]:
        return {'kind': 'real', 'int_value': None, 'real_value': value, 'text_value': None}
    raise ValueError('调度位置必须是有限数值')


def numeric_value(row):
    """将调度数据转换为受支持的数值表示。"""
    return int(row['text_value']) if row['kind'] == 'bigint' else row['int_value'] if row['kind'] == 'int' else row['real_value']


def save_document(connection, instance, slot, document):
    """持久化指定实例的调度定义文档。"""
    from module.scheduler.models import ProgramDocument
    document = ProgramDocument.model_validate(normalize(document)).model_dump()
    connection.execute('DELETE FROM scheduler_documents WHERE instance=? AND slot=?', (instance, slot))
    document_id = insert(connection, 'scheduler_documents', dict(instance=instance, slot=slot,
        schema_version=document['schemaVersion'], name=document['name']))
    owner = {'instance': instance, 'document_id': document_id}
    for graph_no, graph in enumerate([document, *document['subgraphs']]):
        keys = {'document_id': document_id, 'graph_no': graph_no}
        insert(connection, 'scheduler_graphs', dict(keys, subgraph_id=graph['id'] if graph_no else None,
            name=graph['name'] if graph_no else None, pure=int(graph['pure']) if graph_no else None, entry_node=graph['entry']))
        for node_no, node in enumerate(graph['nodes']):
            node_keys = dict(keys, node_no=node_no)
            insert(connection, 'scheduler_nodes', dict(node_keys, node_id=node['id'], type=node['type'],
                label=node['label'], comment=node['comment']))
            for name, value in node['params'].items():
                insert(connection, 'scheduler_node_parameters', dict(node_keys, name=name,
                    value_set_id=write_value(connection, value=value, **owner)))
            for name, value in node['position'].items():
                insert(connection, 'scheduler_node_positions', dict(node_keys, name=name, **numeric_columns(value)))
        for edge_no, edge in enumerate(graph['edges']):
            insert(connection, 'scheduler_edges', dict(keys, edge_no=edge_no, edge_id=edge['id'],
                source_node=edge['source'], source_port=edge['sourcePort'], target_node=edge['target'],
                target_port=edge['targetPort'], kind=edge['kind']))
        if graph_no:
            for direction, field in (('input', 'inputs'), ('output', 'outputs')):
                for ordinal, port in enumerate(graph[field]):
                    insert(connection, 'scheduler_graph_ports', dict(keys, direction=direction, ordinal=ordinal,
                        name=port['name'], type=port['type'], required=int(port['required'])))
    for ordinal, variable in enumerate(document['variables']):
        insert(connection, 'scheduler_variable_definitions', dict(document_id=document_id, ordinal=ordinal,
            name=variable['name'], type=variable['type'], persistent=int(variable['persistent']),
            value_set_id=write_value(connection, value=variable['initial'], **owner)))
    for name, value in document['viewport'].items():
        insert(connection, 'scheduler_viewport_fields', dict(document_id=document_id, name=name, **numeric_columns(value)))


def read_document(connection, instance, slot):
    """读取指定实例的调度定义文档。"""
    document = connection.execute('SELECT * FROM scheduler_documents WHERE instance=? AND slot=?', (instance, slot)).fetchone()
    if document is None:
        return None
    document_id = document['id']
    graphs = []
    for graph in connection.execute('SELECT * FROM scheduler_graphs WHERE document_id=? ORDER BY graph_no', (document_id,)):
        key = (document_id, graph['graph_no'])
        nodes = []
        for node in connection.execute('SELECT * FROM scheduler_nodes WHERE document_id=? AND graph_no=? ORDER BY node_no', key):
            node_key = (*key, node['node_no'])
            params = {row['name']: read_value(connection, row['value_set_id']) for row in connection.execute(
                'SELECT * FROM scheduler_node_parameters WHERE document_id=? AND graph_no=? AND node_no=? ORDER BY rowid', node_key)}
            position = {row['name']: numeric_value(row) for row in connection.execute(
                'SELECT * FROM scheduler_node_positions WHERE document_id=? AND graph_no=? AND node_no=? ORDER BY rowid', node_key)}
            nodes.append(dict(id=node['node_id'], type=node['type'], label=node['label'], comment=node['comment'], params=params, position=position))
        edges = [dict(id=row['edge_id'], source=row['source_node'], sourcePort=row['source_port'],
            target=row['target_node'], targetPort=row['target_port'], kind=row['kind']) for row in connection.execute(
                'SELECT * FROM scheduler_edges WHERE document_id=? AND graph_no=? ORDER BY edge_no', key)]
        value = dict(entry=graph['entry_node'], nodes=nodes, edges=edges)
        if graph['graph_no']:
            value.update(id=graph['subgraph_id'], name=graph['name'], pure=bool(graph['pure']))
            for direction, field in (('input', 'inputs'), ('output', 'outputs')):
                value[field] = [dict(name=row['name'], type=row['type'], required=bool(row['required'])) for row in connection.execute(
                    'SELECT * FROM scheduler_graph_ports WHERE document_id=? AND graph_no=? AND direction=? ORDER BY ordinal', (*key, direction))]
        graphs.append(value)
    if not graphs:
        raise ValueError('调度文档缺少主图')
    variables = [dict(name=row['name'], type=row['type'], initial=read_value(connection, row['value_set_id']),
        persistent=bool(row['persistent'])) for row in connection.execute(
            'SELECT * FROM scheduler_variable_definitions WHERE document_id=? ORDER BY ordinal', (document_id,))]
    viewport = {row['name']: numeric_value(row) for row in connection.execute(
        'SELECT * FROM scheduler_viewport_fields WHERE document_id=? ORDER BY rowid', (document_id,))}
    return dict(graphs[0], schemaVersion=document['schema_version'], name=document['name'],
                subgraphs=graphs[1:], variables=variables, viewport=viewport)


def save_program(connection, instance, data, revision):
    """保存调度程序及其当前修订版本。"""
    register_instance(connection, instance)
    connection.execute('''INSERT INTO scheduler_programs VALUES(?,?,?,?) ON CONFLICT(instance)
        DO UPDATE SET mode=excluded.mode,generation=excluded.generation,revision=excluded.revision''',
        (instance, data['mode'], data['generation'], revision))
    save_document(connection, instance, 'draft', data['draft'])
    if data.get('active') is not None:
        save_document(connection, instance, 'active', data['active'])
    else:
        connection.execute("DELETE FROM scheduler_documents WHERE instance=? AND slot='active'", (instance,))


def read_program(connection, instance):
    """读取已存储的调度程序及其修订信息。"""
    row = connection.execute('SELECT * FROM scheduler_programs WHERE instance=?', (instance,)).fetchone()
    if row is None:
        return None
    return dict(mode=row['mode'], generation=row['generation'], revision=row['revision'],
                draft=read_document(connection, instance, 'draft'), active=read_document(connection, instance, 'active'))


def relational_record(name, value):
    """将调度节点映射为关系型数据记录。"""
    if name == 'lastResult':
        return type(value) is dict
    if type(value) is not dict:
        return False
    if name in ('lastExecuted', 'cooldowns'):
        return all(type(item) is str for item in value.values())
    if name == 'rotation':
        return all(item is not None and scalar(item, 'I')[0] for item in value.values())
    if name == 'quotas':
        return all(type(days) is dict and days and all(len(day) == 10 and item is not None and scalar(item, 'I')[0]
            for day, item in days.items()) for days in value.values())
    if name == 'results':
        return all(type(item) is dict for item in value.values())
    return False


def save_persistent(connection, instance, data):
    """写入调度器需要持久保留的运行状态。"""
    data = normalize(data)
    register_instance(connection, instance)
    for table in RUNTIME_TABLES:
        if table != 'scheduler_observations':
            connection.execute(f'DELETE FROM {table} WHERE instance=?', (instance,))
    connection.execute('DELETE FROM typed_value_sets WHERE runtime_instance=?', (instance,))
    owner = {'instance': instance, 'runtime': True}
    for name, value in data.get('variables', {}).items():
        insert(connection, 'scheduler_state_variables', dict(instance=instance, name=name,
            value_set_id=write_value(connection, value=value, **owner)))
    records = data.get('records', {})
    mask = sum(1 << index for index, name in enumerate(RECORD_NAMES) if name in records)
    insert(connection, 'scheduler_runtime', dict(instance=instance, in_flight=data.get('inFlight'), record_mask=mask))
    for name, value in records.items():
        if not relational_record(name, value):
            insert(connection, 'scheduler_record_extensions', dict(instance=instance, name=name,
                value_set_id=write_value(connection, value=value, **owner)))
        elif name in ('lastExecuted', 'cooldowns'):
            kind = 'last_executed' if name == 'lastExecuted' else 'cooldown'
            for key, timestamp in value.items():
                insert(connection, 'scheduler_times', dict(instance=instance, kind=kind, record_key=key, recorded_at=timestamp))
        elif name == 'rotation':
            for key, count in value.items():
                insert(connection, 'scheduler_counters', dict(instance=instance, kind='rotation', record_key=key, server_day='', count=count))
        elif name == 'quotas':
            for key, days in value.items():
                for day, count in days.items():
                    insert(connection, 'scheduler_counters', dict(instance=instance, kind='quota', record_key=key, server_day=day, count=count))
        else:
            results = value.items() if name == 'results' else (('', value),)
            for key, result in results:
                save_row(connection, 'scheduler_results', dict(instance=instance, scope='task' if name == 'results' else 'last',
                    record_key=key), result, RESULT_FIELDS, owner)


def read_persistent(connection, instance):
    """读取实例的调度持久变量与运行状态。"""
    variables = {row['name']: read_value(connection, row['value_set_id']) for row in connection.execute(
        'SELECT * FROM scheduler_state_variables WHERE instance=? ORDER BY rowid', (instance,))}
    runtime = connection.execute('SELECT * FROM scheduler_runtime WHERE instance=?', (instance,)).fetchone()
    records = {name: {} for index, name in enumerate(RECORD_NAMES) if runtime and runtime['record_mask'] & (1 << index)}
    for row in connection.execute('SELECT * FROM scheduler_times WHERE instance=? ORDER BY rowid', (instance,)):
        records.setdefault('lastExecuted' if row['kind'] == 'last_executed' else 'cooldowns', {})[row['record_key']] = row['recorded_at']
    for row in connection.execute('SELECT * FROM scheduler_counters WHERE instance=? ORDER BY rowid', (instance,)):
        if row['kind'] == 'rotation':
            records.setdefault('rotation', {})[row['record_key']] = row['count']
        else:
            records.setdefault('quotas', {}).setdefault(row['record_key'], {})[row['server_day']] = row['count']
    for row in connection.execute('SELECT * FROM scheduler_results WHERE instance=? ORDER BY rowid', (instance,)):
        value = load_row(connection, row, RESULT_FIELDS)
        if row['scope'] == 'last':
            records['lastResult'] = value
        else:
            records.setdefault('results', {})[row['record_key']] = value
    for row in connection.execute('SELECT * FROM scheduler_record_extensions WHERE instance=? ORDER BY rowid', (instance,)):
        records[row['name']] = read_value(connection, row['value_set_id'])
    result = {'variables': variables, 'records': records}
    if runtime and runtime['in_flight']:
        result['inFlight'] = runtime['in_flight']
    return result if any(result.values()) else {}


def write_observation(connection, instance, name, value, timestamp, source):
    """保存带观察时间与来源的资源观测。"""
    values = value if type(value) is dict else {'Value': value}
    numbers = [values.get(key) for key in ('Value', 'Limit', 'Total')]
    if any(not scalar(number, 'R')[0] for number in numbers):
        raise ValueError('调度观察值必须为有限数值或空值')
    register_instance(connection, instance)
    connection.execute('''INSERT INTO scheduler_observations VALUES(?,?,?,?,?,?,?) ON CONFLICT(instance,resource)
        DO UPDATE SET value=excluded.value,resource_limit=COALESCE(excluded.resource_limit,scheduler_observations.resource_limit),
        total=COALESCE(excluded.total,scheduler_observations.total),observed_at=excluded.observed_at,source=excluded.source''',
        (instance, name, *(float(number) if number is not None else None for number in numbers), timestamp, source))


def read_observations(connection, instance):
    """汇集指定实例已保存的资源观测。"""
    return {row['resource']: dict(Value=row['value'], Limit=row['resource_limit'], Total=row['total'],
        observedAt=row['observed_at'], source=row['source']) for row in connection.execute(
        'SELECT * FROM scheduler_observations WHERE instance=?', (instance,))}


def delete_scheduler(connection, instance):
    """清理指定实例的普通调度数据。"""
    connection.execute('DELETE FROM scheduler_programs WHERE instance=?', (instance,))
    for table in RUNTIME_TABLES:
        connection.execute(f'DELETE FROM {table} WHERE instance=?', (instance,))
    connection.execute('DELETE FROM typed_value_sets WHERE runtime_instance=?', (instance,))


def copy_scheduler(source, destination, instance, target=None):
    """归档与恢复重新分配内部 ID，所有读取固定在一个源快照中。"""
    target = target or instance
    program = read_program(source, instance)
    if program:
        save_program(destination, target, program, program['revision'])
    persistent = read_persistent(source, instance)
    if persistent:
        save_persistent(destination, target, persistent)
    for name, observation in read_observations(source, instance).items():
        write_observation(destination, target, name, observation, observation['observedAt'], observation['source'])
