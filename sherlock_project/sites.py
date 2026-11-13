"""Sherlock 站点信息模块。

保存网站信息，为用户名查询提供原始数据。
"""
import json
import requests
import secrets


MANIFEST_URL = "https://data.sherlockproject.xyz"
EXCLUSIONS_URL = "https://raw.githubusercontent.com/sherlock-project/sherlock/refs/heads/exclusions/false_positive_exclusions.txt"

class SiteInformation:
    def __init__(self, name, url_home, url_username_format, username_claimed,
                information, is_nsfw, username_unclaimed=secrets.token_urlsafe(10)):
        """创建单个站点的信息对象。

        参数：
        self                   -- 当前对象。
        name                   -- 站点名称字符串。
        url_home               -- 站点首页 URL 字符串。
        url_username_format    -- 用户个人主页的 URL 模板字符串。
                                  用 "{}" 标记需要替换为用户名的位置。
                                  例如，"https://somesite.com/users/{}" 表示
                                  用户个人主页位于该站点的 /users/ 路径下。
        username_claimed       -- 已知在该站点注册的用户名字符串。
        username_unclaimed     -- 预留的未注册用户名参数；当前实现不使用传入值，
                                  而是随机生成用于测试的用户名。
        information            -- 包含站点全部已知信息的字典，
                                  包括检测用户名是否存在所需的自定义规则。
                                  本对象仅保存这些信息，供后续检测使用。
        is_nsfw                -- 是否为含有不适宜工作场所内容的站点（NSFW）。

        返回值：
        无。
        """

        self.name = name
        self.url_home = url_home
        self.url_username_format = url_username_format

        self.username_claimed = username_claimed
        self.username_unclaimed = secrets.token_urlsafe(32)
        self.information = information
        self.is_nsfw  = is_nsfw


    def __str__(self):
        """返回包含站点名称和首页 URL 的字符串。"""

        return f"{self.name} ({self.url_home})"


class SitesInformation:
    def __init__(
            self,
            data_file_path: str|None = None,
            honor_exclusions: bool = True,
            do_not_exclude: list[str] = [],
        ):
        """创建包含所有支持站点的信息对象。

        参数：
        self                   -- 当前对象。
        data_file_path         -- JSON 数据文件路径或 URL 字符串。
                                  支持以下形式：
                                  * 绝对路径，例如 "c:/stuff/data.json"。
                                  * 相对于当前工作目录的路径，例如 "data.json"。
                                  * URL，例如 "https://example.com/data.json"
                                    或 "http://example.com/data.json"。
                                  加载或解析失败时抛出异常。
                                  未指定时使用默认的远程站点清单。
        honor_exclusions       -- 是否应用远程排除列表，默认为 True。
        do_not_exclude         -- 即使在排除列表中，也需要保留的站点名称列表。

        返回值：
        无。
        """

        if not data_file_path:
            # 默认从远程加载最新的站点清单，
            # 使用户及时获得站点规则更新，避免因本地数据过时
            # 而重复报告已经修复的误报问题。
            data_file_path = MANIFEST_URL

        if data_file_path.lower().startswith("http"):
            # 数据来源为 URL。
            try:
                response = requests.get(url=data_file_path, timeout=30)
            except Exception as error:
                raise FileNotFoundError(
                    f"Problem while attempting to access data file URL '{data_file_path}':  {error}"
                )

            if response.status_code != 200:
                raise FileNotFoundError(f"Bad response while accessing "
                                        f"data file URL '{data_file_path}'."
                                        )
            try:
                site_data = response.json()
            except Exception as error:
                raise ValueError(
                    f"Problem parsing json contents at '{data_file_path}':  {error}."
                )

        else:
            # 数据来源为本地文件。
            try:
                with open(data_file_path, "r", encoding="utf-8") as file:
                    try:
                        site_data = json.load(file)
                    except Exception as error:
                        raise ValueError(
                            f"Problem parsing json contents at '{data_file_path}':  {error}."
                        )

            except FileNotFoundError:
                raise FileNotFoundError(f"Problem while attempting to access "
                                        f"data file '{data_file_path}'."
                                        )

        site_data.pop('$schema', None)

        if honor_exclusions:
            try:
                response = requests.get(url=EXCLUSIONS_URL, timeout=10)
                if response.status_code == 200:
                    exclusions = response.text.splitlines()
                    exclusions = [exclusion.strip() for exclusion in exclusions]

                    for site in do_not_exclude:
                        if site in exclusions:
                            exclusions.remove(site)

                    for exclusion in exclusions:
                        try:
                            site_data.pop(exclusion, None)
                        except KeyError:
                            pass

            except Exception:
                # 排除列表加载失败时，继续执行，但不应用排除规则。
                print("Warning: Could not load exclusions, continuing without them.")
                honor_exclusions = False

        self.sites = {}

        # 将 JSON 文件中的所有站点信息加入内部站点列表。
        for site_name in site_data:
            try:

                self.sites[site_name] = \
                    SiteInformation(site_name,
                                    site_data[site_name]["urlMain"],
                                    site_data[site_name]["url"],
                                    site_data[site_name]["username_claimed"],
                                    site_data[site_name],
                                    site_data[site_name].get("isNSFW",False)

                                    )
            except KeyError as error:
                raise ValueError(
                    f"Problem parsing json contents at '{data_file_path}':  Missing attribute {error}."
                )
            except TypeError:
                print(f"Encountered TypeError parsing json contents for target '{site_name}' at {data_file_path}\nSkipping target.\n")


    def remove_nsfw_sites(self, do_not_remove: list = []):
        """移除标记了 isNSFW 的站点，保留明确指定的例外。

        参数：
        self                   -- 当前对象。
        do_not_remove          -- 需要保留的站点名称列表，比较时忽略大小写。

        返回值：
        无。
        """
        sites = {}
        do_not_remove = [site.casefold() for site in do_not_remove]
        for site in self.sites:
            if self.sites[site].is_nsfw and site.casefold() not in do_not_remove:
                continue
            sites[site] = self.sites[site]
        self.sites =  sites

    def site_name_list(self):
        """返回按名称排序的站点名称字符串列表。"""

        return sorted([site.name for site in self], key=str.lower)

    def __iter__(self):
        """迭代站点集合，依次返回各站点的信息对象。"""

        for site_name in self.sites:
            yield self.sites[site_name]

    def __len__(self):
        """返回站点集合中的站点数量。"""
        return len(self.sites)
