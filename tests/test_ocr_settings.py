"""OCR 设置与缓存回归测试，模型工厂全部替换，不读取模型或访问 GPU。"""

import os
import subprocess
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from module.ocr import al_ocr
from module.ocr.al_ocr import AlOcr, OcrSettings


def make_config(*, backend='onnxruntime', device='cpu', vendor=False, version='standard'):
    return SimpleNamespace(
        ocr_backend=backend,
        ocr_device=device,
        Optimization_OcrWindowsMlVendorEp=vendor,
        ocr_model_version=Mock(return_value=version),
        override=Mock(),
    )


class FakeModel:
    def __init__(self):
        self.closed = False
        self.threads = []
        self.before_infer = None

    def __call__(self, *args, **kwargs):
        if self.closed:
            raise AssertionError('使用了已经释放的模型')
        self.threads.append(threading.get_ident())
        if self.before_infer:
            self.before_infer()
        return SimpleNamespace(txts=['测试文本'])

    def close(self):
        self.closed = True


class TestOcrSettingsCache(unittest.TestCase):
    def setUp(self):
        al_ocr.reset_ocr_model()
        self.enterContext(patch('module.ocr.al_ocr.logger'))
        self.enterContext(patch.object(AlOcr, '_save_debug_image'))
        self.default_config = self.enterContext(patch(
            'module.ocr.al_ocr.AzurLaneConfig', return_value=make_config(),
        ))
        self.factory_threads = []

        def create(*args):
            self.factory_threads.append(threading.get_ident())
            return FakeModel()

        self.factory = self.enterContext(patch('module.ocr.al_ocr._create_ocr', side_effect=create))
        self.det_factory = self.enterContext(patch(
            'module.ocr.al_ocr._create_det_ocr_for_onnx', side_effect=create,
        ))
        self.ncnn_det_factory = self.enterContext(patch(
            'module.ocr.al_ocr._create_det_ocr_for_ncnn', side_effect=create,
        ))
        self.addCleanup(al_ocr.reset_ocr_model)

    def test_construction_is_lazy_and_default_config_uses_current_environment(self):
        ocr = AlOcr(name='azur_lane')
        self.default_config.assert_not_called()
        self.factory.assert_not_called()

        with patch.dict(os.environ, {'ALAS_CONFIG_NAME': '当前实例'}):
            self.assertIsNone(ocr.init())

        self.default_config.assert_called_once_with('当前实例')
        self.assertEqual(self.factory_threads, [al_ocr._ocr_worker_ident])
        self.assertNotEqual(self.factory_threads[0], threading.get_ident())

    def test_different_config_instances_use_their_own_settings(self):
        first = AlOcr(name='cn', config=make_config(device='cpu'))
        second = AlOcr(name='cn', config=make_config(device='gpu', vendor=True, version='pro'))
        first.init()
        second.init()

        self.assertIsNot(first.model, second.model)
        first_settings = self.factory.call_args_list[0].args[1]
        second_settings = self.factory.call_args_list[1].args[1]
        self.assertEqual(first_settings.device, 'cpu')
        self.assertEqual(second_settings.device, 'gpu')
        self.assertEqual(second_settings.model_version, 'pro')
        self.assertTrue(second_settings.allow_vendor_execution_providers)
        self.default_config.assert_not_called()

    def test_equivalent_settings_share_model_and_effective_default_version(self):
        first = AlOcr(name='azur_lane', config=make_config(version='auto'))
        second = AlOcr(name='azur_lane', config=make_config(version='alocr_en_v2_6'))
        first.init()
        second.init()

        self.assertIs(first.model, second.model)
        self.factory.assert_called_once()

    def test_backend_device_vendor_and_version_each_separate_cache_entries(self):
        base = OcrSettings('onnxruntime', 'cpu', False, 'standard')
        choices = [
            base,
            replace(base, backend='ncnn'),
            replace(base, device='gpu'),
            replace(base, allow_vendor_execution_providers=True),
            replace(base, model_version='pro'),
        ]
        models = []
        for settings in choices:
            ocr = AlOcr(name='cn', settings=settings)
            ocr.init()
            models.append(ocr.model)

        self.assertEqual(len({id(model) for model in models}), len(choices))
        self.assertEqual([entry.args[1] for entry in self.factory.call_args_list], choices)
        self.default_config.assert_not_called()

    def test_recognition_and_detection_use_one_snapshot_despite_config_mutation(self):
        config = make_config(device='cpu', version='lite')

        def create(name, settings):
            config.ocr_device = 'gpu'
            config.ocr_model_version.return_value = 'pro'
            return FakeModel()

        self.factory.side_effect = create
        ocr = AlOcr(name='cn', config=config)
        self.assertEqual(ocr.det(None), [])

        rec_settings = self.factory.call_args.args[1]
        det_settings = self.det_factory.call_args.args[1]
        self.assertIs(rec_settings, det_settings)
        self.assertEqual(det_settings.device, 'cpu')
        self.assertEqual(det_settings.model_version, 'lite')

    def test_ncnn_detection_stays_shared_across_recognition_versions(self):
        first = AlOcr(name='cn', config=make_config(backend='ncnn', version='lite'))
        second = AlOcr(name='jp', config=make_config(backend='ncnn', version='pro'))
        self.assertEqual(first.det(None), [])
        self.assertEqual(second.det(None), [])

        self.assertIs(first._det_model, second._det_model)
        self.ncnn_det_factory.assert_called_once_with()
        self.det_factory.assert_not_called()
        self.assertEqual(al_ocr.release_ocr_models(names=['det']), 1)
        self.assertFalse(first.model.closed)

    def test_reset_reloads_default_config_and_replaces_closed_models_on_same_instance(self):
        self.default_config.side_effect = [make_config(device='cpu'), make_config(device='gpu')]
        ocr = AlOcr(name='cn')
        ocr.det(None)
        old_rec, old_det = ocr.model, ocr._det_model

        self.assertEqual(al_ocr.reset_ocr_model(), 2)
        self.assertTrue(old_rec.closed)
        self.assertTrue(old_det.closed)
        ocr.det(None)

        self.assertIsNot(ocr.model, old_rec)
        self.assertIsNot(ocr._det_model, old_det)
        self.assertEqual(self.default_config.call_count, 2)
        self.assertEqual(self.factory.call_args.args[1].device, 'gpu')

    def test_default_config_is_not_reused_after_environment_switch(self):
        self.default_config.side_effect = [make_config(device='cpu'), make_config(device='gpu')]
        ocr = AlOcr(name='cn')
        with patch.dict(os.environ, {'ALAS_CONFIG_NAME': '实例甲'}):
            ocr.init()
        with patch.dict(os.environ, {'ALAS_CONFIG_NAME': '实例乙'}):
            ocr.init()

        self.assertEqual(self.default_config.call_args_list, [call('实例甲'), call('实例乙')])
        self.assertEqual(self.factory.call_args.args[1].device, 'gpu')

    def test_release_by_name_covers_all_settings_and_preserves_other_names(self):
        first = AlOcr(name='cn', config=make_config(device='cpu'))
        second = AlOcr(name='cn', config=make_config(device='gpu'))
        other = AlOcr(name='jp', config=make_config())
        for ocr in (first, second, other):
            ocr.init()
        old_first = first.model

        self.assertEqual(al_ocr.release_ocr_models(names=['cn']), 2)
        self.assertTrue(old_first.closed)
        self.assertTrue(second.model.closed)
        self.assertFalse(other.model.closed)
        self.assertEqual(first.ocr(None), '测试文本')
        self.assertIsNot(first.model, old_first)
        self.assertEqual(other.ocr(None), '测试文本')
        self.assertEqual(self.factory.call_count, 4)

    def test_concurrent_init_and_inference_share_one_model_on_worker_thread(self):
        settings = OcrSettings('onnxruntime', 'cpu', False, 'standard')
        instances = [AlOcr(name='cn', settings=settings) for _ in range(4)]
        with ThreadPoolExecutor(max_workers=4) as executor:
            self.assertEqual(list(executor.map(lambda ocr: ocr.init(), instances)), [None] * 4)
            self.assertEqual(list(executor.map(lambda ocr: ocr.ocr(None), instances)), ['测试文本'] * 4)

        self.factory.assert_called_once()
        self.assertEqual(self.factory_threads, [al_ocr._ocr_worker_ident])
        self.assertEqual(instances[0].model.threads, [al_ocr._ocr_worker_ident] * 4)

    def test_reset_waits_for_inference_before_closing_model(self):
        ocr = AlOcr(name='cn', config=make_config())
        ocr.init()
        old_model = ocr.model
        entered, resume, reset_queued = threading.Event(), threading.Event(), threading.Event()

        def block_inference():
            entered.set()
            if not resume.wait(5):
                raise AssertionError('推理测试未收到继续信号')

        old_model.before_infer = block_inference
        original_put = al_ocr._ocr_queue.put

        def put(job):
            original_put(job)
            if job.func.__name__ == '_reset':
                reset_queued.set()

        with ThreadPoolExecutor(max_workers=2) as executor, patch.object(al_ocr._ocr_queue, 'put', side_effect=put):
            inference = executor.submit(ocr.ocr, None)
            try:
                self.assertTrue(entered.wait(5))
                reset = executor.submit(al_ocr.reset_ocr_model)
                self.assertTrue(reset_queued.wait(5))
                self.assertFalse(old_model.closed)
            finally:
                resume.set()
            self.assertEqual(inference.result(timeout=5), '测试文本')
            self.assertEqual(reset.result(timeout=5), 1)

        self.assertTrue(old_model.closed)
        self.assertEqual(ocr.ocr(None), '测试文本')
        self.assertIsNot(ocr.model, old_model)

    def test_benchmark_device_override_uses_its_config_without_global_reset(self):
        from module.daemon.ocr_benchmark import OcrBenchmark

        benchmark = OcrBenchmark.__new__(OcrBenchmark)
        benchmark.config = make_config(device='ane', vendor=True, version='pro')
        benchmark._find_archive = Mock(return_value=None)
        benchmark._load_test_cases = Mock(return_value=[])
        with (
            patch('module.daemon.ocr_benchmark.logger'),
            patch('module.daemon.ocr_benchmark.os.path.exists', return_value=False),
            patch('module.ocr.al_ocr.reset_ocr_model') as reset,
        ):
            benchmark._run_single('cn', '不存在的数据集', 'cases', use_gpu=False)
            benchmark._run_single('cn', '不存在的数据集', 'cases', use_gpu=True)

        settings = [entry.args[1] for entry in self.factory.call_args_list]
        self.assertEqual([item.device for item in settings], ['cpu', 'gpu'])
        self.assertTrue(all(item.allow_vendor_execution_providers for item in settings))
        self.assertTrue(all(item.model_version == 'pro' for item in settings))
        self.assertEqual(benchmark.config.ocr_device, 'ane')
        benchmark.config.override.assert_not_called()
        reset.assert_not_called()
        self.default_config.assert_not_called()


