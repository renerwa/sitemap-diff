"""Discord 机器人应用层

- 配置 Intents 与命令前缀
- 提供基础示例命令与启动入口
"""
import logging

import discord
from discord import app_commands
from discord.ext import commands
from core.config import discord_config
from services.rss.manager import RSSManager
from pathlib import Path
from urllib.parse import urlparse

description = """An bot to change clothes."""

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="/", description=description, intents=intents)

@bot.command()
async def trip(ctx):
    await ctx.send("trip")

@bot.tree.command(name="trip", description="示例斜杠命令：返回固定文本")
async def trip_slash(interaction: discord.Interaction):
    await interaction.response.send_message("trip")

@bot.tree.command(name="ping", description="测试机器人连通性")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("pong")

rss_manager = RSSManager()

class RSSCommands(app_commands.Group):
    def __init__(self):
        super().__init__(name="rss", description="管理sitemap订阅")

    @app_commands.command(name="list", description="显示所有监控的sitemap")
    async def list(self, interaction: discord.Interaction):
        feeds = rss_manager.get_feeds()
        if not feeds:
            await interaction.response.send_message("当前没有订阅的 sitemap")
            return
        feed_list = "\n".join([f"- {feed}" for feed in feeds])
        await interaction.response.send_message(f"当前订阅列表：\n{feed_list}")

    @app_commands.command(name="add", description="添加sitemap订阅")
    async def add(self, interaction: discord.Interaction, url: str):
        await interaction.response.defer()
        if "sitemap" not in url.lower():
            await interaction.followup.send("URL必须包含 sitemap 关键词，例如 https://example.com/sitemap.xml")
            return
        success, error_msg, dated_file, new_urls = rss_manager.add_feed(url)
        domain = urlparse(url).netloc
        try:
            if success:
                await interaction.followup.send(f"成功添加订阅：{url}")
                header_message = (
                    f"✨ {domain} ✨\n"
                    f"------------------------------------\n"
                    + (f"发现新增内容！ (共 {len(new_urls)} 条)\n" if new_urls else f"{domain} 今日sitemap无更新\n")
                    + f"来源: {url}\n"
                )
                if dated_file and Path(dated_file).exists():
                    await interaction.followup.send(content=header_message, file=discord.File(dated_file))
                    try:
                        Path(dated_file).unlink(missing_ok=True)
                    except Exception:
                        pass
                else:
                    await interaction.followup.send(header_message)
                for u in new_urls:
                    await interaction.followup.send(u)
                if new_urls:
                    await interaction.followup.send(f"✨ {domain} 更新推送完成 ✨\n------------------------------------")
            else:
                if "今天已经更新过此sitemap" in error_msg:
                    await interaction.followup.send(f"该sitemap今天已经更新过：{url}")
                    current_file = rss_manager.sitemap_dir / domain / "sitemap-current.xml"
                    if current_file.exists():
                        await interaction.followup.send(content=f"今天的Sitemap文件\nURL: {url}", file=discord.File(current_file))
                else:
                    await interaction.followup.send(f"添加失败：{error_msg}")
        except Exception as e:
            await interaction.followup.send(f"处理订阅时发生错误：{str(e)}")

    @app_commands.command(name="del", description="删除sitemap订阅")
    async def delete(self, interaction: discord.Interaction, url: str):
        success, error_msg = rss_manager.remove_feed(url)
        if success:
            await interaction.response.send_message(f"成功删除订阅：{url}")
        else:
            await interaction.response.send_message(f"删除失败：{error_msg}")

