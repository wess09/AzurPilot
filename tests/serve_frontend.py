"""浏览器测试专用服务，使用临时配置并禁止真实游戏进程。"""
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import uvicorn

from module.api.app import create_app
from module.api.config_service import ROOT
from tests.test_api import fixture
from module.runtime.account_local import LocalProtector


def main():
    with tempfile.TemporaryDirectory(prefix='azurpilot-ui-') as directory, \
            tempfile.TemporaryDirectory(prefix='azurpilot-ui-keys-') as keys, \
            patch.object(LocalProtector, 'key_directory', return_value=Path(keys) / 'private'), \
            patch('module.runtime.account_tpm.TpmProtector.available', return_value=False):
        root = fixture(directory)
        shutil.copytree(ROOT / 'frontend/dist', root / 'frontend/dist')
        path = root / 'config/testpilot.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        for name, value in {'Oil': 14200, 'Coin': 186420, 'Gem': 2468, 'Cube': 384}.items():
            data['Dashboard'][name]['Value'] = value
            data['Dashboard'][name]['Record'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        app = create_app(root=root, password='', manage_runtime=False, mount_mcp=False)
        runtime = app.state.gateway.router.runtime
        def reject_execution(*args, **kwargs):
            from module.api.protocol import ApiError
            raise ApiError('TEST_ENVIRONMENT', '浏览器测试服务不会执行游戏任务')
        runtime.start = runtime.stop = reject_execution
        # 浏览器验收可测试密码流程，但不能写入真实模拟器或建立主机 TPM 密钥。
        account_method = app.state.gateway.router.methods['accounts.manage']
        def manage_test_account(params):
            if params.action in ('capture', 'select'):
                return reject_execution()
            if params.action == 'bind_tpm':
                from unittest.mock import patch
                from module.api.protocol import ApiError
                with patch('module.runtime.account_tpm.TpmProtector.wrap',
                           side_effect=ApiError('TPM_UNAVAILABLE', '模拟 TPM 验证失败')):
                    return account_method.handler(params)
            return account_method.handler(params)
        from module.api.router import Method
        app.state.gateway.router.methods['accounts.manage'] = Method(account_method.params, manage_test_account, True)
        # 测试页面只能读取版本信息，禁止触发真实仓库获取、更新和取消。
        from module.api.router import Method
        from module.api.protocol import Params
        for method in ('updater.fetch', 'updater.apply', 'updater.cancel'):
            app.state.gateway.router.methods[method] = Method(Params, reject_execution, True)
        runtime.statistics = lambda instance, days, resource: {
            'instance': instance, 'resource': resource, 'points': [], 'truncated': False,
        }
        from module.api.router import Method
        from module.api.protocol import StatisticsReportParams
        app.state.gateway.router.methods['statistics.report'] = Method(StatisticsReportParams, lambda params: {
            'instance': params.instance, 'category': params.category, 'month': params.month,
            'metrics': [], 'series': [{'key': 'oil', 'label': '石油', 'points': []}], 'tables': [], 'notes': [],
        })
        uvicorn.run(app, host='127.0.0.1', port=22391, log_level='warning')


if __name__ == '__main__':
    main()
