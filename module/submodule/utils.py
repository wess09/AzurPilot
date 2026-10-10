"""子模块工具函数，定义外部桥接模块的注册表和映射关系。
维护可用功能列表、模块名称字典，
以及各功能到对应子模块的映射配置。"""

import os

MOD_DICT = {
    'maa': 'AlasMaaBridge',
    'fpy': 'AlasFpyBridge',
}
MOD_FUNC_DICT = {
    'MaaCopilot': 'maa',
    'FpyBattle': 'fpy',
    'FpyBenchmark': 'fpy',
    'FpyCall': 'fpy',
}
MOD_CONFIG_DICT = {}


def get_available_func():
    """获取所有可用的内置辅助功能名称元组。

    Returns:
        tuple[str, ...]: 功能名称元组。
    """
    return (
        'Daemon',
        'OpsiDaemon',
        'EventStory',
        'BoxDisassemble',
        'StorageStatistics',
        'AutoEquip',
        'AzurLaneUncensored',
        'Benchmark',
        'OcrBenchmark',
        'MeowfficerScore',
        'FleetScan',
        'MindCalculatorScan',
        'GameManager',
        'EmulatorManager',
    )

def get_available_mod():
    """获取所有已注册的子模块标识集合。

    Returns:
        set[str]: 子模块标识集合。
    """
    return set(MOD_DICT)


def get_available_mod_func():
    """获取所有由子模块实现的功能名称集合。

    Returns:
        set[str]: 功能名称集合。
    """
    return set(MOD_FUNC_DICT)


def get_func_mod(func):
    """根据功能名称查询所属的子模块标识。

    Args:
        func (str): 功能名称。

    Returns:
        str | None: 对应的子模块标识，若不属于任何子模块则返回 None。
    """
    return MOD_FUNC_DICT.get(func)


def list_mod_dir():
    """获取子模块标识与物理目录名的映射列表。

    Returns:
        list[tuple[str, str]]: (模块标识, 目录名) 列表。
    """
    return list(MOD_DICT.items())


def get_mod_dir(name):
    """根据子模块标识获取其物理目录名。

    Args:
        name (str): 子模块标识。

    Returns:
        str | None: 对应的子模块目录名。
    """
    return MOD_DICT.get(name)


def get_mod_filepath(name):
    """获取子模块的相对文件路径。

    Args:
        name (str): 子模块标识。

    Returns:
        str: 相对文件路径。
    """
    return os.path.join('./submodule', get_mod_dir(name))


def list_mod_template():
    """列出所有子模块的配置模板名称。

    Returns:
        list[str]: 模板名称列表。
    """
    out = []
    for file in os.listdir('./config'):
        name, extension = os.path.splitext(file)
        config_name, mod_name = os.path.splitext(name)
        mod_name = mod_name[1:]
        if config_name == 'template' and extension == '.json' and mod_name != '':
            out.append(f'{config_name}-{mod_name}')

    return out


def list_mod_instance():
    """扫描 config 目录并列出所有子模块实例配置名称。

    Returns:
        list[str]: 子模块实例名称列表。
    """
    global MOD_CONFIG_DICT
    MOD_CONFIG_DICT.clear()
    out = []
    for file in os.listdir('./config'):
        name, extension = os.path.splitext(file)
        config_name, mod_name = os.path.splitext(name)
        mod_name = mod_name[1:]
        if config_name != 'template' and extension == '.json' and mod_name != '':
            out.append(config_name)
            MOD_CONFIG_DICT[config_name] = mod_name

    return out


def get_config_mod(config_name):
    """根据配置名称解析对应的所属模块。

    Args:
        config_name (str): 配置名称。

    Returns:
        str: 模块名称（'alas' 或对应子模块名）。
    """
    if config_name.startswith('template-'):
        mod_name = config_name.replace('template-', '')
        # 主模块模板在前端展示为 template-ap（对应 config/template.json），
        # 其实际模块名仍为 alas，这里映射回去。
        # 与 module/config/utils.py 中的 DEFAULT_CONFIG_NAME 保持一致。
        return 'alas' if mod_name == 'ap' else mod_name
    try:
        return MOD_CONFIG_DICT[config_name]
    except KeyError:
        return 'alas'