@bot.tree.command(name="news", description="从存储的sitemap生成并发送关键词速览")
async def news(interaction: discord.Interaction):
    await interaction.response.defer()
    feeds = rss_manager.get_feeds()
    if not feeds:
        await interaction.followup.send("没有配置任何 sitemap 订阅，无法生成关键词速览。")
        return
    all_new_urls = []
    for feed_url in feeds:
        try:
            domain = urlparse(feed_url).netloc
            domain_dir = rss_manager.sitemap_dir / domain
            current_sitemap_file = domain_dir / "sitemap-current.xml"
            latest_sitemap_file = domain_dir / "sitemap-latest.xml"
            if current_sitemap_file.exists() and latest_sitemap_file.exists():
                current_content = current_sitemap_file.read_text()
                latest_content = latest_sitemap_file.read_text()
                new_urls_for_feed = rss_manager.compare_sitemaps(current_content, latest_content)
                all_new_urls.extend(new_urls_for_feed)
        except Exception:
            continue
    if not all_new_urls:
        await interaction.followup.send("所有订阅源的 current/latest 对比均无新增内容。")
        return
    from urllib.parse import urlparse as _parse
    domain_keywords = {}
    for url in all_new_urls:
        try:
            parsed_url = _parse(url)
            domain = parsed_url.netloc
            path_parts = parsed_url.path.rstrip("/").split("/")
            if path_parts and path_parts[-1]:
                keyword = path_parts[-1].strip()
                if keyword:
                    domain_keywords.setdefault(domain, []).append(keyword)
        except Exception:
            continue
    for domain in list(domain_keywords.keys()):
        domain_keywords[domain] = list(set(domain_keywords[domain]))
    if domain_keywords:
        summary_message = "━━━━━━━━━━━━━━━━━━\n🎯 #今日新增 #关键词 #速览 🎯\n━━━━━━━━━━━━━━━━━━\n\n"
        for domain, keywords in domain_keywords.items():
            if keywords:
                summary_message += f"📌 {domain}:\n"
                for i, keyword in enumerate(keywords, 1):
                    summary_message += f"  {i}. {keyword}\n"
                summary_message += "\n"
        await interaction.followup.send(summary_message)

@bot.event
async def on_ready():
    try:
        bot.tree.add_command(RSSCommands())
        guild_id = discord_config.get("guild_id")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            logging.info(f"Synced {len(synced)} slash commands to guild {guild_id}")
        else:
            synced = await bot.tree.sync()
            logging.info(f"Globally synced {len(synced)} slash commands")
    except Exception as e:
        logging.error(f"Slash command sync failed: {str(e)}", exc_info=True)

async def start_task():
    """以任务形式启动 Discord 机器人"""
    token = discord_config["token"]
    logging.info("Starting Discord bot")
    return await bot.start(token)

async def scheduled_task():
    await bot.wait_until_ready()
    channel_id = discord_config.get("target_channel_id")
    if not channel_id:
        return
    try:
        channel = bot.get_channel(int(channel_id))
    except Exception:
        channel = None
    if not channel:
        return
    from urllib.parse import urlparse as _parse
    while True:
        try:
            feeds = rss_manager.get_feeds()
            all_new_urls = []
            for url in feeds:
                success, error_msg, dated_file, new_urls = rss_manager.add_feed(url)
                domain = urlparse(url).netloc
                if success and dated_file and Path(dated_file).exists():
                    header_message = (
                        f"{domain}\n"
                        f"------------------------------------\n"
                        + (f"新增 {len(new_urls)} 条\n" if new_urls else f"{domain} 今日无更新\n")
                        + f"来源: {url}\n"
                    )
                    await channel.send(header_message)
                    await channel.send(file=discord.File(dated_file))
                    try:
                        Path(dated_file).unlink(missing_ok=True)
                    except Exception:
                        pass
                    for u in new_urls:
                        await channel.send(u)
                elif "今天已经更新过此sitemap" in error_msg:
                    pass
                else:
                    pass
                all_new_urls.extend(new_urls)
            await asyncio.sleep(10)
            if all_new_urls:
                domain_keywords = {}
                for u in all_new_urls:
                    try:
                        parsed_url = _parse(u)
                        d = parsed_url.netloc
                        parts = parsed_url.path.rstrip("/").split("/")
                        if parts and parts[-1]:
                            k = parts[-1].strip()
                            if k:
                                domain_keywords.setdefault(d, []).append(k)
                    except Exception:
                        continue
                for d in list(domain_keywords.keys()):
                    domain_keywords[d] = list(set(domain_keywords[d]))
                if domain_keywords:
                    summary_message = "━━━━━━━━━━━━━━━━━━\n#今日新增 #关键词 #速览\n━━━━━━━━━━━━━━━━━━\n\n"
                    for d, keywords in domain_keywords.items():
                        if keywords:
                            summary_message += f"{d}:\n"
                            for i, k in enumerate(keywords, 1):
                                summary_message += f"  {i}. {k}\n"
                            summary_message += "\n"
                    await channel.send(summary_message)
            await asyncio.sleep(3600)
        except Exception:
            await asyncio.sleep(60)
