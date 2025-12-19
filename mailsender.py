import os
from dotenv import load_dotenv
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import aiosmtplib
from typing import List, Optional
import logging

# 加载 .env 文件
load_dotenv()

# 重要：建议使用环境变量管理敏感信息[citation:8]
bool_map = {"True": True, "False": False, "true": True, "false": False}
SEND_MAIL_SWITCH = bool_map.get(os.environ.get("SEND_MAIL_SWITCH"))
SEND_MAIL_HOST = os.environ.get("SEND_MAIL_HOST")  # 例如Gmail
SEND_MAIL_PORT = int(os.environ.get("SEND_MAIL_PORT"))
SEND_MAIL_USERNAME = os.environ.get("SEND_MAIL_USERNAME")
SEND_MAIL_PASSWORD = os.environ.get("SEND_MAIL_PASSWORD")  # 使用专用密码或授权码
SEND_MAIL_RECIPIENTS = os.environ.get("SEND_MAIL_RECIPIENTS").split(",")

async def send(
        sender: str,
        recipients: List[str],
        subject: str,
        body: str,
        smtp_server: str,
        smtp_port: int,
        username: str,
        password: str,
        use_tls: bool = True,
        html_body: Optional[str] = None
) -> bool:
    """
    使用 aiosmtplib 异步发送邮件。

    Args:
        sender: 发件人邮箱地址
        recipients: 收件人邮箱地址列表
        subject: 邮件主题
        body: 邮件正文（纯文本）
        smtp_server: SMTP服务器地址 (如: smtp.gmail.com)
        smtp_port: SMTP服务器端口 (如: 587)
        username: 登录用户名（通常是邮箱地址）
        password: 登录密码或应用专用密码
        use_tls: 是否使用TLS加密（默认True）
        html_body: HTML格式的邮件正文（可选）

    Returns:
        bool: 发送成功返回True，失败返回False
    """
    try:
        # 1. 创建邮件消息
        if html_body:
            # 创建多部分消息（同时包含纯文本和HTML）
            message = MIMEMultipart('alternative')
            message.attach(MIMEText(body, 'plain', 'utf-8'))
            message.attach(MIMEText(html_body, 'html', 'utf-8'))
        else:
            # 创建纯文本消息
            message = MIMEText(body, 'plain', 'utf-8')

        # 2. 设置邮件头
        message['From'] = sender
        message['To'] = ', '.join(recipients)  # 多个收件人用逗号分隔
        message['Subject'] = subject

        # 3. 连接SMTP服务器并发送
        smtp = aiosmtplib.SMTP(
            hostname=smtp_server,
            port=smtp_port,
            use_tls=use_tls
        )

        await smtp.connect()

        # 如果使用TLS，需要启动TLS加密
        if use_tls and smtp_port == 587:
            await smtp.starttls()

        # 登录到邮件服务器
        await smtp.login(username, password)

        # 发送邮件
        await smtp.sendmail(
            sender,
            recipients,
            message.as_string()
        )

        # 退出连接
        await smtp.quit()

        logging.info(f"邮件发送成功！收件人: {', '.join(recipients)}")
        return True

    except Exception as e:
        logging.error(f"邮件发送失败: {e}")
        return False

# 使用示例
async def send_email_async(subject, body):
    if not SEND_MAIL_SWITCH:
        logging.info("邮件发送开关未开启")
        return

    # 配置邮件参数（请替换为你的实际信息）
    email_config = {
        'sender': SEND_MAIL_USERNAME,  # 发件人邮箱
        'recipients': SEND_MAIL_RECIPIENTS,  # 收件人列表
        'subject': subject,  # 邮件主题
        'body': body,  # 纯文本正文
        'smtp_server': SEND_MAIL_HOST,  # SMTP服务器
        'smtp_port': SEND_MAIL_PORT,  # SMTP端口
        'username': SEND_MAIL_USERNAME,  # 登录用户名
        'password': SEND_MAIL_PASSWORD,  # 密码或应用专用密码
        'use_tls': True,  # 使用TLS加密
    }

    # 发送纯文本邮件
    success = await send(**email_config)

    if success:
        logging.info("纯文本邮件发送完成")


# 运行示例
if __name__ == "__main__":
    asyncio.run(send_email_async('测试邮件主题','这是一封测试邮件的正文内容。'))
