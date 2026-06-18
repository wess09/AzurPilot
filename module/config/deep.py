from collections import deque

# deep_* 系列函数用于访问嵌套字典。
# 以高性能为目标，因此代码可读性较低。
# 一般性能基准测试中，耗时排序如下：
# - 当 key 存在时
#   try: dict[key] except KeyError << dict.get(key) < if key in dict: dict[key]
# - 当 key 不存在时
#   if key in dict: dict[key] < dict.get(key) <<< try: dict[key] except KeyError

OP_ADD = 'add'
OP_SET = 'set'
OP_DEL = 'del'


def deep_get(d, keys, default=None):
    """从嵌套字典和列表中安全地获取值。

    参考: https://stackoverflow.com/questions/25833613/safe-method-to-get-value-of-nested-dictionary

    Args:
        d: 目标字典。
        keys (list[str] | str): 键路径，如 ['Scheduler', 'NextRun', 'value']。
            也支持点分字符串，如 'Scheduler.NextRun.value'。
        default: 键不存在时的默认返回值。

    Returns:
        对应键路径的值，不存在时返回 default。
    """
    # 240 + 30 * depth (ns)
    if type(keys) is str:
        keys = keys.split('.')

    try:
        for k in keys:
            d = d[k]
        return d
    # 键不存在
    except KeyError:
        return default
    # 索引越界
    except IndexError:
        return default
    # keys 不可迭代或 d 不是字典（列表索引必须是整数或切片，不能是 str）
    except TypeError:
        return default


def deep_get_with_error(d, keys):
    """从嵌套字典和列表中获取值，键不存在时抛出 KeyError。

    Args:
        d: 目标字典。
        keys (list[str] | str): 键路径，如 ['Scheduler', 'NextRun', 'value']。
            也支持点分字符串，如 'Scheduler.NextRun.value'。

    Returns:
        对应键路径的值。

    Raises:
        KeyError: 键不存在时抛出。
    """
    # 240 + 30 * depth (ns)
    if type(keys) is str:
        keys = keys.split('.')

    try:
        for k in keys:
            d = d[k]
        return d
    # 键不存在（KeyError 直接透传）
    # except KeyError:
    #     raise
    # 索引越界
    except IndexError:
        raise KeyError
    # keys 不可迭代或 d 不是字典（列表索引必须是整数或切片，不能是 str）
    except TypeError:
        raise KeyError


def deep_exist(d, keys):
    """检查嵌套字典或列表中是否存在指定键路径。

    Args:
        d: 目标字典。
        keys (str | list): 键路径，如 'Scheduler.NextRun.value' 或列表形式。

    Returns:
        bool: 键是否存在。
    """
    # 240 + 30 * depth (ns)
    if type(keys) is str:
        keys = keys.split('.')

    try:
        for k in keys:
            d = d[k]
        return True
    # 键不存在
    except KeyError:
        return False
    # 索引越界
    except IndexError:
        return False
    # keys 不可迭代或 d 不是字典（列表索引必须是整数或切片，不能是 str）
    except TypeError:
        return False


def deep_set(d, keys, value):
    """安全地向嵌套字典中设置值，模拟 deep_get() 的键路径遍历逻辑。

    仅支持字典类型，不支持列表。
    """
    # 150 * depth (ns)
    if type(keys) is str:
        keys = keys.split('.')

    first = True
    exist = True
    prev_d = None
    prev_k = None
    prev_k2 = None
    try:
        for k in keys:
            if first:
                prev_d = d
                prev_k = k
                first = False
                continue
            try:
                # 性能排序：if key in dict: dict[key] > dict.get > dict.setdefault > try dict[key] except
                if exist and prev_k in d:
                    prev_d = d
                    d = d[prev_k]
                else:
                    exist = False
                    new = {}
                    d[prev_k] = new
                    d = new
            except TypeError:
                # d 不是字典
                exist = False
                d = {}
                prev_d[prev_k2] = {prev_k: d}

            prev_k2 = prev_k
            prev_k = k
            # prev_k2, prev_k = prev_k, k
    # keys 不可迭代
    except TypeError:
        return

    # 最后一个键，设置值
    try:
        d[prev_k] = value
        return
    # 最后一个 d 不是字典
    except TypeError:
        prev_d[prev_k2] = {prev_k: value}
        return


