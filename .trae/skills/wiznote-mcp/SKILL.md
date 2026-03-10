# WizNote MCP Skill

## 概述

本 Skill 用于通过 MCP 协议与为知笔记服务进行交互，实现笔记查询、读取、创建和附件下载等功能。

## 前置要求

1. 安装依赖：
   ```bash
   cd wiz-mcp
   python3.12 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt --break-system-packages
   ```

2. 配置 `.env` 文件（参考 `.env.example`）

## 可用工具

### 1. wiz_list_notes

列出笔记元数据

**参数：**
- `start_version` (可选): 起始版本号，默认 0
- `count` (可选): 返回数量，默认 50，范围 1-200

**返回：**
```json
{
  "notes": [...],
  "next_version": 123
}
```

**示例：**
```
列出最近 10 条笔记
```

### 2. wiz_search_notes

通过扫描元数据搜索笔记

**参数：**
- `query` (必填): 搜索关键词
- `start_version` (可选): 起始版本号
- `page_size` (可选): 每页大小，默认 100
- `max_pages` (可选): 最大页数，默认 10
- `fields` (可选): 搜索字段，默认 ["title", "category"]
- `case_sensitive` (可选): 是否区分大小写，默认 false

**示例：**
```
搜索包含 "Python" 的笔记
```

### 3. wiz_get_note

读取笔记正文（自动下载图片/附件）

**参数：**
- `doc_guid` (必填): 笔记 GUID
- `format` (可选): 返回格式，支持 "markdown"(默认)、"html"、"both"
- `include_info` (可选): 是否包含笔记信息，默认 true
- `include_resources` (可选): 是否下载图片/附件到本地，默认 **true**

**返回：**
```json
{
  "markdown": "...",
  "resources": [
    {"name": "img.png", "path": "output/notes/xxx/images/img.png", "type": "image"},
    {"name": "file.pdf", "path": "output/notes/xxx/attachments/file.pdf", "type": "attachment"}
  ]
}
```

**示例：**
```
读取 doc_guid 为 xxx 的笔记内容
```

### 4. wiz_create_note

创建笔记（支持从 URL 导入 Markdown）

**参数：**
- `title` (可选): 笔记标题
- `content` (可选): 笔记内容（Markdown 格式）
- `url` (可选): URL 地址，将自动抓取并转换为 Markdown
- `category` (可选): 分类路径，默认 "/My Notes/"
- `tags` (可选): 标签，逗号分隔

**注意：** `content` 和 `url` 至少提供一个

**示例：**
```
从 URL https://example.com/article 创建笔记到为知笔记
```

```
创建新笔记，标题为 "我的笔记"，内容为 Markdown 格式
```

### 5. wiz_list_attachments

列出笔记附件

**参数：**
- `doc_guid` (必填): 笔记 GUID
- `note_type` (可选): 笔记类型，用于协作笔记回退

**示例：**
```
列出笔记 xxx 的附件
```

### 6. wiz_download_attachment

下载附件

**参数：**
- `kind` (可选): 附件类型，"normal"(默认) 或 "collaboration_resource"
- `doc_guid` (必填): 笔记 GUID
- `att_guid` (可选): 普通附件 GUID
- `name` (可选): 附件名称
- `src` (可选): 协作资源标识

**返回：**
```json
{
  "doc_guid": "xxx",
  "att_guid": "xxx",
  "name": "文件.pdf",
  "saved_path": "output/attach/文件.pdf",
  "base64": "..."
}
```

**示例：**
```
下载笔记 xxx 的附件 yyy
```

## 使用场景

### 场景 1：从网页创建笔记

当用户提供一个 URL（如博客文章、CSDN 等），可以将该网页的内容抓取并保存为为知笔记：

```
请将 https://blog.csdn.net/xxx/article/details/xxx 创建为知笔记
```

### 场景 2：查看笔记内容

通过笔记 GUID 查看笔记的 Markdown 内容：

```
请读取为知笔记中标题包含 "Python" 的笔记内容
```

### 场景 3：下载笔记附件

下载笔记中的 PDF、图片等附件：

```
下载为知笔记 xxx 的附件
```

### 场景 4：搜索笔记

搜索特定关键词的笔记：

```
搜索为知笔记中包含 "项目" 的笔记
```

## 注意事项

1. 所有日志输出到 stderr，不会污染 stdout（MCP JSON-RPC 输出）
2. 密码和 token 不会输出到日志
3. 协作笔记通过 WebSocket 获取内容
4. 附件下载返回 Base64 编码，同时自动保存到 `output/attach` 目录
5. URL 抓取功能使用 trafilatura 库，支持大多数主流网站
