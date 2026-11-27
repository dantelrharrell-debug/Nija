"""Bounded synthetic compatibility and denial-of-service regression checks."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest


class SelectorSecurityTests(unittest.TestCase):
    """Run potentially expensive selectors in independently bounded children."""

    def check_selector(self, markup: str, selector: str, expected: int | None) -> None:
        """Ensure known selectors preserve semantics within a process timeout."""
        program = (
            'import json,sys; from bs4 import BeautifulSoup; '
            'markup,selector,expected=json.loads(sys.stdin.read()); '
            'from soupsieve.util import SelectorSyntaxError\n'
            'try:\n'
            ' matches=BeautifulSoup(markup,"html.parser").select(selector)\n'
            'except SelectorSyntaxError:\n'
            ' assert expected is None\n'
            'else:\n'
            ' assert expected is not None and len(matches)==expected\n'
        )
        subprocess.run(
            [sys.executable, '-c', program],
            input=json.dumps([markup, selector, expected]), text=True,
            capture_output=True, timeout=5, check=True,
        )

    def test_deep_descendant_nonmatch_is_bounded(self) -> None:
        """The advisory's ordinary descendant selector cannot occupy a worker."""
        self.check_selector('<div>' * 200, 'section div div div', 0)

    def test_complex_has_is_refused_within_bound(self) -> None:
        """The patched default rejects the expensive complex :has syntax."""
        self.check_selector('<div>' + '<a></a>' * 8000 + '</div>', 'div:has(a ~ b)', None)

    def test_beautifulsoup_selector_results_remain_compatible(self) -> None:
        """A supported child-relative :has selector retains its result."""
        self.check_selector('<section><div><a></a><b></b></div></section>', 'section div:has(> a)', 1)


if __name__ == '__main__':
    unittest.main()
