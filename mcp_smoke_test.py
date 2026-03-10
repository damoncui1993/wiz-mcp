"""MCP 冒烟测试"""
import sys
import json

from scripts.config import get_config
from scripts.wiz_open_api import WizOpenApi
from scripts.server import WizMCPServer
from scripts.logging import get_logger

logger = get_logger()


def test_handshake():
    """测试握手"""
    logger.info("=== 测试 1: 初始化 API (握手) ===")
    config = get_config()
    api = WizOpenApi(config)
    logger.info(f"登录成功: kb_guid={api.kb_guid}, user_guid={api.user_guid}")
    return api


def test_tools_list(server):
    """测试 tools/list"""
    logger.info("=== 测试 2: tools/list ===")
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list"
    }
    response = server.handle_request(request)
    tools = response.get("result", {}).get("tools", [])
    logger.info(f"获取到 {len(tools)} 个工具")
    for tool in tools:
        logger.info(f"  - {tool['name']}")
    return tools


def test_wiz_list_notes(server, api):
    """测试 wiz_list_notes"""
    logger.info("=== 测试 3: wiz_list_notes ===")
    request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "wiz_list_notes",
            "arguments": {
                "start_version": 0,
                "count": 5
            }
        }
    }
    response = server.handle_request(request)
    result_text = response.get("result", {}).get("content", [{}])[0].get("text", "{}")
    result = json.loads(result_text)

    is_error = response.get("result", {}).get("isError", False)
    if is_error:
        logger.error(f"wiz_list_notes 调用失败: {result}")
    else:
        notes = result.get("notes", [])
        logger.info(f"获取到 {len(notes)} 条笔记")
        for note in notes[:3]:
            logger.info(f"  - {note.get('title', '无标题')[:50]}")

    return result


def main():
    """主测试流程"""
    logger.info("开始 MCP 冒烟测试...")

    try:
        # 测试 1: 握手
        api = test_handshake()

        # 测试 2: 初始化 server
        from scripts.config import get_config
        config = get_config()
        server = WizMCPServer()
        server.initialize(config)

        # 测试 3: tools/list
        tools = test_tools_list(server)
        if not tools:
            logger.error("tools/list 失败")
            sys.exit(1)

        # 测试 4: wiz_list_notes
        result = test_wiz_list_notes(server, api)

        if result.get("notes"):
            logger.info("=== 冒烟测试通过 ===")
        else:
            logger.warning("=== 冒烟测试完成（无笔记数据）===")

    except Exception as e:
        logger.error(f"冒烟测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
