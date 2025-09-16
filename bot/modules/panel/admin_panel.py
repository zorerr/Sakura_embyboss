"""
 admin 面板
 功能暂定 开关注册，生成注册码，查看注册码情况，邀请注册排名情况
"""
import asyncio

from pyrogram import filters

from bot import bot, _open, save_config, bot_photo, LOGGER, bot_name, admins, owner, sakura_b, config
from bot.func_helper.filters import admins_on_filter
from bot.schemas import ExDate
from bot.sql_helper.sql_code import sql_count_code, sql_count_p_code, sql_delete_all_unused, sql_delete_unused_by_days
from bot.sql_helper.sql_emby import sql_count_emby
from bot.func_helper.fix_bottons import gm_ikb_content, open_menu_ikb, gog_rester_ikb, back_open_menu_ikb, \
    back_free_ikb, re_cr_link_ikb, close_it_ikb, ch_link_ikb, date_ikb, cr_paginate, cr_renew_ikb, invite_lv_ikb, \
    back_free_register_ikb, back_coin_register_ikb
from bot.func_helper.msg_utils import callAnswer, editMessage, sendPhoto, callListen, deleteMessage, sendMessage
from bot.func_helper.utils import open_check, cr_link_one,rn_link_one, send_register_end_message


@bot.on_callback_query(filters.regex('manage') & admins_on_filter)
async def gm_ikb(_, call):
    await callAnswer(call, '✔️ manage面板')
    stat, all_user, tem, timing = await open_check()
    stat = "True" if stat else "False"
    timing = 'Turn off' if timing == 0 else str(timing) + ' min'
    coin_register = "True" if _open.coin_register else "False"
    all_user_display = "无限制" if all_user == 999999 else str(all_user)
    tg, emby, white = sql_count_emby()
    gm_text = f'⚙️ 欢迎您，亲爱的管理员 {call.from_user.first_name}\n\n' \
              f'· ®️ 注册状态 | **{stat}**\n' \
              f'· ⏳ 定时注册 | **{timing}**\n' \
              f'· 💰 {sakura_b}注册 | **{coin_register}**\n' \
              f'· 🎫 总注册限制 | **{all_user_display}**\n'\
              f'· 🎟️ 已注册人数 | **{emby}** • WL **{white}**\n' \
              f'· 🤖 bot使用人数 | {tg}'

    await editMessage(call, gm_text, buttons=gm_ikb_content)


# 开关注册
@bot.on_callback_query(filters.regex('open-menu') & admins_on_filter)
async def open_menu(_, call):
    await callAnswer(call, '®️ register面板')
    # [开关，注册总数，定时注册] 此间只对emby表中tg用户进行统计
    stat, all_user, tem, timing = await open_check()
    all_user_display = "无限制" if all_user == 999999 else str(all_user)
    tg, emby, white = sql_count_emby()
    openstats = '✅' if stat else '❎'  # 三元运算
    timingstats = '❎' if timing == 0 else '✅'
    coinstats = '✅' if _open.coin_register else '❎'
    text = f'⚙ **注册状态设置**：\n\n- 自由注册即定量方式，定时注册既定时又定量，将自动转发消息至群组，再次点击按钮可提前结束并报告。\n' \
           f'- **注册总人数限制 {all_user_display}**'
    await editMessage(call, text, buttons=open_menu_ikb(openstats, timingstats, coinstats))
    if tem != emby:
        _open.tem = emby
        save_config()


