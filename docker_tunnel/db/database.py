import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from db.models import Base

logger = logging.getLogger(__name__)

engine = None
SessionLocal = None

def init_db():
    """初始化数据库"""
    global engine, SessionLocal
    
    # 确保 data 目录存在
    db_dir = os.path.dirname(os.path.abspath('./data'))
    os.makedirs(db_dir + '/data', exist_ok=True)
    
    from config import DATABASE_PATH
    db_url = f'sqlite:///{DATABASE_PATH}'
    
    engine = create_engine(db_url, echo=False)
    SessionLocal = sessionmaker(bind=engine)
    
    Base.metadata.create_all(engine)
    logger.info(f"Database initialized at {DATABASE_PATH}")

def get_session() -> Session:
    """获取数据库会话"""
    if SessionLocal is None:
        init_db()
    session = SessionLocal()
    return session

@contextmanager
def session_scope():
    """数据库会话上下文管理器"""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()