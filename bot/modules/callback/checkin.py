import asyncio
import random
from datetime import datetime, timezone, timedelta

from pyrogram import filters

from bot import bot, _open, sakura_b
from bot.func_helper.filters import user_in_group_on_filter
from bot.func_helper.msg_utils import callAnswer, editMessage
from bot.sql_helper.sql_emby import sql_get_emby, sql_update_emby, Emby
from pyromod.helpers import ikb

# 存储用户超时任务的全局字典
checkin_timeout_tasks = {}


def generate_math_question():
    """生成简单的数学选择题"""
    operation = random.choice(['+', '-'])
    if operation == '+':
        # 加法：确保结果在1-20之间
        a = random.randint(1, 15)
        b = random.randint(1, 20 - a)
        correct_answer = a + b
    else:
        # 减法：确保结果为正数且在1-20之间
        correct_answer = random.randint(1, 20)
        b = random.randint(1, 15)
        a = correct_answer + b
    
    question = f"{a} {operation} {b} = ?"
    
    # 生成3个错误选项
    wrong_options = set()
    while len(wrong_options) < 3:
        # 错误答案在正确答案±10范围内，但不等于正确答案且大于0
        wrong = correct_answer + random.randint(-10, 10)
        if wrong != correct_answer and wrong > 0:
            wrong_options.add(wrong)
    
    # 将正确答案和错误选项组合并打乱顺序
    all_options = [correct_answer] + list(wrong_options)
    random.shuffle(all_options)
    
    return question, correct_answer, all_options


def generate_question_buttons(user_id, options, correct_answer):
    """生成选择题按钮"""
    buttons = []
    for i, option in enumerate(options):
        # 将正确答案包含在callback数据中：checkin_answer_{user_id}_{selected_answer}_{correct_answer}
        button_data = f"checkin_answer_{user_id}_{option}_{correct_answer}"
        buttons.append((str(option), button_data))
    
    # 将4个选项排成2x2的网格
    button_rows = [
        [buttons[0], buttons[1]],
        [buttons[2], buttons[3]]
    ]
    
    # 添加取消按钮
    button_rows.append([('❌ 取消签到', f'checkin_cancel_{user_id}')])
    
    return ikb(button_rows)


async def handle_checkin_timeout(user_id, chat_id, message_id):
    """处理签到验证超时"""
    try:
        # 等待60秒
        await asyncio.sleep(60)
        
        # 更新数据库标记为已签到（超时失败）
        now = datetime.now(timezone(timedelta(hours=8)))
        sql_update_emby(Emby.tg == user_id, ch=now)
        
        # 编辑消息显示超时结果
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text='⏰ **签到验证超时**\n\n'
                     '验证时间已超过60秒，自动失败\n'
                     '今日签到机会已用完，请明天再试',
                reply_markup=ikb([[('🏠 返回主菜单', 'back_start')]])
            )
        except Exception:
            pass  # 忽略编辑消息可能的错误
        
        # 从字典中移除任务
        checkin_timeout_tasks.pop(user_id, None)
        
    except asyncio.CancelledError:
        # 任务被取消（用户正常完成验证），清理字典
        checkin_timeout_tasks.pop(user_id, None)
    except Exception:
        # 忽略其他异常
        checkin_timeout_tasks.pop(user_id, None)


