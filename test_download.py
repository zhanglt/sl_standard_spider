import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from crawl import standard_info_generator
from downloader import downloader


def response(body=b'%PDF-1.7\n', status=200):
    result = MagicMock()
    result.__enter__.return_value = result
    result.headers = {'Content-Length': str(len(body))}
    result.iter_content.return_value = [body]
    if status >= 400:
        error_response = requests.Response()
        error_response.status_code = status
        result.raise_for_status.side_effect = requests.HTTPError(response=error_response)
    return result


class DownloadTests(unittest.TestCase):
    def test_current_and_legacy_table_columns(self):
        for extra in ('', '<td>extra</td>'):
            with self.subTest(extra=extra):
                page = MagicMock()
                page.url = 'http://example.test/list.jsp'
                page.content = (
                    '<table id="dynamic-table"><tbody><tr><td>uuid</td><td>1</td>'
                    '<td><a href="detail.jsp">name</a></td><td>English</td>'
                    '<td>SL 1</td><td>class</td><td>category</td>'
                    '<td>2026/1/1</td><td>2026/2/1</td>' + extra +
                    '<td>department</td></tr><tr><td>incomplete</td></tr></tbody></table>'
                ).encode()
                with patch('crawl.requests.post', return_value=page), patch(
                    'crawl.get_resource_url', return_value='http://example.test/file.pdf'
                ):
                    records = list(standard_info_generator())
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]['hostUnit'], 'department')

    def test_pdf_saved_after_validation(self):
        with tempfile.TemporaryDirectory() as folder, patch(
            'downloader.requests.get', return_value=response()
        ), redirect_stdout(io.StringIO()):
            path = Path(folder) / 'document.pdf'
            downloader('http://example.test/file', str(path))
            self.assertEqual(path.read_bytes(), b'%PDF-1.7\n')
            self.assertFalse(Path(str(path) + '.temp~').exists())

    def test_error_page_does_not_replace_existing_pdf(self):
        with tempfile.TemporaryDirectory() as folder, patch(
            'downloader.requests.get', return_value=response(b'<html>error</html>')
        ), redirect_stdout(io.StringIO()):
            path = Path(folder) / 'document.pdf'
            path.write_bytes(b'%PDF-original')
            with self.assertRaises(ValueError):
                downloader('http://example.test/file', str(path), rewrite=True)
            self.assertEqual(path.read_bytes(), b'%PDF-original')
            self.assertFalse(Path(str(path) + '.temp~').exists())

    def test_http_error_does_not_create_pdf(self):
        with tempfile.TemporaryDirectory() as folder, patch(
            'downloader.requests.get', return_value=response(b'not found', 404)
        ), redirect_stdout(io.StringIO()):
            path = Path(folder) / 'document.pdf'
            with self.assertRaises(requests.HTTPError):
                downloader('http://example.test/file', str(path))
            self.assertFalse(path.exists())

    def test_interrupted_download_retries(self):
        interrupted = response()
        interrupted.iter_content.side_effect = requests.exceptions.ChunkedEncodingError('broken')
        with tempfile.TemporaryDirectory() as folder, patch(
            'downloader.requests.get', side_effect=[interrupted, response()]
        ) as get, patch('downloader.time.sleep'), redirect_stdout(io.StringIO()):
            path = Path(folder) / 'document.pdf'
            downloader('http://example.test/file', str(path), retry=2)
            self.assertEqual(get.call_count, 2)
            self.assertEqual(path.read_bytes(), b'%PDF-1.7\n')


if __name__ == '__main__':
    unittest.main()