class TestOcrModelFactories(unittest.TestCase):
    def test_device_overrides_keep_platform_auto_selection(self):
        for platform_name, expected in [('darwin', 'ane'), ('win32', 'auto'), ('linux', 'gpu')]:
            with (
                self.subTest(platform=platform_name),
                patch('module.config.config.sys.platform', platform_name),
                patch('module.config.config.platform.machine', return_value='arm64'),
                patch('module.config.config.is_good_gpu', return_value=True),
            ):
                settings = OcrSettings.from_config(make_config(), 'cn', device='auto')
                self.assertEqual(settings.device, expected)

    def test_ncnn_device_overrides_keep_vendor_fallback_and_vulkan_selection(self):
        config = make_config(backend='ncnn')
        for requested in ('qnn_npu', 'openvino_npu', 'openvino_gpu', 'openvino_cpu'):
            with self.subTest(device=requested):
                self.assertEqual(OcrSettings.from_config(config, 'cn', device=requested).device, 'cpu')
        for available, expected in ((True, 'gpu'), (False, 'cpu')):
            with patch('module.ocr.ncnn_ocr.has_ncnn_vulkan_gpu', return_value=available):
                self.assertEqual(OcrSettings.from_config(config, 'cn', device='auto').device, expected)

    def test_default_and_invalid_versions_keep_existing_language_defaults(self):
        for name, expected in al_ocr.DEFAULT_ONNX_MODEL_VERSION.items():
            for requested in ('auto', '无效版本'):
                with self.subTest(name=name, requested=requested):
                    settings = OcrSettings.from_config(make_config(version=requested), name)
                    self.assertEqual(settings.model_version, expected)

    def test_ncnn_legacy_selection_keeps_standard_fallback(self):
        settings = OcrSettings.from_config(make_config(backend='ncnn', version='auto'), 'azur_lane')
        self.assertEqual(settings.model_version, 'standard')
        with patch('module.ocr.al_ocr.NcnnRecOCR') as factory:
            al_ocr._create_ocr('azur_lane', settings)
        factory.assert_called_once_with('azur_lane', device='cpu', version='standard')

    def test_onnx_factories_use_snapshot_for_model_and_execution_provider(self):
        settings = OcrSettings('onnxruntime', 'ane', True, 'lite')
        with (
            patch('module.ocr.al_ocr.RecOnlyOCR') as rec,
            patch('module.ocr.al_ocr.RapidOCR') as det,
            patch('module.ocr.al_ocr._configure_windows_ml_sessions') as sessions,
        ):
            al_ocr._create_ocr('cn', settings)
            al_ocr._create_det_ocr_for_onnx('cn', settings)

        for factory in (rec, det):
            params = factory.call_args.kwargs['params']
            self.assertEqual(params['Rec.model_path'], al_ocr.PPOCR_V6_LITE_MODEL)
            self.assertEqual(params['Rec.rec_keys_path'], al_ocr.PPOCR_V6_TINY_DICT)
            self.assertTrue(params['EngineConfig.onnxruntime.use_coreml'])
            self.assertFalse(params['EngineConfig.onnxruntime.use_dml'])
        self.assertEqual([entry.args[2:] for entry in sessions.call_args_list], [('ane', True)] * 2)

    def test_settings_are_immutable(self):
        settings = OcrSettings.from_config(make_config(), 'cn')
        with self.assertRaises(FrozenInstanceError):
            settings.device = 'gpu'

    def test_import_and_construction_do_not_load_or_save_config(self):
        code = '''
from unittest.mock import patch
with patch('module.config.config.AzurLaneConfig', side_effect=AssertionError('导入时读取了配置')) as config:
    import module.ocr.al_ocr as module
    module.AlOcr(name='azur_lane')
    config.assert_not_called()
    assert module._ocr_worker is None
'''
        proc = subprocess.run(
            [sys.executable, '-c', code],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, 'AZURPILOT_NTP_DISABLE': '1'},
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])


if __name__ == '__main__':
    unittest.main()
