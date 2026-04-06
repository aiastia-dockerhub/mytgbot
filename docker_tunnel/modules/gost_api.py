"""
gost v3 REST API 客户端
文档参考: https://gost.run/api/
"""
import aiohttp
import logging
import json
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)


class GostAPIClient:
    """gost v3 API 客户端"""

    def __init__(self, ip: str, api_port: int, api_user: str, api_password: str):
        self.base_url = f"http://{ip}:{api_port}"
        self.auth = aiohttp.BasicAuth(api_user, api_password)
        self.ip = ip
        self.api_port = api_port

    async def _request(self, method: str, path: str, json_data: Optional[Dict] = None) -> tuple:
        """
        发送请求到 gost API
        返回 (success: bool, data: dict/str)
        """
        url = f"{self.base_url}{path}"
        timeout = aiohttp.ClientTimeout(total=10)
        try:
            async with aiohttp.ClientSession(auth=self.auth, timeout=timeout) as session:
                async with session.request(method, url, json=json_data) as resp:
                    if resp.status in (200, 201, 204):
                        try:
                            data = await resp.json()
                        except:
                            data = {}
                        return True, data
                    else:
                        text = await resp.text()
                        logger.warning(f"gost API error: {resp.status} - {text}")
                        return False, f"HTTP {resp.status}: {text}"
        except aiohttp.ClientConnectorError as e:
            logger.error(f"Cannot connect to gost API at {self.ip}:{self.api_port}: {e}")
            return False, f"无法连接到 {self.ip}:{self.api_port}"
        except aiohttp.ClientResponseError as e:
            logger.error(f"gost API response error: {e}")
            return False, f"API 响应错误: {e}"
        except Exception as e:
            logger.error(f"gost API request failed: {e}")
            return False, f"请求失败: {str(e)}"

    async def test_connection(self) -> tuple:
        """测试 API 连通性"""
        return await self._request("GET", "/config")

    # ==================== 配置管理 ====================

    async def get_config(self) -> tuple:
        """获取完整配置"""
        return await self._request("GET", "/config")

    async def get_services(self) -> tuple:
        """获取所有服务"""
        return await self._request("GET", "/config/services")

    async def get_service(self, name: str) -> tuple:
        """获取指定服务"""
        return await self._request("GET", f"/config/services/{name}")

    async def create_service(self, name: str, addr: str, handler: Dict,
                             listener: Optional[Dict] = None,
                             forwarder: Optional[Dict] = None) -> tuple:
        """
        创建服务
        
        Args:
            name: 服务名称
            addr: 监听地址 (e.g. ":8080")
            handler: 处理器配置 (e.g. {"type": "socks5"})
            listener: 监听器配置 (e.g. {"type": "tls"})
            forwarder: 转发器配置 (e.g. {"nodes": [{"addr": "1.2.3.4:8080"}]})
        """
        service = {
            "name": name,
            "addr": addr,
            "handler": handler,
        }
        if listener:
            service["listener"] = listener
        if forwarder:
            service["forwarder"] = forwarder

        return await self._request("POST", "/config/services", service)

    async def delete_service(self, name: str) -> tuple:
        """删除服务"""
        return await self._request("DELETE", f"/config/services/{name}")

    # ==================== 链路管理 ====================

    async def get_chains(self) -> tuple:
        """获取所有链路"""
        return await self._request("GET", "/config/chains")

    async def create_chain(self, name: str, hops: List[Dict]) -> tuple:
        """
        创建链路
        
        Args:
            name: 链路名称
            hops: 跳数配置列表
                  [{"nodes": [{"addr": "1.2.3.4:8080", "connector": {"type": "relay"}}]}]
        """
        chain = {
            "name": name,
            "hops": hops,
        }
        return await self._request("POST", "/config/chains", chain)

    async def delete_chain(self, name: str) -> tuple:
        """删除链路"""
        return await self._request("DELETE", f"/config/chains/{name}")

    # ==================== 服务状态 ====================

    async def get_services_status(self) -> tuple:
        """获取服务运行状态"""
        return await self._request("GET", "/services")

    # ==================== 高级操作 ====================

    async def create_proxy_service(self, name: str, protocol: str, port: int,
                                   username: str = "", password: str = "") -> tuple:
        """
        创建代理服务（单服务器模式）
        
        支持协议: socks5, http, socks5+tls, http+tls, ss (shadowsocks)
        """
        addr = f":{port}"

        # 解析协议
        handler_type = protocol
        listener_type = None

        if "+tls" in protocol:
            handler_type = protocol.replace("+tls", "")
            listener_type = "tls"
        elif protocol == "ss":
            handler_type = "ss"
        elif protocol == "tcp":
            handler_type = "tcp"

        handler = {"type": handler_type}
        if protocol == "ss":
            # Shadowsocks 默认配置
            handler["auth"] = {"username": username or "ss_user", "password": password or "ss_password_change_me"}
            handler.get("auth", {})["method"] = "chacha20-ietf-poly1305"

        service = {
            "name": name,
            "addr": addr,
            "handler": handler,
        }
        if listener_type:
            service["listener"] = {"type": listener_type}

        return await self._request("POST", "/config/services", service)

    async def create_tunnel_entry(self, service_name: str, port: int,
                                  next_hop_addr: str, protocol: str = "relay+tls") -> tuple:
        """
        创建隧道入口服务
        
        监听端口，转发到下一跳
        TLS: 不指定证书时 gost 自动生成自签名证书（用于加密足够）
        """
        handler_type, listener_type = self._parse_protocol(protocol)
        
        handler = {"type": handler_type or "relay"}
        service = {
            "name": service_name,
            "addr": f":{port}",
            "handler": handler,
            "forwarder": {
                "nodes": [
                    {"addr": next_hop_addr}
                ]
            }
        }
        if listener_type:
            service["listener"] = {"type": listener_type}

        return await self._request("POST", "/config/services", service)

    async def create_tunnel_relay(self, service_name: str, port: int,
                                  next_hop_addr: str, protocol: str = "relay+tls") -> tuple:
        """
        创建隧道中继服务
        
        监听端口，转发到下一跳
        TLS: 不指定证书时 gost 自动生成自签名证书（用于加密足够）
        """
        handler_type, listener_type = self._parse_protocol(protocol)
        
        handler = {"type": handler_type or "relay"}
        service = {
            "name": service_name,
            "addr": f":{port}",
            "handler": handler,
            "forwarder": {
                "nodes": [
                    {"addr": next_hop_addr}
                ]
            }
        }
        if listener_type:
            service["listener"] = {"type": listener_type}

        return await self._request("POST", "/config/services", service)

    async def create_tunnel_exit(self, service_name: str, port: int,
                                 protocol: str = "relay+tls") -> tuple:
        """
        创建隧道出口服务
        
        监听端口，不转发
        TLS: 不指定证书时 gost 自动生成自签名证书（用于加密足够）
        """
        handler_type, listener_type = self._parse_protocol(protocol)
        
        handler = {"type": handler_type or "relay"}
        service = {
            "name": service_name,
            "addr": f":{port}",
            "handler": handler,
        }
        if listener_type:
            service["listener"] = {"type": listener_type}

        return await self._request("POST", "/config/services", service)

    async def create_forward_service(self, name: str, listen_port: int,
                                     target_addr: str, protocol: str = "tcp") -> tuple:
        """
        创建 TCP/UDP 转发服务
        
        监听 listen_port，转发到 target_addr (e.g. "8.8.8.8:80")
        
        Args:
            name: 服务名称
            listen_port: 本地监听端口
            target_addr: 目标地址 (IP:Port)
            protocol: 协议类型 (tcp, udp)
        """
        handler_type = "tcp" if protocol in ("tcp", "udp") else protocol

        service = {
            "name": name,
            "addr": f":{listen_port}",
            "handler": {"type": handler_type},
            "forwarder": {
                "nodes": [
                    {"addr": target_addr}
                ]
            }
        }

        return await self._request("POST", "/config/services", service)

    @staticmethod
    def _parse_protocol(protocol: str) -> tuple:
        """解析协议字符串，返回 (handler_type, listener_type)"""
        if "+" in protocol:
            parts = protocol.split("+")
            handler_type = parts[0]
            listener_type = parts[1] if len(parts) > 1 else None
            return handler_type, listener_type
        return protocol, None