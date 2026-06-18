# 此文件提供了配置管理相关的通用工具函数。
# 包含 JSON/YAML 读写、数据类型解析转换、服务器特定时间计算以及随机 ID 生成等底层功能。
import json
import random
import string
import time
from datetime import datetime, timedelta, timezone

import yaml

import module.config.server as server_
from deploy.atomic import atomic_read_text, atomic_read_bytes, atomic_write
from module.submodule.utils import *
from module.base.decorator import run_once
from module.logger import logger

LANGUAGES = ['zh-CN', 'zh-MIAO', 'en-US', 'ja-JP', 'zh-TW']
SERVER_TO_LANG = {
    'cn': 'zh-CN',
    'en': 'en-US',
    'jp': 'ja-JP',
    'tw': 'zh-TW',
}
LANG_TO_SERVER = {v: k for k, v in SERVER_TO_LANG.items()}
SERVER_TO_TIMEZONE = {
    'cn': timedelta(hours=8),
    'en': timedelta(hours=-7),
    'jp': timedelta(hours=9),
    'tw': timedelta(hours=8),
}
DEFAULT_TIME = datetime(2023, 1, 1, 0, 0)
DEFAULT_CONFIG_NAME = 'ap'


# https://stackoverflow.com/questions/8640959/how-can-i-control-what-scalar-form-pyyaml-uses-for-my-data/15423007
def str_presenter(dumper, data):
    if len(data.splitlines()) > 1:  # 多行字符串使用块样式
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)


yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)


def filepath_args(filename='args', mod_name='alas'):
    if mod_name == 'alas':
        return f'./module/config/argument/{filename}.json'
    else:
        return os.path.join(get_mod_filepath(mod_name), f'./module/config/argument/{filename}.json')


def filepath_argument(filename):
    return f'./module/config/argument/{filename}.yaml'


def filepath_i18n(lang, mod_name='alas'):
    if mod_name == 'alas':
        return os.path.join('./module/config/i18n', f'{lang}.json')
    else:
        return os.path.join(get_mod_filepath(mod_name), './module/config/i18n', f'{lang}.json')


def filepath_config(filename, mod_name='alas'):
    if mod_name == 'alas':
        return os.path.join('./config', f'{filename}.json')
    else:
        return os.path.join('./config', f'{filename}.{mod_name}.json')


def filepath_code():
    return './module/config/config_generated.py'


def read_file(file):
    """
    读取文件，支持 .yaml 和 .json 格式。
    文件不存在时返回空字典。

    Args:
        file (str): 文件路径。

    Returns:
        dict, list: 解析后的数据。
    """
    print(f'read: {file}')
    if file.endswith('.json'):
        content = atomic_read_bytes(file)
        if not content:
            return {}
        return json.loads(content)
    elif file.endswith('.yaml'):
        content = atomic_read_text(file)
        data = list(yaml.safe_load_all(content))
        if len(data) == 1:
            data = data[0]
        if not data:
            data = {}
        return data
    else:
        print(f'Unsupported config file extension: {file}')
        return {}


def write_file(file, data):
    """
    将数据写入文件，支持 .yaml 和 .json 格式。

    Args:
        file (str): 文件路径。
        data (dict, list): 要写入的数据。
    """
    print(f'write: {file}')
    if file.endswith('.json'):
        content = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False, default=str)
        atomic_write(file, content)
    elif file.endswith('.yaml'):
        if isinstance(data, list):
            content = yaml.safe_dump_all(
                data, default_flow_style=False, encoding='utf-8', allow_unicode=True, sort_keys=False)
        else:
            content = yaml.safe_dump(
                data, default_flow_style=False, encoding='utf-8', allow_unicode=True, sort_keys=False)
        atomic_write(file, content)
    else:
        print(f'Unsupported config file extension: {file}')


def iter_folder(folder, is_dir=False, ext=None):
    """
    遍历文件夹中的文件或子目录。

    Args:
        folder (str): 目标文件夹路径。
        is_dir (bool): 为 True 时仅遍历子目录。
        ext (str): 文件扩展名过滤，如 `.yaml`。

    Yields:
        str: 文件的绝对路径。
    """
    for file in os.listdir(folder):
        sub = os.path.join(folder, file)
        if is_dir:
            if os.path.isdir(sub):
                yield sub.replace('\\\\', '/').replace('\\', '/')
        elif ext is not None:
            if not os.path.isdir(sub):
                _, extension = os.path.splitext(file)
                if extension == ext:
                    yield os.path.join(folder, file).replace('\\\\', '/').replace('\\', '/')
        else:
            yield os.path.join(folder, file).replace('\\\\', '/').replace('\\', '/')


