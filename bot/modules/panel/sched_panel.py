import asyncio
import os

import requests
from pyrogram import filters
from pyrogram.types import Message

from bot import bot, sakura_b, schedall, save_config, prefixes, _open, owner, LOGGER, auto_update, group, config
from bot.func_helper.filters import admins_on_filter, user_in_group_on_filter
from bot.func_helper.fix_bottons import sched_buttons, plays_list_button
from bot.func_helper.msg_utils import callAnswer, editMessage, deleteMessage
from bot.func_helper.scheduler import scheduler
from bot.scheduler import *
from bot.scheduler.userplays_rank import Uplaysinfo
from bot.scheduler.ranks_task import day_ranks, week_ranks
from bot.scheduler.check_ex import check_expired
from bot.scheduler.sync_favorites import sync_favorites
from bot.scheduler.clean_logs import clean_old_logs


# 初始化命令 开机检查重启
loop = asyncio.get_event_loop()
loop.call_later(5, lambda: loop.create_task(BotCommands.set_commands(client=bot)))
loop.call_later(5, lambda: loop.create_task(check_restart()))

# 启动定时任务
auto_backup_db = DbBackupUtils.auto_backup_db
user_plays_rank = Uplaysinfo.user_plays_rank
check_low_activity = Uplaysinfo.check_low_activity

async def user_day_plays(): 
    LOGGER.info(f"【定时任务】开始执行日观影榜，uplays状态: {_open.uplays}")
    await user_plays_rank(1, uplays=True)


async def user_week_plays(): 
    LOGGER.info(f"【定时任务】开始执行周观影榜，uplays状态: {_open.uplays}")
    await user_plays_rank(7, uplays=True)


# 写优雅点
# 字典，method相应的操作函数
action_dict = {
    "dayrank": day_ranks,
    "weekrank": week_ranks,
    "dayplayrank": user_day_plays,
    "weekplayrank": user_week_plays,
    "check_ex": check_expired,
    "low_activity": check_low_activity,
    "clean_logs": clean_old_logs,
    "backup_db": None,  # 只做开关用，不直接绑定函数
}

# 字典，对应的操作函数的参数和id
args_dict = {
    "dayrank": {'hour': 18, 'minute': 30, 'id': 'day_ranks'},
    "weekrank": {'day_of_week': "sun", 'hour': 23, 'minute': 59, 'id': 'week_ranks'},
    "dayplayrank": {'hour': 23, 'minute': 0, 'id': 'user_day_plays'},
    "weekplayrank": {'day_of_week': "sun", 'hour': 23, 'minute': 0, 'id': 'user_week_plays'},
    "check_ex": {'hour': 1, 'minute': 30, 'id': 'check_expired'},
    "low_activity": {'hour': 8, 'minute': 30, 'id': 'check_low_activity'},
    "clean_logs": {'hour': 4, 'minute': 0, 'id': 'clean_old_logs'},
    "backup_db": {'hour': 2, 'minute': 0, 'id': 'daily_local_backup'},  # 仅做面板开关用
}


def set_all_sche():
    for key, value in action_dict.items():
        if key == "backup_db":
            continue  # 备份任务单独处理
        if getattr(schedall, key):
            action = action_dict[key]
            args = args_dict[key]
            scheduler.add_job(action, 'cron', **args)
    # 统一由backup_db开关控制数据库备份相关任务
    if getattr(schedall, "backup_db", False):
        scheduler.add_job(DbBackupUtils.daily_local_backup, 'cron', hour=2, minute=0, id='daily_local_backup')
        scheduler.add_job(DbBackupUtils.weekly_send_backup_to_tg, 'cron', day_of_week='sun', hour=3, minute=0, id='weekly_send_backup_to_tg')


set_all_sche()


async def sched_panel(_, msg):
    # await deleteMessage(msg)
    await editMessage(msg,
                      text=f'🎮 **管理定时任务面板**\n\n',
                      buttons=sched_buttons())


@bot.on_callback_query(filters.regex('sched') & admins_on_filter)
async def sched_change_policy(_, call):
    try:
        method = call.data.split('-')[1]
        # 根据method的值来添加或移除相应的任务
        action = action_dict[method]
        args = args_dict[method]
        if getattr(schedall, method):
            scheduler.remove_job(job_id=args['id'], jobstore='default')
        else:
            scheduler.add_job(action, 'cron', **args)
        setattr(schedall, method, not getattr(schedall, method))
        save_config()
        await asyncio.gather(callAnswer(call, f'⭕️ {method} 更改成功'), sched_panel(_, call.message))
    except IndexError:
        await sched_panel(_, call.message)


@bot.on_message(filters.command('check_ex', prefixes) & admins_on_filter)
async def check_ex_admin(_, msg):
    send = await msg.reply("🍥 正在运行 【到期检测】。。。")
    await check_expired()
    await asyncio.gather(msg.delete(), send.edit("✅ 【到期检测结束】"))