@bot.on_callback_query(filters.regex('open_stat') & admins_on_filter)
async def open_stats(_, call):
    stat, all_user, tem, timing = await open_check()
    # 检查是否有定时注册正在运行
    if timing != 0:
        return await callAnswer(call, "🔴 定时注册正在运行中，无法开启自由注册。\n请先关闭定时注册。", True)
    # 检查是否有{sakura_b}注册正在运行
    if _open.coin_register:
        return await callAnswer(call, f"🔴 {sakura_b}注册正在运行中，无法开启自由注册。\n请先关闭{sakura_b}注册。", True)

    tg, current_users, white = sql_count_emby()
    if stat:
        _open.stat = False
        save_config()
        await callAnswer(call, "🟢【自由注册】\n\n已结束", True)
        all_user_display = "无限制" if all_user == 999999 else str(all_user)
        sur = all_user - tem if all_user != 999999 else "无限制"
        
        # 使用统一的推送函数发送自由注册关闭消息
        await send_register_end_message("free_closed", tem, admin_name=call.from_user.first_name)
        
        # 管理员界面更新
        text = f'🫧 管理员 {call.from_user.first_name} 已关闭 **自由注册**\n\n' \
               f'🎫 总注册限制 | {all_user_display}\n🎟️ 已注册人数 | {tem}\n' \
               f'🎭 剩余可注册 | **{sur}**\n🤖 bot使用人数 | {tg}'
        await editMessage(call, text, buttons=back_free_ikb)
        LOGGER.info(f"【admin】-自由注册：管理员 {call.from_user.first_name} 手动关闭了自由注册")
    elif not stat:
        await callAnswer(call, '⭕ 自由注册设置')
        tg, current_users, white = sql_count_emby()
        await editMessage(call,
                          f"🦄【自由注册】 \n\n"
                          f"🎟️ 当前已注册人数：{current_users}\n\n"
                          f"- 请在 120s 内发送开注人数\n"
                          f"- 形如：`50` 即开放50个注册名额\n"
                          f"- 输入 `0` 表示不限制人数\n"
                          f"- 总人数限制将设为：{current_users} + 开注人数\n"
                          f"- 如需要关闭自由注册，再次点击【自由注册】\n"
                          f"- 退出 /cancel")

        txt = await callListen(call, 120, buttons=back_free_register_ikb)
        if txt is False:
            return

        await txt.delete()
        if txt.text == '/cancel':
            return await open_menu(_, call)

        try:
            open_count = int(txt.text)
            if open_count < 0:
                raise ValueError("开注人数不能为负数")
            
            # 0表示不限制人数
            if open_count == 0:
                _open.all_user = 999999
                open_count_display = "无限制"
            else:
                _open.all_user = current_users + open_count
                open_count_display = str(open_count)
            
            _open.stat = True
            save_config()
        except ValueError:
            await editMessage(call, "🚫 请检查数字填写是否正确。\n开注人数必须是非负整数（0表示不限制人数）", buttons=back_free_register_ikb)
        else:
            tg, current_users, white = sql_count_emby()
            sur = _open.all_user - current_users if _open.all_user != 999999 else "无限制"
            total_limit_display = "无限制" if _open.all_user == 999999 else str(_open.all_user)
            
            await asyncio.gather(sendPhoto(call, photo=bot_photo,
                                           caption=f'🫧 管理员 {call.from_user.first_name} 已开启 **自由注册**\n\n'
                                                   f'🎫 总注册限制 | {total_limit_display}\n🎟️ 已注册人数 | {current_users}\n'
                                                   f'🎭 剩余可注册 | **{sur}**\n🤖 bot使用人数 | {tg}',
                                           buttons=gog_rester_ikb(), send=True),
                                 editMessage(call,
                                             f"®️ 好，已设置**自由注册开放 {open_count_display} 个名额**\n"
                                             f"总限额：{total_limit_display}（当前{current_users} + 开放{open_count_display}）",
                                             buttons=back_free_ikb))
            
            open_count_log = "无限制" if open_count == 0 else str(open_count)
            LOGGER.info(f"【admin】：管理员 {call.from_user.first_name} 开启了自由注册，开放 {open_count_log} 个名额，总人数限制 {total_limit_display}")


change_for_timing_task = None