@bot.on_callback_query(filters.regex('checkin_answer_') & user_in_group_on_filter)
async def handle_checkin_answer(_, call):
    """处理选择题答案"""
    try:
        # 解析回调数据：checkin_answer_{user_id}_{selected_answer}_{correct_answer}
        parts = call.data.split('_')
        user_id = int(parts[2])
        selected_answer = int(parts[3])
        correct_answer = int(parts[4])
        
        # 验证是否为本人操作
        if call.from_user.id != user_id:
            return await callAnswer(call, '❌ 这不是您的验证题！', True)
        
        # 检查当日是否已签到（防止旧按钮重复使用）
        now = datetime.now(timezone(timedelta(hours=8)))
        today = now.strftime("%Y-%m-%d")
        e = sql_get_emby(call.from_user.id)
        
        if not e:
            return await callAnswer(call, '🧮 未查询到数据库', True)
            
        if e.ch and e.ch.strftime("%Y-%m-%d") >= today:
            return await callAnswer(call, '⭕ 您今天已经进行过签到验证了！请勿重复操作。', True)
        
        # 取消超时任务
        if user_id in checkin_timeout_tasks:
            checkin_timeout_tasks[user_id].cancel()
            checkin_timeout_tasks.pop(user_id, None)
        
        # 验证答案
        if selected_answer == correct_answer:
            # 答案正确，执行签到
            reward = random.randint(_open.checkin_reward[0], _open.checkin_reward[1])
            s = e.iv + reward
            sql_update_emby(Emby.tg == call.from_user.id, iv=s, ch=now)
            
            success_text = (
                f'🎉 **签到成功！**\n\n'
                f'✅ 验证通过！您选择了正确答案：{correct_answer}\n'
                f'💰 获得奖励：{reward} {sakura_b}\n'
                f'💳 当前余额：{s} {sakura_b}\n'
                f'📅 签到时间：{now.strftime("%Y-%m-%d %H:%M:%S")}'
            )
            
            await callAnswer(call, '🎉 签到成功！')
            await editMessage(call, success_text, 
                             buttons=ikb([[('🏠 返回主菜单', 'back_start')]]))
        else:
            # 答案错误，也更新签到时间（但无奖励）
            sql_update_emby(Emby.tg == call.from_user.id, ch=now)
            
            await callAnswer(call, '❌ 答案错误！')
            await editMessage(call, 
                f'❌ **签到失败！**\n\n'
                f'您选择的答案：{selected_answer}\n'
                f'正确答案：{correct_answer}\n\n'
                f'今日签到失败，请明天再试',
                buttons=ikb([[('🏠 返回主菜单', 'back_start')]])
            )
        
    except (ValueError, IndexError) as e:
        await callAnswer(call, '❌ 数据解析错误', True)


@bot.on_callback_query(filters.regex('checkin_cancel_') & user_in_group_on_filter)
async def handle_checkin_cancel(_, call):
    """处理取消签到"""
    try:
        # 解析用户ID
        user_id = int(call.data.split('_')[2])
        
        # 验证是否为本人操作
        if call.from_user.id != user_id:
            return await callAnswer(call, '❌ 这不是您的操作！', True)
        
        # 显示确认取消的警告
        await callAnswer(call, '⚠️ 取消签到将失去今日签到机会！')
        await editMessage(call, 
            '⚠️ **确认取消签到？**\n\n'
            '注意：取消签到后，今日将无法再次进行签到验证！\n'
            '您确定要取消吗？',
            buttons=ikb([
                [('✅ 确认取消', f'checkin_confirm_cancel_{user_id}')],
                [('🔄 继续签到', f'checkin_back_to_question_{user_id}')]
            ])
        )
        
    except (ValueError, IndexError):
        await callAnswer(call, '❌ 数据解析错误', True)


@bot.on_callback_query(filters.regex('checkin_confirm_cancel_') & user_in_group_on_filter)
async def handle_checkin_confirm_cancel(_, call):
    """确认取消签到"""
    try:
        # 解析用户ID
        user_id = int(call.data.split('_')[3])
        
        # 验证是否为本人操作
        if call.from_user.id != user_id:
            return await callAnswer(call, '❌ 这不是您的操作！', True)
        
        # 检查当日是否已签到（防止旧按钮重复使用）
        now = datetime.now(timezone(timedelta(hours=8)))
        today = now.strftime("%Y-%m-%d")
        e = sql_get_emby(call.from_user.id)
        
        if not e:
            return await callAnswer(call, '🧮 未查询到数据库', True)
            
        if e.ch and e.ch.strftime("%Y-%m-%d") >= today:
            return await callAnswer(call, '⭕ 您今天已经进行过签到验证了！请勿重复操作。', True)
        
        # 取消超时任务
        if user_id in checkin_timeout_tasks:
            checkin_timeout_tasks[user_id].cancel()
            checkin_timeout_tasks.pop(user_id, None)
        
        # 更新数据库，标记为已签到（但无奖励）
        sql_update_emby(Emby.tg == call.from_user.id, ch=now)
        
        await callAnswer(call, '❌ 已取消签到')
        await editMessage(call, 
            '❌ **已取消签到验证**\n\n'
            '您已放弃今日签到机会\n'
            '明天可以重新签到', 
            buttons=ikb([[('🏠 返回主菜单', 'back_start')]])
        )
        
    except (ValueError, IndexError):
        await callAnswer(call, '❌ 数据解析错误', True)


