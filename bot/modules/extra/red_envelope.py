"""
red_envelope - 

Author:susu
Date:2023/01/02
"""

import cn2an
import asyncio
import random
import math
from datetime import datetime, timedelta
from pyrogram import filters
from pyrogram.types import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func

from bot import bot, prefixes, sakura_b, bot_photo, red_envelope
from bot.func_helper.filters import user_in_group_on_filter
from bot.func_helper.fix_bottons import users_iv_button
from bot.func_helper.msg_utils import sendPhoto, sendMessage, callAnswer, editMessage
from bot.func_helper.utils import pwd_create, judge_admins, get_users, cache
from bot.sql_helper import Session
from bot.sql_helper.sql_emby import Emby, sql_get_emby, sql_update_emby
from bot.ranks_helper.ranks_draw import RanksDraw
from bot.schemas import Yulv

# 小项目，说实话不想写数据库里面。放内存里了，从字典里面每次拿分

red_envelopes = {}


class RedEnvelope:
    def __init__(self, money, members, sender_id, sender_name, envelope_type="random"):
        self.id = None
        self.money = money  # 总金额
        self.rest_money = money  # 剩余金额
        self.members = members  # 总份数
        self.rest_members = members  # 剩余份数
        self.sender_id = sender_id  # 发送者ID
        self.sender_name = sender_name  # 发送者名称
        self.type = envelope_type  # random/equal/private
        self.receivers = {}  # {user_id: {"amount": xx, "name": "xx"}}
        self.target_user = None  # 专享红包接收者ID
        self.message = None  # 专享红包消息


async def create_reds(
    money, members, first_name, sender_id, flag=None, private=None, private_text=None
):
    red_id = await pwd_create(5)
    envelope = RedEnvelope(
        money=money, members=members, sender_id=sender_id, sender_name=first_name
    )

    if flag:
        envelope.type = "equal"
    elif private:
        envelope.type = "private"
        envelope.target_user = private
        envelope.message = private_text

    envelope.id = red_id
    red_envelopes[red_id] = envelope

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text="👆🏻 好運連連", callback_data=f"red_envelope-{red_id}"
                )
            ]
        ]
    )