def is_oobe_needed():
    """
    检查是否需要 OOBE 初次设置向导。
    config/ 目录下不存在任何非 template 开头的 .json 配置文件时返回 True。

    Returns:
        bool:
    """
    if not os.path.exists('./config'):
        return True
    for file in os.listdir('./config'):
        name, ext = os.path.splitext(file)
        if ext == '.json' and not name.startswith('template'):
            return False
    return True


def alas_template():
    """
    获取所有 Alas 模板实例名称。

    Returns:
        list[str]: 除 `template` 外的所有 Alas 模板实例名称。
    """
    out = []
    for file in os.listdir('./config'):
        name, extension = os.path.splitext(file)
        if name == 'template' and extension == '.json':
            out.append(f'{name}-alas')

    out.extend(list_mod_template())

    return out


def alas_instance():
    """
    获取所有 Alas 实例名称。

    Returns:
        list[str]: 除 `template` 外的所有 Alas 实例名称。
    """
    out = []
    for file in os.listdir('./config'):
        name, extension = os.path.splitext(file)
        config_name, mod_name = os.path.splitext(name)
        mod_name = mod_name[1:]
        if name != 'template' and extension == '.json' and mod_name == '':
            out.append(name)

    out.extend(list_mod_instance())

    if not len(out):
        out = [DEFAULT_CONFIG_NAME]

    return out


def parse_value(value, data):
    """
    尝试将字符串转换为 float、int 或 datetime。

    Args:
        value (str): 待转换的值。
        data (dict): 参数定义数据，包含 `option` 等字段。

    Returns:
        转换后的值，无法转换时返回原值。
    """
    if 'option' in data:
        if value not in data['option']:
            return data['value']
    if isinstance(value, str):
        if value == '':
            return None
        if value == 'true' or value == 'True':
            return True
        if value == 'false' or value == 'False':
            return False
        if '.' in value:
            try:
                return float(value)
            except ValueError:
                pass
        else:
            try:
                return int(value)
            except ValueError:
                pass
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass

    return value


def data_to_type(data, **kwargs):
    """
    根据参数定义推断对应的 GUI 控件类型。

    | 条件                              | 类型     |
    | ---------------------------------- | -------- |
    | 值为 bool                          | checkbox |
    | 参数有选项列表                      | select   |
    | 名称中包含 `Filter`（data['arg']）  | textarea |
    | 其他参数                           | input    |

    Args:
        data (dict): 参数定义数据。
        kwargs: 附加属性。

    Returns:
        str: GUI 控件类型字符串。
    """
    kwargs.update(data)
    if isinstance(kwargs['value'], bool):
        return 'checkbox'
    elif 'option' in kwargs and kwargs['option']:
        return 'select'
    elif 'Filter' in kwargs['arg']:
        return 'textarea'
    else:
        return 'input'


def data_to_path(data):
    """
    将参数数据转换为配置路径字符串。

    Args:
        data (dict): 包含 `func`、`group`、`arg` 键的字典。

    Returns:
        str: 格式为 `<func>.<group>.<arg>` 的路径。
    """
    return '.'.join([data.get(attr, '') for attr in ['func', 'group', 'arg']])


def path_to_arg(path):
    """
    将 .yaml 文件中的字典键转换为配置中的参数名。

    Args:
        path (str): 如 `Scheduler.ServerUpdate`。

    Returns:
        str: 如 `Scheduler_ServerUpdate`。
    """
    return path.replace('.', '_')


def dict_to_kv(dictionary, allow_none=True):
    """
    将字典转换为 key=value 格式的字符串。

    Args:
        dictionary: 如 `{'path': 'Scheduler.ServerUpdate', 'value': True}`。
        allow_none (bool): 是否包含值为 None 的键。

    Returns:
        str: 如 `path='Scheduler.ServerUpdate', value=True`。
    """
    return ', '.join([f'{k}={repr(v)}' for k, v in dictionary.items() if allow_none or v is not None])


def server_timezone() -> timedelta:
    return SERVER_TO_TIMEZONE.get(server_.server, SERVER_TO_TIMEZONE['cn'])


def server_time_offset() -> timedelta:
    """
    计算本地时间与服务器时间的偏移量。

    本地时间转服务器时间：server_time = local_time + server_time_offset()
    服务器时间转本地时间：local_time = server_time - server_time_offset()
    """
    return datetime.now(timezone.utc).astimezone().utcoffset() - server_timezone()


def random_normal_distribution_int(a, b, n=3):
    """
    生成区间内的正态分布随机整数（不依赖 numpy 的实现）。

    使用多个随机数的平均值模拟正态分布。

    Args:
        a (int): 区间最小值。
        b (int): 区间最大值。
        n (int): 模拟用的随机数个数，默认为 3。

    Returns:
        int: 正态分布随机整数。
    """
    if a < b:
        output = sum([random.randint(a, b) for _ in range(n)]) / n
        return int(round(output))
    else:
        return b