@bot.on_callback_query(filters.regex('open_timing') & admins_on_filter)
async def open_timing(_, call):
    global change_for_timing_task
    if _open.timing == 0:
        # 检查是否有自由注册正在运行
        if _open.stat:
            return await callAnswer(call, "🔴 自由注册正在运行中，无法开启定时注册。\n请先关闭自由注册。", True)
        # 检查是否有{sakura_b}注册正在运行
        if _open.coin_register:
            return await callAnswer(call, f"🔴 {sakura_b}注册正在运行中，无法开启定时注册。\n请先关闭{sakura_b}注册。", True)
            
        await callAnswer(call, '⭕ 定时设置')
        tg, current_users, white = sql_count_emby()
        await editMessage(call,
                          f"🦄【定时注册】 \n\n"
                          f"🎟️ 当前已注册人数：{current_users}\n\n"
                          f"- 请在 120s 内发送 [定时时长] [开注人数]\n"
                          f"- 形如：`30 50` 即30min，开放50个注册名额\n"
                          f"- 总人数限制将设为：{current_users} + 开注人数\n"
                          f"- 开注人数为 0 表示不限制人数\n"
                          f"- 如需要关闭定时注册，再次点击【定时注册】\n"
                          f"- 设置好之后将发送置顶消息注意权限\n- 退出 /cancel")

        txt = await callListen(call, 120, buttons=back_open_menu_ikb)
        if txt is False:
            return

        await txt.delete()
        if txt.text == '/cancel':
            return await open_menu(_, call)

        try:
            new_timing, open_count = txt.text.split()
            new_timing = int(new_timing)
            open_count = int(open_count)
            if new_timing <= 0 or open_count < 0:
                raise ValueError("时长必须大于0，开注人数不能为负数")
            
            _open.timing = new_timing
            
            # 0表示不限制人数
            if open_count == 0:
                _open.all_user = 999999
                open_count_display = "无限制"
            else:
                _open.all_user = current_users + open_count
                open_count_display = str(open_count)
            
            _open.stat = True
            save_config()
        except ValueError:
            await editMessage(call, "🚫 请检查数字填写是否正确。\n`[时长min] [开注人数]`\n时长必须大于0，开注人数必须是非负整数（0表示不限制人数）", buttons=back_open_menu_ikb)
        else:
            tg, current_users, white = sql_count_emby()
            sur = _open.all_user - current_users if _open.all_user != 999999 else "无限制"
            total_limit_display = "无限制" if _open.all_user == 999999 else str(_open.all_user)
            
            await asyncio.gather(sendPhoto(call, photo=bot_photo,
                                           caption=f'🫧 管理员 {call.from_user.first_name} 已开启 **定时注册**\n\n'
                                                   f'⏳ 可持续时间 | **{_open.timing}** min\n'
                                                   f'🎫 总注册限制 | {total_limit_display}\n🎟️ 已注册人数 | {current_users}\n'
                                                   f'🎭 剩余可注册 | **{sur}**\n🤖 bot使用人数 | {tg}',
                                           buttons=gog_rester_ikb(), send=True),
                                 editMessage(call,
                                             f"®️ 好，已设置**定时注册 {_open.timing} min 开放 {open_count_display} 个名额**\n"
                                             f"总限额：{total_limit_display}（当前{current_users} + 开放{open_count_display}）",
                                             buttons=back_free_ikb))
            
            open_count_log = "无限制" if open_count == 0 else str(open_count)
            LOGGER.info(
                f"【admin】-定时注册：管理员 {call.from_user.first_name} 开启了定时注册 {_open.timing} min，开放 {open_count_log} 个名额，总人数限制 {total_limit_display}")
            # 创建一个异步任务并保存为变量，并给它一个名字
            change_for_timing_task = asyncio.create_task(
                change_for_timing(_open.timing, call.from_user.id, call), name='change_for_timing')

    else:
        try:
            # 遍历所有的异步任务，找到'change_for_timing'，取消
            for task in asyncio.all_tasks():
                if task.get_name() == 'change_for_timing':
                    change_for_timing_task = task
                    break
            change_for_timing_task.cancel()
        except AttributeError:
            pass
        else:
            # 手动关闭定时注册，发送管理员关闭消息到群组
            original_timing = _open.timing  # 保存原定时长
            _open.original_timing = original_timing  # 保存到_open对象中供推送使用
            _open.timing = 0
            _open.stat = False
            save_config()
            
            tg, current_users, white = sql_count_emby()
            
            # 使用统一的推送函数发送定时注册关闭消息
            await send_register_end_message("timing_closed", current_users, admin_name=call.from_user.first_name)
            
            LOGGER.info(f"【admin】-定时注册：管理员 {call.from_user.first_name} 手动关闭了定时注册")
            
            await callAnswer(call, "Ⓜ️【定时任务运行终止】\n\n**已为您停止**", True)
            await open_menu(_, call)