@bot.on_message(
    filters.command("red", prefixes) & user_in_group_on_filter & filters.group
)
async def send_red_envelope(_, msg):
    if not red_envelope.status:
        return await asyncio.gather(
            msg.delete(), sendMessage(msg, "🚫 红包功能已关闭！")
        )

    if not red_envelope.allow_private and msg.reply_to_message:
        return await asyncio.gather(
            msg.delete(), sendMessage(msg, "🚫 专属红包功能已关闭！")
        )

    # 处理专享红包
    if msg.reply_to_message and red_envelope.allow_private:
        try:
            money = int(msg.command[1])
            private_text = (
                msg.command[2]
                if len(msg.command) > 2
                else random.choice(Yulv.load_yulv().red_bag)
            )
        except (IndexError, ValueError):
            return await asyncio.gather(
                msg.delete(),
                sendMessage(
                    msg,
                    "**🧧 专享红包：\n\n请回复某人 [数额][空格][个性化留言（可选）]**",
                    timer=60,
                ),
            )

        # 验证发送者资格
        verified, first_name, error = await verify_red_envelope_sender(
            msg, money, is_private=True
        )
        if not verified:
            return

        # 创建并发送红包
        reply, _ = await asyncio.gather(
            msg.reply("正在准备专享红包，稍等"), msg.delete()
        )

        ikb = await create_reds(
            money=money,
            members=1,
            first_name=first_name,
            sender_id=msg.from_user.id if not msg.sender_chat else msg.sender_chat.id,
            private=msg.reply_to_message.from_user.id,
            private_text=private_text,
        )

        user_pic = await get_user_photo(msg.reply_to_message.from_user)
        cover = await RanksDraw.hb_test_draw(
            money, 1, user_pic, f"{msg.reply_to_message.from_user.first_name} 专享"
        )

        await asyncio.gather(
            sendPhoto(msg, photo=cover, buttons=ikb),
            reply.edit(
                f"🔥 [{msg.reply_to_message.from_user.first_name}]"
                f"(tg://user?id={msg.reply_to_message.from_user.id})\n"
                f"您收到一个来自 [{first_name}](tg://user?id={msg.from_user.id}) 的专属红包"
            ),
        )
        return

    # 处理普通红包
    try:
        money = int(msg.command[1])
        members = int(msg.command[2])  # 预先验证members参数
    except (IndexError, ValueError):
        return await asyncio.gather(
            msg.delete(),
            sendMessage(
                msg,
                f"**🧧 发红包格式：\n\n/red [金额] [份数] [mode]**\n\n"
                f"**规则：**\n"
                f"• 持有{sakura_b}≥5，发红包≥5\n"
                f"• 金额≥份数，份数>0\n"
                f"• mode留空=拼手气，任意值=均分\n"
                f"• 专享红包：回复某人+金额",
                timer=60,
            ),
        )

    # 验证发送者资格和红包参数
    verified, first_name, error = await verify_red_envelope_sender(msg, money, members=members)
    if not verified:
        return

    # 创建并发送红包
    flag = msg.command[3] if len(msg.command) > 3 else (1 if money == members else None)
    reply, _ = await asyncio.gather(msg.reply("正在准备红包，稍等"), msg.delete())

    ikb = await create_reds(
        money=money,
        members=members,
        first_name=first_name,
        sender_id=msg.from_user.id if not msg.sender_chat else msg.sender_chat.id,
        flag=flag,
    )

    user_pic = await get_user_photo(msg.from_user if not msg.sender_chat else msg.chat)
    cover = await RanksDraw.hb_test_draw(money, members, user_pic, first_name)

    await asyncio.gather(sendPhoto(msg, photo=cover, buttons=ikb), reply.delete())


@bot.on_callback_query(filters.regex("red_envelope") & user_in_group_on_filter)
async def grab_red_envelope(_, call):
    red_id = call.data.split("-")[1]
    try:
        envelope = red_envelopes[red_id]
    except (IndexError, KeyError):
        return await callAnswer(
            call, "/(ㄒoㄒ)/~~ \n\n来晚了，红包已经被抢光啦。", True
        )

    # 验证用户资格
    e = sql_get_emby(tg=call.from_user.id)
    if not e:
        return await callAnswer(call, "你还未私聊bot! 数据库没有你.", True)

    # 检查是否已领取
    if call.from_user.id in envelope.receivers:
        return await callAnswer(call, "ʕ•̫͡•ʔ 你已经领取过红包了。不许贪吃", True)

    # 检查红包是否已抢完
    if envelope.members > 0:
        # 正数份数：检查剩余份数
        if envelope.rest_members <= 0:
            return await callAnswer(
                call, "/(ㄒoㄒ)/~~ \n\n来晚了，红包已经被抢光啦。", True
            )
    else:
        # 负数份数（管理员特权）：检查已领取次数是否达到绝对值
        if len(envelope.receivers) >= abs(envelope.members):
            return await callAnswer(
                call, "/(ㄒoㄒ)/~~ \n\n来晚了，红包已经被抢光啦。", True
            )

    amount = 0
    # 处理均分红包
    if envelope.type == "equal":
        amount = envelope.money // envelope.members

    # 处理专享红包
    elif envelope.type == "private":
        if call.from_user.id != envelope.target_user:
            return await callAnswer(call, "ʕ•̫͡•ʔ 这是你的专属红包吗？", True)
        amount = envelope.rest_money

    # 处理拼手气红包
    else:
        if envelope.members > 0:
            # 正数份数的拼手气红包
            if envelope.rest_members > 1:
                k = 2 * envelope.rest_money / envelope.rest_members
                amount = int(random.uniform(1, k))
            else:
                amount = envelope.rest_money
        else:
            # 负数份数的拼手气红包（管理员特权）
            remaining_count = abs(envelope.members) - len(envelope.receivers)
            if remaining_count > 1:
                k = 2 * envelope.rest_money / remaining_count
                amount = int(random.uniform(1, k))
            else:
                amount = envelope.rest_money

    # 更新用户余额
    new_balance = e.iv + amount
    sql_update_emby(Emby.tg == call.from_user.id, iv=new_balance)

    # 更新红包信息
    envelope.receivers[call.from_user.id] = {
        "amount": amount,
        "name": call.from_user.first_name or "Anonymous",
    }
    envelope.rest_money -= amount
    envelope.rest_members -= 1

    # 专享红包特殊提示
    if envelope.type == "private":
        await callAnswer(
            call,
            f"🧧恭喜，你领取到了\n{envelope.sender_name} の {amount}{sakura_b}\n\n{envelope.message}",
            True,
        )
    else:
        await callAnswer(
            call, f"🧧恭喜，你领取到了\n{envelope.sender_name} の {amount}{sakura_b}", True
        )

    # 处理红包抢完后的展示
    # 判断红包是否已完成：正数份数看rest_members，负数份数看已领取次数
    is_finished = (envelope.members > 0 and envelope.rest_members == 0) or \
                  (envelope.members < 0 and len(envelope.receivers) >= abs(envelope.members))
    
    if is_finished:
        red_envelopes.pop(red_id)
        text = await generate_final_message(envelope)
        n = 2048
        chunks = [text[i : i + n] for i in range(0, len(text), n)]
        for i, chunk in enumerate(chunks):
            if i == 0:
                await editMessage(call, chunk)
            else:
                await call.message.reply(chunk)


