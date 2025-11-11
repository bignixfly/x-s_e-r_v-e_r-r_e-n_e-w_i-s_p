#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XServer GAME 自动登录和续期脚本
(IMAP 版本 - 适用于 serv00.com 等标准邮箱)
"""

# =====================================================================
#                         导入依赖
# =====================================================================

import asyncio
import time
import re
import datetime
from datetime import timezone, timedelta
import os
import json
import requests
import imaplib  # <-- 新增：用于IMAP
import email      # <-- 新增：用于解析邮件
from email.header import decode_header
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

# =====================================================================
#                         配置区域
# =====================================================================

# 浏览器配置
IS_GITHUB_ACTIONS = os.getenv("GITHUB_ACTIONS") == "true"
USE_HEADLESS = IS_GITHUB_ACTIONS or os.getenv("USE_HEADLESS", "false").lower() == "true"
WAIT_TIMEOUT = 10000    # 页面元素等待超时时间（毫秒）
PAGE_LOAD_DELAY = 3     # 页面加载延迟时间（秒）

# XServer登录配置 (您必须在环境变量中设置)
LOGIN_EMAIL = os.getenv("XSERVER_EMAIL")
LOGIN_PASSWORD = os.getenv("XSERVER_PASSWORD")
TARGET_URL = "https://secure.xserver.ne.jp/xapanel/login/xmgame"

# --- 新增：IMAP 邮箱配置 ---
# 您必须在 GitHub Secrets 或 .env 文件中设置以下所有变量
# -----------------------------------------------------------------
# serv00.com IMAP 服务器地址
IMAP_SERVER = os.getenv("IMAP_SERVER", "mail1.serv00.com")
# serv00.com IMAP SSL 端口
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
# 您的 serv00.com 完整邮箱地址
IMAP_USER = os.getenv("IMAP_USER", "smileh81317@smileh81317.serv00.net")
# 您的 serv00.com 邮箱密码 (!!! 必须设置 !!!)
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD")

# --- 新增：邮件过滤配置 (已根据您的日志更新默认值) ---
# XServer 发送验证码的 *发件人* 地址 (请确认是否准确)
XSERVER_SENDER = os.getenv("XSERVER_SENDER", "support@xserver.ne.jp")
# XServer 验证码邮件的 *主题* (请确认是否准确)
XSERVER_SUBJECT = os.getenv("XSERVER_SUBJECT", "【XServerアカウント】ログイン用認証コードのお知らせ")
# -----------------------------------------------------------------


# =====================================================================
#                   XServer 自动登录类 (IMAP 版本)
# =====================================================================

class XServerAutoLogin:
    """XServer GAME 自动登录主类 - IMAP 版本"""
    
    def __init__(self):
        """
        初始化 XServer GAME 自动登录器
        使用配置区域的设置
        """
        self.browser = None
        self.context = None
        self.page = None
        self.headless = USE_HEADLESS
        self.email = LOGIN_EMAIL
        self.password = LOGIN_PASSWORD
        self.target_url = TARGET_URL
        self.wait_timeout = WAIT_TIMEOUT
        self.page_load_delay = PAGE_LOAD_DELAY
        self.screenshot_count = 0
        
        # --- IMAP 邮箱配置 ---
        self.imap_server = IMAP_SERVER
        self.imap_port = IMAP_PORT
        self.imap_user = IMAP_USER
        self.imap_password = IMAP_PASSWORD
        self.xserver_sender = XSERVER_SENDER
        self.xserver_subject = XSERVER_SUBJECT
        
        # 续期状态跟踪
        self.old_expiry_time = None
        self.new_expiry_time = None
        self.renewal_status = "Unknown"
    
    
    # =================================================================
    #                       1. 浏览器管理模块
    # =================================================================
        
    async def setup_browser(self):
        """设置并启动 Playwright 浏览器"""
        try:
            playwright = await async_playwright().start()
            
            browser_args = [
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-notifications',
                '--window-size=1920,1080',
                '--lang=ja-JP',
                '--accept-lang=ja-JP,ja,en-US,en'
            ]
            
            self.browser = await playwright.chromium.launch(
                headless=self.headless,
                args=browser_args
            )
            
            self.context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                locale='ja-JP',
                timezone_id='Asia/Tokyo',
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            
            self.page = await self.context.new_page()
            
            await stealth_async(self.page)
            print("✅ Stealth 插件已应用")
            
            print("✅ Playwright 浏览器初始化成功")
            return True
            
        except Exception as e:
            print(f"❌ Playwright 浏览器初始化失败: {e}")
            return False
    
    async def take_screenshot(self, step_name=""):
        """截图功能 - 用于可视化调试"""
        try:
            if self.page:
                self.screenshot_count += 1
                beijing_time = datetime.datetime.now(timezone(timedelta(hours=8)))
                timestamp = beijing_time.strftime("%H%M%S")
                filename = f"step_{self.screenshot_count:02d}_{timestamp}_{step_name}.png"
                
                filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
                
                await self.page.screenshot(path=filename, full_page=True)
                print(f"📸 截图已保存: {filename}")
                
        except Exception as e:
            print(f"⚠️ 截图失败: {e}")
    
    def validate_config(self):
        """验证配置信息"""
        if not self.email or not self.password:
            print("❌ XSERVER_EMAIL 或 XSERVER_PASSWORD 未设置！")
            return False
            
        # --- 新增：验证 IMAP 配置 ---
        if not self.imap_user or not self.imap_password or not self.imap_server:
            print("❌ IMAP_USER, IMAP_PASSWORD 或 IMAP_SERVER 未设置！")
            print("   请确保您已在环境变量中设置了 serv00.com 的邮箱密码 (IMAP_PASSWORD)")
            return False
        
        print("✅ XServer 登录配置已加载")
        print(f"✅ IMAP 邮箱配置已加载 (用户: {self.imap_user})")
        return True
    
    async def cleanup(self):
        """清理资源"""
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            print("🧹 浏览器已关闭")
        except Exception as e:
            print(f"⚠️ 清理资源时出错: {e}")
    
    # =================================================================
    #                       2. 页面导航模块
    # =================================================================
    
    async def navigate_to_login(self):
        """导航到登录页面"""
        try:
            print(f"🌐 正在访问: {self.target_url}")
            await self.page.goto(self.target_url, wait_until='load')
            await self.page.wait_for_selector("body", timeout=self.wait_timeout)
            print("✅ 页面加载成功")
            await self.take_screenshot("login_page_loaded")
            return True
            
        except Exception as e:
            print(f"❌ 导航失败: {e}")
            return False
    
    
    # =================================================================
    #                       3. 登录表单处理模块
    # =================================================================
    
    async def find_login_form(self):
        """查找登录表单元素"""
        try:
            print("🔍 正在查找登录表单...")
            await asyncio.sleep(self.page_load_delay)
            
            email_selector = "input[name='memberid']"
            await self.page.wait_for_selector(email_selector, timeout=self.wait_timeout)

            password_selector = "input[name='user_password']"
            await self.page.wait_for_selector(password_selector, timeout=self.wait_timeout)

            login_button_selector = "input[value='ログインする']"
            await self.page.wait_for_selector(login_button_selector, timeout=self.wait_timeout)
            
            print("✅ 找到登录表单元素")
            return email_selector, password_selector, login_button_selector
            
        except Exception as e:
            print(f"❌ 查找登录表单时出错: {e}")
            return None, None, None
    
    async def human_type(self, selector, text):
        """模拟人类输入行为"""
        for char in text:
            await self.page.type(selector, char, delay=100)
            await asyncio.sleep(0.05)
    
    async def perform_login(self):
        """执行登录操作"""
        try:
            print("🎯 开始执行登录操作...")
            
            email_selector, password_selector, login_button_selector = await self.find_login_form()
            
            if not email_selector or not password_selector:
                return False
            
            print("📝 正在填写登录信息...")
            
            await self.page.fill(email_selector, "")
            await self.human_type(email_selector, self.email)
            print("✅ 邮箱已填写")
            
            await asyncio.sleep(2)
            
            await self.page.fill(password_selector, "")
            await self.human_type(password_selector, self.password)
            print("✅ 密码已填写")
            
            await asyncio.sleep(2)
            
            if login_button_selector:
                print("🖱️ 点击登录按钮...")
                await self.page.click(login_button_selector)
            else:
                print("⌨️ 使用回车键提交...")
                await self.page.press(password_selector, "Enter")
            
            print("✅ 登录表单已提交")
            await asyncio.sleep(5)
            return True
            
        except Exception as e:
            print(f"❌ 登录操作失败: {e}")
            return False
    
    
    # =================================================================
    #                       4. 验证码处理模块 (IMAP 版本)
    # =================================================================
    
    async def handle_verification_page(self):
        """处理验证页面 - 检测是否需要验证"""
        try:
            print("🔍 检查是否需要验证...")
            await self.take_screenshot("checking_verification_page")
            await asyncio.sleep(3)
            
            current_url = self.page.url
            print(f"📍 当前URL: {current_url}")
            
            if "loginauth/index" in current_url:
                print("🔐 检测到XServer新环境验证页面！")
                
                print("🔍 正在查找发送验证码按钮...")
                selector = "input[value*='送信']"
                
                try:
                    await self.page.wait_for_selector(selector, timeout=self.wait_timeout)
                    print("✅ 找到发送验证码按钮")
                    print("📧 点击发送验证码按钮，验证码将发送到您的邮箱")
                    await self.page.click(selector)
                    print("✅ 已点击发送验证码按钮")
                except Exception as e:
                    print(f"❌ 查找发送验证码按钮失败: {e}")
                    return False
                
                await asyncio.sleep(5)
                return await self.handle_code_input_page()
            
            return True
            
        except Exception as e:
            print(f"❌ 处理验证页面时出错: {e}")
            return False
    
    async def handle_code_input_page(self):
        """处理验证码输入页面 - 自动获取并输入验证码"""
        try:
            print("🔍 检查是否跳转到验证码输入页面...")
            current_url = self.page.url
            print(f"📍 当前URL: {current_url}")
            
            if "loginauth/smssend" in current_url:
                print("✅ 成功跳转到验证码输入页面！")
                print("📧 验证码已发送到您的邮箱")
                
                code_input_selector = "input[id='auth_code'][name='auth_code']"
                
                try:
                    await self.page.wait_for_selector(code_input_selector, timeout=self.wait_timeout)
                    print("✅ 找到验证码输入框")
                    
                    # --- 关键修改 ---
                    # 调用新的 IMAP 函数，而不是旧的 cloudmail 函数
                    print("📬 正在调用 IMAP 函数获取验证码...")
                    verification_code = await self.get_verification_code_from_imap()
                    # -----------------
                    
                    if verification_code:
                        return await self.input_verification_code(verification_code)
                    else:
                        print("❌ 自动获取验证码失败")
                        return False
                
                except Exception as e:
                    print(f"❌ 未找到验证码输入框: {e}")
                    return False
            else:
                print("⚠️ 未检测到验证码输入页面，可能已直接登录成功")
                return True
            
        except Exception as e:
            print(f"❌ 处理验证码输入页面时出错: {e}")
            return False
    
    async def input_verification_code(self, verification_code: str):
        """输入验证码并提交"""
        try:
            print(f"🔑 正在输入验证码: {verification_code}")
            await asyncio.sleep(2)
            
            code_input_selector = "input[id='auth_code'][name='auth_code']"
            
            await self.page.fill(code_input_selector, "")
            await asyncio.sleep(1)
            await self.human_type(code_input_selector, verification_code)
            print("✅ 验证码已输入")
            
            await asyncio.sleep(2)
            
            print("🔍 正在查找ログイン按钮...")
            login_submit_selector = "input[type='submit'][value='ログイン']"
            await self.page.wait_for_selector(login_submit_selector, timeout=self.wait_timeout)
            print("✅ 找到ログイン按钮")
            
            await asyncio.sleep(1)
            await self.page.click(login_submit_selector)
            print("✅ 验证码已提交")
            
            await asyncio.sleep(8)
            return True
            
        except Exception as e:
            print(f"❌ 输入验证码失败: {e}")
            await self.take_screenshot("verification_input_failed")
            return False

    
    # --- (保留) 验证码提取函数 ---
    def _extract_verification_code(self, mail_content: str):
        """
        从邮件内容中提取验证码 (此函数被保留，因为 IMAP 仍需要它)
        """
        # 验证码匹配模式（格式：【認証コード】　　　　　　　： 88617）
        pattern = r'【認証コード】[\s　]+[：:]\s*(\d{4,8})'
        
        matches = re.findall(pattern, mail_content, re.IGNORECASE | re.MULTILINE)
        if matches:
            valid_codes = [code for code in matches if 4 <= len(code) <= 8]
            if valid_codes:
                return valid_codes[0]
        
        print("❌ 未能匹配到验证码")
        print(f"📝 邮件内容长度: {len(mail_content)} 字符")
        for line in mail_content.split('\n'):
            if '認証コード' in line:
                print(f"🔍 包含認証コード的行: {line}")
        
        return None

    # --- (新增/已修复) IMAP 验证码获取函数 ---
    async def get_verification_code_from_imap(self):
        try:
            print("📧 开始从 IMAP 获取验证码...")
            await asyncio.sleep(15)
    
            print(f"🚀 正在连接 IMAP 服务器: {self.imap_server}:{self.imap_port}")
            mail = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
    
            print(f"🔑 正在登录邮箱: {self.imap_user}")
            mail.login(self.imap_user, self.imap_password)
    
            mail.select("inbox")
            print("📬 已进入收件箱")
    
            # 避免日文编码错误：只用 FROM 搜索
            status, messages = mail.search(None, 'FROM', f'"{self.xserver_sender}"')
            if status != "OK":
                print("❌ 搜索邮件失败")
                mail.logout()
                return None
    
            mail_ids = messages[0].split()
            if not mail_ids:
                print(f"❌ 未找到来自 {self.xserver_sender} 的邮件")
                mail.logout()
                return None
    
            print(f"✅ 找到 {len(mail_ids)} 封邮件，开始匹配主题...")
    
            def decode_subject(raw_subject):
                decoded_parts = decode_header(raw_subject)
                subject = ""
                for part, enc in decoded_parts:
                    if isinstance(part, bytes):
                        subject += part.decode(enc or "utf-8", errors="ignore")
                    else:
                        subject += part
                return subject.strip()
    
            # 从最新开始遍历
            for mail_id in reversed(mail_ids):
                status, data = mail.fetch(mail_id, "(RFC822)")
                if status != "OK":
                    continue
    
                msg = email.message_from_bytes(data[0][1])
                raw_subject = msg.get("Subject", "")
                subject = decode_subject(raw_subject)
    
                print(f"📧 收到邮件主题: {subject}")
                if self.xserver_subject.strip() not in subject:
                    continue  # 跳过不匹配的邮件
    
                print(f"✅ 匹配成功的邮件主题: {subject}")
    
                # 提取正文
                mail_content = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition")):
                            charset = part.get_content_charset()
                            mail_content = part.get_payload(decode=True).decode(charset or "utf-8", errors="ignore")
                            break
                else:
                    charset = msg.get_content_charset()
                    mail_content = msg.get_payload(decode=True).decode(charset or "utf-8", errors="ignore")
    
                mail.logout()
                print("🔒 已登出 IMAP 服务器")
    
                if not mail_content:
                    print("❌ 邮件内容为空或无法解析")
                    return None
    
                verification_code = self._extract_verification_code(mail_content)
                if verification_code:
                    print(f"🎉 成功提取验证码: {verification_code}")
                    return verification_code
                else:
                    print("❌ 未能在邮件正文中找到验证码")
                    return None
    
            print("❌ 所有邮件中都未找到匹配主题")
            mail.logout()
            return None
    
        except imaplib.IMAP4.error as e:
            print(f"❌ IMAP 登录失败: {e}")
            return None
        except Exception as e:
            print(f"❌ 从 IMAP 获取验证码失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    
    # =================================================================
    #                       5. 登录结果处理模块
    # =================================================================
    
    async def handle_login_result(self):
        """处理登录结果"""
        try:
            print("🔍 正在检查登录结果...")
            await asyncio.sleep(3)
            current_url = self.page.url
            print(f"📍 当前URL: {current_url}")
            
            success_url = "https://secure.xserver.ne.jp/xapanel/xmgame/index"
            
            if current_url == success_url:
                print("✅ 登录成功！已跳转到XServer GAME管理页面")
                print("⏰ 等待页面加载完成...")
                await asyncio.sleep(3)
                
                print("🔍 正在查找ゲーム管理按钮...")
                try:
                    game_button_selector = "a:has-text('ゲーム管理')"
                    await self.page.wait_for_selector(game_button_selector, timeout=self.wait_timeout)
                    print("✅ 找到ゲーム管理按钮")
                    
                    print("🖱️ 正在点击ゲーム管理按钮...")
                    await self.page.click(game_button_selector)
                    print("✅ 已点击ゲーム管理按钮")
                    
                    await asyncio.sleep(5)
                    
                    final_url = self.page.url
                    print(f"📍 最终页面URL: {final_url}")
                    
                    expected_game_url = "https://secure.xserver.ne.jp/xmgame/game/index"
                    if expected_game_url in final_url:
                        print("✅ 成功点击ゲーム管理按钮并跳转到游戏管理页面")
                        await self.take_screenshot("game_page_loaded")
                        
                        await self.get_server_time_info()
                    else:
                        print(f"⚠️ 跳转到游戏页面可能失败")
                        await self.take_screenshot("game_page_redirect_failed")
                        
                except Exception as e:
                    print(f"❌ 查找或点击ゲーム管理按钮时出错: {e}")
                    await self.take_screenshot("game_button_error")
                
                return True
            else:
                print(f"❌ 登录失败！当前URL不是预期的成功页面")
                return False
            
        except Exception as e:
            print(f"❌ 检查登录结果时出错: {e}")
            return False
            
    # =================================================================
    #                       6. 续期模块 (未更改)
    # =================================================================
    
    async def get_server_time_info(self):
        """获取服务器时间信息"""
        try:
            print("🕒 正在获取服务器时间信息...")
            await asyncio.sleep(3)
            
            try:
                elements = await self.page.locator("text=/残り\\d+時間\\d+分/").all()
                
                for element in elements:
                    element_text = await element.text_content()
                    element_text = element_text.strip() if element_text else ""
                    
                    if element_text and len(element_text) < 200 and "残り" in element_text and "時間" in element_text:
                        print(f"✅ 找到时间元素: {element_text}")
                        
                        remaining_match = re.search(r'残り(\d+時間\d+分)', element_text)
                        if remaining_match:
                            remaining_raw = remaining_match.group(1)
                            remaining_formatted = self.format_remaining_time(remaining_raw)
                            print(f"⏰ 剩余时间: {remaining_formatted}")
                        
                        expiry_match = re.search(r'\((\d{4}-\d{2}-\d{2})まで\)', element_text)
                        if expiry_match:
                            expiry_raw = expiry_match.group(1)
                            expiry_formatted = self.format_expiry_date(expiry_raw)
                            print(f"📅 到期时间: {expiry_formatted}")
                            self.old_expiry_time = expiry_formatted
                        
                        break
                        
            except Exception as e:
                print(f"❌ 获取时间信息时出错: {e}")
            
            await self.click_upgrade_button()
            
        except Exception as e:
            print(f"❌ 获取服务器时间信息失败: {e}")
    
    def format_remaining_time(self, time_str):
        return time_str
    
    def format_expiry_date(self, date_str):
        return date_str
    
    async def click_upgrade_button(self):
        """点击升级延长按钮"""
        try:
            print("🔄 正在查找アップグレード・期限延長按钮...")
            
            upgrade_selector = "a:has-text('アップグレード・期限延長')"
            await self.page.wait_for_selector(upgrade_selector, timeout=self.wait_timeout)
            print("✅ 找到アップグレード・期限延長按钮")
            
            await self.page.click(upgrade_selector)
            print("✅ 已点击アップグレード・期限延長按钮")
            
            await asyncio.sleep(5)
            await self.verify_upgrade_page()
            
        except Exception as e:
            print(f"❌ 点击升级按钮失败: {e}")
    
    async def verify_upgrade_page(self):
        """验证升级页面"""
        try:
            current_url = self.page.url
            expected_url = "https://secure.xserver.ne.jp/xmgame/game/freeplan/extend/index"
            
            print(f"📍 升级页面URL: {current_url}")
            
            if expected_url in current_url:
                print("✅ 成功跳转到升级页面")
                await self.check_extension_restriction()
            else:
                print(f"❌ 升级页面跳转失败")
                
        except Exception as e:
            print(f"❌ 验证升级页面失败: {e}")
    
    async def check_extension_restriction(self):
        """检查期限延长限制信息"""
        try:
            print("🔍 正在检测期限延长限制提示...")
            
            restriction_selector = "text=/残り契約時間が24時間を切るまで、期限の延長は行えません/"
            
            try:
                element = await self.page.wait_for_selector(restriction_selector, timeout=5000)
                restriction_text = await element.text_content()
                print(f"✅ 找到期限延长限制信息")
                print(f"📝 限制信息: {restriction_text}")
                self.renewal_status = "Unexpired" # 未到期
                return True
                
            except Exception:
                print("ℹ️ 未找到期限延长限制信息，可以进行延长操作")
                await self.perform_extension_operation()
                return False
                
        except Exception as e:
            print(f"❌ 检测期限延长限制失败: {e}")
            return True
    
    async def perform_extension_operation(self):
        """执行期限延长操作"""
        try:
            print("🔄 开始执行期限延长操作...")
            await self.click_extension_button()
            
        except Exception as e:
            print(f"❌ 执行期限延长操作失败: {e}")
    
    async def click_extension_button(self):
        """点击期限延长按钮"""
        try:
            print("🔍 Zha '期限を延長する' an ...")
            
            extension_selector = "a:has-text('期限を延長する')"
            
            await self.page.wait_for_selector(extension_selector, timeout=self.wait_timeout)
            print("✅ 找到'期限を延長する'按钮")
            
            await self.page.click(extension_selector)
            print("✅ 已点击'期限を延長する'按钮")
            
            print("⏰ 等待页面跳转...")
            await asyncio.sleep(5)
            
            await self.verify_extension_input_page()
            return True
            
        except Exception as e:
            print(f"❌ 点击期限延长按钮失败: {e}")
            return False
    
    async def verify_extension_input_page(self):
        """验证是否成功跳转到期限延长输入页面"""
        try:
            current_url = self.page.url
            expected_url = "https://secure.xserver.ne.jp/xmgame/game/freeplan/extend/input"
            
            print(f"📍 当前页面URL: {current_url}")
            
            if expected_url in current_url:
                print("🎉 成功跳转到期限延长输入页面！")
                await self.take_screenshot("extension_input_page")
                await self.click_confirmation_button()
                return True
            else:
                print(f"❌ 页面跳转失败")
                return False
            
        except Exception as e:
            print(f"❌ 验证期限延长输入页面失败: {e}")
            return False
            
    async def click_confirmation_button(self):
        """点击確認画面に進む按钮"""
        try:
            print("🔍 正在查找'確認画面に進む'按钮...")
            
            confirmation_selector = "button[type='submit']:has-text('確認画面に進む')"
            await self.page.wait_for_selector(confirmation_selector, timeout=self.wait_timeout)
            print("✅ 找到'確認画面に進む'按钮")
            
            await self.page.click(confirmation_selector)
            print("✅ 已点击'確認画面に進む'按钮")
            
            print("⏰ 等待页面跳转...")
            await asyncio.sleep(5)
            
            await self.click_final_extension_button()
            return True
            
        except Exception as e:
            print(f"❌ 点击確認画面に進む按钮失败: {e}")
            return False
            
    async def click_final_extension_button(self):
        """点击最終的'期限を延長する'按钮 (确认页面)"""
        try:
            print("🔍 正在查找最终的'期限を延長する'按钮...")
            
            final_button_selector = "button[type='submit']:has-text('期限を延長する')"
            await self.page.wait_for_selector(final_button_selector, timeout=self.wait_timeout)
            print("✅ 找到最终的'期限を延長する'按钮")
            
            await self.page.click(final_button_selector)
            print("✅ 已点击最终的'期限を延長する'按钮")
            
            print("⏰ 正在处理续期...")
            await asyncio.sleep(8)
            
            await self.verify_extension_complete()
            return True
            
        except Exception as e:
            print(f"❌ 点击最终的'期限を延長する'按钮失败: {e}")
            return False
            
    async def verify_extension_complete(self):
        """验证续期是否完成"""
        try:
            current_url = self.page.url
            expected_url = "https://secure.xserver.ne.jp/xmgame/game/freeplan/extend/complete"
            
            print(f"📍 续期结果页面URL: {current_url}")
            
            if expected_url in current_url:
                print("🎉 续期成功！")
                await self.take_screenshot("extension_complete")
                self.renewal_status = "Success"
                await self.get_new_expiry_time()
            else:
                print("❌ 续期失败")
                self.renewal_status = "Failed"
                await self.take_screenshot("extension_failed")
                
        except Exception as e:
            print(f"❌ 验证续期完成页面失败: {e}")
            self.renewal_status = "Failed"
            
    async def get_new_expiry_time(self):
        """获取新的到期时间"""
        try:
            print("📅 正在获取新的到期时间...")
            
            # 查找 "YYYY-MM-DD まで" 格式的文本
            expiry_selector = "text=/\\d{4}-\\d{2}-\\d{2} まで/"
            element = await self.page.wait_for_selector(expiry_selector, timeout=self.wait_timeout)
            
            element_text = await element.text_content()
            expiry_match = re.search(r'(\d{4}-\d{2}-\d{2}) まで', element_text)
            
            if expiry_match:
                self.new_expiry_time = expiry_match.group(1)
                print(f"✅ 新的到期时间: {self.new_expiry_time}")
            else:
                print("⚠️ 未能解析新的到期时间")
                
        except Exception as e:
            print(f"❌ 获取新的到期时间失败: {e}")

    # =================================================================
    #                       7. 主执行流程
    # =================================================================
    
    async def run(self):
        """主执行流程"""
        print("🚀 === XServer 自动续期脚本 (IMAP版) 开始运行 ===")
        start_time = time.time()
        
        if not self.validate_config():
            return

        if not await self.setup_browser():
            return
        
        try:
            # 步骤1: 导航到登录页
            if not await self.navigate_to_login():
                raise Exception("导航到登录页失败")
            
            # 步骤2: 执行登录
            if not await self.perform_login():
                raise Exception("执行登录失败")

            # 步骤3: 处理验证 (如果需要)
            # handle_verification_page 会自动调用 handle_code_input_page 和 get_verification_code_from_imap
            if not await self.handle_verification_page():
                raise Exception("处理验证码页面失败")

            # 步骤4: 处理登录结果 (会自动触发续期流程)
            if not await self.handle_login_result():
                # 检查是否是登录失败，还是验证码错误
                current_url = self.page.url
                if "loginauth/smssend" in current_url:
                    print("❌ 验证码错误或已过期")
                    await self.take_screenshot("verification_code_error")
                else:
                    print("❌ 登录失败 (用户名或密码错误?)")
                    await self.take_screenshot("login_failed")
                raise Exception("登录或验证失败")

            print("\n✅ === 任务执行完毕 ===")
            
        except Exception as e:
            print(f"\n❌ === 任务执行中出错 ===\n错误: {e}")
            await self.take_screenshot("runtime_error")
        
        finally:
            await self.cleanup()
            end_time = time.time()
            print(f"🏃 脚本总耗时: {end_time - start_time:.2f} 秒")
            
            # 打印续期结果
            print("\n--- 续期结果 ---")
            print(f"原到期时间: {self.old_expiry_time or '未获取'}")
            print(f"新到期时间: {self.new_expiry_time or 'N/A'}")
            print(f"续期状态: {self.renewal_status}")
            print("====================\n")


# =====================================================================
#                         脚本入口
# =====================================================================

async def main():
    login_instance = XServerAutoLogin()
    await login_instance.run()

if __name__ == "__main__":
    asyncio.run(main())
