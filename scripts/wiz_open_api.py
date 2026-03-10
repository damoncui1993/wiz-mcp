"""为知笔记 Open API 封装 - HTTP/WS 调用"""
import json
import time
import ssl
from urllib.parse import urlparse
import requests
from websocket import create_connection

from scripts.config import Config
from scripts.logging import get_logger

logger = get_logger()


class WizOpenApi:
    """为知笔记 Open API 封装类"""

    ATTACHMENT_CONNECT_TIMEOUT_S = 10
    ATTACHMENT_READ_TIMEOUT_S = 60
    ATTACHMENT_CHUNK_SIZE = 64 * 1024

    def __init__(self, config: Config):
        self.config = config
        self.token = ''
        self.kb_server = ''
        self.kb_guid = ''
        self.user_guid = ''
        self.domain = ''

        self._auth()

    def _auth(self):
        """认证登录"""
        data = self._login()
        self.token = data['result']['token']
        self.kb_server = data['result']['kbServer']
        self.kb_guid = data['result']['kbGuid']
        self.user_guid = data['result']['userGuid']

        # 从 kb_server 提取 domain
        parsed = urlparse(self.kb_server)
        self.domain = parsed.netloc

        logger.info(f"登录成功: kb_guid={self.kb_guid}, user_guid={self.user_guid}")

        # 如果配置了 group_name，切换到对应群组
        if self.config.group_name:
            self._switch_group()

    def _login(self):
        """登录接口"""
        login_url = f'{self.config.as_url}/as/user/login'
        response = requests.post(
            login_url,
            data={'userId': self.config.user_id, 'password': self.config.password}
        )

        if response.status_code != 200:
            raise Exception(f'登录失败: HTTP状态码 {response.status_code}')

        data = response.json()
        if data.get('returnCode') != 200:
            raise Exception(f'登录失败: {data}')

        return data

    def _switch_group(self):
        """切换群组"""
        if not self.config.group_name:
            return

        group_list_url = f'{self.config.as_url}/as/user/groups'
        response = requests.get(group_list_url, headers={'X-Wiz-Token': self.token})

        if response.status_code != 200:
            raise Exception(f'获取群组列表失败: HTTP状态码 {response.status_code}')

        data = response.json()
        if data.get('returnCode') != 200:
            raise Exception(f'获取群组列表失败: {data}')

        groups = data.get('result', [])
        matching_group = None
        for group in groups:
            if group.get('name') == self.config.group_name:
                matching_group = group
                break

        if not matching_group:
            raise Exception(f'群组名称不存在: {self.config.group_name}')

        # 切换到群组的 kb
        self.kb_guid = matching_group['kbGuid']
        # kbServer 也可以从 group 获取，但最终以 BASE 作为请求 base
        self.domain = urlparse(matching_group.get('kbServer', self.kb_server)).netloc

        logger.info(f"已切换到群组: {self.config.group_name}, kb_guid={self.kb_guid}")

    def get_note_list(self, version: int = 0, count: int = 50):
        """
        获取笔记列表
        :param version: 起始版本
        :param count: 返回数量
        :return: 笔记列表数据
        """
        note_list_url = f'{self.kb_server}/ks/note/list/version/{self.kb_guid}'
        response = requests.get(
            note_list_url,
            params={'version': version, 'count': count},
            headers={'X-Wiz-Token': self.token}
        )

        if response.status_code != 200:
            raise Exception(f'获取笔记列表失败: HTTP状态码 {response.status_code}')

        data = response.json()
        if data.get('returnCode') != 200:
            raise Exception(f'获取笔记列表失败: {data}')

        return data['result']

    def search_notes(self, keyword: str, with_abstract: bool = True, with_favor: bool = False):
        """
        搜索笔记（官方搜索接口）
        :param keyword: 搜索关键词
        :param with_abstract: 是否返回摘要
        :param with_favor: 是否包含收藏
        :return: 搜索结果列表
        """
        url = f'{self.kb_server}/ks/note/search/{self.kb_guid}'
        params = {
            'ss': keyword,
            'withAbstract': 'true' if with_abstract else 'false',
            'withFavor': 'true' if with_favor else 'false',
            'clientType': 'web',
            'clientVersion': '4.0',
            'lang': 'zh-cn'
        }
        headers = {
            'X-Wiz-Token': self.token,
            'X-Wiz-Referer': 'http://127.0.0.1'
        }

        response = requests.get(url, params=params, headers=headers)

        if response.status_code != 200:
            raise Exception(f'搜索笔记失败: HTTP状态码 {response.status_code}')

        data = response.json()
        if data.get('returnCode') != 200:
            raise Exception(f'搜索笔记失败: {data}')

        return data.get("result", [])

    def get_note_detail(self, doc_guid: str):
        """
        获取笔记详情（用于判断笔记类型和下载内容）
        :param doc_guid: 笔记GUID
        :return: 笔记详情数据
        """
        note_download_url = f'{self.kb_server}/ks/note/download/{self.kb_guid}/{doc_guid}'
        response = requests.get(
            note_download_url,
            params={'downloadInfo': '0', 'downloadData': '1'},
            headers={'X-Wiz-Token': self.token}
        )

        if response.status_code != 200:
            raise Exception(f'下载笔记失败: HTTP状态码 {response.status_code}')

        data = response.json()
        if data.get('returnCode') != 200:
            raise Exception(f'下载笔记失败: {data}')

        return data

    def get_note_content(self, doc_guid: str):
        """
        获取笔记正文内容
        :param doc_guid: 笔记GUID
        :return: 原始内容字符串
        """
        detail = self.get_note_detail(doc_guid)
        return detail.get('html', '')

    def get_collaboration_token(self, doc_guid: str) -> str:
        """
        获取协作笔记的 editorToken
        :param doc_guid: 笔记GUID
        :return: editorToken
        """
        url = f'{self.kb_server}/ks/note/{self.kb_guid}/{doc_guid}/tokens'
        response = requests.post(url, headers={'X-Wiz-Token': self.token})

        if response.status_code != 200:
            raise Exception(f'获取协作笔记token失败: HTTP状态码 {response.status_code}')

        data = response.json()
        if data.get('returnCode') != 200:
            raise Exception(f'获取协作笔记token失败: {data}')

        return data['result']['editorToken']

    def get_collaboration_content(self, editor_token: str, doc_guid: str) -> str:
        """
        通过 WebSocket 获取协作笔记内容
        :param editor_token: 协作编辑器 token
        :param doc_guid: 笔记GUID
        :return: 协作笔记 JSON 字符串
        """
        # 构建 WebSocket URL
        scheme = 'wss' if self.config.base_url.startswith('https') else 'ws'
        ws_url = f"{scheme}://{self.domain}/editor/{self.kb_guid}/{doc_guid}"

        # SSL 配置
        sslopt = None
        if scheme == 'wss':
            import certifi
            sslopt = {
                'cert_reqs': ssl.CERT_REQUIRED,
                'ca_certs': certifi.where(),
            }

        # 构建请求消息
        hs_request = {
            "a": "hs",
            "id": None,
            "auth": {
                "appId": self.kb_guid,
                "docId": doc_guid,
                "userId": self.user_guid,
                "permission": "w",
                "token": editor_token
            }
        }

        f_request = {
            "a": "f",
            "c": self.kb_guid,
            "d": doc_guid,
            "v": None
        }

        s_request = {
            "a": "s",
            "c": self.kb_guid,
            "d": doc_guid,
            "v": None
        }

        ws = create_connection(ws_url, sslopt=sslopt)

        # 3 次 hs 握手
        ws.send(json.dumps(hs_request))
        ws.recv()
        ws.send(json.dumps(hs_request))
        ws.recv()
        ws.send(json.dumps(hs_request))
        ws.recv()

        # f 请求，第二个 recv() 返回正文
        ws.send(json.dumps(f_request))
        ws.recv()
        content = ws.recv()

        # s 请求
        ws.send(json.dumps(s_request))
        ws.recv()

        ws.close()

        logger.info(f"获取协作笔记内容成功: doc_guid={doc_guid}")
        return content

    def get_note_attachments(self, doc_guid: str):
        """
        获取笔记附件列表
        :param doc_guid: 笔记GUID
        :return: 附件列表
        """
        url = f'{self.kb_server}/ks/note/attachments/{self.kb_guid}/{doc_guid}'
        params = {
            'extra': '1',
            'clientType': 'web',
            'clientVersion': '4.0',
            'lang': 'zh-cn'
        }
        response = requests.get(url, params=params, headers={'X-Wiz-Token': self.token})

        if response.status_code != 200:
            raise Exception(f'获取笔记附件列表失败: HTTP状态码 {response.status_code}')

        data = response.json()
        if data.get('returnCode') != 200:
            raise Exception(f'获取笔记附件列表失败: {data}')

        return data['result']

    def download_attachment(self, doc_guid: str, att_guid: str):
        """
        下载普通附件
        :param doc_guid: 笔记GUID
        :param att_guid: 附件GUID
        :return: 二进制内容
        """
        url = f'{self.kb_server}/ks/attachment/download/{self.kb_guid}/{doc_guid}/{att_guid}'
        params = {
            'clientType': 'web',
            'clientVersion': '4.0',
            'lang': 'zh-cn'
        }

        timeout = (self.ATTACHMENT_CONNECT_TIMEOUT_S, self.ATTACHMENT_READ_TIMEOUT_S)

        response = requests.get(
            url,
            params=params,
            headers={'X-Wiz-Token': self.token},
            stream=True,
            timeout=timeout
        )

        if response.status_code != 200:
            raise Exception(f'下载附件失败: HTTP状态码 {response.status_code}')

        return response.content

    def download_collaboration_resource(self, editor_token: str, doc_guid: str, src: str):
        """
        下载协作笔记资源
        :param editor_token: 编辑器 token
        :param doc_guid: 笔记GUID
        :param src: 资源标识
        :return: 二进制内容
        """
        url = f'{self.kb_server}/editor/{self.kb_guid}/{doc_guid}/resources/{src}'

        timeout = (self.ATTACHMENT_CONNECT_TIMEOUT_S, self.ATTACHMENT_READ_TIMEOUT_S)

        headers = {
            'cookie': f'x-live-editor-token={editor_token}',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }

        response = requests.get(url, headers=headers, stream=True, timeout=timeout)

        if response.status_code != 200:
            raise Exception(f'下载协作资源失败: HTTP状态码 {response.status_code}')

        return response.content

    def create_note(self, title: str, html: str, category: str = "/My Notes/", tags: str = ""):
        """
        创建笔记
        :param title: 笔记标题
        :param html: HTML 内容
        :param category: 分类路径
        :param tags: 标签，逗号分隔
        :return: 创建结果
        """
        url = f'{self.kb_server}/ks/note/create/{self.kb_guid}'
        params = {
            'clientType': 'web',
            'clientVersion': '4.0',
            'lang': 'zh-cn'
        }

        # 构建请求体
        data = {
            'kbGuid': self.kb_guid,
            'html': html,
            'category': category,
            'owner': self.config.user_id,
            'tags': tags,
            'title': title,
            'params': None,
            'appInfo': None
        }

        response = requests.post(
            url,
            params=params,
            json=data,
            headers={
                'X-Wiz-Token': self.token,
                'content-type': 'application/json'
            }
        )

        if response.status_code != 200:
            raise Exception(f'创建笔记失败: HTTP状态码 {response.status_code}')

        result = response.json()
        if result.get('returnCode') != 200:
            raise Exception(f'创建笔记失败: {result}')

        return result

    def save_note(self, doc_guid: str, title: str, html: str, category: str = "/My Notes/"):
        """
        保存/更新笔记
        :param doc_guid: 笔记GUID
        :param title: 笔记标题
        :param html: HTML 内容
        :param category: 分类路径
        :return: 保存结果
        """
        url = f'{self.kb_server}/ks/note/save/{self.kb_guid}/{doc_guid}'
        params = {
            'infoOnly': '',
            'clientType': 'web',
            'clientVersion': '4.0',
            'lang': 'zh-cn'
        }

        # 构建请求体
        data = {
            'category': category,
            'docGuid': doc_guid,
            'kbGuid': self.kb_guid,
            'title': title,
            'html': html,
            'resources': []
        }

        response = requests.put(
            url,
            params=params,
            json=data,
            headers={
                'X-Wiz-Token': self.token,
                'content-type': 'application/json'
            }
        )

        if response.status_code != 200:
            raise Exception(f'保存笔记失败: HTTP状态码 {response.status_code}')

        result = response.json()
        if result.get('returnCode') != 200:
            raise Exception(f'保存笔记失败: {result}')

        return result

    def get_note_resources(self, doc_guid: str):
        """
        获取笔记的所有资源（图片/附件）
        :param doc_guid: 笔记GUID
        :return: 资源列表 [{name, url, type}, ...]
        """
        detail = self.get_note_detail(doc_guid)
        resources = detail.get('resources', [])

        result = []
        for res in resources:
            result.append({
                'name': res.get('name', ''),
                'url': res.get('url', ''),
                'type': res.get('type', 'attachment')
            })

        return result

    def download_resource(self, url: str) -> bytes:
        """
        下载资源文件
        :param url: 资源URL
        :return: 二进制内容
        """
        timeout = (self.ATTACHMENT_CONNECT_TIMEOUT_S, self.ATTACHMENT_READ_TIMEOUT_S)
        response = requests.get(url, timeout=timeout)

        if response.status_code != 200:
            raise Exception(f'下载资源失败: HTTP状态码 {response.status_code}')

        return response.content

    def get_collaboration_image(self, doc_guid: str, image_name: str) -> bytes:
        """
        获取协作笔记的图片
        :param doc_guid: 笔记GUID
        :param image_name: 图片名称
        :return: 图片二进制内容
        """
        token = self.get_collaboration_token(doc_guid)
        url = f'{self.kb_server}/editor/{self.kb_guid}/{doc_guid}/resources/{image_name}'

        timeout = (self.ATTACHMENT_CONNECT_TIMEOUT_S, self.ATTACHMENT_READ_TIMEOUT_S)
        headers = {
            'cookie': f'x-live-editor-token={token}',
            'user-agent': 'Mozilla/5.0'
        }

        response = requests.get(url, headers=headers, timeout=timeout)

        if response.status_code != 200:
            raise Exception(f'下载协作图片失败: HTTP状态码 {response.status_code}')

        return response.content