# bot数据库手动备份
@bot.on_message(filters.command('backup_db', prefixes) & filters.user(owner))
async def manual_backup_db(_, msg):
    await asyncio.gather(deleteMessage(msg), auto_backup_db())


@bot.on_message(filters.command('days_ranks', prefixes) & admins_on_filter)
async def day_r_ranks(_, msg):
    await asyncio.gather(msg.delete(), day_ranks(pin_mode=False))


@bot.on_message(filters.command('week_ranks', prefixes) & admins_on_filter)
async def week_r_ranks(_, msg):
    await asyncio.gather(msg.delete(), week_ranks(pin_mode=False))


@bot.on_message(filters.command('low_activity', prefixes) & admins_on_filter)
async def run_low_ac(_, msg):
    await deleteMessage(msg)
    send = await msg.reply(f"⭕ 不活跃检测运行ing···")
    await asyncio.gather(check_low_activity(), send.delete())


@bot.on_message(filters.command('clean_logs', prefixes) & admins_on_filter)
async def run_clean_logs(_, msg):
    await deleteMessage(msg)
    send = await msg.reply(f"🗑️ 日志清理运行中...")
    await clean_old_logs()
    await send.edit("✅ 【日志清理完成】")


@bot.on_message(filters.command('uranks', prefixes) & admins_on_filter)
async def shou_dong_uplayrank(_, msg):
    await deleteMessage(msg)
    try:
        days = int(msg.command[1])
        await user_plays_rank(days=days, uplays=False)
    except (IndexError, ValueError):
        await msg.reply(
            f"🔔 请输入 `/uranks 天数`，此运行手动不会影响{sakura_b}的结算（仅定时运行时结算），放心使用。\n"
            f"定时结算状态: {_open.uplays}")


@bot.on_message(filters.command('sync_favorites', prefixes) & admins_on_filter)
async def sync_favorites_admin(_, msg):
    await deleteMessage(msg)
    await msg.reply("⭕ 正在同步用户收藏记录...")
    await sync_favorites()
    await msg.reply("✅ 用户收藏记录同步完成")


@bot.on_message(filters.command('restart', prefixes) & admins_on_filter)
async def restart_bot(_, msg):
    await deleteMessage(msg)
    send = await msg.reply("Restarting，等待几秒钟。")
    schedall.restart_chat_id = send.chat.id
    schedall.restart_msg_id = send.id
    save_config()
    try:
        # some code here
        LOGGER.info("重启")
        os.execl('/bin/systemctl', 'systemctl', 'restart', 'embyboss')  # 用当前进程执行systemctl命令，重启embyboss服务
    except FileNotFoundError:
        exit(1)


@bot.on_callback_query(filters.regex('uranks') & user_in_group_on_filter)
async def page_uplayrank(_, call):
    j, days = map(int, call.data.split(":")[1].split('_'))
    await callAnswer(call, f'将为您翻到第 {j} 页')
    a, b, c = await Uplaysinfo.users_playback_list(days)
    if not a:
        return await callAnswer(call, f'🍥 获取过去{days}天UserPlays失败了嘤嘤嘤 ~ 手动重试', True)
    button = await plays_list_button(b, j, days)
    text = a[j - 1]
    await editMessage(call, text, buttons=button)


from asyncio import create_subprocess_shell

from asyncio.subprocess import PIPE


async def execute(command, pass_error=True):
    """执行"""
    executor = await create_subprocess_shell(
        command, stdout=PIPE, stderr=PIPE, stdin=PIPE
    )

    stdout, stderr = await executor.communicate()
    if pass_error:
        try:
            result = str(stdout.decode().strip()) + str(stderr.decode().strip())
        except UnicodeDecodeError:
            result = str(stdout.decode("gbk").strip()) + str(stderr.decode("gbk").strip())
    else:
        try:
            result = str(stdout.decode().strip())
        except UnicodeDecodeError:
            result = str(stdout.decode("gbk").strip())
    return result


from sys import executable, argv


