import pytz
import asyncio

from bot import bot, _open, save_config, owner, admins, bot_name, ranks, schedall, group, config
from bot.sql_helper.sql_code import sql_add_code
from bot.sql_helper.sql_emby import sql_get_emby, sql_count_emby
from cacheout import Cache

cache = Cache()

# 注册并发控制配置
REGISTRATION_SEMAPHORE = asyncio.Semaphore(8)  # 最多8个并发注册
REGISTRATION_QUEUE = {}  # 注册队列状态跟踪
REGISTRATION_STATS = {
    'total_registrations': 0,
    'concurrent_registrations': 0,
    'failed_registrations': 0,
    'total_time': 0
}

# 添加一个锁来保护队列操作
_queue_lock = asyncio.Lock()

class RegistrationController:
    """注册流程控制器"""
    
    @staticmethod
    async def add_to_queue(user_id, user_name):
        """添加用户到注册队列"""
        async with _queue_lock:
            # 检查用户是否已经在队列中
            if user_id in REGISTRATION_QUEUE:
                return None  # 用户已在队列中
            
            queue_position = len(REGISTRATION_QUEUE) + 1
            REGISTRATION_QUEUE[user_id] = {
                'position': queue_position,
                'user_name': user_name,
                'start_time': asyncio.get_event_loop().time(),
                'status': 'waiting'
            }
            return queue_position
    
    @staticmethod
    async def remove_from_queue(user_id):
        """从队列中移除用户"""
        async with _queue_lock:
            REGISTRATION_QUEUE.pop(user_id, None)
    
    @staticmethod
    async def update_status(user_id, status):
        """更新用户状态（线程安全）"""
        async with _queue_lock:
            if user_id in REGISTRATION_QUEUE:
                REGISTRATION_QUEUE[user_id]['status'] = status
    
    @staticmethod
    async def get_queue_status(user_id):
        """获取用户在队列中的状态"""
        return REGISTRATION_QUEUE.get(user_id)
    
    @staticmethod
    async def get_queue_length():
        """获取当前队列长度"""
        return len(REGISTRATION_QUEUE)

async def register_with_concurrency_control(user_id, user_name, func, *args, **kwargs):
    """
    注册并发控制包装器 - 防止同时过多注册请求
    """
    from bot.sql_helper.sql_emby import sql_count_emby
    from bot import _open, bot, LOGGER
    
    # 第一次人数检查：在加入队列前
    tg, current_count, white = sql_count_emby()
    if _open.all_user != 999999 and current_count >= _open.all_user:
        try:
            await bot.send_message(user_id, f"🚫 很抱歉，注册已满员\n\n当前用户数：{current_count}/{_open.all_user}")
        except Exception:
            pass
        LOGGER.info(f"【注册限制】用户 {user_id} 尝试注册被拒绝：已达人数上限 {current_count}/{_open.all_user}")
        return None
    
    # 检查队列长度
    async with _queue_lock:
        current_queue_length = len(REGISTRATION_QUEUE)
    
    if current_queue_length >= 25:
        try:
            await bot.send_message(user_id, f"🚫 注册人数过多，请稍后再试\n\n当前排队：{current_queue_length}/25")
        except Exception:
            pass
        return None
    
    # 添加到队列
    queue_position = await RegistrationController.add_to_queue(user_id, user_name)
    if queue_position is None:
        try:
            await bot.send_message(user_id, "⚠️ 您已在注册队列中，请耐心等待")
        except Exception:
            pass
        return None
    
    try:
        # 发送队列位置通知
        if queue_position > 1:
            try:
                await bot.send_message(user_id, f"📋 您已加入注册队列\n排队位置：第 {queue_position} 位")
            except Exception:
                pass
        
        # 获取信号量（等待轮到自己）
        async with REGISTRATION_SEMAPHORE:
            try:
                # 第二次人数检查：在开始注册前（获取信号量后）
                tg, current_count_final, white = sql_count_emby()
                if _open.all_user != 999999 and current_count_final >= _open.all_user:
                    try:
                        await bot.send_message(user_id, f"🚫 注册期间已达人数限制\n\n当前用户数：{current_count_final}/{_open.all_user}\n\n您的注册已取消")
                    except Exception:
                        pass
                    LOGGER.info(f"【注册限制】用户 {user_id} 注册被取消：注册期间达到人数上限 {current_count_final}/{_open.all_user}")
                    return None
                
                # 更新状态为处理中
                await RegistrationController.update_status(user_id, 'processing')
                
                # 执行实际注册
                result = await func(*args, **kwargs)
                
                # 更新统计
                REGISTRATION_STATS['total_registrations'] += 1
                if result:
                    LOGGER.info(f"【注册成功】用户 {user_id}({user_name}) 注册完成")
                else:
                    REGISTRATION_STATS['failed_registrations'] += 1
                    LOGGER.warning(f"【注册失败】用户 {user_id}({user_name}) 注册失败")
                
                return result
                
            except Exception as e:
                REGISTRATION_STATS['failed_registrations'] += 1
                LOGGER.error(f"【注册异常】用户 {user_id}({user_name}) 注册出现异常: {str(e)}")
                try:
                    await bot.send_message(user_id, f"❌ 注册过程中发生错误，请稍后重试")
                except Exception:
                    pass
                return None
                
    finally:
        # 清理队列（确保在所有情况下都能清理）
        try:
            await RegistrationController.remove_from_queue(user_id)
        except Exception as e:
            LOGGER.error(f"【队列清理】清理用户 {user_id} 队列状态失败: {str(e)}")
        
        # 更新并发计数
        try:
            async with _queue_lock:
                REGISTRATION_STATS['concurrent_registrations'] = len(REGISTRATION_QUEUE)
        except Exception:
            pass


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


