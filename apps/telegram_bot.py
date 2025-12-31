"""Telegram 机器人应用层

- 负责构建 Telegram Application、注册基础命令与业务命令
- 支持多个机器人实例（通过逗号分隔多 token）
- 提供定时任务定时检查 RSS/Sitemap 更新并推送
"""
from core.config import telegram_config
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, Application
import logging
import asyncio

tel_bots = {}
commands = [
    BotCommand(command="help", description="Show help message"),
]


async def post_init(application: Application) -> None:
    """在应用初始化后设置机器人命令列表"""
    await application.bot.set_my_commands(commands)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /start 命令，复用帮助信息"""
    await help(update, context)


async def help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """显示帮助信息（当前仅示例欢迎语）"""
    help_text = f"Hello, {update.message.from_user.first_name}"
    await update.message.reply_text(help_text, disable_web_page_preview=True)


async def run(token):
    """启动一个 Telegram Bot 实例，并注册命令与业务模块"""
    global tel_bots
    application = (
        ApplicationBuilder()
        .token(token)
        .concurrent_updates(True)
        .post_init(post_init)
        .build()
    )

    # 用 token 作为 key 存储 bot 实例，便于定时任务取用
    tel_bots[token] = application.bot

    # 注册基础命令
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help))

    # 从 services 加载业务命令（RSS/Sitemap 管理）
    from services.rss.commands import register_commands

    register_commands(application)

    await application.initialize()
    await application.start()
    logging.info("Telegram bot startup successful")
    await application.updater.start_polling(drop_pending_updates=True)


async def init_task():
    """预留的初始化异步任务（当前用于日志标记）"""
    logging.info("Initializing Telegram bot")


async def start_task(token):
    """以任务形式启动指定 token 的机器人"""
    return await run(token)


def close_all():
    """关闭所有 Telegram 机器人（目前仅日志标记，具体关闭由 Application 管理）"""
    logging.info("Closing Telegram bot")


async def scheduled_task(token):
    """定时任务：轮询订阅源，下载并比较 Sitemap 差异，推送更新与关键词汇总"""
    await asyncio.sleep(5)

    bot = tel_bots.get(token)
    if not bot:
        logging.error(f"未找到token对应的bot实例: {token}")
        return

    # 延迟导入，避免循环依赖；复用 rss_manager 与工具函数
    from services.rss.commands import (
        rss_manager,
        send_update_notification,
        send_keywords_summary,
    )

    while True:
        try:
            feeds = rss_manager.get_feeds()
            logging.info(f"定时任务开始检查订阅源更新，共 {len(feeds)} 个订阅")

            # 汇总本轮所有新增 URL，用于生成关键词速览
            all_new_urls = []
            for url in feeds:
                logging.info(f"正在检查订阅源: {url}")
                # add_feed 内部会调用 download_sitemap 并返回新增 URL
                success, error_msg, dated_file, new_urls = rss_manager.add_feed(url)

                if success and dated_file.exists():
                    # 推送文件与新增 URL 列表到目标频道
                    await send_update_notification(bot, url, new_urls, dated_file)
                    if new_urls:
                        logging.info(
                            f"订阅源 {url} 更新成功，发现 {len(new_urls)} 个新URL，已发送通知。"
                        )
                    else:
                        logging.info(f"订阅源 {url} 更新成功，无新增URL，已发送通知。")
                elif "今天已经更新过此sitemap" in error_msg:
                    logging.info(f"订阅源 {url} {error_msg}")
                else:
                    logging.warning(f"订阅源 {url} 更新失败: {error_msg}")
                # 将新URL添加到汇总列表中
                all_new_urls.extend(new_urls)

            # 调用封装函数发送关键词汇总
            await asyncio.sleep(10)  # 等待以确保之前消息发送完成
            await send_keywords_summary(bot, all_new_urls)

            logging.info("所有订阅源检查完成，等待下一次检查")
            await asyncio.sleep(3600)  # 维持 1 小时检查间隔
        except Exception as e:
            logging.error(f"检查订阅源更新失败: {str(e)}", exc_info=True)
            await asyncio.sleep(60)  # 出错后等待 1 分钟再试
