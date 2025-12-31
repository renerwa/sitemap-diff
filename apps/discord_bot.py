"""Discord 机器人应用层

- 配置 Intents 与命令前缀
- 提供基础示例命令与启动入口
"""
import logging

import discord
from discord.ext import commands
from core.config import discord_config

description = """An bot to change clothes."""

# 配置机器人的意图，允许读取成员与消息内容
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# 创建命令机器人，使用斜杠前缀
bot = commands.Bot(command_prefix="/", description=description, intents=intents)


@bot.command()
async def trip(ctx):
    """示例命令：回复固定文本"""
    await ctx.send(f"trip")


async def start_task():
    """以任务形式启动 Discord 机器人"""
    token = discord_config["token"]
    logging.info(f"{token}")
    return await bot.start(token)
