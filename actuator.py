import asyncio
import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

from binance import AsyncClient, BinanceSocketManager

import loggerfactory
import mailsender
from balancesync import USDCBalanceSync
from datasaver import KlineDataSaver
from polymarkettrader import PolymarketTrader
import webredeemer

import os
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# 读取环境变量
# 代理配置
LOCAL_HTTPS_PROXY = os.environ.get("LOCAL_HTTPS_PROXY")

# pm信息
PM_PROXY_ADDRESS = os.environ.get("PM_PROXY_ADDRESS")
PM_PRIVATE_KEY = os.environ.get("PM_PRIVATE_KEY")
PM_BUILDER_API_KEY = os.environ.get("PM_BUILDER_API_KEY")
PM_BUILDER_SECRET = os.environ.get("PM_BUILDER_SECRET")
PM_BUILDER_PASSPHRASE = os.environ.get("PM_BUILDER_PASSPHRASE")
# 交易对信息
TRADE_PAIR_UP = os.environ.get("TRADE_PAIR_UP")
TRADE_PAIR_DOWN = os.environ.get("TRADE_PAIR_DOWN")
TRADE_PAIR_EXCHANGE = os.environ.get("TRADE_PAIR_EXCHANGE")

# 配置日志
LOGGING_LEVEL = os.environ.get("LOGGING_LEVEL", "INFO")
logger = loggerfactory.get_logger(logging.getLevelNamesMapping()[LOGGING_LEVEL])


@dataclass
class KlineData:
    """K线数据类"""
    symbol: str
    open_time: int
    close_time: int
    open_price: float
    close_price: float
    high: float
    low: float
    volume: float
    is_closed: bool

    @property
    def is_bullish(self) -> bool:
        """判断是否为阳线（收盘价高于开盘价）"""
        return self.close_price > self.open_price

    @property
    def is_bearish(self) -> bool:
        """判断是否为阴线（收盘价低于开盘价）"""
        return self.close_price < self.open_price

    @property
    def price_change(self) -> float:
        """价格变化百分比"""
        return ((self.close_price - self.open_price) / self.open_price) * 100 if self.open_price > 0 else 0


@dataclass
class TradingPairMonitor:
    """交易对监控器"""
    symbol: str
    klines: deque = field(default_factory=lambda: deque(maxlen=20))  # 存储最近20根K线
    current_kline: Optional[KlineData] = None

    def update_kline(self, kline_msg: dict) -> None:
        """更新K线数据"""
        k = kline_msg['k']

        kline_data = KlineData(
            symbol=self.symbol,
            open_time=k['t'],
            close_time=k['T'],
            open_price=float(k['o']),
            close_price=float(k['c']),
            high=float(k['h']),
            low=float(k['l']),
            volume=float(k['v']),
            is_closed=k['x']  # K线是否已闭合
        )

        # 如果是新K线开始
        if not self.current_kline or self.current_kline.open_time != kline_data.open_time:
            if self.current_kline and self.current_kline.is_closed:
                self.klines.append(self.current_kline)
            self.current_kline = kline_data
        else:
            # 更新当前K线
            self.current_kline = kline_data

        logger.debug(f"{self.symbol} K线更新: 开盘={kline_data.open_price}, 收盘={kline_data.close_price}, "
                     f"是否闭合={kline_data.is_closed}")


