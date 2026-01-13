# 项目文件结构说明

本项目的文件树结构如下所示，主要包含了爬虫、数据处理、自动发布以及相关辅助工具脚本。

```
project_root/
├── data/                  # 原始数据存储目录 (爬虫抓取的初始数据)
│   ├── image/             # 图片文件夹 (按笔记ID分类存储)
│   └── annotations.json   # 原始数据标注信息文件
│
├── data_final/            # 最终数据集目录 (经过筛选和处理后的数据)
│   ├── image/             # 图片文件夹
│   └── annotations.json   # 最终数据的标注信息文件
│
├── docs/                  # 项目文档目录
│   ├── problem.md         # 问题记录与分析
│   ├── todo.md            # 待办事项列表
│   ├── 发布设计思路.md     # 自动发布功能的设计文档
│   ├── 自动发布问题与解决方案.md # 发布过程中的问题与解决
│   ├── 设计思路.md         # 整体项目设计思路
│   ├── 问题与解决方案.md    # 通用问题与解决方案记录
│   └── project_structure.md # 本文件：项目文件结构说明
│
├── test/                  # 测试与实验性代码目录
│   ├── baidu_crawler.py   # 百度图片爬虫测试脚本
│   ├── crawler.py         # 通用爬虫测试脚本
│   ├── merge.py           # 代码/数据合并测试脚本
│   ├── processor.py       # 数据处理流程测试
│   ├── publisher.py       # 发布功能测试脚本
│   └── xhs_test.py        # 小红书相关功能测试
│
├── add_to_final.py        # 数据迁移工具：将选定的 data 数据添加到 data_final
├── archive_data.py        # 数据归档工具：将 data 目录下的数据归档到 data_past (按时间戳)
├── filter_data_final.py   # 数据过滤工具：对 data_final 中的数据进行清洗 (如去除无效数据)
├── get_cookies.py         # Cookie 获取工具：启动浏览器手动登录以获取小红书 Cookies
├── reference.py           # 参考代码：包含 Selenium 等相关实现的参考片段
├── requirements.txt       # 项目依赖清单
├── .env                   # 环境变量配置文件 (API Key 等)
├── cookies.json           # 小红书登录 Cookie 文件
├── .gitignore             # Git 忽略文件配置
├── xhs_crawler.py         # [核心] 小红书数据采集爬虫主程序
├── xhs_publisher.py       # [核心] 小红书自动发布主程序
└── xhs_sign_utils.py      # [核心] 小红书 API 签名算法工具模块
```

## 核心模块说明

1.  **数据采集 (`xhs_crawler.py`)**:
    *   负责从小红书或其他来源抓取笔记数据 (图片、标题、文案等)。
    *   依赖 `xhs_sign_utils.py` 进行 API 签名。
    *   抓取的数据默认存储在 `data/` 目录下。

2.  **数据处理与管理**:
    *   `add_to_final.py`: 用于挑选高质量数据，将其从 `data/` 移动或复制到 `data_final/`，作为待发布库。
    *   `filter_data_final.py`: 对 `data_final/` 中的数据进行二次清洗，确保发布质量。
    *   `archive_data.py`: 用于清理 `data/` 目录，将旧数据归档，保持工作区整洁。

3.  **自动发布 (`xhs_publisher.py`)**:
    *   读取 `data_final/` 中的数据。
    *   调用 AI 接口 (如需要) 生成或优化文案。
    *   使用 Playwright 或 Selenium 模拟浏览器操作，自动发布笔记到小红书。

4.  **辅助工具**:
    *   `get_cookies.py`: 解决账号登录问题，获取必要的 Cookie 凭证。
    *   `test/` 目录下的脚本用于开发过程中的单元测试和功能验证。
