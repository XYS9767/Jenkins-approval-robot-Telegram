#!/usr/bin/env python3

import requests
import sys
import logging
from typing import Dict, Any

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class JenkinsApprovalClient:
    
    def __init__(self, approval_service_url: str = "http://192.168.9.134:8770"):
        self.base_url = approval_service_url.rstrip('/')
        self.session = requests.Session()
        self.session.timeout = 10
        
    def wait_for_approval(self, project: str, env: str, build: str, job: str, 
                         version: str, desc: str = "默认更新", action: str = "部署",
                         timeout: int = 30) -> Dict[str, Any]:
        try:
            params = {
                'project': project,
                'env': env,
                'build': build,
                'job': job,
                'version': version,
                'desc': desc,
                'action': action,
                'timeout': timeout
            }
            
            logger.info(f"🚀 发送审批请求: {project} -> {env} (构建: {build})")
            logger.info(f"📋 请求参数: {params}")
            
            # 发送审批请求
            response = self.session.get(
                f"{self.base_url}/api/stage/approval/wait",
                params=params
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"✅ 审批通过: {result.get('message', '无消息')}")
                return {
                    'success': True,
                    'status': 'approved',
                    'data': result
                }
            
            elif response.status_code == 403:
                result = response.json()
                logger.error(f"❌ 审批拒绝: {result.get('message', '无消息')}")
                return {
                    'success': False,
                    'status': 'rejected',
                    'data': result
                }
            
            elif response.status_code == 408:
                result = response.json()
                logger.warning(f"⏰ 审批超时: {result.get('message', '无消息')}")
                return {
                    'success': False,
                    'status': 'timeout',
                    'data': result
                }
            
            else:
                error_msg = f"审批服务返回错误状态: {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg = error_data.get('message', error_msg)
                except:
                    pass
                
                logger.error(f"❌ 审批服务错误: {error_msg}")
                return {
                    'success': False,
                    'status': 'error',
                    'message': error_msg,
                    'data': None
                }
                
        except requests.exceptions.ConnectException as e:
            error_msg = f"无法连接到审批服务: {self.base_url}"
            logger.error(f"❌ 连接错误: {error_msg}")
            return {
                'success': False,
                'status': 'connection_error',
                'message': error_msg,
                'data': None
            }
            
        except requests.exceptions.Timeout as e:
            error_msg = f"审批服务响应超时"
            logger.error(f"❌ 超时错误: {error_msg}")
            return {
                'success': False,
                'status': 'timeout_error',
                'message': error_msg,
                'data': None
            }
            
        except Exception as e:
            error_msg = f"系统错误: {str(e)}"
            logger.error(f"❌ 系统异常: {error_msg}")
            return {
                'success': False,
                'status': 'system_error',
                'message': error_msg,
                'data': None
            }
    
    def get_approval_status(self, request_id: str) -> Dict[str, Any]:
        try:
            response = self.session.get(f"{self.base_url}/api/approval/{request_id}")
            
            if response.status_code == 200:
                result = response.json()
                return {
                    'success': True,
                    'data': result.get('data', {})
                }
            else:
                return {
                    'success': False,
                    'message': f"获取审批状态失败: {response.status_code}"
                }
                
        except Exception as e:
            return {
                'success': False,
                'message': f"获取审批状态异常: {str(e)}"
            }
    
    def send_stage_notification(self, stage: str, status: str, project: str, 
                               env: str, build: str, msg: str = "") -> bool:
        try:
            params = {
                'stage': stage,
                'status': status,
                'project': project,
                'env': env,
                'build': build
            }
            
            if msg:
                params['msg'] = msg
            
            logger.info(f"📡 发送阶段通知: {stage} -> {status}")
            
            response = self.session.get(
                f"{self.base_url}/api/stage/notify",
                params=params
            )
            
            if response.status_code in [200, 404]:  # 404也算成功，因为通知服务可能不存在
                logger.info("✅ 通知已发送")
                return True
            else:
                logger.warning(f"⚠️  通知发送失败: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"❌ 发送通知异常: {str(e)}")
            return False

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Jenkins审批客户端')
    parser.add_argument('--url', default='http://192.168.9.134:8770', help='审批服务地址')
    parser.add_argument('--project', required=True, help='项目名称')
    parser.add_argument('--env', required=True, help='环境名称')
    parser.add_argument('--build', required=True, help='构建号')
    parser.add_argument('--job', required=True, help='作业名称')
    parser.add_argument('--version', required=True, help='版本号')
    parser.add_argument('--desc', default='默认更新', help='描述')
    parser.add_argument('--action', default='部署', help='操作类型')
    parser.add_argument('--timeout', type=int, default=30, help='超时时间（分钟）')
    
    args = parser.parse_args()
    
    client = JenkinsApprovalClient(args.url)
    
    # 发送开始通知
    client.send_stage_notification(
        "审批", "start", args.project, args.env, args.build
    )
    
    # 等待审批
    result = client.wait_for_approval(
        project=args.project,
        env=args.env,
        build=args.build,
        job=args.job,
        version=args.version,
        desc=args.desc,
        action=args.action,
        timeout=args.timeout
    )
    
    # 发送结果通知
    if result['success']:
        client.send_stage_notification(
            "审批", "success", args.project, args.env, args.build,
            f"审批通过 - {result['data'].get('approver', '未知')}"
        )
        print(f"✅ 审批通过: {result['data'].get('message', '无消息')}")
        sys.exit(0)
    else:
        status = result['status']
        message = result.get('message', '无消息')
        
        if status == 'rejected':
            client.send_stage_notification(
                "审批", "failed", args.project, args.env, args.build,
                f"审批被拒绝 - {message}"
            )
            print(f"❌ 审批被拒绝: {message}")
            sys.exit(1)
        elif status == 'timeout':
            client.send_stage_notification(
                "审批", "failed", args.project, args.env, args.build,
                f"审批超时 - {message}"
            )
            print(f"⏰ 审批超时: {message}")
            sys.exit(2)
        else:
            client.send_stage_notification(
                "审批", "failed", args.project, args.env, args.build,
                f"审批失败 - {message}"
            )
            print(f"❌ 审批失败: {message}")
            sys.exit(3)

if __name__ == '__main__':
    main()