def ensure_time(second, n=3, precision=3):
    """
    确保输入为时间值，支持区间随机。

    Args:
        second (int, float, tuple): 时间值，如 10、(10, 30)、'10, 30'。
        n (int): 模拟用的随机数个数，默认为 3。
        precision (int): 小数精度。

    Returns:
        float: 处理后的时间值。
    """
    if isinstance(second, tuple):
        multiply = 10 ** precision
        return random_normal_distribution_int(second[0] * multiply, second[1] * multiply, n) / multiply
    elif isinstance(second, str):
        if ',' in second:
            lower, upper = second.replace(' ', '').split(',')
            lower, upper = int(lower), int(upper)
            return ensure_time((lower, upper), n=n, precision=precision)
        if '-' in second:
            lower, upper = second.replace(' ', '').split('-')
            lower, upper = int(lower), int(upper)
            return ensure_time((lower, upper), n=n, precision=precision)
        else:
            return int(second)
    else:
        return second


def get_os_next_reset():
    """
    获取下个月的第一天（大世界重置时间）。

    Returns:
        datetime.datetime: 下次重置的本地时间。
    """
    diff = server_time_offset()
    server_now = datetime.now() - diff
    server_reset = (server_now.replace(day=1) + timedelta(days=32)) \
        .replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    local_reset = server_reset + diff
    return local_reset