def deep_default(d, keys, value):
    """安全地向嵌套字典中设置默认值（仅当键不存在时），模拟 deep_get() 的键路径遍历逻辑。

    仅支持字典类型，不支持列表。
    """
    # 150 * depth (ns)
    if type(keys) is str:
        keys = keys.split('.')

    first = True
    exist = True
    prev_d = None
    prev_k = None
    prev_k2 = None
    try:
        for k in keys:
            if first:
                prev_d = d
                prev_k = k
                first = False
                continue
            try:
                # 性能排序：if key in dict: dict[key] > dict.get > dict.setdefault > try dict[key] except
                if exist and prev_k in d:
                    prev_d = d
                    d = d[prev_k]
                else:
                    exist = False
                    new = {}
                    d[prev_k] = new
                    d = new
            except TypeError:
                # d 不是字典
                exist = False
                d = {}
                prev_d[prev_k2] = {prev_k: d}

            prev_k2 = prev_k
            prev_k = k
            # prev_k2, prev_k = prev_k, k
    # keys 不可迭代
    except TypeError:
        return

    # 最后一个键，设置默认值
    try:
        d.setdefault(prev_k, value)
        return
    # 最后一个 d 不是字典
    except AttributeError:
        prev_d[prev_k2] = {prev_k: value}
        return


def deep_pop(d, keys, default=None):
    """从嵌套字典和列表中弹出值。"""
    if type(keys) is str:
        keys = keys.split('.')

    try:
        for k in keys[:-1]:
            d = d[k]
        # 不使用 pop(k, default) 以兼容列表弹出
        return d.pop(keys[-1])
    # 键不存在
    except KeyError:
        return default
    # keys 不可迭代或 d 不是字典（列表索引必须是整数或切片，不能是 str）
    except TypeError:
        return default
    # keys 索引越界
    except IndexError:
        return default
    # 最后一个 d 不是字典（无 pop 方法）
    except AttributeError:
        return default


def deep_iter_depth1(data):
    """等价于 data.items()，但在 data 非字典时静默忽略错误。

    Args:
        data: 待遍历的数据。

    Yields:
        Any: 键。
        Any: 值。
    """
    try:
        for k, v in data.items():
            yield k, v
        return
    except AttributeError:
        # data 不是字典
        return


def deep_iter_depth2(data):
    """遍历深度为 2 的嵌套字典的键值对，是 deep_iter 的简化版本。

    Args:
        data: 待遍历的嵌套字典。

    Yields:
        Any: 第一层键。
        Any: 第二层键。
        Any: 值。
    """
    try:
        for k1, v1 in data.items():
            if type(v1) is dict:
                for k2, v2 in v1.items():
                    yield k1, k2, v2
    except AttributeError:
        # data 不是字典
        return


def deep_iter(data, min_depth=None, depth=3):
    """遍历嵌套字典的键值对。

    性能参考：depth=3 时遍历 alas.json（530+ 行）约 300us。
    仅支持字典类型。

    Args:
        data: 待遍历的嵌套字典。
        min_depth: 最小遍历深度，小于此深度的层级仅用于路径构建。
        depth: 最大遍历深度。

    Yields:
        list[str]: 键路径。
        Any: 值。
    """
    if min_depth is None:
        min_depth = depth
    assert 1 <= min_depth <= depth

    # 等价于 dict.items()
    try:
        if depth == 1:
            for k, v in data.items():
                yield [k], v
            return
        # 遍历第一层
        elif min_depth == 1:
            q = deque()
            for k, v in data.items():
                key = [k]
                if type(v) is dict:
                    q.append((key, v))
                else:
                    yield key, v
        # 仅遍历目标深度
        else:
            q = deque()
            for k, v in data.items():
                key = [k]
                if type(v) is dict:
                    q.append((key, v))
    except AttributeError:
        # data 不是字典
        return

    # 逐层遍历
    current = 2
    while current <= depth:
        new_q = deque()
        # 最大深度
        if current == depth:
            for key, data in q:
                for k, v in data.items():
                    yield key + [k], v
        # 在目标深度范围内
        elif min_depth <= current < depth:
            for key, data in q:
                for k, v in data.items():
                    subkey = key + [k]
                    if type(v) is dict:
                        new_q.append((subkey, v))
                    else:
                        yield subkey, v
        # 尚未达到最小深度
        else:
            for key, data in q:
                for k, v in data.items():
                    subkey = key + [k]
                    if type(v) is dict:
                        new_q.append((subkey, v))
        q = new_q
        current += 1


