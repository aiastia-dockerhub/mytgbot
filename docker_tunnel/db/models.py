from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()


class Server(Base):
    """服务器模型 - 记录 gost API 连接信息"""
    __tablename__ = 'servers'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    ip = Column(String(100), nullable=False)
    api_port = Column(Integer, default=18080)
    api_user = Column(String(100), nullable=False)
    api_password_encrypted = Column(Text, nullable=False)  # 加密存储
    status = Column(String(20), default='offline')  # online/offline
    remark = Column(String(500), default='')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联
    proxies = relationship("Proxy", back_populates="server", cascade="all, delete-orphan")
    tunnel_nodes = relationship("TunnelNode", back_populates="server", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Server(id={self.id}, name='{self.name}', ip='{self.ip}', status='{self.status}')>"


class Proxy(Base):
    """代理模型 - 单服务器上的代理服务"""
    __tablename__ = 'proxies'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    server_id = Column(Integer, ForeignKey('servers.id'), nullable=False)
    protocol = Column(String(50), default='socks5')  # socks5/http/ss/relay+tls/tcp
    listen_port = Column(Integer, nullable=False)
    config_json = Column(Text, default='')  # gost 服务配置 JSON
    is_active = Column(Boolean, default=False)
    remark = Column(String(500), default='')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    server = relationship("Server", back_populates="proxies")

    __table_args__ = (
        Index('ix_proxies_server_name', 'server_id', 'name', unique=True),
    )

    def __repr__(self):
        return f"<Proxy(id={self.id}, name='{self.name}', protocol='{self.protocol}', port={self.listen_port})>"


class Tunnel(Base):
    """隧道模型 - 多服务器组成的链路"""
    __tablename__ = 'tunnels'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    protocol = Column(String(50), default='relay+tls')  # 隧道协议
    port = Column(Integer, default=8080)  # 隧道端口
    is_active = Column(Boolean, default=False)
    remark = Column(String(500), default='')
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联节点（有序）
    nodes = relationship("TunnelNode", back_populates="tunnel", cascade="all, delete-orphan",
                         order_by="TunnelNode.node_order")

    def __repr__(self):
        return f"<Tunnel(id={self.id}, name='{self.name}', protocol='{self.protocol}', active={self.is_active})>"

    @property
    def node_count(self):
        return len(self.nodes) if self.nodes else 0


class TunnelNode(Base):
    """隧道节点模型 - 隧道中的每个服务器节点"""
    __tablename__ = 'tunnel_nodes'

    id = Column(Integer, primary_key=True)
    tunnel_id = Column(Integer, ForeignKey('tunnels.id'), nullable=False)
    server_id = Column(Integer, ForeignKey('servers.id'), nullable=False)
    node_order = Column(Integer, nullable=False)  # 节点顺序，0=入口
    role = Column(String(20), nullable=False)  # entry/relay/exit
    gost_service_name = Column(String(100), default='')  # gost 中创建的服务名
    created_at = Column(DateTime, default=datetime.utcnow)

    tunnel = relationship("Tunnel", back_populates="nodes")
    server = relationship("Server", back_populates="tunnel_nodes")

    __table_args__ = (
        Index('ix_tunnel_nodes_tunnel_order', 'tunnel_id', 'node_order', unique=True),
    )

    def __repr__(self):
        return f"<TunnelNode(id={self.id}, tunnel_id={self.tunnel_id}, order={self.node_order}, role='{self.role}')>"