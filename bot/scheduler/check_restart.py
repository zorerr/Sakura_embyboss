# 重启
from bot import bot, LOGGER, schedall, save_config, auto_update
from pyrogram.errors import BadRequest
import asyncio


async def wait_for_bot_start(bot, max_retry=10, interval=1):
    """
    等待bot启动，最多重试max_retry次，每次间隔interval秒。
    """
    for _ in range(max_retry):
        # pyrogram v2有is_connected，v1有started
        if getattr(bot, "is_connected", False) or getattr(bot, "started", False):
            return True
        await asyncio.sleep(interval)
    return False

# 定义一个检查函数
async def check_restart():
    # 新增：等待bot启动
    ready = await wait_for_bot_start(bot)
    if not ready:
        LOGGER.warning("bot未启动，check_restart放弃执行")
        return
    if schedall.restart_chat_id != 0:
        chat_id, msg_id = schedall.restart_chat_id, schedall.restart_msg_id
        up_description = auto_update.up_description if auto_update.up_description else ""
        text = 'Restarted Successfully!\n\n' + up_description
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text)
        except BadRequest:
            await bot.send_message(chat_id=chat_id, text=text)
        LOGGER.info(f"目标：{chat_id} 消息id：{msg_id} 已提示重启成功")
        schedall.restart_chat_id = 0
        schedall.restart_msg_id = 0
        auto_update.up_description = None
        save_config()

    else:
        LOGGER.info("未检索到有重启指令，直接启动")
