# -*- coding: utf-8 -*-
"""
Telegram处理器模块
"""

from datetime import datetime
from typing import Optional

from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, CallbackQueryHandler, CallbackContext, Dispatcher

from ..core.approval_manager import ApprovalManager
from ..services.permission_service import permission_service
from ..utils.logger import get_logger
from ..utils.message_utils import (
    clean_message_text, format_approval_message, format_approval_result_message
)

logger = get_logger(__name__)


class TelegramHandler:
    """Telegram消息和命令处理器"""
    
    def __init__(self, bot: Bot, chat_id: str, approval_manager: ApprovalManager):
        self.bot = bot
        self.chat_id = chat_id
        self.approval_manager = approval_manager
        self.api_handler = None  # 将在set_api_handler中设置
    
    def set_api_handler(self, api_handler):
        """设置API处理器引用，用于统一的审批处理"""
        self.api_handler = api_handler
    
    def setup_handlers(self, dispatcher: Dispatcher) -> None:
        """设置命令处理器"""
        handlers = [
            CommandHandler("approve", self._cmd_approve),
            CommandHandler("reject", self._cmd_reject),
            CommandHandler("status", self._cmd_status),
            CommandHandler("jenkins", self._cmd_jenkins),
            CallbackQueryHandler(self._button_handler)
        ]
        
        for handler in handlers:
            dispatcher.add_handler(handler)
        
        dispatcher.add_error_handler(self._error_handler)
        logger.info("Telegram命令处理器设置完成")
    
    def _error_handler(self, update: Update, context: CallbackContext) -> None:
        """全局错误处理器"""
        try:
            logger.error("Telegram机器人错误: {}".format(str(context.error)))
        except Exception as e:
            logger.error("错误处理器本身出错: {}".format(str(e)))
    
    def send_simple_message(self, message: str) -> bool:
        """发送简单消息"""
        try:
            if not self.bot or not self.chat_id:
                return False
            
            result = self.bot.send_message(
                chat_id=self.chat_id,
                text=clean_message_text(message),
                timeout=20,
                disable_web_page_preview=True,
                parse_mode='HTML'
            )
            
            return bool(result)
            
        except Exception as e:
            logger.error("发送消息失败: {}".format(str(e)))
            return False
    
    def send_message_with_buttons(self, message: str, reply_markup) -> bool:
        """发送带按钮的消息"""
        try:
            if not self.bot or not self.chat_id:
                return False
            
            result = self.bot.send_message(
                chat_id=self.chat_id,
                text=clean_message_text(message),
                reply_markup=reply_markup,
                timeout=20,
                disable_web_page_preview=True,
                parse_mode='HTML'
            )
            
            return bool(result)
            
        except Exception as e:
            logger.error("发送带按钮消息失败: {}".format(str(e)))
            return False
    
    def send_approval_notification(self, approval_id: str) -> bool:
        """发送审批通知"""
        try:
            if not self.bot:
                return False
            
            approval = self.approval_manager.get_approval(approval_id)
            if not approval:
                return False
            
            # 格式化消息
            text = format_approval_message(approval.to_dict())
            
            # 创建按钮
            keyboard = [
                [
                    InlineKeyboardButton("同意发布", callback_data="approve_{}".format(approval_id)),
                    InlineKeyboardButton("拒绝发布", callback_data="reject_{}".format(approval_id))
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            message = self.bot.send_message(
                chat_id=self.chat_id,
                text=clean_message_text(text),
                timeout=15,
                disable_web_page_preview=True,
                reply_markup=reply_markup
            )
            
            if message:
                logger.info("审批通知发送成功: {}".format(approval_id))
                return True
            else:
                return False
            
        except Exception as e:
            logger.error("发送审批通知失败: {}".format(str(e)))
            return False
    
    # Telegram命令处理器
    def _cmd_approve(self, update: Update, context: CallbackContext) -> None:
        """处理审批同意命令"""
        args = context.args
        if not args:
            self._send_reply(update, "请提供审批ID\n\n使用: /approve <approval_id>")
            return
        
        approval_id = args[0]
        user = update.effective_user
        
        # 🔥 关键修复：使用APIHandler的统一审批处理，确保事件触发
        if self.api_handler:
            success, message = self.api_handler.process_approval_internal(
                approval_id, 'approved', str(user.id), user.username or user.first_name, "Telegram审批"
            )
        else:
            # 备用方案：使用原来的ApprovalManager
            logger.warning("API处理器未设置，使用备用审批处理")
            success, message = self.approval_manager.process_approval(
                approval_id, 'approved', user.id, user.username or user.first_name
            )
        
        if success:
            text = "审批成功\n\n审批ID: {}\n处理人: {}\n\n构建将继续执行".format(
                approval_id, user.first_name)
            logger.info(f"✅ Telegram审批成功: {approval_id} by {user.first_name}")
        else:
            text = "审批失败\n\n错误: {}".format(message)
            logger.error(f"❌ Telegram审批失败: {approval_id} - {message}")
        
        self._send_reply(update, text)
    
    def _cmd_reject(self, update: Update, context: CallbackContext) -> None:
        """处理审批拒绝命令"""
        args = context.args
        if not args:
            self._send_reply(update, "请提供审批ID\n\n使用: /reject <approval_id>")
            return
        
        approval_id = args[0]
        user = update.effective_user
        
        # 🔥 关键修复：使用APIHandler的统一审批处理，确保事件触发
        if self.api_handler:
            success, message = self.api_handler.process_approval_internal(
                approval_id, 'rejected', str(user.id), user.username or user.first_name, "Telegram审批"
            )
        else:
            # 备用方案：使用原来的ApprovalManager
            logger.warning("API处理器未设置，使用备用审批处理")
            success, message = self.approval_manager.process_approval(
                approval_id, 'rejected', user.id, user.username or user.first_name
            )
        
        if success:
            text = "审批拒绝\n\n审批ID: {}\n处理人: {}\n\n构建已停止".format(
                approval_id, user.first_name)
            logger.info(f"✅ Telegram审批拒绝: {approval_id} by {user.first_name}")
        else:
            text = "操作失败\n\n错误: {}".format(message)
            logger.error(f"❌ Telegram审批拒绝失败: {approval_id} - {message}")
        
        self._send_reply(update, text)
    
    def _cmd_status(self, update: Update, context: CallbackContext) -> None:
        """查看审批状态命令"""
        args = context.args
        
        if not args:
            # 显示统计信息
            stats = self.approval_manager.get_approval_statistics()
            text = """审批状态统计

总审批数: {}
待处理: {}
已同意: {}
已拒绝: {}

使用 /status <approval_id> 查看具体审批""".format(
                stats['total'], stats['pending'], stats['approved'], stats['rejected']
            )
        else:
            # 显示具体审批信息
            approval_id = args[0]
            approval = self.approval_manager.get_approval(approval_id)
            
            if not approval:
                text = "审批ID {} 不存在".format(approval_id)
            else:
                text = """审批详情

审批ID: {}
状态: {}
项目: {}
构建: #{}
环境: {}
创建时间: {}""".format(
                    approval_id,
                    approval.status,
                    approval.job_name,
                    approval.build_number,
                    approval.environment,
                    approval.created_at
                )
                
                if approval.status != 'pending':
                    text += "\n处理人: {}".format(approval.processed_by or '未知')
                    text += "\n处理时间: {}".format(approval.processed_at or '未知')
        
        self._send_reply(update, text)
    
    def _cmd_jenkins(self, update: Update, context: CallbackContext) -> None:
        """查看Jenkins状态命令"""
        jenkins_status = self.approval_manager.jenkins_service.get_jenkins_status()
        
        if jenkins_status['status'] == 'connected':
            text = """Jenkins状态

服务器: {}
版本: {}
状态: 连接正常
用户: {}""".format(
                jenkins_status['url'],
                jenkins_status['version'],
                jenkins_status['username']
            )
        else:
            text = "Jenkins连接失败\n\n错误: {}".format(jenkins_status.get('error', '未知错误'))
        
        self._send_reply(update, text)
    
    def _button_handler(self, update: Update, context: CallbackContext) -> None:
        """处理按钮点击事件 - 支持完整审批流程"""
        query = update.callback_query
        
        # 🔥 强制输出调试信息
        print(f"\n" + "🔥"*80)
        print(f"🔥 【TELEGRAM BUTTON CLICK】 收到按钮点击事件")
        print(f"🔥"*80)
        
        try:
            query.answer(text="处理中...")
        except Exception:
            pass
        
        callback_data = query.data
        user = query.from_user
        user_name = user.username or user.first_name or 'Unknown'
        
        print(f"👤 用户: {user_name}")
        print(f"📝 回调数据: {callback_data}")
        print(f"⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        logger.info(f"👤 用户 {user_name} 点击按钮: {callback_data}")
        
        # 解析回调数据 - 新格式 action:approval_id
        if ':' not in callback_data:
            self._edit_message(query, "❌ 无效的操作格式")
            return
        
        try:
            action, approval_id = callback_data.split(':', 1)
        except ValueError:
            self._edit_message(query, "❌ 无效的操作数据")
            return
        
        # 检查用户权限
        from ..services.permission_service import permission_service
        
        if not permission_service.check_permission(user_name):
            self._edit_message(query, f"❌ 用户 {user_name} 没有操作权限")
            return
        
        # 根据操作类型处理
        if action == 'approve':
            print(f"✅ 处理审批通过: {approval_id}")
            if not permission_service.check_permission(user_name, 'approve'):
                print(f"❌ 用户权限检查失败: {user_name}")
                self._edit_message(query, f"❌ 用户 {user_name} 没有审批权限")
                return
            
            print(f"🚀 开始调用审批处理: {approval_id}")
            result = self._process_approval_action(approval_id, 'approved', user_name)
            print(f"✅ 审批处理结果: {result}")
            
        elif action == 'reject':
            print(f"❌ 处理审批拒绝: {approval_id}")
            if not permission_service.check_permission(user_name, 'reject'):
                print(f"❌ 用户权限检查失败: {user_name}")
                self._edit_message(query, f"❌ 用户 {user_name} 没有拒绝权限")
                return
            
            print(f"🚀 开始调用拒绝处理: {approval_id}")
            result = self._process_approval_action(approval_id, 'rejected', user_name)
            print(f"❌ 拒绝处理结果: {result}")
            
        elif action == 'logs':
            # 查看日志
            self._edit_message(query, f"🔍 日志链接：http://localhost:8770/logs/{approval_id}\n\n点击链接查看详细信息")
            return
            
        else:
            self._edit_message(query, f"❌ 不支持的操作: {action}")
            return
        
        # 更新消息内容
        print(f"🔄 更新Telegram消息: success={result['success']}")
        if result['success']:
            # 获取用户显示信息
            user_display = permission_service.get_user_display_name(user_name)
            
            if result['action'] == 'approved':
                status_emoji = "✅"
                status_text = "审批通过"
                action_text = "部署将继续进行"
            else:
                status_emoji = "❌"
                status_text = "审批拒绝"
                action_text = "部署已停止"
            
            print(f"✅ Telegram消息将更新为: {status_text}")
            
            new_text = f"""{status_emoji} {status_text}

📋 项目信息：
• 项目名称：{result['project']}
• 环境：{result['env'].upper()}
• 构建号：#{result['build']}
• 版本：{result.get('version', '未知')}

👤 审批信息：
• 审批人：{user_display}
• 审批时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🆔 审批ID：{approval_id}
🎯 {action_text}"""
            
            self._edit_message(query, new_text)
            print(f"✅ Telegram消息已更新完成")
        else:
            self._edit_message(query, f"❌ 操作失败\n\n{result['message']}")
            print(f"❌ Telegram显示操作失败")
        
        print(f"🔥"*80)
        print(f"🔥 【TELEGRAM BUTTON HANDLER COMPLETE】")
        print(f"🔥"*80 + "\n")
    
    def _process_approval_action(self, approval_id: str, action: str, user_name: str) -> dict:
        """处理审批操作"""
        try:
            print(f"\n" + "⚡"*80)
            print(f"⚡ 【PROCESS APPROVAL ACTION】 {action.upper()}")
            print(f"📝 审批ID: {approval_id}")
            print(f"👤 用户: {user_name}")
            print(f"🔗 API Handler存在: {self.api_handler is not None}")
            print(f"⚡"*80)
            
            logger.info(f"📋 Telegram按钮处理审批操作: {approval_id} - {action} by {user_name}")
            
            # 🔥 关键修复：使用APIHandler的统一审批处理，确保事件触发
            if self.api_handler:
                print(f"🚀 调用API Handler的process_approval_internal方法")
                success, message = self.api_handler.process_approval_internal(
                    approval_id, action, "telegram_user", user_name, "Telegram按钮审批"
                )
                print(f"✅ API Handler处理结果: success={success}, message={message}")
                
                if success:
                    # 从内存中获取审批信息用于显示
                    approval_data = self.api_handler.pending_approvals.get(approval_id, {})
                    return {
                        'success': True,
                        'action': action,
                        'project': approval_data.get('project', 'unknown'),
                        'env': approval_data.get('env', 'unknown'),
                        'build': approval_data.get('build', 'unknown'),
                        'version': approval_data.get('version', 'unknown'),
                        'message': message
                    }
                else:
                    return {
                        'success': False,
                        'message': message
                    }
            else:
                # 备用方案：使用原来的ApprovalManager
                logger.warning("API处理器未设置，使用备用审批处理")
                success, message = self.approval_manager.process_approval(
                    approval_id, action, "telegram_user", user_name
                )
                
                if success:
                    return {
                        'success': True,
                        'action': action,
                        'project': 'unknown',
                        'env': 'unknown',
                        'build': 'unknown',
                        'version': 'unknown',
                        'message': message
                    }
                else:
                    return {
                        'success': False,
                        'message': message
                    }
            
        except Exception as e:
            logger.error(f"❌ 处理审批操作失败: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'message': str(e)
            }
    
    def _send_reply(self, update: Update, text: str) -> None:
        """发送回复消息"""
        try:
            update.message.reply_text(clean_message_text(text))
        except Exception as e:
            logger.error("发送回复失败: {}".format(str(e)))
    
    def _edit_message(self, query, text: str) -> None:
        """编辑消息"""
        try:
            query.edit_message_text(clean_message_text(text))
        except Exception as e:
            logger.error("编辑消息失败: {}".format(str(e)))

