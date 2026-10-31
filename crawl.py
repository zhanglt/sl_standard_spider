import re
import logging
from urllib.parse import urljoin

import requests
from lxml import etree

from downloader import HEADERS
from config import is_file_downloaded, get_file_name

LIST_URL = 'http://121.36.94.83:9008/jsp/yishenqing/appladd/bzsearch.jsp'
TIMEOUT = (10, 60)


def get_resource_url(url: str, code: str, name: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    down_code = re.search(r'window.open\(.*\)', resp.text)
    target_url = ''
    if down_code:
        path = re.sub(r'["+()\s]', '', down_code.group()).replace('window.open', '')
        pdf_url = urljoin(resp.url, path)
        # 从信息页抓取的pdf下载地址，推荐性规范的资源已被删除，不能直接下载，需要转换为swf下载地址
        swf_url = pdf_url.replace('/pdf/', '/swf/').replace('.pdf', '.swf')
        # 判断服务器存在哪种格式的资源，优先下载PDF
        for candidate, content_type in [(pdf_url, 'pdf'), (swf_url, 'flash')]:
            with requests.head(candidate, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True) as resource:
                if resource.ok and content_type in resource.headers.get('Content-Type', '').lower():
                    target_url = candidate
                    break
    if not target_url:
        logging.warning(msg='未解析到下载地址！ -> %s' % get_file_name(code, name))
    return target_url


def standard_info_generator(ignore_downloaded=False, on_failure=None):
    response = requests.post(LIST_URL, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    html = etree.HTML(response.content)
    if html is None:
        raise ValueError('标准列表响应为空')
    trs = html.xpath('//*[@id="dynamic-table"]/tbody/tr')
    if not trs:
        raise ValueError('未找到标准列表，请检查网站是否更改了页面结构')
    for tr in trs:
        if len(tr.xpath('./td')) < 10 or not tr.xpath('./td[3]/a/@href'):
            logging.warning('跳过格式不完整的标准列表行')
            continue
        uuid = ','.join(tr.xpath('./td')[0].xpath('./text()'))
        txh = ','.join(tr.xpath('./td')[1].xpath('./text()'))
        name = re.sub(r'\s+', ' ', ''.join(tr.xpath('./td')[2].xpath('./a/text()')))
        href = urljoin(response.url, tr.xpath('./td')[2].xpath('./a/@href')[0])
        name_en = re.sub(r'\s+', ' ', ''.join(tr.xpath('./td')[3].xpath('./text()')))
        code = re.sub(r'\s+', ' ', ''.join(tr.xpath('./td')[4].xpath('./text()')))
        if ignore_downloaded and is_file_downloaded(code, name):
            continue
        klass = re.sub(r'\s+', ' ', ''.join(tr.xpath('./td')[5].xpath('./text()')))
        category = re.sub(r'\s+', ' ', ''.join(tr.xpath('./td')[6].xpath('./text()')))
        public_date = re.sub(r'\s+', ' ', ''.join(tr.xpath('./td')[7].xpath('./text()')))
        implement_date = re.sub(r'\s+', ' ', ''.join(tr.xpath('./td')[8].xpath('./text()')))
        department = re.sub(r'\s+', ' ', ''.join(tr.xpath('./td')[-1].xpath('./text()')))
        record = {'code': code, 'name': name, 'detail_url': href, 'url': ''}
        try:
            url = get_resource_url(href, code, name)
            if not url:
                raise ValueError('未解析到下载地址')
        except Exception as exc:
            logging.warning('获取下载地址失败，跳过 %s: %s', get_file_name(code, name), exc)
            if on_failure is not None:
                on_failure(record, exc)
            continue

        yield {
            'url': url,
            'detail_url': href,
            'code': code,
            'name': name,
            'englishName': name_en,
            'publicDate': public_date.replace('/', '-'),
            'implementDate': implement_date.replace('/', '-'),
            'hostUnit': department,
            'industrySon': klass,
            'category': category,
            'uuid': uuid,
            'txh': txh,
        }


if __name__ == '__main__':
    for st in standard_info_generator(ignore_downloaded=True):
        print(st)

