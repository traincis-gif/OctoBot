#  Drakkar-Software OctoBot-Tentacles
#  Copyright (c) Drakkar-Software, All rights reserved.
#
#  This library is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3.0 of the License, or (at your option) any later version.
#
#  This library is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public
#  License along with this library.
import decimal
import typing

import octobot_commons.constants as commons_constants
import octobot_trading.exchanges as exchanges
import octobot_trading.enums as trading_enums
import octobot_trading.exchanges.connectors.ccxt.constants as ccxt_constants
import octobot_trading.exchanges.connectors.ccxt.enums as ccxt_enums
import octobot_trading.constants as constants


class ParadexConnector(exchanges.CCXTConnector):

    def _client_factory(
        self,
        force_unauth,
        keys_adapter: typing.Callable[
            [exchanges.ExchangeCredentialsData], exchanges.ExchangeCredentialsData
        ] = None,
    ) -> tuple:
        return super()._client_factory(force_unauth, keys_adapter=self._keys_adapter)

    def _keys_adapter(
        self, creds: exchanges.ExchangeCredentialsData
    ) -> exchanges.ExchangeCredentialsData:
        # Paradex uses Starknet: api_key as account address, secret as private key
        creds.wallet_address = creds.api_key
        creds.private_key = creds.secret
        creds.api_key = creds.secret = None
        return creds


class Paradex(exchanges.RestExchange):
    DESCRIPTION = ""
    DEFAULT_CONNECTOR_CLASS = ParadexConnector

    FIX_MARKET_STATUS = True
    REQUIRE_ORDER_FEES_FROM_TRADES = True

    # Paradex is futures-only (perps on Starknet)
    MARK_PRICE_IN_TICKER = True
    FUNDING_IN_TICKER = True
    REQUIRES_SYMBOL_FOR_EMPTY_POSITION = True

    # Paradex supports cross margin only
    SUPPORTS_SET_MARGIN_TYPE = False

    SUPPORTED_ELEMENTS = {
        trading_enums.ExchangeTypes.FUTURE.value: {
            trading_enums.ExchangeSupportedElements.UNSUPPORTED_ORDERS.value: [
                trading_enums.TraderOrderType.STOP_LOSS_LIMIT,
                trading_enums.TraderOrderType.TAKE_PROFIT,
                trading_enums.TraderOrderType.TAKE_PROFIT_LIMIT,
                trading_enums.TraderOrderType.TRAILING_STOP,
                trading_enums.TraderOrderType.TRAILING_STOP_LIMIT,
            ],
            trading_enums.ExchangeSupportedElements.SUPPORTED_BUNDLED_ORDERS.value: {},
        },
    }

    @classmethod
    def get_name(cls):
        return 'paradex'

    @classmethod
    def get_supported_exchange_types(cls) -> list:
        return [
            trading_enums.ExchangeTypes.FUTURE,
        ]

    def get_adapter_class(self):
        return ParadexCCXTAdapter

    def get_additional_connector_config(self):
        return {
            ccxt_constants.CCXT_OPTIONS: {
                "fetchMarkets": {
                    "types": ["swap"],
                }
            }
        }

    def get_order_additional_params(self, order) -> dict:
        params = {}
        if self.exchange_manager.is_future:
            params["reduceOnly"] = order.reduce_only
        return params


