"""International display and authenticated owner-boundary regressions."""
import ast
import logging
import sqlite3
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from unittest.mock import patch

import jwt
from flask import Flask, jsonify, request

from user_trade_reporting import get_user_confirmed_history, get_user_access_status


class Ledger:
    def __init__(self, path):
        self.path = path

    def _get_connection(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn


class InternationalHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(str(Path(self.tmp.name) / 'ledger.db'))
        with self.ledger._get_connection() as conn:
            conn.executescript('''
                CREATE TABLE completed_trades (
                    id INTEGER PRIMARY KEY, user_id TEXT, position_id TEXT,
                    exit_reason TEXT, symbol TEXT, side TEXT, entry_price REAL,
                    exit_price REAL, quantity REAL, entry_fee REAL, exit_fee REAL,
                    total_fees REAL, gross_profit REAL, net_profit REAL,
                    entry_time TEXT, exit_time TEXT);
                CREATE TABLE trade_ledger (user_id TEXT, position_id TEXT,
                    action TEXT, order_id TEXT, notes TEXT);
            ''')
        self.add('british-user', 'one', broker='kraken')
        self.add('japanese-user', 'two', broker='okx')
        self.add('british-user', 'manual', reason='manual')

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, owner, position, broker='kraken', reason='canonical_confirmed_fill'):
        with self.ledger._get_connection() as conn:
            conn.execute('INSERT INTO completed_trades VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                         (owner, position, reason, 'BTC-EUR', 'long', 100, 110, 1,
                          1, 1, 2, 10, 8, '2026-07-01T12:00:00', '2026-07-01T13:00:00'))
            conn.execute('INSERT INTO trade_ledger VALUES (?,?,?,?,?)',
                         (owner, position, 'CLOSE', 'order-' + position, 'fill; broker=' + broker + '; confirmed=true'))

    def test_private_confirmed_closes_and_local_time(self):
        report = get_user_confirmed_history(self.ledger, user_id='british-user', timezone_name='Europe/London')
        self.assertEqual(report['count'], 1)
        trade = report['trades'][0]
        self.assertEqual(trade['position_id'], 'one')
        self.assertEqual(trade['exit_time_local'], '2026-07-01T14:00:00+01:00')
        self.assertEqual(trade['exit_time_utc'], '2026-07-01T13:00:00+00:00')
        self.assertEqual(trade['price_currency'], 'EUR')
        self.assertIsNone(trade['pnl_currency'])
        self.assertFalse(trade['fx_conversion_verified'])
        self.assertNotIn('notes', trade)

    def test_asian_user_sees_only_own_records(self):
        result = get_user_confirmed_history(self.ledger, user_id='japanese-user', timezone_name='Asia/Tokyo')
        self.assertEqual(result['trades'][0]['broker'], 'okx')
        self.assertEqual(result['trades'][0]['exit_time_local'], '2026-07-01T22:00:00+09:00')

    def test_missing_or_ambiguous_close_proof_is_excluded(self):
        with self.ledger._get_connection() as conn:
            conn.execute('INSERT INTO trade_ledger VALUES (?,?,?,?,?)',
                         ('british-user', 'one', 'CLOSE', 'other-order', 'fill; broker=okx; confirmed=true'))
        result = get_user_confirmed_history(self.ledger, user_id='british-user')
        self.assertEqual(result['count'], 0)
        self.assertEqual(result['excluded_unverified_rows'], 1)

    def test_invalid_fee_updates_do_not_appear_as_confirmed_pnl(self):
        with self.ledger._get_connection() as conn:
            conn.execute("UPDATE completed_trades SET net_profit=100 WHERE position_id='one'")
        self.assertEqual(get_user_confirmed_history(self.ledger, user_id='british-user')['count'], 0)

    def test_unverified_rows_advance_pagination(self):
        self.add('british-user', 'newer')
        result = get_user_confirmed_history(self.ledger, user_id='british-user', limit=1)
        self.assertTrue(result['has_more'])
        second = get_user_confirmed_history(self.ledger, user_id='british-user', limit=1, offset=result['next_offset'])
        self.assertFalse(second['has_more'])
        self.assertNotEqual(result['trades'][0]['position_id'], second['trades'][0]['position_id'])

    def test_identity_pagination_broker_and_timezone_fail_closed(self):
        cases = [{'user_id': ''}, {'user_id': 'platform'}, {'limit': 201}, {'offset': -1},
                 {'timezone_name': 'Bad/Zone'}, {'broker': "kraken' OR 1=1"}]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                get_user_confirmed_history(self.ledger, **({'user_id': 'british-user'} | kwargs))

    def test_entitlement_is_not_international_execution_proof(self):
        module = types.ModuleType('user_live_trading_access')
        module.evaluate_live_trading_access = lambda uid: types.SimpleNamespace(
            allowed=True, blocker='none', brokers=('kraken',))
        with patch.dict(sys.modules, {'user_live_trading_access': module}):
            result = get_user_access_status('british-user')
        self.assertTrue(result['entitlement_allowed'])
        self.assertFalse(result['trading_enabled'])
        self.assertFalse(result['country_eligibility_verified'])

    def test_actual_api_routes_enforce_auth_and_identity(self):
        # Compile the actual route/auth functions without starting any production
        # managers or importing the trading package. No route is reimplemented.
        for filename in ('api_server.py', 'gateway.py'):
            with self.subTest(filename=filename):
                app = Flask(filename)
                app.config['SECRET_KEY'] = 'test-signing-value-not-for-production-123456'  # pragma: allowlist secret
                source = ast.parse((Path(__file__).resolve().parents[1] / filename).read_text())
                wanted = {'decode_jwt_token', 'require_auth', 'get_trade_history', 'get_trading_status'}
                nodes = [n for n in source.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
                env = dict(app=app, request=request, jsonify=jsonify, wraps=wraps, jwt=jwt,
                           logger=logging.getLogger('test'), Optional=__import__('typing').Optional,
                           Dict=__import__('typing').Dict, require_tos_accepted=lambda f: f)
                exec(compile(ast.Module(body=nodes, type_ignores=[]), filename, 'exec'), env)
                ledger_module = types.ModuleType('bot.trade_ledger_db')
                ledger_module.get_trade_ledger_db = lambda: self.ledger
                bot_module = types.ModuleType('bot')
                bot_module.__path__ = []
                token = jwt.encode({'user_id': 'british-user',
                                    'exp': datetime.now(timezone.utc) + timedelta(minutes=1)},
                                   app.config['SECRET_KEY'], algorithm='HS256')
                with patch.dict(sys.modules, {'bot': bot_module, 'bot.trade_ledger_db': ledger_module}):
                    client = app.test_client()
                    self.assertEqual(client.get('/api/trading/history').status_code, 401)
                    headers = {'Authorization': 'Bearer ' + token}
                    other = client.get('/api/trading/history?user_id=japanese-user', headers=headers)
                    self.assertEqual(other.status_code, 403)
                    response = client.get('/api/trading/history?timezone=Asia/Tokyo', headers=headers)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json['trades'][0]['position_id'], 'one')
                    self.assertEqual(client.get('/api/trading/history?limit=-1', headers=headers).status_code, 400)
                    with patch('user_trade_reporting.get_user_access_status', side_effect=RuntimeError):
                        response = client.get('/api/trading/status', headers=headers)
                    self.assertEqual(response.status_code, 503)
                    self.assertFalse(response.json['trading_enabled'])

    def test_mobile_status_requires_request_identity_and_never_invents_readiness(self):
        from flask import Blueprint
        from typing import Optional
        app = Flask('mobile-status')
        blueprint = Blueprint('mobile-status', __name__)
        path = Path(__file__).resolve().parents[1] / 'unified_mobile_api.py'
        source = ast.parse(path.read_text())
        wanted = {'_get_request_user_id', 'get_trading_status'}
        nodes = [n for n in source.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
        env = dict(unified_mobile_api=blueprint, request=request, jsonify=jsonify,
                   logger=logging.getLogger('test'), Optional=Optional)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), env)
        app.register_blueprint(blueprint)
        self.assertEqual(app.test_client().get('/trading/status').status_code, 401)
        with app.test_request_context('/trading/status?user_id=japanese-user'):
            request.user_id = 'british-user'
            self.assertEqual(env['get_trading_status']()[1], 403)
        with app.test_request_context('/trading/status'):
            request.user_id = 'british-user'
            with patch('user_trade_reporting.get_user_access_status', side_effect=RuntimeError):
                response, status = env['get_trading_status']()
            self.assertEqual(status, 503)
            self.assertFalse(response.json['trading_enabled'])


if __name__ == '__main__':
    unittest.main()
