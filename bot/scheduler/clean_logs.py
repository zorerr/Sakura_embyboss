"""
日志清理任务
每3天删除一次旧日志文件
"""
import os
import glob
from datetime import datetime, timedelta
from bot import LOGGER


async def clean_old_logs():
    """清理3天前的日志文件"""
    try:
        LOGGER.info("【日志清理】开始清理旧日志文件")
        
        # 计算3天前的日期
        three_days_ago = datetime.now() - timedelta(days=3)
        cutoff_date = three_days_ago.strftime('%Y%m%d')
        
        # 获取log目录下的所有日志文件
        log_pattern = "log/log_*.txt"
        log_files = glob.glob(log_pattern)
        
        deleted_count = 0
        for log_file in log_files:
            # 从文件名中提取日期
            filename = os.path.basename(log_file)
            if filename.startswith('log_') and filename.endswith('.txt'):
                date_str = filename[4:12]  # 提取YYYYMMDD部分
                
                # 比较日期，删除3天前的文件
                if date_str < cutoff_date:
                    try:
                        os.remove(log_file)
                        deleted_count += 1
                        LOGGER.info(f"【日志清理】已删除旧日志文件: {log_file}")
                    except OSError as e:
                        LOGGER.error(f"【日志清理】删除文件失败 {log_file}: {e}")
        
        if deleted_count > 0:
            LOGGER.info(f"【日志清理】清理完成，共删除 {deleted_count} 个旧日志文件")
        else:
            LOGGER.info("【日志清理】没有需要清理的旧日志文件")
            
    except Exception as e:
        LOGGER.error(f"【日志清理】清理过程发生错误: {e}") 