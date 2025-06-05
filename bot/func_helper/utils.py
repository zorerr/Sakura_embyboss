import pytz
import asyncio
import time

from bot import bot, _open, save_config, owner, admins, bot_name, ranks, schedall, group, config
from bot.sql_helper.sql_code import sql_add_code
from bot.sql_helper.sql_emby import sql_get_emby, sql_count_emby
from cacheout import Cache

cache = Cache()

def judge_admins(uid):
    """
    判断是否admin
    :param uid: tg_id
    :return: bool
    """
    if uid != owner and uid not in admins and uid not in group:
        return False
    else:
        return True

# @cache.memoize(ttl=60)
async def members_info(tg=None, name=None):
    """
    基础资料 - 可传递 tg,emby_name
    :param tg: tg_id
    :param name: emby_name
    :return: name, lv, ex, us, embyid, pwd2
    """
    if tg is None:
        tg = name
    data = sql_get_emby(tg)
    if data is None:
        return None
    else:
        name = data.name or '无账户信息'
        pwd2 = data.pwd2
        embyid = data.embyid
        us = data.iv
        lv_dict = {'a': '白名单', 'b': '**正常**', 'c': '**已禁用**', 'd': '未注册'}  # , 'e': '**21天未活跃/无信息**'
        lv = lv_dict.get(data.lv, '未知')
        if lv == '白名单':
            ex = '+ ∞'
        elif data.name is not None and schedall.low_activity and not schedall.check_ex:
            ex = f'__若{config.keep_alive_days}天无观看将封禁__'
        elif data.name is not None and not schedall.low_activity and not schedall.check_ex:
            ex = ' __无需保号，放心食用__'
        else:
            ex = data.ex or '无账户信息'
        return name, lv, ex, us, embyid, pwd2


async def open_check():
    """
    对config查询open
    :return: open_stats, all_user, tem, timing
    """
    open_stats = _open.stat
    all_user = _open.all_user
    tem = _open.tem
    timing = _open.timing
    return open_stats, all_user, tem, timing


def tem_deluser():
    _open.tem = _open.tem - 1
    save_config()


async def send_register_end_message(register_mode, current_users, start_users=None, admin_name=None):
    """发送注册结束消息到群组
    
    Args:
        register_mode: 注册模式 ("coin", "free", "timing", "coin_closed", "free_closed", "timing_closed")
        current_users: 当前注册用户数
        start_users: 注册开始时的用户数（可选，用于计算新增席位）
        admin_name: 管理员名称（用于手动关闭的情况）
    """
    from bot import sakura_b, bot_photo, bot, LOGGER
    from bot.sql_helper.sql_emby import sql_count_emby
    
    LOGGER.debug(f"【群组推送】开始发送 {register_mode} 模式注册结束消息")
    
    # 重新获取最新数据以确保准确性
    tg, final_users, white = sql_count_emby()
    
    # 计算新增席位和剩余可注册
    if start_users is not None:
        new_seats = final_users - start_users
    else:
        # 如果没有提供开始用户数，则使用当前用户数作为新增（向后兼容）
        new_seats = 0
    
    # 处理剩余席位显示：999999表示无限制
    if _open.all_user == 999999:
        remaining_seats = "无限制"
        all_user_display = "无限制"
    else:
        remaining_seats = _open.all_user - final_users if final_users < _open.all_user else 0
        all_user_display = str(_open.all_user)
    
    # 根据注册模式生成不同的推送消息
    if register_mode == "coin":
        text = f'💰** {sakura_b}注册结束**：\n\n🍉 目前席位：{final_users}\n🥝 新增席位：{new_seats}\n🍋 剩余席位：{remaining_seats}'
    elif register_mode == "free":
        text = f'🆓** 自由注册结束**：\n\n🍉 目前席位：{final_users}\n🥝 新增席位：{new_seats}\n🍋 剩余席位：{remaining_seats}'
    elif register_mode == "timing":
        text = f'⏳** 定时注册结束**：\n\n🍉 目前席位：{final_users}\n🥝 新增席位：{new_seats}\n🍋 剩余席位：{remaining_seats}'
    elif register_mode == "coin_closed":
        register_type = f"{sakura_b}注册"
        text = f'🫧 管理员 {admin_name or "未知"} 已关闭 **{register_type}**\n\n' \
               f'💰 所需{sakura_b} | {_open.coin_cost}\n🎫 总注册限制 | {all_user_display}\n🎟️ 已注册人数 | {final_users}\n' \
               f'🎭 剩余可注册 | **{remaining_seats}**\n🤖 bot使用人数 | {tg}'
    elif register_mode == "free_closed":
        register_type = "自由注册"
        text = f'🫧 管理员 {admin_name or "未知"} 已关闭 **{register_type}**\n\n' \
               f'🎫 总注册限制 | {all_user_display}\n🎟️ 已注册人数 | {final_users}\n' \
               f'🎭 剩余可注册 | **{remaining_seats}**\n🤖 bot使用人数 | {tg}'
    elif register_mode == "timing_closed":
        register_type = "定时注册"
        text = f'🫧 管理员 {admin_name or "未知"} 已关闭 **{register_type}**\n\n' \
               f'⏳ 原定时长 | {getattr(_open, "original_timing", "未知")} min（已终止）\n🎫 总注册限制 | {all_user_display}\n🎟️ 已注册人数 | {final_users}\n' \
               f'🎭 剩余可注册 | **{remaining_seats}**\n🤖 bot使用人数 | {tg}'
    else:
        text = f'📝** 注册结束**：\n\n🍉 目前席位：{final_users}\n🥝 新增席位：{new_seats}\n🍋 剩余席位：{remaining_seats}'
    
    LOGGER.debug(f"【群组推送】推送内容：{text[:100]}...")
    
    # 发送到主群组
    try:
        await bot.send_photo(chat_id=group[0], photo=bot_photo, caption=text)
        LOGGER.debug(f"【群组推送】{register_mode} 模式推送成功发送到群组 {group[0]}")
    except Exception as e:
        LOGGER.error(f"【群组推送】发送注册结束消息失败: {e}")
        print(f"发送注册结束消息失败: {e}")


