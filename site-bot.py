"""站点监控机器人主入口

- 负责初始化日志与事件循环
- 根据环境配置启动 Telegram 与 Discord 机器人
- 为每个 Telegram 机器人附加定时任务（每小时检查一次订阅源）
"""
import logging
import os
import asyncio

from apps import telegram_bot, discord_bot
from core.config import discord_config, telegram_config


def main():

    # 初始化日志输出格式与等级
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(funcName)s:%(lineno)d] - %(message)s',
        level=logging.INFO
    )

    # 创建并设置事件循环，承载两个机器人运行
    # 注意：Windows 下建议使用默认事件循环策略
    # 如果需要集成到其他服务，请考虑复用外部事件循环

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    # loop = asyncio.get_event_loop()

    tasks = []
    discord_token = str(discord_config['token'])
    telegram_token = str(telegram_config['token'])
    logging.info(f'discord token: {discord_token}')
    logging.info(f'telegram token: {telegram_token}')

    # 如果配置了 Discord token，则启动 Discord 机器人
    if discord_token:
        tasks.append(discord_bot.start_task())

    # 如果配置了 Telegram token（支持多个，用逗号分隔），则启动每个机器人
    # 并为每个机器人添加定时任务以检查 RSS/Sitemap 更新
    if telegram_token:
        tasks.append(telegram_bot.init_task())
        tokens = telegram_token.split(",")
        if len(tokens) >= 1:
            for tel_token in tokens:
                tasks.append(telegram_bot.start_task(tel_token))
                # 为每个bot添加定时任务
                tasks.append(telegram_bot.scheduled_task(tel_token))

    try:
        # 等待所有启动任务完成后，进入常驻运行
        loop.run_until_complete(asyncio.gather(*tasks))
        # loop.call_later(5, asyncio.ensure_future, telegram_bot.scheduled_task())
        loop.run_forever()
    except KeyboardInterrupt:
        # 支持 Ctrl-C 安全退出
        logging.info("Ctrl-C close!!")
        telegram_bot.close_all()
    finally:
        # 关闭事件循环释放资源
        loop.close()


if __name__ == '__main__':
    main()

