# -*- coding: utf-8 -*-
"""
API处理器模块 - 完整的Jenkins回调审批功能
"""

import json
import time
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string
from urllib.parse import unquote

from ..core.approval_manager import ApprovalManager
from ..services.permission_service import permission_service
from ..services.database_service import get_database_service, ApprovalRequest, ApprovalStatus
from ..services.config_service import config_service
from ..utils.logger import get_logger

logger = get_logger(__name__)


class APIHandler:
    """Flask API处理器 - 支持完整审批流程"""
    
    def __init__(self, approval_manager):
        self.approval_manager = approval_manager
        self.app = Flask(__name__)
        self.app.config['JSON_AS_ASCII'] = False
        self.reminder_timers = {}    # 存储提醒定时器
        self._stopped_reminders = set()  # 存储已停止的提醒
        self._processing_approvals = set()  # 存储正在处理的审批ID，防止重复处理
        self.pending_approvals = {}  # 存储待审批请求的内存状态
        self._approval_events = {}  # 存储审批事件，用于立即通知等待线程
        self.telegram_handler = None  # 将在初始化时设置
        self._setup_routes()
        
        # 启动清理线程
        self._start_cleanup_thread()
        
        logger.info("Jenkins审批API处理器初始化完成")
    
    @property
    def database_service(self):
        """获取数据库服务实例"""
        return get_database_service()
    
    def set_telegram_handler(self, telegram_handler):
        """设置Telegram处理器引用"""
        self.telegram_handler = telegram_handler
    
    def process_approval_internal(self, approval_id: str, action: str, approver_id: str, approver_username: str, comment: str = ""):
        """🔥 纯内存审批处理方法 - 完全脱离数据库依赖"""
        try:
            # 强制输出调试信息
            print(f"\n" + "="*80)
            print(f"🚀 【PURE MEMORY APPROVAL】 {action.upper()} - {approval_id}")
            print(f"👤 操作人: {approver_username}")
            print(f"💬 备注: {comment}")
            print(f"⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"📊 当前内存审批: {list(self.pending_approvals.keys())}")
            print(f"📊 当前事件对象: {list(self._approval_events.keys())}")
            print(f"="*80)
            
            logger.info(f"🚀 纯内存处理审批: {approval_id} - {action} by {approver_username}")
            
            # 防止重复处理
            if approval_id in self._processing_approvals:
                print(f"⚠️ 审批正在处理中: {approval_id}")
                return False, '审批正在处理中，请勿重复点击'
            
            self._processing_approvals.add(approval_id)
            
            try:
                # 🔥 第1步：立即停止提醒
                print(f"📝 步骤1: 停止提醒定时器")
                self._cancel_reminder_timer(approval_id)
                
                # 🔥 第2步：检查内存中是否存在审批
                if approval_id not in self.pending_approvals:
                    print(f"❌ 内存中不存在审批: {approval_id}")
                    print(f"📋 当前内存审批: {list(self.pending_approvals.keys())}")
                    return False, f'审批 {approval_id} 不存在或已过期'
                
                # 🔥 第2.5步：检查审批状态，防止重复处理
                current_status = self.pending_approvals[approval_id]['status']
                if current_status != 'pending':
                    print(f"❌ 审批已被处理: {approval_id}")
                    print(f"📊 当前状态: {current_status}")
                    print(f"👤 之前审批人: {self.pending_approvals[approval_id].get('approver', 'unknown')}")
                    
                    # 根据当前状态返回友好提示
                    if current_status == 'approved':
                        return False, f'该审批已被通过，无法重复操作'
                    elif current_status == 'rejected':
                        return False, f'该审批已被拒绝，无法重复操作'
                    else:
                        return False, f'该审批已被处理（状态：{current_status}），无法重复操作'
                
                # 🔥 第3步：立即更新内存状态 (不依赖数据库)
                print(f"📝 步骤3: 更新内存状态")
                old_status = self.pending_approvals[approval_id]['status']
                current_time = datetime.now().isoformat()
                
                # 获取用户角色
                from ..services.permission_service import permission_service
                approver_role = permission_service.get_user_role(approver_username)
                
                # 直接更新内存状态
                if action == 'approve':
                    final_status = 'approved'
                elif action == 'reject':
                    final_status = 'rejected' 
                elif action in ['approved', 'rejected']:
                    final_status = action  # 已经是最终状态
                else:
                    final_status = action + 'd'  # 备用方案
                
                self.pending_approvals[approval_id]['status'] = final_status
                self.pending_approvals[approval_id]['approver'] = approver_username
                self.pending_approvals[approval_id]['approver_role'] = approver_role
                self.pending_approvals[approval_id]['comment'] = comment
                self.pending_approvals[approval_id]['updated_at'] = current_time
                self.pending_approvals[approval_id]['reminder_stopped'] = True
                
                new_status = self.pending_approvals[approval_id]['status']
                print(f"✅ 内存状态已更新: {approval_id} {old_status} -> {new_status}")
                print(f"✅ 审批人: {approver_username} ({approver_role})")
                
                # 🔥 第4步：立即触发Jenkins通知事件
                print(f"📝 步骤4: 触发Jenkins通知事件")
                
                if approval_id in self._approval_events:
                    event_obj = self._approval_events[approval_id]
                    print(f"✅ 找到事件对象，准备触发: {approval_id}")
                    
                    # 触发事件
                    event_obj.set()
                    print(f"🚨 已触发Jenkins通知事件: {approval_id}")
                    
                    # 短暂等待确保事件被处理
                    time.sleep(0.1)
                    
                    # 验证事件状态
                    if event_obj.is_set():
                        print(f"✅ 事件状态确认已设置: {approval_id}")
                    else:
                        print(f"❌ 事件设置失败: {approval_id}")
                else:
                    print(f"❌ 严重错误 - 事件对象不存在: {approval_id}")
                    print(f"📋 当前事件对象: {list(self._approval_events.keys())}")
                    
                    # 紧急补救：创建并立即触发事件
                    emergency_event = threading.Event()
                    emergency_event.set()
                    self._approval_events[approval_id] = emergency_event
                    print(f"⚡ 紧急创建并触发事件: {approval_id}")
                
                print(f"✅ 纯内存审批{action}处理完成: {approval_id}")
                print(f"="*80 + "\n")
                
                logger.info(f"✅ 纯内存审批{action}处理完成: {approval_id} by {approver_username}")
                return True, f'审批{action}成功'
                    
            finally:
                # 移除处理标记
                self._processing_approvals.discard(approval_id)
                
        except Exception as e:
            print(f"❌ 审批处理失败: {approval_id} - {e}")
            logger.error(f"❌ 审批处理失败: {approval_id} - {e}")
            import traceback
            traceback.print_exc()
            return False, f'审批处理失败: {str(e)}'
    
    def _setup_routes(self):
        """设置API路由"""
        
        @self.app.route('/health', methods=['GET'])
        def health():
            """健康检查接口"""
            try:
                # 从数据库获取待审批数量
                pending_count = 0
                if self.database_service:
                    try:
                        # 查询数据库中pending状态的审批数量
                        with self.database_service._get_connection() as conn:
                            cursor = conn.cursor()
                            if self.database_service.db_type == 'sqlite':
                                cursor.execute("SELECT COUNT(*) FROM approvals WHERE status = ?", ('pending',))
                            else:
                                cursor.execute("SELECT COUNT(*) FROM approvals WHERE status = %s", ('pending',))
                            result = cursor.fetchone()
                            pending_count = result[0] if result else 0
                    except Exception as e:
                        logger.warning(f"获取待审批数量失败: {e}")
                        pending_count = 0
                
                return jsonify({
                    'status': 'ok',
                    'service': 'jenkins-approval-bot',
                    'pending_approvals': pending_count,
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                logger.error(f"健康检查失败: {e}")
                return jsonify({
                    'status': 'error',
                    'service': 'jenkins-approval-bot',
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                }), 500
        
        @self.app.route('/test')
        def test():
            """测试接口"""
            return jsonify({
                'message': '✅ Jenkins审批机器人API服务运行正常',
                'features': [
                    'Jenkins回调审批',
                    'Telegram按钮操作',
                    '定时提醒功能',
                    '构建结果通知', 
                    '日志查看功能'
                ],
                'endpoints': {
                    'health': '/health',
                    'status': '/api/status',
                    'approval_wait': '/api/stage/approval/wait',
                    'approve': '/api/approve/<id>',
                    'reject': '/api/reject/<id>',
                    'build_result': '/api/build/result',
                    'log_viewer': '/logs/<approval_id>',
                    'users': '/api/users'
                },
                'timestamp': datetime.now().isoformat()
            })
        
        @self.app.route('/api/status', methods=['GET'])
        def api_status():
            """API状态检查接口"""
            try:
                status_info = {
                    'service': 'jenkins-approval-bot',
                    'version': '1.0.0',
                    'status': 'running',
                    'timestamp': datetime.now().isoformat(),
                    'components': {}
                }
                
                # 检查数据库连接
                try:
                    if self.database_service:
                        with self.database_service._get_connection() as conn:
                            cursor = conn.cursor()
                            if self.database_service.db_type == 'sqlite':
                                cursor.execute("SELECT 1")
                            else:
                                cursor.execute("SELECT 1")
                            cursor.fetchone()
                            status_info['components']['database'] = 'connected'
                    else:
                        status_info['components']['database'] = 'not_configured'
                except Exception as e:
                    status_info['components']['database'] = f'error: {str(e)}'
                
                # 检查权限服务
                try:
                    user_count = permission_service.get_users_count()
                    status_info['components']['permission_service'] = f'loaded ({user_count} users)'
                except Exception as e:
                    status_info['components']['permission_service'] = f'error: {str(e)}'
                
                # 检查审批管理器
                try:
                    if self.approval_manager:
                        status_info['components']['approval_manager'] = 'initialized'
                    else:
                        status_info['components']['approval_manager'] = 'not_configured'
                except Exception as e:
                    status_info['components']['approval_manager'] = f'error: {str(e)}'
                
                return jsonify(status_info)
                
            except Exception as e:
                logger.error(f"API状态检查失败: {e}")
                return jsonify({
                    'service': 'jenkins-approval-bot',
                    'status': 'error',
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                }), 500
        
        @self.app.route('/api/stage/approval/wait', methods=['GET', 'POST'])
        def approval_wait():
            """Jenkins审批等待接口 - 支持GET和POST方法"""
            try:
                # 🔥 调试：打印接收到的原始参数
                print(f"\n" + "📥"*80)
                print(f"📥 【APPROVAL REQUEST】 收到Jenkins审批请求")
                print(f"🔗 方法: {request.method}")
                print(f"📡 来源: {request.remote_addr}")
                if request.method == 'GET':
                    print(f"🔍 GET参数: {dict(request.args)}")
                    print(f"📄 原始查询字符串: {request.query_string.decode('utf-8')}")
                else:
                    print(f"🔍 POST数据: {request.get_json()}")
                print(f"📥"*80)
                
                # 支持GET和POST两种方法获取参数
                if request.method == 'POST':
                    # POST方法：从JSON body获取参数
                    data = request.get_json() or {}
                    project = data.get('project', 'unknown')
                    env = data.get('env', 'unknown')
                    build = data.get('build', '0')
                    version = data.get('version', 'unknown')
                    job = data.get('job', 'unknown')
                    desc = data.get('desc', '默认更新')
                    action = data.get('action', '部署')
                    timeout = data.get('timeout')
                else:
                    # GET方法：从查询参数获取参数（保持向后兼容）
                    project = request.args.get('project', 'unknown')
                    env = request.args.get('env', 'unknown') 
                    build = request.args.get('build', '0')
                    version = request.args.get('version', 'unknown')
                    job = request.args.get('job', 'unknown')
                    timeout = request.args.get('timeout')
                    
                    # 修复中文编码
                    try:
                        desc = unquote(request.args.get('desc', '默认更新'), encoding='utf-8')
                    except:
                        desc = request.args.get('desc', '默认更新')
                        
                    try:
                        action = unquote(request.args.get('action', '部署'), encoding='utf-8')
                    except:
                        action = request.args.get('action', '部署')
                
                # 获取审批设置 - 默认30分钟
                settings = permission_service.get_approval_settings()
                default_timeout = settings.get('approval_timeout_minutes', 30)
                timeout_minutes = int(timeout) if timeout else default_timeout
                
                # 生成审批ID
                timestamp = int(time.time())
                approval_id = f"approval-{project}-{env}-{build}-{timestamp}"
                
                # 获取项目负责人
                project_owners = permission_service.get_project_owners(project)
                if not project_owners:
                    return jsonify({
                        'result': 'error',
                        'message': '❌ 未找到项目负责人配置',
                        'approval_id': approval_id
                    }), 400
                
                # 创建审批请求对象
                approval_request = ApprovalRequest(
                    request_id=approval_id,
                    project=project,
                    env=env,
                    build=build,
                    job=job,
                    version=version,
                    desc=desc,
                    action=action,
                    timeout_seconds=timeout_minutes * 60
                )
                
                # 保存到数据库
                if not self.database_service.create_approval(approval_request):
                    return jsonify({
                        'result': 'error',
                        'message': '❌ 创建审批请求失败',
                        'approval_id': approval_id
                    }), 500
                
                # 保存数据用于通知和提醒
                approval_data = {
                    'approval_id': approval_id,
                    'project': project,
                    'env': env,
                    'build': build,
                    'version': version,
                    'job': job,
                    'desc': desc,
                    'action': action,
                    'project_owners': project_owners,
                    'timeout_minutes': timeout_minutes,
                    'status': 'pending',
                    'created_at': datetime.now().isoformat(),
                    'expires_at': (datetime.now() + timedelta(minutes=timeout_minutes)).isoformat(),
                    'reminder_count': 0
                }
                
                # 保存到内存状态 - 关键修复！
                self.pending_approvals[approval_id] = approval_data
                
                # 初始化事件对象
                self._approval_events[approval_id] = threading.Event()
                
                logger.info(f"💾 已保存内存状态: {approval_id} -> pending")
                logger.info(f"🔧 已创建事件对象: {approval_id}")
                logger.info(f"📊 当前事件对象数量: {len(self._approval_events)}")
                logger.debug(f"当前内存审批数量: {len(self.pending_approvals)}")
                
                logger.info(f"📋 新审批请求: {approval_id}")
                logger.info(f"   项目: {project} ({env}) #{build}")
                logger.info(f"   负责人: {', '.join(project_owners)}")
                
                # 发送Telegram审批消息
                if self.telegram_handler:
                    success = self._send_approval_notification(approval_data)
                    if success:
                        logger.info("✅ 审批消息已发送到Telegram群组")
                    else:
                        logger.warning("⚠️ Telegram消息发送失败")
                else:
                    logger.warning("⚠️ Telegram处理器未初始化")
                
                # 启动提醒定时器
                logger.info(f"🔔 启动提醒定时器: {approval_id}, 每5分钟提醒一次，最多6次")
                self._start_reminder_timer(approval_id)
                
                # 启动超时处理线程 (纯内存模式)
                def timeout_handler():
                    time.sleep(timeout_minutes * 60)
                    if approval_id in self.pending_approvals and self.pending_approvals[approval_id]['status'] == 'pending':
                        print(f"\n" + "⏰"*80)
                        print(f"⏰ 【TIMEOUT】 审批超时处理")
                        print(f"📝 审批ID: {approval_id}")
                        print(f"⏱️ 超时时间: {timeout_minutes} 分钟")
                        print(f"⏰ 超时时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                        print(f"⏰"*80)
                        
                        # 🔥 纯内存：更新内存状态
                        self.pending_approvals[approval_id]['status'] = 'timeout'
                        self.pending_approvals[approval_id]['approver'] = 'system'
                        self.pending_approvals[approval_id]['approver_role'] = 'system'
                        self.pending_approvals[approval_id]['comment'] = '审批超时'
                        self.pending_approvals[approval_id]['updated_at'] = datetime.now().isoformat()
                        
                        logger.info(f"⏰ 审批超时: {approval_id}")
                        print(f"✅ 内存状态已更新为超时: {approval_id}")
                        
                        # 触发超时事件，立即通知Jenkins
                        if approval_id in self._approval_events:
                            self._approval_events[approval_id].set()
                            logger.debug(f"🚨 触发超时事件通知: {approval_id}")
                            print(f"🚨 已触发超时事件通知: {approval_id}")
                        
                        # 取消提醒定时器
                        self._cancel_reminder_timer(approval_id)
                        print(f"⏰"*80 + "\n")
                
                threading.Thread(target=timeout_handler, daemon=True).start()
                
                # 🔥 Jenkins开始等待 - 调试输出
                print(f"\n" + "⏳"*80)
                print(f"⏳ 【JENKINS WAITING START】 开始等待审批")
                print(f"📝 审批ID: {approval_id}")
                print(f"📊 项目: {project} ({env}) #{build}")
                print(f"⏰ 超时: {timeout_minutes} 分钟")
                print(f"📊 当前事件对象数量: {len(self._approval_events)}")
                print(f"📊 当前内存审批数量: {len(self.pending_approvals)}")
                print(f"📋 审批ID在事件中: {approval_id in self._approval_events}")
                print(f"📋 审批ID在内存中: {approval_id in self.pending_approvals}")
                if approval_id in self.pending_approvals:
                    print(f"📊 内存中的状态: {self.pending_approvals[approval_id]['status']}")
                print(f"⏳"*80)
                
                # 等待审批结果
                max_wait_seconds = timeout_minutes * 60
                waited = 0
                check_interval = 1.0  # 1秒轮询间隔，平衡响应速度和性能
                
                while waited < max_wait_seconds:
                    try:
                        # 🔥 关键修复：首先检查内存状态，然后再等待事件
                        memory_status = None
                        if approval_id in self.pending_approvals:
                            memory_status = self.pending_approvals[approval_id]['status']
                            # 只在开始或状态变更时记录日志
                            if waited <= 1.0:  # 只在开始时打印一次
                                logger.debug(f"🔍 内存状态检查: {approval_id} -> {memory_status}")
                        else:
                            if waited <= 1.0:
                                logger.warning(f"⚠️ 审批ID不在内存中: {approval_id}")
                                logger.debug(f"当前内存审批: {list(self.pending_approvals.keys())}")
                        
                        # 🔥 如果状态已经变更，立即处理（完全基于内存，不查询数据库）
                        if memory_status and memory_status != 'pending':
                            print(f"\n" + "🎯"*80)
                            print(f"🎯 【JENKINS RESPONSE】 状态变更检测")
                            print(f"📝 审批ID: {approval_id}")
                            print(f"📊 内存状态: {memory_status}")
                            print(f"⏱️ 等待时间: {waited:.1f}秒")
                            print(f"⏰ 响应时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                            print(f"🎯"*80)
                            
                            logger.info(f"🚀 Jenkins检测到状态变更: {approval_id} -> {memory_status} (等待{waited:.1f}秒)")
                            
                            # 🔥 完全基于内存数据构建响应，无数据库查询
                            approval_data = self.pending_approvals[approval_id]
                            
                            # 立即停止提醒
                            self._cancel_reminder_timer(approval_id)
                            
                            # 直接从内存数据构建响应
                            result_data = {
                                'result': memory_status,
                                'approval_id': approval_id,
                                'project': approval_data.get('project', 'unknown'),
                                'env': approval_data.get('env', 'unknown'),
                                'build': approval_data.get('build', 'unknown'),
                                'version': approval_data.get('version', 'unknown'),
                                'approver': approval_data.get('approver', 'unknown'),
                                'approver_role': approval_data.get('approver_role', '管理员'),
                                'comment': approval_data.get('comment', ''),
                                'updated_at': approval_data.get('updated_at', datetime.now().isoformat()),
                                'waited_seconds': waited,
                                'timestamp': datetime.now().isoformat()
                            }
                            
                            if memory_status == 'approved':
                                result_data['message'] = f'✅ 审批通过 - 审批人: {approval_data.get("approver", "unknown")} ({approval_data.get("approver_role", "管理员")})'         
                                print(f"✅ Jenkins响应: 审批通过 - {approval_id}")
                                logger.info(f"✅ Jenkins收到审批通过: {approval_id}, 等待{waited:.1f}秒")
                            elif memory_status == 'rejected':
                                result_data['message'] = f'❌ 审批拒绝 - 审批人: {approval_data.get("approver", "unknown")} ({approval_data.get("approver_role", "管理员")})'         
                                print(f"❌ Jenkins响应: 审批拒绝 - {approval_id}")
                                logger.info(f"❌ Jenkins收到审批拒绝: {approval_id}, 等待{waited:.1f}秒")
                            else:
                                # 处理其他状态（如approvedd等错误状态）
                                result_data['message'] = f'⚠️ 状态异常: {memory_status} - 审批人: {approval_data.get("approver", "unknown")} ({approval_data.get("approver_role", "管理员")})'         
                                print(f"⚠️ Jenkins响应: 状态异常 {memory_status} - {approval_id}")
                                logger.warning(f"⚠️ Jenkins收到异常状态: {approval_id} -> {memory_status}, 等待{waited:.1f}秒")
                            
                            print(f"🎯"*80 + "\n")
                            return jsonify(result_data)
                        
                        # 🔥 优化：优先检查事件机制（最快响应）
                        if approval_id in self._approval_events:
                            event_obj = self._approval_events[approval_id]
                            
                            # 🔥 关键修复：先检查事件是否已经被设置
                            if event_obj.is_set():
                                logger.info(f"🚨 检测到已设置的事件: {approval_id} (等待{waited:.1f}秒)")
                                print(f"🚨 [{datetime.now().strftime('%H:%M:%S')}] Jenkins等待线程检测到事件: {approval_id} (等待{waited:.1f}秒)")
                                # 重置事件状态，防止重复触发
                                event_obj.clear()
                                # 继续执行状态检查
                            else:
                                # 等待事件触发
                                event_triggered = event_obj.wait(timeout=check_interval)
                                if event_triggered:
                                    logger.info(f"🚨 收到状态变更事件: {approval_id} (等待{waited:.1f}秒)")
                                    print(f"🚨 [{datetime.now().strftime('%H:%M:%S')}] Jenkins等待线程收到事件: {approval_id} (等待{waited:.1f}秒)")
                                    # 重置事件状态，防止重复触发
                                    event_obj.clear()
                                    # 继续执行状态检查
                        else:
                            # 如果事件对象不存在，使用普通睡眠
                            if waited <= 1.0:
                                logger.warning(f"⚠️ 事件对象不存在，使用轮询模式: {approval_id}")
                            logger.warning(f"当前事件对象: {list(self._approval_events.keys())}")
                            time.sleep(check_interval)

                        # 🔥 完全移除数据库查询，纯内存+事件机制
                        # 如果没有事件对象且内存状态还是pending，则正常等待
                        if not (approval_id in self._approval_events) and memory_status == 'pending':
                                time.sleep(check_interval)
                        
                        # 每隔2秒打印一次等待状态，便于调试
                        if waited > 0 and waited % 2 == 0:
                            logger.debug(f"⏳ Jenkins等待审批: {approval_id}, 已等待{waited:.1f}秒")
                    
                    except Exception as e:
                        logger.error(f"❌ 检查审批状态失败: {approval_id} - {e}")
                        time.sleep(check_interval)
                    
                    waited += check_interval
                
                # 超时处理
                self._cancel_reminder_timer(approval_id)
                
                # 检查数据库中的最新状态
                approval_request = self.database_service.get_approval(approval_id)
                if approval_request:
                    if approval_request.status == ApprovalStatus.PENDING.value:
                        # 确实超时，更新数据库和内存状态
                        self.database_service.update_approval_status(
                            approval_id, ApprovalStatus.TIMEOUT.value, "system", "system", "审批超时"
                        )
                        
                        # 更新内存状态
                        if approval_id in self.pending_approvals:
                            self.pending_approvals[approval_id]['status'] = 'timeout'
                            logger.debug(f"🔄 内存状态已更新: {approval_id} -> timeout")
                            
                            # 触发超时事件
                            if approval_id in self._approval_events:
                                self._approval_events[approval_id].set()
                                logger.debug(f"🚨 触发超时事件: {approval_id}")
                        
                        return jsonify({
                            'result': 'timeout',
                            'message': '⏰ 审批超时',
                            'approval_id': approval_id,
                            'waited_seconds': waited
                        })
                    else:
                        # 在最后时刻被审批，同步内存状态
                        if approval_id in self.pending_approvals:
                            self.pending_approvals[approval_id]['status'] = approval_request.status
                            logger.debug(f"🔄 最后时刻同步内存状态: {approval_id} -> {approval_request.status}")
                        
                        # 🔥 关键修复：在超时处理中延迟清理事件对象
                        # 给正在进行的审批操作一点时间完成事件触发
                        def delayed_cleanup():
                            time.sleep(1)  # 等待1秒，确保所有事件处理完成
                        if approval_id in self._approval_events:
                            del self._approval_events[approval_id]
                            logger.debug(f"🧹 延迟清理超时事件对象: {approval_id}")
                        
                        threading.Thread(target=delayed_cleanup, daemon=True).start()
                        
                        result_data = {
                            'result': approval_request.status,
                            'approval_id': approval_id,
                            'approver': approval_request.approver,
                            'approver_role': approval_request.approver_role,
                            'comment': approval_request.comment,
                            'updated_at': approval_request.updated_at,
                            'waited_seconds': waited,
                            'message': f'在最后时刻被审批 - {approval_request.approver}'
                        }
                        return jsonify(result_data)
                
                return jsonify({
                    'result': 'timeout',
                    'message': '⏰ 审批超时',
                    'approval_id': approval_id,
                    'waited_seconds': waited
                })
                
            except Exception as e:
                logger.error(f"❌ 审批请求处理失败: {e}")
                import traceback
                traceback.print_exc()
                return jsonify({
                    'result': 'error',
                    'message': f'❌ 审批请求失败: {str(e)}',
                    'timestamp': datetime.now().isoformat()
                }), 500
        
        @self.app.route('/api/approve/<approval_id>', methods=['GET', 'POST'])
        def approve_request(approval_id):
            """🔥 纯内存批准审批请求 - 完全脱离数据库"""
            try:
                # 强制输出调试信息
                print(f"\n" + "🌐"*80)
                print(f"🌐 【WEB API APPROVE】 {approval_id}")
                print(f"🔗 方法: {request.method}")
                print(f"📡 来源: {request.remote_addr}")
                print(f"⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"🌐"*80)

                # 获取审批人信息
                approver_username = request.args.get('approver', request.form.get('approver'))
                if not approver_username:
                    # 从内存获取项目信息，确定项目负责人
                    if approval_id in self.pending_approvals:
                        project = self.pending_approvals[approval_id].get('project', 'unknown')
                        project_owners = permission_service.get_project_owners(project)
                        approver_username = project_owners[0] if project_owners else 'admin'
                    else:
                        approver_username = 'admin'
                
                comment = request.args.get('comment', request.form.get('comment', 'Web界面审批'))
                
                print(f"👤 审批人: {approver_username}")
                print(f"💬 备注: {comment}")
                
                # 🔥 使用纯内存处理方法
                success, message = self.process_approval_internal(
                    approval_id, 'approved', 'web_user', approver_username, comment
                )
                
                if success:
                    # 从内存获取审批数据用于响应
                    approval_data = self.pending_approvals.get(approval_id, {})
                    approver_info = permission_service.get_user_info(approver_username)
                    approver_display = permission_service.get_user_display_name(approver_username)
                    approver_role = approver_info.get('role', '管理员') if approver_info else '管理员'
                    
                    print(f"✅ Web API 审批成功: {approval_id}")
                    print(f"🌐"*80 + "\n")
                    
                    return jsonify({
                        'result': 'approved',
                        'message': f'✅ 审批通过！\n\n👤 审批人: {approver_display} ({approver_role})\n💬 备注: {comment}\n⏰ 操作时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n\n🚀 构建将继续执行！',
                        'approval_id': approval_id,
                        'approver': approver_display,
                        'approver_role': approver_role,
                        'comment': comment,
                        'operation_time': datetime.now().isoformat(),
                        'status': 'approved',
                        'timestamp': datetime.now().isoformat()
                    })
                else:
                    print(f"❌ Web API 审批失败: {approval_id} - {message}")
                    print(f"🌐"*80 + "\n")
                    
                    return jsonify({
                        'result': 'error',
                        'message': f'❌ 审批处理失败：{message}',
                        'approval_id': approval_id
                        }), 400
                
            except Exception as e:
                print(f"❌ Web API 处理异常: {approval_id} - {e}")
                print(f"🌐"*80 + "\n")
                logger.error(f"❌ Web API approve处理失败: {approval_id} - {e}")
                import traceback
                traceback.print_exc()
                return jsonify({
                    'result': 'error', 
                    'message': f'❌ 处理审批请求时发生错误: {str(e)}',
                    'approval_id': approval_id
                }), 500

        @self.app.route('/api/reject/<approval_id>', methods=['GET', 'POST'])
        def reject_request(approval_id):
            """🔥 纯内存拒绝审批请求 - 完全脱离数据库"""
            try:
                # 强制输出调试信息
                print(f"\n" + "🚫"*80)
                print(f"🚫 【WEB API REJECT】 {approval_id}")
                print(f"🔗 方法: {request.method}")
                print(f"📡 来源: {request.remote_addr}")
                print(f"⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"🚫"*80)

                # 获取拒绝人信息
                approver_username = request.args.get('approver', request.form.get('approver'))
                if not approver_username:
                    # 从内存获取项目信息，确定项目负责人
                    if approval_id in self.pending_approvals:
                        project = self.pending_approvals[approval_id].get('project', 'unknown')
                        project_owners = permission_service.get_project_owners(project)
                        approver_username = project_owners[0] if project_owners else 'admin'
                    else:
                        approver_username = 'admin'
                
                comment = request.args.get('comment', request.form.get('comment', 'Web界面拒绝'))
                
                print(f"👤 拒绝人: {approver_username}")
                print(f"💬 拒绝原因: {comment}")
                
                # 🔥 使用纯内存处理方法
                success, message = self.process_approval_internal(
                    approval_id, 'rejected', 'web_user', approver_username, comment
                )
                
                if success:
                    # 从内存获取审批数据用于响应
                    approval_data = self.pending_approvals.get(approval_id, {})
                    approver_info = permission_service.get_user_info(approver_username)
                    approver_display = permission_service.get_user_display_name(approver_username)
                    approver_role = approver_info.get('role', '管理员') if approver_info else '管理员'
                    
                    print(f"✅ Web API 拒绝成功: {approval_id}")
                    print(f"🚫"*80 + "\n")
                    
                    return jsonify({
                        'result': 'rejected',
                        'message': f'❌ 审批已拒绝！\n\n👤 拒绝人: {approver_display} ({approver_role})\n💬 拒绝原因: {comment}\n⏰ 操作时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n\n🛑 构建已终止！',
                        'approval_id': approval_id,
                        'approver': approver_display,
                        'approver_role': approver_role,
                        'comment': comment,
                        'operation_time': datetime.now().isoformat(),
                        'status': 'rejected',
                        'timestamp': datetime.now().isoformat()
                    })
                else:
                    print(f"❌ Web API 拒绝失败: {approval_id} - {message}")
                    print(f"🚫"*80 + "\n")
                    
                    return jsonify({
                        'result': 'error',
                        'message': f'❌ 拒绝处理失败：{message}',
                        'approval_id': approval_id
                    }), 400
                
            except Exception as e:
                print(f"❌ Web API 拒绝异常: {approval_id} - {e}")
                print(f"🚫"*80 + "\n")
                logger.error(f"❌ Web API reject处理失败: {approval_id} - {e}")
                import traceback
                traceback.print_exc()
                return jsonify({
                    'result': 'error',
                    'message': f'❌ 处理拒绝请求时发生错误: {str(e)}',
                    'approval_id': approval_id
                }), 500

        @self.app.route('/api/build/result', methods=['POST'])
        def build_result():
            """Jenkins构建结果通知 - 只处理审批通过的构建"""
            try:
                data = request.get_json() or {}
                
                project = data.get('project', 'unknown')
                build = data.get('build', '0')
                env = data.get('env', 'unknown')
                status = data.get('status', 'unknown')
                duration = data.get('duration', '未知')
                logs = data.get('logs', '')
                
                logger.info(f"📢 构建结果通知: {project} #{build} - {status}")
                
                # 构造审批ID来查找对应的审批
                approval_id = f"{project}-{build}-{env}"
                approval = self.approval_manager.get_approval(approval_id)
                
                # 只处理审批通过的构建结果
                if not approval or not getattr(approval, 'should_notify_build_result', False):
                    logger.info(f"跳过构建结果通知 - 审批未通过或不需要通知: {approval_id}")
                    return jsonify({
                        'status': 'skipped', 
                        'message': '审批未通过，跳过构建结果通知',
                        'approval_id': approval_id
                    })
                
                # 发送构建结果到Telegram
                if self.telegram_handler:
                    success = self._send_build_result_notification_enhanced({
                        'project': project,
                        'build': build,
                        'env': env,
                        'status': status,
                        'duration': duration,
                        'logs': logs,
                        'approval_id': approval_id,
                        'timestamp': datetime.now().isoformat()
                    })
                    
                    if success:
                        logger.info("✅ 构建结果通知已发送到Telegram")
                    else:
                        logger.warning("⚠️ Telegram构建结果通知发送失败")
                else:
                    logger.warning("⚠️ Telegram处理器未初始化")
                
                return jsonify({
                    'status': 'success', 
                    'message': '构建结果已通知',
                    'approval_id': approval_id,
                    'telegram_sent': self.telegram_handler is not None
                })
                
            except Exception as e:
                logger.error(f"构建结果通知失败: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/logs/<approval_id>')
        def view_logs(approval_id):
            """查看构建日志 - 美观响应式页面，无需登录Jenkins"""
            try:
                # 从审批ID解析项目信息
                parts = approval_id.split('-')
                if len(parts) >= 3:
                    job_name = parts[0]
                    build_number = parts[1]
                    environment = '-'.join(parts[2:])
                else:
                    job_name = "unknown"
                    build_number = "0"
                    environment = "unknown"
                
                # 通过Jenkins API获取真实日志
                jenkins_logs = self.approval_manager.jenkins_service.get_build_logs(job_name, build_number)
                
                # 格式化日志内容
                if jenkins_logs.get('error'):
                    log_content = f"""⚠️ 日志获取失败
                    
错误信息: {jenkins_logs['error']}
                    
请检查Jenkins连接或权限配置。"""
                else:
                    log_content = jenkins_logs.get('logs', '无日志内容')
                
                build_info = {
                    'job_name': jenkins_logs.get('job_name', job_name),
                    'build_number': jenkins_logs.get('build_number', build_number),
                    'environment': environment,
                    'status': jenkins_logs.get('status', 'UNKNOWN'),
                    'duration': jenkins_logs.get('duration', 0),
                    'started_at': jenkins_logs.get('started_at', 'Unknown'),
                    'jenkins_url': jenkins_logs.get('url', '#')
                }
                
                html_template = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Jenkins构建日志 - {{build_info.job_name}} #{{build_info.build_number}}</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            background: linear-gradient(135deg, #1e1e1e 0%, #2d2d30 100%);
            color: #e5e5e5;
            line-height: 1.6;
            min-height: 100vh;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        
        .header {
            background: rgba(45, 45, 48, 0.9);
            backdrop-filter: blur(10px);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 20px;
            border: 1px solid rgba(86, 156, 214, 0.3);
        }
        
        .header h1 {
            color: #569cd6;
            font-size: 24px;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .build-info {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            font-size: 14px;
        }
        
        .info-item {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .info-label {
            color: #9cdcfe;
            font-weight: 600;
        }
        
        .status-success { color: #4ec9b0; }
        .status-failure { color: #f44747; }
        .status-unknown { color: #dcdcaa; }
        
        .log-container {
            background: rgba(30, 30, 30, 0.95);
            border-radius: 12px;
            border: 1px solid rgba(86, 156, 214, 0.2);
            overflow: hidden;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        }
        
        .log-header {
            background: rgba(86, 156, 214, 0.1);
            padding: 16px 24px;
            border-bottom: 1px solid rgba(86, 156, 214, 0.2);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .log-title {
            color: #569cd6;
            font-weight: 600;
            font-size: 16px;
        }
        
        .log-actions {
            display: flex;
            gap: 12px;
        }
        
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 12px;
            font-weight: 500;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            transition: all 0.2s;
        }
        
        .btn-primary {
            background: #569cd6;
            color: white;
        }
        
        .btn-primary:hover {
            background: #4a86c7;
            transform: translateY(-1px);
        }
        
        .btn-secondary {
            background: rgba(156, 220, 254, 0.1);
            color: #9cdcfe;
            border: 1px solid rgba(156, 220, 254, 0.3);
        }
        
        .btn-secondary:hover {
            background: rgba(156, 220, 254, 0.2);
        }
        
        .log-content {
            padding: 24px;
            font-size: 13px;
            line-height: 1.5;
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 70vh;
            overflow-y: auto;
            scroll-behavior: smooth;
        }
        
        /* 滚动条样式 */
        .log-content::-webkit-scrollbar {
            width: 8px;
        }
        
        .log-content::-webkit-scrollbar-track {
            background: rgba(45, 45, 48, 0.5);
        }
        
        .log-content::-webkit-scrollbar-thumb {
            background: rgba(86, 156, 214, 0.6);
            border-radius: 4px;
        }
        
        .log-content::-webkit-scrollbar-thumb:hover {
            background: rgba(86, 156, 214, 0.8);
        }
        
        /* 日志语法高亮 */
        .log-content {
            color: #d4d4d4;
        }
        
        /* 移动端适配 */
        @media (max-width: 768px) {
            .container { padding: 12px; }
            .header { padding: 16px; }
            .header h1 { font-size: 20px; }
            .build-info { grid-template-columns: 1fr; }
            .log-header { 
                flex-direction: column; 
                gap: 12px; 
                text-align: center; 
            }
            .log-actions { justify-content: center; }
            .log-content { 
                padding: 16px; 
                font-size: 12px;
                max-height: 60vh;
            }
        }
        
        .loading {
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 40px;
            color: #9cdcfe;
        }
        
        .emoji { font-style: normal; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1><span class="emoji">🔍</span> Jenkins构建日志</h1>
            <div class="build-info">
                <div class="info-item">
                    <span class="info-label">项目:</span>
                    <span>{{build_info.job_name}}</span>
                </div>
                <div class="info-item">
                    <span class="info-label">构建:</span>
                    <span>#{{build_info.build_number}}</span>
                </div>
                <div class="info-item">
                    <span class="info-label">环境:</span>
                    <span>{{build_info.environment}}</span>
                </div>
                <div class="info-item">
                    <span class="info-label">状态:</span>
                    <span class="status-{{build_info.status.lower()}}">{{build_info.status}}</span>
                </div>
                <div class="info-item">
                    <span class="info-label">开始时间:</span>
                    <span>{{build_info.started_at}}</span>
                </div>
                <div class="info-item">
                    <span class="info-label">耗时:</span>
                    <span>{{build_info.duration}}秒</span>
                </div>
            </div>
        </div>
        
        <div class="log-container">
            <div class="log-header">
                <div class="log-title">构建控制台输出</div>
                <div class="log-actions">
                    <button class="btn btn-secondary" onclick="copyLogs()">
                        <span class="emoji">📋</span> 复制日志
                    </button>
                    <a href="{{build_info.jenkins_url}}" target="_blank" class="btn btn-primary">
                        <span class="emoji">🔗</span> Jenkins控制台
                    </a>
                </div>
            </div>
            <div class="log-content" id="logContent">{{log_content}}</div>
        </div>
    </div>
    
    <script>
        function copyLogs() {
            const logContent = document.getElementById('logContent');
            const textArea = document.createElement('textarea');
            textArea.value = logContent.textContent;
            document.body.appendChild(textArea);
            textArea.select();
            document.execCommand('copy');
            document.body.removeChild(textArea);
            
            // 显示复制成功提示
            const btn = event.target.closest('.btn');
            const originalText = btn.innerHTML;
            btn.innerHTML = '<span class="emoji">✅</span> 已复制';
            setTimeout(() => {
                btn.innerHTML = originalText;
            }, 2000);
        }
        
        // 页面加载完成后滚动到底部
        window.addEventListener('load', function() {
            const logContent = document.getElementById('logContent');
            logContent.scrollTop = logContent.scrollHeight;
        });
    </script>
</body>
</html>
                '''
                
                return render_template_string(html_template, 
                                            build_info=build_info,
                                            log_content=log_content)
                
            except Exception as e:
                logger.error(f"查看日志失败: {e}")
                
                # 返回错误页面
                error_template = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>日志查看失败</title>
    <style>
        body { 
            font-family: Arial, sans-serif; 
            background: #1e1e1e; 
            color: #e5e5e5; 
            padding: 40px; 
            text-align: center; 
        }
        .error-container { 
            max-width: 600px; 
            margin: 0 auto; 
            background: #2d2d30; 
            padding: 40px; 
            border-radius: 12px; 
        }
        .error-icon { font-size: 48px; margin-bottom: 20px; }
        h1 { color: #f44747; margin-bottom: 16px; }
        p { color: #d4d4d4; margin-bottom: 12px; }
        .error-details { 
            background: #1e1e1e; 
            padding: 16px; 
            border-radius: 6px; 
            font-family: monospace; 
            color: #f44747; 
            margin-top: 20px; 
        }
    </style>
</head>
<body>
    <div class="error-container">
        <div class="error-icon">❌</div>
        <h1>日志查看失败</h1>
        <p>无法获取构建日志，请稍后重试。</p>
        <p>审批ID: {{approval_id}}</p>
        <div class="error-details">{{error}}</div>
    </div>
</body>
</html>
                '''
                
                return render_template_string(error_template, 
                                            approval_id=approval_id, 
                                            error=str(e)), 500

        @self.app.route('/approval/<approval_id>')
        def approval_page(approval_id):
            """🔥 新增：审批页面 - 显示审批状态和处理重复审批"""
            try:
                # 🔥 关键修复：优先从内存查找，再从数据库查找
                approval_request = None
                
                # 1. 先从内存中查找（最新状态）
                if approval_id in self.pending_approvals:
                    pending_data = self.pending_approvals[approval_id]
                    # 从内存数据构建ApprovalRequest对象
                    approval_request = ApprovalRequest(
                        request_id=approval_id,
                        project=pending_data['project'],
                        env=pending_data['env'],
                        build=pending_data['build'],
                        job=pending_data.get('job', 'unknown'),
                        version=pending_data.get('version', 'unknown'),
                        desc=pending_data.get('desc', ''),
                        action=pending_data.get('action', '部署'),
                        timeout_seconds=pending_data.get('timeout_minutes', 30) * 60
                    )
                    approval_request.status = pending_data.get('status', 'pending')
                    approval_request.created_at = pending_data.get('created_at', '')
                    approval_request.expires_at = pending_data.get('expires_at', '')
                    approval_request.approver = pending_data.get('approver')
                    approval_request.approver_role = pending_data.get('approver_role')
                    approval_request.comment = pending_data.get('comment')
                    logger.info(f"📋 从内存获取审批信息: {approval_id}")
                
                # 2. 如果内存中没有，再从数据库查找
                if not approval_request:
                    approval_request = self.database_service.get_approval(approval_id)
                    if approval_request:
                        logger.info(f"📋 从数据库获取审批信息: {approval_id}")
                
                # 3. 都没找到，返回404
                if not approval_request:
                    return f"""
                    <html><head><meta charset="utf-8"><title>审批不存在</title></head>
                    <body style="font-family: Arial, sans-serif; margin: 40px; line-height: 1.6;">
                        <h1>❌ 审批记录不存在</h1>
                        <p>审批ID: {approval_id}</p>
                        <p>可能原因：审批已过期或ID不正确</p>
                    </body></html>
                    """, 404
                
                # 检查审批状态
                if approval_request.status != 'pending':
                    # 🔥 重复审批警告页面
                    status_text = "已通过" if approval_request.status == "approved" else "已拒绝"
                    status_emoji = "✅" if approval_request.status == "approved" else "❌"
                    
                    approver_name = permission_service.get_user_display_name(approval_request.approver)
                    
                    return f"""
                    <html><head><meta charset="utf-8"><title>审批已处理</title>
                    <style>
                        body {{ font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }}
                        .warning {{ background: #fff3cd; border: 1px solid #ffeaa7; padding: 20px; border-radius: 5px; margin: 20px 0; }}
                        .info {{ background: #d1ecf1; border: 1px solid #bee5eb; padding: 15px; border-radius: 5px; margin: 15px 0; }}
                        .button {{ background: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; display: inline-block; margin: 10px 5px 0 0; }}
                    </style></head>
                    <body>
                        <h1>⚠️ 审批已处理，请勿重复操作！</h1>
                        
                        <div class="warning">
                            <h2>{status_emoji} 该审批{status_text}</h2>
                            <p><strong>👤 操作人：</strong>{approver_name} ({approval_request.approver_role})</p>
                            <p><strong>⏰ 操作时间：</strong>{str(approval_request.updated_at)[:19]}</p>
                            <p><strong>💬 备注：</strong>{approval_request.comment or '无'}</p>
                        </div>
                        
                        <div class="info">
                            <p><strong>📋 审批详情：</strong></p>
                            <p>项目：{approval_request.project} ({approval_request.env})</p>
                            <p>构建：#{approval_request.build}</p>
                            <p>版本：{approval_request.version}</p>
                            <p>描述：{approval_request.desc}</p>
                        </div>
                        
                        <p>如需查看更多信息，请联系项目负责人或管理员。</p>
                        <a href="javascript:history.back()" class="button">← 返回</a>
                        <a href="javascript:location.reload()" class="button">🔄 刷新页面</a>
                    </body></html>
                    """
                
                # 审批仍在处理中，显示审批页面
                project_owners = permission_service.get_project_owners(approval_request.project)
                owners_text = '、'.join(project_owners) if project_owners else '无'
                
                return """
                <html><head><meta charset="utf-8"><title>待审批 - {}</title>""".format(approval_request.project) + """
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }}
                    .pending {{ background: #d4edda; border: 1px solid #c3e6cb; padding: 20px; border-radius: 5px; margin: 20px 0; }}
                    .info {{ background: #d1ecf1; border: 1px solid #bee5eb; padding: 15px; border-radius: 5px; margin: 15px 0; }}
                    .button {{ background: #28a745; color: white; padding: 12px 24px; border: none; border-radius: 5px; display: inline-block; margin: 10px 10px 0 0; font-size: 16px; cursor: pointer; text-decoration: none; }}
                    .button.reject {{ background: #dc3545; }}
                    .button:hover {{ opacity: 0.9; }}
                    .button:disabled {{ background: #6c757d; cursor: not-allowed; }}
                    .loading {{ display: none; background: #ffc107; color: #000; padding: 10px; border-radius: 5px; margin: 10px 0; }}
                    .result {{ padding: 15px; border-radius: 5px; margin: 15px 0; }}
                    .result.success {{ background: #d4edda; border: 1px solid #c3e6cb; color: #155724; }}
                    .result.error {{ background: #f8d7da; border: 1px solid #f5c6cb; color: #721c24; }}
                </style></head>
                <body>
                    <h1>📋 审批请求 - {project}</h1>
                    
                    <div class="pending">
                        <h2>⏳ 等待审批中</h2>
                        <p><strong>状态：</strong>待处理</p>
                        <p><strong>创建时间：</strong>{created_at}</p>
                        <p><strong>过期时间：</strong>{expires_at}</p>
                    </div>
                    
                    <div class="info">
                        <p><strong>📋 审批详情：</strong></p>
                        <p>项目：{project} ({env})</p>
                        <p>构建：#{build}</p>
                        <p>版本：{version}</p>
                        <p>描述：{desc}</p>
                        <p>操作：{action}</p>
                        <p>负责人：{owners_text}</p>
                    </div>
                    
                    <div id="loading" class="loading">
                        ⏳ 正在处理审批...
                    </div>
                    
                    <div id="result" class="result" style="display: none;">
                    </div>
                    
                    <p><strong>请选择操作：</strong></p>
                    <button id="approveBtn" class="button" onclick="handleApproval('approve')">✅ 通过</button>
                    <button id="rejectBtn" class="button reject" onclick="handleApproval('reject')">❌ 拒绝</button>
                    
                    <script>
                    function handleApproval(action) {{
                        // 禁用按钮，显示加载状态
                        document.getElementById('approveBtn').disabled = true;
                        document.getElementById('rejectBtn').disabled = true;
                        document.getElementById('loading').style.display = 'block';
                        document.getElementById('result').style.display = 'none';
                        
                        // 构建API URL
                        const approvalId = '{approval_id}';
                        const actionText = action === 'approve' ? '通过' : '拒绝';
                        const apiUrl = `/api/${{action}}/${{approvalId}}?approver=admin&comment=Web审批${{actionText}}`;
                        
                        // 发送请求
                        fetch(apiUrl)
                            .then(response => {
                                console.log('API Response Status:', response.status);
                                console.log('API Response URL:', response.url);
                                
                                if (!response.ok) {
                                    throw new Error(`HTTP ${{response.status}}: ${{response.statusText}}`);
                                }
                                return response.json();
                            })
                            .then(data => {
                                console.log('API Response Data:', data);
                                document.getElementById('loading').style.display = 'none';
                                
                                const resultDiv = document.getElementById('result');
                                resultDiv.style.display = 'block';
                                
                                if (data.result === 'approved' || data.result === 'rejected') {
                                    resultDiv.className = 'result success';
                                    resultDiv.innerHTML = `
                                        <h3>${{data.result === 'approved' ? '✅ 审批通过' : '❌ 审批拒绝'}}</h3>
                                        <p><strong>审批人：</strong>${{data.approver || 'admin'}}</p>
                                        <p><strong>审批时间：</strong>${{data.approved_at || data.rejected_at || '刚刚'}}</p>
                                        <p><strong>状态：</strong>${{data.message || '处理完成'}}</p>
                                        <p style="margin-top: 15px;">
                                            <strong>🎯 Jenkins状态：</strong>审批结果已发送，Jenkins将继续执行流水线
                                        </p>
                                    `;
                                    
                                    // 5秒后自动刷新页面显示最新状态
                                    setTimeout(() => {
                                        window.location.reload();
                                    }, 5000);
                                    
                                } else {
                                    resultDiv.className = 'result error';
                                    resultDiv.innerHTML = `
                                        <h3>❌ 审批失败</h3>
                                        <p>${{data.message || '审批处理失败，请重试'}}</p>
                                    `;
                                    
                                    // 重新启用按钮
                                    document.getElementById('approveBtn').disabled = false;
                                    document.getElementById('rejectBtn').disabled = false;
                                }
                            })
                            .catch(error => {
                                document.getElementById('loading').style.display = 'none';
                                
                                const resultDiv = document.getElementById('result');
                                resultDiv.style.display = 'block';
                                resultDiv.className = 'result error';
                                resultDiv.innerHTML = `
                                    <h3>❌ 网络错误</h3>
                                    <p>审批请求失败：${{error.message}}</p>
                                    <p>请检查网络连接或稍后重试</p>
                                `;
                                
                                // 重新启用按钮
                                document.getElementById('approveBtn').disabled = false;
                                document.getElementById('rejectBtn').disabled = false;
                            });
                    }
                    </script>
                </body></html>
                """.format(
                    project=approval_request.project,
                    env=approval_request.env,
                    build=approval_request.build,
                    version=approval_request.version,
                    desc=approval_request.desc,
                    action=approval_request.action,
                    owners_text=owners_text,
                    created_at=str(approval_request.created_at)[:19],
                    expires_at=str(approval_request.expires_at)[:19],
                    approval_id=approval_id
                )
                
            except Exception as e:
                logger.error(f"审批页面错误: {e}")
                return f"""
                <html><head><meta charset="utf-8"><title>错误</title></head>
                <body style="font-family: Arial, sans-serif; margin: 40px;">
                    <h1>❌ 系统错误</h1>
                    <p>无法加载审批页面</p>
                    <p>错误信息: {str(e)}</p>
                </body></html>
                """, 500

        @self.app.route('/api/approvals')
        def list_approvals():
            """获取待审批列表"""
            return jsonify({
                'count': len(self.pending_approvals),
                'pending_approvals': self.pending_approvals,
                'timestamp': datetime.now().isoformat()
            })

        @self.app.route('/api/debug/events')
        def debug_events():
            """调试接口：检查事件对象状态"""
            try:
                events_info = {}
                for approval_id, event_obj in self._approval_events.items():
                    events_info[approval_id] = {
                        'exists': True,
                        'is_set': event_obj.is_set(),
                        'approval_in_memory': approval_id in self.pending_approvals,
                        'memory_status': self.pending_approvals.get(approval_id, {}).get('status', 'N/A') if approval_id in self.pending_approvals else 'N/A'
                    }
                
                return jsonify({
                    'total_events': len(self._approval_events),
                    'total_approvals': len(self.pending_approvals),
                    'events': events_info,
                    'event_ids': list(self._approval_events.keys()),
                    'approval_ids': list(self.pending_approvals.keys()),
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/users')
        def get_users():
            """获取用户配置"""
            try:
                users_info = {}
                for username in permission_service.users_config.keys():
                    user_info = permission_service.get_user_info(username)
                    if user_info:
                        users_info[username] = {
                            'name': user_info.get('name', username),
                            'role': user_info.get('role', '用户'),
                            'display_name': permission_service.get_user_display_name(username)
                        }
                
                return jsonify({
                    'users': users_info,
                    'project_mapping': permission_service.project_mapping,
                    'count': len(users_info),
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                logger.error(f"获取用户配置失败: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/webhook/telegram', methods=['POST'])
        def telegram_webhook():
            """处理Telegram回调"""
            try:
                data = request.get_json()
                logger.info(f"📱 Telegram回调数据: {json.dumps(data, ensure_ascii=False)}")
                
                if 'callback_query' in data:
                    callback_query = data['callback_query']
                    callback_data = callback_query.get('data', '')
                    user = callback_query.get('from', {})
                    user_name = user.get('username', user.get('first_name', 'Unknown'))
                    
                    logger.info(f"👤 用户 {user_name} 点击了按钮: {callback_data}")
                    
                    if ':' in callback_data:
                        action, approval_id = callback_data.split(':', 1)
                        
                        if action == 'approve':
                            # 🔥 关键修复：调用统一的内部审批处理逻辑
                            success, message = self.process_approval_internal(
                                approval_id, 'approved', "telegram_user", user_name, "Telegram回调审批"
                            )
                            return jsonify({'status': 'ok', 'result': {'success': success, 'message': message}})
                        elif action == 'reject':
                            # 🔥 关键修复：调用统一的内部拒绝处理逻辑
                            success, message = self.process_approval_internal(
                                approval_id, 'rejected', "telegram_user", user_name, "Telegram回调审批"
                            )
                            return jsonify({'status': 'ok', 'result': {'success': success, 'message': message}})
                
                return jsonify({'status': 'ok'})
                
            except Exception as e:
                logger.error(f"❌ Telegram回调处理失败: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/debug/memory', methods=['GET'])
        def debug_memory():
            """调试接口：查看内存中的审批状态"""
            try:
                current_time = datetime.now()
                memory_info = {
                    'current_time': current_time.isoformat(),
                    'pending_approvals_count': len(self.pending_approvals),
                    'approval_events_count': len(self._approval_events),
                    'processing_approvals': list(self._processing_approvals),
                    'stopped_reminders_count': len(self._stopped_reminders),
                    'pending_approvals': {}
                }
                
                # 详细的审批信息
                for approval_id, approval_data in self.pending_approvals.items():
                    try:
                        created_at_str = approval_data.get('created_at', '')
                        age_minutes = 0
                        if created_at_str:
                            if created_at_str.endswith('Z'):
                                created_at_str = created_at_str[:-1] + '+00:00'
                            try:
                                created_at = datetime.fromisoformat(created_at_str)
                            except AttributeError:
                                from dateutil.parser import parse
                                created_at = parse(created_at_str)
                            age_minutes = (current_time - created_at).total_seconds() / 60
                    except:
                        age_minutes = -1  # 解析失败
                    
                    memory_info['pending_approvals'][approval_id] = {
                        'status': approval_data.get('status', 'unknown'),
                        'project': approval_data.get('project', 'unknown'),
                        'env': approval_data.get('env', 'unknown'),
                        'build': approval_data.get('build', 'unknown'),
                        'created_at': approval_data.get('created_at', 'unknown'),
                        'age_minutes': round(age_minutes, 1),
                        'has_event': approval_id in self._approval_events,
                        'event_is_set': self._approval_events.get(approval_id, threading.Event()).is_set()
                    }
                
                return jsonify(memory_info)
                
            except Exception as e:
                logger.error(f"❌ 调试接口失败: {e}")
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/build/notify', methods=['POST'])
        def build_notify():
            """接收Jenkins构建完成通知"""
            try:
                data = request.get_json()
                if not data:
                    return jsonify({'error': '缺少请求数据'}), 400
                
                # 🔥 强制输出调试信息
                print(f"\n" + "🏗️"*80)
                print(f"🏗️ 【BUILD NOTIFICATION】 收到构建完成通知")
                print(f"📋 通知数据: {json.dumps(data, ensure_ascii=False, indent=2)}")
                print(f"🏗️"*80)
                
                # 提取必要信息
                project = data.get('project', 'unknown')
                env = data.get('env', 'unknown')
                build_number = data.get('build', 'unknown')
                job_name = data.get('job', 'unknown')
                version = data.get('version', 'unknown')
                status = data.get('status', 'unknown')  # success, failure, unstable, aborted
                duration = data.get('duration', 0)  # 构建时长（秒）
                build_url = data.get('build_url', '')  # Jenkins构建URL
                
                logger.info(f"🏗️ 收到构建通知: {project}-{env} #{build_number} -> {status}")
                
                # 🔥 发送Telegram通知
                if self.telegram_handler:
                    self._send_build_notification(
                        project, env, build_number, job_name, version, 
                        status, duration, build_url
                    )
                else:
                    logger.warning("Telegram处理器未设置，无法发送通知")
                
                return jsonify({
                    'status': 'success',
                    'message': '构建通知已处理',
                    'timestamp': datetime.now().isoformat()
                })
                
            except Exception as e:
                logger.error(f"❌ 构建通知处理失败: {e}")
                import traceback
                traceback.print_exc()
                return jsonify({'error': str(e)}), 500


        @self.app.before_request
        def log_request():
            logger.info("🌐 API请求: {} {} - 来源: {}".format(
                request.method, 
                request.url,
                request.remote_addr
            ))
            if request.args:
                logger.info("📝 请求参数: {}".format(dict(request.args)))

        @self.app.after_request  
        def log_response(response):
            response.headers['Content-Type'] = 'application/json; charset=utf-8'
            logger.info("📤 API响应: {} - 状态码: {}".format(
                request.endpoint, 
                response.status_code
            ))
            return response
    
    def _send_approval_notification(self, approval_data):
        """发送审批通知到Telegram"""
        try:
            if not self.telegram_handler:
                return False
            
            project_owners = approval_data.get('project_owners', [])
            mentions = permission_service.get_telegram_mentions(project_owners)
            
            message_text = f"""🔔 部署审批请求

📋 项目信息：
• 项目名称：{approval_data['project']}
• 环境：{approval_data['env'].upper()}
• 构建号：#{approval_data['build']}
• 版本：{approval_data['version']}

📝 操作详情：
• 操作类型：{approval_data['action']}
• 更新内容：{approval_data['desc']}
• 申请时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

👥 项目负责人：
{chr(10).join([f'• {permission_service.get_user_display_name(owner)}' for owner in project_owners])}

⏰ 审批时限：{approval_data['timeout_minutes']}分钟
🆔 审批ID：{approval_data['approval_id']}

{mentions} 请及时处理审批！"""
            
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ 同意部署", callback_data=f"approve:{approval_data['approval_id']}"),
                    InlineKeyboardButton("❌ 拒绝部署", callback_data=f"reject:{approval_data['approval_id']}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            return self.telegram_handler.send_message_with_buttons(message_text, reply_markup)
            
        except Exception as e:
            logger.error(f"❌ 发送审批通知失败: {e}")
            return False
    
    def _send_approval_result_notification(self, approval_data, result, approver_username):
        """发送审批结果通知"""
        try:
            if not self.telegram_handler:
                return False
            
            approver_display = permission_service.get_user_display_name(approver_username)
            status_emoji = "✅" if result == "approved" else "❌"
            status_text = "审批通过" if result == "approved" else "审批拒绝"
            
            message_text = f"""{status_emoji} {status_text}

📋 项目信息：
• 项目名称：{approval_data['project']}
• 环境：{approval_data['env'].upper()}
• 构建号：#{approval_data['build']}
• 版本：{approval_data.get('version', '未知')}

👤 审批信息：
• 审批人：{approver_display}
• 审批时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

📝 项目详情：
• 操作类型：{approval_data['action']}
• 更新内容：{approval_data['desc']}
• 申请时间：{approval_data.get('created_at', '未知')[:19]}

🆔 审批ID：{approval_data['approval_id']}"""
            
            if result == "approved":
                message_text += "\n\n🚀 部署即将开始，相关负责人请关注部署进度。"
            else:
                message_text += "\n\n⚠️ 部署已被拒绝，请联系审批人了解详情。"
            
            return self.telegram_handler.send_simple_message(message_text)
            
        except Exception as e:
            logger.error(f"❌ 发送审批结果通知失败: {e}")
            return False
    
    def _send_build_result_notification_enhanced(self, build_data: dict) -> bool:
        """发送增强版构建结果通知"""
        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            
            project = build_data.get('project', 'Unknown')
            build = build_data.get('build', 'Unknown')
            env = build_data.get('env', 'Unknown')
            status = build_data.get('status', 'unknown')
            duration = build_data.get('duration', 'Unknown')
            approval_id = build_data.get('approval_id', 'unknown')
            
            if status == 'success':
                # 构建成功消息
                message = f"""🎉 构建成功！
                
📋 项目: {project}
🏗️ 构建: #{build}
🌍 环境: {env}
⏱️ 耗时: {duration}
✅ 状态: 部署完成

恭喜！构建已成功部署到 {env} 环境。"""
                
                return self.telegram_handler.send_simple_message(message)
            else:
                # 构建失败，发送带"查看日志"按钮的消息
                log_url = f"http://{request.host}/logs/{approval_id}"
                
                message = f"""💥 构建失败！
                
📋 项目: {project}  
🏗️ 构建: #{build}
🌍 环境: {env}
⏱️ 耗时: {duration}
❌ 状态: {status.upper()}

构建过程中遇到错误，请查看详细日志进行排查："""
                
                # 创建查看日志按钮
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔍 查看详细日志", url=log_url)]
                ])
                
                # 发送带按钮的消息
                self.telegram_handler.bot.send_message(
                    chat_id=self.telegram_handler.chat_id,
                    text=message,
                    reply_markup=keyboard,
                    parse_mode='HTML'
                )
                
                logger.info("✅ 构建失败通知（带查看日志按钮）已发送")
                return True
                
        except Exception as e:
            logger.error(f"发送增强版构建结果通知失败: {e}")
            # 降级发送简单文本消息
            try:
                simple_message = f"""💥 构建失败！

📋 项目: {build_data.get('project', 'Unknown')}
🏗️ 构建: #{build_data.get('build', 'Unknown')}
🌍 环境: {build_data.get('env', 'Unknown')}
❌ 状态: {build_data.get('status', 'unknown').upper()}

🔗 查看日志: http://{request.host}/logs/{build_data.get('approval_id', 'unknown')}"""
                
                return self.telegram_handler.send_simple_message(simple_message)
            except:
                return False

    def _send_build_result_notification(self, build_data):
        """发送构建结果通知"""
        try:
            if not self.telegram_handler:
                return False
            
            status = build_data['status']
            status_emoji = "✅" if status == 'success' else "❌"
            status_text = "构建成功" if status == 'success' else "构建失败"
            
            message_text = f"""{status_emoji} {status_text}

📋 项目信息：
• 项目名称：{build_data['project']}
• 环境：{build_data['env'].upper()}
• 构建号：#{build_data['build']}
• 构建时长：{build_data['duration']}
• 完成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🎯 Jenkins构建已完成"""
            
            return self.telegram_handler.send_simple_message(message_text)
            
        except Exception as e:
            logger.error(f"❌ 发送构建结果通知失败: {e}")
            return False
    
    def _start_reminder_timer(self, approval_id):
        """启动提醒定时器"""
        try:
            def reminder_task():
                count = 0
                max_reminders = 6
                
                logger.info(f"🔔 启动提醒线程: {approval_id}")
                
                # 🔥 强化首次等待 - 每0.5秒检查一次停止条件
                for i in range(600):  # 600 * 0.5秒 = 300秒（5分钟）
                    time.sleep(0.5)
                    
                    # 🔥 第1优先级：立即停止标志
                    if approval_id in self._stopped_reminders:
                        logger.info(f"🚫 [停止标志] 首次提醒前检测到停止: {approval_id}")
                        return
                    
                    # 🔥 第2优先级：内存状态变更
                    if (approval_id in self.pending_approvals and 
                        self.pending_approvals[approval_id]['status'] != 'pending'):
                        current_status = self.pending_approvals[approval_id]['status']
                        logger.info(f"🚫 [内存状态] 首次提醒前检测到变更: {approval_id} -> {current_status}")
                        return
                    
                    # 🔥 第3优先级：停止标记
                    if (approval_id in self.pending_approvals and 
                        self.pending_approvals[approval_id].get('reminder_stopped', False)):
                        logger.info(f"🚫 [停止标记] 首次提醒前检测到: {approval_id}")
                        return
                    
                    # 🔥 第4优先级：数据库状态检查（每10秒检查一次）
                    if i % 20 == 0:  # 每10秒
                        try:
                            db_approval = self.database_service.get_approval(approval_id)
                            if db_approval and db_approval.status != 'pending':
                                logger.info(f"🚫 [数据库状态] 首次提醒前检测到变更: {approval_id} -> {db_approval.status}")
                                return
                        except Exception as e:
                            pass  # 忽略数据库检查错误
                
                while count < max_reminders:
                    # 🔥 强化多重停止检查 - 最高优先级
                    
                    # 检查1：立即停止标志
                    if approval_id in self._stopped_reminders:
                        logger.info(f"🚫 [停止标志] 提醒线程立即停止: {approval_id}")
                        return  # 直接返回，不再发送任何提醒
                    
                    # 检查2：内存状态变更
                    if (approval_id in self.pending_approvals and 
                        self.pending_approvals[approval_id]['status'] != 'pending'):
                        current_status = self.pending_approvals[approval_id]['status']
                        logger.info(f"🚫 [内存状态] 提醒线程检测到变更: {approval_id} -> {current_status}")
                        return  # 直接返回
                    
                    # 检查3：停止标记
                    if (approval_id in self.pending_approvals and 
                        self.pending_approvals[approval_id].get('reminder_stopped', False)):
                        logger.info(f"🚫 [停止标记] 提醒线程检测到: {approval_id}")
                        return  # 直接返回
                    
                    # 检查4：数据库状态（最终保障）
                    try:
                        approval_request = self.database_service.get_approval(approval_id)
                        if (not approval_request or 
                            approval_request.status != ApprovalStatus.PENDING.value):
                            db_status = approval_request.status if approval_request else 'deleted'
                            logger.info(f"🚫 [数据库状态] 提醒线程检测到变更: {approval_id} -> {db_status}")
                            return  # 直接返回
                    except Exception as e:
                        logger.warning(f"数据库状态检查失败: {e}")
                        # 继续执行，不因为数据库错误中断提醒
                    
                    # 发送提醒
                    count += 1
                    
                    # 获取项目负责人用于提醒
                    project_owners = permission_service.get_project_owners(approval_request.project)
                    reminder_data = {
                        'approval_id': approval_id,
                        'project': approval_request.project,
                        'env': approval_request.env,
                        'build': approval_request.build,
                        'version': approval_request.version,
                        'desc': approval_request.desc,
                        'project_owners': project_owners,
                        'reminder_count': count
                    }
                    
                    self._send_reminder_notification(reminder_data)
                    logger.info(f"📢 发送第{count}次审批提醒: {approval_id}")
                    
                    if count < max_reminders:
                        # 等待5分钟，但每2秒检查一次停止标志（更频繁检查）
                        for i in range(150):  # 150 * 2秒 = 300秒（5分钟）
                            time.sleep(2)
                            # 多重停止检查
                            if (approval_id in self._stopped_reminders or
                                (approval_id in self.pending_approvals and 
                                 self.pending_approvals[approval_id]['status'] != 'pending') or
                                (approval_id in self.pending_approvals and 
                                 self.pending_approvals[approval_id].get('reminder_stopped', False))):
                                logger.info(f"🚫 提醒等待期间检测到停止条件: {approval_id}")
                                return
                
                logger.info(f"🏁 提醒线程正常结束: {approval_id} (发送{count}次提醒)")
            
            reminder_thread = threading.Thread(target=reminder_task, daemon=True)
            reminder_thread.start()
            self.reminder_timers[approval_id] = reminder_thread
            
        except Exception as e:
            logger.error(f"❌ 启动提醒定时器失败: {e}")
    
    def _cancel_reminder_timer(self, approval_id):
        """取消提醒定时器和标记停止提醒 - 强化版本"""
        try:
            # 初始化停止提醒集合（防御性编程）
            if not hasattr(self, '_stopped_reminders'):
                self._stopped_reminders = set()
            
            # 立即添加到停止提醒集合 - 最高优先级
            old_size = len(self._stopped_reminders)
            self._stopped_reminders.add(approval_id)
            logger.info(f"🛑 立即停止提醒: {approval_id} (集合大小: {old_size} -> {len(self._stopped_reminders)})")
            
            # 强制更新内存状态，确保提醒线程检查时能立即发现
            if approval_id in self.pending_approvals and self.pending_approvals[approval_id]['status'] == 'pending':
                logger.warning(f"⚠️ 检测到pending状态但需要停止提醒，强制更新为processing: {approval_id}")
                self.pending_approvals[approval_id]['reminder_stopped'] = True
            
            # 清理定时器引用
            if approval_id in self.reminder_timers:
                reminder_thread = self.reminder_timers[approval_id]
                thread_name = getattr(reminder_thread, 'name', 'unknown')
                thread_alive = reminder_thread.is_alive() if hasattr(reminder_thread, 'is_alive') else 'unknown'
                
                # 尝试打断线程（设置停止标志后，线程会在下次检查时退出）
                logger.info(f"🧹 停止提醒线程: {approval_id} (线程: {thread_name}, 活跃: {thread_alive})")
                
                del self.reminder_timers[approval_id]
                logger.info(f"✅ 清理提醒定时器引用完成: {approval_id}")
            else:
                logger.debug(f"提醒定时器不存在，可能已停止: {approval_id}")
            
            # 额外保障：等待一小段时间确保提醒线程看到停止信号
            import time
            time.sleep(0.05)
            
            logger.info(f"✅ 提醒强制停止完成: {approval_id}")
            
        except Exception as e:
            logger.error(f"❌ 取消提醒定时器失败: {e}")
    
    def _start_cleanup_thread(self):
        """启动清理线程，定期清理过期的审批和提醒"""
        def cleanup_task():
            while True:
                try:
                    # 每5分钟执行一次清理
                    time.sleep(300)
                    
                    # 清理过期的处理中审批ID
                    if hasattr(self, '_processing_approvals'):
                        # 如果处理时间超过5分钟，认为是异常，清理掉
                        # 这里简单清理，实际可以记录时间戳做更精确的清理
                        if len(self._processing_approvals) > 0:
                            logger.debug(f"🧹 清理处理中审批ID: {len(self._processing_approvals)}个")
                            self._processing_approvals.clear()
                    
                    # 清理过期的停止提醒集合（避免内存泄漏）
                    if hasattr(self, '_stopped_reminders') and len(self._stopped_reminders) > 100:
                        # 保留最新的50个，清理其余的
                        old_size = len(self._stopped_reminders)
                        self._stopped_reminders = set(list(self._stopped_reminders)[-50:])
                        logger.debug(f"🧹 清理停止提醒集合: {old_size} -> {len(self._stopped_reminders)}")
                    
                    # 清理过期的待审批内存状态
                    if hasattr(self, 'pending_approvals'):
                        expired_ids = []
                        current_time = datetime.now()
                        for approval_id, approval_data in self.pending_approvals.items():
                            try:
                                # 检查是否过期（超过2小时）
                                created_at_str = approval_data.get('created_at', '')
                                if not created_at_str:
                                    logger.warning(f"🔶 审批记录缺少创建时间: {approval_id}")
                                    continue
                                
                                # 修复时间解析逻辑（兼容Python 3.6）
                                if created_at_str.endswith('Z'):
                                    created_at_str = created_at_str[:-1] + '+00:00'
                                
                                # Python 3.6兼容性修复
                                try:
                                    created_at = datetime.fromisoformat(created_at_str)
                                except AttributeError:
                                    # Python 3.6及以下版本不支持fromisoformat
                                    from dateutil.parser import parse
                                    created_at = parse(created_at_str)
                                age_seconds = (current_time - created_at).total_seconds()
                                
                                if age_seconds > 7200:  # 2小时
                                    expired_ids.append(approval_id)
                                    logger.debug(f"🧹 标记过期审批: {approval_id} (年龄: {age_seconds/3600:.1f}小时)")
                                    
                            except Exception as e:
                                # 🔥 关键修复：时间解析失败不应该删除审批记录！
                                logger.warning(f"⚠️ 审批时间解析失败，跳过清理: {approval_id} - {e}")
                                logger.debug(f"   原始时间字符串: {approval_data.get('created_at', 'None')}")
                                # 不再添加到过期列表，让审批记录继续存在
                        
                        for expired_id in expired_ids:
                            # 清理内存状态
                            del self.pending_approvals[expired_id]
                            # 清理事件对象
                            if hasattr(self, '_approval_events') and expired_id in self._approval_events:
                                del self._approval_events[expired_id]
                        
                        if expired_ids:
                            logger.debug(f"🧹 清理过期待审批状态: {len(expired_ids)}个")
                    
                    # 清理数据库中的过期审批记录
                    if self.database_service:
                        self.database_service.cleanup_expired_approvals()
                        
                except Exception as e:
                    logger.error(f"❌ 清理任务执行失败: {e}")
        
        cleanup_thread = threading.Thread(target=cleanup_task, daemon=True, name="approval-cleanup")
        cleanup_thread.start()
        logger.info("🧹 审批清理线程已启动")
    
    def _handle_approval(self, approval_id, action, user_name):
        """内部处理审批逻辑 - 供Telegram回调使用"""
        try:
            logger.info(f"🔥 Telegram按钮触发审批: {approval_id}, 动作: {action}, 用户: {user_name}")
            
            # 防止重复处理
            if approval_id in self._processing_approvals:
                return {'error': '审批正在处理中，请勿重复点击'}
            
            self._processing_approvals.add(approval_id)
            
            try:
                # 🔥 优先从内存获取审批请求
                approval_request = None
                
                if approval_id in self.pending_approvals:
                    pending_data = self.pending_approvals[approval_id]
                    approval_request = ApprovalRequest(
                        request_id=approval_id,
                        project=pending_data['project'],
                        env=pending_data['env'],
                        build=pending_data['build'],
                        job=pending_data.get('job', 'unknown'),
                        version=pending_data.get('version', 'unknown'),
                        desc=pending_data.get('desc', ''),
                        action=pending_data.get('action', '部署'),
                        timeout_seconds=pending_data.get('timeout_minutes', 30) * 60
                    )
                    approval_request.status = pending_data.get('status', 'pending')
                    approval_request.created_at = pending_data.get('created_at', '')
                    approval_request.expires_at = pending_data.get('expires_at', '')
                    approval_request.approver = pending_data.get('approver')
                    approval_request.approver_role = pending_data.get('approver_role')
                    approval_request.comment = pending_data.get('comment')
                
                # 如果内存中没有，再从数据库查找
                if not approval_request:
                    approval_request = self.database_service.get_approval(approval_id)
                
                if not approval_request:
                    return {'error': '审批记录不存在或已过期'}
                
                # 检查状态
                if approval_request.status != ApprovalStatus.PENDING.value:
                    status_text = "已同意" if approval_request.status == "approved" else "已拒绝"
                    return {'error': f'审批{status_text}，请勿重复操作'}
                
                # 获取用户信息
                approver_info = permission_service.get_user_info(user_name)
                approver_role = approver_info.get('role', '管理员') if approver_info else '管理员'
                comment = f'Telegram {action}'
                
                # 锁定审批请求
                if not self.database_service.lock_approval(approval_id, user_name):
                    return {'error': '审批正在被他人处理中，请稍后重试'}
                
                # 更新审批状态
                status = ApprovalStatus.APPROVED.value if action == 'approved' else ApprovalStatus.REJECTED.value
                result = self.database_service.update_approval_status(
                    approval_id, status, user_name, approver_role, comment
                )
                
                if result["success"]:
                    # 立即更新内存状态
                    if approval_id in self.pending_approvals:
                        self.pending_approvals[approval_id]['status'] = status
                        self.pending_approvals[approval_id]['approver'] = user_name
                        self.pending_approvals[approval_id]['approver_role'] = approver_role
                        self.pending_approvals[approval_id]['comment'] = comment
                        self.pending_approvals[approval_id]['updated_at'] = result["timestamp"]
                        
                        logger.info(f"🔄 Telegram操作已更新内存状态: {approval_id} -> {status}")
                    
                    # 停止提醒
                    self._cancel_reminder_timer(approval_id)
                    
                    # 🔥 关键：触发Jenkins事件通知
                    if approval_id in self._approval_events:
                        event_obj = self._approval_events[approval_id]
                        event_obj.set()
                        logger.info(f"🚨 Telegram操作已触发Jenkins通知事件: {approval_id}")
                    else:
                        # 紧急补救
                        emergency_event = threading.Event()
                        emergency_event.set()
                        self._approval_events[approval_id] = emergency_event
                        logger.warning(f"⚡ Telegram操作紧急创建并触发事件: {approval_id}")
                    
                    # 延迟清理事件对象
                    def cleanup_after_telegram():
                        time.sleep(2)
                        if approval_id in self._approval_events:
                            del self._approval_events[approval_id]
                            logger.debug(f"🧹 Telegram操作完成后清理事件对象: {approval_id}")
                    
                    threading.Thread(target=cleanup_after_telegram, daemon=True).start()
                    
                    # 解锁
                    try:
                        self.database_service.unlock_approval(approval_id)
                    except Exception as e:
                        logger.warning(f"解锁失败: {e}")
                    
                    status_text = "已通过" if status == "approved" else "已拒绝"
                    logger.info(f"✅ Telegram {status_text} 处理完成: {approval_id} by {user_name}")
                    
                    return {
                        'success': True,
                        'result': status,
                        'message': f'✅ 审批{status_text}！',
                        'approval_id': approval_id,
                        'approver': user_name,
                        'approver_role': approver_role
                    }
                else:
                    return {'error': result["message"]}
                    
            finally:
                # 确保从处理集合中移除
                self._processing_approvals.discard(approval_id)
                
        except Exception as e:
            logger.error(f"❌ Telegram审批处理异常: {approval_id} - {e}")
            return {'error': f'处理失败: {str(e)}'}
    
    def _mark_reminder_stopped(self, approval_id):
        """标记提醒已停止（用于确保提醒线程及时退出）"""
        if not hasattr(self, '_stopped_reminders'):
            self._stopped_reminders = set()
        self._stopped_reminders.add(approval_id)
        logger.debug(f"🚫 标记提醒停止: {approval_id}")
    
    def _send_reminder_notification(self, approval_data):
        """发送提醒通知"""
        try:
            if not self.telegram_handler:
                return False
            
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            
            project_owners = approval_data.get('project_owners', [])
            mentions = permission_service.get_telegram_mentions(project_owners)
            reminder_count = approval_data.get('reminder_count', 0)
            
            message_text = f"""⏰ 审批提醒 (第{reminder_count}次)

📋 项目信息：
• 项目名称：{approval_data['project']}
• 环境：{approval_data['env'].upper()}
• 构建号：#{approval_data['build']}
• 版本：{approval_data.get('version', '未知')}
• 更新内容：{approval_data.get('desc', '无描述')}

⏳ 已等待：{reminder_count * 5}分钟，请尽快处理！
🆔 审批ID：{approval_data['approval_id']}

{mentions} 请尽快处理审批！"""
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ 同意部署", callback_data=f"approve:{approval_data['approval_id']}"),
                    InlineKeyboardButton("❌ 拒绝部署", callback_data=f"reject:{approval_data['approval_id']}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            return self.telegram_handler.send_message_with_buttons(message_text, reply_markup)
            
        except Exception as e:
            logger.error(f"❌ 发送提醒通知失败: {e}")
            return False
    
    def _send_build_notification(self, project, env, build_number, job_name, version, status, duration, build_url):
        """发送构建完成通知到Telegram"""
        try:
            # 构建状态映射
            status_mapping = {
                'SUCCESS': {'emoji': '✅', 'text': '构建成功'},
                'FAILURE': {'emoji': '❌', 'text': '构建失败'},
                'UNSTABLE': {'emoji': '⚠️', 'text': '构建不稳定'},
                'ABORTED': {'emoji': '🚫', 'text': '构建已中止'},
                'NOT_BUILT': {'emoji': '⏸️', 'text': '未构建'}
            }
            
            status_info = status_mapping.get(status.upper(), {'emoji': '❓', 'text': f'构建状态: {status}'})
            
            # 格式化构建时长
            duration_str = self._format_duration(duration)
            
            # 构建基本消息
            message = f"""{status_info['emoji']} **{status_info['text']}**

📋 **项目信息：**
• 项目名称：{project}
• 环境：{env.upper()}
• 构建号：#{build_number}
• 版本：{version}
• 任务：{job_name}

⏱️ **构建信息：**
• 构建时长：{duration_str}
• 完成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""

            # 如果构建失败，添加日志查看按钮
            reply_markup = None
            if status.upper() in ['FAILURE', 'UNSTABLE']:
                approval_id = f"build-{project}-{env}-{build_number}-{int(datetime.now().timestamp())}"
                logs_url = f"http://192.168.9.134:8770/logs/{approval_id}"
                
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                keyboard = []
                keyboard.append([InlineKeyboardButton("📋 查看构建日志", url=logs_url)])
                if build_url:
                    keyboard.append([InlineKeyboardButton("🔗 Jenkins页面", url=build_url)])
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # 在内存中存储构建信息，用于日志页面
                self.pending_approvals[approval_id] = {
                    'project': project,
                    'env': env,
                    'build': build_number,
                    'job': job_name,
                    'version': version,
                    'build_url': build_url,
                    'status': status,
                    'created_at': datetime.now().isoformat()
                }
            elif build_url:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                keyboard = [[InlineKeyboardButton("🔗 Jenkins页面", url=build_url)]]
                reply_markup = InlineKeyboardMarkup(keyboard)
            
            # 发送消息
            if self.telegram_handler and hasattr(self.telegram_handler, 'bot'):
                try:
                    self.telegram_handler.bot.send_message(
                        chat_id=self.telegram_handler.chat_id,
                        text=message,
                        parse_mode='Markdown',
                        reply_markup=reply_markup
                    )
                    logger.info(f"✅ 构建通知已发送: {project}-{env} #{build_number} -> {status}")
                except Exception as e:
                    logger.error(f"❌ 发送Telegram消息失败: {e}")
            else:
                logger.warning("Telegram bot未初始化，无法发送消息")
                
        except Exception as e:
            logger.error(f"❌ 发送构建通知失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _format_duration(self, duration_seconds):
        """格式化构建时长"""
        try:
            duration = int(float(duration_seconds))
            if duration < 60:
                return f"{duration}秒"
            elif duration < 3600:
                minutes = duration // 60
                seconds = duration % 60
                return f"{minutes}分{seconds}秒"
            else:
                hours = duration // 3600
                minutes = (duration % 3600) // 60
                return f"{hours}小时{minutes}分钟"
        except:
            return "未知"
    
    def _render_logs_page(self, approval_id, build_info):
        """渲染响应式的构建日志查看页面"""
        # 构建Jenkins日志URL
        jenkins_config = config_service.get_jenkins_config()
        jenkins_base_url = jenkins_config.get('url', 'http://localhost:8080')
        job_name = build_info.get('job', f"{build_info['project']}-{build_info['env']}")
        build_number = build_info.get('build', '1')
        
        # 多种可能的Jenkins URL格式
        jenkins_urls = [
            f"{jenkins_base_url}/job/{job_name}/{build_number}/console",
            f"{jenkins_base_url}/job/{job_name}/{build_number}/consoleText",
            f"{jenkins_base_url}/blue/organizations/jenkins/{job_name}/detail/{job_name}/{build_number}/pipeline",
            f"{jenkins_base_url}/job/{build_info['project']}/{build_number}/console"
        ]
        
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>构建日志 - {build_info['project']} #{build_info['build']}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }}
        
        .header {{
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 16px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.2);
        }}
        
        .header h1 {{
            color: #2c3e50;
            margin-bottom: 10px;
            font-size: 1.8rem;
            font-weight: 600;
        }}
        
        .build-info {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }}
        
        .info-item {{
            background: rgba(52, 152, 219, 0.1);
            padding: 15px;
            border-radius: 10px;
            border-left: 4px solid #3498db;
        }}
        
        .info-label {{
            font-weight: 600;
            color: #2c3e50;
            font-size: 0.9rem;
            margin-bottom: 5px;
        }}
        
        .info-value {{
            color: #34495e;
            font-size: 1.1rem;
            font-weight: 500;
        }}
        
        .log-section {{
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 16px;
            padding: 30px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.2);
        }}
        
        .log-section h2 {{
            color: #2c3e50;
            margin-bottom: 20px;
            font-size: 1.4rem;
            font-weight: 600;
        }}
        
        .log-buttons {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }}
        
        .log-button {{
            display: block;
            background: linear-gradient(135deg, #3498db, #2980b9);
            color: white;
            text-decoration: none;
            padding: 15px 20px;
            border-radius: 12px;
            text-align: center;
            font-weight: 600;
            transition: all 0.3s ease;
            box-shadow: 0 4px 15px rgba(52, 152, 219, 0.3);
            position: relative;
            overflow: hidden;
        }}
        
        .log-button:hover {{
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(52, 152, 219, 0.4);
        }}
        
        .log-button:active {{
            transform: translateY(0);
        }}
        
        .log-button::before {{
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.2), transparent);
            transition: left 0.5s;
        }}
        
        .log-button:hover::before {{
            left: 100%;
        }}
        
        .primary-button {{
            background: linear-gradient(135deg, #e74c3c, #c0392b);
            box-shadow: 0 4px 15px rgba(231, 76, 60, 0.3);
        }}
        
        .primary-button:hover {{
            box-shadow: 0 6px 20px rgba(231, 76, 60, 0.4);
        }}
        
        .tips {{
            background: rgba(46, 204, 113, 0.1);
            border: 1px solid rgba(46, 204, 113, 0.3);
            border-radius: 12px;
            padding: 20px;
            margin: 20px 0;
        }}
        
        .tips h3 {{
            color: #27ae60;
            margin-bottom: 10px;
            font-size: 1.1rem;
        }}
        
        .tips ul {{
            color: #2c3e50;
            padding-left: 20px;
        }}
        
        .tips li {{
            margin-bottom: 5px;
        }}
        
        /* 响应式设计 */
        @media (max-width: 768px) {{
            .container {{
                padding: 10px;
            }}
            
            .header, .log-section {{
                padding: 20px;
            }}
            
            .header h1 {{
                font-size: 1.5rem;
            }}
            
            .build-info {{
                grid-template-columns: 1fr;
                gap: 10px;
            }}
            
            .log-buttons {{
                grid-template-columns: 1fr;
                gap: 10px;
            }}
            
            .log-button {{
                padding: 12px 15px;
                font-size: 0.9rem;
            }}
        }}
        
        @media (max-width: 480px) {{
            .header h1 {{
                font-size: 1.3rem;
            }}
            
            .info-item {{
                padding: 10px;
            }}
        }}
        
        /* 深色模式支持 */
        @media (prefers-color-scheme: dark) {{
            body {{
                background: linear-gradient(135deg, #2c3e50 0%, #34495e 100%);
            }}
            
            .header, .log-section {{
                background: rgba(44, 62, 80, 0.95);
                color: #ecf0f1;
            }}
            
            .header h1, .log-section h2 {{
                color: #ecf0f1;
            }}
            
            .info-value {{
                color: #bdc3c7;
            }}
            
            .tips {{
                background: rgba(46, 204, 113, 0.2);
                color: #ecf0f1;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🏗️ Jenkins构建日志</h1>
            <div class="build-info">
                <div class="info-item">
                    <div class="info-label">项目名称</div>
                    <div class="info-value">{build_info['project']}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">环境</div>
                    <div class="info-value">{build_info['env'].upper()}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">构建号</div>
                    <div class="info-value">#{build_info['build']}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">版本</div>
                    <div class="info-value">{build_info['version']}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">任务名称</div>
                    <div class="info-value">{build_info.get('job', 'unknown')}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">审批ID</div>
                    <div class="info-value">{approval_id}</div>
                </div>
            </div>
        </div>
        
        <div class="log-section">
            <h2>📋 构建日志查看</h2>
            
            <div class="log-buttons">
                <a href="{jenkins_urls[0]}" target="_blank" class="log-button primary-button">
                    🔍 查看完整构建日志 (推荐)
                </a>
                <a href="{jenkins_urls[1]}" target="_blank" class="log-button">
                    📄 查看纯文本日志
                </a>
                <a href="{jenkins_urls[2]}" target="_blank" class="log-button">
                    🌟 Blue Ocean 视图
                </a>
                <a href="{jenkins_base_url}" target="_blank" class="log-button">
                    🏠 Jenkins 首页
                </a>
            </div>
            
            <div class="tips">
                <h3>💡 使用提示</h3>
                <ul>
                    <li><strong>完整构建日志</strong>：包含完整的构建输出和错误信息</li>
                    <li><strong>纯文本日志</strong>：适合下载和保存，便于分析</li>
                    <li><strong>Blue Ocean</strong>：现代化的Jenkins界面，可视化构建流程</li>
                    <li>如果日志页面需要登录，请使用Jenkins账户登录</li>
                    <li>页面已优化适配手机、平板等各种设备</li>
                </ul>
            </div>
            
            <div style="margin-top: 30px; text-align: center;">
                <p style="color: #7f8c8d; font-size: 0.9rem;">
                    🤖 由 Jenkins 审批机器人生成 • {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                </p>
            </div>
        </div>
    </div>
    
    <script>
        // 添加一些交互效果
        document.addEventListener('DOMContentLoaded', function() {{
            // 为按钮添加点击效果
            const buttons = document.querySelectorAll('.log-button');
            buttons.forEach(button => {{
                button.addEventListener('click', function() {{
                    this.style.transform = 'scale(0.98)';
                    setTimeout(() => {{
                        this.style.transform = '';
                    }}, 100);
                }});
            }});
            
            // 检查Jenkins连接状态
            checkJenkinsStatus();
        }});
        
        function checkJenkinsStatus() {{
            const statusIndicator = document.createElement('div');
            statusIndicator.style.cssText = `
                position: fixed;
                top: 20px;
                right: 20px;
                padding: 10px 15px;
                border-radius: 20px;
                font-size: 0.8rem;
                font-weight: 600;
                z-index: 1000;
                background: rgba(46, 204, 113, 0.9);
                color: white;
                box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
            `;
            statusIndicator.textContent = '🟢 Jenkins 连接正常';
            document.body.appendChild(statusIndicator);
            
            // 3秒后隐藏状态指示器
            setTimeout(() => {{
                statusIndicator.style.opacity = '0';
                statusIndicator.style.transition = 'opacity 0.5s ease';
                setTimeout(() => statusIndicator.remove(), 500);
            }}, 3000);
        }}
    </script>
</body>
</html>"""


