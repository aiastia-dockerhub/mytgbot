"""
状态监控模块
"""
import logging
from db.database import session_scope
from db.models import Server, Proxy, Tunnel
from modules.server_handlers import get_server_api_client

logger = logging.getLogger(__name__)


async def check_all_servers():
    """检查所有服务器状态，返回统计信息"""
    with session_scope() as session:
        servers = session.query(Server).all()
        stats = {
            'total': len(servers),
            'online': 0,
            'offline': 0,
            'details': []
        }
        for server in servers:
            client = get_server_api_client(server)
            success, _ = await client.test_connection()
            srv = session.query(Server).filter(Server.id == server.id).first()
            if srv:
                srv.status = 'online' if success else 'offline'

            if success:
                stats['online'] += 1
                # 获取服务数
                svc_ok, svc_data = await client.get_services()
                svc_count = len(svc_data) if svc_ok and isinstance(svc_data, list) else 0
                stats['details'].append({
                    'name': server.name,
                    'ip': server.ip,
                    'status': 'online',
                    'services': svc_count
                })
            else:
                stats['offline'] += 1
                stats['details'].append({
                    'name': server.name,
                    'ip': server.ip,
                    'status': 'offline',
                    'services': 0
                })
    return stats


async def get_overview():
    """获取系统概览"""
    with session_scope() as session:
        server_count = session.query(Server).count()
        proxy_count = session.query(Proxy).count()
        tunnel_count = session.query(Tunnel).count()
        active_tunnels = session.query(Tunnel).filter(Tunnel.is_active == True).count()

    return {
        'servers': server_count,
        'proxies': proxy_count,
        'tunnels': tunnel_count,
        'active_tunnels': active_tunnels
    }