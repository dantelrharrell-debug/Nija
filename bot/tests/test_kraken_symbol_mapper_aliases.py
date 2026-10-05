"""Verify Bitcoin aliases only adopt pairs present in Kraken API discovery."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bot.kraken_symbol_mapper import KrakenSymbolMapper


class PairFrame:
    """Minimal DataFrame-shaped public AssetPairs response."""

    def __init__(self, rows):
        self.rows = rows

    def iterrows(self):
        return iter(self.rows)


class KrakenSymbolMapperAliasTests(unittest.TestCase):
    def mapper(self, rows):
        with patch.object(KrakenSymbolMapper, '_load_static_mappings'):
            mapper = KrakenSymbolMapper()
        api = SimpleNamespace(get_tradable_asset_pairs=lambda: PairFrame(rows))
        with patch.object(mapper, '_update_static_mappings'):
            mapper.initialize_from_api(api)
        return mapper

    def test_api_bitcoin_pair_validates_both_spellings_and_exact_native_id(self):
        mapper = self.mapper([('XXBTZUSD', {'wsname': 'XBT/USD'})])
        for symbol in ('BTC-USD', 'XBT-USD'):
            self.assertTrue(mapper.is_available(symbol))
            self.assertEqual(mapper.to_kraken_symbol(symbol), 'XXBTZUSD')
        self.assertEqual(mapper.to_standard_symbol('XXBTZUSD'), 'BTC-USD')

    def test_alias_does_not_invent_quote_currency_or_unobserved_bitcoin_pair(self):
        mapper = self.mapper([('XETHZUSD', {'wsname': 'ETH/USD'})])
        mapper._static_map['BTC-USD'] = 'XXBTZUSD'
        self.assertFalse(mapper.is_available('BTC-USD'))
        self.assertFalse(mapper.is_available('XBT-USD'))
        self.assertFalse(mapper.is_available('BTC-USDT'))
        self.assertTrue(mapper.is_available('ETH-USD'))

    def test_each_discovered_quote_keeps_its_exchange_pair_id(self):
        mapper = self.mapper([
            ('XXBTZUSD', {'wsname': 'XBT/USD'}),
            ('XBTUSDT', {'wsname': 'XBT/USDT'}),
        ])
        self.assertEqual(mapper.to_kraken_symbol('BTC-USDT'), 'XBTUSDT')
        self.assertTrue(mapper.is_available('BTC-USDT'))
        self.assertFalse(mapper.is_available('BTC-EUR'))

    def test_other_asset_names_are_not_prefix_rewritten(self):
        mapper = self.mapper([('XBTFOOUSD', {'wsname': 'XBTFOO/USD'})])
        self.assertTrue(mapper.is_available('XBTFOO-USD'))
        self.assertFalse(mapper.is_available('BTCFOO-USD'))


if __name__ == '__main__':
    unittest.main()
