import asyncio
import json
import logging
from datetime import datetime, timedelta
from time import sleep

import requests
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType, PostOrdersArgs, BalanceAllowanceParams
from ctfredeemer import PolymarketCTFRedeemer


class PolymarketTrader:
    def __init__(self, private_key, proxy_address, builder_api_key, builder_secret, builder_passphrase):
        self.host = "https://clob.polymarket.com"
        self.chain_id = 137  # Polymarket 基于 Polygon 链
        self.private_key = private_key
        self.proxy_address = proxy_address
        self.client = None
        self._init_client()
        self.redeemer = PolymarketCTFRedeemer(
            relayer_url="https://relayer-v2.polymarket.com",
            private_key=private_key,
            builder_api_key=builder_api_key,
            builder_secret=builder_secret,
            builder_passphrase=builder_passphrase
        )

    def _init_client(self):
        """初始化API客户端[citation:1]"""
        try:
            # signature_type=1 代表通过Email/Magic登录[citation:1]
            self.client = ClobClient(
                host=self.host,
                key=self.private_key,
                chain_id=self.chain_id,
                signature_type=1,
                funder=self.proxy_address
            )
            api_creds = self.client.create_or_derive_api_creds()
            self.client.set_api_creds(api_creds)
            logging.info("Polymarket 客户端初始化成功")
        except Exception as e:
            logging.error(f"客户端初始化失败: {e}")
            raise

    async def submit_limit_orders(self, order_args):
        """创建并提交订单[citation:1]"""
        try:
            post_order_args = []
            for order_arg in order_args:
                token_id = ""
                token_ids = self.get_next_bet_token_ids(order_arg["symbol"])
                if order_arg["position"] == "up":
                    token_id = token_ids[0]
                if order_arg["position"] == "down":
                    token_id = token_ids[1]
                args = OrderArgs(
                    price=order_arg["price"],  # 价格，单位 USDc
                    size=order_arg["size"],  # 数量
                    side=order_arg["side"],  # BUY 或 SELL
                    token_id=token_id  # 市场对应的 Token ID
                )
                sleep(0.1)
                # 1. 签名订单
                signed_order = self.client.create_order(args)
                post_order_args.append(PostOrdersArgs(order=signed_order))

            # 2. 实际提交订单 (请谨慎操作)
            resp = self.client.post_orders(post_order_args)
            logging.info(f"订单提交成功: {resp}")
            return resp
        except Exception as e:
            logging.error(f"订单创建失败: {e}")
            return None

    def get_next_bet_token_ids(self, symbol):
        """获取下一个15min bet"""
        slug = f"{symbol}-updown-15m-{self.get_next_interval_timestamp()}"

        try:
            # 发送GET请求
            response = requests.get(url=f"https://gamma-api.polymarket.com/markets/slug/{slug}")
            # 检查HTTP状态码
            response.raise_for_status()

            # 尝试解析JSON响应 返回clobTokenIds
            try:
                return json.loads(response.json().get("clobTokenIds"))
            except json.JSONDecodeError as e:
                raise ValueError(f"JSON解析失败: {e}\n响应内容: {response.text[:200]}...")

        except requests.exceptions.Timeout:
            raise requests.exceptions.Timeout(f"请求超时...")
        except requests.exceptions.RequestException as e:
            raise requests.exceptions.RequestException(f"请求失败: {e}")

    def get_next_interval_timestamp(self, current_time=None, interval_minutes=15, return_as_milliseconds=False):
        """
         获取下一个间隔时间戳（更通用版本）

         Args:
             current_time: 当前时间，默认为当前系统时间
             interval_minutes: 时间间隔分钟数，默认为15分钟
             return_as_milliseconds: 是否返回毫秒时间戳

         Returns:
             int: 下一个间隔时间戳
         """
        # 如果没有提供当前时间，使用当前系统时间
        if current_time is None:
            current_time = datetime.now()

        # 计算到下一个间隔需要增加的分钟数
        minutes_to_add = interval_minutes - (current_time.minute % interval_minutes)

        # 如果已经是间隔的倍数，取下一个间隔
        if minutes_to_add == 0:
            minutes_to_add = interval_minutes

        # 计算下一个间隔时间
        next_interval = current_time + timedelta(minutes=minutes_to_add)
        next_interval = next_interval.replace(second=0, microsecond=0)

        # 转换为时间戳
        timestamp_seconds = next_interval.timestamp()

        return int(timestamp_seconds * 1000) if return_as_milliseconds else int(timestamp_seconds)

    def get_redeemable_positions(self):
        """获取当前持仓"""
        try:
            logging.info(f"🛢️ 获取当前持仓...")
            # 发送GET请求
            response = requests.get(url=f"https://data-api.polymarket.com/positions?user={self.proxy_address}")
            # 检查HTTP状态码
            response.raise_for_status()
            # 尝试解析JSON响应 返回
            try:
                return [position for _ in list(response.json()) if position and position["redeemable"]]
            except json.JSONDecodeError as e:
                raise ValueError(f"JSON解析失败: {e}\n响应内容: {response.text[:200]}...")

        except requests.exceptions.Timeout:
            raise requests.exceptions.Timeout(f"请求超时...")
        except requests.exceptions.RequestException as e:
            raise requests.exceptions.RequestException(f"请求失败: {e}")

    async def redeem(self, positions):
        """获取当前持仓"""
        try:
            logging.info(f"🎫 尝试赎回所有仓位...")
            for position in positions:
                result = await self.redeemer.redeem_positions(
                    collateral_token="0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",  # Polygon USDC
                    condition_id=position['conditionId'],
                    index_sets=[position['outcomeIndex']],  # 赎回YES or NO
                    parent_collection_id="0x0000000000000000000000000000000000000000000000000000000000000000"
                )

                if result["success"]:
                    logging.info(f"\n🎉 赎回成功！交易详情: {result['explorer_url']}")

                    # 等待交易确认
                    logging.info("等待交易确认...")
                    status = await self.redeemer.get_transaction_status(result["transaction_hash"])
                    logging.info(f"最终状态: {status}")
                else:
                    logging.info(f"赎回失败: {result.get('error')}")

        except requests.exceptions.Timeout:
            raise requests.exceptions.Timeout(f"请求超时...")
        except requests.exceptions.RequestException as e:
            raise requests.exceptions.RequestException(f"请求失败: {e}")