async def verify_red_envelope_sender(msg, money, is_private=False, members=None):
    """验证发红包者资格

    Args:
        msg: 消息对象
        money: 红包金额
        is_private: 是否为专享红包
        members: 红包份数（普通红包）

    Returns:
        tuple: (验证是否通过, 发送者名称, 错误信息)
    """
    if not msg.sender_chat:
        e = sql_get_emby(tg=msg.from_user.id)
        
        # 检查是否为管理员
        is_admin = judge_admins(msg.from_user.id)
        
        # 基础验证条件
        conditions = [
            e,  # 用户存在
            e.iv >= 5 if e else False,  # 持有金额不小于5
        ]
        
        # 金额和余额检查 - 区分管理员和普通用户
        if is_admin:
            # 管理员可以发负数金额，余额检查逻辑需要特殊处理
            if money >= 0:
                # 正数金额：检查余额是否足够
                conditions.extend([
                    e.iv >= money if e else False,  # 余额充足
                    money >= 5,  # 金额不小于5
                ])
            else:
                # 负数金额：管理员可以发任意负数金额，不需要检查余额和金额限制
                pass  # 不添加额外条件
        else:
            # 普通用户：保持原有严格验证
            conditions.extend([
                e.iv >= money if e else False,  # 余额充足
                money >= 5,  # 红包金额不小于5（已包含>0检查）
            ])

        if is_private:
            # 专享红包额外检查 不能发给自己
            conditions.append(msg.reply_to_message.from_user.id != msg.from_user.id)
        else:
            # 普通红包额外检查
            if members is None:
                # 如果没有传入members，尝试从命令中解析（保持向后兼容）
                try:
                    members = int(msg.command[2])
                except (IndexError, ValueError):
                    # 格式错误处理
                    return await asyncio.gather(
                        msg.delete(),
                        sendMessage(
                            msg,
                            "**🧧 专享红包格式：**\n\n回复某人 [金额] [留言]（可选）\n\n"
                            f"**规则：**持有{sakura_b}≥5，发红包≥5",
                            timer=60,
                        ),
                    )
                    return False, None, "格式错误"
            
            # 管理员可以发负数金额红包，普通用户不可以
            if is_admin:
                conditions.extend([
                    members > 0,  # 份数必须为正数
                    abs(money) >= members  # 金额绝对值不小于份数
                ])
            else:
                conditions.extend([
                    members > 0,  # 份数必须为正数
                    money >= members  # 金额不小于份数
                ])

        # 调试信息：如果是管理员且金额为负数，显示详细的验证状态
        # 临时调试代码，测试完成后移除
        # if is_admin and money < 0:
        #     debug_info = f"调试信息 - 管理员:{is_admin}, 金额:{money}, 份数:{members}, 用户存在:{bool(e)}, 余额:{e.iv if e else 'N/A'}"
        #     await sendMessage(msg, debug_info, timer=10)

        if not all(conditions):
            error_msg = (
                f"[{msg.from_user.first_name}](tg://user?id={msg.from_user.id}) "
                f"违反规则，禁言一分钟。\nⅰ 所持有{sakura_b}不得小于5\nⅱ 发出{sakura_b}不得小于5\nⅲ 金额和份数必须大于0"
            )
            if is_private:
                error_msg += "\nⅳ 不许发自己"
            else:
                # 使用已经定义的is_admin变量
                if is_admin:
                    error_msg += "\nⅳ 金额不得小于份数数量\nⅴ 份数不能为0\nⅵ 未私聊过bot"
                else:
                    error_msg += "\nⅳ 金额不得小于份数\nⅴ 未私聊过bot"

            if is_admin:
                # 管理员违反规则：只发送错误消息，不禁言
                await asyncio.gather(
                    msg.delete(),
                    sendMessage(msg, error_msg, timer=60),
                )
            else:
                # 普通用户违反规则：尝试禁言，然后发送错误消息
                ban_success = True
                try:
                    await msg.chat.restrict_member(
                        msg.from_user.id,
                        ChatPermissions(),
                        datetime.now() + timedelta(minutes=1),
                    )
                except Exception as ex:
                    ban_success = False
                
                # 根据禁言结果发送消息
                final_error_msg = error_msg if ban_success else error_msg + "\n(禁言失败)"
                await asyncio.gather(
                    msg.delete(),
                    sendMessage(msg, final_error_msg, timer=60),
                )
            return False, None, error_msg

        # 验证通过,扣除余额
        sql_update_emby(Emby.tg == msg.from_user.id, iv=e.iv - money)
        return True, msg.from_user.first_name, None

    else:
        # 频道/群组发送
        first_name = msg.chat.title if msg.sender_chat.id == msg.chat.id else None
        if not first_name:
            return False, None, "无法获取发送者名称"
        return True, first_name, None


