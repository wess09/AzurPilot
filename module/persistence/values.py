"""将自由值保存为 SQLite 类型化树，不保存序列化载荷。"""
import json
import math

from module.persistence.database import register_instance


def normalize(value, *, special=False):
    """沿用原接口可序列化范围及键转换；JSON 只在内存边界使用。"""
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=special))


def scalar(value, kind):
    """返回可无损用于业务列的值；不适配的值由兼容树保存。"""
    if value is None:
        return True, None
    if kind == 'T':
        return type(value) is str, value
    if kind == 'I':
        return type(value) is int and -(2 ** 63) <= value < 2 ** 63, value
    if kind == 'B':
        return type(value) is bool, int(value) if type(value) is bool else value
    if kind == 'R':
        valid = type(value) in (int, float) and abs(value) <= 1.7976931348623157e308 and math.isfinite(value)
        return valid and (type(value) is float or int(float(value)) == value), value
    return value in kind if type(value) is str else False, value


def write_value(connection, instance, value, *, document_id=None, month=None, runtime=False, ship=False):
    """将嵌套值递归写入带类型标记的存储节点。"""
    register_instance(connection, instance)
    owner = (document_id, month, instance if runtime else None, instance if ship else None)
    if sum(item is not None for item in owner) != 1:
        raise ValueError('扩展值需要唯一的所属上下文')
    value = normalize(value, special=month is not None or ship)
    value_id = connection.execute('''INSERT INTO typed_value_sets
        (instance,document_id,month,runtime_instance,ship_instance) VALUES(?,?,?,?,?)''', (instance, *owner)).lastrowid
    rows = []

    def visit(item, parent=None, key=None, ordinal=0):
        """遍历并编码嵌套数据中的各级子项。"""
        node = len(rows) + 1
        integer = real = text = None
        if item is None:
            kind = 'null'
        elif type(item) is bool:
            kind, integer = 'bool', int(item)
        elif type(item) is int:
            if -(2 ** 63) <= item < 2 ** 63:
                kind, integer = 'int', item
            else:
                kind, text = 'bigint', str(item)
        elif type(item) is float:
            if math.isfinite(item):
                kind, real = 'real', item
            else:
                kind, text = 'special_real', 'nan' if math.isnan(item) else '+inf' if item > 0 else '-inf'
        elif type(item) is str:
            kind, text = 'string', item
        elif type(item) is dict:
            kind = 'object'
        elif type(item) is list:
            kind = 'array'
        else:
            raise TypeError('扩展值类型不受支持')
        rows.append((value_id, node, parent, key, ordinal, kind, integer, real, text))
        children = item.items() if kind == 'object' else enumerate(item) if kind == 'array' else ()
        for position, (member, child) in enumerate(children):
            visit(child, node, member if kind == 'object' else None, position)

    visit(value)
    connection.executemany('INSERT INTO typed_value_nodes VALUES(?,?,?,?,?,?,?,?,?)', rows)
    return value_id


def read_value(connection, value_id):
    """从类型化节点恢复原始的嵌套业务值。"""
    rows = connection.execute('SELECT * FROM typed_value_nodes WHERE value_set_id=? ORDER BY node_no', (value_id,)).fetchall()
    if not rows or rows[0]['node_no'] != 1 or rows[0]['parent_no'] is not None:
        raise ValueError('扩展值缺少唯一根节点')
    values, parents, next_ordinals = {}, {}, {}
    for row in rows:
        kind = row['kind']
        if kind in ('null', 'object', 'array'):
            value = None if kind == 'null' else {} if kind == 'object' else []
        elif kind in ('int', 'bool'):
            value = bool(row['int_value']) if kind == 'bool' else row['int_value']
        elif kind == 'bigint':
            value = int(row['text_value'])
            if str(value) != row['text_value']:
                raise ValueError('扩展大整数格式不规范')
        elif kind == 'real':
            value = row['real_value']
        elif kind == 'special_real':
            value = {'nan': float('nan'), '+inf': float('inf'), '-inf': -float('inf')}[row['text_value']]
        elif kind == 'string':
            value = row['text_value']
        else:
            raise ValueError('未知扩展值类型')
        parent = row['parent_no']
        if parent is not None:
            if parent not in parents or row['ordinal'] != next_ordinals.get(parent, 0):
                raise ValueError('扩展节点顺序或父节点无效')
            next_ordinals[parent] = row['ordinal'] + 1
            container = values[parent]
            if parents[parent] == 'object' and row['member_key'] is not None:
                container[row['member_key']] = value
            elif parents[parent] == 'array' and row['member_key'] is None:
                container.append(value)
            else:
                raise ValueError('扩展节点与容器类型不符')
        elif row['node_no'] != 1:
            raise ValueError('扩展值存在多个根节点')
        values[row['node_no']], parents[row['node_no']] = value, kind
    return values[1]
