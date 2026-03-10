你是资深 Python 工程师与 AI 工具协议专家。请从零实现一个独立项目 “wiz-mcp”，其功能与行为需尽可能 100% 对齐参考实现（一个可运行的 Python MCP STDIO Server，用于为知笔记查询/读取/附件下载）。目标平台：Python 3.12，本地运行 Trae/OpenClaw。

【参考实现（行为对齐目标）】
- 本地参考实现的行为目标与目录结构：wiz-mcp
- 协作笔记 WS 获取内容：参考 awaken233/wiz2obsidian 的 3 次 hs + 1 次 f + 1 次 s 的握手取数逻辑
  https://github.com/awaken233/wiz2obsidian
- WebSocket 客户端库与调用方式：websocket-client create_connection（短连接收发）
  https://github.com/websocket-client/websocket-client

【V1范围（只读）】
- 列出笔记元数据
- 通过扫描元数据实现“搜索”
- 读取笔记正文（普通HTML/Lite/协作）
- 列出附件（普通接口 / 协作回退解析）
- 下载附件（二进制 base64 返回）

【关键配置：必须只用一个统一 base】
- 必须支持 .env（项目根目录 .env）
- 仅允许下列环境变量（不要再兼容 WIZ_AS_URL/WIZ_KB_SERVER）：
  - WIZ_USER_ID（必填）
  - WIZ_PASSWORD（必填）
  - WIZ_GROUP_NAME（可选）
  - WIZ_BASE_URL（必填；同时作为 /as、/ks、/editor 的 base，例如 http://127.0.0.1:5688）
  - WIZ_KB_GUID（可选；如果填成 URL 则忽略/置空）
- Config.load() 规则：
  - 若项目根目录存在 .env，则 load_dotenv
  - 校验 WIZ_USER_ID/WIZ_PASSWORD/WIZ_BASE_URL 必填
  - as_url = WIZ_BASE_URL，kb_server = WIZ_BASE_URL
  - kb_guid 若包含 “://” 视为误填，置空

【MCP协议要求（STDIO / JSON-RPC）】
必须实现 4 个 JSON-RPC method：
1) initialize
2) notifications/initialized
3) tools/list
4) tools/call

输出约束：
- stdout 只允许输出 JSON-RPC 响应（每行一个 JSON）
- 日志必须输出到 stderr（不能污染 stdout）
- tools/call 的 result 返回必须为 MCP CallToolResult 风格：
  { "content":[{"type":"text","text":"..."}], "isError"?: boolean }
- tool 业务错误不要走 JSON-RPC error，使用 isError=true + 文本说明；协议错误才走 JSON-RPC error
- 不允许把密码/token/base64 打到日志或 stdout

【必须提供的 5 个 MCP tools（名字固定，schema 固定）】
1) wiz_list_notes
   - input: {start_version?:int=0, count?:int=50(1..200)}
   - output(text JSON): {notes:[noteMeta...], next_version:int|null}

2) wiz_search_notes
   - input: {
       query:string(必填),
       start_version?:int=0,
       page_size?:int=100(1..200),
       max_pages?:int=10(1..200),
       fields?:["title"|"category"|"url"|"type"] 默认 ["title","category"],
       case_sensitive?:bool=false
     }
   - 实现方式：用 wiz_list_notes 扫描元数据并在本地过滤（不依赖服务端 search）
   - output(text JSON): {matches:[noteMeta...], next_version:int|null}

3) wiz_get_note
   - input: {doc_guid:string(必填), format?: "markdown"|"html"|"both"=markdown, include_info?:bool=true}
   - 行为：
     - 先用 /ks/note/download/... 拿到 info.type 判断是否 collaboration
     - collaboration：
       - POST /ks/note/{kbGuid}/{docGuid}/tokens (X-Wiz-Token) -> editorToken
       - ws/wss://{domain}/editor/{kbGuid}/{docGuid} 取协作 JSON（详见下方 WS 细则）
       - origin_content=协作 JSON 字符串
       - 用 CollaborationNoteParser 把 JSON 转 markdown
     - 非 collaboration：
       - origin_content = download 返回的 html 字符串
       - HtmlNoteParser 用 html2text 转 markdown
     - format=html 时返回 origin_content（协作就是 JSON 原文不返回；对齐参考实现：协作仅支持 markdown/both 时 markdown，html 仅对普通笔记有意义）
   - output(text JSON): {doc_guid,type,info?,markdown?,html?}

4) wiz_list_attachments
   - input: {doc_guid:string(必填), note_type?:string}
   - 行为：
     - 先尝试普通附件接口：GET /ks/note/attachments/{kbGuid}/{docGuid}
     - 若返回 attachments 非空：直接返回 {attachments:[...]}
     - 若 note_type == "collaboration" 且 attachments 为空或接口失败：必须回退：
       - 获取 editorToken + 协作 JSON（同 get_note）
       - 解析协作 JSON 的 blocks，抽取 embedType/embedData：
         - 输出 embeds: [{embedType, src, fileName?}]
       - 同时把协作 JSON 先转 markdown（CollaborationNoteParser），再从 markdown 中提取：
         [xxx](wiz-collab-attachment://SRC) 这种链接的 SRC（排除图片语法 ![]()），输出 attachment_names:[src...]
       - 最终返回 {collaboration:{attachment_names:[...], embeds:[...]}}
     - 若非 collaboration 且接口失败：返回 isError=true
   - output(text JSON): {doc_guid,note_type,attachments? , collaboration?}

5) wiz_download_attachment
   - input: {
       kind?: "normal"|"collaboration_resource"=normal,
       doc_guid:string(必填),
       att_guid?:string,
       name?:string(仅回显/清理换行),
       src?:string
     }
   - 行为：
     - kind=normal：GET /ks/attachment/download/{kbGuid}/{docGuid}/{attGuid} 二进制下载 -> base64 返回
     - kind=collaboration_resource：
       - 必须先取 editorToken（tokens）
       - GET /editor/{kbGuid}/{docGuid}/resources/{src}
       - Header: cookie: x-live-editor-token={editorToken}
       - 二进制下载 -> base64 返回
   - output(text JSON): {doc_guid, att_guid?/src?, name?, base64}