class PmTradingStrategy:
    """交易策略引擎"""

    def __init__(self, pm_trader: PolymarketTrader, balance_sync: Optional[USDCBalanceSync]):
        self.monitors: Dict[str, TradingPairMonitor] = {}
        self.entry_condition_active = False
        self.last_notification_time = 0
        self.notification_cooldown = 60 * 2  # 通知冷却时间（秒）
        self.pm_trader = pm_trader
        self.balance_sync = balance_sync

        # 初始化监控器
        symbols = [TRADE_PAIR_UP, TRADE_PAIR_DOWN, TRADE_PAIR_EXCHANGE]
        for symbol in symbols:
            self.monitors[symbol] = TradingPairMonitor(symbol=symbol)

    def update_data(self, symbol: str, kline_msg: dict) -> None:
        """更新交易对数据"""
        if symbol in self.monitors:
            self.monitors[symbol].update_kline(kline_msg)
            self._check_conditions()

    def _check_conditions(self) -> None:
        """检查所有交易条件"""

        # 确保有足够的历史数据
        for monitor in self.monitors.values():
            if len(monitor.klines) < 2:
                return

        # 获取各交易对数据
        up_pair = self.monitors[TRADE_PAIR_UP]
        down_pair = self.monitors[TRADE_PAIR_DOWN]
        exchange_pair = self.monitors[TRADE_PAIR_EXCHANGE]

        # 检查入场条件（条件2）
        if self._check_entry_conditions(up_pair, down_pair, exchange_pair):
            logger.info("🎯 入场位置生效！等待下单信号")
            if not self.entry_condition_active:
                self.entry_condition_active = True

        # 检查出场条件（条件3）
        elif self._check_exit_conditions(up_pair, down_pair, exchange_pair):
            logger.info("🤮 下单位置生效，入场条件失效")
            if self.entry_condition_active:
                self.entry_condition_active = False

        # 检查触发通知条件（条件4）
        if self.entry_condition_active:
            self._check_notification_condition(exchange_pair)

    def _check_entry_conditions(self, up_pair: TradingPairMonitor,
                                down_pair: TradingPairMonitor,
                                exchange_pair: TradingPairMonitor) -> bool:
        """检查入场条件"""
        if len(exchange_pair.klines) < 2:
            return False

        # 获取最近两根K线
        exchange_pair_kline1 = list(exchange_pair.klines)[-1]  # 上一个周期
        exchange_pair_kline2 = list(exchange_pair.klines)[-2]  # 上上个周期

        # 条件1: XRP/BTC连续两个周期上涨
        if not (exchange_pair_kline2.is_bullish and exchange_pair_kline1.is_bullish):
            return False

        # 条件2: BTC/USDC上一个周期阴线
        if len(up_pair.klines) < 1:
            return False
        up_pair_last = list(up_pair.klines)[-1]
        if not up_pair_last.is_bearish:
            return False

        # 条件3: XRP/USDC上一个周期阳线
        if len(down_pair.klines) < 1:
            return False
        down_pair_last = list(down_pair.klines)[-1]
        if not down_pair_last.is_bullish:
            return False

        return True

    def _check_exit_conditions(self, up_pair: TradingPairMonitor,
                               down_pair: TradingPairMonitor,
                               exchange_pair: TradingPairMonitor) -> bool:
        """检查出场条件"""
        if len(exchange_pair.klines) < 2:
            return False

        # 获取最近两根K线
        exchange_pair_kline1 = list(exchange_pair.klines)[-1]  # 上一个周期
        exchange_pair_kline2 = list(exchange_pair.klines)[-2]  # 上上个周期

        # 条件1: XRP/BTC连续两个周期下跌
        if not (exchange_pair_kline2.is_bearish and exchange_pair_kline1.is_bearish):
            return False

        # 条件2: BTC/USDC上一个周期阳线
        if len(up_pair.klines) < 1:
            return False
        up_pair_last = list(up_pair.klines)[-1]
        if not up_pair_last.is_bullish:
            return False

        # 条件3: XRP/USDC上一个周期阴线
        if len(down_pair.klines) < 1:
            return False
        down_pair_last = list(down_pair.klines)[-1]
        if not down_pair_last.is_bearish:
            return False

        return True

    def _check_notification_condition(self, exchange_pair: TradingPairMonitor) -> None:
        """检查通知触发条件"""
        current_time = time.time()

        # 检查冷却时间
        if current_time - self.last_notification_time < self.notification_cooldown:
            return

        # 需要至少两根K线
        if len(exchange_pair.klines) < 2:
            return

        # 条件1: XRP/BTC在上一个周期下跌
        exchange_pair_kline1 = list(exchange_pair.klines)[-1]

        if not exchange_pair_kline1.is_bearish:
            return

        # 条件2: 当前周期剩余2分钟且当前周期下跌
        if exchange_pair.current_kline:
            remaining_time = self._get_kline_remaining_time(exchange_pair.current_kline)
            if 0 <= remaining_time <= 120 and exchange_pair.current_kline.is_bearish:  # 剩余2分钟左右且当前下跌（考虑网络延迟）
                asyncio.create_task(self._trigger_buy_action())
                self.last_notification_time = current_time

    def _get_kline_remaining_time(self, kline: KlineData) -> int:
        """获取K线剩余时间（秒）"""
        current_timestamp = int(time.time() * 1000)
        remaining_ms = kline.close_time - current_timestamp
        return max(0, remaining_ms // 1000)

    async def _trigger_buy_action(self):
        """触发买入"""
        buy_size = 5

        if self.balance_sync.is_running():
            buy_size = math.floor(self.balance_sync.get_latest_balance() * 100) / 100
            buy_size = math.floor(buy_size)
            if buy_size < 5:
                # 尝试赎回持仓
                redeemable_positions = self.pm_trader.get_redeemable_positions()
                if len(redeemable_positions) > 0:
                    # TODO 受限Python的clob client未支持调用链上合约，尝试手动实现调用ctf合约链上abi无果（参考ctfredeemer.py），这里没实现代理钱包的支持 暂时改用网页触发赎回持仓
                    # await self.pm_trader.redeem(redeemable_positions)
                    webredeemer.redeemer_in_web()
                    buy_size = math.floor(await self.balance_sync.fetch_usdc_balance() * 100) / 100

            elif buy_size > 500:
                logger.error("⬆️ 余额达到500上限, 按500买入...")
                buy_size = 500

        order_args = [
            {"symbol": TRADE_PAIR_UP[:-4], "position": "up", "side": "BUY", "price": 0.5, "size": buy_size},
            {"symbol": TRADE_PAIR_DOWN[:-4], "position": "down", "side": "BUY", "price": 0.5, "size": buy_size}
        ]

        await self.pm_trader.submit_limit_orders(order_args)

        # 触发通知
        notification_msg = (
            f"🚨 PM买入交易触发！\n"
            f"条件满足：\n"
            f"1. 入场条件已生效\n"
            f"2. {TRADE_PAIR_EXCHANGE}连续周期下跌\n"
            f"3. 当前15分钟周期剩余约2分钟\n"
            f"💰 余额: {buy_size} usdc"
            f"⌛️ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self._trigger_custom_notification(notification_msg)

    def _trigger_custom_notification(self, notification_msg) -> None:
        """触发自定义通知"""
        """发送通知（可扩展为邮件、短信等）"""
        logger.info(notification_msg)
        task = asyncio.create_task(mailsender.send_email_async("PM交易通知(稳稳的幸福版😊)", notification_msg))
        task.add_done_callback(self.handle_task_result)

    def handle_task_result(self, task: asyncio.Task):
        """用于处理任务结果的回调函数"""
        try:
            # 获取任务结果，这会重新抛出任务内的任何异常
            task.result()
            logging.info("后台任务执行成功")
        except asyncio.CancelledError:
            logging.warning("后台任务被取消")
        except Exception as e:
            # 在这里记录异常，确保错误不会消失
            logging.error(f"后台任务执行失败: {e}", exc_info=True)


class BinanceWebSocketMonitor:
    """币安WebSocket监控器"""

    def __init__(self, https_proxy: Optional[str] = None,
                 api_key: Optional[str] = None, api_secret: Optional[str] = None,
                 pm_proxy_address: Optional[str] = None, pm_private_key: Optional[str] = None,
                 builder_api_key: Optional[str] = None, builder_secret: Optional[str] = None,
                 builder_passphrase: Optional[str] = None):
        self.https_proxy = https_proxy
        self.api_key = api_key
        self.api_secret = api_secret
        self.pm_proxy_address = pm_proxy_address
        self.pm_private_key = pm_private_key
        # 初始化k线记录器
        self.data_saver = KlineDataSaver(base_dir="./kline_data")
        # 初始化余额同步
        self.balance_sync = USDCBalanceSync(wallet_address=self.pm_proxy_address,sync_interval=300)
        # 初始化pm客户端
        self.pm_trader = PolymarketTrader(proxy_address=self.pm_proxy_address, private_key=self.pm_private_key,
                                          builder_api_key=builder_api_key, builder_secret=builder_secret,
                                          builder_passphrase=builder_passphrase)
        # 初始化策略
        self.strategy = PmTradingStrategy(pm_trader=self.pm_trader, balance_sync=self.balance_sync)
        self.is_running = False

    async def start_monitoring(self) -> None:
        """启动监控"""
        self.is_running = True

        # 初始化客户端（公共数据不需要API密钥）
        client = await AsyncClient.create(https_proxy=self.https_proxy)
        bsm = BinanceSocketManager(client)

        # 订阅15分钟K线数据[citation:4]
        streams = [
            f"{TRADE_PAIR_UP}@kline_15m",
            f"{TRADE_PAIR_DOWN}@kline_15m",
            f"{TRADE_PAIR_EXCHANGE}@kline_15m"
        ]

        # 创建组合流连接[citation:4]
        conn_key = bsm.multiplex_socket(streams)

        logger.info("开始监控币安价格数据...")
        logger.info(f"监控的交易对: {', '.join(streams)}")

        async with conn_key as stream:
            while self.is_running:
                try:
                    msg = await stream.recv()

                    if msg and 'data' in msg:
                        data = msg['data']

                        # 解析K线数据[citation:4]
                        if data['e'] == 'kline':
                            symbol = data['s'].lower()
                            self.strategy.update_data(symbol, data)

                            # 记录重要价格变动
                            self._log_price_update(data)

                    # 短暂睡眠避免CPU过载
                    await asyncio.sleep(0.1)

                except asyncio.CancelledError:
                    logger.info("监控任务被取消")
                    break
                except Exception as e:
                    logger.error(f"处理WebSocket消息时出错: {e}")
                    await asyncio.sleep(5)  # 错误后等待5秒重试

        await client.close_connection()

    def _log_price_update(self, data: dict) -> None:
        """记录价格更新"""
        k = data['k']
        symbol = data['s']

        # 只记录K线闭合时的数据
        if k['x']:
            logger.info(
                f"{symbol} 15分钟K线闭合: "
                f"开盘={k['o']}, 收盘={k['c']}, "
                f"最高={k['h']}, 最低={k['l']}, "
                f"涨跌={'📈' if float(k['c']) > float(k['o']) else '📉'}"
            )
            # 写入kline数据到文件 用于历史数据回测
            self.data_saver.save_kline(symbol, k)

    def stop(self) -> None:
        """停止监控"""
        self.is_running = False
        logger.info("停止价格监控...")

    def destroy(self) -> None:
        self.data_saver.close()  # 关闭文件流
        self.balance_sync.stop()  # 停止余额同步


async def main():
    """主函数"""
    monitor = BinanceWebSocketMonitor(https_proxy=LOCAL_HTTPS_PROXY,
                                      pm_proxy_address=PM_PROXY_ADDRESS, pm_private_key=PM_PRIVATE_KEY,
                                      builder_api_key=PM_BUILDER_API_KEY, builder_secret=PM_BUILDER_SECRET,
                                      builder_passphrase=PM_BUILDER_PASSPHRASE)

    try:
        # 启动监控
        await monitor.start_monitoring()
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭...")
        monitor.stop()
    except Exception as e:
        logger.error(f"程序运行出错: {e}")
        raise e
    finally:
        monitor.destroy()
        logger.info("程序退出")


if __name__ == "__main__":
    # 运行程序
    asyncio.run(main())
