"""
初始化数据库
"""
from bot import db_host, db_user, db_pwd, db_name, db_port
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session

# 创建engine对象
engine = create_engine(f"mysql+pymysql://{db_user}:{db_pwd}@{db_host}:{db_port}/{db_name}?utf8mb4", echo=False,
                       echo_pool=False,
                       pool_size=50,                    # 增加连接池大小，支持更多并发
                       max_overflow=20,                 # 允许额外连接，应对突发流量
                       pool_recycle=60 * 15,           # 缩短连接回收时间至15分钟
                       pool_pre_ping=True,             # 连接预检，确保连接有效性
                       pool_timeout=30,                # 获取连接的超时时间
                       )

# 创建Base对象
Base = declarative_base()
Base.metadata.bind = engine
Base.metadata.create_all(bind=engine, checkfirst=True)


# 调用sql_start()函数，返回一个Session对象
def sql_start() -> scoped_session:
    return scoped_session(sessionmaker(bind=engine, autoflush=False))


Session = sql_start()
