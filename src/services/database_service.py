# -*- coding: utf-8 -*-
"""
数据库服务 - 提供审批数据的持久化存储
"""

import threading
import time
from datetime import datetime
from typing import Optional, Dict, Any, Union
from enum import Enum

try:
    import pymysql
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False
    

from ..utils.logger import get_logger
from .config_validator import ConfigurationError

logger = get_logger(__name__)


class ApprovalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved" 
    REJECTED = "rejected"
    TIMEOUT = "timeout"


class ApprovalRequest:
    """审批请求数据类"""
    
    def __init__(self, request_id: str, project: str, env: str, build: str,
                 job: str, version: str, desc: str = "默认更新", action: str = "部署",
                 timeout_seconds: int = 1800):
        self.request_id = request_id
        self.project = project
        self.env = env
        self.build = build
        self.job = job
        self.version = version
        self.desc = desc
        self.action = action
        self.timeout_seconds = timeout_seconds
        self.status = ApprovalStatus.PENDING.value
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at
        self.approver: Optional[str] = None
        self.approver_role: Optional[str] = None
        self.comment: Optional[str] = None


class DatabaseService:
    """MySQL/TiDB 数据库服务"""
    
    def __init__(self, db_config: dict = None):
        # 数据库配置必须由外部提供，不使用硬编码默认值
        if db_config is None:
            raise ConfigurationError(
                "❌ 数据库服务需要配置参数，请检查配置文件中的 database 配置节"
            )
        
        # 验证必需的配置项
        if not isinstance(db_config, dict):
            raise ConfigurationError("❌ 数据库配置必须是字典格式")
        
        self.config = db_config
        self.db_type = db_config.get('type', 'mysql').lower()
        
        # 验证数据库类型
        if self.db_type != 'mysql':
            raise ConfigurationError(f"❌ 不支持的数据库类型: {self.db_type}，当前仅支持 MySQL/TiDB")
        
        # 从配置中获取参数，不提供默认值
        self.connection_timeout = db_config.get('connection_timeout', 30)
        self.auto_cleanup_days = db_config.get('auto_cleanup_days', 30)
        self.lock = threading.RLock()
        
        # 验证数据库类型和依赖
        self._validate_database_support()
        
        # 初始化数据库连接信息
        self._init_connection_info()
        
        # 初始化数据库表
        self._init_database()
    
    def _validate_database_support(self):
        """验证数据库类型和依赖"""
        if self.db_type == 'mysql' and not MYSQL_AVAILABLE:
            raise ImportError("MySQL支持需要安装pymysql: pip install pymysql")
        elif self.db_type != 'mysql':
            raise ValueError(f"不支持的数据库类型: {self.db_type}，仅支持 MySQL/TiDB")
    
    def _init_connection_info(self):
        """初始化数据库连接信息"""
        if self.db_type == 'mysql':
            self._init_mysql_info()
    
    def _init_mysql_info(self):
        """初始化MySQL连接信息"""
        mysql_config = self.config.get('mysql')
        if not mysql_config:
            raise ConfigurationError(
                "❌ 配置文件中缺少 'database.mysql' 配置节\n"
                "请在 config/app.json 中添加 MySQL 数据库连接配置"
            )
        
        # 验证必需的MySQL配置项
        required_keys = ['host', 'port', 'database', 'username', 'password']
        missing_keys = [key for key in required_keys if key not in mysql_config]
        if missing_keys:
            raise ConfigurationError(
                f"❌ MySQL配置缺少必需项: {', '.join(missing_keys)}\n"
                "请在 config/app.json 的 database.mysql 节中添加这些配置"
            )
        
        self.mysql_config = {
            'host': mysql_config['host'],
            'port': int(mysql_config['port']),
            'database': mysql_config['database'],
            'user': mysql_config['username'],
            'password': mysql_config['password'],
            'charset': mysql_config.get('charset', 'utf8mb4'),
            'autocommit': True,
            'connect_timeout': self.connection_timeout
        }
        
        logger.info(f"✅ MySQL连接配置: {self.mysql_config['host']}:{self.mysql_config['port']}/{self.mysql_config['database']}")
    
    def _get_connection(self):
        """获取数据库连接"""
        if self.db_type == 'mysql':
            return pymysql.connect(**self.mysql_config)
        else:
            raise ValueError(f"不支持的数据库类型: {self.db_type}")
    
    def _get_dict_cursor(self, conn):
        """获取字典游标"""
        if self.db_type == 'mysql':
            return conn.cursor(pymysql.cursors.DictCursor)
    
    def _init_database(self):
        """初始化数据库表"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # 创建审批表
                cursor.execute(self._get_create_approvals_sql_mysql())
                cursor.execute(self._get_create_history_sql_mysql())
                conn.commit()
                
                logger.info(f"✅ {self.db_type.upper()}数据库初始化完成")
                
        except Exception as e:
            logger.error(f"❌ {self.db_type.upper()}数据库初始化失败: {e}")
            raise
    
    def _get_create_approvals_sql_mysql(self):
        """获取MySQL创建审批表的SQL"""
        return """
            CREATE TABLE IF NOT EXISTS approvals (
                request_id VARCHAR(255) PRIMARY KEY,
                project VARCHAR(100) NOT NULL,
                env VARCHAR(50) NOT NULL,
                build VARCHAR(100) NOT NULL,
                job VARCHAR(200) NOT NULL,
                version VARCHAR(100) NOT NULL,
                `desc` TEXT,
                `action` VARCHAR(50),
                timeout_seconds INT,
                status VARCHAR(20) DEFAULT 'pending',
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                approver VARCHAR(100),
                approver_role VARCHAR(100),
                comment TEXT,
                is_locked TINYINT DEFAULT 0,
                lock_timestamp DATETIME,
                lock_timeout INT DEFAULT 60,
                INDEX idx_status (status),
                INDEX idx_created_at (created_at),
                INDEX idx_project_env (project, env)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    
    def _get_create_history_sql_mysql(self):
        """获取MySQL创建历史表的SQL"""
        return """
            CREATE TABLE IF NOT EXISTS approval_history (
                id INT AUTO_INCREMENT PRIMARY KEY,
                request_id VARCHAR(255) NOT NULL,
                `action` VARCHAR(50) NOT NULL,
                operator VARCHAR(100) NOT NULL,
                operator_role VARCHAR(100),
                comment TEXT,
                `timestamp` DATETIME NOT NULL,
                INDEX idx_request_id (request_id),
                INDEX idx_timestamp (`timestamp`),
                FOREIGN KEY (request_id) REFERENCES approvals (request_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    
    def create_approval(self, approval: ApprovalRequest) -> bool:
        """创建审批请求"""
        try:
            with self.lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    # 插入审批记录
                    cursor.execute("""
                        INSERT INTO approvals 
                        (request_id, project, env, build, job, version, `desc`, `action`, 
                         timeout_seconds, status, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        approval.request_id, approval.project, approval.env, approval.build,
                        approval.job, approval.version, approval.desc, approval.action,
                        approval.timeout_seconds, approval.status, approval.created_at, approval.updated_at
                    ))
                    
                    # 添加历史记录
                    self._add_history(conn, approval.request_id, "created", "system", "system", "创建审批请求")
                    conn.commit()
                    
                    logger.info(f"✅ 创建审批请求: {approval.request_id}")
                    return True
                    
        except Exception as e:
            logger.error(f"❌ 创建审批请求失败: {approval.request_id} - {e}")
            return False
    
    def get_approval(self, request_id: str) -> Optional[ApprovalRequest]:
        """获取审批请求"""
        try:
            with self.lock:
                with self._get_connection() as conn:
                    cursor = self._get_dict_cursor(conn)
                    
                    # 根据数据库类型使用不同的占位符
                    if self.db_type == 'sqlite':
                        cursor.execute("SELECT * FROM approvals WHERE request_id = ?", (request_id,))
                    else:
                        cursor.execute("SELECT * FROM approvals WHERE request_id = %s", (request_id,))
                    
                    row = cursor.fetchone()
                    if row:
                        approval = ApprovalRequest(
                            request_id=row['request_id'],
                            project=row['project'],
                            env=row['env'],
                            build=row['build'],
                            job=row['job'],
                            version=row['version'],
                            desc=row['desc'],
                            action=row['action'],
                            timeout_seconds=row['timeout_seconds']
                        )
                        approval.status = row['status']
                        approval.created_at = row['created_at']
                        approval.updated_at = row['updated_at']
                        approval.approver = row['approver']
                        approval.approver_role = row['approver_role']
                        approval.comment = row['comment']
                        return approval
                    
                    return None
                    
        except Exception as e:
            logger.error(f"❌ 获取审批请求失败: {request_id} - {e}")
            return None
    
    def lock_approval(self, request_id: str, approver: str, timeout: int = 60) -> bool:
        """锁定审批请求防止并发操作"""
        try:
            with self.lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    now = datetime.now()
                    
                    # 格式化时间
                    if self.db_type == 'sqlite':
                        now_str = now.isoformat()
                        # 检查是否已锁定且未过期
                        cursor.execute("""
                            SELECT is_locked, lock_timestamp, lock_timeout, approver 
                            FROM approvals WHERE request_id = ?
                        """, (request_id,))
                        
                        placeholders = "?, ?, ?, ?"
                        update_params = (1, now_str, timeout, approver, request_id)
                    else:
                        now_str = now.strftime('%Y-%m-%d %H:%M:%S')
                        # 检查是否已锁定且未过期
                        cursor.execute("""
                            SELECT is_locked, lock_timestamp, lock_timeout, approver 
                            FROM approvals WHERE request_id = %s
                        """, (request_id,))
                        
                        if self.db_type == 'mysql':
                            lock_value = 1
                        else:  # postgresql
                            lock_value = True
                        
                        placeholders = "%s, %s, %s, %s"
                        update_params = (lock_value, now_str, timeout, approver, request_id)
                    
                    row = cursor.fetchone()
                    if not row:
                        return False
                    
                    is_locked, lock_timestamp, lock_timeout, current_approver = row
                    
                    # 检查锁是否过期
                    if is_locked and lock_timestamp:
                        if self.db_type == 'sqlite':
                            lock_time = datetime.fromisoformat(str(lock_timestamp))
                        else:
                            lock_time = lock_timestamp if isinstance(lock_timestamp, datetime) else datetime.strptime(str(lock_timestamp), '%Y-%m-%d %H:%M:%S')
                        
                        if (datetime.now() - lock_time).total_seconds() > lock_timeout:
                            is_locked = 0  # 锁已过期
                    
                    if is_locked and current_approver != approver:
                        return False  # 被其他人锁定
                    
                    # 设置锁
                    if self.db_type == 'sqlite':
                        cursor.execute(f"""
                            UPDATE approvals 
                            SET is_locked = ?, lock_timestamp = ?, lock_timeout = ?, approver = ?
                            WHERE request_id = ?
                        """, update_params)
                    else:
                        cursor.execute(f"""
                            UPDATE approvals 
                            SET is_locked = %s, lock_timestamp = %s, lock_timeout = %s, approver = %s
                            WHERE request_id = %s
                        """, update_params)
                    
                    if self.db_type != 'sqlite':
                        conn.commit()
                    
                    logger.debug(f"🔒 锁定审批请求: {request_id} by {approver}")
                    return True
                    
        except Exception as e:
            logger.error(f"❌ 锁定审批请求失败: {request_id} - {e}")
            return False
    
    def unlock_approval(self, request_id: str) -> bool:
        """解锁审批请求"""
        try:
            with self.lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    
                    # 解锁审批请求
                    if self.db_type == 'sqlite':
                        cursor.execute("""
                            UPDATE approvals 
                            SET is_locked = 0, lock_timestamp = NULL, lock_timeout = NULL
                            WHERE request_id = ?
                        """, (request_id,))
                    else:
                        cursor.execute("""
                            UPDATE approvals 
                            SET is_locked = 0, lock_timestamp = NULL, lock_timeout = NULL
                            WHERE request_id = %s
                        """, (request_id,))
                    
                    conn.commit()
                    
                    if cursor.rowcount > 0:
                        logger.debug(f"✅ 解锁审批请求: {request_id}")
                        return True
                    else:
                        logger.warning(f"⚠️ 解锁失败，审批请求不存在: {request_id}")
                        return False
                    
        except Exception as e:
            logger.error(f"❌ 解锁审批请求失败: {request_id} - {e}")
            return False
    
    def update_approval_status(self, request_id: str, status: str, approver: str,
                             approver_role: str, comment: str = "") -> Dict[str, Any]:
        """更新审批状态"""
        try:
            with self.lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    now = datetime.now()
                    
                    # 格式化时间
                    if self.db_type == 'sqlite':
                        now_str = now.isoformat()
                        # 检查当前状态
                        cursor.execute("""
                            SELECT status, is_locked, approver FROM approvals WHERE request_id = ?
                        """, (request_id,))
                    else:
                        now_str = now.strftime('%Y-%m-%d %H:%M:%S')
                        cursor.execute("""
                            SELECT status, is_locked, approver FROM approvals WHERE request_id = %s
                        """, (request_id,))
                    
                    row = cursor.fetchone()
                    if not row:
                        return {
                            "success": False,
                            "message": "审批请求不存在",
                            "code": "NOT_FOUND"
                        }
                    
                    current_status, is_locked, current_approver = row
                    
                    # 强化状态检查 - 防止任何非pending状态的重复操作
                    if current_status != ApprovalStatus.PENDING.value:
                        logger.warning(f"🚫 阻止重复审批操作: {request_id}, 当前状态: {current_status}, 当前处理人: {current_approver}")
                        return {
                            "success": False,
                            "message": f"❌ 审批已处理！当前状态: {current_status}, 操作人: {current_approver}，请勿重复操作",
                            "current_status": current_status,
                            "approver": current_approver,
                            "code": "ALREADY_PROCESSED"
                        }
                    
                    if not is_locked or current_approver != approver:
                        return {
                            "success": False,
                            "message": "审批请求未被正确锁定",
                            "code": "LOCK_REQUIRED"
                        }
                    
                    # 更新状态
                    if self.db_type == 'sqlite':
                        cursor.execute("""
                            UPDATE approvals 
                            SET status = ?, approver = ?, approver_role = ?, comment = ?, 
                                updated_at = ?, is_locked = 0, lock_timestamp = NULL
                            WHERE request_id = ?
                        """, (status, approver, approver_role, comment, now_str, request_id))
                    elif self.db_type == 'mysql':
                        cursor.execute("""
                            UPDATE approvals 
                            SET status = %s, approver = %s, approver_role = %s, comment = %s, 
                                updated_at = %s, is_locked = 0, lock_timestamp = NULL
                            WHERE request_id = %s
                        """, (status, approver, approver_role, comment, now_str, request_id))
                    else:  # postgresql
                        cursor.execute("""
                            UPDATE approvals 
                            SET status = %s, approver = %s, approver_role = %s, comment = %s, 
                                updated_at = %s, is_locked = FALSE, lock_timestamp = NULL
                            WHERE request_id = %s
                        """, (status, approver, approver_role, comment, now_str, request_id))
                    
                    # 记录历史
                    self._add_history(conn, request_id, status, approver, approver_role, comment)
                    
                    # 强制立即提交事务 - 确保状态更新立即生效
                    conn.commit()
                    logger.info(f"🔄 数据库事务强制提交完成: {request_id} -> {status}")
                    
                    # 二次验证状态是否真的更新了
                    cursor.execute("SELECT status FROM approvals WHERE request_id = %s" if self.db_type == 'mysql' else "SELECT status FROM approvals WHERE request_id = ?", (request_id,))
                    verify_row = cursor.fetchone()
                    if verify_row and verify_row[0] == status:
                        logger.info(f"✅ 状态更新验证成功: {request_id} -> {status}")
                    else:
                        logger.error(f"❌ 状态更新验证失败: {request_id}, 期望: {status}, 实际: {verify_row[0] if verify_row else 'NULL'}")
                    
                    logger.info(f"✅ 更新审批状态完成: {request_id} - {status} by {approver}")
                    return {
                        "success": True,
                        "message": f"审批{status}成功",
                        "status": status,
                        "approver": approver,
                        "approver_role": approver_role,
                        "timestamp": now_str,
                        "code": "SUCCESS"
                    }
                    
        except Exception as e:
            logger.error(f"❌ 更新审批状态失败: {request_id} - {e}")
            return {
                "success": False,
                "message": f"系统错误: {str(e)}",
                "code": "SYSTEM_ERROR"
            }
    
    def _add_history(self, conn, request_id: str, action: str, operator: str,
                    operator_role: str, comment: str):
        """添加历史记录"""
        cursor = conn.cursor()
        now = datetime.now()
        
        if self.db_type == 'sqlite':
            now_str = now.isoformat()
            cursor.execute("""
                INSERT INTO approval_history 
                (request_id, `action`, operator, operator_role, comment, `timestamp`)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (request_id, action, operator, operator_role, comment, now_str))
        else:
            now_str = now.strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute("""
                INSERT INTO approval_history 
                (request_id, `action`, operator, operator_role, comment, `timestamp`)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (request_id, action, operator, operator_role, comment, now_str))
    
    def cleanup_expired_approvals(self):
        """清理过期的审批请求"""
        try:
            with self.lock:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    now = datetime.now()
                    
                    # 查找过期的待审批请求
                    if self.db_type == 'sqlite':
                        cursor.execute("""
                            SELECT request_id, created_at, timeout_seconds 
                            FROM approvals 
                            WHERE status = 'pending'
                        """)
                    else:
                        cursor.execute("""
                            SELECT request_id, created_at, timeout_seconds 
                            FROM approvals 
                            WHERE status = 'pending'
                        """)
                    
                    expired_requests = []
                    for row in cursor.fetchall():
                        request_id, created_at, timeout_seconds = row
                        
                        # 处理不同数据库的时间格式
                        if self.db_type == 'sqlite':
                            created_time = datetime.fromisoformat(str(created_at))
                        else:
                            created_time = created_at if isinstance(created_at, datetime) else datetime.strptime(str(created_at), '%Y-%m-%d %H:%M:%S')
                        
                        if (now - created_time).total_seconds() > timeout_seconds:
                            expired_requests.append(request_id)
                    
                    # 标记为超时
                    for request_id in expired_requests:
                        if self.db_type == 'sqlite':
                            now_str = now.isoformat()
                            cursor.execute("""
                                UPDATE approvals 
                                SET status = 'timeout', updated_at = ?
                                WHERE request_id = ?
                            """, (now_str, request_id))
                        else:
                            now_str = now.strftime('%Y-%m-%d %H:%M:%S')
                            cursor.execute("""
                                UPDATE approvals 
                                SET status = 'timeout', updated_at = %s
                                WHERE request_id = %s
                            """, (now_str, request_id))
                        
                        self._add_history(conn, request_id, "timeout", "system", "system", "审批超时")
                    
                    if self.db_type != 'sqlite':
                        conn.commit()
                    
                    if expired_requests:
                        logger.info(f"⏰ 清理过期审批请求: {len(expired_requests)}个")
                        
        except Exception as e:
            logger.error(f"❌ 清理过期审批失败: {e}")