class ParadexCCXTAdapter(exchanges.CCXTAdapter):

    PARADEX_DEFAULT_FUNDING_TIME = 8 * commons_constants.HOURS_TO_SECONDS

    def fix_ticker(self, raw, **kwargs):
        fixed = super().fix_ticker(raw, **kwargs)
        fixed[trading_enums.ExchangeConstantsTickersColumns.TIMESTAMP.value] = (
            fixed.get(trading_enums.ExchangeConstantsTickersColumns.TIMESTAMP.value)
            or self.connector.client.seconds()
        )
        return fixed

    def fix_market_status(self, raw, remove_price_limits=False, **kwargs):
        fixed = super().fix_market_status(
            raw, remove_price_limits=remove_price_limits, **kwargs
        )
        return fixed

    def parse_position(self, fixed, **kwargs):
        try:
            size = decimal.Decimal(
                str(fixed.get(ccxt_enums.ExchangePositionCCXTColumns.CONTRACTS.value, 0))
            )
            symbol = self.connector.get_pair_from_exchange(
                fixed[ccxt_enums.ExchangePositionCCXTColumns.SYMBOL.value]
            )
            original_side = fixed.get(ccxt_enums.ExchangePositionCCXTColumns.SIDE.value)

            unrealized_pnl = self.safe_decimal(
                fixed,
                ccxt_enums.ExchangePositionCCXTColumns.UNREALISED_PNL.value,
                constants.ZERO,
            )
            liquidation_price = self.safe_decimal(
                fixed,
                ccxt_enums.ExchangePositionCCXTColumns.LIQUIDATION_PRICE.value,
                constants.ZERO,
            )
            entry_price = self.safe_decimal(
                fixed,
                ccxt_enums.ExchangePositionCCXTColumns.ENTRY_PRICE.value,
                constants.ZERO,
            )

            return {
                trading_enums.ExchangeConstantsPositionColumns.SYMBOL.value: symbol,
                trading_enums.ExchangeConstantsPositionColumns.TIMESTAMP.value: self.connector.client.safe_value(
                    fixed, ccxt_enums.ExchangePositionCCXTColumns.TIMESTAMP.value, 0
                ),
                trading_enums.ExchangeConstantsPositionColumns.SIDE.value: trading_enums.PositionSide.BOTH,
                trading_enums.ExchangeConstantsPositionColumns.MARGIN_TYPE.value: trading_enums.MarginType.CROSS,
                trading_enums.ExchangeConstantsPositionColumns.SIZE.value: (
                    size
                    if original_side == trading_enums.PositionSide.LONG.value
                    else -size
                ),
                trading_enums.ExchangeConstantsPositionColumns.INITIAL_MARGIN.value: self.safe_decimal(
                    fixed,
                    ccxt_enums.ExchangePositionCCXTColumns.INITIAL_MARGIN.value,
                    constants.ZERO,
                ),
                trading_enums.ExchangeConstantsPositionColumns.NOTIONAL.value: self.safe_decimal(
                    fixed,
                    ccxt_enums.ExchangePositionCCXTColumns.NOTIONAL.value,
                    constants.ZERO,
                ),
                trading_enums.ExchangeConstantsPositionColumns.LEVERAGE.value: self.safe_decimal(
                    fixed,
                    ccxt_enums.ExchangePositionCCXTColumns.LEVERAGE.value,
                    constants.ONE,
                ),
                trading_enums.ExchangeConstantsPositionColumns.UNREALIZED_PNL.value: unrealized_pnl,
                trading_enums.ExchangeConstantsPositionColumns.REALISED_PNL.value: self.safe_decimal(
                    fixed,
                    ccxt_enums.ExchangePositionCCXTColumns.REALISED_PNL.value,
                    constants.ZERO,
                ),
                trading_enums.ExchangeConstantsPositionColumns.LIQUIDATION_PRICE.value: liquidation_price,
                trading_enums.ExchangeConstantsPositionColumns.ENTRY_PRICE.value: entry_price,
                trading_enums.ExchangeConstantsPositionColumns.CONTRACT_TYPE.value: self.connector.exchange_manager.exchange.get_contract_type(
                    symbol
                ),
                trading_enums.ExchangeConstantsPositionColumns.POSITION_MODE.value: trading_enums.PositionMode.ONE_WAY,
            }
        except KeyError as e:
            self.logger.error(f"Fail to parse position dict ({e})")
        return fixed

    def parse_funding_rate(self, fixed, from_ticker=False, **kwargs):
        funding_dict = super().parse_funding_rate(
            fixed, from_ticker=from_ticker, **kwargs
        )
        if from_ticker:
            if ccxt_constants.CCXT_INFO not in fixed:
                return {}
            funding_dict = fixed[ccxt_constants.CCXT_INFO]
            funding_next_timestamp = self.get_uniformized_timestamp(
                float(
                    funding_dict.get(
                        ccxt_enums.ExchangeFundingCCXTColumns.NEXT_FUNDING_TIME.value, 0
                    )
                )
            )
            funding_rate = decimal.Decimal(
                str(
                    funding_dict.get(
                        ccxt_enums.ExchangeFundingCCXTColumns.FUNDING_RATE.value,
                        constants.NaN,
                    )
                )
            )
            funding_dict.update(
                {
                    trading_enums.ExchangeConstantsFundingColumns.LAST_FUNDING_TIME.value: max(
                        funding_next_timestamp - self.PARADEX_DEFAULT_FUNDING_TIME, 0
                    ),
                    trading_enums.ExchangeConstantsFundingColumns.FUNDING_RATE.value: funding_rate,
                    trading_enums.ExchangeConstantsFundingColumns.NEXT_FUNDING_TIME.value: funding_next_timestamp,
                    trading_enums.ExchangeConstantsFundingColumns.PREDICTED_FUNDING_RATE.value: funding_rate,
                }
            )
        else:
            funding_next_timestamp = float(
                funding_dict.get(
                    trading_enums.ExchangeConstantsFundingColumns.NEXT_FUNDING_TIME.value,
                    0,
                )
            )
            funding_dict.update(
                {
                    trading_enums.ExchangeConstantsFundingColumns.LAST_FUNDING_TIME.value: max(
                        funding_next_timestamp - self.PARADEX_DEFAULT_FUNDING_TIME, 0
                    ),
                }
            )
        return funding_dict

    def parse_mark_price(self, fixed, from_ticker=False, **kwargs) -> dict:
        if from_ticker and ccxt_constants.CCXT_INFO in fixed:
            try:
                return {
                    trading_enums.ExchangeConstantsMarkPriceColumns.MARK_PRICE.value: fixed[
                        ccxt_constants.CCXT_INFO
                    ][trading_enums.ExchangeConstantsMarkPriceColumns.MARK_PRICE.value]
                }
            except KeyError:
                pass
        return {
            trading_enums.ExchangeConstantsMarkPriceColumns.MARK_PRICE.value: decimal.Decimal(
                str(
                    fixed.get(
                        trading_enums.ExchangeConstantsTickersColumns.CLOSE.value, 0
                    )
                )
            )
        }
