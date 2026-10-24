from nonebot import on_message
from nonebot.rule import to_me
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Event

import os
import time
from datetime import datetime, timedelta
import random
import psutil

def turn_size(size)->str:
    """将 Size(byte) 转化为可读字符串"""
    if size == 0:
        return "0 B"
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    index = 0
    while size > 1024 and index < len(units) - 1:
        size /= 1024.0
        index += 1
    return f'{size:.2f} {units[index]}'

commands = ['info - 显示此页面', 'about - 关于']
mottos = ["有这时间看QQ还不如多背两个英语单词","金考卷做了吗!?"]
#TODO - 添加英语课信息
eng = [
    "下午最后一节",
    ""
]
info = on_command(cmd="info",aliases={'time'},rule=to_me(), priority=9, block=True)
about = on_command(cmd="about",rule=to_me(), priority=9, block=True)

@info.handle()
async def handle_info(event: Event):
    # 显示提示信息
    today = datetime.today()
    monday = today - timedelta(days=today.weekday())
    sunday = today - timedelta(days=today.weekday() - 6)
    cpu_usage = psutil.cpu_percent(interval=3)
    mem = psutil.virtual_memory()
    boot_time = datetime.fromtimestamp(psutil.boot_time()).strftime('%Y-%m-%d %H:%M:%S')
    msg = f"CPU {cpu_usage}%\nMEM {turn_size(mem.used)}/{turn_size(mem.total)} = {mem.percent}%\nBoot {boot_time}"
    cmds = "".join([f"    * /{i}\n" for i in commands])
    info_text = (
        "==========Info==========\n"
        f"time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}\n"
        f"this week: {monday.strftime('%m.%d-')}{sunday.strftime('%d')}\n"
        f"{msg}\n"
        f"commands:\n{cmds}"
    )
    await info.finish(info_text)

@about.handle()
async def handle_about(event: Event):
    # about
    about_text = (
        "==========About==========\n"
        "NapCap QQ + NoneBot2\n"
        "Python environment\n"
        "GitHub: "
        "  - " + random.choice(mottos)
    )
    await about.finish(about_text)