# 延迟初始化，在配置加载后创建
database_service = None

def initialize_database_service(config_service=None):
    """初始化数据库服务"""
    global database_service
    
    if database_service is None:
        # 如果提供了配置服务，从配置中读取
        if config_service:
            try:
                # 确保配置已加载
                config_service.load_config_files()
                db_config = config_service.get_database_config()
                logger.info(f"从配置加载数据库配置: host={db_config.get('mysql', {}).get('host', 'localhost')}, user={db_config.get('mysql', {}).get('username', 'root')}")
                database_service = DatabaseService(db_config)
                logger.info(f"✅ 数据库服务初始化完成: MySQL/TiDB")
            except Exception as e:
                logger.error(f"❌ 从配置初始化数据库失败: {e}")
                logger.info("⚠️ 回退到默认配置")
                database_service = DatabaseService()
        else:
            # 使用默认配置
            logger.warning("⚠️ 没有提供配置服务，使用默认数据库配置")
            database_service = DatabaseService()
            logger.info(f"✅ 数据库服务使用默认配置初始化: MySQL/TiDB")
    
    return database_service

def get_database_service():
    """获取数据库服务实例"""
    global database_service
    if database_service is None:
        logger.warning("数据库服务尚未初始化，请先调用initialize_database_service(config_service)")
        return None
    return database_service

# 为了兼容性，保留原来的变量名，但使用延迟初始化
def _get_database_service():
    """获取数据库服务实例的内部函数"""
    return get_database_service()

# 延迟初始化 - 不在模块导入时创建，等待显式调用
database_service = None

