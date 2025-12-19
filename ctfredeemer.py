import os
import logging
from typing import List, Optional
from eth_typing import HexStr, ChecksumAddress
from web3 import Web3
from py_builder_relayer_client.client import RelayClient
from py_builder_relayer_client.models import OperationType, SafeTransaction
from py_builder_signing_sdk.config import BuilderConfig, BuilderApiKeyCreds


class PolymarketCTFRedeemer:
    """
    使用Polymarket官方Relayer客户端赎回CTF仓位
    完全基于官方示例实现
    """

    # CTF合约地址 (Polygon主网)
    CTF_ADDRESS = Web3.to_checksum_address("0x4D97DCd97eC945f40cF65F87097ACe5EA0476045")

    # CTF合约ABI片段 (仅包含redeemPositions函数)
    CTF_ABI = [
        {
            "inputs": [
                {"internalType": "address", "name": "collateralToken", "type": "address"},
                {"internalType": "bytes32", "name": "parentCollectionId", "type": "bytes32"},
                {"internalType": "bytes32", "name": "conditionId", "type": "bytes32"},
                {"internalType": "uint256[]", "name": "indexSets", "type": "uint256[]"}
            ],
            "name": "redeemPositions",
            "outputs": [],
            "stateMutability": "nonpayable",
            "type": "function"
        }
    ]

    def __init__(
            self,
            relayer_url: Optional[str] = None,
            private_key: Optional[str] = None,
            builder_api_key: Optional[str] = None,
            builder_secret: Optional[str] = None,
            builder_passphrase: Optional[str] = None
    ):
        """
        初始化Relayer客户端

        Args:
            relayer_url: Relayer服务URL，默认从环境变量读取
            private_key: 钱包私钥，默认从环境变量读取
            builder_api_key: Builder API密钥，默认从环境变量读取
            builder_secret: Builder API密钥，默认从环境变量读取
            builder_passphrase: Builder API密码，默认从环境变量读取
        """
        # 从环境变量读取配置（优先使用参数传入的值）
        self.relayer_url = relayer_url or os.getenv("POLYMARKET_RELAYER_URL")
        self.private_key = private_key or os.getenv("PRIVATE_KEY")
        self.builder_api_key = builder_api_key or os.getenv("BUILDER_API_KEY")
        self.builder_secret = builder_secret or os.getenv("BUILDER_SECRET")
        self.builder_passphrase = builder_passphrase or os.getenv("BUILDER_PASS_PHRASE")

        self.chain_id = 137  # Polygon主网
        self.w3 = Web3(Web3.HTTPProvider("https://polygon-rpc.com"))

        self._validate_config()
        self.client = self._init_relay_client()

    def _validate_config(self) -> None:
        """验证必要的配置参数"""
        required_vars = {
            "POLYMARKET_RELAYER_URL": self.relayer_url,
            "PRIVATE_KEY": self.private_key,
            "BUILDER_API_KEY": self.builder_api_key,
            "BUILDER_SECRET": self.builder_secret,
            "BUILDER_PASS_PHRASE": self.builder_passphrase
        }

        missing = [name for name, value in required_vars.items() if not value]
        if missing:
            raise ValueError(f"缺少必要的配置参数: {', '.join(missing)}")

        # 验证私钥格式
        if not self.private_key.startswith("0x"):
            self.private_key = "0x" + self.private_key
        if len(self.private_key) != 66:
            raise ValueError("私钥格式不正确，应为64个十六进制字符（可选的0x前缀）")

    def _init_relay_client(self) -> RelayClient:
        """初始化RelayClient"""
        # 配置Builder凭证
        builder_config = BuilderConfig(
            local_builder_creds=BuilderApiKeyCreds(
                key=self.builder_api_key,
                secret=self.builder_secret,
                passphrase=self.builder_passphrase,
            )
        )

        # 初始化RelayClient
        return RelayClient(
            relayer_url=self.relayer_url,
            chain_id=self.chain_id,
            private_key=self.private_key,
            builder_config=builder_config
        )

    async def redeem_positions(
            self,
            collateral_token: str,
            condition_id: str,
            index_sets: List[int],
            parent_collection_id: str = "0x0000000000000000000000000000000000000000000000000000000000000000"
    ) -> dict:
        """
        赎回CTF仓位

        Args:
            collateral_token: 抵押代币地址
            condition_id: 条件ID
            index_sets: 索引集合数组
            parent_collection_id: 父集合ID，默认为空

        Returns:
            包含交易哈希和状态的字典
        """
        try:
            # 1. 准备参数
            collateral_token_addr = Web3.to_checksum_address(collateral_token)
            condition_id_bytes = HexStr(condition_id)
            parent_collection_id_bytes = HexStr(parent_collection_id)

            logging.info(
                f"准备赎回仓位..."
                f"  CTF合约: {self.CTF_ADDRESS}"
                f"  抵押代币: {collateral_token_addr}"
                f"  条件ID: {condition_id}"
                f"  索引集合: {index_sets}"
            )

            # 2. 编码交易数据
            ctf_contract = self.w3.eth.contract(
                address=self.CTF_ADDRESS,
                abi=self.CTF_ABI
            )

            transaction_data = ctf_contract.encode_abi(
                abi_element_identifier="redeemPositions(address,bytes32,bytes32,uint256[])",
                args=[
                    collateral_token_addr,
                    parent_collection_id_bytes,
                    condition_id_bytes,
                    index_sets
                ]
            )

            # 3. 构造交易对象
            redeem_tx = SafeTransaction(
                to=self.CTF_ADDRESS,
                operation=OperationType.DelegateCall,
                data=transaction_data,
                value="0",
            )

            # 4. 通过Relayer执行交易
            logging.info("通过Relayer提交交易...")
            response = self.client.execute(
                transactions=[redeem_tx],
                metadata="Redeem position"
            )

            # 5. 等待交易结果
            result = response.wait()

            logging.info(f"✅ 赎回交易已提交！交易哈希: {result.transactionHash} 状态: {result.status}")

            return {
                "success": True,
                "transaction_hash": result.transactionHash,
                "status": result.status,
                "relayer_response": result,
                "explorer_url": f"https://polygonscan.com/tx/{result.transactionHash}"
            }

        except Exception as e:
            e.with_traceback()
            logging.error(f"❌ 赎回失败: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "collateral_token": collateral_token,
                "condition_id": condition_id
            }

    async def get_transaction_status(self, transaction_hash: str) -> dict:
        """获取交易状态"""
        try:
            receipt = self.w3.eth.wait_for_transaction_receipt(
                transaction_hash,
                timeout=120,
                poll_latency=2
            )

            status = "success" if receipt.status == 1 else "failed"

            return {
                "success": receipt.status == 1,
                "status": status,
                "block_number": receipt.blockNumber,
                "gas_used": receipt.gasUsed,
                "transaction_hash": transaction_hash
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "transaction_hash": transaction_hash
            }