def deep_values(data, min_depth=None, depth=3):
    """遍历嵌套字典中的所有值。

    性能参考：depth=3 时遍历 alas.json（530+ 行）约 300us。
    仅支持字典类型。

    Args:
        data: 待遍历的嵌套字典。
        min_depth: 最小遍历深度。
        depth: 最大遍历深度。

    Yields:
        Any: 值。
    """
    if min_depth is None:
        min_depth = depth
    assert 1 <= min_depth <= depth

    # 等价于 dict.values()
    try:
        if depth == 1:
            for v in data.values():
                yield v
            return
        # 遍历第一层
        elif min_depth == 1:
            q = deque()
            for v in data.values():
                if type(v) is dict:
                    q.append(v)
                else:
                    yield v
        # 仅遍历目标深度
        else:
            q = deque()
            for v in data.values():
                if type(v) is dict:
                    q.append(v)
    except AttributeError:
        # data 不是字典
        return

    # 逐层遍历
    current = 2
    while current <= depth:
        new_q = deque()
        # 最大深度
        if current == depth:
            for data in q:
                for v in data.values():
                    yield v
        # 在目标深度范围内
        elif min_depth <= current < depth:
            for data in q:
                for v in data.values():
                    if type(v) is dict:
                        new_q.append(v)
                    else:
                        yield v
        # 尚未达到最小深度
        else:
            for data in q:
                for v in data.values():
                    if type(v) is dict:
                        new_q.append(v)
        q = new_q
        current += 1


def deep_iter_diff(before, after):
    """遍历两个字典之间的差异。

    比较两个深度嵌套字典时速度很快，耗时与差异数量成正比。

    Args:
        before: 变更前的字典。
        after: 变更后的字典。

    Yields:
        list[str]: 键路径。
        Any: before 中的值，不存在则为 None。
        Any: after 中的值，不存在则为 None。
    """
    if before == after:
        return
    if type(before) is not dict or type(after) is not dict:
        yield [], before, after
        return

    queue = deque([([], before, after)])
    while True:
        new_queue = deque()
        for path, d1, d2 in queue:
            keys1 = set(d1.keys())
            keys2 = set(d2.keys())
            for key in keys1.union(keys2):
                try:
                    val2 = d2[key]
                except KeyError:
                    # 安全访问 d1[key]，因为 key 来自两者的并集
                    # 如果不在 d2 中则一定在 d1 中
                    yield path + [key], d1[key], None
                    continue
                try:
                    val1 = d1[key]
                except KeyError:
                    yield path + [key], None, val2
                    continue
                # 先比较字典，速度很快
                if val1 != val2:
                    if type(val1) is dict and type(val2) is dict:
                        new_queue.append((path + [key], val1, val2))
                    else:
                        yield path + [key], val1, val2
        queue = new_queue
        if not queue:
            break


def deep_iter_patch(before, after):
    """遍历从 before 到 after 的补丁事件，类似生成 json-patch。

    比较两个深度嵌套字典时速度很快，耗时与差异数量成正比。

    Args:
        before: 变更前的字典。
        after: 变更后的字典。

    Yields:
        str: 操作类型，OP_ADD、OP_SET 或 OP_DEL。
        list[str]: 键路径。
        Any: after 中的值，OP_DEL 事件时为 None。
    """
    if before == after:
        return
    if type(before) is not dict or type(after) is not dict:
        yield OP_SET, [], after
        return

    queue = deque([([], before, after)])
    while True:
        new_queue = deque()
        for path, d1, d2 in queue:
            keys1 = set(d1.keys())
            keys2 = set(d2.keys())
            for key in keys1.union(keys2):
                try:
                    val2 = d2[key]
                except KeyError:
                    yield OP_DEL, path + [key], None
                    continue
                try:
                    val1 = d1[key]
                except KeyError:
                    yield OP_ADD, path + [key], val2
                    continue
                # 先比较字典，速度很快
                if val1 != val2:
                    if type(val1) is dict and type(val2) is dict:
                        new_queue.append((path + [key], val1, val2))
                    else:
                        yield OP_SET, path + [key], val2
        queue = new_queue
        if not queue:
            break
