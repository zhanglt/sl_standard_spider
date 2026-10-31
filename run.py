import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from config import BASE_DIR, is_file_downloaded
from crawl import get_resource_url, standard_info_generator
from download_standard import download_standard

DEFAULT_FAILED_FILE = Path(BASE_DIR) / 'failed_downloads.json'
DEFAULT_LOG_FILE = Path(BASE_DIR) / 'logs' / 'run.log'


class FailureStore:
    def __init__(self, path):
        self.path = Path(path)
        self.records = {}
        if self.path.exists():
            records = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(records, list):
                raise ValueError('失败记录必须是 JSON 数组')
            for record in records:
                if (not isinstance(record, dict)
                        or not all(isinstance(record.get(field), str) for field in ('code', 'name'))
                        or not any(isinstance(record.get(field), str) and record[field]
                                   for field in ('url', 'detail_url'))
                        or not isinstance(record.get('failure_count', 0), int)
                        or record.get('failure_count', 0) < 0):
                    raise ValueError('失败记录缺少 code、name 或下载/详情地址')
                self.records[self.key(record)] = record

    @staticmethod
    def key(record):
        return record['code'], record['name']

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + '.tmp')
        temporary.write_text(
            json.dumps(list(self.records.values()), ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8',
        )
        os.replace(temporary, self.path)

    def fail(self, record, exc):
        key = self.key(record)
        previous = self.records.get(key, {})
        self.records[key] = {
            **record,
            'error': str(exc),
            'error_type': type(exc).__name__,
            'failed_at': datetime.now(timezone.utc).isoformat(),
            'failure_count': previous.get('failure_count', 0) + 1,
        }
        self.save()
        logging.error('条目失败 %s《%s》: %s', record['code'], record['name'], exc)

    def success(self, record):
        if self.records.pop(self.key(record), None) is not None:
            self.save()


def configure_logging(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.FileHandler(path, encoding='utf-8'), logging.StreamHandler()],
        force=True,
    )


def execute(swf2pdf_dpi=300, failed_file=DEFAULT_FAILED_FILE, retry_failed=False):
    store = FailureStore(failed_file)
    if retry_failed:
        if not store.path.exists():
            raise FileNotFoundError('失败记录文件不存在: %s' % store.path)
        # Snapshot the queue because successful items are removed during processing.
        records = list(store.records.values())
        logging.info('仅重试失败条目，共 %s 项，记录文件: %s', len(records), store.path)
    else:
        records = standard_info_generator(ignore_downloaded=True, on_failure=store.fail)
        logging.info('开始遍历标准列表，失败记录文件: %s', store.path)
    store.save()
    for record in records:
        try:
            if not record.get('code') or not record.get('name'):
                raise ValueError('标准编号或名称为空')
            if not is_file_downloaded(record['code'], record['name']):
                if retry_failed and record.get('detail_url'):
                    record['url'] = get_resource_url(
                        record['detail_url'], record['code'], record['name'])
                if not record.get('url'):
                    raise ValueError('未解析到下载地址')
                logging.info('开始下载 %s《%s》: %s', record['code'], record['name'], record['url'])
                download_standard(record['url'], record['code'], record['name'],
                                  swf2pdf_dpi=swf2pdf_dpi)
        except Exception as exc:
            store.fail(record, exc)
        else:
            store.success(record)
            logging.info('条目完成 %s《%s》', record['code'], record['name'])
    logging.info('本轮运行结束，剩余失败条目: %s', len(store.records))


def main():
    parser = argparse.ArgumentParser(description='下载水利标准，记录日志并支持失败条目重试')
    parser.add_argument('--failed-file', type=Path, default=DEFAULT_FAILED_FILE,
                        help='失败记录 JSON 文件路径')
    parser.add_argument('--retry-failed', nargs='?', const=True, type=Path,
                        help='仅重试失败记录，可指定文件路径')
    parser.add_argument('--log-file', type=Path, default=DEFAULT_LOG_FILE,
                        help='运行日志路径（追加写入）')
    parser.add_argument('--dpi', type=int, default=150, help='SWF 转 PDF 的 DPI')
    args = parser.parse_args()
    configure_logging(args.log_file)
    try:
        if args.dpi <= 0:
            raise ValueError('DPI 必须大于零')
        failed_file = (args.retry_failed if isinstance(args.retry_failed, Path)
                       else args.failed_file)
        execute(args.dpi, failed_file,
                retry_failed=args.retry_failed is not None)
    except Exception:
        logging.exception('运行中止')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
