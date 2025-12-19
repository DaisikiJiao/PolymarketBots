import asyncio
import logging
from web3 import Web3
from web3.exceptions import ContractLogicError
from typing import Optional

class USDCBalanceSync:
    """
    一个用于异步定时同步Polygon链上USDC余额的类。
    """

    # Polygon 主网 USDC 合约地址 (官方)
    USDC_CONTRACT_ADDRESS = Web3.to_checksum_address('0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174')
    # USDC ABI (精简版，仅包含balanceOf函数)[citation:1]
    USDC_ABI = '[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}]'

    def __init__(self,
                 wallet_address: str,
                 rpc_url: str = "https://polygon-rpc.com",
                 sync_interval: int = 600):
        """
        初始化余额同步器。

        Args:
            wallet_address: 要查询余额的钱包地址 (0x开头)。
            rpc_url: Polygon网络的RPC节点URL。默认使用公共节点，生产环境建议使用付费服务[citation:1]。
            sync_interval: 余额同步间隔时间（秒），默认600秒（10分钟）。
        """
        self.wallet_address = Web3.to_checksum_address(wallet_address)
        self.rpc_url = rpc_url
        self.sync_interval = sync_interval

        self.web3 = Web3(Web3.HTTPProvider(self.rpc_url))
        # 创建USDC合约实例[citation:1]
        self.usdc_contract = self.web3.eth.contract(
            address=self.USDC_CONTRACT_ADDRESS,
            abi=self.USDC_ABI
        )

        self._latest_balance: Optional[float] = None  # 最新余额 (USDC单位)
        self._sync_task: Optional[asyncio.Task] = None  # 后台同步任务
        self._is_running = False  # 控制任务循环的标志
        self._logger = logging.getLogger(__name__)
        self.start()

    def _init_usdc_balance(self) -> Optional[float]:
        """查询一次链上USDC余额[citation:4]。"""
        try:
            if not self.web3.is_connected():
                self._logger.warning("RPC连接断开，尝试重连...")
                # 简单重连逻辑
                self.web3 = Web3(Web3.HTTPProvider(self.rpc_url))
                if not self.web3.is_connected():
                    self._logger.error("无法重新连接到RPC节点。")
                    return None

            # 调用智能合约的balanceOf函数[citation:1]
            balance_wei = self.usdc_contract.functions.balanceOf(self.wallet_address).call()
            # USDC有6位小数，进行转换
            balance_usdc = balance_wei / 1_000_000
            return balance_usdc

        except ContractLogicError as e:
            self._logger.error(f"合约调用失败: {e}")
        except Exception as e:
            self._logger.error(f"查询余额时发生未知错误: {e}")
        return None

    async def fetch_usdc_balance(self) -> Optional[float]:
        """查询一次链上USDC余额[citation:4]。"""
        try:
            if not self.web3.is_connected():
                self._logger.warning("RPC连接断开，尝试重连...")
                # 简单重连逻辑
                self.web3 = Web3(Web3.HTTPProvider(self.rpc_url))
                if not self.web3.is_connected():
                    self._logger.error("无法重新连接到RPC节点。")
                    return None

            # 调用智能合约的balanceOf函数[citation:1]
            balance_wei = self.usdc_contract.functions.balanceOf(self.wallet_address).call()
            # USDC有6位小数，进行转换
            balance_usdc = balance_wei / 1_000_000
            return balance_usdc

        except ContractLogicError as e:
            self._logger.error(f"合约调用失败: {e}")
        except Exception as e:
            self._logger.error(f"查询余额时发生未知错误: {e}")
        return None

    async def _sync_loop(self):
        """执行定时同步的循环。"""
        self._logger.info(f"余额同步循环已启动，每 {self.sync_interval} 秒同步一次。")
        while self._is_running:
            balance = await self.fetch_usdc_balance()
            if balance is not None:
                self._latest_balance = balance
                self._logger.info(f"余额同步成功: {balance:,.2f} USDC")
            # 等待下一个同步周期
            await asyncio.sleep(self.sync_interval)

    def get_latest_balance(self) -> Optional[float]:
        """
        获取最近一次成功同步的余额。
        注意：这是快照值，可能不是实时余额。
        """
        return self._latest_balance

    def start(self):
        """启动后台余额同步任务。"""
        if self._is_running:
            self._logger.warning("同步任务已在运行。")
            return

        self._is_running = True
        # 立即执行一次同步，避免初始等待
        initial_balance = self._init_usdc_balance()
        if initial_balance is not None:
            self._latest_balance = initial_balance
            self._logger.info(f"初始余额同步: {initial_balance:,.2f} USDC")

        # 创建并运行后台任务[citation:5]
        self._sync_task = asyncio.create_task(self._sync_loop())
        self._logger.info("余额同步服务已启动。")

    def stop(self):
        """安全停止后台同步任务。"""
        self._logger.info("正在停止余额同步服务...")
        self._is_running = False
        if self._sync_task:
            self._sync_task.cancel()  # 取消任务
            self._sync_task = None
        self._logger.info("余额同步服务已停止。")

    def is_running(self) -> bool:
        """检查同步服务是否正在运行。"""
        return self._is_running