# 保留原函数以保持向后兼容性，但内部调用新的统一函数
async def send_coin_register_end_message():
    """发送{sakura_b}注册结束消息到群组 - 向后兼容性函数"""
    from bot.sql_helper.sql_emby import sql_count_emby
    tg, current_users, white = sql_count_emby()
    await send_register_end_message("coin", current_users)


from random import choice
import string


async def pwd_create(length=8, chars=string.ascii_letters + string.digits):
    """
    简短地生成随机密码，包括大小写字母、数字，可以指定密码长度
    :param length: 长度
    :param chars: 字符 -> python3中为string.ascii_letters,而python2下则可以使用string.letters和string.ascii_letters
    :return: 密码
    """
    return ''.join([choice(chars) for i in range(length)])


# 创建注册
async def cr_link_one(tg: int, times, count, days: int, method: str):
    """
    创建连接
    :param tg:
    :param times:
    :param count:
    :param days:
    :param method:
    :return:
    """
    links = ''
    code_list = []
    i = 1
    if method == 'code':
        while i <= count:
            p = await pwd_create(10)
            uid = f'{ranks.logo}-{times}-Register_{p}'
            code_list.append(uid)
            link = f'`{uid}`\n'
            links += link
            i += 1
    elif method == 'link':
        while i <= count:
            p = await pwd_create(10)
            uid = f'{ranks.logo}-{times}-Register_{p}'
            code_list.append(uid)
            link = f't.me/{bot_name}?start={uid}\n'
            links += link
            i += 1
    if sql_add_code(code_list, tg, days) is False:
        return None
    return links


# 创建续期
async def rn_link_one(tg: int, times, count, days: int, method: str):
    """
    创建连接
    :param tg:
    :param times:
    :param count:
    :param days:
    :param method:
    :return:
    """
    links = ''
    code_list = []
    i = 1
    if method == 'code':
        while i <= count:
            p = await pwd_create(10)
            uid = f'{ranks.logo}-{times}-Renew_{p}'
            code_list.append(uid)
            link = f'`{uid}`\n'
            links += link
            i += 1
    elif method == 'link':
        while i <= count:
            p = await pwd_create(10)
            uid = f'{ranks.logo}-{times}-Renew_{p}'
            code_list.append(uid)
            link = f't.me/{bot_name}?start={uid}\n'
            links += link
            i += 1
    if sql_add_code(code_list, tg, days) is False:
        return None
    return links