async def change_for_timing(timing, tgid, call):
    a = _open.tem
    timing = timing * 60
    manually_cancelled = False
    try:
        await asyncio.sleep(timing)
    except asyncio.CancelledError:
        manually_cancelled = True
        # 手动取消时不需要发送推送，因为在上面的else块已经处理了
    finally:
        if not manually_cancelled:
            # 只有在自动结束时才发送推送和管理员私信
            _open.timing = 0
            _open.stat = False
            save_config()
            
            # 调用统一的定时注册结束推送处理函数
            from bot.modules.panel.member_panel import _handle_timing_registration_end
            await _handle_timing_registration_end(a, tgid)


@bot.on_callback_query(filters.regex('open_coin_register') & admins_on_filter)
async def open_coin_register(_, call):
    stat, all_user, tem, timing = await open_check()
    # 检查是否有其他注册模式正在运行
    if timing != 0:
        return await callAnswer(call, f"🔴 定时注册正在运行中，无法开启{sakura_b}注册。\n请先关闭定时注册。", True)
    if stat:
        return await callAnswer(call, f"🔴 自由注册正在运行中，无法开启{sakura_b}注册。\n请先关闭自由注册。", True)

    tg, current_users, white = sql_count_emby()
    if _open.coin_register:
        _open.coin_register = False
        save_config()
        await callAnswer(call, f"🟢【{sakura_b}注册】\n\n已结束", True)
        all_user_display = "无限制" if _open.all_user == 999999 else str(_open.all_user)
        sur = _open.all_user - current_users if _open.all_user != 999999 else "无限制"
        
        # 使用统一的推送函数发送积分注册关闭消息
        await send_register_end_message("coin_closed", current_users, admin_name=call.from_user.first_name)
        
        # 管理员界面更新
        text = f'🫧 管理员 {call.from_user.first_name} 已关闭 **{sakura_b}注册**\n\n' \
               f'💰 所需{sakura_b} | {_open.coin_cost}\n🎫 总注册限制 | {all_user_display}\n🎟️ 已注册人数 | {current_users}\n' \
               f'🎭 剩余可注册 | **{sur}**\n🤖 bot使用人数 | {tg}'
        await editMessage(call, text, buttons=back_free_ikb)
        LOGGER.info(f"【admin】-{sakura_b}注册：管理员 {call.from_user.first_name} 手动关闭了{sakura_b}注册")
    elif not _open.coin_register:
        await callAnswer(call, f'⭕ {sakura_b}注册设置')
        await editMessage(call,
                          f"🦄【{sakura_b}注册】 \n\n"
                          f"🎟️ 当前已注册人数：{current_users}\n\n"
                          f"- 请在 120s 内发送 [所需{sakura_b}数量] [开注人数]\n"
                          f"- 形如：`100 50` 即需要100个{sakura_b}，开放50个注册名额\n"
                          f"- 总人数限制将设为：{current_users} + 开注人数\n"
                          f"- 开注人数为 0 表示不限制人数\n"
                          f"- 用户必须拥有足够的{sakura_b}才能注册\n"
                          f"- 如需要关闭{sakura_b}注册，再次点击【{sakura_b}注册】\n"
                          f"- 退出 /cancel")

        txt = await callListen(call, 120, buttons=back_coin_register_ikb)
        if txt is False:
            return

        await txt.delete()
        if txt.text == '/cancel':
            return await open_menu(_, call)

        try:
            coin_cost, open_count = txt.text.split()
            coin_cost = int(coin_cost)
            open_count = int(open_count)
            if coin_cost <= 0 or open_count < 0:
                raise ValueError(f"所需{sakura_b}数量必须大于0，开注人数不能为负数")
            
            _open.coin_cost = coin_cost
            
            # 0表示不限制人数
            if open_count == 0:
                _open.all_user = 999999
                open_count_display = "无限制"
            else:
                _open.all_user = current_users + open_count
                open_count_display = str(open_count)
            
            _open.coin_register = True
            save_config()
        except ValueError:
            await editMessage(call, f"🚫 请检查数字填写是否正确。\n`[所需{sakura_b}数量] [开注人数]`\n所需{sakura_b}数量必须大于0，开注人数必须是非负整数（0表示不限制人数）", buttons=back_coin_register_ikb)
        else:
            tg, current_users, white = sql_count_emby()
            sur = _open.all_user - current_users if _open.all_user != 999999 else "无限制"
            total_limit_display = "无限制" if _open.all_user == 999999 else str(_open.all_user)
            
            await asyncio.gather(sendPhoto(call, photo=bot_photo,
                                           caption=f'🫧 管理员 {call.from_user.first_name} 已开启 **{sakura_b}注册**\n\n'
                                                   f'💰 所需{sakura_b} | {_open.coin_cost}\n🎫 总注册限制 | {total_limit_display}\n🎟️ 已注册人数 | {current_users}\n'
                                                   f'🎭 剩余可注册 | **{sur}**\n🤖 bot使用人数 | {tg}',
                                           buttons=gog_rester_ikb(), send=True),
                                 editMessage(call,
                                             f"®️ 好，已设置**{sakura_b}注册需要 {coin_cost} 个{sakura_b}，开放 {open_count_display} 个名额**\n"
                                             f"总限额：{total_limit_display}（当前{current_users} + 开放{open_count_display}）",
                                             buttons=back_free_ikb))
            
            open_count_log = "无限制" if open_count == 0 else str(open_count)
            LOGGER.info(f"【admin】：管理员 {call.from_user.first_name} 开启了{sakura_b}注册，需要 {coin_cost} 个{sakura_b}，开放 {open_count_log} 个名额，总人数限制 {total_limit_display}")