async def get_user_photo(user):
    """获取用户头像"""
    if not user.photo:
        return None
    return await bot.download_media(
        user.photo.big_file_id,
        in_memory=True,
    )


async def generate_final_message(envelope):
    """生成红包领取完毕的消息"""
    if envelope.type == "private":
        receiver = envelope.receivers[envelope.target_user]
        return (
            f"🧧 {sakura_b}红包\n\n**{envelope.message}\n\n"
            f"🕶️{envelope.sender_name} **的专属红包已被 "
            f"[{receiver['name']}](tg://user?id={envelope.target_user}) 领取"
        )

    # 排序领取记录
    sorted_receivers = sorted(
        envelope.receivers.items(), key=lambda x: x[1]["amount"], reverse=True
    )

    text = (
        f"🧧 {sakura_b}红包\n\n**{random.choice(Yulv.load_yulv().red_bag)}\n\n"
        f"😎 {envelope.sender_name} **的红包已经被抢光啦~\n\n"
    )

    for i, (user_id, details) in enumerate(sorted_receivers):
        if i == 0:
            text += f"**🏆 手气最佳 [{details['name']}](tg://user?id={user_id}) **获得了 {details['amount']} {sakura_b}"
        else:
            text += f"\n**[{details['name']}](tg://user?id={user_id})** 获得了 {details['amount']} {sakura_b}"

    return text