async def cr_link_two(tg: int, for_tg, days: int):
    code_list = []
    invite_code = await pwd_create(11)
    uid = f'{for_tg}-{invite_code}'
    code_list.append(uid)
    link = f't.me/{bot_name}?start={uid}'
    if sql_add_code(code_list, tg, days) is False:
        return None
    return link


from datetime import datetime, timedelta


async def convert_s(seconds: int):
    # 创建一个时间间隔对象，换算以后返回计算出的字符串
    duration = timedelta(seconds=seconds)
    days = duration.days
    hours, remainder = divmod(duration.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    days = '' if days == 0 else f'{days} 天'
    hours = '' if hours == 0 else f'{hours} 小时'
    return f"{days} {hours} {minutes} 分钟"


def convert_runtime(RunTimeTicks: int):
    # 创建一个时间间隔对象，换算以后返回计算出的字符串
    seconds = RunTimeTicks // 10000000
    duration = timedelta(seconds=seconds)
    hours, remainder = divmod(duration.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    hours = '' if hours == 0 else f'{hours} 小时'
    return f"{hours} {minutes} 分钟"


def convert_to_beijing_time(original_date):
    original_date = original_date.split(".")[0].replace('T', ' ')
    dt = datetime.strptime(original_date, "%Y-%m-%d %H:%M:%S") + timedelta(hours=8)
    # 使用pytz.timezone函数获取北京时区对象
    beijing_tz = pytz.timezone("Asia/Shanghai")
    # 使用beijing_tz.localize函数将dt对象转换为有时区的对象
    dt = beijing_tz.localize(dt)
    return dt


@cache.memoize(ttl=300)
async def get_users():
    # 创建一个空字典来存储用户的 first_name 和 id
    members_dict = {}
    async for member in bot.get_chat_members(group[0]):
        try:
            members_dict[member.user.id] = member.user.first_name
        except Exception as e:
            print(f'{e} 某名bug {member}')
    return members_dict


def bytes_to_gb(size_in_bytes):
    # 1 GB = 1024^3 字节
    size_in_gb = size_in_bytes / (1024 ** 3)
    return f"{round(size_in_gb)} G"


import abc


class Singleton(abc.ABCMeta, type):
    """
    类单例
    """

    _instances: dict = {}

    def __call__(cls, *args, **kwargs):
        key = (cls, args, frozenset(kwargs.items()))
        if key not in cls._instances:
            cls._instances[key] = super().__call__(*args, **kwargs)
        return cls._instances[key]

# import random
# import grequests


# def err_handler(request, exception):
#     get_bot_wlc()


# def random_shici_data(data_list, x):
#     try:
#         # 根据不同的url返回的数据结构，获取相应的字段
#         if x == 0:
#             ju, nm = data_list[0]["content"], f'{data_list[0]["author"]}《{data_list[0]["origin"]}》'
#         elif x == 1:
#             ju, nm = data_list[1]["hitokoto"], f'{data_list[1]["from_who"]}《{data_list[1]["from"]}》'
#         elif x == 2:
#             ju, nm = data_list[2]["content"], data_list[2]["source"]
#             # 如果没有作者信息，就不显示
#         return ju, nm
#     except:
#         return False


# # 请求每日诗词
# def get_bot_shici():
#     try:
#         urls = ['https://v1.jinrishici.com/all.json', 'https://international.v1.hitokoto.cn/?c=i',
#                 'http://yijuzhan.com/api/word.php?m=json']
#         reqs = [grequests.get(url) for url in urls]
#         res_list = grequests.map(reqs)  # exception_handler=err_handler
#         data_list = [res.json() for res in res_list]
#         # print(data_list)
#         seq = [0, 1, 2]
#         x = random.choice(seq)
#         seq.remove(x)
#         e = random.choice(seq)
#         ju, nm = random_shici_data(data_list, x=x)
#         e_ju, e_nm = random_shici_data(data_list, x=e)
#         e_ju = random.sample(e_ju, 6)
#         T = ju
#         t = random.sample(ju, 2)
#         e_ju.extend(t)
#         random.shuffle(e_ju)
#         for i in t:
#             ju = ju.replace(i, '░')  # ░
#         print(T, e_ju, ju, nm)
#         return T, e_ju, ju, nm
#     except Exception as e:
#         print(e)
#         # await get_bot_shici()
