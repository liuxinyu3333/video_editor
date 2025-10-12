import os, mimetypes, smtplib, argparse, ssl
from email.message import EmailMessage
from typing import List
import time

def send_mail(smtp_host, smtp_port, username, password, mail_from, mail_to, subject, body, filepaths: List[str], debug=False, connection_pool=None):
    # ---- 基础校验 ----
    if not username or not password:
        raise ValueError("请提供完整的邮箱账号与授权码（QQ 必须使用授权码，不是登录密码）")
    if not mail_from:
        raise ValueError("发件人邮箱 mail_from 不能为空")
    # QQ 邮箱要求发件人与登录账号一致
    if mail_from.strip().lower() != username.strip().lower():
        raise ValueError(f"发件人({mail_from})必须与登录账号({username})一致（QQ 邮箱限制）")

    # ---- 组装邮件 ----
    msg = EmailMessage()
    msg["From"] = mail_from
    msg["To"] = mail_to
    msg["Subject"] = subject
    msg.set_content(body)

    # 添加多个附件
    for filepath in filepaths:
        if not os.path.isfile(filepath):
            print(f"[WARN] 文件不存在，跳过：{filepath}")
            continue
            
        ctype, _ = mimetypes.guess_type(filepath)
        maintype, subtype = (ctype.split("/", 1) if ctype else ("application", "octet-stream"))
        with open(filepath, "rb") as f:
            msg.add_attachment(f.read(), maintype=maintype, subtype=subtype,
                               filename=os.path.basename(filepath))
        print(f"[INFO] 已添加附件：{os.path.basename(filepath)}")

    # ---- 建立连接并发送 ----
    if connection_pool and connection_pool.get('server'):
        # 复用连接
        server = connection_pool['server']
        try:
            server.send_message(msg)
            print(f"[SUCCESS] 邮件发送成功！（复用连接）")
            return server  # 返回连接供下次使用
        except Exception as e:
            print(f"[ERROR] 复用连接发送失败，尝试重新连接：{e}")
            try:
                server.quit()
            except:
                pass
            connection_pool['server'] = None
    
    # 新建连接
    context = ssl.create_default_context()
    if smtp_port == 465:
        server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30, context=context)  # 减少超时时间
    else:
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)  # 减少超时时间

    try:
        if debug:
            server.set_debuglevel(1)  # 打印 SMTP 会话
        server.ehlo()

        if smtp_port != 465:
            # 587 需要 STARTTLS
            server.starttls(context=context)
            server.ehlo()

        server.login(username, password)
        print(f"[INFO] 登录成功，准备发送邮件到：{mail_to}")
        server.send_message(msg)
        print(f"[SUCCESS] 邮件发送成功！")
        
        # 保存连接供下次使用
        if connection_pool is not None:
            connection_pool['server'] = server
            return server
        else:
            server.quit()
            return None
            
    except Exception as e:
        print(f"[ERROR] 发送失败：{e}")
        try:
            server.quit()
        except:
            pass
        raise

def send_mail_batch(smtp_host, smtp_port, username, password, mail_from, mail_list, subject, body, filepaths: List[str], debug=False):
    """批量发送邮件，复用连接"""
    connection_pool = {'server': None}
    
    for i, mail_to in enumerate(mail_list):
        print(f"\n[INFO] 发送第 {i+1}/{len(mail_list)} 封邮件到：{mail_to}")
        
        try:
            # 复用连接发送
            server = send_mail(smtp_host, smtp_port, username, password, mail_from, 
                             mail_to, subject, body, filepaths, debug, connection_pool)
            
            # 短暂等待，避免发送过快
            if i < len(mail_list) - 1:  # 不是最后一封
                time.sleep(2)  # 减少到2秒
                
        except Exception as e:
            print(f"[ERROR] 发送到 {mail_to} 失败：{e}")
            # 重置连接池
            if connection_pool.get('server'):
                try:
                    connection_pool['server'].quit()
                except:
                    pass
                connection_pool['server'] = None
            continue
    
    # 最后关闭连接
    if connection_pool.get('server'):
        try:
            connection_pool['server'].quit()
            print("[INFO] 已关闭SMTP连接")
        except:
            pass

def main(body_text: str | None = None, target_email: str | None = None, filepaths: List[str] | None = None, batch_mode: bool = False):
    p = argparse.ArgumentParser(description="发送附件到邮箱（QQ 邮箱）")

    # QQ 邮箱推荐配置
    p.add_argument("--host", default="smtp.qq.com", help="SMTP 服务器（QQ：smtp.qq.com）")
    p.add_argument("--port", type=int, default=587, help="SMTP 端口：465(SSL) 或 587(STARTTLS)")

    p.add_argument("--user", default="1758107959@qq.com", help="邮箱账号（完整 QQ 邮箱）")
    p.add_argument("--pwd",  default="tcsivyrmyqwfbiab", help="QQ 邮箱授权码（不是QQ密码）")

    p.add_argument("--mail_from", default="1758107959@qq.com", help="发件人邮箱（需与账号相同）")
    p.add_argument("--to", default="xinyu.liu1@rwth-aachen.de", help="收件人邮箱")
    p.add_argument("--batch", nargs="+", help="批量发送到多个邮箱")

    p.add_argument("--sub", default="gpt生成的文件", help="邮件主题")
    p.add_argument("--body", default="见附件。", help="正文")
    p.add_argument("--files", nargs="+", default=["gpt_replies.txt"], help="要发送的文件路径列表（可多个）")

    p.add_argument("--debug", action="store_true", help="打印 SMTP 调试信息")

    args = p.parse_args()

    # 允许用环境变量隐藏敏感信息
    user = args.user or os.getenv("MAIL_USER", "")
    pwd  = args.pwd  or os.getenv("MAIL_PASS", "")
    if body_text is not None:
        args.body = body_text
    if target_email is not None:
        args.to = target_email
    if filepaths is not None:
        args.files = filepaths
        
    print(f"[INFO] 开始发送邮件...")
    print(f"[INFO] 发件人：{args.mail_from}")
    print(f"[INFO] 附件：{args.files}")
    
    if args.batch:
        # 批量发送模式
        print(f"[INFO] 批量发送到 {len(args.batch)} 个邮箱")
        send_mail_batch(args.host, args.port, user, pwd, args.mail_from,
                       args.batch, args.sub, args.body, args.files, debug=args.debug)
    else:
        # 单发模式
        print(f"[INFO] 发送到：{args.to}")
        send_mail(args.host, args.port, user, pwd, args.mail_from,
                 args.to, args.sub, args.body, args.files, debug=args.debug)
    
    print("✅ 发送完成")

if __name__ == "__main__":
    files_to_send = [
        r"E:\coin_works\project\video_storage\DA 交易者聯盟\2025-08-26-DA交易者聯盟-1\2025-08-26-DA交易者聯盟-1.txt",    # 改成你的绝对路径
        r"E:\coin_works\project\video_storage\DA 交易者聯盟\2025-08-26-DA交易者聯盟-1\frames.zip",  # 改成你的绝对路径
    ]
    main(
        body_text= "这是新的视频帧zip和txt文件",
        filepaths= files_to_send
    )