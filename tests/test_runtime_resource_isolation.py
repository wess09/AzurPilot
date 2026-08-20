"""运行态资源隔离与共享缓存回归测试。"""

import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np

from module.base.button import Button
from module.base.async_executor import async_executor
from module.base.runtime_context import (
    RuntimeContext,
    clear_runtime_context,
    current_runtime_id,
    runtime_scope,
)
from module.statistics.item import ItemGrid
from module.logger import logger, reset_runtime_log_context, set_runtime_log_context


class TestButtonRuntimeProperties(unittest.TestCase):
    def test_dynamic_properties_are_isolated_and_no_scope_remains_compatible(self):
        button = Button(
            area=(0, 0, 10, 10),
            color=(255, 255, 255),
            button=(10, 10, 20, 20),
            name='BASE_BUTTON',
        )
        alpha = RuntimeContext('button-alpha')
        beta = RuntimeContext('button-beta')

        with runtime_scope(context=alpha):
            button.area = (1, 2, 11, 12)
            button._button = (3, 4, 13, 14)
            button.name = 'ALPHA_BUTTON'
            self.assertEqual((1, 2, 11, 12), button.area)
            self.assertEqual((3, 4, 13, 14), button._button)
            self.assertEqual('ALPHA_BUTTON', button.name)

        with runtime_scope(context=beta):
            self.assertEqual((0, 0, 10, 10), button.area)
            self.assertEqual((10, 10, 20, 20), button._button)
            self.assertEqual('BASE_BUTTON', button.name)
            button.area = (5, 6, 15, 16)
            button._button = (7, 8, 17, 18)
            button.name = 'BETA_BUTTON'

        with runtime_scope(context=alpha):
            self.assertEqual((1, 2, 11, 12), button.area)
            self.assertEqual((3, 4, 13, 14), button._button)
            self.assertEqual('ALPHA_BUTTON', button.name)

        # 未进入运行态时仍使用原有的实例字段语义。
        button.name = 'LEGACY_BUTTON'
        self.assertEqual('LEGACY_BUTTON', button.name)

    def test_area_override_does_not_reuse_another_workers_preheated_template(self):
        button = Button(
            area=(0, 0, 10, 10),
            color=(255, 255, 255),
            button=(0, 0, 10, 10),
            file='runtime-test-button.png',
            name='RUNTIME_TEMPLATE_BUTTON',
        )
        alpha = RuntimeContext('template-alpha')
        beta = RuntimeContext('template-beta')
        loaded_areas = []

        def load_template(_file, area):
            loaded_areas.append(area)
            return np.full((10, 10, 3), area[0], dtype=np.uint8)

        with patch('module.base.button.load_image', side_effect=load_template):
            with runtime_scope(context=alpha):
                button.ensure_binary_template()
                button.ensure_luma_template()
                alpha_binary = button.image_binary
                alpha_luma = button.image_luma

            with runtime_scope(context=beta):
                button.area = (10, 0, 20, 10)
                button.ensure_binary_template()
                button.ensure_luma_template()
                self.assertEqual(10, int(button.image[0, 0, 0]))
                self.assertIsNot(alpha_binary, button.image_binary)
                self.assertIsNot(alpha_luma, button.image_luma)

        self.assertEqual([(0, 0, 10, 10), (10, 0, 20, 10)], loaded_areas)


class TestItemGridRuntimeState(unittest.TestCase):
    def test_static_templates_are_shared_but_hits_and_items_are_isolated(self):
        grid = ItemGrid(None, {})
        alpha = RuntimeContext('grid-alpha')
        beta = RuntimeContext('grid-beta')
        template = object()
        cost_template = object()

        with runtime_scope(context=alpha):
            grid.templates['shared'] = template
            grid.colors['shared'] = (1, 2, 3)
            grid.cost_templates['cost'] = cost_template
            grid.templates_hit['shared'] = 4
            grid.cost_templates_hit['cost'] = 5
            grid.items = ['alpha-item']

        with runtime_scope(context=beta):
            self.assertIs(template, grid.templates['shared'])
            self.assertEqual((1, 2, 3), grid.colors['shared'])
            self.assertIs(cost_template, grid.cost_templates['cost'])
            self.assertEqual(0, grid.templates_hit['shared'])
            self.assertEqual(0, grid.cost_templates_hit['cost'])
            self.assertEqual([], grid.items)
            grid.templates_hit['shared'] = 9
            grid.cost_templates_hit['cost'] = 10
            grid.items = ['beta-item']

        with runtime_scope(context=alpha):
            self.assertEqual(4, grid.templates_hit['shared'])
            self.assertEqual(5, grid.cost_templates_hit['cost'])
            self.assertEqual(['alpha-item'], grid.items)

        with runtime_scope(context=beta):
            self.assertEqual(9, grid.templates_hit['shared'])
            self.assertEqual(10, grid.cost_templates_hit['cost'])
            self.assertEqual(['beta-item'], grid.items)

    def test_extract_template_waits_for_shared_template_snapshot_lock(self):
        grid = ItemGrid(None, {})
        prepared = threading.Event()
        begin = threading.Event()
        load_called = threading.Event()
        completed = threading.Event()
        errors = []

        def load_items(_image):
            grid.items = []
            load_called.set()

        grid._load_image = load_items

        def extract():
            try:
                with runtime_scope('item-snapshot-race'):
                    # 预先建立该线程的运行态，确保随后阻塞的位置正是模板快照。
                    grid.items = []
                    prepared.set()
                    begin.wait(timeout=1)
                    grid.extract_template(None)
            except BaseException as exc:
                errors.append(exc)
            finally:
                completed.set()

        thread = threading.Thread(target=extract)
        thread.start()
        self.assertTrue(prepared.wait(timeout=1))
        try:
            with grid._template_lock:
                begin.set()
                self.assertTrue(load_called.wait(timeout=1))
                self.assertFalse(completed.wait(timeout=0.1))
        finally:
            thread.join(timeout=1)
            clear_runtime_context('item-snapshot-race')

        self.assertFalse(thread.is_alive())
        self.assertEqual([], errors)


class TestRuntimeContextCleanup(unittest.TestCase):
    def test_clear_removes_options_with_full_context(self):
        context = RuntimeContext('cleanup')
        context.set_option('strict_ocr_server', True)
        context.state(object(), 'state', dict)['value'] = 1

        context.clear()

        self.assertIsNone(context.get_option('strict_ocr_server'))


class TestRuntimeLogRouting(unittest.TestCase):
    def test_logger_print_routes_to_current_worker_file_and_renderable_sink(self):
        alpha = RuntimeContext('log-alpha')
        sink = Mock()
        with runtime_scope(context=alpha):
            set_runtime_log_context('runtime-log-test', sink)
            try:
                logger.print('隔离日志输出')
                self.assertTrue(sink.called)
            finally:
                reset_runtime_log_context()


class TestRuntimeContextPropagation(unittest.TestCase):
    def test_async_executor_carries_worker_context_to_background_loop(self):
        with runtime_scope('async-context-test'):
            future = async_executor.submit(current_runtime_id)
            self.assertEqual('async-context-test', future.result(timeout=2))
        clear_runtime_context('async-context-test')


if __name__ == '__main__':
    unittest.main()
