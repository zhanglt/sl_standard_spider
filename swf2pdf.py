import os
import logging
import sys
import shutil
import subprocess
from pathlib import Path

from fitz import Document

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if 'win' in sys.platform.lower():
    swfrender = os.path.join(BASE_DIR, 'bin', 'swfrender.exe')
elif 'linux' in sys.platform.lower():
    swfrender = os.path.join(BASE_DIR, 'bin', 'swfrender')
else:
    raise OSError('操作系统平台不受支持 -> %s' % sys.platform)


def swf2pdf(src_path: str, target_path: str, dpi: int = 300) -> None:
    if not os.path.isfile(swfrender):
        raise EnvironmentError('找不到 swfrender 程序依赖 -> %s' % swfrender)
    if not os.access(swfrender, os.X_OK):
        raise PermissionError('swfrender 没有执行权限，请执行 chmod +x "%s"' % swfrender)
    name = src_path.split(os.sep)[-1]
    image_path_dir = os.path.join(os.path.dirname(src_path), name.replace('.swf', '-pngs'))
    os.makedirs(image_path_dir, exist_ok=True)
    image_path = os.path.join(image_path_dir, 'content.png')
    logging.info('开始将swf转为png图片，稍候...')
    result = subprocess.run(
        [swfrender, src_path, '-r', str(dpi), '-o', image_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError('swfrender 转换失败: %s' % result.stderr.strip())
    logging.info('已将swf转为png图片 -> %s', image_path_dir)
    logging.info('开始将png转为合并为PDF')
    with Document() as pdf:
        images = sorted(
            Path(image_path_dir).glob('content-*.png'),
            key=lambda path: int(path.stem.rsplit('-', 1)[1]),
        )
        if not images and os.path.isfile(image_path):
            images = [Path(image_path)]
        if not images:
            raise RuntimeError('未从swf文件中解出图片 -> %s' % src_path)
        for img_path in images:
            with Document(str(img_path)) as img:
                with Document(stream=img.convert_to_pdf(), filetype='pdf') as p:
                    pdf.insert_pdf(p)
                    logging.info('添加图片到pdf -> %s', img_path)
        pdf.save(target_path)
    logging.info('合并完成，保存转换后的PDF -> %s', target_path)
    shutil.rmtree(image_path_dir)
    logging.info('临时文件已清除！')