def get_os_reset_remain():
    """
    获取距离大世界下次重置的剩余天数。

    Returns:
        int: 剩余天数。
    """
    next_reset = get_os_next_reset()
    now = datetime.now()
    logger.attr('OpsiNextReset', next_reset)

    remain = int((next_reset - now).total_seconds() // 86400)
    logger.attr('ResetRemain', remain)
    return remain


def get_server_next_update(daily_trigger):
    """
    获取服务器下次更新时间。

    Args:
        daily_trigger (list[str], str): 每日触发时间列表，如 ["00:00", "12:00", "18:00"]。

    Returns:
        datetime.datetime: 下次更新的本地时间。
    """
    if isinstance(daily_trigger, str):
        daily_trigger = daily_trigger.replace(' ', '').split(',')

    diff = server_time_offset()
    local_now = datetime.now()
    trigger = []
    for t in daily_trigger:
        h, m = [int(x) for x in t.split(':')]
        future = local_now.replace(hour=h, minute=m, second=0, microsecond=0) + diff
        s = (future - local_now).total_seconds() % 86400
        future = local_now + timedelta(seconds=s)
        trigger.append(future)
    update = sorted(trigger)[0]
    return update


def get_server_last_update(daily_trigger):
    """
    获取服务器上次更新时间。

    Args:
        daily_trigger (list[str], str): 每日触发时间列表，如 ["00:00", "12:00", "18:00"]。

    Returns:
        datetime.datetime: 上次更新的本地时间。
    """
    if isinstance(daily_trigger, str):
        daily_trigger = daily_trigger.replace(' ', '').split(',')

    diff = server_time_offset()
    local_now = datetime.now()
    trigger = []
    for t in daily_trigger:
        h, m = [int(x) for x in t.split(':')]
        future = local_now.replace(hour=h, minute=m, second=0, microsecond=0) + diff
        s = (future - local_now).total_seconds() % 86400 - 86400
        future = local_now + timedelta(seconds=s)
        trigger.append(future)
    update = sorted(trigger)[-1]
    return update


def nearest_future(future, interval=120):
    """
    获取最近的未来时间点。
    若多个时间点在 `interval` 秒内完成，则返回最晚的一个。

    Args:
        future (list[datetime.datetime]): 未来时间点列表。
        interval (int): 合并间隔，单位为秒。

    Returns:
        datetime.datetime: 最终选择的时间点。
    """
    future = [datetime.fromisoformat(f) if isinstance(f, str) else f for f in future]
    future = sorted(future)
    next_run = future[0]
    for finish in future:
        if finish - next_run < timedelta(seconds=interval):
            next_run = finish

    return next_run


def get_nearest_weekday_date(target):
    """
    获取从当前日期起最近的目标星期几的日期。

    Args:
        target (int): 目标星期几（0=周一, 6=周日）。

    Returns:
        datetime.datetime: 最近的目标星期几的本地时间。
    """
    diff = server_time_offset()
    server_now = datetime.now() - diff

    days_ahead = target - server_now.weekday()
    if days_ahead <= 0:
        # 目标日期已过，跳到下周
        days_ahead += 7
    server_reset = (server_now + timedelta(days=days_ahead)) \
        .replace(hour=0, minute=0, second=0, microsecond=0)

    local_reset = server_reset + diff
    return local_reset


def get_server_weekday():
    """
    获取服务器当前是星期几。

    Returns:
        int: 星期几（0=周一, 6=周日）。
    """
    diff = server_time_offset()
    server_now = datetime.now() - diff
    result = server_now.weekday()
    return result


def get_server_monthday():
    """
    获取服务器当前是几号。

    Returns:
        int: 月份中的天数。
    """
    diff = server_time_offset()
    server_now = datetime.now() - diff
    result = server_now.day
    return result


def random_id(length=32):
    """
    生成随机 ID。

    Args:
        length (int): ID 长度，默认为 32。

    Returns:
        str: 随机 AzurStat ID。
    """
    return ''.join(random.sample(string.ascii_lowercase + string.digits, length))


def to_list(text, length=1):
    """
    将文本转换为整数列表。

    Args:
        text (str): 逗号分隔的数字文本，如 `1, 2, 3`。
        length (int): 单个数字时扩展为指定长度的列表，
            如 text='3', length=5 返回 `[3, 3, 3, 3, 3]`。

    Returns:
        list[int]: 整数列表。
    """
    if text.isdigit():
        return [int(text)] * length
    out = [int(letter.strip()) for letter in text.split(',')]
    return out


def type_to_str(typ):
    """
    将任意类型或对象转换为字符串。

    Args:
        typ: 类型或对象。

    Returns:
        str: 类型名称，如 `int`、`datetime.datetime`。
    """
    if not isinstance(typ, type):
        typ = type(typ).__name__
    return str(typ)


def time_delta(_timedelta):
    """
    计算两个时间之间的差值，按年/月/日/时/分/秒拆分。

    Args:
        _timedelta (datetime.timedelta): 时间差。

    Returns:
        dict: 拆分后的时间差字典，包含 'Y'、'M'、'D'、'h'、'm'、's' 键。
    """
    _time_delta = abs(_timedelta.total_seconds())
    d_base = datetime(2010, 1, 1, 0, 0, 0)
    d = datetime(2010, 1, 1, 0, 0, 0)-_timedelta
    _time_dict = {
        'Y': d.year - d_base.year,
        'M': d.month - d_base.month,
        'D': d.day - d_base.day,
        'h': d.hour - d_base.hour,
        'm': d.minute - d_base.minute,
        's': d.second - d_base.second
    }
    # _sec ={
    #     'Y': 365*24*60*60,
    #     'M': 30*24*60*60,
    #     'D': 24*60*60,
    #     'h': 60*60,
    #     'm': 60,
    #     's': 1
    # }
    # for _key in _time_dict:
    #     _time_dict[_key] = int(_time_delta//_sec[_key])
    #     _time_delta = _time_delta%_sec[_key]
    return _time_dict


def readable_time(before: str, value: str) -> str:
    """
    计算两个时间之间的差值，返回人类可读的时间描述。
    """
    timedata = {
        'value': value,
        'time': '',
        'time_name': 'NoData'
    }
    if not before:
        timedata['value'] = 'None'
        return timedata
    try:
        ti = datetime.fromisoformat(before)
    except ValueError:
        timedata['time_name'] = 'TimeError'
        return timedata
    if ti == DEFAULT_TIME:
        timedata['value'] = 'None'
        return timedata

    diff = time.time() - ti.timestamp()
    if diff < -1:
        timedata['time_name'] = 'TimeError'
    elif diff < 60:
        timedata['time_name'] = 'JustNow'
    elif diff < 5400:
        timedata['time'] = int(diff // 60)
        timedata['time_name'] = 'MinutesAgo'
    elif diff < 129600:
        timedata['time'] = int(diff // 3600)
        timedata['time_name'] = 'HoursAgo'
    elif diff < 1296000:
        timedata['time'] = int(diff // 86400)
        timedata['time_name'] = 'DaysAgo'
    else:
        timedata['time_name'] = 'LongTimeAgo'
    return timedata

@run_once
def is_good_gpu():
    if os.name != 'nt':
        logger.info("当前系统为非 Windows，不使用 GPU")
        return False

    try:
        import subprocess

        res = subprocess.run(['powershell', '-NoProfile', '-Command',
                              'Get-CimInstance Win32_VideoController | ForEach-Object { $_.AdapterRAM }'],
                             capture_output=True, text=True, check=True)
        for line in res.stdout.splitlines():
            line = line.strip()
            if line:
                try:
                    # AdapterRAM 单位为字节，1GB = 1073741824 字节
                    if int(line) >= 1073741824:
                        logger.info("检测到高性能 GPU")
                        return True
                except (ValueError, TypeError):
                    continue
        logger.info("未检测到高性能 GPU")
        return False
    except Exception:
        logger.warning("检测 GPU 性能失败")
        return False
    

if __name__ == '__main__':
    get_os_reset_remain()
