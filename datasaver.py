import gzip
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict, is_dataclass
from datetime import datetime, timedelta
from pathlib import Path
from queue import Queue
from typing import Dict, List, Optional, Any, Union
import logging

@dataclass
class KlineData:
    """K线数据结构"""
    symbol: str
    interval: str
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int
    quote_volume: float
    trades: int
    taker_buy_base: float
    taker_buy_quote: float
    ignore: float = 0.0

    @classmethod
    def from_binance_data(cls, symbol: str, interval: str, kline_data: Dict) -> 'KlineData':
        """从币安K线数据创建对象"""
        k = kline_data['k']
        return cls(
            symbol=symbol,
            interval=interval,
            open_time=k['t'],
            open=float(k['o']),
            high=float(k['h']),
            low=float(k['l']),
            close=float(k['c']),
            volume=float(k['v']),
            close_time=k['T'],
            quote_volume=float(k['q']),
            trades=k['n'],
            taker_buy_base=float(k['V']),
            taker_buy_quote=float(k['Q']),
            ignore=float(k['B']) if 'B' in k else 0.0
        )

class KlineDataSaver:
    """K线数据保存器，支持按日期和交易对自动分文件存储"""

    def __init__(
            self,
            base_dir: str = "./kline_data",
            compress: bool = False,
            buffer_size: int = 100,
            flush_interval: int = 10,  # 秒
            use_threading: bool = True
    ):
        """
        初始化K线数据保存器

        Args:
            base_dir: 数据存储根目录
            compress: 是否使用gzip压缩
            buffer_size: 缓冲区大小，达到此数量后自动写入
            flush_interval: 自动刷新间隔（秒）
            use_threading: 是否使用多线程异步写入
        """
        self.base_dir = Path(base_dir)
        self.compress = compress
        self.buffer_size = buffer_size
        self.flush_interval = flush_interval
        self.use_threading = use_threading

        # 创建基础目录
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # 数据缓冲区：{(symbol, date_str): [kline_data]}
        self.buffers: Dict[str, List[Dict]] = {}

        # 当前打开的文件句柄
        self.file_handles: Dict[str, Any] = {}

        # 最后刷新时间
        self.last_flush_time = time.time()

        # 异步写入队列和线程池
        if self.use_threading:
            self.write_queue = Queue(maxsize=1000)
            self.thread_pool = ThreadPoolExecutor(max_workers=2)
            self._start_writer_thread()

        # 文件状态记录
        self.file_status_path = self.base_dir / "file_status.json"
        self.file_status = self._load_file_status()

        logging.info(f"K线数据保存器初始化完成，数据目录: {self.base_dir}")

    def _load_file_status(self) -> Dict:
        """加载文件状态记录"""
        if self.file_status_path.exists():
            try:
                with open(self.file_status_path, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def _save_file_status(self):
        """保存文件状态记录"""
        try:
            with open(self.file_status_path, 'w') as f:
                json.dump(self.file_status, f, indent=2)
        except Exception as e:
            logging.error(f"保存文件状态失败: {e}")

    def _get_date_str(self, timestamp_ms: int) -> str:
        """将时间戳转换为日期字符串"""
        dt = datetime.fromtimestamp(timestamp_ms / 1000)
        return dt.strftime("%Y-%m-%d")

    def _get_file_path(self, symbol: str, date_str: str) -> Path:
        """获取文件路径"""
        # 按交易对创建子目录
        symbol_dir = self.base_dir / symbol
        symbol_dir.mkdir(exist_ok=True)

        # 按时间周期创建子目录
        interval_dir = symbol_dir / "15m"  # 固定为15分钟周期
        interval_dir.mkdir(exist_ok=True)

        # 文件名
        filename = f"{symbol}_15m_{date_str}"
        if self.compress:
            filename += ".json.gz"
        else:
            filename += ".json"

        return interval_dir / filename

    def _open_file(self, symbol: str, date_str: str, mode: str = 'a'):
        """打开文件，返回文件句柄"""
        file_path = self._get_file_path(symbol, date_str)

        # 检查文件是否已经打开
        file_key = f"{symbol}_{date_str}"
        if file_key in self.file_handles:
            return self.file_handles[file_key]

        # 打开新文件
        try:
            if self.compress:
                f = gzip.open(file_path, mode + 't', encoding='utf-8')
            else:
                f = open(file_path, mode, encoding='utf-8')

            self.file_handles[file_key] = f

            # 记录文件状态
            if file_key not in self.file_status:
                self.file_status[file_key] = {
                    'symbol': symbol,
                    'date': date_str,
                    'created_at': datetime.now().isoformat(),
                    'last_updated': datetime.now().isoformat(),
                    'line_count': 0
                }

            logging.debug(f"打开文件: {file_path}")
            return f

        except Exception as e:
            logging.error(f"打开文件失败 {file_path}: {e}")
            raise

    def _close_file(self, symbol: str, date_str: str):
        """关闭文件"""
        file_key = f"{symbol}_{date_str}"
        if file_key in self.file_handles:
            try:
                self.file_handles[file_key].close()
                del self.file_handles[file_key]
                logging.debug(f"关闭文件: {symbol}_{date_str}")
            except Exception as e:
                logging.error(f"关闭文件失败 {file_key}: {e}")

    def _close_all_files(self):
        """关闭所有打开的文件"""
        for file_key in list(self.file_handles.keys()):
            symbol, date_str = file_key.split('_', 1)
            self._close_file(symbol, date_str)

    def _start_writer_thread(self):
        """启动写入线程"""

        def writer_worker():
            while True:
                try:
                    data = self.write_queue.get()
                    if data is None:  # 终止信号
                        break

                    symbol, kline_data, date_str = data
                    self._write_single_kline(symbol, kline_data, date_str)
                    self.write_queue.task_done()

                except Exception as e:
                    logging.error(f"写入线程错误: {e}")

        # 启动线程
        self.thread_pool.submit(writer_worker)
        logging.info("启动异步写入线程")

    def _write_single_kline(self, symbol: str, kline_data: Union[Dict, KlineData], date_str: str):
        """写入单条K线数据"""
        try:
            # 打开文件
            f = self._open_file(symbol, date_str)

            # 转换为JSON字符串
            if is_dataclass(kline_data):
                data_dict = asdict(kline_data)
            else:
                data_dict = kline_data

            json_str = json.dumps(data_dict, ensure_ascii=False)

            # 写入文件（每行一个JSON对象）
            f.write(json_str + '\n')
            f.flush()  # 确保数据立即写入磁盘

            # 更新文件状态
            file_key = f"{symbol}_{date_str}"
            if file_key in self.file_status:
                self.file_status[file_key]['line_count'] += 1
                self.file_status[file_key]['last_updated'] = datetime.now().isoformat()

            logging.debug(f"写入数据: {symbol} | {date_str} | 开盘: {data_dict.get('open')}")

        except Exception as e:
            logging.error(f"写入数据失败 {symbol}_{date_str}: {e}")

    def _buffer_kline(self, symbol: str, kline_data: Dict, date_str: str):
        """缓冲K线数据"""
        buffer_key = f"{symbol}_{date_str}"

        if buffer_key not in self.buffers:
            self.buffers[buffer_key] = []

        self.buffers[buffer_key].append(kline_data)

        # 检查是否达到缓冲区大小
        if len(self.buffers[buffer_key]) >= self.buffer_size:
            self.flush_buffer(buffer_key)

    def flush_buffer(self, buffer_key: Optional[str] = None):
        """刷新缓冲区到文件"""
        try:
            if buffer_key:
                # 刷新指定缓冲区
                if buffer_key in self.buffers and self.buffers[buffer_key]:
                    klines = self.buffers[buffer_key]
                    symbol, date_str = buffer_key.split('_', 1)

                    if self.use_threading:
                        # 异步写入
                        for kline in klines:
                            self.write_queue.put((symbol, kline, date_str))
                    else:
                        # 同步写入
                        for kline in klines:
                            self._write_single_kline(symbol, kline, date_str)

                    # 清空缓冲区
                    self.buffers[buffer_key] = []

            else:
                # 刷新所有缓冲区
                for key in list(self.buffers.keys()):
                    self.flush_buffer(key)

        except Exception as e:
            logging.error(f"刷新缓冲区失败: {e}")

    def save_kline(self, symbol: str, kline_data: Union[Dict, KlineData]):
        """
        保存K线数据

        Args:
            symbol: 交易对，如'BTCUSDC'
            kline_data: K线数据，可以是字典或KlineData对象
        """
        try:
            # 提取时间信息
            if is_dataclass(kline_data):
                timestamp_ms = kline_data.open_time
                data_for_save = kline_data
            else:
                timestamp_ms = kline_data.get('open_time') or kline_data.get('t')
                data_for_save = kline_data

            # 获取日期字符串
            date_str = self._get_date_str(timestamp_ms)

            # 检查是否需要切换文件（日期变化）
            self._check_and_switch_files(symbol, date_str)

            # 缓冲数据
            self._buffer_kline(symbol, data_for_save, date_str)

            # 定期刷新
            current_time = time.time()
            if current_time - self.last_flush_time > self.flush_interval:
                self.flush_buffer()
                self.last_flush_time = current_time

            return True

        except Exception as e:
            logging.error(f"保存K线数据失败: {e}")
            return False

    def _check_and_switch_files(self, symbol: str, current_date_str: str):
        """检查并切换文件（如果日期变化）"""
        # 检查是否有旧日期的文件需要关闭
        for file_key in list(self.file_handles.keys()):
            if file_key.startswith(f"{symbol}_") and not file_key.endswith(f"_{current_date_str}"):
                # 提取日期部分
                old_date_str = file_key.split('_', 1)[1]

                # 关闭旧文件
                self._close_file(symbol, old_date_str)

                # 刷新对应的缓冲区
                buffer_key = f"{symbol}_{old_date_str}"
                if buffer_key in self.buffers:
                    self.flush_buffer(buffer_key)

                logging.info(f"日期变化，关闭旧文件: {symbol}_{old_date_str}")

    def batch_save(self, symbol: str, klines: List[Union[Dict, KlineData]]):
        """批量保存K线数据"""
        success_count = 0
        for kline in klines:
            if self.save_kline(symbol, kline):
                success_count += 1

        # 确保所有数据都写入
        self.flush_buffer()

        logging.info(f"批量保存完成: {symbol} | 成功: {success_count}/{len(klines)}")
        return success_count

    def get_file_info(self, symbol: Optional[str] = None, date_str: Optional[str] = None) -> List[Dict]:
        """获取文件信息"""
        info_list = []

        for file_key, status in self.file_status.items():
            file_symbol, file_date = file_key.split('_', 1)

            if symbol and file_symbol != symbol:
                continue
            if date_str and file_date != date_str:
                continue

            # 获取文件大小
            file_path = self._get_file_path(file_symbol, file_date)
            file_size = file_path.stat().st_size if file_path.exists() else 0

            info_list.append({
                'symbol': file_symbol,
                'date': file_date,
                'file_path': str(file_path),
                'size_bytes': file_size,
                'size_mb': round(file_size / 1024 / 1024, 2),
                'line_count': status.get('line_count', 0),
                'created_at': status.get('created_at'),
                'last_updated': status.get('last_updated')
            })

        return info_list

    def cleanup_old_files(self, days_to_keep: int = 30):
        """清理旧文件"""
        try:
            cutoff_date = datetime.now() - timedelta(days=days_to_keep)
            deleted_count = 0

            for file_key, status in list(self.file_status.items()):
                file_date_str = status['date']
                file_date = datetime.strptime(file_date_str, "%Y-%m-%d")

                if file_date < cutoff_date:
                    file_path = self._get_file_path(status['symbol'], file_date_str)

                    if file_path.exists():
                        file_path.unlink()
                        deleted_count += 1

                    # 从状态中移除
                    del self.file_status[file_key]

            self._save_file_status()
            logging.info(f"清理完成，删除 {deleted_count} 个旧文件")
            return deleted_count

        except Exception as e:
            logging.error(f"清理文件失败: {e}")
            return 0

    def close(self):
        """关闭保存器，释放资源"""
        logging.info("正在关闭K线数据保存器...")

        # 刷新所有缓冲区
        self.flush_buffer()

        # 关闭所有文件
        self._close_all_files()

        # 停止写入线程
        if self.use_threading:
            self.write_queue.put(None)  # 发送终止信号
            self.thread_pool.shutdown(wait=True)

        # 保存文件状态
        self._save_file_status()

        logging.info("K线数据保存器已关闭")


# 用于回测的数据加载器
class BacktestDataLoader:
    """回测数据加载器"""

    @staticmethod
    def load_kline_data(symbol: str, date_str: str, base_dir: str = "./kline_data") -> List[Dict]:
        """加载指定交易对和日期的K线数据"""
        file_path = Path(base_dir) / symbol / "15m" / f"{symbol}_15m_{date_str}.json"
        gz_path = file_path.with_suffix('.json.gz')

        data = []
        try:
            if gz_path.exists():
                # 加载gzip压缩文件
                with gzip.open(gz_path, 'rt', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            data.append(json.loads(line))
            elif file_path.exists():
                # 加载普通JSON文件
                with open(file_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            data.append(json.loads(line))
            else:
                logging.warning(f"文件不存在: {file_path}")

        except Exception as e:
            logging.error(f"加载数据失败: {e}")

        logging.info(f"加载数据: {symbol} | {date_str} | 条数: {len(data)}")
        return data

    @staticmethod
    def load_date_range(symbol: str, start_date: str, end_date: str,
                        base_dir: str = "./kline_data") -> List[Dict]:
        """加载日期范围内的数据"""
        all_data = []
        current_date = datetime.strptime(start_date, "%Y-%m-%d")
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")

        while current_date <= end_date_obj:
            date_str = current_date.strftime("%Y-%m-%d")
            daily_data = BacktestDataLoader.load_kline_data(symbol, date_str, base_dir)
            all_data.extend(daily_data)
            current_date += timedelta(days=1)

        # 按时间排序
        all_data.sort(key=lambda x: x['open_time'])

        logging.info(f"加载日期范围数据: {symbol} | {start_date} 到 {end_date} | 总条数: {len(all_data)}")
        return all_data