【HTTP/WS细则（与参考实现对齐）】
- 登录：
  POST {BASE}/as/user/login (form: userId,password)
  返回 result.token/kbServer/kbGuid/userGuid
- 重要：即使配置里只有 WIZ_BASE_URL，仍要以 login 返回的 kbGuid/userGuid/token 为准
- group 切换（可选）：
  若 WIZ_GROUP_NAME 非空：GET {BASE}/as/user/groups (X-Wiz-Token) 匹配 name 后切换 kbGuid/kbServer
  注意：kbServer 也可以来自 group 返回；但最终都以 BASE 作为请求 base（对齐统一入口策略）

- WS 连接 URL：
  domain 从 urlparse(BASE).netloc 得到
  ws_url = (BASE scheme==https ? wss : ws) + "://" + domain + "/editor/{kbGuid}/{docGuid}"
  - https 用 wss 并启用 sslopt(cert_reqs=CERT_REQUIRED, ca_certs=certifi.where())
  - http 用 ws 且不传 sslopt

- WS 消息顺序（严格）：
  hs_request:
    {"a":"hs","id":null,"auth":{"appId":kbGuid,"docId":docGuid,"userId":userGuid,"permission":"w","token":editorToken}}
  f_request: {"a":"f","c":kbGuid,"d":docGuid,"v":null}
  s_request: {"a":"s","c":kbGuid,"d":docGuid,"v":null}
  send(hs); recv()
  send(hs); recv()
  send(hs); recv()
  send(f);  recv(); recv()   # 第二个 recv() 为协作 JSON 正文 origin_content
  send(s);  recv()
  close()

【解析器能力（必须按“够用版”实现，别过度扩展）】
- HtmlNoteParser：html2text.html2text + NoteFixer.fix
- LiteNoteParser：BeautifulSoup 提取 body/pre 文本 + NoteFixer.fix
- CollaborationNoteParser：实现 JSON->Markdown 的最小覆盖：
  - block.type == "text" 支持 heading(1..6)
  - block.type == "list" 支持 ordered/level/start
  - block.type == "embed" 支持 embedType:
    - image -> ![fileName](src)
    - office/drawio -> [fileName](wiz-collab-attachment://src)
    - mermaid -> ```mermaid\n...\n``` 或 fallback 成 attachment 链接
    - webpage -> [webpage](src)
  - block.type == "table"：支持 cols + children，通过 doc 内 id_map 查 cell text[]，输出 markdown 表格
  - text[] 的 attributes 支持最小转换：link、style-code、style-bold、style-italic、style-strikethrough、wiki-link

【工程结构（必须输出这些文件/路径）】
wiz-mcp/
  wiz_mcp_server.py                  # 入口：from wiz_mcp.server import main
  mcp_smoke_test.py                  # 冒烟：握手 + tools/list + call(wiz_list_notes)，跳过非 JSON 行
  requirements.txt                   # requests websocket-client python-dotenv html2text bs4 certifi (+pypdf可不强制)
  .env.example                       # 包含 WIZ_BASE_URL 示例
  .gitignore                         # 忽略 .env / __pycache__ / output
  README.md                          # 安装/配置/启动/Trae mcpServers JSON 示例
  .trae/skills/wiznote-mcp/SKILL.md  # Skill 指南
  wiz_mcp/
    __init__.py
    logging.py                       # stderr logger
    config.py
    note.py
    note_parser.py
    note_fixer.py
    html_note_parser.py
    lite_note_parser.py
    collaboration_note_parser.py
    note_parser_factory.py
    wiz_open_api.py                  # HTTP/WS 封装
    server.py                        # MCP server 主实现 + tools

【必须提供的文档内容】
- README.md 必须包含：
  - 安装：python3.12 -m pip install -r requirements.txt
  - .env 示例（WIZ_BASE_URL）
  - 启动：python3.12 wiz_mcp_server.py
  - Trae mcpServers JSON（command python3.12 + args 绝对路径 + cwd 项目根目录 + PYTHONUNBUFFERED=1）
  - 冒烟测试：python3.12 mcp_smoke_test.py

【交付方式】
- 输出完整目录树
- 给出每个文件的完整代码（不要省略）
- 关键模块写中文注释（server/config/wiz_open_api/collaboration_note_parser）
- 代码需可运行：至少 mcp_smoke_test 在配置正确时通过

自检清单（必须逐条确认）：
- 是否只用 WIZ_BASE_URL（没有 WIZ_AS_URL/WIZ_KB_SERVER 分支）？
- stdout 是否只输出 JSON-RPC？日志是否全部 stderr？
- tools/list 的 schema 与工具名是否完全一致？
- 协作 WS 是否严格 3 次 hs + f 两次 recv + s？
- list_attachments 协作场景 attachments 为空是否会回退解析 embeds 与 attachment_names？
- download_attachment 协作资源是否用 cookie x-live-editor-token 下载？