async def send_register_end_message(register_mode, current_users, start_users=None):
    """发送注册结束消息到群组
    
    Args:
        register_mode: 注册模式 ("coin", "free", "timing")
        current_users: 当前注册用户数
        start_users: 注册开始时的用户数（可选，用于计算新增席位）
    """
    from bot import sakura_b, bot_photo, bot
    from bot.sql_helper.sql_emby import sql_count_emby
    
    # 重新获取最新数据以确保准确性
    tg, final_users, white = sql_count_emby()
    
    # 计算新增席位和剩余可注册
    if start_users is not None:
        new_seats = final_users - start_users
    else:
        # 如果没有提供开始用户数，则使用当前用户数作为新增（向后兼容）
        new_seats = 0
    
    remaining_seats = _open.all_user - final_users if final_users < _open.all_user else 0
    
    # 根据注册模式生成不同的推送消息
    if register_mode == "coin":
        text = f'💰** {sakura_b}注册结束**：\n\n🍉 目前席位：{final_users}\n🥝 新增席位：{new_seats}\n🍋 剩余席位：{remaining_seats}'
    elif register_mode == "free":
        text = f'🆓** 自由注册结束**：\n\n🍉 目前席位：{final_users}\n🥝 新增席位：{new_seats}\n🍋 剩余席位：{remaining_seats}'
    elif register_mode == "timing":
        text = f'⏳** 定时注册结束**：\n\n🍉 目前席位：{final_users}\n🥝 新增席位：{new_seats}\n🍋 剩余席位：{remaining_seats}'
    else:
        text = f'📝** 注册结束**：\n\n🍉 目前席位：{final_users}\n🥝 新增席位：{new_seats}\n🍋 剩余席位：{remaining_seats}'
    
    # 发送到主群组
    try:
        await bot.send_photo(chat_id=group[0], photo=bot_photo, caption=text)
    except Exception as e:
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


async def check_registration_overflow():
    """
    检查注册是否超额的监控函数
    """
    from bot.sql_helper.sql_emby import sql_count_emby
    from bot import _open, LOGGER, bot, owner
    
    try:
        tg, current_count, white = sql_count_emby()
        if current_count > _open.all_user:
            overflow_count = current_count - _open.all_user
            
            # 记录警告日志
            LOGGER.warning(f"【超额注册】检测到超额注册：{current_count}/{_open.all_user}，超出{overflow_count}人")
            
            # 通知管理员
            try:
                await bot.send_message(
                    owner,
                    f"⚠️ **超额注册警报**\n\n"
                    f"• 当前用户数：{current_count}\n"
                    f"• 设定限制：{_open.all_user}\n"
                    f"• 超出人数：{overflow_count}\n\n"
                    f"建议检查并发控制是否正常工作"
                )
            except Exception:
                pass
            
            return overflow_count
        return 0
    except Exception as e:
        LOGGER.error(f"【监控异常】检查注册超额状态失败: {str(e)}")
        return -1

def get_registration_stats():
    """
    获取注册统计信息
    """
    queue_length = len(REGISTRATION_QUEUE)
    return {
        'queue_length': queue_length,
        'total_registrations': REGISTRATION_STATS['total_registrations'],
        'failed_registrations': REGISTRATION_STATS['failed_registrations'],
        'concurrent_registrations': REGISTRATION_STATS['concurrent_registrations'],
        'success_rate': (
            (REGISTRATION_STATS['total_registrations'] - REGISTRATION_STATS['failed_registrations']) 
            / max(REGISTRATION_STATS['total_registrations'], 1) * 100
        )
    }
