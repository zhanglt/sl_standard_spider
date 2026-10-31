import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from run import FailureStore, configure_logging, execute
from crawl import standard_info_generator


class RunTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'failures.json'
        self.record = {'code': 'SL 1', 'name': '测试标准',
                       'detail_url': 'http://example.test/detail',
                       'url': 'http://example.test/old.pdf'}

    def read_records(self):
        return json.loads(self.path.read_text(encoding='utf-8'))

    def test_failure_saved_immediately_and_deduplicated(self):
        store = FailureStore(self.path)
        store.fail(self.record, RuntimeError('转换失败'))
        self.assertEqual(self.read_records()[0]['error_type'], 'RuntimeError')
        store.fail(self.record, OSError('磁盘错误'))
        self.assertEqual(len(self.read_records()), 1)
        self.assertEqual(self.read_records()[0]['failure_count'], 2)

    def test_address_failures_are_persisted_by_crawler(self):
        from unittest.mock import MagicMock

        page = MagicMock()
        page.url = 'http://example.test/list'
        page.content = (
            '<table id="dynamic-table"><tbody><tr><td>id</td><td>1</td>'
            '<td><a href="detail">name</a></td><td>English</td><td>SL 1</td>'
            '<td>class</td><td>category</td><td>date</td><td>date</td><td>unit</td>'
            '</tr></tbody></table>'
        ).encode()
        for error in (requests.Timeout('超时'), ValueError('解析异常'), None):
            with self.subTest(error=error), patch('crawl.requests.post', return_value=page), patch(
                'crawl.get_resource_url', side_effect=error, return_value=''
            ):
                store = FailureStore(self.path)
                self.assertEqual(list(standard_info_generator(on_failure=store.fail)), [])
                record = self.read_records()[0]
                self.assertEqual(record['detail_url'], 'http://example.test/detail')
                self.assertTrue(record['error'])

    def test_queue_write_failure_preserves_previous_file(self):
        store = FailureStore(self.path)
        store.fail(self.record, RuntimeError('首次失败'))
        original = self.path.read_bytes()
        with patch('run.os.replace', side_effect=OSError('无法替换文件')):
            with self.assertRaises(OSError):
                store.fail(self.record, RuntimeError('第二次失败'))
        self.assertEqual(self.path.read_bytes(), original)

    def test_download_failure_does_not_stop_next_item(self):
        other = {**self.record, 'code': 'SL 2'}
        with patch('run.standard_info_generator', return_value=[self.record, other]), patch(
            'run.is_file_downloaded', return_value=False
        ), patch('run.download_standard', side_effect=[RuntimeError('转换失败'), None]) as download:
            execute(failed_file=self.path)
        self.assertEqual(download.call_count, 2)
        self.assertEqual(self.read_records()[0]['code'], 'SL 1')

    def test_retry_only_queue_refreshes_url_and_clears_success(self):
        FailureStore(self.path).fail(self.record, ValueError('下载失败'))
        with patch('run.standard_info_generator') as crawl, patch(
            'run.is_file_downloaded', return_value=False
        ), patch('run.get_resource_url', return_value='http://example.test/new.pdf') as resolve, patch(
            'run.download_standard'
        ) as download:
            execute(failed_file=self.path, retry_failed=True)
        crawl.assert_not_called()
        resolve.assert_called_once()
        self.assertEqual(download.call_args.args[0], 'http://example.test/new.pdf')
        self.assertEqual(self.read_records(), [])

    def test_retry_resolution_failure_remains_in_queue(self):
        FailureStore(self.path).fail(self.record, ValueError('无地址'))
        with patch('run.is_file_downloaded', return_value=False), patch(
            'run.get_resource_url', side_effect=requests.Timeout('连接超时')
        ), patch('run.download_standard') as download:
            execute(failed_file=self.path, retry_failed=True)
        download.assert_not_called()
        self.assertEqual(self.read_records()[0]['failure_count'], 2)
        self.assertEqual(self.read_records()[0]['error_type'], 'Timeout')

    def test_direct_url_only_record_can_be_retried(self):
        record = {**self.record, 'detail_url': ''}
        FailureStore(self.path).fail(record, ValueError('下载失败'))
        with patch('run.is_file_downloaded', return_value=False), patch(
            'run.get_resource_url'
        ) as resolve, patch('run.download_standard') as download:
            execute(failed_file=self.path, retry_failed=True)
        resolve.assert_not_called()
        download.assert_called_once_with(record['url'], record['code'], record['name'],
                                         swf2pdf_dpi=300)
        self.assertEqual(self.read_records(), [])

    def test_existing_pdf_removed_without_network(self):
        FailureStore(self.path).fail(self.record, ValueError('下载失败'))
        with patch('run.is_file_downloaded', return_value=True), patch(
            'run.get_resource_url'
        ) as resolve, patch('run.download_standard') as download:
            execute(failed_file=self.path, retry_failed=True)
        resolve.assert_not_called()
        download.assert_not_called()
        self.assertEqual(self.read_records(), [])

    def test_invalid_file_preserved_and_missing_file_rejected(self):
        with self.assertRaises(FileNotFoundError):
            execute(failed_file=self.path, retry_failed=True)
        self.path.write_text('invalid', encoding='utf-8')
        with self.assertRaises(ValueError):
            execute(failed_file=self.path, retry_failed=True)
        self.assertEqual(self.path.read_text(), 'invalid')

    def test_log_file_appends(self):
        path = Path(self.folder.name) / 'logs' / 'run.log'
        root = logging.getLogger()
        old_handlers, old_level = root.handlers[:], root.level
        # Detach existing test-runner handlers before configuring application logging.
        root.handlers = []
        try:
            configure_logging(path)
            logging.info('第一次运行')
            configure_logging(path)
            logging.error('第二次运行')
            content = path.read_text(encoding='utf-8')
            self.assertIn('INFO 第一次运行', content)
            self.assertIn('ERROR 第二次运行', content)
        finally:
            for handler in root.handlers:
                handler.close()
            root.handlers = old_handlers
            root.setLevel(old_level)


if __name__ == '__main__':
    unittest.main()
