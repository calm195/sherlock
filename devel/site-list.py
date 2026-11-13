#!/usr/bin/env python
# 生成支持的站点列表并写入 sites.mdx，
# 同时按字母和数字顺序整理所有站点。
import json
import os

DATA_REL_URI: str = "sherlock_project/resources/data.json"

DEFAULT_ENCODING = "utf-8"

# 读取 data.json 文件。
with open(DATA_REL_URI, "r", encoding=DEFAULT_ENCODING) as data_file:
    data: dict = json.load(data_file)

# 移除 JSON Schema 专用字段，避免将其当作站点处理。
social_networks = data.copy()
social_networks.pop('$schema', None)

# 按字母和数字顺序排列社交网站。
social_networks = sorted(social_networks.items())

# 创建用于保存站点列表的输出目录。
os.mkdir("output")

# 将支持的站点列表写入 sites.mdx。
with open("output/sites.mdx", "w", encoding=DEFAULT_ENCODING) as site_file:
    site_file.write("---\n")
    site_file.write("title: 'List of supported sites'\n")
    site_file.write("sidebarTitle: 'Supported sites'\n")
    site_file.write("icon: 'globe'\n")
    site_file.write("description: 'Sherlock currently supports **400+** sites'\n")
    site_file.write("---\n\n")

    for social_network, info in social_networks:
        url_main = info["urlMain"]
        is_nsfw = "**(NSFW)**" if info.get("isNSFW") else ""
        site_file.write(f"1. [{social_network}]({url_main}) {is_nsfw}\n")

# 用排序后的数据覆盖 data.json 文件。
with open(DATA_REL_URI, "w", encoding=DEFAULT_ENCODING) as data_file:
    sorted_data = json.dumps(data, indent=2, sort_keys=True)
    data_file.write(sorted_data)
    data_file.write("\n")  # 写入数据后保留文件末尾的换行。

print("Finished updating supported site listing!")