@bot.on_callback_query(filters.regex('open_us') & admins_on_filter)
async def open_us(_, call):
    await callAnswer(call, '🤖开放账号天数')
    send = await call.message.edit(
        "🦄 请在 120s 内发送开放注册时账号的有效天数，本次修改不会对注册状态改动，如需要开注册请点击打开自由注册\n**注**：总人数满自动关闭注册 取消 /cancel")
    if send is False:
        return

    txt = await callListen(call, 120, buttons=back_free_ikb)
    if txt is False:
        return
    elif txt.text == "/cancel":
        await txt.delete()
        return await open_menu(_, call)

    try:
        await txt.delete()
        a = int(txt.text)
    except ValueError:
        await editMessage(call, f"❌ 八嘎，请输入一个数字给我。", buttons=back_free_ikb)
    else:
        _open.open_us = a
        save_config()
        await editMessage(call, f"✔️ 成功，您已设置 **开放注册时账号的有效天数 {a}**", buttons=back_free_ikb)
        LOGGER.info(f"【admin】：管理员 {call.from_user.first_name} 调整了开放注册时账号的有效天数：{a}")

# 生成注册链接
@bot.on_callback_query(filters.regex('cr_link') & admins_on_filter)
async def cr_link(_, call):
    await callAnswer(call, '✔️ 创建注册/续期码')
    send = await editMessage(call,
                             f'🎟️ 请回复创建 [天数] [数量] [模式] [续期]\n\n'
                             f'**天数**：月30，季90，半年180，年365\n'
                             f'**模式**： link -深链接 | code -码\n'
                             f'**续期**： F - 注册码，T - 续期码\n'
                             f'**示例**：`30 1 link F` 记作 30天一条注册深链接\n'
                             f'__取消本次操作，请 /cancel__')
    if send is False:
        return

    content = await callListen(call, 120, buttons=re_cr_link_ikb)
    if content is False:
        return
    elif content.text == '/cancel':
        await content.delete()
        return await editMessage(call, '⭕ 您已经取消操作了。', buttons=re_cr_link_ikb)
    try:
        await content.delete()
        times, count, method, renew = content.text.split()
        count = int(count)
        days = int(times)
        if method != 'code' and method != 'link':
            return editMessage(call, '⭕ 输入的method参数有误', buttons=re_cr_link_ikb)
    except (ValueError, IndexError):
        return await editMessage(call, '⚠️ 检查输入，有误。', buttons=re_cr_link_ikb)
    else:
        if renew == 'F':
            links = await cr_link_one(call.from_user.id, times, count, days, method)
            if links is None:
                return await editMessage(call, '⚠️ 数据库插入失败，请检查数据库。', buttons=re_cr_link_ikb)
            links = f"🎯 {bot_name}已为您生成了 **{days}天** 注册码 {count} 个\n\n" + links
            chunks = [links[i:i + 4096] for i in range(0, len(links), 4096)]
            for chunk in chunks:
                await sendMessage(content, chunk, buttons=close_it_ikb)
            await editMessage(call, f'📂 {bot_name}已为 您 生成了 {count} 个 {days} 天注册码', buttons=re_cr_link_ikb)
            LOGGER.info(f"【admin】：{bot_name}已为 {content.from_user.id} 生成了 {count} 个 {days} 天注册码")

        else:
            links = await rn_link_one(call.from_user.id, times, count, days, method)
            if links is None:
                return await editMessage(call, '⚠️ 数据库插入失败，请检查数据库。', buttons=re_cr_link_ikb)
            links = f"🎯 {bot_name}已为您生成了 **{days}天** 续期码 {count} 个\n\n" + links
            chunks = [links[i:i + 4096] for i in range(0, len(links), 4096)]
            for chunk in chunks:
                await sendMessage(content, chunk, buttons=close_it_ikb)
            await editMessage(call, f'📂 {bot_name}已为 您 生成了 {count} 个 {days} 天续期码', buttons=re_cr_link_ikb)
            LOGGER.info(f"【admin】：{bot_name}已为 {content.from_user.id} 生成了 {count} 个 {days} 天续期码")


