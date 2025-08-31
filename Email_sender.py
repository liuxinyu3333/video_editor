import os, mimetypes, smtplib, argparse, ssl
from email.message import EmailMessage

def send_mail(smtp_host, smtp_port, username, password, mail_from, mail_to, subject, body, filepath, debug=False):
    # ---- 基础校验 ----
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"文件不存在：{filepath}")
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

    ctype, _ = mimetypes.guess_type(filepath)
    maintype, subtype = (ctype.split("/", 1) if ctype else ("application", "octet-stream"))
    with open(filepath, "rb") as f:
        msg.add_attachment(f.read(), maintype=maintype, subtype=subtype,
                           filename=os.path.basename(filepath))

    # ---- 建立连接并发送 ----
    context = ssl.create_default_context()
    if smtp_port == 465:
        server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=60, context=context)
    else:
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=60)

    try:
        if debug:
            server.set_debuglevel(1)  # 打印 SMTP 会话
        server.ehlo()

        if smtp_port != 465:
            # 587 需要 STARTTLS
            server.starttls(context=context)
            server.ehlo()

        server.login(username, password)
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except Exception:
            pass

def main(body_text: str | None = None, target_email: str | None = None):
    p = argparse.ArgumentParser(description="发送附件到邮箱（QQ 邮箱）")

    # QQ 邮箱推荐配置
    p.add_argument("--host", default="smtp.qq.com", help="SMTP 服务器（QQ：smtp.qq.com）")
    p.add_argument("--port", type=int, default=587, help="SMTP 端口：465(SSL) 或 587(STARTTLS)")

    p.add_argument("--user", default="1758107959@qq.com", help="邮箱账号（完整 QQ 邮箱）")
    p.add_argument("--pwd",  default="tcsivyrmyqwfbiab", help="QQ 邮箱授权码（不是QQ密码）")

    p.add_argument("--mail_from", default="1758107959@qq.com", help="发件人邮箱（需与账号相同）")
    p.add_argument("--to", default="xinyu.liu1@rwth-aachen.de", help="收件人邮箱")

    p.add_argument("--sub", default="gpt生成的文件", help="邮件主题")
    p.add_argument("--body", default="见附件。", help="正文")
    p.add_argument("--file", default="gpt_replies.txt", help="要发送的文件路径")

    p.add_argument("--debug", action="store_true", help="打印 SMTP 调试信息")

    args = p.parse_args()

    # 允许用环境变量隐藏敏感信息
    user = args.user or os.getenv("MAIL_USER", "")
    pwd  = args.pwd  or os.getenv("MAIL_PASS", "")
    if body_text is not None:
        args.body = body_text
    if target_email is not None:
        args.to = target_email
    send_mail(args.host, args.port, user, pwd, args.mail_from,
              args.to, args.sub, args.body, args.file, debug=args.debug)
    print("✅ 已发送")

if __name__ == "__main__":
    main()
