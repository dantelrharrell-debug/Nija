"""Import observation must not execute a lazy module's attribute loader."""
import ast
import logging
from functools import wraps
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest


class UniversalExitImportLookupTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / "universal_broker_exit_supervisor_patch.py"
        tree = ast.parse(source.read_text())
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == "_patch_module")
        self.registrations = []
        self.marker = "__test_exit_supervisor_patched__"
        namespace = {"Any": object, "wraps": wraps, "logger": logging.getLogger(__name__),
                     "_PATCHED": self.marker, "_MARKER": "test",
                     "_register_broker": self.registrations.append}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
        self.patch_module = namespace["_patch_module"]

    def test_lazy_module_attribute_loader_is_never_called(self):
        module = ModuleType("lazy_library")
        calls = []
        def lazy(name):
            calls.append(name)
            # A realistic lazy loader imports modules, re-entering the hook.
            return self.patch_module(module)
        module.__getattr__ = lazy
        self.assertFalse(self.patch_module(module))
        self.assertEqual(calls, [])

    def test_real_bound_class_keeps_registration_and_connect_result(self):
        class KrakenBroker:
            def __init__(self, value):
                self.value = value
            def connect(self, value):
                return value
        module = ModuleType("actual_broker")
        module.KrakenBroker = KrakenBroker
        def lazy(name):
            raise AssertionError("unbound attribute lookup: " + name)
        module.__getattr__ = lazy
        self.assertTrue(self.patch_module(module))
        patched_init, patched_connect = KrakenBroker.__init__, KrakenBroker.connect
        self.assertFalse(self.patch_module(module))
        self.assertIs(KrakenBroker.__init__, patched_init)
        self.assertIs(KrakenBroker.connect, patched_connect)
        broker = KrakenBroker(17)
        self.assertEqual(broker.value, 17)
        self.assertEqual(broker.connect("connected"), "connected")
        self.assertEqual(self.registrations, [broker, broker])

    def test_namespace_test_doubles_still_work_and_non_namespaces_are_ignored(self):
        self.assertFalse(self.patch_module(SimpleNamespace()))
        self.assertFalse(self.patch_module(None))
        self.assertFalse(self.patch_module(object()))


if __name__ == "__main__":
    unittest.main()