# 检索
@bot.on_callback_query(filters.regex('ch_link') & admins_on_filter)
async def ch_link(_, call):
    await callAnswer(call, '🔍 查看管理们注册码...时长会久一点', True)
    a, b, c, d, f, e = sql_count_code()
    text = f'**🎫 常用code数据：\n• 已使用 - {a}  | • 未使用 - {e}\n• 月码 - {b}   | • 季码 - {c} \n• 半年码 - {d}  | • 年码 - {f}**'
    ls = []
    admins.append(owner)
    for i in admins:
        name = await bot.get_chat(i)
        a, b, c, d, f ,e= sql_count_code(i)
        text += f'\n👮🏻`{name.first_name}`: 月/{b}，季/{c}，半年/{d}，年/{f}，已用/{a}，未用/{e}'
        f = [f"🔎 {name.first_name}", f"ch_admin_link-{i}"]
        ls.append(f)
    ls.append(["🚮 删除未使用码", f"delete_codes"])
    admins.remove(owner)
    keyboard = ch_link_ikb(ls)
    text += '\n详情查询 👇'

    await editMessage(call, text, buttons=keyboard)

# 删除未使用码
@bot.on_callback_query(filters.regex('delete_codes') & admins_on_filter)
async def delete_unused_codes(_, call):
    await callAnswer(call, '⚠️ 请确认要删除码的类别')
    if call.from_user.id != owner:
        return await callAnswer(call, '🚫 不可以哦！ 你又不是owner', True)
    
    await editMessage(call, 
        "请回复要删除的未使用码天数类别，多个天数用空格分隔\n"
        "例如: `5 30 180` 将删除属于5天、30天和180天类别的未使用码\n"
        "输入 `all` 删除所有未使用码\n"
        "取消请输入 /cancel")
    
    content = await callListen(call, 120)
    if content is False:
        return
    elif content.text == '/cancel':
        await content.delete()
        return await gm_ikb(_, call)
        
    try:
        if content.text.lower() == 'all':
            count = sql_delete_all_unused()
            text = f"已删除所有未使用码，共 {count} 个"
        else:
            days = [int(x) for x in content.text.split()]
            count = sql_delete_unused_by_days(days)
            text = f"已删除指定天数的未使用码，共 {count} 个"
        await content.delete()
    except ValueError:
        text = "❌ 输入格式错误"
    
    ls=[]
    ls.append(["🔄 继续删除", f"delete_codes"])
    keyboard = ch_link_ikb(ls)
    await editMessage(call, text, buttons=keyboard)