@bot.on_message(
    filters.command("srank", prefixes) & user_in_group_on_filter & filters.group
)
async def s_rank(_, msg):
    await msg.delete()
    sender = None
    if not msg.sender_chat:
        e = sql_get_emby(tg=msg.from_user.id)
        if judge_admins(msg.from_user.id):
            sender = msg.from_user.id
        elif not e or e.iv < 5:
            await asyncio.gather(
                msg.delete(),
                msg.chat.restrict_member(
                    msg.from_user.id,
                    ChatPermissions(),
                    datetime.now() + timedelta(minutes=1),
                ),
                sendMessage(
                    msg,
                    f"[{msg.from_user.first_name}]({msg.from_user.id}) "
                    f"未私聊过bot或不足支付手续费5{sakura_b}，禁言一分钟。",
                    timer=60,
                ),
            )
            return
        else:
            sql_update_emby(Emby.tg == msg.from_user.id, iv=e.iv - 5)
            sender = msg.from_user.id
    elif msg.sender_chat.id == msg.chat.id:
        sender = msg.chat.id
    reply = await msg.reply(f"已扣除手续5{sakura_b}, 请稍等......加载中")
    text, i = await users_iv_rank()
    t = "❌ 数据库操作失败" if not text else text[0]
    button = await users_iv_button(i, 1, sender or msg.chat.id)
    await asyncio.gather(
        reply.delete(),
        sendPhoto(
            msg,
            photo=bot_photo,
            caption=f"**▎🏆 {sakura_b}风云录**\n\n{t}",
            buttons=button,
        ),
    )


@cache.memoize(ttl=120)
async def users_iv_rank():
    with Session() as session:
        # 查询 Emby 表的所有数据，且>0 的条数
        p = session.query(func.count()).filter(Emby.iv > 0).scalar()
        if p == 0:
            return None, 1
        # 创建一个空字典来存储用户的 first_name 和 id
        members_dict = await get_users()
        i = math.ceil(p / 10)
        a = []
        b = 1
        m = ["🥇", "🥈", "🥉", "🏅"]
        # 分析出页数，将检索出 分割p（总数目）的 间隔，将间隔分段，放进【】中返回
        while b <= i:
            d = (b - 1) * 10
            # 查询iv排序，分页查询
            result = (
                session.query(Emby)
                .filter(Emby.iv > 0)
                .order_by(Emby.iv.desc())
                .limit(10)
                .offset(d)
                .all()
            )
            e = 1 if d == 0 else d + 1
            text = ""
            for q in result:
                name = str(members_dict.get(q.tg, q.tg))[:12]
                medal = m[e - 1] if e < 4 else m[3]
                text += f"{medal}**第{cn2an.an2cn(e)}名** | [{name}](tg://user?id={q.tg}) の **{q.iv} {sakura_b}**\n"
                e += 1
            a.append(text)
            b += 1
        # a 是内容物，i是页数
        return a, i


# 检索翻页
@bot.on_callback_query(filters.regex("users_iv") & user_in_group_on_filter)
async def users_iv_pikb(_, call):
    # print(call.data)
    j, tg = map(int, call.data.split(":")[1].split("_"))
    if call.from_user.id != tg:
        if not judge_admins(call.from_user.id):
            return await callAnswer(
                call, "❌ 这不是你召唤出的榜单，请使用自己的 /srank", True
            )

    await callAnswer(call, f"将为您翻到第 {j} 页")
    a, b = await users_iv_rank()
    button = await users_iv_button(b, j, tg)
    text = a[j - 1]
    await editMessage(call, f"**▎🏆 {sakura_b}风云录**\n\n{text}", buttons=button)
