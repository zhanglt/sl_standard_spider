import os
import logging
import re
import sys
import time

import requests

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36 Edg/96.0.1054.62',
}


def get_size_flag(total_length: int) -> tuple:
    if total_length >= 1073741824:
        return 1073741824, 'GB'
    if total_length >= 1048576:
        return 1048576, 'MB'
    return 1024, 'KB'


def downloader(url: str, path: str = None, chunk_size: int = 4096,
               rewrite: bool = False, retry: int = 1, **kwargs) -> None:
    if not path:
        path = re.sub(r'[/\\<>?:"|*]+', ' ', url.split('/')[-1])
        path = os.path.join('.', path)
    if os.path.isfile(path) and os.path.getsize(path) > 0 and not rewrite:
        logging.info('文件已存在：%s', path)
        return

    logging.info('下载：%s -> %s', url, path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    temp_path = path + '.temp~'
    kwargs.setdefault('timeout', (10, 60))
    attempt = 0
    while True:
        attempt += 1
        started = time.monotonic()
        try:
            with requests.get(url, stream=True, **kwargs) as response:
                response.raise_for_status()
                total_length = int(response.headers.get('Content-Length', 0))
                downloaded = 0
                signature = b''
                with open(temp_path, 'wb') as output:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if not chunk:
                            continue
                        if len(signature) < 5:
                            signature = (signature + chunk)[:5]
                        downloaded += len(chunk)
                        output.write(chunk)
                        unit, label = get_size_flag(downloaded)
                        speed = downloaded / max(time.monotonic() - started, 0.001) / 1024
                        sys.stdout.write('\r\t已下载:%.2f%s  下载速度:%.2fkB/s' % (
                            downloaded / unit, label, speed))
                        sys.stdout.flush()

                # Some error pages return HTTP 200; validate before publishing the file.
                if not downloaded:
                    raise ValueError('服务器返回空文件')
                if path.lower().endswith('.pdf') and signature != b'%PDF-':
                    raise ValueError('服务器返回的内容不是 PDF 文件')
                if path.lower().endswith('.swf') and signature[:3] not in (b'FWS', b'CWS', b'ZWS'):
                    raise ValueError('服务器返回的内容不是 SWF 文件')
                if total_length and not response.headers.get('Content-Encoding') and downloaded != total_length:
                    raise requests.exceptions.ChunkedEncodingError('下载文件不完整')
            os.replace(temp_path, path)
            unit, label = get_size_flag(downloaded)
            logging.info('下载完成！\t文件大小：%.2f%s\t共用时：%.2fS',
                         downloaded / unit, label, time.monotonic() - started)
            return
        except (requests.RequestException, ValueError) as exc:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            if isinstance(exc, requests.HTTPError) and exc.response is not None:
                if 400 <= exc.response.status_code < 500:
                    raise
            if retry > 0 and attempt >= retry:
                raise
            logging.warning('下载失败（第 %s 次尝试），5S后重试：%s', attempt, exc)
            time.sleep(5)
