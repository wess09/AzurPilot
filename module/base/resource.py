import re

import module.config.server as server
from module.base.decorator import cached_property, del_cached_property


def get_assets_from_file(file, regex):
    assets = set()
    with open(file, 'r', encoding='utf-8') as f:
        for row in f.readlines():
            result = regex.search(row)
            if result:
                assets.add(result.group(1))
    return assets


class PreservedAssets:
    @cached_property
    def ui(self):
        assets = set()
        assets |= get_assets_from_file(
            file='./module/ui/assets.py',
            regex=re.compile(r'^([A-Za-z][A-Za-z0-9_]+) = ')
        )
        assets |= get_assets_from_file(
            file='./module/ui/ui.py',
            regex=re.compile(r'\(([A-Z][A-Z0-9_]+),')
        )
        assets |= get_assets_from_file(
            file='./module/handler/info_handler.py',
            regex=re.compile(r'\(([A-Z][A-Z0-9_]+),')
        )
        # MAIN_CHECK 等价于 MAIN_GOTO_CAMPAIGN
        # assets.add('MAIN_GOTO_CAMPAIGN')
        return assets


_preserved_assets = PreservedAssets()


class Resource:
    # 类属性，记录所有按钮和模板实例
    instances = {}
    # 实例属性，记录实例的缓存属性名称列表
    cached = []

    def resource_add(self, key):
        Resource.instances[key] = self

    def resource_release(self):
        for cache in self.cached:
            del_cached_property(self, cache)

    @classmethod
    def is_loaded(cls, obj):
        if hasattr(obj, '_image') and obj._image is None:
            return False
        elif hasattr(obj, 'image') and obj.image is None:
            return False
        return True

    @classmethod
    def resource_show(cls):
        from module.logger import logger
        logger.hr('Show resource')
        for key, obj in cls.instances.items():
            if cls.is_loaded(obj):
                continue
            logger.info(f'{obj}: {key}')

    @staticmethod
    def parse_property(data, s=None):
        """
        解析 Button 或 Template 对象的属性值。

        用于解析 `area`、`color`、`button` 等属性，支持按服务器区分的字典或直接字符串。

        Args:
            data: 属性值，字典或字符串。
            s: 服务器标识，如 'cn'、'en'、'jp'、'tw'。为 None 时使用全局 `server.server`。
        """
        if s is None:
            s = server.server
        if isinstance(data, dict):
            return data[s]
        else:
            return data


def release_resources(next_task=''):
    # 释放所有 OCR 模型
    # 通常会加载 2 个模型，每个约占 20MB
    # 释放后可节省 20-40MB 内存
    from module.webui.setting import State
    if State.deploy_config.UseOcrServer:
        if not next_task:
            # 空闲时断开 OCR 服务器连接
            from module.ocr.ocr import OCR_MODEL
            try:
                OCR_MODEL.close()
            except AttributeError:
                pass
    else:
        # 仅在使用实例内 OCR 时释放
        from module.ocr.ocr import OCR_MODEL
        if 'Opsi' in next_task or 'commission' in next_task:
            # OCR 模型即将被使用，不释放
            models = []
        elif next_task:
            # 释放除 'azur_lane' 以外的 OCR 模型
            models = ['cnocr', 'jp', 'tw']
        else:
            models = ['azur_lane', 'cnocr', 'jp', 'tw']
        for model in models:
            del_cached_property(OCR_MODEL, model)

    # 释放资源缓存
    # module.ui 约有 80 个资源，占约 3MB
    # Alas 总共约 800 个资源，但不会全部加载
    # 模板图像占用更多，每个约 6MB
    for key, obj in Resource.instances.items():
        # 保留 UI 切换所需的资源
        if next_task and str(obj) in _preserved_assets.ui:
            continue
        # if Resource.is_loaded(obj):
        #     logger.info(f'Release {obj}')
        obj.resource_release()

    # 释放地图检测的缓存图像
    from module.map_detection.utils_assets import ASSETS
    attr_list = [
        'ui_mask',
        'ui_mask_os',
        'ui_mask_stroke',
        'ui_mask_in_map',
        'ui_mask_os_in_map',
        'tile_center_image',
        'tile_corner_image',
        'tile_corner_image_list'
    ]
    for attr in attr_list:
        del_cached_property(ASSETS, attr)

    # 大多数情况下无明显效果，但仍然调用
    # gc.collect()
