"""RSS/Sitemap 管理器

- 负责持久化订阅源列表与创建目录结构
- 下载并保存每日 sitemap，维护 current/latest 两份版本
- 比较新旧 sitemap 差异，返回新增 URL 列表
"""
import json
import logging
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
import requests
import gzip
from io import BytesIO
from typing import Set


class RSSManager:
    """封装对 RSS/Sitemap 的增删查与下载、比较逻辑"""
    def __init__(self):
        self.config_dir = Path("storage/rss/config")
        self.sitemap_dir = Path("storage/rss/sitemaps")  # 存储 sitemap 的基础目录
        self.feeds_file = self.config_dir / "feeds.json"
        self._init_directories()

    def _init_directories(self):
        """初始化必要目录与订阅配置文件"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.sitemap_dir.mkdir(parents=True, exist_ok=True)

        if not self.feeds_file.exists():
            self.feeds_file.write_text("[]")

    def download_sitemap(self, url: str) -> tuple[bool, str, Path | None, list[str]]:
        """下载并保存 sitemap 文件

        Args:
            url: sitemap的URL

        Returns:
            tuple[bool, str, Path | None, list[str]]: (是否成功, 错误信息, 带日期的文件路径, 新增的 URL 列表)
        """
        try:
            # 以域名分目录存放相关文件
            logging.info(f"尝试下载sitemap: {url}")
            # 从URL中提取域名作为目录名
            domain = urlparse(url).netloc
            # 构建完整路径
            domain_dir = self.sitemap_dir / domain
            # 为该域名创建专属文件夹（如果不存在）
            domain_dir.mkdir(parents=True, exist_ok=True)

            # 检查今天是否已经更新过（避免重复下载）
            last_update_file = domain_dir / "last_update.txt"
            today = datetime.now().strftime("%Y%m%d")
            logging.info(f"今天的日期: {today}")

            # 维护 current/latest 两份版本，并生成当日带日期的临时文件用于发送
            current_file = domain_dir / "sitemap-current.xml"
            latest_file = domain_dir / "sitemap-latest.xml"
            dated_file = domain_dir / f"{domain}_sitemap_{today}.xml"

            # 如果上次更新日期与今天相同，且相关文件已存在，则直接返回
            if last_update_file.exists():
                # 从文件读取上次更新日期
                last_date = last_update_file.read_text().strip()
                logging.info(f"上次更新日期: {last_date}")
                if last_date == today:
                    if (
                        dated_file.exists()
                        and current_file.exists()
                        and latest_file.exists()
                    ):
                        current_content = current_file.read_text()
                        latest_content = latest_file.read_text()
                        new_urls = self.compare_sitemaps(
                            current_content, latest_content
                        )
                        return True, "今天已经更新过此sitemap, 但没发送", dated_file, new_urls
                    return (
                        dated_file.exists(),
                        "今天已经更新过此sitemap",
                        dated_file,
                        [],
                    )

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            }
            response = requests.get(url, timeout=20, headers=headers)
            response.raise_for_status()

            combined_urls = self._collect_urls_from_sitemap(response, headers=headers, depth=0)
            combined_xml = self._build_urlset_xml(combined_urls)

            new_urls = []
            if current_file.exists():
                old_content = current_file.read_text()
                new_urls = self.compare_sitemaps(combined_xml, old_content)
                current_file.replace(latest_file)

            current_file.write_text(combined_xml)
            dated_file.write_text(combined_xml)

            last_update_file.write_text(today)

            logging.info(f"sitemap已保存到: {current_file}")
            return True, "", dated_file, new_urls  # 返回新增 URL 列表

        except requests.exceptions.RequestException as e:
            return False, f"下载失败: {str(e)}", None, []
        except Exception as e:
            return False, f"保存失败: {str(e)}", None, []

    def add_feed(self, url: str) -> tuple[bool, str, Path | None, list[str]]:
        """添加 sitemap 监控（首次会下载当日文件）

        Args:
            url: sitemap的URL

        Returns:
            tuple[bool, str, Path | None, list[str]]: (是否成功, 错误信息, 带日期的文件路径, 新增的 URL 列表)
        """
        try:
            logging.info(f"尝试添加sitemap监控: {url}")

            # 验证是否已存在
            feeds = self.get_feeds()
            if url not in feeds:
                # 如果是新的feed，先尝试下载
                success, error_msg, dated_file, new_urls = self.download_sitemap(url)
                if not success:
                    return False, error_msg, None, []

                # 添加到监控列表
                feeds.append(url)
                self.feeds_file.write_text(json.dumps(feeds, indent=2))
                logging.info(f"成功添加sitemap监控: {url}")
                return True, "", dated_file, new_urls
            else:
                # 已存在的 feed 也尝试下载（可能是新的一天）
                success, error_msg, dated_file, new_urls = self.download_sitemap(url)
                if not success:
                    return False, error_msg, None, []
                return True, "已存在的feed更新成功", dated_file, new_urls

        except Exception as e:
            logging.error(f"添加sitemap监控失败: {url}", exc_info=True)
            return False, f"添加失败: {str(e)}", None, []

    def remove_feed(self, url: str) -> tuple[bool, str]:
        """删除 RSS 订阅

        Args:
            url: RSS订阅链接

        Returns:
            tuple[bool, str]: (是否删除成功, 错误信息)
        """
        try:
            logging.info(f"尝试删除RSS订阅: {url}")
            feeds = self.get_feeds()

            if url not in feeds:
                logging.warning(f"RSS订阅不存在: {url}")
                return False, "该RSS订阅不存在"

            feeds.remove(url)
            logging.info(f"正在写入RSS订阅到文件: {self.feeds_file}")
            self.feeds_file.write_text(json.dumps(feeds, indent=2))
            logging.info(f"成功删除RSS订阅: {url}")
            return True, ""
        except Exception as e:
            logging.error(f"删除RSS订阅失败: {url}", exc_info=True)
            return False, f"删除失败: {str(e)}"

    def get_feeds(self) -> list:
        """获取所有监控的订阅源列表"""
        try:
            content = self.feeds_file.read_text()
            return json.loads(content)
        except Exception as e:
            logging.error("读取feeds文件失败", exc_info=True)
            return []

    def compare_sitemaps(self, current_content: str, old_content: str) -> list[str]:
        """比较新旧 sitemap，返回新增的 URL 列表

        采用官方 sitemap 命名空间解析 URL 列表，取差集获得新增项
        """
        try:
            current_urls = self._extract_all_urls(current_content)
            old_urls = self._extract_all_urls(old_content)
            return list(current_urls - old_urls)
        except Exception as e:
            logging.error(f"比较sitemap失败: {str(e)}")
            return []

    def _build_urlset_xml(self, urls: Set[str]) -> str:
        ns = "http://www.sitemaps.org/schemas/sitemap/0.9"
        items = []
        for u in sorted(urls):
            items.append(f"<url><loc>{u}</loc></url>")
        return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="{ns}">\n' + "\n".join(items) + "\n</urlset>"

    def _is_gzip_response(self, resp: requests.Response, url: str) -> bool:
        ct = (resp.headers.get("Content-Type") or "").lower()
        ce = (resp.headers.get("Content-Encoding") or "").lower()
        return url.lower().endswith(".gz") or "gzip" in ce or "application/gzip" in ct or "application/x-gzip" in ct

    def _response_to_text(self, resp: requests.Response, url: str) -> str:
        try:
            if self._is_gzip_response(resp, url):
                raw = resp.content
                try:
                    data = gzip.decompress(raw)
                except OSError:
                    data = raw
                try:
                    return data.decode("utf-8")
                except UnicodeDecodeError:
                    return data.decode("latin-1", errors="ignore")
            else:
                if resp.encoding:
                    return resp.text
                return resp.content.decode("utf-8", errors="ignore")
        except Exception:
            return resp.text

    def _collect_urls_from_sitemap(self, resp: requests.Response, headers: dict, depth: int) -> Set[str]:
        from xml.etree import ElementTree as ET
        txt = self._response_to_text(resp, resp.url)
        urls: Set[str] = set()
        try:
            root = ET.fromstring(txt)
        except Exception:
            return urls
        tag = root.tag.lower()
        if tag.endswith("urlset"):
            for loc in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc"):
                if loc.text:
                    urls.add(loc.text.strip())
            if not urls:
                for loc in root.findall(".//loc"):
                    if loc.text:
                        urls.add(loc.text.strip())
            return urls
        if tag.endswith("sitemapindex"):
            if depth > 3:
                return urls
            for node in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}sitemap/{http://www.sitemaps.org/schemas/sitemap/0.9}loc"):
                if node.text:
                    child_url = node.text.strip()
                    try:
                        child_resp = requests.get(child_url, timeout=20, headers=headers)
                        child_resp.raise_for_status()
                        child_urls = self._collect_urls_from_sitemap(child_resp, headers=headers, depth=depth + 1)
                        urls.update(child_urls)
                    except Exception:
                        logging.warning(f"子 sitemap 获取失败: {child_url}")
            if not urls:
                for node in root.findall(".//sitemap/loc"):
                    if node.text:
                        child_url = node.text.strip()
                        try:
                            child_resp = requests.get(child_url, timeout=20, headers=headers)
                            child_resp.raise_for_status()
                            child_urls = self._collect_urls_from_sitemap(child_resp, headers=headers, depth=depth + 1)
                            urls.update(child_urls)
                        except Exception:
                            logging.warning(f"子 sitemap 获取失败: {child_url}")
            return urls
        return urls

    def _extract_all_urls(self, xml_text: str) -> Set[str]:
        from xml.etree import ElementTree as ET
        urls: Set[str] = set()
        try:
            root = ET.fromstring(xml_text)
        except Exception:
            return urls
        tag = root.tag.lower()
        if tag.endswith("urlset"):
            for loc in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc"):
                if loc.text:
                    urls.add(loc.text.strip())
            if not urls:
                for loc in root.findall(".//loc"):
                    if loc.text:
                        urls.add(loc.text.strip())
        elif tag.endswith("sitemapindex"):
            urls = set()
        return urls