@bot.on_callback_query(filters.regex('checkin_back_to_question_') & user_in_group_on_filter)
async def handle_checkin_back_to_question(_, call):
    """返回签到题目"""
    try:
        # 解析用户ID
        user_id = int(call.data.split('_')[4])
        
        # 验证是否为本人操作
        if call.from_user.id != user_id:
            return await callAnswer(call, '❌ 这不是您的操作！', True)
        
        # 取消之前的超时任务
        if user_id in checkin_timeout_tasks:
            checkin_timeout_tasks[user_id].cancel()
            checkin_timeout_tasks.pop(user_id, None)
        
        # 重新生成题目
        question, correct_answer, options = generate_math_question()
        
        await callAnswer(call, '🔄 继续签到验证')
        msg = await editMessage(call, 
            f'🎯 **签到验证**\n\n'
            f'请选择正确答案完成签到验证：\n\n'
            f'**{question}**\n\n'
            f'💰 **奖励范围**：{_open.checkin_reward[0]}-{_open.checkin_reward[1]} {sakura_b}\n'
            f'⚠️ 只能选择一次，请谨慎作答！',
            buttons=generate_question_buttons(call.from_user.id, options, correct_answer)
        )
        
        # 启动新的超时任务
        timeout_task = asyncio.create_task(
            handle_checkin_timeout(user_id, call.message.chat.id, call.message.id)
        )
        checkin_timeout_tasks[user_id] = timeout_task
    except (ValueError, IndexError):
        await callAnswer(call, '❌ 数据解析错误', True)


@bot.on_callback_query(filters.regex('checkin') & user_in_group_on_filter)
async def user_in_checkin(_, call):
    # 避免处理checkin_answer和checkin_cancel
    if 'checkin_answer_' in call.data or 'checkin_cancel_' in call.data:
        return
        
    now = datetime.now(timezone(timedelta(hours=8)))
    today = now.strftime("%Y-%m-%d")
    
    if not _open.checkin:
        return await callAnswer(call, '❌ 未开启签到功能，等待！', True)
    
    e = sql_get_emby(call.from_user.id)
    if not e:
        return await callAnswer(call, '🧮 未查询到数据库', True)
    
    if e.ch and e.ch.strftime("%Y-%m-%d") >= today:
        return await callAnswer(call, '⭕ 您今天已经进行过签到验证了！每天只能尝试一次，请明天再来。', True)
    
    # 检查是否已有进行中的验证（防止机器人重启后重复验证）
    if call.from_user.id in checkin_timeout_tasks:
        return await callAnswer(call, '⚠️ 您已经在进行签到验证，请完成当前验证或等待超时。', True)
    
    # 生成随机验证题
    question, correct_answer, options = generate_math_question()
    
    # 显示选择题
    await callAnswer(call, '🎯 开始签到验证')
    msg = await editMessage(call, 
        f'🎯 **签到验证**\n\n'
        f'请选择正确答案完成签到验证：\n\n'
        f'**{question}**\n\n'
        f'💰 **奖励范围**：{_open.checkin_reward[0]}-{_open.checkin_reward[1]} {sakura_b}\n'
        f'⚠️ 只能选择一次，请谨慎作答！',
        buttons=generate_question_buttons(call.from_user.id, options, correct_answer)
    )
    
    # 启动60秒超时任务
    timeout_task = asyncio.create_task(
        handle_checkin_timeout(call.from_user.id, call.message.chat.id, call.message.id)
    )
    checkin_timeout_tasks[call.from_user.id] = timeout_task
