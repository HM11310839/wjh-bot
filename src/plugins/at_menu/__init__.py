from nonebot import on_message
from nonebot.rule import to_me
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Event
from nonebot.adapters import Message
from nonebot.params import CommandArg
import os
import time
from datetime import datetime, timedelta
import random
import psutil

from . import manager

json_folder = r"D:\wjhBot"
manager = manager.JobManager(json_folder)
job_list = []
commands = ['info - 显示此页面', 'about - 关于', 'list - 显示列表', 'search <name> - 查询相关答案']
mottos = ["有这时间看QQ还不如多背两个英语单词","金考卷做了吗!?"]
#TODO - 添加英语课信息
eng = [
    "下午最后一节",
    ""
]
info = on_command(cmd="info",aliases={'time'},rule=to_me(), priority=9, block=True)
about = on_command(cmd="about",aliases={'a'},rule=to_me(), priority=9, block=True)
answer = on_message(rule=to_me(), priority=10, block=True)
search = on_command(cmd="search",aliases={'s'},rule=to_me(), priority=9, block=True)
listjobs = on_command(cmd="list",aliases={'l'},rule=to_me(), priority=9, block=True)

def key1(a):
    try:
        return a['test_name']
    except:
        return a

def key2(a):
    try:
        return a[2]
    except:
        return a

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

def load_jobs():
    global job_list
    jobs = manager.list_jobs()
    jobs.sort(key=key1)
    job_list = [(i['test_name'],i['job_hash'],i['book_id']) for i in jobs]

def list_jobs():
    result = "List ->\n"
    if not job_list:
        load_jobs()
    if not job_list:
        result += "No info"
    else:
        for i in range(len(job_list)):
            result += f"    *{i+1:<2} {job_list[i][0]}\n"
    return result

def get_this_week():
    today = datetime.today()
    monday = today - timedelta(days=today.weekday())
    sunday = today - timedelta(days=today.weekday() - 6)
    if sunday.month != monday.month:
        info = manager.search_jobs(f"{monday.strftime('%#m.%#d-')}{sunday.strftime('%#m.%#d')}日听力练习")
    else:
        info = manager.search_jobs(f"{monday.strftime('%#m.%#d-')}{sunday.strftime('%#d')}日听力练习")
    info.sort(key=key2)
    return info

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
    cmds = "".join([f"    /{i}\n" for i in commands])
    info_text = (
        "==========Info==========\n"
        f"time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}\n"
        f"this week: {monday.strftime('%m.%d-')}{sunday.strftime('%d')}\n"
        f"{msg}\n"
        f"{list_jobs()}\n"
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
        "GitHub: https://github.com/HM11310839/wjh-bot\n\n"
        "  - " + random.choice(mottos)
    )
    await about.finish(about_text)

@listjobs.handle()
async def handle_listjobs(event: Event):
    await listjobs.finish(list_jobs())

@answer.handle()
async def handle_answer(event: Event):
    # Get Answer
    week = get_this_week()
    if week:
        for job in week:
            job_hash, book_id, job_name = job
            text = f"{job_name}\n"
            ans = manager.get_answers(job_hash, book_id)
            if ans:
                for i in range(len(ans)):
                    text += f"#{i+1:<2} {ans[i]}\n"
            else:
                text += f"Error.2 Get answers failed.\n{job_hash} {book_id}"
            await answer.send(text)
        answer.finish()
    else:
        await answer.finish("Error.1 Get answers failed.\nNo this week information.\n"+ list_jobs())

@search.handle()
async def handle_search(args: Message = CommandArg()):
    name = args.extract_plain_text().strip()
    if name:
        info = manager.search_jobs(name)
        info.sort(key=key2)
        if info:
            result = f"有关 {name} 的查询结果：\n\n"
            for job in info:
                job_hash, book_id, job_name = job
                text = f"{job_name}\n"
                ans = manager.get_answers(job_hash, book_id)
                if ans:
                    for i in range(len(ans)):
                        text += f"#{i + 1:<2} {ans[i]}\n"
                else:
                    text += f"Error.3 Get answers failed.\n{job_hash} {book_id}"
                result += text
                result += '\n'
            await answer.finish(result)
        else:
            await answer.finish('没有查询到相关结果...')
    else:
        await answer.finish("输入参数有误 @... /search <name>")