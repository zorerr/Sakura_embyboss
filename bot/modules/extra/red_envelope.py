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

from bot import bot, prefixes, sakura_b, bot_photo, red_envelope, LOGGER
from bot.func_helper.filters import user_in_group_on_filter
from bot.func_helper.fix_bottons import users_iv_button
from bot.func_helper.msg_utils import sendPhoto, sendMessage, callAnswer, editMessage
from bot.func_helper.utils import pwd_create, judge_admins, get_users, cache
from bot.func_helper.scheduler import scheduler
from bot.sql_helper import Session
from bot.sql_helper.sql_emby import Emby, sql_get_emby, sql_update_emby
from bot.ranks_helper.ranks_draw import RanksDraw
from bot.schemas import Yulv, MAX_INT_VALUE, MIN_INT_VALUE

# 小项目，说实话不想写数据库里面。放内存里了，从字典里面每次拿分

red_envelopes = {}

# 红包锁字典，用于并发控制
red_envelope_locks = {}

# 全局锁，用于保护锁字典的创建操作
_lock_creation_lock = asyncio.Lock()

# 红包过期时间（小时）
RED_ENVELOPE_EXPIRE_HOURS = 24


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
        self.created_time = datetime.now()  # 创建时间


async def create_reds(
    money, members, first_name, sender_id, flag=None, private=None, private_text=None
):
    red_id = await pwd_create(5)
    envelope = RedEnvelope(
        money=money, members=members, sender_id=sender_id, sender_name=first_name
    )

    if flag or money < 0:  # 负数金额红包强制使用均分模式
        envelope.type = "equal"
        if money < 0:
            LOGGER.debug(f"【负分红包】强制使用均分模式：金额={money}, 份数={members}")
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
    
    # 先检查红包是否存在，避免为不存在的红包创建锁
    if red_id not in red_envelopes:
        return await callAnswer(
            call, "/(ㄒoㄒ)/~~ \n\n来晚了，红包已经被抢光啦。", True
        )
    
    # 安全地获取或创建红包锁
    async with _lock_creation_lock:
        if red_id not in red_envelope_locks:
            red_envelope_locks[red_id] = asyncio.Lock()
        envelope_lock = red_envelope_locks[red_id]
    
    # 使用红包专用锁保护整个领取过程
    async with envelope_lock:
        # 在锁内再次检查红包是否存在（可能在等锁期间被删除）
        try:
            envelope = red_envelopes[red_id]
        except (IndexError, KeyError):
            return await callAnswer(
                call, "/(ㄒoㄒ)/~~ \n\n来晚了，红包已经被抢光啦。", True
            )

        # 检查红包是否过期
        if is_envelope_expired(envelope):
            # 处理过期红包
            if red_id in red_envelopes:  # 再次检查红包是否还存在
                await handle_expired_envelope(red_id, envelope)
                # 清理锁
                red_envelope_locks.pop(red_id, None)
            return await callAnswer(
                call, f"/(ㄒoㄒ)/~~ \n\n红包已过期({RED_ENVELOPE_EXPIRE_HOURS}小时)，剩余金额已退还给发送者。", True
            )

        # 验证用户资格
        e = sql_get_emby(tg=call.from_user.id)
        if not e:
            return await callAnswer(call, "你还未私聊bot! 数据库没有你.", True)

        # 检查是否已领取（在锁内再次检查）
        if call.from_user.id in envelope.receivers:
            return await callAnswer(call, "ʕ•̫͡•ʔ 你已经领取过红包了。不许贪吃", True)

        # 检查红包是否已抢完（在锁内再次检查）
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

        # 在锁保护下计算领取金额
        amount = 0
        # 处理均分红包
        if envelope.type == "equal":
            # 均分红包：需要考虑负数金额的情况
            abs_money = abs(envelope.money)
            abs_members = abs(envelope.members)
            base_amount = abs_money // abs_members
            remainder = abs_money % abs_members
            current_receivers = len(envelope.receivers)
            
            if envelope.money >= 0:
                # 正数金额：前remainder个人多分1分
                amount = base_amount + (1 if current_receivers < remainder else 0)
            else:
                # 负数金额：按负数分配，前remainder个人多扣1分
                amount = -(base_amount + (1 if current_receivers < remainder else 0))
                # 记录详细日志以便排查问题
                LOGGER.debug(f"【负分红包均分】金额={envelope.money}, 剩余金额={envelope.rest_money}, 份数={envelope.members}, 剩余份数={envelope.rest_members}, 当前领取人数={current_receivers}, 基础金额={base_amount}, 余数={remainder}, 分配金额={amount}")

        # 处理专享红包
        elif envelope.type == "private":
            if call.from_user.id != envelope.target_user:
                return await callAnswer(call, "ʕ•̫͡•ʔ 这是你的专属红包吗？", True)
            amount = envelope.rest_money

        # 处理拼手气红包
        else:
            if envelope.members > 0:
                # 正数份数的拼手气红包
                if envelope.rest_members > 1 and envelope.rest_money > 1:
                    # 确保至少给最后一个人留1分
                    max_amount = envelope.rest_money - (envelope.rest_members - 1)
                    if max_amount >= 1:
                        k = 2 * envelope.rest_money / envelope.rest_members
                        amount = int(random.uniform(1, min(k, max_amount, envelope.rest_money)))
                        amount = max(1, amount)  # 确保至少1分
                    else:
                        amount = 1  # 最小保证1分
                else:
                    amount = envelope.rest_money
    # 边界安全：确保领取金额合法，区分正负金额红包
    if envelope.money >= 0:
        # 正数金额红包：金额不能小于0，不能大于剩余金额
        amount = max(0, min(amount, envelope.rest_money))
        # 防止出现0分红包（除非剩余金额确实为0）
        if envelope.rest_money > 0 and amount == 0:
            amount = 1
    else:
        # 负数金额红包：金额应为负数，且绝对值不能大于剩余金额的绝对值
        amount = max(amount, envelope.rest_money)
        # 防止出现0分红包（负数情况）
        if amount == 0:
            amount = -1  # 至少扣除1分
    

    # 数据库事务保护：先更新用户余额，成功后再更新红包状态
    try:
        # 更新用户余额
        new_balance = e.iv + amount
        if new_balance > MAX_INT_VALUE or new_balance < MIN_INT_VALUE:
            return await callAnswer(call, f"账户余额超出安全范围（{MIN_INT_VALUE} 到 {MAX_INT_VALUE}）。", True)
        sql_update_emby(Emby.tg == call.from_user.id, iv=new_balance)
        
        # 数据库操作成功后，更新红包状态
        envelope.receivers[call.from_user.id] = {
            "amount": amount,
            "name": call.from_user.first_name or "Anonymous",
        }
        envelope.rest_money -= amount
        
        # 更新剩余份数
        if envelope.members > 0:
            # 正数份数：直接减1
            envelope.rest_members -= 1
        # 负数份数不需要更新rest_members，因为我们使用len(envelope.receivers)来追踪已领取人数
        
        # 记录负分红包领取后的状态（用于调试）
        if envelope.money < 0:
            LOGGER.debug(f"【负分红包领取】用户ID={call.from_user.id}, 金额={amount}, 剩余金额={envelope.rest_money}, 剩余份数={envelope.rest_members}, 当前领取人数={len(envelope.receivers)}")
    except Exception as db_error:
        LOGGER.error(f"【红包领取失败】数据库更新失败:{db_error}，用户:{call.from_user.id}")
        return await callAnswer(call, "❌ 系统繁忙，请稍后再试", True)
        
    # 提示用户领取成功
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
        # 记录红包完成日志
        if envelope.money < 0:
            LOGGER.info(f"【负分红包完成】红包{red_id}已被领完，总共{len(envelope.receivers)}人领取，总金额{envelope.money}")
        else:
            LOGGER.info(f"【红包完成】红包{red_id}已被领完，总共{len(envelope.receivers)}人领取")
            
        # 从内存中移除红包和锁
        red_envelopes.pop(red_id)
        red_envelope_locks.pop(red_id, None)
        
        # 生成并显示红包领取结果
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

    # 排序领取记录（按金额绝对值排序，对于负数金额的红包，绝对值越大的越靠前）
    sorted_receivers = sorted(
        envelope.receivers.items(), key=lambda x: abs(x[1]["amount"]), reverse=True
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


@bot.on_message(filters.command("srank", prefixes) & user_in_group_on_filter & filters.group)
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


def is_envelope_expired(envelope):
    """检查红包是否过期"""
    expire_time = envelope.created_time + timedelta(hours=RED_ENVELOPE_EXPIRE_HOURS)
    return datetime.now() > expire_time


async def handle_expired_envelope(envelope_id, envelope):
    """处理过期红包，退还余额给发送者"""
    try:
        LOGGER.info(f"【红包过期处理】开始处理过期红包:{envelope_id}, 剩余金额:{envelope.rest_money}")
        
        # 计算需要退还的金额
        refund_amount = envelope.rest_money
        
        if refund_amount > 0 and envelope.sender_id:
            # 退还金额给发送者
            e = sql_get_emby(tg=envelope.sender_id)
            if e:
                new_balance = e.iv + refund_amount
                sql_update_emby(Emby.tg == envelope.sender_id, iv=new_balance)
                LOGGER.info(f"【红包过期退款】退还{refund_amount}{sakura_b}给用户{envelope.sender_id}, 新余额:{new_balance}")
                
                # 发送过期通知
                try:
                    expire_msg = (
                        f"🧧 **红包过期通知**\n\n"
                        f"您的红包已过期，剩余 {refund_amount} {sakura_b} 已自动退还\n"
                        f"过期时间：{RED_ENVELOPE_EXPIRE_HOURS}小时"
                    )
                    await bot.send_message(envelope.sender_id, expire_msg)
                    LOGGER.info(f"【红包过期通知】已向用户{envelope.sender_id}发送过期通知")
                except Exception as notify_error:
                    LOGGER.warning(f"【红包过期通知】发送通知失败:{notify_error}")
            else:
                LOGGER.error(f"【红包过期退款】用户{envelope.sender_id}数据不存在，无法退款")
        else:
            LOGGER.info(f"【红包过期处理】红包{envelope_id}无需退款，剩余金额:{refund_amount}")
        
        # 从红包字典中移除
        red_envelopes.pop(envelope_id, None)
        # 清理对应的锁
        red_envelope_locks.pop(envelope_id, None)
        LOGGER.info(f"【红包过期处理】红包{envelope_id}处理完成，已从内存中移除")
        return True
        
    except Exception as e:
        # 发生错误时也要移除红包和锁，避免一直占用内存
        red_envelopes.pop(envelope_id, None)
        red_envelope_locks.pop(envelope_id, None)
        LOGGER.error(f"【红包过期处理】处理红包{envelope_id}时发生错误:{e}，已强制移除")
        return False


async def cleanup_expired_envelopes():
    """清理过期红包的定时任务"""
    try:
        LOGGER.info(f"【红包清理任务】开始执行，当前红包总数:{len(red_envelopes)}")
        
        # 查找过期红包 - 先复制字典内容避免迭代时修改
        expired_ids = []
        red_envelopes_copy = dict(red_envelopes)  # 创建副本进行安全遍历
        for envelope_id, envelope in red_envelopes_copy.items():
            if is_envelope_expired(envelope):
                expired_ids.append((envelope_id, envelope))
        
        LOGGER.info(f"【红包清理任务】发现{len(expired_ids)}个过期红包需要处理")
        
        # 串行处理过期红包，避免并发修改字典
        cleanup_count = 0
        total_refund = 0
        for envelope_id, envelope in expired_ids:
            # 在处理前再次检查红包是否还存在（可能已被领完）
            if envelope_id not in red_envelopes:
                continue
                
            refund_before = envelope.rest_money
            success = await handle_expired_envelope(envelope_id, envelope)
            if success:
                cleanup_count += 1
                total_refund += refund_before
                
        if cleanup_count > 0:
            LOGGER.info(f"【红包清理任务】清理完成，处理了{cleanup_count}个过期红包，总退款:{total_refund}{sakura_b}")
        else:
            LOGGER.info(f"【红包清理任务】无过期红包需要清理")
            
        # 记录当前红包状态统计
        active_count = len(red_envelopes)
        if active_count > 0:
            total_money = sum(env.rest_money for env in red_envelopes.values())
            LOGGER.info(f"【红包状态统计】当前活跃红包:{active_count}个，剩余总金额:{total_money}{sakura_b}")
            
        # 清理孤立的锁（对应的红包已不存在）
        orphaned_locks = []
        for lock_id in list(red_envelope_locks.keys()):
            if lock_id not in red_envelopes:
                orphaned_locks.append(lock_id)
        
        for lock_id in orphaned_locks:
            red_envelope_locks.pop(lock_id, None)
            
        if orphaned_locks:
            LOGGER.info(f"【锁清理】清理了{len(orphaned_locks)}个孤立的锁")
            
    except Exception as e:
        LOGGER.error(f"【红包清理任务】清理过程发生错误: {e}")


# 启动红包过期清理定时任务
scheduler.add_job(
    func=cleanup_expired_envelopes,
    trigger='interval',
    hours=24,
    id='cleanup_expired_envelopes',
    replace_existing=True
)
