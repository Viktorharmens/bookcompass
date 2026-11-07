"""Tests voor de pure hulpfuncties van scraper (zonder netwerk). Draaien: python -m unittest discover -s tests"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper import _detect, _norm, _ol_title_query  # noqa: E402


class DetectTest(unittest.TestCase):
    def test_bare_olid(self):
        self.assertEqual(_detect('OL123W'), 'olid')
        self.assertEqual(_detect(' ol45M '), 'olid')

    def test_url(self):
        self.assertEqual(_detect('https://openlibrary.org/works/OL123W'), 'openlibrary')


class OlTitleQueryTest(unittest.TestCase):
    def test_field_query(self):
        self.assertEqual(_ol_title_query('Tirza', 'Grunberg'), 'title:(Tirza) author:(Grunberg)')
        # Aanhalingstekens en haakjes in de titel breken de zoeksyntax niet.
        q = _ol_title_query('Het "diner" (roman)')
        self.assertEqual(q.split(), ['title:(Het', 'diner', 'roman)'])


class NormTest(unittest.TestCase):
    def test_accents_and_punctuation(self):
        self.assertEqual(_norm('Één dag, één nacht!'), 'eendageennacht')


if __name__ == '__main__':
    unittest.main()
