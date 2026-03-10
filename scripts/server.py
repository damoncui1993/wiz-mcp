"""MCP Server 主实现"""
import sys
import json
import base64
import re
import os
from pathlib import Path
from typing import Any, Dict, Optional

from scripts.config import Config, get_config
from scripts.wiz_open_api import WizOpenApi
from scripts.note_parser_factory import NoteParserFactory
from scripts.note import Note
from scripts.logging import get_logger

logger = get_logger()


class WizMCPServer:
    """为知笔记 MCP Server"""

    def __init__(self):
        self.config: Optional[Config] = None
        self.api: Optional[WizOpenApi] = None

    def initialize(self, config: Config):
        """初始化 Server"""
        self.config = config
        self.api = WizOpenApi(config)
        logger.info("WizMCP Server 初始化完成")

    def handle_request(self, request: dict) -> dict:
        """处理 JSON-RPC 请求"""
        method = request.get("method")
        request_id = request.get("id")

        if method == "initialize":
            return self._handle_initialize(request_id)
        elif method == "notifications/initialized":
            return self._handle_notifications_initialized(request_id)
        elif method == "tools/list":
            return self._handle_tools_list(request_id)
        elif method == "tools/call":
            return self._handle_tools_call(request_id, request.get("params", {}))
        else:
            return self._error_response(request_id, -32601, f"Method not found: {method}")

    def _handle_initialize(self, request_id: Any) -> dict:
        """处理 initialize 请求"""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "wiz-mcp",
                    "version": "1.0.0"
                }
            }
        }

    def _handle_notifications_initialized(self, request_id: Any) -> dict:
        """处理 notifications/initialized 请求"""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {}
        }

    def _handle_tools_list(self, request_id: Any) -> dict:
        """处理 tools/list 请求"""
        tools = [
            {
                "name": "wiz_list_notes",
                "description": "列出笔记元数据",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "start_version": {
                            "type": "integer",
                            "description": "起始版本号，默认0"
                        },
                        "count": {
                            "type": "integer",
                            "description": "返回数量，默认50，范围1-200",
                            "default": 50
                        }
                    }
                }
            },
            {
                "name": "wiz_search_notes",
                "description": "通过扫描元数据搜索笔记",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索关键词（必填）"
                        },
                        "start_version": {
                            "type": "integer",
                            "description": "起始版本号，默认0"
                        },
                        "page_size": {
                            "type": "integer",
                            "description": "每页大小，默认100，范围1-200",
                            "default": 100
                        },
                        "max_pages": {
                            "type": "integer",
                            "description": "最大页数，默认10，范围1-200",
                            "default": 10
                        },
                        "fields": {
                            "type": "array",
                            "items": {"type": "string", "enum": ["title", "category", "url", "type"]},
                            "description": "搜索字段，默认['title', 'category']",
                            "default": ["title", "category"]
                        },
                        "case_sensitive": {
                            "type": "boolean",
                            "description": "是否区分大小写，默认false",
                            "default": False
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "wiz_get_note",
                "description": "读取笔记正文（支持下载图片/附件到本地）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "doc_guid": {
                            "type": "string",
                            "description": "笔记GUID（必填）"
                        },
                        "format": {
                            "type": "string",
                            "enum": ["markdown", "html", "both"],
                            "description": "返回格式，默认markdown",
                            "default": "markdown"
                        },
                        "include_info": {
                            "type": "boolean",
                            "description": "是否包含笔记信息，默认true",
                            "default": True
                        },
                        "include_resources": {
                            "type": "boolean",
                            "description": "是否下载图片/附件到本地，默认true",
                            "default": True
                        }
                    },
                    "required": ["doc_guid"]
                }
            },
            {
                "name": "wiz_list_attachments",
                "description": "列出笔记附件",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "doc_guid": {
                            "type": "string",
                            "description": "笔记GUID（必填）"
                        },
                        "note_type": {
                            "type": "string",
                            "description": "笔记类型（可选，用于协作笔记回退）"
                        }
                    },
                    "required": ["doc_guid"]
                }
            },
            {
                "name": "wiz_download_attachment",
                "description": "下载附件",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": ["normal", "collaboration_resource"],
                            "description": "附件类型，默认normal",
                            "default": "normal"
                        },
                        "doc_guid": {
                            "type": "string",
                            "description": "笔记GUID（必填）"
                        },
                        "att_guid": {
                            "type": "string",
                            "description": "普通附件GUID"
                        },
                        "name": {
                            "type": "string",
                            "description": "附件名称（仅回显/清理换行）"
                        },
                        "src": {
                            "type": "string",
                            "description": "协作资源标识"
                        }
                    },
                    "required": ["doc_guid"]
                }
            },
            {
                "name": "wiz_create_note",
                "description": "创建笔记（支持从URL导入Markdown）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "笔记标题"
                        },
                        "content": {
                            "type": "string",
                            "description": "笔记内容（Markdown格式）"
                        },
                        "url": {
                            "type": "string",
                            "description": "URL地址，将自动抓取并转换为Markdown"
                        },
                        "category": {
                            "type": "string",
                            "description": "分类路径，默认 /My Notes/",
                            "default": "/My Notes/"
                        },
                        "tags": {
                            "type": "string",
                            "description": "标签，逗号分隔"
                        }
                    }
                }
            }
        ]

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": tools}
        }

    def _handle_tools_call(self, request_id: Any, params: dict) -> dict:
        """处理 tools/call 请求"""
        tool_name = params.get("name")
        tool_args = params.get("arguments", {})

        try:
            if tool_name == "wiz_list_notes":
                result = self._tool_wiz_list_notes(tool_args)
            elif tool_name == "wiz_search_notes":
                result = self._tool_wiz_search_notes(tool_args)
            elif tool_name == "wiz_get_note":
                result = self._tool_wiz_get_note(tool_args)
            elif tool_name == "wiz_list_attachments":
                result = self._tool_wiz_list_attachments(tool_args)
            elif tool_name == "wiz_download_attachment":
                result = self._tool_wiz_download_attachment(tool_args)
            elif tool_name == "wiz_create_note":
                result = self._tool_wiz_create_note(tool_args)
            else:
                return self._error_response(request_id, -32601, f"Unknown tool: {tool_name}")

            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, ensure_ascii=False)
                        }
                    ]
                }
            }

        except Exception as e:
            logger.error(f"工具执行失败: {tool_name}, error: {e}")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"error": str(e)}, ensure_ascii=False)
                        }
                    ],
                    "isError": True
                }
            }

    def _tool_wiz_list_notes(self, args: dict) -> dict:
        """wiz_list_notes 工具"""
        start_version = args.get("start_version", 0)
        count = min(max(args.get("count", 50), 1), 200)

        result = self.api.get_note_list(start_version, count)

        # API 直接返回数组或 {notes: [...], next_version: n}
        if isinstance(result, list):
            notes = result
            next_version = None
        else:
            notes = result.get("notes", []) if isinstance(result, dict) else []
            next_version = result.get("next_version") if isinstance(result, dict) else None

        return {
            "notes": notes,
            "next_version": next_version
        }

    def _tool_wiz_search_notes(self, args: dict) -> dict:
        """wiz_search_notes 工具"""
        query = args.get("query", "")
        start_version = args.get("start_version", 0)
        page_size = min(max(args.get("page_size", 100), 1), 200)
        max_pages = min(max(args.get("max_pages", 10), 1), 200)
        fields = args.get("fields", ["title", "category"])
        case_sensitive = args.get("case_sensitive", False)

        if not query:
            raise ValueError("query 是必填参数")

        all_matches = []
        current_version = start_version
        pages_scanned = 0

        while pages_scanned < max_pages:
            result = self.api.get_note_list(current_version, page_size)

            # 处理 API 返回数组或字典的情况
            if isinstance(result, list):
                notes = result
            else:
                notes = result.get("notes", []) if isinstance(result, dict) else []

            if not notes:
                break

            for note in notes:
                matched = False
                note_text = ""

                if "title" in fields:
                    note_text += str(note.get("title", "")) + " "
                if "category" in fields:
                    note_text += str(note.get("category", "")) + " "
                if "url" in fields:
                    note_text += str(note.get("url", "")) + " "
                if "type" in fields:
                    note_text += str(note.get("type", "")) + " "

                if case_sensitive:
                    matched = query in note_text
                else:
                    matched = query.lower() in note_text.lower()

                if matched:
                    all_matches.append(note)

            # 处理 API 返回数组或字典的情况
            if isinstance(result, list):
                next_version = None
            else:
                next_version = result.get("next_version") if isinstance(result, dict) else None

            if next_version is None or next_version == 0:
                break

            current_version = next_version
            pages_scanned += 1

        return {
            "matches": all_matches,
            "next_version": current_version if all_matches else None
        }

    def _tool_wiz_get_note(self, args: dict) -> dict:
        """wiz_get_note 工具"""
        doc_guid = args.get("doc_guid")
        format_type = args.get("format", "markdown")
        include_info = args.get("include_info", True)
        include_resources = args.get("include_resources", True)

        if not doc_guid:
            raise ValueError("doc_guid 是必填参数")

        # 先获取笔记详情判断类型
        detail = self.api.get_note_detail(doc_guid)
        info = detail.get("info", {})
        note_type = info.get("type", "")
        title = info.get("title", "无标题")

        result = {
            "doc_guid": doc_guid,
            "type": note_type
        }

        if include_info:
            result["info"] = info

        # 获取原始内容
        is_collab = Note.is_collaboration_note(note_type)

        if is_collab:
            # 协作笔记
            editor_token = self.api.get_collaboration_token(doc_guid)
            collab_json = self.api.get_collaboration_content(editor_token, doc_guid)

            origin_content = collab_json

            if format_type in ("markdown", "both"):
                from scripts.collaboration_note_parser import CollaborationNoteParser
                parser = CollaborationNoteParser()
                result["markdown"] = parser.parse_content(collab_json)

            if format_type == "html":
                # 协作笔记返回 JSON 原文
                result["html"] = collab_json
            elif format_type == "both":
                result["html"] = collab_json

            # 下载协作笔记的资源
            if include_resources:
                resources_info = self._download_collaboration_resources(doc_guid, title)
                result["resources"] = resources_info["resources"]
                result["markdown"] = self._replace_resource_paths(
                    result.get("markdown", ""),
                    resources_info["replace_map"]
                )
        else:
            # 普通笔记
            origin_content = self.api.get_note_content(doc_guid)

            if format_type in ("markdown", "both"):
                parser = NoteParserFactory.create_parser(note_type)
                result["markdown"] = parser.parse_content(origin_content)

            if format_type in ("html", "both"):
                result["html"] = origin_content

            # 下载普通笔记的资源
            if include_resources:
                resources_info = self._download_note_resources(doc_guid, title)
                result["resources"] = resources_info["resources"]
                result["markdown"] = self._replace_resource_paths(
                    result.get("markdown", ""),
                    resources_info["replace_map"]
                )

        return result

    def _download_note_resources(self, doc_guid: str, title: str) -> dict:
        """下载普通笔记的资源（图片/附件）"""
        resources = self.api.get_note_resources(doc_guid)

        output_dir = Path(__file__).parent.parent / "output" / "notes" / doc_guid
        images_dir = output_dir / "images"
        attachments_dir = output_dir / "attachments"

        images_dir.mkdir(parents=True, exist_ok=True)
        attachments_dir.mkdir(parents=True, exist_ok=True)

        downloaded_resources = []
        replace_map = {}

        for res in resources:
            name = res.get("name", "")
            url = res.get("url", "")
            res_type = res.get("type", "attachment")

            if not name or not url:
                continue

            try:
                # 判断是图片还是附件
                ext = name.lower().split('.')[-1] if '.' in name else ''
                image_exts = ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp']

                if ext in image_exts:
                    # 图片
                    save_dir = images_dir
                    save_path = save_dir / name
                    rel_path = f"output/notes/{doc_guid}/images/{name}"
                else:
                    # 附件
                    save_dir = attachments_dir
                    save_path = save_dir / name
                    rel_path = f"output/notes/{doc_guid}/attachments/{name}"

                # 下载并保存
                content = self.api.download_resource(url)
                with open(save_path, "wb") as f:
                    f.write(content)

                downloaded_resources.append({
                    "name": name,
                    "path": str(save_path),
                    "relative_path": rel_path,
                    "type": "image" if ext in image_exts else "attachment"
                })

                # 记录替换映射（原路径 -> 新路径）
                replace_map[name] = rel_path
                logger.info(f"下载资源: {name} -> {rel_path}")

            except Exception as e:
                logger.warning(f"下载资源失败: {name}, error: {e}")

        return {
            "resources": downloaded_resources,
            "replace_map": replace_map
        }

    def _download_collaboration_resources(self, doc_guid: str, title: str) -> dict:
        """下载协作笔记的资源（图片/drawio等）"""
        # 获取协作笔记的 JSON 内容，提取 embed 信息
        editor_token = self.api.get_collaboration_token(doc_guid)
        collab_json = self.api.get_collaboration_content(editor_token, doc_guid)

        import json
        try:
            data = json.loads(collab_json)
            blocks = data.get("data", {}).get("data", {}).get("blocks", [])
        except:
            blocks = []

        output_dir = Path(__file__).parent.parent / "output" / "notes" / doc_guid
        images_dir = output_dir / "images"
        attachments_dir = output_dir / "attachments"

        images_dir.mkdir(parents=True, exist_ok=True)
        attachments_dir.mkdir(parents=True, exist_ok=True)

        downloaded_resources = []
        replace_map = {}

        for block in blocks:
            if block.get("type") != "embed":
                continue

            embed_type = block.get("embedType", "")
            embed_data = block.get("embedData", {})

            if embed_type == "image":
                src = embed_data.get("src", "")
                file_name = embed_data.get("fileName", src)

                if not src:
                    continue

                try:
                    content = self.api.get_collaboration_image(doc_guid, src)
                    save_path = images_dir / file_name
                    with open(save_path, "wb") as f:
                        f.write(content)

                    rel_path = f"output/notes/{doc_guid}/images/{file_name}"
                    downloaded_resources.append({
                        "name": file_name,
                        "path": str(save_path),
                        "relative_path": rel_path,
                        "type": "image"
                    })

                    replace_map[src] = rel_path
                    logger.info(f"下载协作图片: {file_name}")

                except Exception as e:
                    logger.warning(f"下载协作图片失败: {src}, error: {e}")

            elif embed_type in ("office", "drawio"):
                src = embed_data.get("src", "")
                file_name = embed_data.get("fileName", src)

                if not src:
                    continue

                try:
                    content = self.api.download_collaboration_resource(editor_token, doc_guid, src)
                    save_path = attachments_dir / file_name
                    with open(save_path, "wb") as f:
                        f.write(content)

                    rel_path = f"output/notes/{doc_guid}/attachments/{file_name}"
                    downloaded_resources.append({
                        "name": file_name,
                        "path": str(save_path),
                        "relative_path": rel_path,
                        "type": embed_type
                    })

                    replace_map[src] = rel_path
                    logger.info(f"下载协作附件: {file_name}")

                except Exception as e:
                    logger.warning(f"下载协作附件失败: {src}, error: {e}")

        return {
            "resources": downloaded_resources,
            "replace_map": replace_map
        }

    def _replace_resource_paths(self, markdown: str, replace_map: dict) -> str:
        """替换 Markdown 中的资源路径"""
        if not replace_map:
            return markdown

        for old_path, new_path in replace_map.items():
            # 替换各种格式的引用
            # ![name](old_path) -> ![name](new_path)
            # [name](wiz-collab-attachment://old_path) -> [name](new_path)
            # ![name](wiz-collab-attachment://old_path) -> ![name](new_path)

            # 处理 wiz-collab-attachment:// 协议
            markdown = markdown.replace(f"](wiz-collab-attachment://{old_path})", f"]({new_path})")
            markdown = markdown.replace(f"]({old_path})", f"]({new_path})")

        return markdown

    def _tool_wiz_list_attachments(self, args: dict) -> dict:
        """wiz_list_attachments 工具"""
        doc_guid = args.get("doc_guid")
        note_type = args.get("note_type", "")

        if not doc_guid:
            raise ValueError("doc_guid 是必填参数")

        result = {
            "doc_guid": doc_guid,
            "note_type": note_type
        }

        try:
            attachments = self.api.get_note_attachments(doc_guid)

            if attachments:
                result["attachments"] = attachments
            elif note_type == "collaboration" and not attachments:
                # 协作笔记回退解析
                collab_result = self._parse_collaboration_attachments(doc_guid)
                result["collaboration"] = collab_result
            elif not attachments:
                # 非协作笔记没有附件
                result["attachments"] = []

        except Exception as e:
            if note_type == "collaboration":
                # 协作笔记回退解析
                collab_result = self._parse_collaboration_attachments(doc_guid)
                result["collaboration"] = collab_result
            else:
                raise Exception(f"获取附件列表失败: {e}")

        return result

    def _parse_collaboration_attachments(self, doc_guid: str) -> dict:
        """解析协作笔记的附件"""
        editor_token = self.api.get_collaboration_token(doc_guid)
        collab_json = self.api.get_collaboration_content(editor_token, doc_guid)

        from scripts.collaboration_note_parser import CollaborationNoteParser
        parser = CollaborationNoteParser()
        markdown = parser.parse_content(collab_json)

        # 解析 embeds
        json_data = json.loads(collab_json)
        embeds = []
        blocks = json_data.get("data", {}).get("data", {}).get("blocks", [])
        for block in blocks:
            if block.get("type") == "embed":
                embed_type = block.get("embedType", "")
                embed_data = block.get("embedData", {})
                embeds.append({
                    "embedType": embed_type,
                    "src": embed_data.get("src", ""),
                    "fileName": embed_data.get("fileName", "")
                })

        # 从 markdown 中提取 wiz-collab-attachment:// 链接（排除图片）
        attachment_names = []
        pattern = r'\[([^\]]+)\]\(wiz-collab-attachment://([^)]+)\)'
        for match in re.finditer(pattern, markdown):
            src = match.group(2)
            if src not in attachment_names:
                attachment_names.append(src)

        return {
            "attachment_names": attachment_names,
            "embeds": embeds
        }

    def _tool_wiz_download_attachment(self, args: dict) -> dict:
        """wiz_download_attachment 工具"""
        kind = args.get("kind", "normal")
        doc_guid = args.get("doc_guid")
        att_guid = args.get("att_guid")
        name = args.get("name", "")
        src = args.get("src")

        if not doc_guid:
            raise ValueError("doc_guid 是必填参数")

        # 清理 name 中的换行
        if name:
            name = name.replace("\n", " ").replace("\r", "")

        result = {
            "doc_guid": doc_guid
        }

        if kind == "normal":
            if not att_guid:
                raise ValueError("kind=normal 时，att_guid 是必填参数")

            binary_content = self.api.download_attachment(doc_guid, att_guid)
            result["att_guid"] = att_guid
            result["name"] = name
            result["kind"] = "normal"

        else:
            # collaboration_resource
            if not src:
                raise ValueError("kind=collaboration_resource 时，src 是必填参数")

            editor_token = self.api.get_collaboration_token(doc_guid)
            binary_content = self.api.download_collaboration_resource(editor_token, doc_guid, src)
            result["src"] = src
            result["name"] = name
            result["kind"] = "collaboration_resource"

        # 保存到 output/attach 目录
        if name:
            save_dir = Path(__file__).parent.parent / "output" / "attach"
            save_dir.mkdir(parents=True, exist_ok=True)
            file_path = save_dir / name
            with open(file_path, "wb") as f:
                f.write(binary_content)
            result["saved_path"] = str(file_path)

        # 转换为 base64
        result["base64"] = base64.b64encode(binary_content).decode("utf-8")

        return result

    def _tool_wiz_create_note(self, args: dict) -> dict:
        """wiz_create_note 工具 - 创建笔记"""
        title = args.get("title", "")
        content = args.get("content", "")
        url = args.get("url", "")
        category = args.get("category", "/My Notes/")
        tags = args.get("tags", "")

        # 如果提供了 URL，则抓取网页内容
        if url:
            import trafilatura
            logger.info(f"正在抓取 URL: {url}")
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                markdown_content = trafilatura.extract(downloaded, output_format="markdown")
                if not title:
                    # 尝试从网页中提取标题
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(downloaded, 'html.parser')
                    title = soup.title.string if soup.title else url
                content = markdown_content or ""
                logger.info(f"成功抓取 URL，内容长度: {len(content)}")
            else:
                raise Exception(f"无法抓取 URL: {url}")

        if not content:
            raise Exception("content 或 url 是必填参数")

        if not title:
            title = "无标题"

        # 将 Markdown 转换为 HTML
        import markdown
        html_body = markdown.markdown(content, extensions=['extra', 'meta'])

        # 构建为知笔记的 HTML 格式
        html = f"""<!DOCTYPE html>
<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<style id="wiz_custom_css">html, body {{font-size: 12pt;}}body {{font-family: Helvetica, "Hiragino Sans GB", "微软雅黑", "Microsoft YaHei UI", SimSun, SimHei, arial, sans-serif;line-height: 1.6;margin: 0 auto;padding: 20px 16px;padding: 1.25rem 1rem;}}h1, h2, h3, h4, h5, h6 {{margin:20px 0 10px;margin:1.25rem 0 0.625rem;padding: 0;font-weight: bold;}}h1 {{font-size:20pt;font-size:1.67rem;}}h2 {{font-size:18pt;font-size:1.5rem;}}h3 {{font-size:15pt;font-size:1.25rem;}}h4 {{font-size:14pt;font-size:1.17rem;}}h5 {{font-size:12pt;font-size:1rem;}}h6 {{font-size:12pt;font-size:1rem;color: #777777;margin: 1rem 0;}}div, p, ul, ol, dl, li {{margin:0;}}blockquote, table, pre, code {{margin:8px 0;}}ul, ol {{padding-left:32px;padding-left:2rem;}}blockquote {{padding:0 12px;}}blockquote > :first-child {{margin-top:0;}}blockquote > :last-child {{margin-bottom:0;}}img {{border:0;max-width:100%;height:auto !important;margin:2px 0;}}table {{border-collapse:collapse;border:1px solid #bbbbbb;}}td, th {{padding:4px 8px;border-collapse:collapse;border:1px solid #bbbbbb;height:28px;word-break:break-all;box-sizing: border-box;}}</style>
</head>
<body>
{html_body}
</body>
</html>"""

        # 创建笔记
        result_data = self.api.create_note(title, html, category, tags)

        # 返回结果
        return {
            "title": title,
            "category": category,
            "tags": tags,
            "url": url if url else None,
            "doc_guid": result_data.get("result", {}).get("docGuid", ""),
            "message": "笔记创建成功"
        }

    def _error_response(self, request_id: Any, code: int, message: str) -> dict:
        """返回错误响应"""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message
            }
        }


def main():
    """主入口"""
    try:
        config = get_config()
        server = WizMCPServer()
        server.initialize(config)

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
                response = server.handle_request(request)
                print(json.dumps(response, ensure_ascii=False), file=sys.stdout)
                sys.stdout.flush()
            except json.JSONDecodeError:
                # 跳过非 JSON 行
                continue
            except Exception as e:
                logger.error(f"处理请求失败: {e}")
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32603,
                        "message": f"Internal error: {e}"
                    }
                }
                print(json.dumps(error_response, ensure_ascii=False), file=sys.stdout)
                sys.stdout.flush()

    except Exception as e:
        logger.error(f"Server 启动失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