@bot.on_callback_query(filters.regex('ch_admin_link'))
async def ch_admin_link(client, call):
    i = int(call.data.split('-')[1])
    if call.from_user.id != owner and call.from_user.id != i:
        return await callAnswer(call, '🚫 你怎么偷窥别人呀! 你又不是owner', True)
    await callAnswer(call, f'💫 管理员 {i} 的注册码')
    a, b, c, d, f, e= sql_count_code(i)
    name = await client.get_chat(i)
    text = f'**🎫 [{name.first_name}-{i}](tg://user?id={i})：\n• 已使用 - {a}  | • 未使用 - {e}\n• 月码 - {b}    | • 季码 - {c} \n• 半年码 - {d}  | • 年码 - {f}**'
    await editMessage(call, text, date_ikb(i))


@bot.on_callback_query(
    filters.regex('register_mon') | filters.regex('register_sea')
    | filters.regex('register_half') | filters.regex('register_year') | filters.regex('register_used') | filters.regex('register_unused'))
async def buy_mon(_, call):
    await call.answer('✅ 显示注册码')
    cd, times, u = call.data.split('_')
    n = getattr(ExDate(), times)
    a, i = sql_count_p_code(u, n)
    if a is None:
        x = '**空**'
    else:
        x = a[0]
    first = await bot.get_chat(u)
    keyboard = await cr_paginate(i, 1, n)
    await sendMessage(call, f'🔎当前 {first.first_name} - **{n}**天，检索出以下 **{i}**页：\n\n{x}', keyboard)


# 检索翻页
@bot.on_callback_query(filters.regex('pagination_keyboard'))
async def paginate_keyboard(_, call):
    j, mode = map(int, call.data.split(":")[1].split('_'))
    await callAnswer(call, f'好的，将为您翻到第 {j} 页')
    a, b = sql_count_p_code(call.from_user.id, mode)
    keyboard = await cr_paginate(b, j, mode)
    text = a[j-1]
    await editMessage(call, f'🔎当前模式- **{mode}**天，检索出以下 **{b}**页链接：\n\n{text}', keyboard)


@bot.on_callback_query(filters.regex('set_renew'))
async def set_renew(_, call):
    await callAnswer(call, '🚀 进入续期设置')
    try:
        method = call.data.split('-')[1]
        setattr(_open, method, not getattr(_open, method))
        save_config()
    except IndexError:
        pass
    finally:
        await editMessage(call, text='⭕ **关于用户组的续期功能**\n\n选择点击下方按钮开关任意兑换功能',
                          buttons=cr_renew_ikb())
@bot.on_callback_query(filters.regex('set_freeze_days') & admins_on_filter)
async def set_freeze_days(_, call):
    await callAnswer(call, '⭕ 设置封存天数')
    send = await call.message.edit(
        "🦄 请在 120s 内发送封存账号天数，\n**注**：用户到期后被禁用，再过指定天数后会被删除 取消 /cancel")
    if send is False:
        return

    txt = await callListen(call, 120, buttons=back_free_ikb)
    if txt is False:
        return
    elif txt.text == "/cancel":
        await txt.delete()
        return await open_menu(_, call)

    try:
        await txt.delete()
        a = int(txt.text)
    except ValueError:
        await editMessage(call, f"❌ 八嘎，请输入一个数字给我。", buttons=back_free_ikb)
    else:
        config.freeze_days = a
        save_config()
        await editMessage(call, f"✔️ 成功，您已设置 **封存账号天数 {a}**", buttons=back_free_ikb)
        LOGGER.info(f"【admin】：管理员 {call.from_user.first_name} 调整了封存账号天数：{a}")

@bot.on_callback_query(filters.regex('set_invite_lv'))
async def invite_lv_set(_, call):
    try:
        method = call.data
        if method.startswith('set_invite_lv-'):
            # 当选择具体等级时
            level = method.split('-')[1]
            if level in ['a', 'b', 'c', 'd']:
                _open.invite_lv = level
                save_config()
                await callAnswer(call, f'✅ 已设置邀请等级为 {level}', show_alert=True)
        await callAnswer(call, '🚀 进入邀请等级设置')
        # 当点击设置邀请等级按钮时
        await editMessage(call, 
            "请选择邀请等级:\n\n"
            f"当前等级: {_open.invite_lv}\n\n"
            "🅰️ - 白名单可使用\n"
            "🅱️ - 注册用户可使用\n" 
            "©️ - 已禁用用户可使用\n"
            "🅳️ - 无账号用户可使用",
            buttons=invite_lv_ikb())
        return
    except IndexError:
        pass