@scheduler.SCHEDULER.scheduled_job('cron', hour='12', minute='30', id='update_bot')
async def update_bot(force: bool = False, msg: Message = None, manual: bool = False):
    """
    自动更新，支持ssh方式，详细日志，失败时TG提示。
    """
    LOGGER.info(f"[update_bot] ====== 开始更新检查 (manual={manual}, force={force}) ======")
    
    # 保存当前的restart值
    current_restart_chat_id = schedall.restart_chat_id
    current_restart_msg_id = schedall.restart_msg_id
    LOGGER.info(f"[update_bot] 保存当前restart状态: chat_id={current_restart_chat_id}, msg_id={current_restart_msg_id}")
    
    if not auto_update.status and not manual:
        LOGGER.info("[update_bot] 自动更新未启用且非手动模式，退出更新")
        return
        
    LOGGER.info(f"[update_bot] 正在检查仓库 {auto_update.git_repo} 的最新提交")
    commit_url = f"https://api.github.com/repos/{auto_update.git_repo}/commits?per_page=1"
    resp = requests.get(commit_url)
    
    try:
        if resp.status_code == 200:
            latest_commit = resp.json()[0]["sha"]
            current_commit = auto_update.commit_sha
            LOGGER.info(f"[update_bot] 当前commit: {current_commit}, 最新commit: {latest_commit}")
            
            if latest_commit != current_commit:
                up_description = resp.json()[0]["commit"]["message"]
                LOGGER.info(f"[update_bot] 发现新版本，更新说明: {up_description}")
                
                LOGGER.info("[update_bot] ====== 开始获取最新代码 ======")
                fetch_result = await execute("git fetch --all")
                LOGGER.info(f"[update_bot] git fetch --all 输出:\n{fetch_result}")
                
                if 'fatal' in fetch_result or 'error' in fetch_result.lower():
                    error_msg = "[update_bot] git fetch 失败，请检查SSH配置。"
                    LOGGER.error(error_msg)
                    await bot.send_message(chat_id=get_notify_chat_id(msg), text=error_msg)
                    return
                
                # 总是执行强制重置，确保与远程代码同步
                LOGGER.info("[update_bot] ====== 强制重置到远程master分支 ======")
                reset_result = await execute("git reset --hard origin/master")
                LOGGER.info(f"[update_bot] git reset --hard origin/master 输出:\n{reset_result}")
                
                if 'fatal' in reset_result or 'error' in reset_result.lower():
                    error_msg = "[update_bot] git reset 失败，请检查本地代码状态。"
                    LOGGER.error(error_msg)
                    await bot.send_message(chat_id=get_notify_chat_id(msg), text=error_msg)
                    return
                
                text = '【AutoUpdate_Bot】运行成功，已更新bot代码。重启bot中...'
                await bot.send_message(chat_id=get_notify_chat_id(msg), text=text)
                
                LOGGER.info(f"[update_bot] 更新配置: commit_sha={latest_commit}, description={up_description}")
                # 先保存更新说明，再保存commit_sha
                auto_update.up_description = up_description
                auto_update.commit_sha = latest_commit
                save_config()
                
                LOGGER.info("[update_bot] ====== 开始重启bot ======")
                # 确保日志被写入
                await asyncio.sleep(2)
                os.execl(executable, executable, *argv)
            else:
                message = "【AutoUpdate_Bot】运行成功，未检测到更新，结束"
                await bot.send_message(chat_id=get_notify_chat_id(msg), text=message) if not msg else await msg.edit(message)
                LOGGER.info(message)
        else:
            text = '【AutoUpdate_Bot】失败，请检查 git_repo 是否正确，形如 `berry8838/Sakura_embyboss`'
            await bot.send_message(chat_id=get_notify_chat_id(msg), text=text) if not msg else await msg.edit(text)
            LOGGER.error(f"[update_bot] GitHub API请求失败: status_code={resp.status_code}")
    except Exception as e:
        # 恢复之前的restart_chat_id和restart_msg_id
        LOGGER.error(f"[update_bot] 更新过程发生错误: {str(e)}")
        schedall.restart_chat_id = current_restart_chat_id
        schedall.restart_msg_id = current_restart_msg_id
        auto_update.commit_sha = None
        auto_update.up_description = None  # 出错时也清除更新说明
        save_config()
        err_msg = f"[update_bot] 自动更新失败: {e}"
        LOGGER.error(err_msg)
        await bot.send_message(chat_id=get_notify_chat_id(msg), text=err_msg)
    finally:
        LOGGER.info("[update_bot] ====== 更新流程结束 ======")


@bot.on_message(filters.command('update_bot', prefixes) & admins_on_filter)
async def get_update_bot(_, msg: Message):
    delete_task = msg.delete()
    send_task = bot.send_message(chat_id=msg.chat.id, text='正在更新bot代码，请稍等。。。')
    results = await asyncio.gather(delete_task, send_task)
    # results[1] 是发送消息的结果，从中提取 chat_id 和 message_id
    if len(results) == 2 and isinstance(results[1], Message):
        reply = results[1]
        schedall.restart_chat_id = reply.chat.id
        schedall.restart_msg_id = reply.id
        save_config()
        await update_bot(msg=reply, manual=True)


# 辅助函数：根据触发来源决定消息发送对象
def get_notify_chat_id(msg):
    if msg and hasattr(msg, 'chat') and msg.chat:
        return msg.chat.id
    else:
        return group[0]