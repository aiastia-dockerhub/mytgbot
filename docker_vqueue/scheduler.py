"""定时任务模块 - 24小时活跃度检查"""
import logging

from telegram.ext import ContextTypes

from database import check_and_reset_24h_counts
from sender import process_queue

from config import ACTIVE_CHECK_INTERVAL, QUEUE_CHECK_INTERVAL

logger = logging.getLogger(__name__)


async def job_active_check(context: ContextTypes.DEFAULT_TYPE):
    """定时检查用户24h活跃度"""
    logger.info("开始24小时活跃度检查...")
    stopped_ids = check_and_reset_24h_counts()

    if stopped_ids:
        logger.info("以下用户因不活跃被系统停止: %s", stopped_ids)
        # 通知被停止的用户
        for uid in stopped_ids:
            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text="⚠️ 由于你24小时内发送的视频不足，已被系统暂停。\n"
                         "发送 /resume 可以重新恢复。"
                )
            except Exception as e:
                logger.warning("通知用户 %s 失败: %s", uid, e)
    else:
        logger.info("24小时活跃度检查完成，无需停止用户")


async def job_process_queue(context: ContextTypes.DEFAULT_TYPE):
    """定时处理发送队列"""
    await process_queue(context)


def setup_jobs(application):
    """注册所有定时任务"""
    job_queue = application.job_queue

    # 队列处理：每 QUEUE_CHECK_INTERVAL 秒执行
    job_queue.run_repeating(
        job_process_queue,
        interval=QUEUE_CHECK_INTERVAL,
        first=10,
        name="process_queue"
    )

    # 活跃度检查：每 ACTIVE_CHECK_INTERVAL 秒执行
    job_queue.run_repeating(
        job_active_check,
        interval=ACTIVE_CHECK_INTERVAL,
        first=60,
        name="active_check"
    )

    logger.info("已注册定时任务: 队列处理(每%ds), 活跃度检查(每%ds)",
                QUEUE_CHECK_INTERVAL, ACTIVE_CHECK_INTERVAL)