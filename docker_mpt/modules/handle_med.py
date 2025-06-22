
import logging 

import os
from datetime import datetime
from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto, MessageMediaWebPage
logging.basicConfig(
    level=logging.INFO, # 可以暂时设置为 DEBUG 级别以获取更多信息
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def handle_media(message, account_config):
    """处理媒体文件"""
    logger.debug(f"[DEBUG] handle_media triggered for message_id: {message.id}")
    try:
        if not account_config['storage'].get('auto_download', False): # 确保 auto_download 配置存在且为True
            logger.debug("Auto download is disabled in config. Skipping media download.")
            return

        download_path_base = account_config['storage'].get('download_path', './downloads')
        os.makedirs(download_path_base, exist_ok=True) # 确保下载路径存在
        logger.debug(f"Download path base: {download_path_base}")

        file_name = None
        ext = None
        mime = None
        if message.media:
            if isinstance(message.media, MessageMediaDocument) and message.media.document:
                doc = message.media.document
                # 优先从 attributes 获取文件名
                for attr in doc.attributes:
                    if hasattr(attr, 'file_name') and attr.file_name:
                        file_name = attr.file_name
                        break
                mime = getattr(doc, 'mime_type', None)
                logger.debug(f"Media is document, original file_name: {file_name}, mime_type: {mime}")
                # 如果没有 file_name，尝试用 mime_type 推断扩展名
                if not file_name:
                    ext = None
                    if mime:
                        if mime.startswith('image/'):
                            ext = '.' + mime.split('/')[-1]
                        elif mime.startswith('video/'):
                            ext = '.' + mime.split('/')[-1]
                        elif mime.startswith('audio/'):
                            ext = '.' + mime.split('/')[-1]
                        elif mime == 'application/pdf':
                            ext = '.pdf'
                        elif mime == 'text/plain':
                            ext = '.txt'
                    file_name = f"document_{message.id}{ext or '.file'}"
                else:
                    # 如果 file_name 没有扩展名但 mime_type 有，补全扩展名
                    if '.' not in file_name and mime:
                        if mime.startswith('image/'):
                            file_name += '.' + mime.split('/')[-1]
                        elif mime.startswith('video/'):
                            file_name += '.' + mime.split('/')[-1]
                        elif mime.startswith('audio/'):
                            file_name += '.' + mime.split('/')[-1]
                        elif mime == 'application/pdf':
                            file_name += '.pdf'
                        elif mime == 'text/plain':
                            file_name += '.txt'
            elif isinstance(message.media, MessageMediaPhoto):
                file_name = f"photo_{message.id}.jpg"
                logger.debug(f"Media is photo, generated file_name: {file_name}")
            elif isinstance(message.media, MessageMediaWebPage) and message.media.webpage.document:
                doc = message.media.webpage.document
                for attr in doc.attributes:
                    if hasattr(attr, 'file_name') and attr.file_name:
                        file_name = attr.file_name
                        break
                mime = getattr(doc, 'mime_type', None)
                if not file_name:
                    ext = None
                    if mime:
                        if mime.startswith('image/'):
                            ext = '.' + mime.split('/')[-1]
                        elif mime.startswith('video/'):
                            ext = '.' + mime.split('/')[-1]
                        elif mime.startswith('audio/'):
                            ext = '.' + mime.split('/')[-1]
                        elif mime == 'application/pdf':
                            ext = '.pdf'
                        elif mime == 'text/plain':
                            ext = '.txt'
                    file_name = f"webmedia_{message.id}{ext or '.file'}"
                else:
                    if '.' not in file_name and mime:
                        if mime.startswith('image/'):
                            file_name += '.' + mime.split('/')[-1]
                        elif mime.startswith('video/'):
                            file_name += '.' + mime.split('/')[-1]
                        elif mime.startswith('audio/'):
                            file_name += '.' + mime.split('/')[-1]
                        elif mime == 'application/pdf':
                            file_name += '.pdf'
                        elif mime == 'text/plain':
                            file_name += '.txt'
                logger.debug(f"Media is webpage document, generated file_name: {file_name}, mime_type: {mime}")
            else:
                file_name = f"media_{message.id}.unknown" # 通用回退
                logger.debug(f"Media is unknown type, generated file_name: {file_name}")

            if file_name:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                formatted_name_pattern = account_config['storage'].get('file_naming', "{timestamp}_{chat_id}_{message_id}_{filename}")
                formatted_name = formatted_name_pattern.format(
                    chat_id=message.chat_id,
                    message_id=message.id,
                    timestamp=timestamp,
                    filename=file_name
                )

                download_path_full = os.path.join(download_path_base, formatted_name)
                logger.info(f"准备下载媒体文件到: {download_path_full}")
                await message.download_media(download_path_full)
                logger.info(f"已下载媒体文件: {formatted_name}")
            else:
                logger.warning(f"Could not determine file name for message {message.id}, skipping download.")
        else:
            logger.debug(f"No media found in message {message.id}.")
    except Exception as e:
        logger.error(f"处理媒体文件时出错: {str(e)}", exc_info=True)

